# 적격심사 규칙 기관·지역 축 설계

> 작성일: 2026-10-02
> 범위: 설계만 작성. 코드와 DB는 변경하지 않습니다.

## 1. 확인된 현황과 설계 원칙

`EvaluationRule`은 규칙 ID·용역 유형·별표·시행일·출처·식별 패턴·하한율과 배점 파라미터를 보유하지만, 적용 법령·수요기관·지역 필드는 없습니다 (`src/app/services/evaluation_rules.py:20-43`). 현재 근거상 국가계약은 기초금액 ±2%, 조달청 세부기준이고 지방계약은 ±3%, 행안부 예규입니다. 분석 문서는 데이터에 적용 법령 구분 필드가 없어 기관명으로 대리한다고 기록합니다 (`docs/design/g2b_procurement_institution_analysis.md:239-247`).

따라서 규칙 선언에는 규칙의 적용 범위를 두고, 스냅샷에는 판정 당시 공고에서 추출한 범위 값을 복사 보존합니다. 값 미상은 임의 추정하지 않고 `NULL`로 남깁니다. 기존 컬럼 이름·타입은 변경하지 않으며 추가 컬럼은 nullable로 제안합니다.

## 2. `EvaluationRule` 추가 필드

| 제안 필드 | 타입 | 의미와 매칭 | 근거 |
| --- | --- | --- | --- |
| `contract_regime` | `str \| None` | `NATIONAL`, `LOCAL` 등 적용 법령 축. 정확한 허용값 집합은 구현 전 확정 필요. | 국가·지방 계약의 기준과 예비가격 범위가 다르고 원천 데이터에 법령 구분 필드가 없다는 점 (`g2b_procurement_institution_analysis.md:241-247`). 현재 판정에서 계약방법 문자열의 “지방” 포함 여부를 별도로 확인하는 코드가 이미 있음 (`src/app/api/v1/evaluations.py:638-642`). |
| `institution_scope` | `str` | `ALL`, `INSTITUTION`, `REGION` 범위 구분. 광역 공통 규칙과 특정 수요기관 규칙을 구별. 기본값 `ALL`은 기존 규칙 호환용. | 기관별·지역별 산식이 없다는 공백 및 기관별 공고 규모 차이 (`docs/ops/handoff_20261001_qualification_score_table.md:78-81`). |
| `institution_code` | `str \| None` | 기관 식별 코드. 기관 단위 규칙에 쓰며 이름 변경·동명이인 문제를 줄임. 코드의 원천 필드와 표준은 현재 확인 불가. | 공고에서 `dminstt_nm` 수요기관명이 강한 특징으로 쓰였으나 법령 필드는 없어 기관명 대리 상태 (`g2b_procurement_institution_analysis.md:247`, `handoff_20261001_qualification_score_table.md:81`). 코드 사용 가능성은 구현 전 확인 불가. |
| `institution_name` | `str \| None` | 표기·감사 편의를 위한 기관명. 코드가 없거나 과거 원자료만 있는 경우 이름 비교 대안. 정규화 규칙은 확인 불가. | 수요기관명 대리 사용 근거 (`g2b_procurement_institution_analysis.md:247`). |
| `region_code` | `str \| None` | 지역 범위 규칙 식별자. 지역 코드 체계와 데이터 필드는 확인 불가. | 기관 발주에 따라 예측 잔차 하한이 달라 지역 축을 분리할 필요가 있다는 분석 (`g2b_procurement_institution_analysis.md:247`); handoff의 서울·청주·서울교통공사·제주 기관 분포 (`handoff_20261001_qualification_score_table.md:81`). |
| `region_name` | `str \| None` | 지역명 표시용 값. `region_code`와 함께 보존하며 표준화 방식은 확인 불가. | 지역별 축 공백 (`handoff_20261001_qualification_score_table.md:78`) 및 발주기관 소속별 차이 (`g2b_procurement_institution_analysis.md:247`). |

