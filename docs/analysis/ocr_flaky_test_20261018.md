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

1. (검토 후 기각) 프로세스 전역 상태 초기화 누락 가설 (`src/app/services/document_extraction/ocr.py:58-60`).
   - `_engine`, `_engine_unavailable` 는 모듈 전역이고, `get_engine()` (ocr.py:104-127) 은 첫 실패 시 `_engine_unavailable = True` 를 세웁니다.
   - 처음에는 `ocr.get_engine` 자체가 다른 시험의 대역으로 남아 본 시험의 모델 부재 경로가 대역을 호출할 수 있다는 가설을 세웠으나, 저장소 어디에도 `ocr.get_engine` 에 대한 직접 대입이 없고 모든 대역 주입은 `monkeypatch.setattr(ocr, "get_engine", ...)` 로 이루어집니다. pytest monkeypatch 는 시험 종료 시 자동으로 원래 값을 복구하므로, 복구 누락 가설은 코드 근거가 없습니다. 따라서 이 원인은 기각했습니다.

2. 동시 처리 세마포어 미대기 (`src/app/api/v1/documents.py:57-58`, `_extract_holding_slot` at documents.py:128-137).
   - `_EXTRACTION_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_EXTRACTIONS)` (MAX_CONCURRENT_EXTRACTIONS=2, documents.py:45) 는 프로세스 전역입니다.
   - `extract_document` (documents.py:200) 은 자리가 없으면 503 으로 끝내고 OCR 경로에 도달하지 못합니다. `test_ocr_timeout_is_422` 등이 남긴 느린 추출 스레드가 자리를 들고 있으면 본 시험의 요청이 spurious 503 을 받아 `status=unavailable` 로그 수가 달라질 수 있습니다.
   - `_extract_holding_slot` (documents.py:128-137) 은 `_extract` 완료 후 finally 에서 `_EXTRACTION_SLOTS.release()` (documents.py:137) 로 자리를 반납합니다. 제한 시간을 넘긴 스레드는 계속 돌며 끝날 때만 반납합니다.
   - 하드닝 시험 파일 (tests/test_document_extraction_hardening.py:153-175) 의 `_await_free_extraction_slots` autouse fixture 가 시작 시점에 두 자리가 모두 비기를 기다리는 선례가 있습니다. OCR 시험 파일에도 같은 fixture 를 두어 느린 스레드가 자리 반납을 끝낸 뒤 시험을 시작하게 했습니다.

## 수정 근거

- `tests/test_document_extraction_ocr.py`: `_reset_ocr_engine` 은 `_engine`, `_engine_unavailable` 만 되돌립니다 (`get_engine` 복구 줄은 근거 없는 원인 1 과 함께 제거).
- `tests/test_document_extraction_ocr.py`: 하드닝 파일과 동일한 `_await_free_extraction_slots` autouse fixture 로 느린 추출 스레드가 자리 반납을 끝낸 뒤 시험을 시작.
- `tests/conftest.py`: 파일 내 `_reset_ocr_engine` 과 중복이던 `_reset_ocr_globals` fixture 를 제거.
- 운영 코드(ocr.py, documents.py)의 OCR 동작(모델 해시 검증, 경고 1회)과 슬롯 반납 경로는 변경하지 않았습니다. 시험의 단정(`len(unavailable) == 1`)도 느슨하게 바꾸지 않았습니다.
