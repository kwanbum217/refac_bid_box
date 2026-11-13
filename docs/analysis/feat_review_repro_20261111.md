# 2026-11-09 기능 검토 미확인 항목 재현 보고서

> **작성일**: 2026-11-11
> **기준 커밋**: `5922bbff` (main, 2026-11-10)
> **작업 브랜치**: `kwanbum217/orca-repro`
> **범위**: 2026-11-09 보고서 두 건의 미확인 13개 항목 (I-ai F-05~F-09, I-data F-03·F-05~F-11)
> **방법**: 현재 코드 정독, 기존 시험 실행, 읽기 전용 DB 조회(`scripts/db_readonly_query.py`). 코드 수정 없음.
> **제약**: 격리 워크트리이므로 ML 가중치와 drift baseline 아티팩트가 없습니다. 운영 API 는 호출하지 않았습니다.

---

## 1. 요약

| 구분 | 건수 |
| --- | ---: |
| 대상 항목 | 13 |
| 재현됨 | 11 |
| 부분 재현 | 2 |
| 재현 안 됨 | 0 |
| 이미 해소 | 0 |

**핵심 결론**: 13개 중 11개가 현재 main 에서 그대로 재현됩니다. I-ai F-05 는 커밋 `7c2e0f93`(전용 모델 없는 분야 투찰가 추천 차단) 이후 서빙 측 서술이 달라져 부분 재현으로 판정했습니다. I-ai F-08 은 관측 훅이 추가됐으나 기본 폴백 정의는 그대로여서 재현됩니다.

| 항목 | 제목 | 원 등급 | 판정 | 수정 규모 | 결정 필요 |
| --- | --- | :---: | :---: | :---: | :---: |
| I-ai F-05 | 드리프트 감시 대상과 서빙 대상 불일치 | 중 | 부분 재현 | 중 | 아니오 |
| I-ai F-06 | 쌍대검정 파일 부재 시 승격 차단 | 중 | 재현됨 | 소 | 아니오 |
| I-ai F-07 | `/predict` 가 누락 특징을 기본값으로 채움 | 중 | 재현됨 | 소 | 예(422 계약) |
| I-ai F-08 | train/serve 기관 이력 폴백 정의 차이 | 중 | 재현됨 | 중 | 아니오 |
| I-ai F-09 | React 가 `features_used` 원문 노출 | 중 | 재현됨 | 소 | 아니오 |
| I-data F-03 | SSR 로그아웃의 이벤트 루프 블로킹 | 중 | 재현됨 | 소 | 아니오 |
| I-data F-05 | 자동화 구독 미구현 | 중 | 재현됨 | 대 | 예 |
| I-data F-06 | 수집 API `end_date` 단독 지정 무시 | 하 | 재현됨 | 소 | 아니오 |
| I-data F-07 | 대시보드 정적 상태·미동작 버튼 | 하 | 재현됨 | 소 | 아니오 |
| I-data F-08 | REST 공고 응답 표시 필드 누락 | 하 | 재현됨 | 중 | 예(계약 범위) |
| I-data F-09 | Meilisearch 삭제 미동기화·무알림 | 중 | 재현됨 | 중 | 아니오 |
| I-data F-10 | 비밀번호 변경·재설정·탈퇴 미구현 | 하 | 재현됨 | 대 | 예 |
| I-data F-11 | `/evaluations/rules` 무인증·무쿼터 | 하 | 재현됨 | 소 | 아니오 |

---

## 2. I-ai 항목 상세

### 2.1 I-ai F-05 드리프트 감시 대상과 서빙 대상 불일치 (원 등급 중)