`institution_scope`가 `ALL`이면 기관·지역 필드는 비워 두고, `INSTITUTION`이면 기관 코드 우선(불가 시 정규화 이름), `REGION`이면 지역 코드 우선으로 비교하는 안입니다. 국가·지방 구분이 공고에서 판별되지 않으면 특정 법령 전용 규칙을 선택하지 않아야 합니다. 기존 `patterns` 등의 판정 조건과 우선순위 결합 방식은 현재 근거만으로 확정할 수 없습니다.

## 3. 스냅샷 스키마 추가안 및 롤백

현재 `BidEvaluationSnapshot`은 `rule_id`를 필수 저장하지만 적용 기관과 지역을 보존하지 않습니다 (`src/app/models/evaluations.py:68-101`). 새 컬럼은 계산을 재현하는 규칙 적용 문맥을 저장합니다.

| 추가 컬럼 | 권장 타입 | NULL 허용 | 용도 |
| --- | --- | --- | --- |
| `contract_regime` | `VARCHAR(20)` | 예 | 판정된 국가·지방 계약 축 |
| `institution_code` | `VARCHAR(100)` | 예 | 원천 기관 코드(코드 체계·길이는 확인 불가, 100은 기존 `rule_id`와 맞춘 초안) |
| `institution_name` | `VARCHAR(255)` | 예 | 판정 당시 기관명 스냅샷 |
| `region_code` | `VARCHAR(100)` | 예 | 원천 지역 코드(코드 체계·길이는 확인 불가) |
| `region_name` | `VARCHAR(255)` | 예 | 판정 당시 지역명 |

초안 DDL (MySQL):

```sql
ALTER TABLE bid_evaluation_snapshots
  ADD COLUMN contract_regime VARCHAR(20) NULL,
  ADD COLUMN institution_code VARCHAR(100) NULL,
  ADD COLUMN institution_name VARCHAR(255) NULL,
  ADD COLUMN region_code VARCHAR(100) NULL,
  ADD COLUMN region_name VARCHAR(255) NULL;
```

이는 설계 초안이며 실제 컬럼 길이·인덱스·마이그레이션 프레임워크는 구현 단계에서 현행 DB와 원천 필드를 확인해야 합니다. 기존 행은 모두 `NULL`로 남겨 과거 기관 정보를 추정하지 않습니다. 추가 단계는 기존 `rule_id`, JSON 및 인덱스를 건드리지 않습니다. 조회 성능 요구와 분포를 확인하기 전에는 새 인덱스를 추가하지 않습니다.

롤백은 신규 다섯 컬럼만 `ALTER TABLE ... DROP COLUMN`으로 제거하는 별도 다운 마이그레이션으로 합니다. 롤백 전에 새 컬럼 값을 소비하는 애플리케이션을 이전 버전으로 되돌리고, 신규 컬럼 데이터가 보존 대상인지 확인해야 합니다. 다운 실행 후에는 신규 문맥 값이 소실됩니다. 기존 컬럼·행·JSON은 삭제하거나 변환하지 않습니다.

## 4. 판정 로직 변경 지점

기관 입력을 규칙 축에 매핑할 주 판정 지점은 `src/app/services/evaluation_rules.py:1530-1560`의 `resolve_evaluation_rule_from_raw_data`입니다. 여기서 현재 낙찰·예정가격 결정·용역구분 등의 원자료를 추출해 `resolve_evaluation_rule`에 전달합니다. 설계상 이 경계에서 법령 구분, 기관 코드/명, 지역 코드/명을 추출해 `resolve_evaluation_rule`로 전달하고, `resolve_evaluation_rule` (`:1231` 이하)의 후보 규칙 선택 과정에서 기존 카테고리·낙찰방법·공고일 조건과 함께 축 일치 여부를 검사합니다.

API 조립 진입점은 `src/app/api/v1/evaluations.py:1250-1259`의 `_analyze_bid`이며, 선택된 규칙 결과를 계산으로 넘깁니다. 다만 현재 코드는 `_analyze_bid`에서 `raw_data`를 resolver에 전달할 뿐 기관별 규칙을 선택하지 않습니다. `_is_local_contract` (`src/app/api/v1/evaluations.py:638-642`)은 지방 여부를 계약 방법 문자열에서 읽어 복수예가 변동 범위에 사용하며, 규칙 레지스트리 매핑 기능은 아닙니다. 함수 간 전달 방식, 기관 코드 원천, 우선순위 충돌 규칙은 확인 불가이며 구현 전 확정해야 합니다.

