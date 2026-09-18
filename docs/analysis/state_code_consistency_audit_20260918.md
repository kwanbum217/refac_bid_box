# CURRENT_STATE 문서와 실제 코드 정합성 점검 보고서

> **작성일**: 2026-09-18
> **점검자**: Orca Worker (investigator, task_3eb0b73f1972)
> **점검 대상**: [docs/context/CURRENT_STATE.md](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/context/CURRENT_STATE.md), [docs/context/current_state_facts.yaml](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/context/current_state_facts.yaml)
> **점검 범위**: active 사실 2건(`negotiation_contract_support`, `drift_job`), blocked 사실 1건(`gate_g2`), 6.1절 알려진 미해결 사항(Unknowns) 5건, 문서-원장 간 상호 일치성
> **원칙**: 진실 우선순위(실제 코드 및 실측 아티팩트 > CURRENT_STATE.md > README.md > 과거 handoff). 발견된 불일치를 직접 수정하지 않고 목록·근거·권고만 작성함.

---

## 1. 점검 개요

본 보고서는 2026-09-18 기준 [CURRENT_STATE.md](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/context/CURRENT_STATE.md) 및 [current_state_facts.yaml](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/context/current_state_facts.yaml)에 수록된 과업 상태와 알려진 미해결 사항이 실제 저장소의 소스 코드, 설정, 테스트 및 실측 아티팩트와 일치하는지 정밀 점검한 결과입니다.

Task Capsule 계약에 따라 점검 대상은 active 사실 2건, blocked 사실 1건, 6.1절 unknowns 5건 및 사실 원장과의 정합성으로 한정하였으며, 이미 종결된 closed 사실 전량을 재검증하는 범위 확장은 배제하였습니다. 또한 불일치 판정 시 코드를 수정하지 않고 오직 문서의 수정 방향만을 권고합니다.

---

## 2. 점검 결과 총괄표

