# refac_bid_box 문서 인덱스

> **작성일**: 2026-07-31
> **정정일**: 2026-09-02
> **버전**: v1.4.0
> **상태**: Phase 0~6 완료 / Phase 7 컷오버 보류
> **적용 범위**: `bid_box` (Django) → `refac_bid_box` (FastAPI + SSR/HTMX) 전환

---

## 문서 목록

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| **운영 상태 정본** | [`context/CURRENT_STATE.md`](context/CURRENT_STATE.md) | **단일 진실 원천(SSOT).** 현재 구현 상태, 테스트/CI, 런타임 지표 |
| **리팩토링 설계서** | [`design/REFACTORING_DESIGN.md`](design/REFACTORING_DESIGN.md) | 전체 리팩토링 청사진 (설계 기준선) |
| **프론트엔드 결정** | [`design/FRONTEND_DECISION.md`](design/FRONTEND_DECISION.md) | SSR+HTMX 확정, React SPA 중단 |
| **공고 검색 전환** | [`handoff/2026-08-09_bid_search_meilisearch_handoff.md`](handoff/2026-08-09_bid_search_meilisearch_handoff.md) | Meilisearch 읽기 모델 구현 및 초기 색인 검증 절차 |

---

## 폴더 구조

```
docs/
├── README.md
├── servc_model_status.md
├── context/
├── design/
├── migration/
├── ops/
├── analysis/
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
| HTMX 이행 계획 | [`htmx_migration_plan_20260823.md`](design/htmx_migration_plan_20260823.md) | SSR+HTMX 목표 대비 도입도 0% 실태, 전면/선별/포기 3안 비교와 공수 추정. 도입 여부는 미결정 |
| KB 증분 색인 설계·실측 | [`kb_incremental_indexing_20260806.md`](design/kb_incremental_indexing_20260806.md) | 전량 재구축을 본문 SHA256 기반 증분 색인으로 교체, 변경 0건 시 재임베딩 회피 |
| 원본 테스트 재현 현황 | [`original_test_parity_20260804.md`](design/original_test_parity_20260804.md) | 원본 테스트 이름 기준 커버리지 122/131, 구조적 제외 9건과 근거 |
| RAG 한국어 임베딩 교체 | [`rag_embedding_korean_20260806.md`](design/rag_embedding_korean_20260806.md) | top-5 4%(MiniLM) -> 100%(bge-m3) 실측, 임베딩 교체·운영 재색인 |
| 원천 데이터 2025-01 체제 전환 | [`servc_2025_source_regime_shift_20260811.md`](design/servc_2025_source_regime_shift_20260811.md) | 2025-01 경계로 다수 필드 값 구성이 계단식 전환, 학습용 `lwlt_rate` 포함 |
| 학습 사용 필드 부재 표기 감사 | [`servc_absence_notation_audit_20260811.md`](design/servc_absence_notation_audit_20260811.md) | 13개 필드 부재 표기 접힘 전수 점검, train/serve 불일치 없음. 숫자형 결측 정보 손실 유보 |
| CatBoost L1 앙상블 | [`servc_ensemble_catboost_l1_20260809.md`](design/servc_ensemble_catboost_l1_20260809.md) | L1 목적함수로 희석이 줄어도 앙상블 여지 없음, 앙상블 축 종결 |
| 오차 집중 진단 | [`servc_error_concentration_20260807.md`](design/servc_error_concentration_20260807.md) | 오차가 일반용역 x 얕은 기관 이력에 집중, 개선 상한은 전체 MAE 6~8% |
| 제도 플래그 특징 홀드아웃 | [`servc_flag_features_holdout_20260811.md`](design/servc_flag_features_holdout_20260811.md) | 플래그 3종 특징 추가가 분할 산포 안이라 기각·코드 복원 |
| 플래그 표기·실질 판정 | [`servc_flag_notation_verdict_20260811.md`](design/servc_flag_notation_verdict_20260811.md) | 두 플래그의 2025년 전환: 하나는 실질 구성 변화, 하나는 표기 이동 |
| 일반용역 얕은 이력 신호 | [`servc_general_service_signal_20260807.md`](design/servc_general_service_signal_20260807.md) | 해당 셀에 남은 수치 신호 없음, 현재 특징 집합으로는 상한 6~8% 도달 불가 |
| quantile 목적함수 재탐색 | [`servc_hyperparam_quantile_20260807.md`](design/servc_hyperparam_quantile_20260807.md) | quantile(0.5) 하 좌표 하강 8축, 홀드아웃 우세가 운영 쌍대에서 부호까지 뒤집혀 기각 |
| 기관 x 소분류 교차 | [`servc_inst_clsfc_cross_20260809.md`](design/servc_inst_clsfc_cross_20260809.md) | 교차 셀이 잔차를 가르나 전년 오프셋이 다음 해로 전이되지 않아 기각 |
| 예측구간 기준선 감사 | [`servc_interval_baseline_audit_20260811.md`](design/servc_interval_baseline_audit_20260811.md) | 두 측정 차이는 표본 수·DB 엔진 전환이 원인, 모델·데이터 증분 아님 |
| 예측구간 집단별 품질 | [`servc_interval_by_group_20260806.md`](design/servc_interval_by_group_20260806.md) | 구간이 결측/보유 집단에 이미 반응, 다중 비교 보정 후 잔차 없음 |
| 분포 예측 계열 기각 | [`servc_interval_coverage_recheck_20260811.md`](design/servc_interval_coverage_recheck_20260811.md) | LightGBMLSS·NGBoost 도입 기각, 80.32% 피복률 수치는 저장소에 부재 |
| 손실함수 quantile 승격 | [`servc_loss_function_20260807.md`](design/servc_loss_function_20260807.md) | huber -> quantile(0.5) 승격 완료, 운영 쌍대 2개 연도 통과 |
| 하한율 결측 재분해(체제 후) | [`servc_lwlt_missing_remechanism_20260811.md`](design/servc_lwlt_missing_remechanism_20260811.md) | 2025-01 이후에도 제도적 부재 99.98% 유지, 지시자 추가 불필요 |
| 하한율 결측 잔차 진단 | [`servc_lwlt_residual_diagnosis_20260806.md`](design/servc_lwlt_residual_diagnosis_20260806.md) | 결측 집단 큰 오차는 편향 아닌 산포, 편향 보정 계열 전면 기각 |
| 비예가 학습 프레임 원인 | [`servc_nonprearng_population_cause_20260812.md`](design/servc_nonprearng_population_cause_20260812.md) | 비예가는 목표 변수가 없어 학습에서 빠지는 게 옳고, 서빙 라우팅이 오류 |
| 쌍대 비교 provenance 가드 | [`servc_paired_provenance_guard_20260812.md`](design/servc_paired_provenance_guard_20260812.md) | fallback으로 자기 자신과 비교되는 허위 쌍대 판정 방지 계약 설계 |
| 사전규격 API 재수집 | [`servc_prespec_api_probe_20260809.md`](design/servc_prespec_api_probe_20260809.md) | 유일한 추론 시점 후보였으나 연결률 37.62%로 이득 없음, 재수집 기각 |
| 분위 모델 용량 재측정 | [`servc_quantile_capacity_20260811.md`](design/servc_quantile_capacity_20260811.md) | 분위 모델에 카테고리 설정 통로 개설, 리프 63 유지·상향 기각 |
| raw_data 후보 스크리닝 | [`servc_raw_data_candidate_screen_20260809.md`](design/servc_raw_data_candidate_screen_20260809.md) | 미사용 키 후보 18종 전량 탈락, raw_data 축 종결 |
| raw_data 채움률·키 조사 | [`servc_raw_data_key_audit_20260809.md`](design/servc_raw_data_key_audit_20260809.md) | 공고 99.93%·결과 16.55% 채움률, 미사용 키 후보 18종 확보 |
| raw_data 체제 전환 전수 확인 | [`servc_rawdata_regime_scan_20260811.md`](design/servc_rawdata_regime_scan_20260811.md) | 92종 필드 2025-01 전환 스캔, 학습 사용 필드에는 무전환 |
| 최근 구간 표본 가중 | [`servc_recency_weighting_20260806.md`](design/servc_recency_weighting_20260806.md) | 가중이 최소 감지 차이 미달·결측 집단 악화로 기각 |
| 학습 프레임 비예가 결손 | [`servc_training_frame_population_gap_20260811.md`](design/servc_training_frame_population_gap_20260811.md) | 학습 프레임이 비예가 공고를 잃는 관측 확정, 원인 규명은 후속 문서 |
| 미사용 제도 플래그 감사 | [`servc_unused_rawdata_field_audit_20260811.md`](design/servc_unused_rawdata_field_audit_20260811.md) | 미사용 플래그 5개가 잔차에 3년 일관 편향, 새 축 개시 |
| SSE 첫 토큰 대책 | [`sse_first_token_20260805.md`](design/sse_first_token_20260805.md) | 첫 토큰 지연이 사고(thinking) 토큰·생성 루프 때문임을 규명, 대책 적용 |
| 물품 특징 값 감사 | [`thng_feature_value_audit_20260811.md`](design/thng_feature_value_audit_20260811.md) | 물품 학습 특징 34개 중 17개 상수, 성능 손실은 아니나 기회 손실 확정 |
| 물품 parquet 재생성 회수 감사 | [`thng_parquet_recovery_audit_20260811.md`](design/thng_parquet_recovery_audit_20260811.md) | 회수 28,547건 판정 재현, 실효 14,766건이며 전부 시간순 홀드아웃에 포함 |

## 2. migration/

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| DB 마이그레이션 | [`db_migration_runbook.md`](migration/db_migration_runbook.md) | 덤프/복원/검증 |
| ML/Chroma 검증 | [`ml_weights_verification.md`](migration/ml_weights_verification.md) | 체크섬·회귀 테스트 |
| Django 마이그레이션 히스토리 | [`django_migration_history.md`](migration/django_migration_history.md) | 원본 19개 마이그레이션 목록과 변경 내용, Alembic 기준선 추적 기록 |
| 인코딩 손상 분석 | [`encoding_corruption_analysis.md`](migration/encoding_corruption_analysis.md) | 건설 낙찰 결과 1,244,778행 손상, 복구 불가 확정·표시 계층 제외 처리 |

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
| 추후 작업 백로그 (구 정본) | [`2026-08-13_future_work_backlog.md`](handoff/2026-08-13_future_work_backlog.md) | 과거 백로그 (현재 정본은 `docs/context/CURRENT_STATE.md` 참조). 수집 안정화 관찰, P1 다중 워커 기각 이후 코드 경로 프로파일링 |
| GPT 코디네이션 세션 인수인계 | [`2026-08-13_gpt_coordination_handoff.md`](handoff/2026-08-13_gpt_coordination_handoff.md) | 기능 기준 `d82a638`. 완료·기각 결과, Git·Docker·Orca 종료 상태, 다음 Task 사양과 재개 명령 |
| 예측 P95 병목 감사 | [`2026-08-13_prediction_p95_diagnosis.md`](handoff/2026-08-13_prediction_p95_diagnosis.md) | /predict P95 627ms 원인(스레드 미제한·특징 3중 구축·이중 프리로드), 최소 수정 후보 A~E, 재측정 매트릭스 1/2/4/10 |
| 용역 OOS 준비도 판정 | [`2026-08-13_servc_oos_readiness_gate.md`](handoff/2026-08-13_servc_oos_readiness_gate.md) | 현행 champion OOS 후보 2건으로 판정 불가. 수집 백필과 3,098건 축적을 다음 게이트로 확정 |
| 수동 재학습 API 재구현 계획 | [`2026-08-13_retrain_api_reimplementation_plan.md`](handoff/2026-08-13_retrain_api_reimplementation_plan.md) | 구 브랜치 전체 병합을 기각하고 최신 main의 9파일 최소 이식 범위와 검증 절차 확정 |
| 외부 정적 분석 검증 | [`2026-08-14_gpt_analysis_verification.md`](handoff/2026-08-14_gpt_analysis_verification.md) | GPT 5.6 저장소 감사 대조. 2026-08-04 P95 19.1ms 를 현행 근거로 쓰지 말 것, cron 중복은 해결됨, 교정된 실행 순서 |
| 수집 관찰 1회차 | [`2026-08-14_collection_observation_round1.md`](handoff/2026-08-14_collection_observation_round1.md) | 정기 수집 실측. 완료 기준을 최신 개찰 시각 전진에서 개찰 건수 증가로 교체한 근거 |
| Servc OOS 필터 진단 | [`2026-08-14_servc_oos_filter_diagnosis.md`](handoff/2026-08-14_servc_oos_filter_diagnosis.md) | **유효 OOS 2건 서술 폐기.** 실측 1,194건, 전환율 86.02%, 3,098 도달 약 14.0영업일. 08-03 공고 수집 공백이 조인 탈락 원인 |
| 2026-08-14 후반 세션 인수인계 | [`2026-08-14_late_session_handoff.md`](handoff/2026-08-14_late_session_handoff.md) | 레이턴시 게이트 규약 제정, GC freeze 채택, SSE 기준선, 워커 배정 정책. **성능 작업 착수 전 필독** |
| 2026-08-22 P95·워커 감시 인수인계 | [`2026-08-22_p95_and_worker_supervision_handoff.md`](handoff/2026-08-22_p95_and_worker_supervision_handoff.md) | 최신 G3 게이트 결과, Terra Medium·Gemini Medium 운영 정책, c1·c2·c4 회귀 원인 분리 순서 |
| 세션 TODO (2026-08-01) | [`2026-08-01_session_todo.md`](handoff/2026-08-01_session_todo.md) | 재개 방법·완료 상태. Phase 0~6 완료, Phase 7 검증 잔존 |
| 백필 재개 안내 | [`2026-08-02_backfill_resume.md`](handoff/2026-08-02_backfill_resume.md) | 입찰공고 10년치 결손 상태와 중단 시점 현황, 재개 명령 |
| 용역 진단 재개 인수인계 | [`2026-08-06_servc_diagnosis_handoff.md`](handoff/2026-08-06_servc_diagnosis_handoff.md) | 잔차 구조 진단 완료, 5개 접근 기각·모델 변경 없음 |
| KB 커버리지 인수인계 | [`2026-08-07_kb_coverage_handoff.md`](handoff/2026-08-07_kb_coverage_handoff.md) | 50만 건 색인(499,195건, top-5 98.0%), 테스트의 운영 Slack 경고 발신 문제 해결 |
| 손실함수 승격 절차 인수인계 | [`2026-08-07_servc_loss_function_handoff.md`](handoff/2026-08-07_servc_loss_function_handoff.md) | quantile(0.5) 승격 완료 기록. 결과 정본은 설계 문서 8장 |
| 다음 축 인수인계 | [`2026-08-07_servc_next_axis_handoff.md`](handoff/2026-08-07_servc_next_axis_handoff.md) | 승격 이후 남은 개선 축, 하이퍼파라미터·앙상블·교차·raw_data·재수집 전부 기각 |
| 병행 세션 조율 | [`2026-08-09_parallel_session_coordination.md`](handoff/2026-08-09_parallel_session_coordination.md) | 일일 자동화와 raw_data 키 조사가 같은 트리를 밟지 않도록 범위 분리 |
| 2026-08-11 저녁 세션 인수인계 | [`2026-08-11_evening_session_handoff.md`](handoff/2026-08-11_evening_session_handoff.md) | Orca 4섹션 결과. 제도 플래그 기각, 원천 전환이 표기 변경으로 정정 |
| 2026-08-11 다중 섹션 인수인계 | [`2026-08-11_multi_section_handoff.md`](handoff/2026-08-11_multi_section_handoff.md) | Task 4건 완료·병합은 사용자 승인 대기 |
| 토큰 리셋 후 착수 목록 | [`2026-08-11_next_session_todo.md`](handoff/2026-08-11_next_session_todo.md) | 하한율 결측 재분해 최우선 등 착수 후보 우선순위 |
| 미병합 브랜치 감사 보고 | [`2026-08-13_branch_audit_report.md`](handoff/2026-08-13_branch_audit_report.md) | fix/arq-worker-compose·task-976479dbe8cb 내용과 main 흡수 확인 |
| 예측 계측·c10 벤치마크 | [`2026-08-13_p1_predict_instrumentation.md`](handoff/2026-08-13_p1_predict_instrumentation.md) | /predict 구간 계측 통일과 c10 P95 199.18ms 목표 실패, 후속 워커 판정 |
| Cerebras 워커 연동 점검 | [`2026-08-14_cerebras_gemma4_worker_setup.md`](handoff/2026-08-14_cerebras_gemma4_worker_setup.md) | Gemma-4 31B 워커 환경 구성과 실측 점검 |
| 2026-08-14 세션 인수인계 | [`2026-08-14_session_handoff.md`](handoff/2026-08-14_session_handoff.md) | 마이크로배칭·Servc OOS 재측정·c10 tail 원인 규명 등 완료 내역 |
| 코디네이터 토큰 소진 인수인계 | [`2026-08-15_coordinator_token_exhaustion_handoff.md`](handoff/2026-08-15_coordinator_token_exhaustion_handoff.md) | 주간 한도 97% 소진, 워커 산출물은 격리 브랜치 대기·main 안전 |
| 무료 워커 builder 경합 | [`2026-08-20_free_worker_builder_bakeoff.md`](handoff/2026-08-20_free_worker_builder_bakeoff.md) | 무료 모델 10종 동일 과제 경합, 연속 이탈 카운터 구분이 변별 지점 |
| OpenRouter 워커 자격 검증 | [`2026-08-20_openrouter_worker_qualification.md`](handoff/2026-08-20_openrouter_worker_qualification.md) | 무료 워커 probe·모델 재고 대조, 워커 보고 오기 정정 |
| ORM Mapped 종료 인수인계 | [`2026-08-21_orm_mapped_shutdown_handoff.md`](handoff/2026-08-21_orm_mapped_shutdown_handoff.md) | ORM Mapped 전환 완료, 스키마 drift 0건·데이터 보존 검증 통과 |
| 최신 main 후속 감사 | [`2026-08-22_post_1a45ad5_audit.md`](handoff/2026-08-22_post_1a45ad5_audit.md) | 신규 29개 커밋 검토, P0 없음·provenance 결박 P1 1건과 P2 잔여 |
| 후속 감사 항목 처리 | [`2026-08-23_followup_audit_closure.md`](handoff/2026-08-23_followup_audit_closure.md) | 5트랙 처리, P1 런타임 소스 provenance 등 병합 |
| 잔여 과업 명세 | [`2026-08-23_next_work_spec.md`](handoff/2026-08-23_next_work_spec.md) | 다음 세션 착수 과업 6종과 착수 조건·완료 기준 |
| Ollama c4·RAG 계측 인수인계 | [`2026-08-23_ollama_c4_rag_segments.md`](handoff/2026-08-23_ollama_c4_rag_segments.md) | Ollama 직렬화로 두 측정이 병렬 불가한 근거와 구간 분리 설계 |
| Orca 후속 작업 인수인계 | [`2026-08-23_orca_coordinator_handoff.md`](handoff/2026-08-23_orca_coordinator_handoff.md) | P1 benchmark provenance 결박 구현, main 병합 대기 |
| 코디네이터 토큰 소진 인수인계 v2 | [`2026-08-23_orca_coordinator_token_exhaustion_handoff_v2.md`](handoff/2026-08-23_orca_coordinator_token_exhaustion_handoff_v2.md) | P1 결박 병합 완료, P2 start/end provenance 완료·Level 1 게이트 대기 |
| 감사 보완 통합·종료 인수인계 | [`2026-08-24_audit_remediation_shutdown.md`](handoff/2026-08-24_audit_remediation_shutdown.md) | 공통 provenance·Orca 경계·RAG·Arq 하네스 통합, 재측정·병합 미수행 |
| CI 복구·감사 재검증 | [`2026-08-24_ci_crossplatform_and_audit_reverify.md`](handoff/2026-08-24_ci_crossplatform_and_audit_reverify.md) | 크로스 플랫폼 CI 결함 3건 수정, 감사 13항목 재검증 병합 |
| 2026-08-24 세션 종료 인수인계 | [`2026-08-24_session_close.md`](handoff/2026-08-24_session_close.md) | 감사 13항목 해소·3플랫폼 CI green·Arq 기준선·e2b 비교 보류 |
| 기관 낙찰률 이력 구현 기록 | [`inst_hist_rate_impl_todo.md`](handoff/inst_hist_rate_impl_todo.md) | inst_hist_rate 구현 위치와 결정 사항, TODO에서 기록 문서로 전환 |
| 2026-08-24 감사·기준선 세션 | [`session_20260824_audit_p1_and_calibration.md`](handoff/session_20260824_audit_p1_and_calibration.md) | 감사 P1 5건 해소·Arq 정식 기준선 확정·e4b/e2b 품질 실측 |
| **2026-08-25 감사 종결·검색 수정 세션 (current)** | [`session_20260825_audit_closeout_and_retrieval_fix.md`](handoff/session_20260825_audit_closeout_and_retrieval_fix.md) | 외부 감사 2건 25항목 종결, 벡터 검색 필터 미적용 결함 해소(근거 적중 15/16 -> 16/16), LLM 품질 v2 재측정으로 e2b 미승격 판정 |

---

## 4. ops/

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| **Wave G 세션 종료 인수인계** | [`handoff_20260902_wave_g_session_close.md`](ops/handoff_20260902_wave_g_session_close.md) | 2026-09-02 세션 종료. 남은 항목과 재기동 절차. 이전 인계보다 이 문서가 우선 |
| **웨이브별 해소 이력** | [`wave_resolution_history_20260902.md`](ops/wave_resolution_history_20260902.md) | CURRENT_STATE 에서 분리한 보안 P0·Wave A~G 해소 내역과 병합 커밋. 근거가 필요할 때만 조회 |
| **SSR 브라우저 E2E 범위 조사** | [`ssr_e2e_scope_survey_20260902.md`](analysis/ssr_e2e_scope_survey_20260902.md) | 대상 화면 15종, 도구 4종 비교, 공유 자원 충돌, 4단계 분할안. 권장 pytest-playwright. 착수는 합의 대기 |
| **레이턴시 게이트 측정 규약** | [`latency_gate_protocol.md`](ops/latency_gate_protocol.md) | **정본 규약.** 표본 `n >= 오염요청수 x 60`(예측 600, SSE 60), warmup 제외, 3회 최악값, c10 P95 100ms, 주변 부하 기록. 규약 제정 이전 측정은 통과·미달 어느 근거도 아님 |
| Phase 7 검증 보고서 | [`phase7_cutover_report_20260804.md`](ops/phase7_cutover_report_20260804.md) | 과거 Phase 7 이행 보고서 (HISTORICAL, 현재 판정 근거 사용 금지) |
| 크로스 플랫폼 가이드 | [`cross_platform_guide.md`](ops/cross_platform_guide.md) | macOS·Windows 재현 및 검증 절차 |
| 모델 승격·롤백 런북 | [`model_promotion_runbook.md`](ops/model_promotion_runbook.md) | 승격 게이트, 쌍대 비교 절차, 롤백 왕복 |
| 스냅샷 재집계 비용 | [`snapshot_rebuild_cost_20260806.md`](ops/snapshot_rebuild_cost_20260806.md) | 주간 재집계로 506초에서 135.8초. 날짜 축 확장·LIKE 제거 기각, 증분 집계 타당성 판정(8절) |
| Orca 오케스트레이션 실행 지침 | [`orca_orchestration_playbook.md`](ops/orca_orchestration_playbook.md) | 다중 섹션 병렬 운영 절차. 작업 분해, 모델·effort 배정, 감독, 접합부 검증, 함정 12건 |
| 에이전트 워커 기동 참조 | [`agent_worker_launch_reference.md`](ops/agent_worker_launch_reference.md) | 제공자별 기동 경로와 모델 ID, 오해하기 쉬운 신호, `worker-start` 차단 시 inject 우회. **기동 불가 판정 전에 필독** |
| Arq 임계값 도출 및 Provenance | [`arq_threshold_provenance_20260823.md`](ops/arq_threshold_provenance_20260823.md) | Arq 처리량/P95/실패율 게이트 임계값 도출 근거 및 provenance 규약 |
| Arq 브랜치 잔존 파일 회수 판정 | [`arq_branch_file_triage_20260814.md`](ops/arq_branch_file_triage_20260814.md) | integrate/arq-worker-cutover 고유 파일 4건, 전량 폐기 권고 |
| Codex 라우팅 브랜치 판정 | [`codex_task_routing_branch_verdict_20260814.md`](ops/codex_task_routing_branch_verdict_20260814.md) | feat/codex-task-routing 고유 파일 17건, 전량 폐기 권고 |
| 호스트 DB 이중화 제거 | [`db_dedup_host_container_20260809.md`](ops/db_dedup_host_container_20260809.md) | 호스트 MariaDB 3307 -> MySQL 8 Docker 3306 통일, 무손실 대조 포함 |
| 깊은 페이지 지연 개선 | [`deep_page_pagination_20260811.md`](ops/deep_page_pagination_20260811.md) | 도달 가능 페이지 상한(1000) 도입, page=100000 TTFB 1156ms -> 4ms |
| 환경변수 명세 | [`environment_variables.md`](ops/environment_variables.md) | 모든 환경변수의 단일 명세, 키명·용도·기본값 기록 |
| 게이트 규약 첫 재측정 | [`gate_remeasure_20260814.md`](ops/gate_remeasure_20260814.md) | 규약 제정 후 첫 적용, c10 P95 게이트 통과 |
| Git 브랜치 전략 | [`git_branching_strategy.md`](ops/git_branching_strategy.md) | 1인 작업 브랜치 모델과 커밋 메시지 규칙 (PR·dev 브랜치 없음) |
| 레이턴시 벤치마크 결과 | [`latency_benchmark.md`](ops/latency_benchmark.md) | 2026-08-02 측정 결과, 사전 집계 적용 후 응답 목표 달성 |
| 다중 에이전트 셋업 가이드 | [`multi_agent_setup.md`](ops/multi_agent_setup.md) | 5개 CLI 에이전트의 AGENTS.md 단일 진실 원천 자동 로드 매핑 |
| Orca 제어 평면 도구 규약 | [`orca_control_plane_tools.md`](ops/orca_control_plane_tools.md) | orca_taskctl·orca_model_router 인터페이스와 Task Intent 스키마 |
| Orca v2 토큰 최적화 설계 | [`orca_coordinator_token_optimization_v2.md`](ops/orca_coordinator_token_optimization_v2.md) | 자동 주입 축소·Coordinator/Worker Plane 분리 설계 정본 |
| 기각·반복 금지 목록 | [`orca_do_not_repeat.md`](ops/orca_do_not_repeat.md) | 기각 항목의 실측 근거 상세. 요약은 CURRENT_STATE 3장 |
| Task Capsule v2 규약 | [`orca_task_capsule_v2.md`](ops/orca_task_capsule_v2.md) | Capsule·worker_done·review_done 스키마와 자족적 실행 계약 |
| v2 구현 전 기준선 감사 | [`orca_token_optimization_v2_baseline_20260815.md`](ops/orca_token_optimization_v2_baseline_20260815.md) | 부트스트랩·자동 로드 AS-IS 기록 (T0) |
| v2 Cross-CLI 검증 | [`orca_v2_cross_cli_validation_20260815.md`](ops/orca_v2_cross_cli_validation_20260815.md) | 5대 CLI 진입점·검증기 정적 정합성 결정론적 검증 (T6) |
| 수신면 도구 독립 감사 | [`orca_v2_intake_tools_audit_20260815.md`](ops/orca_v2_intake_tools_audit_20260815.md) | 코디네이터 수신면 도구 4종 실행 검증, 결함 6건 보고 |
| Level 3 검토 축소 실험 | [`orca_v2_level3_reduction_experiment_20260815.md`](ops/orca_v2_level3_reduction_experiment_20260815.md) | 리뷰 계약 개선(팔 B)이 체크리스트 밖 결함 검출을 높이는지 실측 |
| Level 3 재실험 사전 등록 | [`orca_v2_level3_reduction_rerun_prereg_20260815.md`](ops/orca_v2_level3_reduction_rerun_prereg_20260815.md) | 저밀도 픽스처·채점 규칙 사전 고정 |
| Level 3 재실험 결과 | [`orca_v2_level3_reduction_rerun_results_20260815.md`](ops/orca_v2_level3_reduction_rerun_results_20260815.md) | 저밀도 환경에서 팔 B 검출 우위 확인 |
| 프록시 지표 원장 규약 | [`orca_v2_metrics_ledger.md`](ops/orca_v2_metrics_ledger.md) | append-only 원장 정의와 인터프리터 사용법 |
| 프록시 지표 원시 데이터 | [`orca_v2_metrics_ledger.jsonl`](ops/orca_v2_metrics_ledger.jsonl) | Dispatch마다 누적하는 원장 원시 JSONL |
| Reviewer 계층 첫 실행 | [`orca_v2_reviewer_plane_20260815.md`](ops/orca_v2_reviewer_plane_20260815.md) | Builder->Reviewer->Coordinator 구조 실사용, pass를 검토 축소 근거로 못 씀 |
| Reviewer 감도 시험 | [`orca_v2_reviewer_sensitivity_20260815.md`](ops/orca_v2_reviewer_sensitivity_20260815.md) | 체크리스트 계약 효과와 모델 효과 분리, 계약이 실효 |
| v2 런타임 스모크·부트스트랩 | [`orca_v2_runtime_smoke_20260815.md`](ops/orca_v2_runtime_smoke_20260815.md) | 5대 CLI 부트스트랩 문자 수 실측 (T6) |
| 게이트 규약·브랜치 감사 | [`phase7_gate_and_stale_branch_audit_20260814.md`](ops/phase7_gate_and_stale_branch_audit_20260814.md) | 성능 게이트 표본 수 규약 구멍 4건, 미병합 브랜치 판정 |
| Phase 7 레이턴시 재검증 | [`phase7_latency_recheck_20260813.md`](ops/phase7_latency_recheck_20260813.md) | SSE 게이트 통과, 예측 API 목표 실패 (후속 실측 포함) |
| 예측 GC 후보 설계 | [`phase8_predict_gc_candidates_20260814.md`](ops/phase8_predict_gc_candidates_20260814.md) | freeze·threshold·batch-disable 세 후보 정의와 채택 기준 |
| 예측 GC 채택 판정 | [`phase8_predict_gc_verdict_20260814.md`](ops/phase8_predict_gc_verdict_20260814.md) | freeze 채택, threshold 보류, batch-disable 기각 |
| /predict 마이크로배칭 | [`phase8_predict_microbatch_20260814.md`](ops/phase8_predict_microbatch_20260814.md) | 10건·5ms 창 마이크로배처 구현, c10 안정 통과 미확정 |
| c10 P95 표본 수 효과 | [`phase8_predict_p95_samplesize_effect_20260814.md`](ops/phase8_predict_p95_samplesize_effect_20260814.md) | n<=120에서 높은 표본 분산, n>=600에서 안정 수렴 |
| /predict tail 원인 판정 | [`phase8_predict_tail_diagnosis_20260814.md`](ops/phase8_predict_tail_diagnosis_20260814.md) | c10 tail이 단일 배치 스레드 직렬화(H2)임을 판정 |
| predict-tail 병합 판정 | [`phase8_predict_tail_merge_verdict_20260814.md`](ops/phase8_predict_tail_merge_verdict_20260814.md) | 계측 하네스 병합 불가, 벤치마크 스크립트만 선별 병합 |
| 예측 A/B 통제 벤치마크 | [`predict_ab_20260822.md`](ops/predict_ab_20260822.md) | 과거 baseline과 교차 A/B, 이전 c2/c4 미달 미재현 확인 |
| 예측 게이트 재측정 | [`predict_remeasurement_20260822.md`](ops/predict_remeasurement_20260822.md) | c1·c10 통과, c2/c4 회귀 판정선 미달로 승격 보류 유지 |
| 낙찰률 예측 고도화 실측 | [`prediction_model_tuning.md`](ops/prediction_model_tuning.md) | inst_hist_rate 연결로 용역 R2 0.026 -> 0.376, 추론 0.19ms |
| 재학습 E2E 검증 | [`retrain_pipeline_e2e.md`](ops/retrain_pipeline_e2e.md) | 배선 복구, 실제 DB에서 처음 동작시키며 결함 6건 수정 |
| 규모·무성실패 감사 | [`scale_and_silent_failure_audit_20260807.md`](ops/scale_and_silent_failure_audit_20260807.md) | 규모·실패 상황에서 무너지는 결함 유형 조사, 1건 수정·3건 미결 |
| SSE 게이트 기준선 | [`sse_gate_baseline_20260814.md`](ops/sse_gate_baseline_20260814.md) | c1 통과, c4는 로컬 Ollama 직렬화 병목으로 미달 |
| SSE 재측정·Ollama 병렬 | [`sse_rebaseline_and_ollama_parallel_20260814.md`](ops/sse_rebaseline_and_ollama_parallel_20260814.md) | c1 기준선 재수립(n=60), 병렬도 측정은 중단 |
| Uvicorn 워커 증설 후보 | [`uvicorn_worker_scaling_candidate_20260813.md`](ops/uvicorn_worker_scaling_candidate_20260813.md) | 3·4워커 실측으로 기각, 안전 기본값 1 유지 |

## 5. context/ 및 analysis/

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| **프로젝트 현재 운영 상태** | [`context/CURRENT_STATE.md`](context/CURRENT_STATE.md) | **단일 진실 원천(SSOT).** 현재 구현 상태, 테스트/CI 현황, 런타임 지표 |
| 과거 인수인계 (2026-08-18) | [`context/handoff_20260818.md`](context/handoff_20260818.md) | 이전 세션 컨텍스트 인수인계 기록 |
| 분석 보고서 디렉토리 | [`analysis/`](analysis/) | Arq 처리량, I/O 차단, c2/c4 배치 등 심층 성능 및 분석 보고서 모음 |

## 6. changelogs/

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| 작업 일지 | [`changelogs/work_log.md`](changelogs/work_log.md) | Phase별 누적 기록 |
| 작업 일지 개요 | [`changelogs/README.md`](changelogs/README.md) | 일지 디렉터리 목적과 기록 포맷 안내 |

---

## 권장 독해 순서

1. [`AGENTS.md`](../AGENTS.md)
2. [`context/CURRENT_STATE.md`](context/CURRENT_STATE.md) (현재 프로젝트 운영 상태 단일 진실 원천)
3. 관련 프로토콜 및 ADR ([`ops/latency_gate_protocol.md`](ops/latency_gate_protocol.md), [`design/FRONTEND_DECISION.md`](design/FRONTEND_DECISION.md), [`design/REFACTORING_DESIGN.md`](design/REFACTORING_DESIGN.md))
4. 최신 실측 증거 ([`analysis/`](analysis/), [`ops/`](ops/) 최신 보고서)
5. 과거 인수인계 및 작업 이력 ([`handoff/`](handoff/))

---

_본 인덱스는 살아있는 문서입니다._