- **현재 근거**
  - `src/ml/training_config.py:68-72` — `CATEGORY_MODEL_NAMES` 가 `Cnstwk` 를 `cnstwk_institution_v1` 로 매핑합니다.
  - `src/tasks/scheduled_tasks.py:961-963` — 드리프트 크론이 `CATEGORY_MODEL_NAMES` 전체를 돌며 `baseline_dir = registry_dir/model_name/baseline` 을 읽습니다.
  - `src/ml/model_registry.py:65-68` — `CATEGORY_DEFAULT_MODELS` 에는 `Thng`·`Servc` 만 있습니다.
  - `src/ml/model_registry.py:260-268` — 미등록 카테고리는 `"v25"` 로 폴백합니다. 다만 `src/ml/prediction_api.py:141-151` 의 `_require_supported_category` 와 `src/app/api/v1/predictions.py:632-636`, `:857-861` 이 먼저 차단하므로 `v25` 폴백은 공개 예측 경로에서 도달하지 않습니다.
- **원 보고서와 달라진 점**: 커밋 `7c2e0f93` 이 공사(Cnstwk) 예측을 422 로 차단했습니다. 따라서 "실제 서빙은 v25" 는 현재 코드와 맞지 않고, 정확히는 "감시 대상 `cnstwk_institution_v1` 에 대응하는 서빙 경로 자체가 없다" 입니다. 매핑 불일치라는 결함의 본질은 남아 있습니다.
- **실행**: `find ml_registry -type d -name baseline` → 0건. `find ml_registry -name 'feature_distributions*.json'` → 0건. 이 워크트리에서는 실제 PSI 판정을 재현할 수 없어 **주 저장소 또는 운영 baseline 재생성 필요**입니다.
- **판정**: 부분 재현.
- **수정 규모**: 중. **결정 필요**: 아니오.
- **수정 과업 후보**: 감시 매핑을 서빙 매핑에서 파생하거나, 서빙 불가 카테고리는 감시 대상에서 제외하고 기동 검사로 불일치를 막습니다.

### 2.2 I-ai F-06 쌍대검정 파일 부재 시 승격 차단 (원 등급 중)

- **현재 근거**: `src/ml/promotion.py:250-260` — `paired_verdict.json` 이 없으면 "운영 쌍대검정 미판정" 사유를 추가하고, `rejected` 면 기각, `approved` 가 아니면 판정 불가로 막습니다.
- **자산 현황**: `find ml_registry -name paired_verdict.json` → 1건(`servc_institution_v1/v_20260807_110637_435/paired_verdict.json`). 새 모델·카테고리는 이 파일 없이는 승격이 막힙니다.
- **실행**: `uv run pytest tests/test_promotion_gate.py -q -m 'not data_assets' -k "paired or verdict or evidence"` → **9 passed, 11 deselected**. `tests/test_promotion_gate.py:105-109` 가 파일 부재 시 차단을, `:112-123` 이 `force=True` 우회를 각각 고정합니다.
- **판정**: 재현됨. 원 보고서가 언급하지 않은 `force` 우회 통로도 시험으로 확인됩니다.
- **수정 규모**: 소(승격 런북에 판정 생성 절차 명문화). **결정 필요**: 아니오.
- **수정 과업 후보**: `scripts/promote_model.py` 의 판정 생성 절차를 런북에 넣고, `force` 사용 조건을 함께 기록합니다.

### 2.3 I-ai F-07 `/predict` 의 누락 특징 기본값 채움 (원 등급 중)

- **현재 근거**
  - `src/app/schemas/predictions.py:9-24` — 필수는 `presumed_price`·`base_price` 뿐이고 `category_code` 는 기본 `"Thng"` 입니다. `lwlt_rate`, 재발주 6종, 시점 특징은 받지 않습니다.
  - `src/ml/features.py:172-177` — 공고일시가 없으면 `pd.Timestamp.now()` 를 시점 기준으로 씁니다.
  - `src/ml/features.py:197-260` — `build_default_feature_map` 이 누락 특징을 기본값으로 채우고, `:258-260` 에서 `lwlt_rate=0.0`, `lwlt_rate_missing=1.0` 이 됩니다.
  - `src/app/api/v1/predictions.py:834-868` — 특징 누락을 거부하는 검증이 없습니다. 분야 지원 여부만 422 로 검사합니다.
  - `frontend/src/App.tsx:186-193` — React 가 세 필드만 보내 호출합니다.
