# RPO·RTO 복구 목표 정책 (RPO/RTO Policy)

> **작성일**: 2026-09-06
> **버전**: 1.0
> **상태**: 확정 (R-07, 사용자 확정 2026-09-06)
> **관련 문서**: [`docs/ops/backup_recovery_runbook.md`](backup_recovery_runbook.md), [`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md), [`docs/context/current_state_facts.yaml`](../context/current_state_facts.yaml)

---

## 1. 확정 목표

| 지표 | 확정값 | 의미 |
| --- | --- | --- |
| RPO (Recovery Point Objective) | 24시간 | 장애 시 최대 24시간치 데이터 유실을 허용합니다. 마지막 유효 스냅샷 이후의 변경은 복원되지 않을 수 있습니다. |
| RTO (Recovery Time Objective) | 4시간 | 장애 발생 시점부터 서비스 정상화까지 최대 4시간을 허용합니다. |

본 값은 사용자가 2026-09-06에 확정한 정본이며 사용자 승인 없이 변경하지 않습니다.

---

## 2. RPO 24시간 충족 근거

현행 백업 주기인 일 1회 스냅샷이 정상 동작하면 스냅샷 간격이 24시간을 넘지 않으므로 RPO 24시간을 충족합니다. 스냅샷별 실제 시점 차이는 매니페스트의 `consistency_window`으로 관측합니다.

선행 조건으로 백업 스케줄이 활성화되어 있어야 합니다. [`docs/ops/backup_recovery_runbook.md`](backup_recovery_runbook.md)에 따르면 `BACKUP_SCHEDULE_ENABLED=false`가 기본값이며 활성화된 백업 주기가 RPO에 영향을 주므로, 비활성화 상태에서는 본 RPO 전제가 성립하지 않습니다. 스냅샷 생성 실패나 `partial_backup: true` 기록은 RPO 위반 위험이므로 5절 조치 순서를 따릅니다.

---

## 3. RTO 4시간 단계별 시간 예산

| 복구 단계 | 4시간 내 예산 | 상태 | 측정 방법 |
| --- | --- | --- | --- |
| 스냅샷 검증 | 미배정 | 미측정 | restore drill 보고서의 단계별 소요 시간 |
| 아카이브 해제 | 미배정 | 미측정 | restore drill 보고서의 단계별 소요 시간 |
| DB import | 미배정 | 미측정 | restore drill 보고서의 단계별 소요 시간 |
| G1 무손실 검증 | 미배정 | 미측정 | restore drill 보고서의 단계별 소요 시간 |
| 정리 및 서비스 정상화 | 미배정 | 미측정 | drill 범위 확장 시 별도 측정 |

현재 배분된 예산은 없으며 1회차 restore drill 실측 후에 각 단계에 예산을 배분합니다. 실측 합이 4시간을 초과하면 목표 미충족으로 5절을 따릅니다. 실측하지 않은 수치를 실측인 것처럼 기록하지 않습니다.

---

## 4. Restore Drill 주기

분기 1회 실시합니다. drill은 [`docs/ops/backup_recovery_runbook.md`](backup_recovery_runbook.md) 4.4절의 격리 리허설 절차를 따르며 본 정책은 절차를 중복 서술하지 않습니다. drill 보고서의 단계별 소요 시간과 RPO 관측값이 3절 예산 배분의 근거가 됩니다.

---

## 5. 목표 미충족 시 조치 순서

1. drill 보고서와 스냅샷 매니페스트에서 위반 지표를 특정합니다. RPO 위반은 스냅샷 간격과 실패 기록으로, RTO 초과는 단계별 소요 시간의 병목으로 판정합니다.
2. RPO 위반 시 백업 스케줄 주기와 실패 알림을 점검하고 스냅샷 실패 원인을 해소한 뒤 다음 스냅샷에서 충족을 확인합니다.
3. RTO 초과 시 병목 단계를 개선하고 다음 분기 drill에서 재측정합니다.
4. 반복 미충족 시 목표 개정안을 사용자에게 상신합니다. 사용자 승인 없이 목표값을 변경하지 않습니다.
5. 부분 백업(`partial_backup: true`)은 복원 성공 대상으로 기록하지 않습니다.
