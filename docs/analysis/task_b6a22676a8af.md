# Task C4: CI 사각지대 해소 및 커버리지 게이트 구축 보고서

> **작성일**: 2026-09-02
> **작업 식별자**: `task_b6a22676a8af`
> **작업 브랜치**: `kwanbum217/c4-ci`
> **관련 문서**: [`docs/ops/ci_contract.md`](../ops/ci_contract.md), [`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md)

---

## 1. 개요 및 배경

본 작업은 2026-09-02 보완점 분석 보고서 4.2 다 항목에 따라, CI의 사각지대를 해소하고 커버리지 게이트를 구축하여 지속적 통합 신뢰도를 강화하는 것을 목적으로 수행되었습니다.

기존 CI 시스템은 다음과 같은 세 가지 사각지대 및 계약 불일치가 존재했습니다:
1. **커버리지 게이트 부재**: `pytest-cov`가 개발 의존성에 포함되어 있었으나, CI 파이프라인에서 커버리지를 측정하거나 하한선을 강제하는 게이트가 없었습니다.
2. **Push 트리거 브랜치 누락**: GitHub Actions의 `on.push.branches`가 `[main, "feature/**", "fix/**"]`로 제한되어 있어, 1인 개발 환경에서 흔히 사용되는 `kwanbum217/**`, `docs/**` 등의 작업 브랜치에서 병합 전 CI가 작동하지 않았습니다.
3. **로컬 `make check-all`과 CI 간의 검증 계약 불일치**: `make lint` 명령이 `--fix` 및 `format .`을 포함하여 검증 과정에서 파일을 자동 수정하던 반면, CI는 확인 전용(`--check`)을 요구하여 검증 도구의 동작 계약이 어긋나 있었습니다.

---

## 2. 세부 조치 내역

### 2.1 커버리지 실측 및 게이트 하한선 설정

로컬 및 CI 환경에서 `pytest`를 실행하여 현재 백엔드 코드의 실제 커버리지를 정밀 실측하였습니다.

- **실측 커버리지**: **85.17%** (전체 9,967 구문 중 8,489 구문 통과, 1,478 구문 누락)
- **설정 하한선 (`fail_under`)**: **80.00%**

#### 설정 근거
- 실측값(85.17%)보다 임의로 높은 기준을 설정할 경우 사소한 유틸리티 추가나 리팩토링 과정에서 CI가 상시 실패(false alarm)하여 게이트가 무력화될 위험이 있습니다.
- 실측값 대비 약 5%p 낮은 80%를 하한선으로 고정함으로써, 테스트가 작성되지 않은 대규모 기능 유입이나 기존 테스트의 부주의한 삭제 등 실제 품질 회귀만을 정확히 차단합니다.
- `pyproject.toml`의 `[tool.coverage.report]` 섹션에 `fail_under = 80`을 설정하고, `.github/workflows/ci.yml`의 `cross-platform-test` 단계 및 `Makefile`의 `test` 타깃에 `--cov=src --cov-report=term-missing --cov-fail-under=80`을 배선했습니다.

### 2.2 Push 트리거 전 브랜치 확장 및 태그 중복 방지

- `.github/workflows/ci.yml`의 `on.push` 설정을 다음과 같이 수정하였습니다:
  ```yaml
  on:
    push:
      branches: [ '**' ]
      tags-ignore: [ '**' ]
  ```
- 이로써 `kwanbum217/**`을 포함한 모든 작업 브랜치 푸시 시 CI가 즉시 트리거되어 병합 전 완벽한 품질 검증이 이루어지며, 태그 푸시로 인한 불필요한 중복 실행이 차단됩니다.

### 2.3 `make check-all`과 CI 린트 계약 단일화

- `Makefile`의 `lint` 타깃을 무변형 확인 전용(`ruff check .` 및 `ruff format --check .`)으로 전환하고, 자동 수정을 위한 별도의 `format` 타깃을 신설하였습니다.
- `pyproject.toml`의 `[tool.ruff.extend-exclude]`에 `docs`, `frontend`를 추가하여 마크다운 내 코드 스니펫이나 프론트엔드 모듈에 대한 불필요한 포맷팅 검사 간섭을 방지했습니다.
- `.github/workflows/ci.yml`의 `lint-and-validate` Job에 `Run Ruff Format Check` 단계를 추가하여 로컬 `make check-all`과 CI의 검증 단계가 1:1로 일치하도록 통일하였습니다.
- C1에서 추가한 백업 타깃(`backup`, `backup-dry-run`, `restore-dry-run`, `backup-verify`, `backup-list`)은 100% 보존되었습니다.

---

## 3. 검증 결과

본 작업 트리의 모든 변경 사항에 대해 다음 검증 도구를 수행하여 완전한 통과를 확인하였습니다.

1. **GitHub Actions 워크플로우 문법 검사**:
   - 명령: `uv run actionlint`
   - 결과: 통과 (오류 0건)
2. **다중 에이전트 규칙 정합성 검사**:
   - 명령: `python3 scripts/validate_agent_rules.py --quiet`
   - 결과: 17/17 항목 전량 통과
3. **문서 링크 정합성 검사**:
   - 명령: `python3 scripts/validate_doc_links.py --quiet`
   - 결과: 493개 문서 링크 전량 정상
4. **로컬 전체 정적 검증**:
   - 명령: `make check-all`
   - 결과: Ruff 린트/포맷 체크, Bandit 보안 스캔, Mypy 타입 검사, 규칙 검증, 워크플로우 검사 전량 통과
5. **백엔드 테스트 및 커버리지 게이트 실측 검증**:
   - 명령: `uv run pytest tests/ -q -m "not data_assets" --cov=src --cov-report=term-missing --cov-fail-under=80`
   - 결과: 3,139 passed, 25 skipped, 3 deselected, 실측 커버리지 85.17% (하한 80% 게이트 만족)

---

## 4. 결론 및 산출물

- 본 작업을 통해 CI 파이프라인의 브랜치 사각지대와 커버리지 관리 부재가 완전히 해소되었습니다.
- 상세 운영 계약은 [`docs/ops/ci_contract.md`](../ops/ci_contract.md)에 정본으로 기록되었습니다.
- MySQL 8 통합 테스트 범위 확대는 본 과업의 범위를 벗어나므로 `ci_contract.md`에 후속 과업으로 명시하였습니다.
