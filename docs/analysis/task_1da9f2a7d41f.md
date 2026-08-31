# Task task_1da9f2a7d41f: Level 2 Reviewer JSON 복구 및 원문 보존 개선

> 작성일: 2026-09-01
> 대상 모듈: scripts/orca_run_reviewer.py, tests/test_orca_run_reviewer.py
> 작업 ID: task_1da9f2a7d41f (run_f5b20eafcaff)

---

## 1. 작업 개요

- **목적**: qwen3.7-plus 리뷰어 등 모델이 다중 JSON 또는 앞뒤 부가 텍스트를 반환할 때 파싱 실패로 인한 무작위 반려를 방지하고, 파싱 실패 시 정확히 1회 재시도하며, 실패 시 원문(.raw)을 재현 가능한 경로에 보존.
- **원칙**:
  - `json.JSONDecoder().raw_decode` 기반으로 첫 번째 완전한 JSON 객체 추출.
  - 파싱 실패 시 동일 프롬프트로 정확히 1회 재시도.
  - 실패 원문을 `--out` 경로 옆 `.raw` 및 `.orca/reports/` 타임스탬프 파일로 보존.
  - TIER_POLICY 및 MODEL_POOL 모델 배정표 수정 없음 (리뷰어 주 모델 qwen-plus 유지).

---

## 2. 세부 변경 사항

### 2.1 JSON 추출 로직 개선 (`extract_json_from_response`)
- 기존: 첫 번째 `{` 부터 마지막 `}` 까지 통째로 슬라이스하여 `json.loads` 수행 (다중 JSON 객체 또는 후속 데이터 존재 시 파싱 오류 발생).
- 변경: `json.JSONDecoder().raw_decode` 를 활용하여 문자열 내 첫 번째 완전한 JSON 객체(dict)만 정확히 파싱.
- 효과: 다중 JSON 출력, 마크다운 코드펜스, 앞뒤 설명 텍스트가 포함된 응답도 안전하게 첫 JSON 객체를 추출.

### 2.2 파싱 실패 시 1회 재시도 메커니즘 (`run_reviewer`)
- 1차 모델 호출 결과에서 JSON 파싱이 실패한 경우, 동일 프롬프트로 `model_runner` 를 정확히 1회 재시도.
- 재시도 결과 유효한 JSON 이 반환되면 정상 평가 파이프라인으로 복구.
- 재시도도 실패하면 종료 코드 2 로 실패 처리.

### 2.3 실패 원문 이중 보존 (`run_reviewer`)
- 파싱 실패 시 원문 텍스트를 `--out` 인자 대상 경로의 `.raw` 파일에 저장.
- 동시에 `repo_path / ".orca" / "reports" / "{out_stem}_{timestamp}.raw"` 경로에도 타임스탬프 파일로 자동 기록하여 재현 및 사후 분석 가능하도록 보존.

---

## 3. 검증 결과

1. **리뷰어 전용 단위 테스트**:
   - 명령: `uv run pytest tests/test_orca_run_reviewer.py -q`
   - 결과: `42 passed, 1 warning in 0.08s`
   - 신규 추가된 테스트 항목 (4건):
     - `test_extract_json_parses_first_complete_json_object_with_trailing_data`: 다중 객체 및 앞뒤 텍스트 처리 검증
     - `test_retry_on_parse_failure_succeeds_on_second_attempt`: 1회 재시도 성공 복구 검증
     - `test_retry_on_parse_failure_fails_after_exactly_one_retry`: 2회 실패 후 종료 코드 2 및 .raw 이중 저장 검증
     - `test_no_retry_when_first_attempt_succeeds`: 1차 성공 시 불필요한 재시도 없음(1회 호출) 검증

2. **전체 테스트 스위트 회귀 검증**:
   - 명령: `uv run pytest tests/ -q -m 'not data_assets'`
   - 결과: `2928 passed, 8 skipped, 3 deselected, 300 warnings in 237.56s` (전량 통과)

3. **에이전트 규칙 검증**:
   - 명령: `python3 scripts/validate_agent_rules.py --quiet`
   - 결과: `검증 통과: 16/16 건`

---

## 4. 잔여 리스크 및 모니터링 사항

- **잔여 리스크**: 모델이 2회 연속으로 전혀 파싱할 수 없는 비정형 텍스트를 반환하는 경우 종료 코드 2 로 중단됩니다. 이는 계약 위반 상태의 지속을 막기 위한 의도된 동작이며, 생성된 `.orca/reports/*.raw` 로그를 통해 모델 프롬프트 준수도를 추적할 수 있습니다.
- **배정표 불변**: TIER_POLICY 의 리뷰어 주 모델(`qwen-plus`)은 본 작업에서 변경되지 않았으며, 파싱 유연성 확보 및 재시도 메커니즘을 통해 안정성을 높였습니다.