- **실행**: `uv run pytest tests/test_backend_rest_fixes.py -q -m 'not data_assets' -k "predict_without_bid_ntce_dt"` → **1 passed**. `tests/test_backend_rest_fixes.py:193-218` 은 `presumed_price`·`base_price` 만 보낸 요청이 200 과 `feature_time_basis="request_time"` 을 돌려주는 것을 단언하므로, 기본값 채움 동작이 현재 계약으로 고정돼 있음을 확인했습니다.
- **판정**: 재현됨.
- **수정 규모**: 소. **결정 필요**: 예(필수 특징 누락 시 422 로 계약을 좁힐지 결정).
- **수정 과업 후보**: 누락 특징 거부 정책을 정한 뒤 검증을 추가하고, `feature_time_basis` 는 현행대로 유지합니다.
- **결정(2026-11-13)**: 누락 특징을 422 로 거부하지 않고 `build_default_feature_map` 기본값으로 채우는 현행 동작을 계약으로 유지하며, `/predict` 라우트와 `PredictionRequest` docstring 에 명시합니다.

### 2.4 I-ai F-08 train/serve 기관 이력 폴백 정의 차이 (원 등급 중)

- **현재 근거**
  - `src/ml/institution_history.py:480-538` — `lookup_institution_stats` 의 `fallback_definition` 기본값이 `FALLBACK_DEFINITION_CURRENT` 입니다. 표에 없는 기관은 `:531-538` 에서 365일 실시간 집계로 내려갑니다.
  - `src/ml/institution_history.py:189-190` — 학습 정의 이상치 범위는 50~120이고, 서빙 폴백은 0~100 배타입니다.
  - `src/ml/institution_history.py:272-300` — 학습 정의와 같은 `calculate_institution_win_rate_training_parity` 가 이미 있으나 서빙 기본 동작은 바꾸지 않습니다.
  - `grep -rn "fallback_definition=" src/` → 서빙 호출부가 `"training"` 을 넘기는 곳이 없습니다.
- **추가된 완화책**: `src/ml/institution_history.py:503`, `:531` 이 `record_institution_history_fallback`(`src/app/core/observability.py:1038`)으로 폴백 사유를 계측합니다. 커밋 `6a30db57` 이 쌍대 실측 스크립트와 시험을 추가했지만 기본 정의는 그대로입니다.
- **실행**: `uv run pytest tests/test_inst_fallback_paired.py -q -m 'not data_assets'` → **13 passed**. `tests/test_inst_fallback_paired.py:137-145` 가 기본값이 `current` 와 같고 `inst_sample_cnt=0.0` 임을 단언합니다.
- **DB 보조 확인**: `SELECT category, COUNT(*) FROM institution_win_rate_stats GROUP BY category` → `Cnstwk 10,418`, `Thng 15,406`, `Servc 13,450`. 표 미수록 기관 비율은 `bid_results` 대형 조인이 필요해 이번에도 측정하지 않았습니다.
- **판정**: 재현됨.
- **수정 규모**: 중. **결정 필요**: 아니오.
- **수정 과업 후보**: 서빙 폴백 기본값을 `training` 으로 전환하고, 표 미수록 기관 비율을 기존 계측 지표로 감시합니다.

### 2.5 I-ai F-09 React 의 `features_used` 원문 노출 (원 등급 중)

- **현재 근거**: `frontend/src/App.tsx:729-734` — "산출에 사용된 핵심 특징" 블록이 접힘 없이 항상 `JSON.stringify(predictionResult.features_used, null, 2)` 를 렌더합니다. 내부 특징명과 기관 이력 원값이 그대로 노출됩니다.
- **판정**: 재현됨.
- **수정 규모**: 소. **결정 필요**: 아니오.
- **수정 과업 후보**: 개발자 상세로 접거나 제거하고, 노출 정책을 상세 화면과 통일합니다.

