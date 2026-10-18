# OCR 모델 부재 경고 시험 간헐 실패 분석

## 대상

- 시험: `tests/test_document_extraction_ocr.py::test_missing_model_disables_ocr_once`
- 증상: 전량 시험(`uv run pytest tests/ -q -m 'not data_assets'`) 병렬 실행 중 1건 간헐 실패, 단독 재실행 통과.

## 재현 시도

- `uv run pytest "tests/test_document_extraction_ocr.py::test_missing_model_disables_ocr_once" -q` 20회 반복: 0건 실패.
- `uv run pytest tests/test_document_extraction_ocr.py tests/test_document_extraction_hardening.py tests/test_document_extraction_parser.py tests/test_document_extraction_api.py -q` 5회 반복: 0건 실패.
- `uv run pytest tests/test_logging_config.py tests/test_document_extraction_ocr.py -q` 30회 반복: 0건 실패.
- `uv run pytest tests/ -q -m 'not data_assets'` 1회: 7958 passed, 50 skipped, 0 failed.
- 결정적 재현에는 실패했습니다. verdict 는 candidate 입니다.

## 원인 (코드 근거)

1. 프로세스 전역 상태 초기화 누락 (`src/app/services/document_extraction/ocr.py:58-60`).
   - `_engine`, `_engine_unavailable`, `_engine_lock` 는 모듈 전역입니다. `get_engine()` (ocr.py:104-127) 은 첫 실패 시 `_engine_unavailable = True` 를 세우고 경고 로그 1건을 남깁니다.
   - 기존 `_reset_ocr_engine` fixture (tests/test_document_extraction_ocr.py:139-149) 는 `_engine`, `_engine_unavailable` 만 되돌렸고, `ocr.get_engine` 자체는 되돌리지 않았습니다. 다른 시험(`_use_engine`)이 `monkeypatch.setattr(ocr, "get_engine", ...)` 로 대역을 심은 뒤 복구가 누락되면, 본 시험의 모델 부재 경로가 대역을 호출해 `status=unavailable` 로그 수가 달라질 수 있습니다.

2. 동시 처리 세마포어 미대기 (src/app/api/v1/documents.py:57).
   - `_EXTRACTION_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_EXTRACTIONS)` 는 프로세스 전역입니다. `test_ocr_timeout_is_422` 등이 남긴 느린 추출 스레드가 자리를 들고 있으면 본 시험의 요청이 spurious 503 을 받아 OCR 경로에 도달하지 못하고 로그 수가 달라질 수 있습니다.
   - 하드닝 시험 파일(test_document_extraction_hardening.py:153-176)은 `_await_free_extraction_slots` fixture 로 이 상태를 기다리지만, OCR 시험 파일에는 같은 fixture 가 없었습니다.

## 수정 근거

- `tests/test_document_extraction_ocr.py`: `_reset_ocr_engine` 이 `ocr.get_engine` 을 모듈 임포트 시점의 원본(`_ORIGINAL_OCR_GET_ENGINE`)으로 되돌리도록 보강.
- `tests/test_document_extraction_ocr.py`: 하드닝 파일과 동일한 `_await_free_extraction_slots` autouse fixture 를 추가해 느린 스레드가 자리 반납을 끝낸 뒤 시험을 시작.
- `tests/conftest.py`: 모든 시험에 `_reset_ocr_globals` autouse fixture 를 추가해 `_engine`, `_engine_unavailable` 를 시험마다 None/False 로 되돌임.
- 운영 코드(ocr.py)의 OCR 동작(모델 해시 검증, 경고 1회)은 변경하지 않았습니다. 시험의 단정(`len(unavailable) == 1`)도 느슨하게 바꾸지 않았습니다.
