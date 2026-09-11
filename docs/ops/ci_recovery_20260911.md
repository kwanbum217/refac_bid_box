# CI 장애 복구 보고서 (2026-09-11)

> **작성일**: 2026-09-11
> **대상 작업**: task_1d5f4fddb392 (CI 실패 복구 및 회귀 방지)
> **상태**: 완료

---

## 1. 개요

GitHub Actions CI 워크플로에서 발생한 두 건의 실패(Windows 러너 테스트 실패 및 Tailwind CSS 재현성 검사 실패)에 대해 원인을 실측으로 규명하고 복구를 완료하였습니다.

| 항목 | 실패 Job | 증상 요약 | 조치 방식 |
| --- | --- | --- | --- |
| 이슈 1 | Test (windows-latest, py3.11) | 테스트 코드의 OS 경로 구분자(`\`) 가정으로 인한 단정 불일치 | 테스트 단정을 `Path.as_posix()` 기반으로 수정 및 회귀 방지 테스트 추가 |
| 이슈 2 | lint-and-validate (Verify Tailwind CSS Reproducibility) | `detail.html` 변경에 따른 `hover:bg-slate-50/50` 클래스 추가분 미반영 드리프트 | `npm run build:css` 실행을 통한 정본 `tailwind.css` 재생성 및 반영 |

---

## 2. 이슈 1: Windows 러너 경로 구분자 단정 결함

### 2.1 원인 실측 및 분석

Windows 환경 러너에서 다음 두 테스트가 실패하였습니다:
1. `tests/test_orca_forbidden_lockfile_gate.py:47`
   - 기존 단정: `assert str(target.relative_to(tmp_path)) in result.details[0]`
   - 실패 원인: Windows 환경에서 `str(target.relative_to(tmp_path))`는 백슬래시(`\`)가 포함된 `nested\pnpm-lock.yaml`을 생성합니다. 그러나 운영 코드(`scripts/orca_level1_gate.py:529`)는 `path.relative_to(repo).as_posix()`를 사용하여 플랫폼과 무관하게 항상 POSIX 형태인 `nested/pnpm-lock.yaml`을 반환합니다. 이로 인해 부분 문자열 매칭이 실패하였습니다.
2. `tests/test_orca_worker_done_guard.py:535`
   - 기존 단정: `assert str(dest.relative_to(worktree)).startswith(".orca/")`
   - 실패 원인: Windows 환경에서 `str(dest.relative_to(worktree))`는 `.orca\dispatch_capabilities\...`를 반환하므로 슬래시(`/`)로 시작하는 문자열 접두사 검사가 실패하였습니다.

### 2.2 운영 코드가 아닌 테스트를 수정한 근거

- **플랫폼 중립적 정규화 원칙**: 게이트 검출 결과와 보고서 내의 상대 경로는 운영체제(Windows, Linux, macOS)에 따라 형식이 달라지지 않아야 합니다. 그래야만 개발자와 자동화 도구가 동일한 문자열로 대조하고 일관된 로그를 보장받을 수 있습니다.
- **운영 코드 무결성 유지**: 운영 코드는 이미 `.as_posix()`를 통해 올바르게 POSIX 규격을 준수하고 있었으며, 테스트 코드가 OS 기본 문자열화(`str(Path)`)를 사용하여 플랫폼 종속성을 유발한 결함이었습니다.
- **단정 불변조건 준수**: 단정을 완화하거나 제거하지 않고, `Path.as_posix()`를 적용하여 Windows 러너에서도 동일하게 POSIX 경로 일치 여부를 엄격히 확인하도록 개선하였습니다.

### 2.3 조치 내역

- `tests/test_orca_forbidden_lockfile_gate.py`: `target.relative_to(tmp_path).as_posix()`로 수정
- `tests/test_orca_worker_done_guard.py`: `dest.relative_to(worktree).as_posix().startswith(".orca/")`로 수정
- `tests/test_ci_path_separator_regression.py`: Windows 순수 경로(`PureWindowsPath`) 시뮬레이션 및 게이트 POSIX 출력 보장 회귀 방지 테스트 신규 작성

---

## 3. 이슈 2: Tailwind CSS 재현성 검사 실패

### 3.1 원인 실측 및 분석

CI의 `Verify Tailwind CSS Reproducibility` 단계(`npm run build:css` 후 `git diff --exit-code -- src/app/static/css/tailwind.css`)에서 차이가 감지되어 실패하였습니다.
실제 워크트리에서 `npm ci` 후 `npm run build:css`를 실행하고 이전 커밋 버전과 산출물을 규칙 단위로 대조한 결과는 다음과 같습니다:

| 항목 | 변경 전 (`HEAD`) | 변경 후 (재빌드) | 차이 내역 |
| --- | --- | --- | --- |
| 바이트 크기 | 43,995 bytes | 44,063 bytes | +68 bytes |
| CSS 규칙 블록 수 | 499개 블록 | 500개 블록 | +1개 규칙 추가 |
| 추가된 CSS 규칙 | 없음 | `.hover:bg-slate-50/50:hover{...}` | 템플릿 신규 클래스 |

원인 추적 결과, 최근 커밋 `9911eca6`(`fix: 기술용역 적격심사 표시 보완`)에서 `src/app/templates/bids/detail.html` 파일에 `<tr class="hover:bg-slate-50/50">`이 추가되었으나, 정적 빌드 산출물인 `src/app/static/css/tailwind.css`를 함께 재빌드하여 커밋하지 않아 드리프트가 발생한 것으로 확인되었습니다.

버전 불일치나 비결정적 빌드 출력이 아닌 템플릿 변경에 따른 정상적인 CSS 산출물 갱신 누락이 원인입니다.

### 3.2 조치 내역

- `npm run build:css`를 실행하여 갱신된 `src/app/static/css/tailwind.css`를 반영하였습니다.
- 빌드 후 `git diff --exit-code -- src/app/static/css/tailwind.css` 실행 시 무차이(exit code 0)를 실측 검증하였습니다.

---

## 4. 검증 결과 요약

| 검증 단계 | 명령 | 결과 |
| --- | --- | --- |
| 단위 테스트 (수정 및 회귀 방지) | `uv run pytest tests/test_orca_forbidden_lockfile_gate.py tests/test_orca_worker_done_guard.py tests/test_ci_path_separator_regression.py -q` | 33 passed |
| 전체 테스트 (데이터 자산 제외) | `uv run pytest tests/ -q -m 'not data_assets'` | 344 passed, 8 skipped |
| 코딩 및 커밋 규칙 검증 | `python3 scripts/validate_agent_rules.py --quiet` | 통과 |
| CSS 빌드 재현성 검증 | `npm run build:css && git diff --exit-code -- src/app/static/css/tailwind.css` | 차이 없음 (코드 0) |
