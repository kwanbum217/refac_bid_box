> 작성일: 2026-10-03
> 조사 대상: 적격심사 용역 공고, 2025-01-01 이후
> 데이터 기준: `bid_announcements`의 공고 차수별 행
> 판정 상태: 사용자 결정 대기

# 정량평가 구간의 기초금액 대체 영향 분석

## 1. 질문과 현재 동작

적격심사 분석에는 금액으로 점수표 구간을 고르는 경로가 둘 있습니다. 정량평가 배점표는 `presmpt_prce`가 양수이면 그 값을, 아니면 양수 `base_amount`를 사용합니다. 반면 B(가격배점한도)와 k(평점계수)는 `presmpt_prce`만 `resolve_score_params`에 전달하므로 그 값이 없으면 금액 근거로는 선택하지 않습니다. 두 경로 모두 낙찰방법명에 구간 표기가 있으면 해당 구간이 금액보다 우선합니다.

경계는 B가 5억 원, k가 공고 연도별 고시금액입니다. 조사 모집단은 2025년 이후이므로 k 경계는 2025~2026년 값인 2억 3천만 원입니다. 경계와 같으면 이상 구간으로 분류합니다. 코드 기준은 `src/app/api/v1/evaluations.py`의 `_bid_estimated_price` 및 두 호출부, `src/app/services/evaluation_rules.py`의 `resolve_score_params`, `src/ml/notice_amount.py`의 연도표입니다.

## 2. 모집단과 집계

모집단은 `category = 'Servc'`, 공고일 2025-01-01 이상, JSON의 `sucsfbidMthdNm`에 '적격' 포함으로 정의했습니다. 실제 DB에는 낙찰방법명 전용 컬럼이 없고 `raw_data` JSON에 저장되어 있어 JSON 경로를 사용했습니다. 건수는 공고 번호가 아니라 차수까지 구분되는 테이블 행 기준입니다. 운영 코드와 같이 0 이하 금액은 사용 가능한 금액으로 세지 않았습니다.

아래 질의 하나로 이 절의 모든 숫자를 다시 계산할 수 있습니다.

```sh
uv run python scripts/db_readonly_query.py --sql "WITH pop AS (SELECT id, presmpt_prce, base_amount, bid_ntce_dt, JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidMthdNm')) AS method_name FROM bid_announcements WHERE category = 'Servc' AND bid_ntce_dt >= '2025-01-01' AND JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidMthdNm')) LIKE '%적격%') SELECT COUNT(*) AS population, SUM(presmpt_prce IS NOT NULL AND presmpt_prce > 0) AS a_presmpt_positive, SUM((presmpt_prce IS NULL OR presmpt_prce <= 0) AND base_amount IS NOT NULL AND base_amount > 0) AS b_fallback, SUM((presmpt_prce IS NULL OR presmpt_prce <= 0) AND (base_amount IS NULL OR base_amount <= 0)) AS c_both_missing, SUM(presmpt_prce > 0 AND base_amount > 0 AND ((presmpt_prce >= 500000000) <> (base_amount >= 500000000))) AS b_boundary_disagree, SUM(presmpt_prce > 0 AND base_amount > 0 AND ((presmpt_prce >= 230000000) <> (base_amount >= 230000000))) AS k_boundary_disagree, SUM(presmpt_prce > 0 AND base_amount > 0 AND (((presmpt_prce >= 500000000) <> (base_amount >= 500000000)) OR ((presmpt_prce >= 230000000) <> (base_amount >= 230000000)))) AS any_boundary_disagree, SUM((presmpt_prce IS NULL OR presmpt_prce <= 0) AND base_amount > 0) AS b_base_band_only, SUM((presmpt_prce IS NULL OR presmpt_prce <= 0) AND base_amount > 0 AND (method_name REGEXP '5[ ]*억[ ]*원?[ ]*(미만|이상)' OR method_name REGEXP '고시금액[ ]*(미만|이상)')) AS b_method_resolves_any, SUM((presmpt_prce IS NULL OR presmpt_prce <= 0) AND base_amount > 0 AND method_name REGEXP '5[ ]*억[ ]*원?[ ]*(미만|이상)') AS b_method_resolves_B, SUM((presmpt_prce IS NULL OR presmpt_prce <= 0) AND base_amount > 0 AND method_name REGEXP '고시금액[ ]*(미만|이상)') AS b_method_resolves_k FROM pop" --format json
```

| 집계 | 건수 | 의미 |
| --- | ---: | --- |
| 모집단 | 83,862 | 위 조건을 만족하는 행 |
| (a) 추정가격(presmpt_prce) 양수 | 83,772 | 두 금액 구간 경로 모두 금액 판정 가능 |
| (b) 추정가격 없음·기초금액(base_amount) 양수 | 23 | 현행 정량평가는 기초금액 구간 선택, B·k는 금액 미상 |
| (c) 두 금액 모두 없음 | 67 | 두 경로 모두 금액 판정 불가 |
| (a)에서 B 5억 경계 불일치 | 1,210 | 두 금액이 5억 원 경계의 서로 다른 쪽 |
| (a)에서 k 2.3억 경계 불일치 | 2,401 | 두 금액이 고시금액 경계의 서로 다른 쪽 |
| (a)에서 어느 한 경계라도 불일치 | 3,553 | 두 조건의 합집합, 중복은 한 번 계산 |
| (b) 중 기초금액으로 정량평가 구간 선택 | 23 | (b) 전체 |
| (b) 중 방법명으로 B 또는 k 선택 가능 | 4 | B 구간 표기 4건, k 구간 표기 0건 |