---

## 3. I-data 항목 상세

### 3.1 I-data F-03 SSR 로그아웃의 이벤트 루프 블로킹 (원 등급 중)

- **현재 근거**
  - `src/app/api/ui.py:934-955` — `async def logout_submit` 이 `:946` 에서 `destroy_session(bidbox_session)` 을 직접 호출합니다.
  - `src/app/api/ui.py:958-984` — `async def mypage_logout_all` 이 `:974-975` 에서 `invalidate_all_sessions` 와 `destroy_session` 을 직접 호출합니다.
  - `src/app/core/security.py:554-567` — 두 함수 모두 Redis·DB 동기 호출입니다.
  - 같은 파일의 다른 인증 경로는 `asyncio.to_thread` 로 오프로드되어 있습니다(`src/app/api/ui.py:735-740`, `:863-879`).
- **시험 공백**: `grep -n "def test_" tests/test_ssr_auth_offload.py` → 2건(`:50` 로그인, `:74` 가입)뿐입니다. 로그아웃 경로는 검사하지 않습니다.
- **실행**: `uv run pytest tests/test_ssr_auth_offload.py -q -m 'not data_assets'` → 기존 2건 통과. 로그아웃 경로가 시험에 없다는 사실은 위 grep 으로 확인했습니다.
- **판정**: 재현됨.
- **수정 규모**: 소. **결정 필요**: 아니오.
- **수정 과업 후보**: 두 호출을 `await asyncio.to_thread(...)` 로 감싸고 로그아웃 오프로드 회귀 시험을 추가합니다.

### 3.2 I-data F-05 자동화 구독 미구현 (원 등급 중, 사용자 결정 대기)

- **현재 근거**: `src/app/models/chatbot.py:120-157` 에 `AutomationSubscription` ORM 이 있고 `src/app/models/__init__.py:16` 이 export 합니다. `grep -rn "automation_subscriptions\|AutomationSubscription" src/ scripts/` 결과는 모델·export·백업 대상 목록(`scripts/backup_recovery_core.py:31`)뿐이며 API·서비스·스케줄러 소비 코드가 없습니다.
- **실행**: `uv run python scripts/db_readonly_query.py --sql "SELECT COUNT(*) AS n FROM automation_subscriptions"` → **n=0**.
- **판정**: 재현됨(미구현).
- **수정 규모**: 대(구현) 또는 소(문서화). **결정 필요**: 예.
- **권장안**: G1 스키마 보존용 미사용 테이블임을 모델 주석과 문서에 명시하고, 구독 CRUD·스케줄 소비는 별도 결정으로 분리합니다.
- **결정(2026-11-13)**: `automation_subscriptions` 는 G1 스키마 보존용 미사용 테이블로 유지하며, 구독 기능은 범위에서 제외합니다. 모델 docstring 에 명시합니다.

### 3.3 I-data F-06 수집 API `end_date` 단독 지정 무시 (원 등급 하)

- **현재 근거**
  - `src/app/api/v1/bids.py:295-298` — `start_date` 와 `end_date` 를 각각 독립 쿼리로 노출합니다.
  - `src/app/services/collector_service.py:135-136` — `start_date is not None` 일 때만 `end_date` 를 쓰고, 없으면 체크포인트 경로로 가서 `:226` 에서 항상 `yesterday` 를 종료일로 돌려줍니다.
  - `tests/test_collector_catchup.py:86-100` — start·end 동시 지정만 검증합니다.
- **판정**: 재현됨.
- **수정 규모**: 소. **결정 필요**: 아니오.
- **수정 과업 후보**: `start_date` 없이 `end_date` 만 온 요청을 422 로 거부하거나 체크포인트 시작~지정 종료일로 창을 자릅니다.

