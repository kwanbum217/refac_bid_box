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

| 복구 단계 | 4시간 내 예산 | 실측 (2026-09-22) | 측정 방법 |
| --- | --- | ---: | --- |
| 스냅샷 검증 | 미배정 | 2.0초 | restore drill 보고서의 단계별 소요 시간 |
| 아카이브 해제 | 미배정 | 15.5초 | restore drill 보고서의 단계별 소요 시간 |
| DB import | 미배정 | 1,391.6초 | restore drill 보고서의 단계별 소요 시간 |
| G1 무손실 검증 (파일 3.2초 + DB 7.9초) | 미배정 | 11.1초 | restore drill 보고서의 단계별 소요 시간 |
| 정리 | 미배정 | 3.7초 | restore drill 보고서의 단계별 소요 시간 |
| 서비스 정상화 (app·meilisearch 재생성부터 첫 200 응답) | 미배정 | 15.1초 (3회 21.7·15.1·15.1초의 중앙값) | `docker compose up -d --force-recreate --no-deps meilisearch app` 후 health healthy 와 `/accounts/login/` 200 까지 |
| Meilisearch 읽기 모델 전체 재색인 | 미배정 | 미측정 | 스냅샷에 Meilisearch 데이터가 없으므로 실제 재해 복구에는 `scripts/sync_search_index.py` 전체 재색인이 추가로 필요하다 |
| **합계 (재색인 제외)** | 4시간 | **약 1,439초 (약 24분)** | drill 보고서 `total_duration_seconds` 1,423.9초 + 서비스 정상화 15.1초 |

실측 근거는 `data/backups/restore_drill_report_20260922.json`(스냅샷 `snapshot_20260921_061612`, 공고 5,517,351행, 낙찰 3,439,172행, G1 PASS)입니다. 같은 날 첫 drill 은 G1 스키마 서명 기준선이 2026-09-14 테이블 추가를 반영하지 않아 `g1_db_verification` FAIL 이었고(총 1,616.6초), 기준선을 `00222bd0` 에서 갱신한 뒤 재실행해 통과했습니다. 2026-09-11 drill 의 DB import 823.9초 대비 약 1.7배입니다. 원인은 확정하지 못했습니다. 행 수는 공고 5,504,119행에서 5,517,351행(약 0.2%), 덤프 크기는 2.10GB 에서 2.12GB(약 1%)로 거의 같습니다. 그 사이 추가된 스키마 요소는 커버링 인덱스 2개(ix_bid_ann_inst_cat_ntce 762MB, ix_bid_results_inst_cat_stats 396MB)와 테이블 2개(약 268MB)이며 import 중 인덱스 빌드 비용이 늘었을 수 있으나, 이것으로 568초 증가를 모두 설명한다는 근거는 없습니다. 다음 drill 에서 단계 내부 시간을 나눠 재야 합니다.

단계별 예산 배분은 아직 하지 않았습니다. 재색인 단계를 실측한 뒤 배분합니다. 실측 합이 4시간을 초과하면 목표 미충족으로 5절을 따릅니다. 실측하지 않은 수치를 실측인 것처럼 기록하지 않습니다.

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