불일치 건수는 추정가격과 기초금액을 각각 임계값에 대입한 단순 비교입니다. 실제 선택에서는 낙찰방법명 표기가 우선하므로 이 건수가 곧 최종 화면의 변경 건수라고 단정할 수는 없습니다. 모집단의 `base_amount`가 부가세 포함이라는 의미를 운영 데이터 값만으로 검증할 수는 없었습니다. 모델 주석은 이를 '기초금액(사업예산)'으로 설명하며, 기존 B·k 설계 검토는 추정가격과 기준이 다를 수 있다는 이유로 대체하지 않는 방향을 기록합니다.

## 3. 일관화 선택지

| 선택지 | 선택 동작 | 이 모집단에서 확인되는 영향 | 오판 위험 | 사용자 화면 변화 |
| --- | --- | --- | --- | --- |
| 1. 현행 유지 | 정량평가는 추정가격 우선, 없으면 기초금액 대체. B·k는 추정가격만 사용. 방법명 구간 표기가 있으면 우선. | 23건에서 정량평가 구간은 정해지지만 B·k는 금액만으로 미정. 그중 4건은 방법명으로 B가 정해지고, k 방법명 표기 건은 0건. 금액이 둘 다 있는 행에서는 기준이 달라 경계 불일치가 B 1,210건, k 2,401건. | 추정가격과 기초금액 간 기준 차이를 보존하지만 한 화면에서 서로 다른 금액 근거가 쓰일 수 있습니다. | 정량 배점표는 기초금액으로 채워질 수 있고 B·k는 미정으로 남아 사용자 입력이 필요할 수 있습니다. |
| 2. 정량평가도 대체하지 않음 | 두 경로 모두 추정가격만 사용. 방법명 구간 표기는 각 경로에서 우선. | 현재 정량평가에서만 대체되는 23건은 구간 선택이 미정으로 바뀝니다. (c) 67건은 그대로 미정. B·k 값 자체의 변화는 없습니다. | 기준 금액 일관성은 높아지지만, 유효한 추정가격 누락 상태에서 쓸 수 있는 기초금액 정보도 버리므로 정량평가가 더 자주 멈출 수 있습니다. | 23건에서 정량평가 배점표 구간이 선택되지 않고 확인/입력 안내가 나타납니다. |
| 3. B·k도 기초금액 대체 | B·k의 추정가격이 없을 때 양수 기초금액으로 경계를 판정. 방법명 구간 표기는 여전히 우선. | B·k 금액 판정 가능성이 (b) 23건으로 늘어납니다. 이 중 B는 방법명으로 이미 4건 결정되며, k는 방법명 결정 건이 없어 최대 23건이 새 금액 판정을 받습니다. | 기초금액을 추정가격 경계에 직접 대입하면 세금 포함 여부 등 기준 차이로 B 또는 k 구간을 잘못 선택할 수 있습니다. 부가세 환산 규칙을 확인하지 못한 채 환산을 가정하면 세율·면세 여부 차이까지 오차가 생깁니다. | 최대 23건에서 B·k의 미정 표시가 금액 기반 선택값과 근거 표시로 바뀝니다. 근거 문구도 실제 기준을 드러내도록 '기초금액'이라고 표시해야 합니다. |

선택지 3의 수치는 (b) 전체를 상한으로 한 영향입니다. 고시금액 경계에 대한 세금 포함 기초금액의 환산법과 개별 공고의 세율·면세 처리 없이 정확한 변경 구간을 확정할 수 없습니다. B의 4건은 B 관련 방법명 구간 표기가 이미 선택을 제공하므로 금액 대체로 새로 해소되는 B 미정 건수로 세지 않았습니다.

## 4. 권고

현행 유지를 권고합니다. 기초금액 대체는 정량평가 구간 누락을 줄이는 보조 경로이고, B·k 경계는 추정가격과 연도별 고시금액의 관계를 사용합니다. 서로 다른 경제적 기준일 수 있는 값을 한쪽에서만 대체하면 구간 일관성이 자동으로 생기는 것이 아니라 다른 기준을 섞게 됩니다. 관측된 경계 불일치도 상당하지만, 그 자체는 어느 금액이 법적·업무적으로 올바른 기준인지 알려주지 않습니다. 특히 B·k 대체는 현재 결측 23건을 해소하는 대신 기준 차이를 점수 매개변수에 직접 주입할 수 있습니다.

기초금액과 추정가격의 세금 기준을 공고 원문 또는 도메인 규칙으로 확인하고, 사용자에게 각 구간의 금액 근거를 명확히 보여줄 수 있을 때 선택지 3을 다시 검토하는 것이 타당합니다. 선택지 2는 23건의 정량평가 판정 가능성을 낮추는 비용이 있어 근거 없이 일괄 적용하기 어렵습니다.

## 5. 사용자 결정

**결정 필요(사용자)** — 현행 유지, 두 경로 모두 추정가격만 사용, B·k에도 기초금액 대체 적용 중 하나를 선택해 주십시오. 세 번째 선택 시에는 부가세 포함 여부와 추정가격 환산 규칙을 함께 정해야 합니다.