### 3.4 I-data F-07 대시보드 정적 상태·미동작 버튼 (원 등급 하)

- **현재 근거**: `src/app/templates/bids/dashboard.html:82` 가 "정상" 배지를, `:86` 이 "안정" 문구를 하드코딩합니다. `:130` 의 "보고서 내보내기" 버튼에는 핸들러가 없습니다. `grep -n "health\|api/" src/app/templates/bids/dashboard.html` → 0건으로, 실제 점검 API `src/app/api/v1/health.py:294`(`/ready`)를 화면이 호출하지 않습니다.
- **판정**: 재현됨.
- **수정 규모**: 소. **결정 필요**: 아니오.
- **수정 과업 후보**: readiness 결과를 카드에 연결하고, 내보내기를 구현하거나 버튼을 제거합니다.

### 3.5 I-data F-08 REST 공고 응답 표시 필드 누락 (원 등급 하)

- **현재 근거**
  - `src/app/api/v1/bids.py:55-76` — 목록 직렬화에 `institution_region`, `participation_region_preview`, `participation_regions` 가 없습니다.
  - `src/app/api/v1/bids.py:275-289` — 상세 응답은 `bid`, `similar_bids`, `past_results`, `default_prediction_model` 만 반환합니다.
  - `src/app/services/bid_queries.py:1191-1197` — 서비스는 `contract_regime`, `award_method`, `followup_bids`, `restrictions`, `is_negotiation` 을 계산합니다.
  - `src/app/schemas/bids.py:31-45`, `:116-121` — 응답 스키마도 축소되어 있습니다.
- **판정**: 재현됨.
- **수정 규모**: 중(스키마 확장) 또는 소(docstring·OpenAPI 에 축소 계약 명시). **결정 필요**: 예(계약 확장 여부).
- **수정 과업 후보**: SSR 표시 필드를 응답에 포함하거나, REST 가 SSR 보다 좁다는 사실을 계약 문서에 고정합니다.
- **결정(2026-11-13)**: REST 공고 목록·상세 응답은 SSR 화면보다 좁은 축소 계약을 유지하며, 목록·상세 라우트와 응답 스키마 docstring 에 명시합니다.

### 3.6 I-data F-09 Meilisearch 삭제 미동기화·불일치 무알림 (원 등급 중)

- **현재 근거**
  - `src/app/services/search_index.py:441-466` — `sync_search_index` 가 `client.upsert` 만 호출합니다. `grep -rn "delete_documents\|documents/delete\|delete_index" src/app/services/search_index.py src/tasks/scheduled_tasks.py` → 0건입니다.
  - `src/tasks/scheduled_tasks.py:548-566` — 야간 건수 대조는 불일치 시 `logger.warning` 만 남기고 알림을 보내지 않습니다.
  - `src/tasks/scheduled_tasks.py:409` — `FOLLOWUP_KEYS` 에 검색 색인이 없어 `_mark_followup_failures` 로도 상태가 바뀌지 않습니다.
- **판정**: 재현됨.
- **수정 규모**: 중. **결정 필요**: 아니오.
- **수정 과업 후보**: 원본 삭제분 색인 제거 경로를 추가하고, 건수 불일치를 `notify` 경로로 승격합니다.

### 3.7 I-data F-10 비밀번호 변경·재설정·회원 탈퇴 미구현 (원 등급 하, 사용자 결정 대기)

