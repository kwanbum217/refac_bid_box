# task_f1cbfc0d73c2 작업 보고 (R-07 종료)

> **작성일**: 2026-09-06
> **역할**: builder
> **범위**: 문서 3종만 변경하며 src와 scripts는 수정하지 않았습니다.

---

## 1. 수행 내용

사용자가 2026-09-06에 확정한 복구 목표 RPO 24시간·RTO 4시간을 `docs/ops/rpo_rto_policy.md`로 신설했습니다. 정본 상태 원장 `docs/context/current_state_facts.yaml`의 세 사실을 갱신하고 `docs/context/CURRENT_STATE.md`의 해당 문장과 상태 절 배치를 같은 커밋에서 함께 고쳤습니다.

## 2. 사실별 판정

| 사실 | 변경 전 | 변경 후 | 근거 |
| --- | --- | --- | --- |
| rpo_rto | blocked, 미정·결정 대기 | active, 목표 확정·분기 1회 drill 실시 추진 | 사용자 확정 2026-09-06, drill 실시 이력 없음 |
| model_swap_gap | active, 심볼릭 링크 교체 추진 | closed, 세대 디렉터리와 LIVE 포인터 os.replace 교체 완료 | `docs/analysis/task_7f0659b4d4fc.md`, `src/ml/promotion.py`의 `_replace_path`와 LIVE 포인터 공개 경로 |
| state_budget | active, 8,000자 이하 목표 진행 | closed, 8,000자 이하 목표 통과 | CURRENT_STATE.md 6.2절 측정 7,930바이트·5,013자 |

사실을 삭제하지 않았으며 세 사실의 `decision_date`를 2026-09-06으로 바꾸고 근거 문서를 `evidence`에 추가했습니다. `source_commit`은 건드리지 않았습니다.

## 3. 정책 문서 구성

신설 정책 문서는 확정값과 의미, 일 1회 스냅샷의 RPO 충족 근거와 스케줄 활성화 선행 조건, RTO 4시간 단계별 예산표(전 단계 미측정 표기와 측정 방법), 분기 1회 drill 주기, 목표 미충족 시 조치 순서를 담습니다. 복구 절차는 다시 쓰지 않고 `docs/ops/backup_recovery_runbook.md`를 상대 경로로 참조합니다.

## 4. 남은 사항

분기 1회 restore drill 1회차 실시와 그 실측에 따른 RTO 단계별 예산 배분이 남았습니다. 이는 rpo_rto 사실을 active로 유지한 사유와 같습니다.
