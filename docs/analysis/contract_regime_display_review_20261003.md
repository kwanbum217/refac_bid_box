> 검토일: 2026-10-03
> 대상: 커밋 968cd2d4 (브랜치 kwanbum217/contract-regime-display-review, HEAD)
> 범위: git diff main...HEAD 파일 9개
> 역할: 독립 리뷰 (표시만 검토, 코드 수정 없음)

# 지방계약 판별 결과 표시 리뷰

## 1. 대상 확인

- `git log --oneline main..HEAD` 출력은 `968cd2d4 feat: 지방계약 판별 결과 표시` 1건이다.
- `git diff --name-only main...HEAD` 출력은 9개 파일이다.
  - src/app/api/v1/evaluations.py
  - src/app/schemas/evaluations.py
  - src/app/services/bid_queries.py
  - src/app/services/demand_institutions.py
  - src/app/services/evaluation_rules.py
  - src/app/templates/bids/detail.html
  - tests/test_bid_detail_restrictions.py
  - tests/test_contract_regime_display.py
  - tests/test_evaluations_api.py

## 2. 판정

### 2.1 display_matches_judgment: yes

화면과 API에 표시되는 계약 법령, 근거, 범위가 실제 판정과 범위 계산이 쓰는 값과 일치하고, 미상을 국가계약으로 표시하지 않는다.

근거:

- 판정 정본은 `src/app/services/evaluation_rules.py:1393-1401` `extract_contract_regime`이다. `cntrctCnclsMthdNm`과 `cntrct_mthd_nm`에 `지방`이 있으면 `LOCAL`, 아니면 `institution_regime`을 그대로 돌려준다.
- 표시 함수는 `src/app/services/demand_institutions.py:245-285` `describe_contract_regime`이다. 내부에서 `classify_contract_regime` 결과(`src/app/services/demand_institutions.py:206-231`)를 구한 뒤 같은 `extract_contract_regime(data, cntrct_mthd_nm, institution_regime)`를 호출한다(`src/app/services/demand_institutions.py:252-253`). 판정 입력이 동일하므로 분기 가능성이 없다.
- 범위 계산 정본은 `src/app/services/evaluation_scoring.py:273-321` `generate_pred_price_scenarios`이다. `is_local_contract`이면 0.03(`LOCAL_DEFAULT`), 아니면 0.02(`NATIONAL_DEFAULT`)이다.
- API 래퍼는 `src/app/api/v1/evaluations.py:702-705` `_is_local_contract`와 `src/app/api/v1/evaluations.py:714-757` `_scenario_prices`이다. `_is_local_contract`도 같은 `extract_contract_regime(raw_data, bid.cntrct_mthd_nm, institution_regime) == "LOCAL"`이므로 표시용 `regime`과 범위용 `is_local`이 같은 판정을 공유한다. `institution_regime`은 `_analyze_bid`에서 `src/app/api/v1/evaluations.py:1343` 한 번 구해 표시(`src/app/api/v1/evaluations.py:1344`)와 범위(`src/app/api/v1/evaluations.py:1387`) 양쪽에 전달된다.
- 범위 표기 매핑은 `src/app/services/demand_institutions.py:275-277`이다. `LOCAL`이면 `±3%`, `NATIONAL`이면 `±2%`, `None`이면 `±2% (기본값, 법령 미상)`이다. `None`일 때 `_scenario_prices`의 `is_local`은 `False`가 되어 실제 계산도 0.02를 쓰므로 표기와 계산이 일치한다.
- 법령 표기 매핑은 `src/app/services/demand_institutions.py:269-274`이다. `LOCAL`이면 `지방계약`, `NATIONAL`이면 `국가계약`, `None`이면 `계약 법령 미상`이다. 미상을 `국가계약`으로 표기하는 분기가 없다.
- 직접 실행한 정합 행렬 6건이 전부 일치했다. `uv run python3`으로 `classify`/`extract`/`describe`를 대조한 결과, 지방자치단체 기관은 `LOCAL/지방계약/±3%`, 국가기관 기관은 `NATIONAL/국가계약/±2%`, 기관 없음은 `None/계약 법령 미상/±2% (기본값, 법령 미상)`이다. 함정 사례 2건도 일치했다. `dminstt_nm`이 `부산지방국토관리청`이어도 소관구분이 국가기관이면 `NATIONAL/국가계약/±2%`로 기관명에 낚이지 않고, `raw_data.cntrctCnclsMthdNm`에 지방 표기가 있으면 기관이 국가기관이어도 `LOCAL/METHOD_NAME/±3%`으로 계약방법명 우선 규칙과 같다.
- 시험이 미상 표기를 고정한다. `tests/test_contract_regime_display.py:31`는 기관 없음 입력에 `계약 법령 미상`과 `±2% (기본값, 법령 미상)`을 요구하고, `tests/test_contract_regime_display.py:56-62`는 스키마 경유 미상도 같은 표기임을 요구한다. `tests/test_bid_detail_restrictions.py:130`은 SSR 본문에 `계약 법령 미상 · ±2% (기본값, 법령 미상)`이 있음을 요구하고, `tests/test_evaluations_api.py:694-695`는 차단 응답의 `contract_regime.label`과 `range_rate_label`이 같은 미상 표기임을 요구한다.
- 재현 절차: `uv run python3` 위 행렬 스크립트 실행, 또는 `uv run pytest tests/test_contract_regime_display.py -q` 실행.

