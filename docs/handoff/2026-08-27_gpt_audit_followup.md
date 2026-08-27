# GPT 재감사 후속 조치 인수인계 (2026-08-27)

> **작성일**: 2026-08-27
> **Orca Run**: `run_2f3d5d3497a0`
> **워커**: Antigravity `gemini-3.7-flash-medium` 4대
> **기준 커밋**: 착수 `137849e` -> 종료 `7be447f`

---

## 1. 처리 결과

| 지적 | 우선순위 | 처리 | 근거 |
| --- | --- | --- | --- |
| LLM generalization 판정 기준 충돌 | P1 | 코디네이터 확정 후 반영 | `d00c6af` |
| benchmark load metric 의미 왜곡 | P1/P2 | 정규화 load average 로 명칭 분리 | `0efcac1` |
| `audit_model_inventory` 감사 중 상태 변경 | P2 | read-only 기본 + fail-closed + 잠금 | `d934476` |
| numeric omission detector 신뢰성 | P2 | 경계 매칭, 최종 답변 검사, Source 귀속 | `7be447f` |
| Tailwind 빌드 재현성 | P2 | 루트 lockfile + CI 재생성 diff 게이트 | `306b668` |
| Python 지원 범위와 CI matrix 불일치 | P2 | ubuntu 에서 3.12, 3.13 추가 | `306b668` |
| 문서·코드 드리프트 3건 | P3 | 정정 | `d00c6af` |
| 원격 브랜치 정리 | - | 병합 완료 11건 삭제 | 2절 |

---

## 2. 삭제한 원격 브랜치

전부 `origin/main` 에 병합 완료였으며 미병합은 0건이었습니다.

| 브랜치 | SHA |
| --- | --- |
| chore/coordinator-handoff | 790dd57 |
| docs/refresh-current-state-source | a8ad98a |
| fix/orca-worker-preparation-safety | aa56791 |
| kwanbum217/benchmark-load-window | 728d96a |
| kwanbum217/fix/arq-gate-validation | b473e29 |
| kwanbum217/handoff-coldstart-warmup | 73edf7f |
| kwanbum217/handoff-current-state-cleanup | d2b8756 |
| kwanbum217/handoff-query-latency | 1e0608d |
| kwanbum217/predict-remeasure-report | 8496a36 |
| kwanbum217/v3p0-metrics | 884b0f0 |
| kwanbum217/v3p0-reviewer | 9e6f193 |

---

## 3. 확정한 판정 기준 (LLM generalization)

blind fixture 에서 e2b 와 e4b 를 **동일 조건으로 함께** 측정합니다. e2b 승격
유지 조건은 다음 둘을 모두 만족하는 것입니다.

- (A) e2b numeric 정답률이 같은 blind fixture 의 e4b numeric 정답률 이상
- (B) e2b numeric 정답률이 55.0% 이상

v4 fixture 의 61.8% 는 분포가 다른 fixture 의 값이므로 blind fixture 의 절대
문턱으로 이식하지 않습니다. 55.0% 는 모델 선택 문턱이 아니라 두 모델이 모두
미달이면 RAG 답변 생성 자체의 실패로 판정하는 **바닥선**입니다.

---

## 4. 남은 과업

### 4.1 GPT 지적별 종결 여부

이번 세션은 **지적 전부를 종결하지 않았습니다.** GPT 가 P1 로 매긴 두 건은
둘 다 미완결이며, 따라서 **"G3 최종 컷오버 보류" 판정은 그대로 유지됩니다.**

| GPT 지적 | 판정 | 남은 부분 |
| --- | --- | --- |
| `audit_model_inventory` 상태 변경 (P2) | **종결** | 권고 5개 전부 반영 |
| 문서·코드 드리프트 3건 (P3) | **종결** | 없음 |
| Tailwind 빌드 재현성 | **종결** | 없음 |
| Python 지원 범위 ↔ CI matrix | **종결** | macOS/Windows 는 3.11 만 유지 (비용 절충) |
| 원격 브랜치 정리 | **종결** | ruleset 은 별건 |
| e2b 승격 근거 (P1) | **부분** | 판정 기준만 확정. **측정 미실행** |
| CPU 사용률 의미 (P1/P2) | **부분** | 명칭만 분리. **실제 CPU utilization 미도입** |
| omission detector (P2) | **부분** | 경계·후단·Source 만. **expected-fact 선별 미구현** |
| Windows Docker Desktop 실기 | **미착수** | 장비 부재 |
| main ruleset | **미착수** | 이번 세션 범위 제외 |

### 4.2 다음 착수 지점

**우선순위 1순위는 blind fixture 측정입니다.** 판정 기준이 3절로 이미 확정돼
있어 측정 결과가 그대로 판정이 됩니다.

다만 **"측정만 남았다" 는 표현은 정확하지 않습니다.** 착수 전에 확인한 결과
선행 산출물이 없습니다.

| 선행물 | 상태 |
| --- | --- |
| `scripts/measure_llm_quality.py` | **있음** |
| `data/eval/llm_quality_fixture_v1.json` | 있음 (기존 24문항) |
| `data/eval/llm_quality_fixture_v2.json` | **없음.** 설계서 8.3 절 명령이 이 파일을 참조한다 |
| `scripts/build_generalization_fixture.py` | **없음.** 설계서 109 행이 참조하는 파일이 존재하지 않는다 |

따라서 다음 세션의 실제 첫 작업은 측정 실행이 아니라 **fixture 생성기 작성과
v2 fixture 구축**입니다. 설계서 8.3 절 명령을 그대로 실행하면 파일 부재로
실패합니다.

순서는 다음과 같습니다.

1. `scripts/build_generalization_fixture.py` 작성 (설계서 5장 fixture 사양 기준)
2. `data/eval/llm_quality_fixture_v2.json` 생성 후 `validate_llm_quality_fixture.py` 로 검증
3. 설계서 8.3 절 명령으로 e2b·e4b 를 **동일 fixture·동일 조건**으로 각각 3회 측정
4. 3절 기준 (A)(B) 로 판정. 미달이면 e2b 승격 철회 후보 상정

### 4.3 그 밖의 남은 과업

| 과업 | 상태 | 비고 |
| --- | --- | --- |
| 실제 CPU utilization 계측 | 미도입 | 새 의존성(psutil 등) 사전 합의 필요. 현재 지표는 정규화 load average 로 명시돼 있어 오해 소지는 없음 |
| detector expected-fact 선별 | 미구현 | `RetrievalPlan` + `Provenance.items` 연동. 현재는 기본 비활성 관측 기능이라 운영 위험은 없음 |
| Windows Docker Desktop 실기 | 미검증 | 장비 부재. G2 컷오버 차단 요인으로 유지 |
| main ruleset (force-push·삭제 방지) | 미적용 | 사용자가 이번 범위에서 제외 |

---

## 5. 감시 기록

`orca_worker_watch.py` 로 반복 감시했으며 차단 6건(권한 프롬프트 5, CLI 설문 1)을
발견해 해제했습니다. 워커 1대는 편집 전 baseline 전량 pytest 로 12분을 소비해
코디네이터가 터미널 지시로 개입했습니다. 감시 절차는 이번 세션에서
[`docs/ops/orca_worker_supervision_spec.md`](../ops/orca_worker_supervision_spec.md)
로 명세화했습니다.

워커 4대의 워크트리, 터미널, 로컬 브랜치는 모두 정리했습니다.