| 번호 | 점검 항목 | 문서상 상태 | 판정 | 코드 및 파일 근거 | 불일치/특이사항 요약 |
| :---: | :--- | :---: | :---: | :--- | :--- |
| 1 | `negotiation_contract_support` | active | **불일치** | [`src/app/services/evaluation_rules.py:301`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/app/services/evaluation_rules.py#L301)<br>[`src/app/services/evaluation_rules.py:587-633`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/app/services/evaluation_rules.py#L587-L633)<br>[`src/app/services/negotiation_stats.py:1-112`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/app/services/negotiation_stats.py#L1-L112)<br>[`src/app/schemas/evaluations.py:263-276`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/app/schemas/evaluations.py#L263-L276)<br>[`src/app/api/v1/evaluations.py:644-647`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/app/api/v1/evaluations.py#L644-L647)<br>[`src/app/templates/bids/detail.html:367-376`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/app/templates/bids/detail.html#L367-L376)<br>[`tests/test_negotiation_contract.py:1-92`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/tests/test_negotiation_contract.py#L1-L92) | 기능(판별·비율·변종·점수차단·참고분포)이 코드상 전 계층 구현 및 테스트 완료되었으나 여전히 active 상태이며, facts.yaml claim에 두 번째 문장이 누락됨. evidence에 구현 코드가 전무함. |
| 2 | `drift_job` | active | **불일치** | [`src/app/core/config.py:80`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/app/core/config.py#L80)<br>[`src/tasks/scheduled_tasks.py:626, 650-652`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/tasks/scheduled_tasks.py#L626)<br>[`docs/ops/psi_drift_monitoring.md:108`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/ops/psi_drift_monitoring.md#L108)<br>[`src/ml/training_config.py:1-212`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/ml/training_config.py#L1-L212)<br>[`.gitignore:198`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/.gitignore#L198) | scheduled_tasks.py 독스트링에 기본값 False 및 Thng baseline 부재 주석이 잔존함. 1순위 증거 문서(psi_drift_monitoring.md)가 Thng 부재로 기술되어 CURRENT_STATE와 충돌함. 증거 경로인 training_config.py에 baseline 내용 없음. |
| 3 | `gate_g2` | blocked | **일치 (증거 문서 일부 뒤처짐)** | [`docs/ops/cross_platform_guide.md:4-5`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/ops/cross_platform_guide.md#L4-L5)<br>[`.github/workflows/ci.yml:1-120`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/.github/workflows/ci.yml#L1-L120) | 장비 부재로 인한 blocked 판정 자체는 정상이나, evidence 문서인 cross_platform_guide.md의 CI 실행 갱신일(08-24, Run 32703096829)이 CURRENT_STATE(09-05, Run 33947859707)보다 과거로 뒤처져 있음. |
| 4 | Unknown 6.1.1 (Windows Docker Desktop 실기) | 미검증 | **일치** | [`docs/ops/cross_platform_guide.md:1-227`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/ops/cross_platform_guide.md#L1-L227) | 실기 장비 부재로 미검증 상태 유지 중이며 코드 및 환경 현황과 부합함. |
| 5 | Unknown 6.1.2 (RAG cold SQL) | 인덱스·힌트 적용 | **불일치** | [`docs/analysis/rag_coldsql_root_cause_20260913.md:24-25`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/analysis/rag_coldsql_root_cause_20260913.md#L24-L25)<br>[`docs/context/CURRENT_STATE.md:48, 94`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/context/CURRENT_STATE.md#L48)<br>[`docs/context/current_state_facts.yaml:127, 442`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/context/current_state_facts.yaml#L127) | 2장 Section 2에서 coldsql_metric과 coldsql_rerun이 모두 closed(종결)로 확정되었음에도 6.1절 미해결 사항에 잔존하여 상태적 모순 발생. 잔여 미해결 내용이 무엇인지 명시되지 않음. |
| 6 | Unknown 6.1.3 (손상 탐침 제거) | 구조적 제거 확정·효과 크기 미확정 | **일치** | [`src/rag/structured_data.py:807-835`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/rag/structured_data.py#L807-L835)<br>[`docs/analysis/aw2_probe_removal_effect_20260911.md:20-26`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/analysis/aw2_probe_removal_effect_20260911.md#L20-L26) | 마커 존재 시 corrupted_probe 0ms 달성은 코드 및 실측으로 확정되었으며, 잔여 분산으로 인한 총 시간 효과 크기 미확정 서술은 실제 조사 결과와 일치함. |
| 7 | Unknown 6.1.4 (측정 설계와 실행계획 조사) | 도구 완비·원인 미확정 | **불일치 (맥락 노후)** | [`docs/analysis/ax2_plan_instability_20260911.md:13-17`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/analysis/ax2_plan_instability_20260911.md#L13-L17)<br>[`docs/context/CURRENT_STATE.md:72, 96`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/context/CURRENT_STATE.md#L72)<br>[`src/app/services/dashboard.py:484`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/app/services/dashboard.py#L484) | compare-stats 매칭 쿼리 전환 원인은 미확정이나, 사전 집계 스냅샷 도입(compare_stats_snapshot 종결) 및 통계 신선도 정책 수립(mysql_stats_refresh_policy 종결)으로 상위 문제가 완전 해결되었음에도 미해결 사항에 무맥락 잔존함. |
| 8 | Unknown 6.1.5 (ChromaDB 1.x 업그레이드) | 보류 | **일치** | [`pyproject.toml:29`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/pyproject.toml#L29)<br>[`.github/vulnerability-allowlist.yml:14-40`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/.github/vulnerability-allowlist.yml#L14-L40)<br>[`docs/analysis/chromadb_1x_upgrade_plan.md:11-34`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/analysis/chromadb_1x_upgrade_plan.md#L11-L34) | 상류 미수정 및 서버 미노출 사유로 1.x 업그레이드 보류 및 allowlist 만료일 2026-12-31 유지 상태가 코드 및 설정과 완전히 일치함. |

---

## 3. 항목별 상세 분석 및 근거

### 3.1 `negotiation_contract_support` (active 사실)

#### 1) 문서 서술과 원장의 주장 대조
- **[CURRENT_STATE.md:102-103](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/context/CURRENT_STATE.md#L102-L103)**:
  > `협상 공고를 NEGOTIATION_CONTRACT 로 판별하고 공고에 실린 기술능력·입찰가격 평가비율과 변종 식별자를 화면에 제공합니다. 가격점수는 산식 미확정으로 계산하지 않으며 낙찰률 참고 분포 제공까지 진행했습니다.`
- **[current_state_facts.yaml:239](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/context/current_state_facts.yaml#L239)**:
  > `claim: "협상 공고를 NEGOTIATION_CONTRACT 로 판별하고 공고에 실린 기술능력·입찰가격 평가비율과 변종 식별자를 화면에 제공합니다."`

#### 2) 실제 소스 코드 현황
- **협상 계약 판별 및 차단 사유 코드 부여**:
  [`src/app/services/evaluation_rules.py:301`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/app/services/evaluation_rules.py#L301)에서 `BLOCK_CODE_NEGOTIATION_CONTRACT = "NEGOTIATION_CONTRACT"` 정의.
  [`src/app/services/evaluation_rules.py:587-633`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/app/services/evaluation_rules.py#L587-L633)에서 `sucsfbid_mthd_nm`에 '협상에의한계약' 포함 시 4가지 변종(`STANDARD`, `SW`, `ENGINEERING`, `CONSTRUCTION_ENGINEERING`)을 식별하고 기술능력(`tech_ablt_evl_rt`) 및 입찰가격(`bid_prce_evl_rt`) 평가비율을 파싱하여 반환.
- **가격점수 계산 차단 및 화면 안내**:
  [`src/app/services/evaluation_rules.py:623-628`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/app/services/evaluation_rules.py#L623-L628)에서 점수 계산을 명시적으로 차단(`is_blocked=True`).
  [`src/app/templates/bids/detail.html:394`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/app/templates/bids/detail.html#L394)에서 `협상에의한계약은 공고별로 가격점수 산식이 달라 가격점수는 계산하지 않습니다. 기술·가격 평가비율과 낙찰률 참고 분포만 제공합니다.` 문구 렌더링.
- **낙찰률 참고 분포 제공 서비스 및 스키마/UI 연동**:
  [`src/app/services/negotiation_stats.py:1-112`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/app/services/negotiation_stats.py#L1-L112)에서 변종별 과거 낙찰률 참고 분포(`valid_count`, `average`, `median`, `minimum`, `maximum`) 집계 서비스 구현.
  [`src/app/schemas/evaluations.py:275`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/app/schemas/evaluations.py#L275)의 `negotiation_rate_distribution` 필드 정의.
  [`src/app/api/v1/evaluations.py:644-647`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/app/api/v1/evaluations.py#L644-L647)에서 차단 응답 시 변종 통계를 조회하여 바인딩.
  [`src/app/templates/bids/detail.html:367-376, 1054-1066`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/app/templates/bids/detail.html#L367-L376)에서 유효 건수, 평균, 중앙값, 범위 UI 노출.
- **검증 테스트 통과**:
  [`tests/test_negotiation_contract.py:1-92`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/tests/test_negotiation_contract.py#L1-L92)에서 4대 변종 판별 및 비율 파싱 계약 테스트 전량 통과.

#### 3) 발견된 불일치 내역
1. **문서 서술과 원장(Facts)의 Claim 불일치**: `CURRENT_STATE.md`에는 "가격점수는 산식 미확정으로 계산하지 않으며 낙찰률 참고 분포 제공까지 진행했습니다."라는 문장이 추가되어 있으나, `current_state_facts.yaml`의 `claim`에는 해당 서술이 누락되어 원장과 본문이 100% 일치하지 않음.
2. **원장의 증거 경로(`evidence`) 결함**: `current_state_facts.yaml`의 evidence에는 과거 조사 문서(`aq2`, `ng2a`, `handoff`, `bm1`)만 등록되어 있고, 실제 기능을 보증하는 소스 코드(`src/app/services/evaluation_rules.py`, `src/app/services/negotiation_stats.py`, `src/app/templates/bids/detail.html`, `tests/test_negotiation_contract.py`)가 전혀 반영되어 있지 않음.
3. **진행 상태(status) 불일치**: 문서에는 `active`로 분류되어 있으나, 서술된 3대 기능(판별, 비율/변종 제공, 낙찰률 참고 분포)은 이미 코드상 전 계층에 완전하게 구현·배포되어 있음.

#### 4) 권고 사항 (문서 갱신 방향)
- `current_state_facts.yaml`의 `claim`을 `CURRENT_STATE.md`의 전체 문장과 일치시키고, `evidence`에 실제 구현 모듈([`src/app/services/evaluation_rules.py`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/app/services/evaluation_rules.py), [`src/app/services/negotiation_stats.py`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/app/services/negotiation_stats.py), [`src/app/templates/bids/detail.html`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/app/templates/bids/detail.html), [`tests/test_negotiation_contract.py`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/tests/test_negotiation_contract.py))을 추가하십시오.
- 기 구현된 협상 지원 범위를 종결(`closed`) 처리하거나, active로 유지해야 하는 구체적인 잔여 과업(예: 향후 가격점수 산식 확정 및 계산 모델 추가 등)을 명확히 명시하십시오.

---

### 3.2 `drift_job` (active 사실)

#### 1) 문서 서술과 원장의 주장 대조
- **[CURRENT_STATE.md:104-105](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/context/CURRENT_STATE.md#L104-L105)** 및 **[current_state_facts.yaml:430](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/context/current_state_facts.yaml#L430)**:
  > `드리프트 감시는 Servc·Thng·Cnstwk 세 baseline을 모두 갖춰 전 카테고리 진행 중입니다(ML_DRIFT_MONITOR_ENABLED 기본값 True). Thng b_20260915_thng_post_regime(18,069건) 적재로 건너뛰기 예외는 없어졌고, ml_registry는 Git 미추적이라 운영 재생성이 필요합니다.`

#### 2) 실제 소스 코드 현황
- **설정 기본값**:
  [`src/app/core/config.py:80`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/app/core/config.py#L80)에 `ML_DRIFT_MONITOR_ENABLED: bool = True`로 정의됨.
- **태스크 독스트링 및 주석**:
  [`src/tasks/scheduled_tasks.py:626`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/tasks/scheduled_tasks.py#L626)의 함수 독스트링에 `- settings/환경변수 ML_DRIFT_MONITOR_ENABLED 플래그로 활성화 제어 (기본값: False)`라고 기재되어 있음.
  [`src/tasks/scheduled_tasks.py:650-652`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/tasks/scheduled_tasks.py#L650-L652) 주석에 `# baseline 부재 모델(예: Thng)은 예외 없이 건너뜁니다.`라고 명시되어 있음.
- **증거 문서(psi_drift_monitoring.md) 상태**:
  [`docs/ops/psi_drift_monitoring.md:108`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/ops/psi_drift_monitoring.md#L108)에 `baseline이 없는 모델(예: Thng quantum_leap_v25_pro)은 예외나 거짓 드리프트 없이 건너뛰고 retrain_logs에 INSUFFICIENT_DATA로 기록한 뒤 다음 카테고리로 계속합니다`라고 기재되어 있음.
- **증거 파일(training_config.py) 상태**:
  [`src/ml/training_config.py:68-72`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/ml/training_config.py#L68-L72)에는 카테고리별 모델명 맵(`CATEGORY_MODEL_NAMES`)만 정의되어 있을 뿐, baseline 버전이나 드리프트 설정 관련 코드가 전혀 없음.
- **저장소 로컬 상태**:
  [`.gitignore:198`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/.gitignore#L198)에 `ml_registry/`가 등록되어 Git으로 형상 관리되지 않음. 로컬 작업 트리에는 `quantum_leap_v25_pro`와 `servc_institution_v1` 디렉터리만 일부 존재하며, 세 모델 모두 `baseline/` 디렉터리가 없어 실제 태스크 실행 시 로컬에서는 `no_baseline` 분기가 발생함. (단, DB 실측상으로는 원격/운영 DB의 `retrain_logs`에 2026-09-18 05:33 UTC 기준 세 카테고리 실측 결과 id 7, 8, 9가 기록되어 있음).

#### 3) 발견된 불일치 내역
1. **코드 주석 및 독스트링 불일치**: `scheduled_tasks.py:626` 독스트링이 과거 기본값인 `False`로 남아 있어 실제 설정(`True`)과 불일치하며, 650행의 주석도 Thng을 baseline 부재 모델의 예시로 들고 있어 문서 내용과 상충함.
2. **원장 증거 문서([docs/ops/psi_drift_monitoring.md](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/ops/psi_drift_monitoring.md)) 내용 뒤처짐**: 사실 원장 evidence 1순위 문서가 2026-09-06 시점에 머물러 있어, "Thng은 baseline이 없어 건너뛴다"는 과거 사실을 설명하고 있음. CURRENT_STATE의 주장("Thng 적재로 건너뛰기 예외가 없어졌다")과 정면 충돌함.
3. **증거 파일([src/ml/training_config.py](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/ml/training_config.py)) 부적합**: 해당 파일에는 baseline에 관한 설정이나 코드가 전혀 없으므로 증거로서의 적합성이 결여됨.

#### 4) 권고 사항 (문서 갱신 방향)
- [docs/ops/psi_drift_monitoring.md](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/ops/psi_drift_monitoring.md) 6장의 baseline 현황을 2026-09-15 이후 최신 상태(Thng `b_20260915_thng_post_regime` 적재 완료, 3개 카테고리 전량 감시 체계)로 갱신하십시오.
- `current_state_facts.yaml`의 `evidence` 목록에서 부적합한 `src/ml/training_config.py`를 제외하거나 주석을 명시하고, 실제 3개 카테고리 드리프트 감시 실측이 기록된 분석 문서([docs/analysis/drift_monitor_verify_20260918.md](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/analysis/drift_monitor_verify_20260918.md))를 증거 경로에 추가하십시오.
- 향후 코드 리팩토링 과업 시 `src/tasks/scheduled_tasks.py:626` 독스트링(`기본값: True`) 및 650행 주석을 현실에 맞게 수정하도록 백로그에 등록하십시오.

---

### 3.3 `gate_g2` (blocked 사실)

#### 1) 문서 서술과 원장의 주장 대조
- **[CURRENT_STATE.md:15, 108](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/context/CURRENT_STATE.md#L15)** 및 **[current_state_facts.yaml:345](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/context/current_state_facts.yaml#L345)**:
  > `G2 크로스 플랫폼은 보류이며 Windows Docker Desktop 실기 검증은 미검증입니다.`

#### 2) 실제 소스 코드 현황 및 증거 문서 상태
- **게이트 보류 판정**:
  Windows Docker Desktop 실기 장비 부재로 인한 미검증 상태는 현재도 유지되고 있으며, 이는 작업 환경의 제약이므로 문서 결함이 아닙니다.
- **증거 문서([docs/ops/cross_platform_guide.md](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/ops/cross_platform_guide.md)) 내용 뒤처짐**:
  `current_state_facts.yaml:348`의 단일 evidence인 [`docs/ops/cross_platform_guide.md:4-5`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/ops/cross_platform_guide.md#L4-L5) 상단 메타데이터에 다음과 같이 기술되어 있음:
  > `갱신일: 2026-08-24`
  > `상태: 2026-08-24 원격 CI run 32703096829 (bd6212c) 에서 ubuntu·macOS·windows 전부 green / Windows Docker Desktop 실기 미수행`
  반면 `CURRENT_STATE.md:18` 및 `current_state_facts.yaml:170-175`(`ci_windows` 사실)에는 최신 CI 검증 실측으로 `GitHub Actions Run 33947859707 (fa1202f, 2026-09-05, Test windows-latest py3.11 success)`가 기록되어 있음.

#### 3) 발견된 불일치 내역
- 게이트 보류 상태 자체는 코드/환경과 일치하나, 이를 뒷받침하는 증거 문서([docs/ops/cross_platform_guide.md](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/ops/cross_platform_guide.md))의 CI 실행 이력 및 갱신일이 2026-08-24 시점에 멈춰 있어 정본 문서(2026-09-05 fa1202f 실측)보다 뒤처져 있음.

#### 4) 권고 사항 (문서 갱신 방향)
- [docs/ops/cross_platform_guide.md](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/ops/cross_platform_guide.md) 상단의 상태 및 CI 실행 기록을 `fa1202f`(Run 33947859707)로 갱신하여 문서 간 정합성을 일치시키십시오.

---

### 3.4 Section 6.1 Unknowns (알려진 미해결 사항 5건)

#### 1) Unknown 6.1.1: Windows Docker Desktop 실기 (2026-09-03, 미검증)
- **문서 서술**: `장비 확보 후 Compose healthy, 예측 API, 마이그레이션을 확인합니다.`
- **점검 결과**: **일치**. 실기 장비 미확보 상태가 지속 중이며, 1절 게이트 상태(보류) 및 사실 원장(`gate_g2`)과 정합합니다.

#### 2) Unknown 6.1.2: RAG cold SQL (2026-09-13, 인덱스·힌트 적용)
- **문서 서술**: `기관명 LIKE 콜드 I/O. 09-14 정본 콜드 SQL P95 1.9초·최대 5.1초 ([rag_coldsql_root_cause_20260913.md](../analysis/rag_coldsql_root_cause_20260913.md)).`
- **점검 결과**: **불일치 (상태적 모순)**.
  - 근거 문서인 [`docs/analysis/rag_coldsql_root_cause_20260913.md:24-25`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/analysis/rag_coldsql_root_cause_20260913.md#L24-L25)에서 이미 `CURRENT_STATE 6.1의 "1차 원인 미규명" 과 "기관명 필터 live 경로 후보" 를 닫습니다`라고 명시하였음.
  - [CURRENT_STATE.md:48](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/context/CURRENT_STATE.md#L48)의 `coldsql_metric`은 2026-09-01에 관찰 지표로 강등되며 closed 처리됨.
  - [CURRENT_STATE.md:94](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/context/CURRENT_STATE.md#L94) 및 [current_state_facts.yaml:442](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/context/current_state_facts.yaml#L442)의 `coldsql_rerun`은 2026-09-14 정본 콜드 SQL 최대 5,056ms 달성으로 canonical 게이트를 통과하여 closed(종결)됨.
  - 원인 규명, 인덱스/힌트 적용, 벤치마크 재측정 및 사실 종결까지 완료되었음에도 불구하고, 6.1절 "알려진 미해결 사항(Unknowns)"에 여전히 잔존하고 있어 2장 closed 사실과의 모순 및 혼선을 초래함.
- **권고 사항**: 6.1절에서 해당 항목을 삭제하거나, 여전히 미해결로 남아 있는 잔여 관찰 지표(예: 특정 희귀 기관명 쿼리의 추가 최적화 여부 등)가 있다면 그 범위를 한정하여 명확히 재정의하십시오.

#### 3) Unknown 6.1.3: 손상 탐침 제거 (2026-09-11, 구조적 제거 확정·효과 크기 미확정)
- **문서 서술**: `corrupted_probe 0ms 달성을 확정했습니다. 잔여 분산으로 효과 크기는 미확정입니다.`
- **점검 결과**: **일치**.
  - [`src/rag/structured_data.py:807-835`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/rag/structured_data.py#L807-L835) 코드상 스냅샷 마커가 존재할 경우 `corrupted_probe` 호출을 완벽하게 우회함.
  - [`docs/analysis/aw2_probe_removal_effect_20260911.md:20-26`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/analysis/aw2_probe_removal_effect_20260911.md#L20-L26) 실측 결과 `corrupted_probe_ms`는 0ms로 확정되었으나, 콜드 쿼리 자체의 분산으로 인해 총 시간 개선 효과 크기는 미확정으로 판정한 기술 내용과 완전히 부합함.

#### 4) Unknown 6.1.4: 측정 설계와 실행계획 조사 (2026-09-11, 도구 완비·원인 미확정)
- **문서 서술**: `계측 도구를 완비했습니다. 영속 통계 노후를 확인했으나 계획 전환 원인은 미확정입니다.`
- **점검 결과**: **불일치 (맥락 노후 및 과업 완료 미반영)**.
  - [`docs/analysis/ax2_plan_instability_20260911.md:13-17`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/analysis/ax2_plan_instability_20260911.md#L13-L17)에서 compare-stats 매칭 질의의 실행계획 뒤집힘 원인을 '미확정'으로 결론 내린 것은 사실임.
  - 그러나 후속 과업을 통해 실무적 문제는 완전히 종결되었음:
    1) 대상 경로인 compare-stats 엔드포인트는 네 집계를 사전 집계 스냅샷으로 전환하여 캐시 미적중 레이턴시를 4.9ms로 단축 완료 및 종결함 ([CURRENT_STATE.md:72](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/context/CURRENT_STATE.md#L72) `compare_stats_snapshot`).
    2) 영속 통계 노후 문제는 야간 점검 및 수동 갱신 정책(선택지 B) 도입으로 종결함 ([CURRENT_STATE.md:96](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/context/CURRENT_STATE.md#L96) `mysql_stats_refresh_policy`).
  - 즉, 문제가 되었던 서비스 레이턴시와 영속 통계 관리 정책은 모두 해결·종결되었는데, 6.1절에는 마치 시스템의 미해결 장애 요인인 것처럼 맥락 없이 기술되어 있어 오해를 유발함.
- **권고 사항**: 6.1절 서술에 "compare-stats 스냅샷 전환 및 영속 통계 신선도 정책 수립으로 서비스 영향은 해소되었으며, 단일 EXISTS 질의의 옵티마이저 계획 전환 원인 규명만 미해결"임을 구체적으로 보완하거나 항목을 정리하십시오.

#### 5) Unknown 6.1.5: ChromaDB 1.x 업그레이드 (2026-09-13, 보류)
- **문서 서술**: `1.5.9 까지 CVE 미수정, 1.x 는 1건 추가. 서버 미노출로 예외 유지, 12-31 재확인 ([chromadb_1x_upgrade_plan.md](../analysis/chromadb_1x_upgrade_plan.md)).`
- **점검 결과**: **일치**.
  - [`pyproject.toml:29`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/pyproject.toml#L29)에 `chromadb==0.6.3` 고정.
  - [`.github/vulnerability-allowlist.yml:14-40`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/.github/vulnerability-allowlist.yml#L14-L40)에 3건의 CVE에 대해 `expires_on: "2026-12-31"`로 한시 예외 설정 유지.
  - [`docs/analysis/chromadb_1x_upgrade_plan.md:11-34`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/analysis/chromadb_1x_upgrade_plan.md#L11-L34)의 보류 결정과 정합함.

---

## 4. 원장(current_state_facts.yaml)과 부팅 문서(CURRENT_STATE.md) 간 정합성

| 항목 | current_state_facts.yaml | CURRENT_STATE.md | 판정 | 설명 및 불일치 내용 |
| :--- | :--- | :--- | :---: | :--- |
| `updated_at` | `2026-09-16` (3행) | `2026-09-18` (3행) | **불일치** | facts.yaml의 갱신일이 CURRENT_STATE.md보다 이틀 과거 날짜로 머물러 있음. |
| `negotiation_contract_support` claim | 1개 문장만 기재 (239행) | 2개 문장 기재 (102-103행) | **불일치** | CURRENT_STATE.md에 추가된 "가격점수는 산식 미확정으로 계산하지 않으며 낙찰률 참고 분포 제공까지 진행했습니다." 문장이 facts.yaml의 claim에 누락됨. |
| `negotiation_contract_support` evidence | 과거 분석 문서 4건만 기재 | - | **부적합** | 실제 기능 구현 소스 코드 및 테스트가 evidence에 미등록됨. |
| `drift_job` evidence | `src/ml/training_config.py` 포함 | - | **부적합** | 해당 모듈에는 baseline 관련 설정 및 코드가 전혀 없음. |
| `drift_job` 1순위 증거 문서 | `docs/ops/psi_drift_monitoring.md` | - | **내용 충돌** | 증거 문서 108행에서 "Thng은 baseline이 없어 건너뛴다"고 기술하여 사실 주장(적재 완료)과 충돌함. |
| `gate_g2` evidence | `docs/ops/cross_platform_guide.md` | - | **내용 뒤처짐** | 증거 문서의 CI 실행 기록(08-24, Run 32703096829)이 정본(09-05, Run 33947859707)보다 과거 상태임. |

---

## 5. 결론 및 권고 요약

1. **`negotiation_contract_support` 문서 갱신 및 종결 검토**:
   - 이미 소스 코드 전반([`src/app/services/evaluation_rules.py`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/app/services/evaluation_rules.py), [`src/app/services/negotiation_stats.py`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/app/services/negotiation_stats.py), [`src/app/templates/bids/detail.html`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/src/app/templates/bids/detail.html), [`tests/test_negotiation_contract.py`](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/tests/test_negotiation_contract.py))에 구현과 테스트가 완료되었으므로, facts.yaml의 claim과 evidence를 실제 코드 기반으로 갱신하고 현재 구현 범위에 대한 종결(`closed`) 처리를 검토하십시오.
2. **`drift_job` 증거 문서 동기화**:
   - [docs/ops/psi_drift_monitoring.md](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/ops/psi_drift_monitoring.md) 문서가 2026-09-06 시점(Thng baseline 부재)에 멈춰 있으므로, Thng baseline 적재 및 전 카테고리 감시 체계에 맞추어 갱신하십시오. facts.yaml evidence에서 무관한 `training_config.py` 대신 [docs/analysis/drift_monitor_verify_20260918.md](file:///Users/kwanbum/orca/workspaces/refac_bid_box/at3-audit/docs/analysis/drift_monitor_verify_20260918.md)를 바인딩하십시오.
3. **6.1절 Unknowns 정리 (RAG cold SQL, 실행계획 조사)**:
   - 2장 기계 검증 사실에서 이미 `closed`로 확정된 `coldsql_metric` 및 `coldsql_rerun`과 상충되는 6.1절의 `RAG cold SQL` 항목을 정리하십시오.
   - 실행계획 조사 항목 역시 상위 서비스(`compare_stats_snapshot`) 및 통계 신선도 정책(`mysql_stats_refresh_policy`) 종결 사실과 연계하여 실무적 영향이 해소되었음을 명확히 하십시오.
4. **원장(facts.yaml) updated_at 동기화**:
   - facts.yaml의 `updated_at`을 `2026-09-18`로 갱신하여 CURRENT_STATE.md와의 시점 정합성을 맞추십시오.
