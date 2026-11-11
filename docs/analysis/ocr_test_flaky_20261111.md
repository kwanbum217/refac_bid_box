# OCR 모델 부재 경고 시험 간헐 실패 분석 (2026-11-11)

## 대상

- 시험: `tests/test_document_extraction_ocr.py::test_missing_model_disables_ocr_once`
- 증상: 전량 시험 중 첫 요청이 `422` 로 끝나 `assert first.status_code == second.status_code == 200` 이 실패. 응답 문구는 문서 처리 시간 초과이며 단독 재실행은 매번 통과.

## 타임아웃이 걸리는 곳

| 위치 | 역할 |
| --- | --- |
| `src/app/api/v1/documents.py:44` | `EXTRACTION_TIMEOUT_SECONDS = 10.0` 운영 예산 |
| `src/app/api/v1/documents.py:204` | 추출을 `asyncio.to_thread` 로 넘김 |
| `src/app/api/v1/documents.py:210-213` | `asyncio.wait_for(asyncio.shield(runner), timeout=EXTRACTION_TIMEOUT_SECONDS)` |
| `src/app/api/v1/documents.py:222-228` | `TimeoutError` 를 422 로 변환 |

스레드는 강제 종료되지 않으므로 응답만 422 로 끝나고 추출 스레드는 계속 돕니다.

## 어느 요청이 느린가

계측용 임시 pytest 플러그인으로 `pdf_text.extract_page_texts`, `ocr._create_engine`, `ocr.verify_model_files`, `documents._extract` 를 감싸고 라우터의 `elapsed_ms` INFO 로그를 켜서 측정했습니다(플러그인은 커밋하지 않음).

| 실행 | 첫 요청 elapsed | 둘째 요청 elapsed | `_create_engine` | `verify_model_files` |
| --- | --- | --- | --- | --- |
| 5회 반복 | 221 ~ 1991 ms | 0.8 ~ 1.2 ms | 0.219 ~ 1.989 s | 0.000 s |
| 8프로세스 병렬 | 1991 ms (전부) | 1.0 ms | 1.989 s | 0.000 s |

- 첫 요청 비용은 전부 `src/app/services/document_extraction/ocr.py:89-101` 의 `_create_engine` 안에서 발생합니다. 모델 디렉터리가 비어 있어 `verify_model_files`(`ocr.py:92`)는 즉시 예외로 끝나므로, 시간은 그보다 앞선 `ocr.py:90` 의 `from rapidocr import ...`(onnxruntime·opencv 스택 import)가 차지합니다.
- `_create_engine` wall 1.99 s 대 CPU 0.33 s 로 약 83% 가 I/O 대기입니다. 이 대기는 페이지 캐시가 비고 디스크를 여러 프로세스가 함께 쓰는 전량 시험에서 커집니다.
- 둘째 요청이 빠른 이유는 첫 실패가 `_engine_unavailable = True`(`ocr.py:121`)를 세워 `ocr.py:116-117` 에서 곧바로 예외로 끝나기 때문입니다. 즉 시험의 두 요청 중 첫 요청만 느립니다.
- 모델 검사(`ocr.py:92`)가 import(`ocr.py:90`)보다 뒤라, 모델이 없는 경로도 import 비용을 먼저 냅니다.
- 계측 없이 load average 8.16 에서 1회 실행했을 때 호출 전체가 13.41 s 였고 첫 요청이 422, 둘째 요청이 200 이었습니다. 그 실행의 10초 초과분을 단계별로 쪼개지는 못했으므로, 초과분이 모두 import I/O 대기였다는 것은 추정입니다. 다만 첫 요청 비용의 위치와 I/O 대기 비중은 위 측정으로 확인했습니다.

## 수정과 이유

- `tests/conftest.py`: `relaxed_extraction_timeout` fixture 가 `documents.EXTRACTION_TIMEOUT_SECONDS` 를 시험 안에서만 60.0 으로 올립니다.
- `tests/test_document_extraction_ocr.py`: 실제 엔진 생성 경로를 지나는 두 시험(`test_missing_model_disables_ocr_once`, `test_mismatched_model_hash_disables_ocr`)에 이 fixture 를 붙였습니다. 실행 순서가 바뀌어 뒤 시험이 첫 엔진 생성 비용을 내도 같은 이유로 흔들리지 않게 합니다.
- 10초는 운영 요청 예산이고 이 시험의 대상은 "모델이 없으면 경고가 정확히 한 번"이라는 동작입니다. 단정 세 줄은 그대로 두었고, 제한 시간 동작 자체는 `test_ocr_timeout_is_422` 가 `EXTRACTION_TIMEOUT_SECONDS` 를 0.05 로 낮춰 따로 검증합니다. 운영 코드는 바꾸지 않았습니다.

## 부하 재현 결과

- 수정 전, load average 8.16: 같은 시험 1회 실행에서 첫 요청 422, 호출 13.41 s (실패 재현).
- 수정 후, 5회 연속 단독 실행: 5/5 통과.
- 수정 후, 8프로세스 병렬 실행: 8/8 통과, 첫 요청 1.99 s.
- 수정 후, `uv run pytest tests/test_document_extraction_ocr.py -q`: 전건 통과.
- 수정 후, 전량 시험 `uv run pytest tests/ -q -m 'not data_assets'`: 10704 passed, 41 skipped, 2 xfailed, 0 failed (460.92s). 시간 측정 시험도 이 실행에서 실패하지 않았습니다.
