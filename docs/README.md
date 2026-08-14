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
| **공고 검색 전환** | [`handoff/2026-08-09_bid_search_meilisearch_handoff.md`](handoff/2026-08-09_bid_search_meilisearch_handoff.md) | Meilisearch 읽기 모델 구현 및 초기 색인 검증 절차 |

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
| **용역 모델 개선 현황판** | [`servc_model_status.md`](servc_model_status.md) | **용역 작업 전 먼저 읽으십시오.** 열린 축, 닫힌 축, 대기 결정. 갱신형 |
| 용역 낙찰률 예측 모델 | [`servc_prediction_model_design.md`](design/servc_prediction_model_design.md) | 특징 설계, 절제 실험, 승격 기준 |
| 금액 미공개 공고 예측 | [`prediction_without_amount_20260804.md`](design/prediction_without_amount_20260804.md) | 0원 추천 차단. 원본과 의도적으로 다른 동작 |
| G2B 전자입찰 제도 분석 | [`g2b_procurement_institution_analysis.md`](design/g2b_procurement_institution_analysis.md) | 예정가격·낙찰하한율 산식, 2026-05-26 제도 변경 |
| 용역 제도 가정 검증 보고 | [`servc_institution_verification_20260803.md`](design/servc_institution_verification_20260803.md) | V1~V7 데이터 검증 결과, 설계 정정 사항 |
| 낙찰하한율 결측 조사 | [`lwlt_missing_investigation_20260806.md`](design/lwlt_missing_investigation_20260806.md) | 복원 기각. 결측은 제도적 부재, 레짐 전환 편향 없음 |
| 레짐 전환 재점검 (값 수준 축) | [`servc_regime_lwlt_levels_20260810.md`](design/servc_regime_lwlt_levels_20260810.md) | 기각 유지. 인상 희소 수준 3.26%, 오라클 상한 0.0079%p, 재점검 트리거 명시 |
| 레짐 재개 조건 재확인 | [`servc_regime_reopen_check_20260813.md`](design/servc_regime_reopen_check_20260813.md) | 역사적 대리 측정상 재개 근거 없음. 현행 champion OOS 는 라벨 부재로 판정 불가. MAE 격차는 결측 비중이 만든 구성 효과 |
| 용역 분리 모델 실험 | [`servc_segment_experiment_20260803.md`](design/servc_segment_experiment_20260803.md) | 분리 모델·하한율 절단 기각, 제도 특징 채택 |
| 용역 2025년 연도 홀드아웃 | [`servc_year_holdout_2025_20260803.md`](design/servc_year_holdout_2025_20260803.md) | 공고 건당 오차 분포, 연초 성능 저하 |
| 제한경쟁 진단과 난수 구조 | [`servc_restricted_competition_20260803.md`](design/servc_restricted_competition_20260803.md) | 참여업체 수·복수예가 난수 분해, 세부분류 특징 배선 |
| 손실함수와 반복 발주 이력 | [`servc_repeat_procurement_20260803.md`](design/servc_repeat_procurement_20260803.md) | Huber 채택, 재발주 이력 6종, 공고명 텍스트 기각 |
| 예측 구간 보정 측정 | [`servc_prediction_interval_20260804.md`](design/servc_prediction_interval_20260804.md) | 분위 회귀 피복률 실패, 등각예측 보정, API·UI 노출 완료 |
| MLOps 알림 설계 | [`mlops_notification_20260805.md`](design/mlops_notification_20260805.md) | Arq 워커 운영 알림 구현 완료. 웹훅 배선·테스트·Slack 수신 검증 완료 |
| 전량 재적합 결함 | [`servc_refit_on_full_20260805.md`](design/servc_refit_on_full_20260805.md) | 서빙 모델이 최신 20% 미학습. 편향 없는 확인에서 MAE -7.12% |
| 학습·서빙 특징 값 대조 | [`servc_feature_parity_20260805.md`](design/servc_feature_parity_20260805.md) | inst_sample_cnt 가 서빙에서 항상 0 이던 결함, 운영 MAE -6.1% |
| 기관 이력 시간 가중 | [`servc_rolling_institution_20260805.md`](design/servc_rolling_institution_20260805.md) | 고정 창 기각 유지, 전량 재적합 후 지수감쇠 재판정 |
| 용역 기각 후보 재검증 | [`servc_unbiased_candidate_recheck_20260805.md`](design/servc_unbiased_candidate_recheck_20260805.md) | 리프 255와 지수감쇠 배선·재학습·운영 쌍대 검증·승격 |
| 물품 모델 재학습 | [`thng_retraining_20260806.md`](design/thng_retraining_20260806.md) | 34특징 LightGBM 재학습·운영 쌍대 검증·승격 |
| 카테고리 모델 커버리지 | [`category_model_coverage_20260810.md`](design/category_model_coverage_20260810.md) | 공사 전용 모델 부재, 물품 실측 미갱신, 학습 라우팅 결함 수정 |
| 하이퍼파라미터 탐색 | [`servc_hyperparam_search_20260804.md`](design/servc_hyperparam_search_20260804.md) | 좌표 하강 17회, 점 추정·분위 파라미터 분리, 리프 상향은 운영 실측 후 기각 |
| 용역 하한율 가용성 | [`servc_lwlt_availability_20260804.md`](design/servc_lwlt_availability_20260804.md) | 대체 API 검증만 유효. "76.8% 미표기" 판정은 2026-08-10 폐기 |
| 하한율 결측 메커니즘 재분해 | [`servc_lwlt_missing_mechanism_20260810.md`](design/servc_lwlt_missing_mechanism_20260810.md) | 예가방식으로 결측의 99.1% 설명. 첨부문서 파싱 불필요, 축 종결 |
| 초과분 타깃 실험 | [`servc_excess_target_20260810.md`](design/servc_excess_target_20260810.md) | 기각(MAE +0.0364). 적중률만 +0.2687%p 개선되어 목적함수 축 근거 확보 |
| quantile alpha 스윕 | [`servc_quantile_alpha_20260810.md`](design/servc_quantile_alpha_20260810.md) | 기각. 홀드아웃 0.45 최적이나 운영 쌍대 판별 불가. 학습·서빙 특징 괴리 단서 확보 |
| 판정 도구 특징 시점 조사 | [`servc_paired_asof_gap_20260810.md`](design/servc_paired_asof_gap_20260810.md) | 정적 특징 완전 일치, 이력만 시점 차이. as-of 가 오히려 나빠 분포 이동 가설 기각 |
| 홀드아웃 분할 간 산포 | [`servc_split_variance_20260810.md`](design/servc_split_variance_20260810.md) | 분할 산포 0.0074 가 시드 산포의 7.4배. 홀드아웃 최소 감지 차이 기준 변경 |
| 홀드아웃·운영 MAE 격차 규명 | [`servc_holdout_serving_gap_20260810.md`](design/servc_holdout_serving_gap_20260810.md) | 학습만 적용되는 낙찰률 [70,110] 필터가 격차 0.17 전부를 설명. 판정용·보고용 표본 분리 |

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
| 공고 검색 성능 개선 | [`2026-08-09_bid_search_meilisearch_handoff.md`](handoff/2026-08-09_bid_search_meilisearch_handoff.md) | Meilisearch 구현, 초기 색인·P95 검증 절차 |
| 용역 모델 튜닝 인수인계 | [`2026-08-10_servc_tuning_handoff.md`](handoff/2026-08-10_servc_tuning_handoff.md) | 다섯 축 기각 근거, 홀드아웃 판정 기준 0.0074 상향, 남은 사용자 결정 |
| 쌍대 표본 기준 착수 지시 | [`2026-08-11_paired_sample_filter_todo.md`](handoff/2026-08-11_paired_sample_filter_todo.md) | 판정용·보고용 표본 분리 반영. 코드 변경 지점, 검증 절차, 금지 사항 |
| legacy SSE 이관 착수 지시 | [`2026-08-12_legacy_sse_migration_task.md`](handoff/2026-08-12_legacy_sse_migration_task.md) | GET /chatbot/stream 제거 완료. 정본 POST /chat/stream 전면 이관 및 벤치마크 기준선 갱신 |
| P0 후속 마감 이후 착수 목록 | [`2026-08-13_next_session_todo.md`](handoff/2026-08-13_next_session_todo.md) | A1~A5 병합 이후 잔여 과제. 신 제도 표본 1.276% 실측, 미병합 브랜치 처분, 컷오버 점검 |
| 추후 작업 정본 백로그 | [`2026-08-13_future_work_backlog.md`](handoff/2026-08-13_future_work_backlog.md) | **현재 정본.** 수집 안정화 관찰, P1 다중 워커 기각 이후 코드 경로 프로파일링, OOS 게이트와 저장소 잔여물의 의존 순서 |
| GPT 코디네이션 세션 인수인계 | [`2026-08-13_gpt_coordination_handoff.md`](handoff/2026-08-13_gpt_coordination_handoff.md) | 기능 기준 `d82a638`. 완료·기각 결과, Git·Docker·Orca 종료 상태, 다음 Task 사양과 재개 명령 |
| 예측 P95 병목 감사 | [`2026-08-13_prediction_p95_diagnosis.md`](handoff/2026-08-13_prediction_p95_diagnosis.md) | /predict P95 627ms 원인(스레드 미제한·특징 3중 구축·이중 프리로드), 최소 수정 후보 A~E, 재측정 매트릭스 1/2/4/10 |
| 용역 OOS 준비도 판정 | [`2026-08-13_servc_oos_readiness_gate.md`](handoff/2026-08-13_servc_oos_readiness_gate.md) | 현행 champion OOS 후보 2건으로 판정 불가. 수집 백필과 3,098건 축적을 다음 게이트로 확정 |
| 수동 재학습 API 재구현 계획 | [`2026-08-13_retrain_api_reimplementation_plan.md`](handoff/2026-08-13_retrain_api_reimplementation_plan.md) | 구 브랜치 전체 병합을 기각하고 최신 main의 9파일 최소 이식 범위와 검증 절차 확정 |
| 외부 정적 분석 검증 | [`2026-08-14_gpt_analysis_verification.md`](handoff/2026-08-14_gpt_analysis_verification.md) | GPT 5.6 저장소 감사 대조. 2026-08-04 P95 19.1ms 를 현행 근거로 쓰지 말 것, cron 중복은 해결됨, 교정된 실행 순서 |
| 수집 관찰 1회차 | [`2026-08-14_collection_observation_round1.md`](handoff/2026-08-14_collection_observation_round1.md) | 정기 수집 실측. 완료 기준을 최신 개찰 시각 전진에서 개찰 건수 증가로 교체한 근거 |
| Servc OOS 필터 진단 | [`2026-08-14_servc_oos_filter_diagnosis.md`](handoff/2026-08-14_servc_oos_filter_diagnosis.md) | **유효 OOS 2건 서술 폐기.** 실측 1,194건, 전환율 86.02%, 3,098 도달 약 14.0영업일. 08-03 공고 수집 공백이 조인 탈락 원인 |

