# refac_bid_box 문서 인덱스

> **작성일**: 2026-07-31
> **정정일**: 2026-08-06
> **버전**: v1.3.0
> **상태**: Phase 0~6 완료 / Phase 7 컷오버 보류
> **적용 범위**: `bid_box` (Django) → `refac_bid_box` (FastAPI + SSR/HTMX) 전환

---

## 문서 목록

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| **리팩토링 설계서** | [`design/REFACTORING_DESIGN.md`](design/REFACTORING_DESIGN.md) | 전체 리팩토링 청사진 |
| **프론트엔드 결정** | [`design/FRONTEND_DECISION.md`](design/FRONTEND_DECISION.md) | SSR+HTMX 확정, React SPA 중단 |

---

## 폴더 구조

```
docs/
├── README.md
├── design/
├── migration/
├── ops/
├── handoff/
└── changelogs/
```

---

## 1. design/

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| 리팩토링 설계서 | [`REFACTORING_DESIGN.md`](design/REFACTORING_DESIGN.md) | AS-IS/TO-BE, 로드맵 |
| 프론트엔드 결정 | [`FRONTEND_DECISION.md`](design/FRONTEND_DECISION.md) | SSR+HTMX ADR, React 동결 및 노출 차단 |
| React 재현 설계 (기각) | [`frontend_react_reproduction_design.md`](design/frontend_react_reproduction_design.md) | 검토 후 기각. SSR 정본 유지 근거 |
| 용역 낙찰률 예측 모델 | [`servc_prediction_model_design.md`](design/servc_prediction_model_design.md) | 특징 설계, 절제 실험, 승격 기준 |
| 금액 미공개 공고 예측 | [`prediction_without_amount_20260804.md`](design/prediction_without_amount_20260804.md) | 0원 추천 차단. 원본과 의도적으로 다른 동작 |
| G2B 전자입찰 제도 분석 | [`g2b_procurement_institution_analysis.md`](design/g2b_procurement_institution_analysis.md) | 예정가격·낙찰하한율 산식, 2026-05-26 제도 변경 |
| 용역 제도 가정 검증 보고 | [`servc_institution_verification_20260803.md`](design/servc_institution_verification_20260803.md) | V1~V7 데이터 검증 결과, 설계 정정 사항 |
| 낙찰하한율 결측 조사 | [`lwlt_missing_investigation_20260806.md`](design/lwlt_missing_investigation_20260806.md) | 복원 기각. 결측은 제도적 부재, 레짐 전환 편향 없음 |
| 용역 분리 모델 실험 | [`servc_segment_experiment_20260803.md`](design/servc_segment_experiment_20260803.md) | 분리 모델·하한율 절단 기각, 제도 특징 채택 |
| 용역 2025년 연도 홀드아웃 | [`servc_year_holdout_2025_20260803.md`](design/servc_year_holdout_2025_20260803.md) | 공고 건당 오차 분포, 연초 성능 저하 |
| 제한경쟁 진단과 난수 구조 | [`servc_restricted_competition_20260803.md`](design/servc_restricted_competition_20260803.md) | 참여업체 수·복수예가 난수 분해, 세부분류 특징 배선 |
| 손실함수와 반복 발주 이력 | [`servc_repeat_procurement_20260803.md`](design/servc_repeat_procurement_20260803.md) | Huber 채택, 재발주 이력 6종, 공고명 텍스트 기각 |
| 예측 구간 보정 측정 | [`servc_prediction_interval_20260804.md`](design/servc_prediction_interval_20260804.md) | 분위 회귀 피복률 실패, 등각예측 보정, API·UI 노출 완료 |
| MLOps 알림 설계 | [`mlops_notification_20260805.md`](design/mlops_notification_20260805.md) | Harness 대시보드 상실분 보완. 웹훅 방식, 구현 미착수 |
| 전량 재적합 결함 | [`servc_refit_on_full_20260805.md`](design/servc_refit_on_full_20260805.md) | 서빙 모델이 최신 20% 미학습. 편향 없는 확인에서 MAE -7.12% |
| 학습·서빙 특징 값 대조 | [`servc_feature_parity_20260805.md`](design/servc_feature_parity_20260805.md) | inst_sample_cnt 가 서빙에서 항상 0 이던 결함, 운영 MAE -6.1% |
| 기관 이력 시간 가중 | [`servc_rolling_institution_20260805.md`](design/servc_rolling_institution_20260805.md) | 고정 창 기각 유지, 전량 재적합 후 지수감쇠 재판정 |
| 용역 기각 후보 재검증 | [`servc_unbiased_candidate_recheck_20260805.md`](design/servc_unbiased_candidate_recheck_20260805.md) | 리프 255와 지수감쇠 배선·재학습·운영 쌍대 검증·승격 |
| 물품 모델 재학습 | [`thng_retraining_20260806.md`](design/thng_retraining_20260806.md) | 34특징 LightGBM 재학습·운영 쌍대 검증·승격 |
| 하이퍼파라미터 탐색 | [`servc_hyperparam_search_20260804.md`](design/servc_hyperparam_search_20260804.md) | 좌표 하강 17회, 점 추정·분위 파라미터 분리, 리프 상향은 운영 실측 후 기각 |
| 용역 하한율 가용성 | [`servc_lwlt_availability_20260804.md`](design/servc_lwlt_availability_20260804.md) | 결측의 76.8%가 방법명으로 설명 불가. 결측 축소는 유효한 경로 |