### 2.2 single_source_no_behavior_change: yes

설명 로직이 한 함수에만 있고 서버 렌더링과 API가 그것을 쓰며, 판별 규칙과 복수예가 계산 동작이 바뀌지 않았다.

근거:

- `describe_contract_regime` 정의는 저장소 전체에서 `src/app/services/demand_institutions.py:245` 1곳뿐이다. `grep describe_contract_regime src/app` 결과 사용처는 `src/app/services/bid_queries.py:34,757`와 `src/app/api/v1/evaluations.py:82,1344` 2곳뿐이며, 두 곳 모두 import해서 호출한다. 설명 문자열을 복제한 제2 구현이 없다.
- SSR 경로는 `src/app/services/bid_queries.py:735-757`이다. `raw_data`와 `dminsttCd`로 조회한 기관 행을 `describe_contract_regime(raw_data, bid.cntrct_mthd_nm, institution)`에 그대로 넘겨 `contract_regime` 딕셔너리를 템플릿에 전달한다.
- API 경로는 `src/app/api/v1/evaluations.py:1344-1348`이다. 같은 함수 결과를 `ContractRegimeDescription(**contract_regime)`으로 감싸 `with_contract_regime`으로 모든 반환에 부착한다. 차단(`src/app/api/v1/evaluations.py:1371,1378,1399`), 밴드 미해결(`src/app/api/v1/evaluations.py:1410`), 입력 위반(`src/app/api/v1/evaluations.py:1425`), 점수표 결측(`src/app/api/v1/evaluations.py:1444`), 성공 응답까지 누락 경로가 없다. 협상 변형 분기도 `src/app/api/v1/evaluations.py:1367-1371`에서 같은 래퍼를 통과하므로 `contract_regime`이 빠지지 않는다. 기존 필드를 덮어쓰지 않고 `response.contract_regime` 하나만 추가하므로 다른 동작에 영향을 주지 않는다.
- 스키마 추가는 `src/app/schemas/evaluations.py:434-442` `ContractRegimeDescription` 신규 클래스와 `src/app/schemas/evaluations.py:453-455` `EvaluationResponse.contract_regime` Optional 필드뿐이다. 기본값이 `None`이라 기존 응답 파싱을 깨지 않는다.
- 판별 규칙 변경이 없다. `git diff main...HEAD -- src/app/services/evaluation_rules.py` 결과 변경분은 `src/app/services/evaluation_rules.py:82` 주석 1줄뿐이다(`src/ml/features.py:34-37` 인용을 `src/ml/notice_amount.py`로 정정). `extract_contract_regime`, `classify_contract_regime` 본문 변경이 없다.
- 범위 계산 변경이 없다. `git diff main...HEAD --stat -- src/app/services/evaluation_scoring.py` 결과 변경분이 0건이다. `_scenario_prices` 본문 변경도 없고, 호출부에 `institution_regime` 전달이 유지된다(`src/app/api/v1/evaluations.py:1387`).
- `_bid_estimated_price` 변경은 `src/app/api/v1/evaluations.py:360` docstring 1줄뿐이다. `git show main`와 `git show HEAD` 대조 결과 함수 본문(`presmpt_prce` 우선, 없으면 `base_amount`)이 동일하다. 동작 변경이 없다.
- 재현 절차: `git diff main...HEAD -- src/app/services/evaluation_scoring.py`가 빈 출력임을 확인하고, `git diff main...HEAD -- src/app/services/evaluation_rules.py src/app/api/v1/evaluations.py`에서 코드 변경이 주석·docstring·`with_contract_regime` 래핑뿐임을 확인한다.