- **현재 근거**: `src/app/api/v1/accounts.py:533-628` 은 가입(`:533`)·로그인(`:551`)·로그아웃(`:589`)·me(`:604`)·profile(`:609`)만 제공합니다. SSR 수정 화면(`src/app/api/ui.py:579-617`)도 프로필·정량 원자료만 다룹니다. `src/app/templates/accounts/mypage_edit.html:13` 은 "아이디와 비밀번호는 변경할 수 없습니다" 라고 명시합니다. `grep -rn "password_change\|change_password\|reset_password\|delete_account\|withdraw"` → 0건입니다.
- **판정**: 재현됨(미구현).
- **수정 규모**: 대. **결정 필요**: 예.
- **권장안**: 정책 확정 전까지 계정 자기관리 범위에서 제외한다는 결정을 문서에 남기고, 변경·재설정·탈퇴 API 는 별도 과업으로 분리합니다.
- **결정(2026-11-13)**: 계정 자기관리 범위에서 비밀번호 변경·재설정·탈퇴를 제외합니다. 관련 API 는 별도 과업으로 분리합니다.

### 3.8 I-data F-11 평가 규칙 메타 API 무인증·무쿼터 (원 등급 하)

- **현재 근거**: `src/app/api/v1/evaluations.py:2877-2918` — `list_evaluation_rules_meta` 는 `db` 의존성만 받고 `require_current_user`·`enforce_anonymous_api_quota` 가 없습니다. `bid_id` 가 있으면 `_get_bid_or_404`, `_demand_institution_for_bid`, `lookup_attachment_regime_for_bid` 를 수행합니다(`:2893-2909`). 같은 파일의 `/analyze` 는 `:2274`, `:2288` 에서 인증·쿼터를 적용하고 `/recommend` 는 `:2682` 에서 인증을 요구합니다.
- **판정**: 재현됨.
- **수정 규모**: 소. **결정 필요**: 아니오.
- **수정 과업 후보**: 익명 쿼터를 적용하거나 `bid_id` 파라미터를 인증 사용자 전용으로 분리합니다.

---

## 4. 수정 과업 후보 순서 제안

| 순서 | 묶음 | 항목 | 근거 |
| ---: | --- | --- | --- |
| 1 | 즉시 가능한 소규모 | I-data F-06, I-data F-07, I-data F-11, I-ai F-09 | 계약 변경 없이 코드·템플릿만 고칩니다. |
| 2 | 비동기 일관성 | I-data F-03 | 같은 파일에 이미 `to_thread` 선례가 있고 회귀 시험만 추가하면 됩니다. |
| 3 | 운영 절차 | I-ai F-06 | 코드 변경 없이 승격 런북에 판정 생성 절차를 명문화합니다. |
| 4 | 계약 결정 후 | I-ai F-07, I-data F-08 | 422 거부·스키마 확장 여부를 먼저 정해야 합니다. |
| 5 | 모델·감시 정합 | I-ai F-05, I-ai F-08 | 서빙 매핑과 폴백 정의를 동시에 바꾸고 쌍대 실측으로 검증해야 합니다. |
| 6 | 색인 정합 | I-data F-09 | 삭제 동기화와 알림 채널을 함께 넣어야 합니다. |
| 7 | 사용자 결정 대기 | I-data F-05, I-data F-10 | 구현 범위 자체를 먼저 확정해야 합니다. |

---

## 5. 재현 한계

1. **가중치·baseline 부재**: 이 워크트리에 `data/model_files/*/model.bin` 과 `ml_registry/*/baseline/` 이 없습니다. I-ai F-05 의 실제 PSI 판정과 I-ai F-07 의 실제 출력값은 **주 저장소 또는 운영 자산 필요**로 남깁니다.
2. **운영 API 미호출**: 화면 표시값은 코드 경로와 읽기 전용 DB 값으로만 재구성했습니다.
3. **대형 테이블 조인 회피**: I-ai F-08 의 표 미수록 기관 비율은 `bid_results` 전량 조인이 필요해 측정하지 않았습니다. `institution_win_rate_stats` 행 수만 보조로 확인했습니다.
4. **시험 공백은 결과로 기록**: I-data F-03·F-06·F-07·F-08·F-11 은 해당 경로를 직접 검증하는 시험이 없어 코드 정독과 기존 시험 대조로 판정했습니다.
