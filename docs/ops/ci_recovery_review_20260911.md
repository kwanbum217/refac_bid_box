# CI 복구 독립 검토 보고서 (2026-09-11)

> **작성일**: 2026-09-11
> **검토 대상**: 브랜치 kwanbum217/orca-bh1 의 커밋 29ee5ee (BH1, task_1d5f4fddb392)
> **검토 방식**: 읽기 전용 정적 검토. 소스 수정 없음, 테스트 재실행 없음, 빌드 재실행 없음, 커밋 없음.
> **판정**: 통과 (차단 결함 없음)

---

## 1. 검토 범위

변경 파일 5건 (`git diff main...HEAD --name-only` 실측 확인):

| 파일 | 종류 |
| --- | --- |
| tests/test_orca_forbidden_lockfile_gate.py | 단정 1줄 수정 |
| tests/test_orca_worker_done_guard.py | 단정 1줄 수정 |
| tests/test_ci_path_separator_regression.py | 신설 (96줄, 테스트 4건) |
| src/app/static/css/tailwind.css | 빌드 산출물 1줄 재생성 |
| docs/ops/ci_recovery_20260911.md | 복구 보고서 신설 |

---

## 2. 판정 결과 (수용 기준별)

### 2.1 tests 아래 같은 경로 구분자 결함 전수 조사: 잔존 없음

`tests/` tracked 262개 파일 전체를 정적 스캔한 결과, `str(...relative_to(...))` 패턴과 `os.sep` 가정은 0건이다.
`relative_to` 잔존 3건 중 2건은 신설 회귀 테스트 안의 의도적 대조용(`PureWindowsPath` 객체에 `str()`을 적용해 결함을 시연한 뒤 `as_posix()`로 해결함을 단정)이며,
1건(`tests/test_free_worker_aggregate.py:380`)은 실패 메시지 문자열 조립용으로 단정 비교 대상이 아니므로 Windows에서 깨지지 않는다.
운영 코드(`scripts/orca_level1_gate.py:529`, `scripts/orca_taskctl.py:2552`, `scripts/orca_worker_watch.py:138`)는 모두 `as_posix()`로 POSIX 정규화되어 있어 테스트 수정 방향(운영 유지, 테스트 수정)이 옳다.

### 2.2 회귀 방지 테스트가 Windows 형태까지 다룸: 예

신설 `tests/test_ci_path_separator_regression.py` 4건은 현재 OS 출력의 POSIX 고정(`"\\" not in`, 정확한 POSIX 문자열 일치)과
`PureWindowsPath` 시뮬레이션(`str(rel) == "nested\\pnpm-lock.yaml"` 임을 먼저 증명한 뒤 `as_posix()` 일치를 단정)을 모두 포함하므로,
이름뿐인 회귀 테스트가 아니라 실제 회귀를 차단한다. 단정 삭제·완화·`skip`은 없다.

### 2.3 Tailwind 산출물 변경이 정당한 반영: 예

`tailwind.css` diff는 1줄 교체, +68 bytes이며 추가분은 `.hover:bg-slate-50/50:hover` 규칙 하나다.
`src/app/templates/bids/detail.html:1146`에 `<tr class="hover:bg-slate-50/50">`이 존재하므로 빌더 주장(드리프트 반영)과 실제 diff가 일치한다.
무관한 대량 변경이 아니다.

### 2.4 CI 워크플로 미수정: 예

`git diff main...HEAD -- .github/` 출력이 비어 있다.
`Verify Tailwind CSS Reproducibility` 단계와 `windows-latest` 매트릭스가 그대로 유지되며 `continue-on-error` 추가도 없다.

### 2.5 단정 비완화: 예

경로 단정 수정 2줄은 `str(...)`을 `...as_posix()`로 바꾼 것으로 동일 엄격도의 POSIX 일치를 유지한다.
`worker_done.json` 보고 파일은 Capsule 디렉터리에 존재하고 필수 필드 12종을 모두 갖추며 `changed_files` 5건이 실제 diff와 일치한다.

---

## 3. 체크리스트 요약 (13/13)

| ID | 답변 | 의미 |
| --- | --- | --- |
| assertions_not_loosened | no | 단정 삭제·완화·skip 없음 |
| as_posix_used | yes | 2줄 모두 as_posix 기반 수정 |
| all_occurrences_fixed | yes | tests 전수 스캔, 잔존 결함 없음 |
| production_output_changed | yes 아님 (no) | 운영 코드 무수정 |
| tailwind_cause_evidenced | yes | +68 bytes 단일 규칙, 템플릿 근거 확인 |
| ci_check_disabled | no | 워크플로 무수정 |
| regression_test_present | yes | POSIX 고정 + Windows 시뮬레이션 |
| forbidden_lockfiles | no | 금지 잠금 파일 없음 |
| other_worker_area_touched | no | scripts/docker/docs-context 무수정 |
| new_package_added | yes 아님 (no) | 외부 패키지 추가 없음 |
| test_quality | no | 빈·동어반복 테스트 없음 |
| scope_exceeded | no | 허용 5파일 이내 |
| worker_done_report_present | yes | 보고 파일 존재, 필수 필드 완비 |

차단 결함 0건, 미검증 주장 2건(코디네이터 확인 사실로 재검사 면제: 전량 테스트 통과 수, CSS 재빌드 재현성), 누락 테스트 없음.