### 2.3 ui_and_css: yes

상세 머리말 배지와 결과 영역 범위 줄이 렌더링되고, 협상 분기에서는 시나리오 영역이 숨겨지며, `tailwind.css`가 빌드 결과와 같다.

근거:

- 머리말 배지는 `src/app/templates/bids/detail.html:65-67`이다. `{% if contract_regime %}` 가드 안에서 `{{ contract_regime.label }} · {{ contract_regime.range_rate_label }}`을 출력하고 `title`에 `basis_text`를 싣는다. SSR 시험 `tests/test_bid_detail_restrictions.py:130`이 미상 배지 문자열을 본문에서 확인하므로 렌더링 경로가 시험으로 고정된다.
- 범위 줄은 `src/app/templates/bids/detail.html:511` `<p id="contract-regime-range">`와 `src/app/templates/bids/detail.html:1580-1586` JS이다. `scenario_results`가 비어 있지 않고 `data.contract_regime`이 있을 때 `예정가격 변동 범위: 기초금액 {range_rate_label} ({label}{jurisdiction})`을 채우고 `hidden`을 제거한다.
- 협상 분기 제외가 유지된다. `src/app/templates/bids/detail.html:1286`은 협상(`negotiation_variant != null`)이거나 시나리오 행이 없으면 `#scenario-results`를 숨긴다. 분석 실행 경로 `src/app/templates/bids/detail.html:1453-1454`는 `renderNegotiation(data)`가 참이면 조기 반환하므로 협상 공고에서 범위 줄이 그려지지 않는다. 템플릿 고정 시험 `tests/test_contract_regime_display.py:65-72`가 `contract-regime-range` ID, `regime.range_rate_label` 사용, 협상 조건식 존재를 함께 확인한다.
- Tailwind 재현성을 직접 실행으로 확인했다. `npm run build:css` 실행 후 `git diff --exit-code -- src/app/static/css/tailwind.css` 결과는 변경 없음(`CSS-CLEAN`)이다. 이번 커밋이 템플릿에 추가한 클래스는 `badge badge-blue ml-2`, `hidden text-sm text-slate-600` 등 기존 유틸리티 조합이라 CSS 재생성 차이가 없다.
- 재현 절차: `npm run build:css` 후 `git diff --exit-code -- src/app/static/css/tailwind.css` 실행.

## 3. 직접 실행한 검증

- `uv run pytest tests/test_contract_regime_display.py tests/test_bid_detail_restrictions.py tests/test_evaluations_api.py -q` 결과 `57 passed`이다.
- `npm run build:css` 후 `git diff --exit-code -- src/app/static/css/tailwind.css` 결과 변경 없음이다.
- `python3 scripts/validate_agent_rules.py --quiet` 결과 `검증 통과: 21/21 건`이다.

## 4. 비차단 제안 (verdict 반영 없음)

1. 협상 공고의 머리말 배지는 표시되고 결과 영역 범위 줄만 숨겨지는 현재 동작이 사양과 일치한다. 협상에서도 범위 줄을 보여줄지 여부는 취향 영역이므로 이번 리뷰 판정에 반영하지 않는다.
2. 미상일 때 배지 `title`이 `판별 근거 없음`으로 표시되는 fallback(`src/app/templates/bids/detail.html:66`)은 현상 유지가 적절하다. 문구 변경 제안은 취향 영역이므로 판정에 반영하지 않는다.

## 5. 결론

- checklist 3개 항목 모두 `yes`이다. 코드와 시험으로 재현되는 동작 결함이 없으므로 verdict는 `pass`이다.
- 남은 작업은 코디네이터의 `main` 병합 판단뿐이며, 리뷰어 측 추가 수정 사항은 없다.
