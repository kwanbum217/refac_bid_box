# LLM 품질 평가 Canonical 판정 결함 수정 및 비정본 산출물 재분류 분석 보고서

> **작성일**: 2026-08-29
> **작업 식별자**: `task_ca9b69568ca4`
> **작업자**: Antigravity Worker (gemini-3.7-flash-high)
> **대상 파일**: `scripts/measure_llm_quality.py`, `tests/test_measure_llm_quality.py`, `data/benchmarks/README.md`, `data/benchmarks/noncanonical/blind_fixture_v1_20260828_reference.json`

---

## 1. 개요 및 배경

2026-08-28 측정 세션에서 `--fixture` 옵션 기본값(`data/eval/llm_quality_fixture_v1.json`)으로 인해 v1(24문항) fixture로 측정된 산출물이 정본(`canonical=true`)으로 기록되는 결함이 발견되었습니다.
기존 하네스(`scripts/measure_llm_quality.py`)의 `is_canonical` 로직은 소스 Git 상태 및 모델/포트 일치 여부만 검증하고, fixture 내용 해시, 문항 완결성, 반복 횟수, 요청 실패 여부를 전혀 검사하지 않아 비정본 측정이 정본으로 저장될 위험이 있었습니다.

본 작업에서는 하네스에 정본 검증 게이트를 엄격히 결박하고, 잘못 저장된 2026-08-28 산출물을 `noncanonical/` 디렉터리로 격리 재분류하였습니다.

---

## 2. 결함 분석 및 수정 내용

### 2.1 하네스 CLI 및 정본 판정 게이트 강화 (`scripts/measure_llm_quality.py`)

1. **`--fixture` 필수 인자화**: 기본값을 제거하고 `required=True`로 변경하여 fixture 지정을 강제.
2. **정본 Fixture SHA256 레지스트리 구축**: 파일 경로 문자열이 아닌 SHA256 내용 해시(`2c98c636a478cfc92870533513b4442704d8441bd217e303489c9bcf0752e483`)로 정본 식별.
3. **순수 함수 `evaluate_canonical` 분리**:
   - `fixture_sha256_canonical`: 정본 fixture 해시 일치 여부
   - `limit_zero`: `--limit 0` 여부
   - `item_count_full`: 측정 문항 수가 fixture 전체 문항 수와 일치하는지 여부
   - `repetitions_minimum`: 반복 횟수 3회 이상 여부
   - `no_request_failures`: 요청 실패 0건 여부
   - 기존 provenance 및 환경 결박 조건(`start_clean`, `end_clean`, `start_sha_known`, `end_sha_known`, `model_match_expected`, `port_validated`, `provenance_strict`) 동시 유지.
4. **산출물 메타데이터 확장**:
   - `canonical_failed_gates`: 실패한 게이트 식별자 목록 기록 (정본 통과 시 빈 배열)
   - `fixture_sha256`: 측정에 사용된 fixture의 SHA256 해시 기록
   - `limit`: 적용된 limit 값 명시
5. **비정본 판정 시 경고 출력**: `canonical: false`인 경우 저장 후 표준 오류(stderr)에 경고 및 실패 게이트 명시 (종료 코드는 기존 규칙 유지).

### 2.2 2026-08-28 산출물 격리 및 재분류

- `data/benchmarks/blind_fixture_full_20260828_final.json`을 `data/benchmarks/noncanonical/blind_fixture_v1_20260828_reference.json`으로 `git mv` 이동.
- 최상위 `canonical: false`, `provenance.canonical: false`로 수정.
- `noncanonical_reason: "정본 기준(v2 32문항)이 아닌 v1 24문항 fixture로 측정된 참조용 결과입니다."` 필드 추가.
- `results` 측정값 데이터 100% 무손실 보존 (동일성 검증 완료).

### 2.3 문서화 및 테스트 추가

- `data/benchmarks/README.md`: 정본 fixture 사양, 10개 검증 게이트, noncanonical 디렉터리 목적 및 v1 과거 산출물 4건 보존 기준 명시.
- `tests/test_measure_llm_quality.py`:
  - `TestComputeFileSha256`: 파일 해시 계산 함수 검증
  - `TestEvaluateCanonical`: 7개 핵심 게이트 단독 및 복합 위반 검증
  - `TestCliArguments`: `--fixture` 누락 시 실행 실패 검증
  - `TestIntegrationMainHarness`: 비정본 측정 시 `canonical_failed_gates` 저장 및 stderr 경고 통합 검증

---

## 3. 검증 결과

| 검증 항목 | 수행 명령 | 결과 |
| --- | --- | --- |
| 단위 및 통합 테스트 | `uv run pytest tests/test_measure_llm_quality.py -q` | 69 passed |
| 전체 단위 테스트 (데이터 제외) | `uv run pytest tests/ -q -m "not data_assets"` | 통과 |
| 전체 테스트 | `uv run pytest tests/ -q` | 통과 |
| 코드 린트 | `uv run ruff check src/ scripts/ tests/` | All checks passed |
| 에이전트 규칙 검증 | `python3 scripts/validate_agent_rules.py --quiet` | 통과 |