스냅샷 생성 경로는 `_save_snapshot_async` (`src/app/api/v1/evaluations.py:1192-1212`)로 보입니다. 저장 시점에 resolver의 판정 문맥을 함께 넘겨 새 nullable 컬럼에 기록하도록 변경하는 방안을 제안합니다. 해당 함수 호출 지점 전체에서 이 값 전달이 가능한지는 구현 단계 확인이 필요합니다.

## 5. 기관 축 유무에 따른 계산 결과

| 경우 | 축이 없을 때 | 축을 적용할 때 |
| --- | --- | --- |
| 국가·지방 기준 차이 | 동일 용역 유형·낙찰방법·공고일 조건을 만족하는 공통 규칙에서 별표, 하한율 및 배점 파라미터를 선택할 수 있습니다. 국가 ±2%와 지방 ±3% 범위 차이는 일부 가격 시나리오에서만 `_is_local_contract`가 반영하고 규칙 축 자체에는 연결되지 않습니다. | `contract_regime`가 일치하는 규칙만 후보로 삼아 해당 기준 출처의 하한율·배점표·가격 시나리오 파라미터를 선택합니다. 잘못된 법령 규칙 적용 가능성을 줄입니다. 구체 점수 차이는 등록된 기관별 규칙값에 따라 달라 현재 수치로 산출할 수 없습니다. |
| 기관·지역별 세부 기준 | 기관명이 강한 구분 신호여도 규칙 후보 선택에 반영되지 않아 기관별 규칙 차이를 선택·재현하지 못합니다. | 기관/지역 한정 규칙이 등록된 경우 공고의 범위가 일치하면 해당 규칙이 선택됩니다. 범위가 다르거나 식별이 안 되면 `ALL` 공통 규칙으로 후퇴하거나 계산 차단하는 정책을 정해야 합니다. 우선순위·후퇴 정책은 확인 불가입니다. |
| 과거 스냅샷 | `rule_id`로 별표 ID는 찾을 수 있지만 판정 당시 기관·지역을 스냅샷 열로 복원할 수 없습니다. | 새 컬럼에 그 시점의 추출값을 보존해 어떤 기관·지역 축으로 판단했는지 추적할 수 있습니다. 이미 저장된 행은 NULL이므로 소급 식별은 불가합니다. |

축 추가 자체가 점수를 바꾸는 것은 아니며, 범위에 맞는 규칙이 기존과 다른 `lwlt_rate`, `base_rate`, `max_price_score`, `multiplier`, `pass_threshold`를 가지며 선택될 때 결과가 달라집니다. 결과 JSON 세부 산식과 기관별 확정값은 이번 근거에서 확인 불가이므로 숫자 예시는 제시하지 않습니다. 규칙 후보가 없을 때 안전하게 차단할지 공통 규칙으로 후퇴할지는 구현 Task에서 결정해야 합니다.

## 6. 구현 전 확인 항목

- 공고 원자료에 기관 식별 코드 및 지역 코드가 존재하는지, 실제 키·정규화 표준
- 국가·지방 법령을 안정적으로 식별하는 원천값과 예외 처리
- `EvaluationRule`을 DB에 저장하는지 코드 상수만 사용하는지, 규칙 ID를 기관별로 재사용할지
- 기관 전용·지역 전용·공통 규칙이 겹칠 때의 우선순위와 미매칭 시 차단/후퇴 동작
- API에서 `_save_snapshot_async`까지 판정 입력 문맥을 전달하는 호출 경로
- 스냅샷 컬럼 길이·인덱스 및 실제 DB 엔진에서의 DDL 잠금·운영 영향

위 항목은 현재 확인 불가로 남기며, 구현 전에 실제 데이터와 운영 스키마를 확인해야 합니다.
