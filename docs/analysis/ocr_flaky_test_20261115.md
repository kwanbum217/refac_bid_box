# OCR 모델 부재 경고 시험 간헐 실패 분석 (2026-11-15)

> **작성일**: 2026-11-15
> **대상 시험**: `tests/test_document_extraction_ocr.py::test_missing_model_disables_ocr_once`
> **수정 파일**: `tests/test_document_extraction_ocr.py` (시험 코드만, 운영 코드 무변경)
> **결론**: 요청 스레드 안에서 치르던 `rapidocr` 지연 import 가 원인이다. 모델 파일이 없어도 이 import 가 먼저 돌아 디스크에서 수백 ms 에서 수 초를 쓰고, 전량 시험이 디스크를 함께 쓰면 운영 예산을 넘겨 422 가 된다. 시험 파일 첫 시험 전에 같은 import 를 미리 치러 요청 제한 시간 밖으로 옮겼다.

---

## 1. 증상과 범위

- 2026-11-10 전량 시험에서 두 번 실패했습니다. 실패한 요청은 422(문서 처리 시간이 초과되었습니다)였고, 해당 시험 단독 재실행은 매번 통과했습니다.
  - 근거: `docs/handoff/handoff_20261110_session_close.md:68`, `docs/analysis/sajeong_stats_refresh_20261110.md:213`
- 같은 파일의 `test_mismatched_model_hash_disables_ocr` 도 실제 엔진 생성 경로를 지나 같은 비용을 냅니다.

---

## 2. 제한 시간이 걸리는 경로

| 위치 | 역할 |
| --- | --- |
| `src/app/api/v1/documents.py:44` | `EXTRACTION_TIMEOUT_SECONDS = 10.0` 운영 요청 예산 |
| `src/app/api/v1/documents.py:201-202` | 동시 처리 자리를 못 잡으면 503 |
| `src/app/api/v1/documents.py:204` | 추출을 `asyncio.to_thread(_extract_holding_slot, data)` 로 넘김 |
| `src/app/api/v1/documents.py:210-213` | `asyncio.wait_for(asyncio.shield(runner), timeout=EXTRACTION_TIMEOUT_SECONDS)` |
| `src/app/api/v1/documents.py:222-228` | `TimeoutError` 를 422 로 변환 |
| `src/app/services/document_extraction/ocr.py:89-101` | `_create_engine` |
| `src/app/services/document_extraction/ocr.py:90` | `from rapidocr import ModelType, OCRVersion, RapidOCR` (지연 import) |
| `src/app/services/document_extraction/ocr.py:92` | `verify_model_files` (모델 부재 판정) |
| `src/app/services/document_extraction/ocr.py:116-117` | 한 번 실패하면 이후 호출은 즉시 예외 |

`documents.py:212` 는 호출 시점에 모듈 전역을 읽으므로, 설정을 시험 안에서 바꾸면 실제 경로에 적용됩니다.

---

## 3. 원인 후보 판정

### 3.1 (기각) `relaxed_extraction_timeout` 이 실제 추출 경로를 덮지 못한다

- `documents.py:212` 의 `timeout=EXTRACTION_TIMEOUT_SECONDS` 는 함수 호출 시점의 모듈 전역 조회입니다. 라우터 정의 시점에 값이 고정되지 않습니다.
- 실측: 계측 훅에서 요청 처리 직전 `src.app.api.v1.documents.EXTRACTION_TIMEOUT_SECONDS` 를 읽은 값이 `60.0` 이었습니다(`tests/conftest.py:301` 의 monkeypatch 적용). 즉 덮지 못한다는 가설은 성립하지 않습니다.
- 같은 이유로, 이 시험에서 10초 예산 때문에 422 가 나는 경로는 현재 코드에 없습니다. 2026-11-11 커밋 `bbcc4a2c`(main 에 병합됨)가 이미 예산을 60초로 올려 두었고, 그 수정 뒤 2026-11-10 형태의 422 는 재현되지 않습니다.

### 3.2 (기각) 모듈 수준 상태가 앞선 시험과 공유된다

- `tests/test_document_extraction_ocr.py:153-157` 의 `_reset_ocr_engine` 이 `_engine` 과 `_engine_unavailable` 을 시험마다 되돌립니다.
- 같은 파일 :160-184 의 `_await_free_extraction_slots` 가 이전 시험의 느린 추출 스레드가 동시 처리 자리를 반납할 때까지 기다립니다.
- 실측: 요청 2회 중 두 번째 `get_engine` 호출은 0.0ms 로 즉시 끝났고(`ocr.py:116-117` 단락), `status=unavailable` 경고는 정확히 1건이었습니다. 단정 `assert len(unavailable) == 1` 과 `status == unrecognized` 는 그대로 성립합니다.

### 3.3 (확정) 요청 스레드 안에서 치르는 `rapidocr` 지연 import

- `ocr.py:89-101` 은 `verify_model_files`(`:92`)보다 **먼저** `rapidocr` 를 import 합니다(`:90`). 모델 파일이 없어 즉시 실패하는 경로에서도 이 import 비용을 냅니다.
- `rapidocr/__init__.py` 는 `_LAZY_IMPORTS` 와 모듈 `__getattr__` 로 `RapidOCR`(`.main`)을 지연 import 합니다. `RapidOCR` 을 가져올 때 onnxruntime·opencv 스택이 함께 올라오고, 이 비용이 디스크 I/O 에 크게 의존합니다.
- 요청 안에서 이 import 가 실제로 도는 것을 계측으로 확인했습니다. 요청 1회당 `get_engine` 소요:

| 조건 | 첫 요청 `get_engine` | 둘째 요청 `get_engine` | 비고 |
| --- | --- | --- | --- |
| 세션 첫 실행(페이지 캐시 차가움) | 시험 call 전체 6.82s | - | `--durations` 측정 |
| 페이지 캐시 따뜻함 | 311.3ms | 0.0ms | 계측 훅 |
| 페이지 캐시 따뜻함, 다른 실행 | 393.5ms | 0.0ms | 계측 훅 |
| 선행 기록, load average 8.16 | 1.99s (`_create_engine`) | 1.0ms | `docs/analysis/ocr_test_flaky_20261111.md:25-32` |
| 선행 기록, load average 8.16 | 호출 전체 13.41s → 422 | 200 | 같은 문서 :32 |

- 요청 안에서 수 초를 쓰는 작업은 이 import 하나뿐입니다. 모델 부재 판정(`verify_model_files`)은 파일 존재 확인에서 즉시 끝나고, 합성 이미지 PDF 의 텍스트 추출·파싱은 ms 규모입니다. 따라서 10초 초과는 이 import 에서만 발생할 수 있습니다.
- 60초로 완화한 뒤에도 이 비용은 여전히 요청 안에 있어, 디스크 경합이 커지면 같은 방식으로 예산을 넘길 수 있는 구조입니다. 예산을 더 키우는 것으로는 원인이 사라지지 않습니다.

---

## 4. 재현 근거와 재현하지 못한 부분

- 오늘 환경에서 422 자체는 재현하지 못했습니다. 이유는 두 가지입니다. (1) 2026-11-11 커밋 이후 예산이 60초라 10초 초과가 성립하지 않고, (2) 이 저장소의 페이지 캐시가 따뜻해 첫 import 가 0.3~0.4초로 끝났습니다. 페이지 캐시를 비우려면 관리자 권한이 필요해 수행하지 않았습니다.
- 대신 실패를 만든 비용의 위치와 크기를 계측으로 특정했습니다(3.3 표). 2026-11-10 기록의 422 는 그 비용이 요청 안에서 10초를 넘긴 결과와 일치합니다.
- 수정 전 반복·병렬 실행은 모두 통과했습니다(수정 전 기준선: 파일 단독 14 passed·1 skipped, 6 프로세스 병렬 6/6 통과). 즉 이 결함은 부하 조건에서만 드러나며, 단독 반복으로는 재현되지 않습니다.

---

## 5. 수정

`tests/test_document_extraction_ocr.py:134-150` 에 module 범위 autouse fixture `_preload_ocr_import` 를 추가했습니다.

- 시험 파일의 첫 시험이 시작되기 전에 `from rapidocr import ModelType, OCRVersion, RapidOCR` 를 한 번 실행합니다. `ocr.py:90` 과 같은 이름을 가져와야 `RapidOCR` 의 지연 import 까지 끝납니다.
- 이렇게 하면 요청 스레드의 `_create_engine` 은 이미 올라온 모듈을 참조한 뒤 `verify_model_files` 에서 즉시 실패합니다. 요청 안의 `get_engine` 비용이 393.5ms 에서 0.2ms 로 줄었습니다(3.3 표와 같은 계측).
- 패키지를 쓸 수 없는 환경에서는 예외를 삼킵니다. `ocr.py:118-125` 가 import 실패도 `OcrUnavailableError` 로 바꿔 같은 결과(경고 1건, `unrecognized`)를 내기 때문에, 시험 결과를 바꾸지 않습니다.
- 단정은 바꾸지 않았습니다: `first.status_code == second.status_code == 200`, `status == "unrecognized"` 두 건, `len(unavailable) == 1`.
- 운영 코드(`src/`), `tests/conftest.py`, 다른 시험 파일은 건드리지 않았습니다. 기존 `relaxed_extraction_timeout`(`tests/conftest.py:286-301`)은 다른 시험 파일과 공유되므로 그대로 두었습니다.
- 새 라이브러리를 추가하지 않았습니다. `rapidocr` 은 `pyproject.toml:45` 의 기존 의존성입니다.

---

## 6. 검증 기록

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_document_extraction_ocr.py -q` | 14 passed, 1 skipped |
| `uv run pytest "tests/test_document_extraction_ocr.py::test_missing_model_disables_ocr_once" -q` 10회 반복 | 0/10 실패 |
| 같은 파일 6 프로세스 병렬 실행 | 6/6 통과 (각 2.06~2.10s) |
| 예산을 운영값 10.0 으로 강제하고 계측(수정 후) | 첫 요청 `get_engine` 0.2ms, 14 passed 1 skipped |
| `uv run pytest tests/ -q -m 'not data_assets'` | 아래 별도 기록 |

전량 시험: `10909 passed, 41 skipped, 3 deselected, 2 xfailed, 0 failed` (307.37s). `-m 'not data_assets'` 로 제외한 3건은 이 실행에 포함되지 않았습니다. 실패 0건이므로 2026-11-10 형태의 간헐 실패는 이번 실행에서 재발하지 않았습니다.

---

## 7. 남은 위험과 후속

- 운영 코드는 첫 OCR 사용 시 여전히 요청 안에서 `rapidocr` 를 import 합니다(`ocr.py:90`). 운영 예산이 문제가 된다면 `verify_model_files` 를 import 앞으로 옮겨 모델이 없을 때 import 없이 실패하게 하는 편이 낫습니다. 이번 Task 는 시험 범위라 `src/` 를 고치지 않았습니다.
- `tests/conftest.py` 의 `relaxed_extraction_timeout` 은 이제 이 시험의 필수 방어가 아닙니다. 다른 시험 파일이 함께 쓰므로 이 Task 에서 정리하지 않았습니다.