## 2. migration/

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| DB 마이그레이션 | [`db_migration_runbook.md`](migration/db_migration_runbook.md) | 덤프/복원/검증 |
| ML/Chroma 검증 | [`ml_weights_verification.md`](migration/ml_weights_verification.md) | 체크섬·회귀 테스트 |

## 3. handoff/

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| 인수인계 (정정본) | [`2026-07-31_skill_system_handoff.md`](handoff/2026-07-31_skill_system_handoff.md) | 실제 진행 상태 |
| 원본 재현율 복원 | [`2026-07-31_parity_restoration_handoff.md`](handoff/2026-07-31_parity_restoration_handoff.md) | 데이터 유실 복구, 조작·결함 7건 수정, 스택 변경 |
| 백필 완료 | [`2026-08-03_backfill_complete.md`](handoff/2026-08-03_backfill_complete.md) | 과거 결손 복구 결과 |
| 용역 제도 특징 1차 | [`2026-08-03_servc_institution_handoff.md`](handoff/2026-08-03_servc_institution_handoff.md) | 제도 특징 배선 |
| 용역 모델 개선 2차 | [`2026-08-03_servc_model_tuning_handoff.md`](handoff/2026-08-03_servc_model_tuning_handoff.md) | R2 0.6968, MAE -15.6% |
| 용역 제도 분석 인수인계 | [`2026-08-03_servc_institution_handoff.md`](handoff/2026-08-03_servc_institution_handoff.md) | 제도 특징 배선, 세부분류 채택 |
| 용역 모델 튜닝 인수인계 | [`2026-08-03_servc_model_tuning_handoff.md`](handoff/2026-08-03_servc_model_tuning_handoff.md) | Huber, 재발주 이력, 기각 목록 |
| 서빙 배선 인수인계 | [`2026-08-04_servc_serving_handoff.md`](handoff/2026-08-04_servc_serving_handoff.md) | 특징 단일화, 승격 경로, 예측 구간 |
| Phase 7 인수인계 | [`2026-08-04_phase7_handoff.md`](handoff/2026-08-04_phase7_handoff.md) | 컷오버 판정, 재현 절차, 잔여 조건 |
| 리팩토링 세션 인수인계 | [`2026-08-06_refactoring_handoff.md`](handoff/2026-08-06_refactoring_handoff.md) | 첫 토큰·CI·승격 게이트 수정, 기각 목록, 잔여 결정 사항 |
| 모델 성능 개선 재개 인수인계 | [`2026-08-06_model_improvement_handoff.md`](handoff/2026-08-06_model_improvement_handoff.md) | Servc·Thng 승격 상태, 하한율 결측 집단 후속 진단, 기각 경계 |

## 4. ops/

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| Phase 7 검증 보고서 | [`phase7_cutover_report_20260804.md`](ops/phase7_cutover_report_20260804.md) | 무손실·레이턴시·크로스 플랫폼 판정 근거 |
| 크로스 플랫폼 가이드 | [`cross_platform_guide.md`](ops/cross_platform_guide.md) | macOS·Windows 재현 및 검증 절차 |
| 모델 승격·롤백 런북 | [`model_promotion_runbook.md`](ops/model_promotion_runbook.md) | 승격 게이트, 쌍대 비교 절차, 롤백 왕복 |
| 스냅샷 재집계 비용 | [`snapshot_rebuild_cost_20260806.md`](ops/snapshot_rebuild_cost_20260806.md) | 야간 506초 구조, 날짜 축 확장·LIKE 제거 기각 근거 |

## 5. changelogs/

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| 작업 일지 | [`changelogs/work_log.md`](changelogs/work_log.md) | Phase별 누적 기록 |

---

## 권장 독해 순서

1. [`README.md`](../README.md)
2. [`AGENTS.md`](../AGENTS.md) / [`SKILLS.md`](../SKILLS.md)
3. [`design/REFACTORING_DESIGN.md`](design/REFACTORING_DESIGN.md)
4. [`handoff/2026-07-31_parity_restoration_handoff.md`](handoff/2026-07-31_parity_restoration_handoff.md)
5. [`handoff/2026-07-31_skill_system_handoff.md`](handoff/2026-07-31_skill_system_handoff.md)
6. [`handoff/2026-08-04_phase7_handoff.md`](handoff/2026-08-04_phase7_handoff.md)
7. [`ops/phase7_cutover_report_20260804.md`](ops/phase7_cutover_report_20260804.md)

---

_본 인덱스는 살아있는 문서입니다._