## 4. ops/

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| Phase 7 검증 보고서 | [`phase7_cutover_report_20260804.md`](ops/phase7_cutover_report_20260804.md) | 무손실·레이턴시·크로스 플랫폼 판정 근거 |
| 크로스 플랫폼 가이드 | [`cross_platform_guide.md`](ops/cross_platform_guide.md) | macOS·Windows 재현 및 검증 절차 |
| 모델 승격·롤백 런북 | [`model_promotion_runbook.md`](ops/model_promotion_runbook.md) | 승격 게이트, 쌍대 비교 절차, 롤백 왕복 |
| 스냅샷 재집계 비용 | [`snapshot_rebuild_cost_20260806.md`](ops/snapshot_rebuild_cost_20260806.md) | 주간 재집계로 506초에서 135.8초. 날짜 축 확장·LIKE 제거 기각, 증분 집계 타당성 판정(8절) |
| Orca 오케스트레이션 실행 지침 | [`orca_orchestration_playbook.md`](ops/orca_orchestration_playbook.md) | 다중 섹션 병렬 운영 절차. 작업 분해, 모델·effort 배정, 감독, 접합부 검증, 함정 12건 |
| 에이전트 워커 기동 참조 | [`agent_worker_launch_reference.md`](ops/agent_worker_launch_reference.md) | 제공자별 기동 경로와 모델 ID, 오해하기 쉬운 신호, `worker-start` 차단 시 inject 우회. **기동 불가 판정 전에 필독** |

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
