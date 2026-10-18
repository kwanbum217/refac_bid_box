# 남은 자동 계산 차단 상위 3종 원인 조사

> **작성일**: 2026-10-18
> **기준 원장**: `data/reference/rule_coverage_ledger.yaml` (생성 2026-10-18 04:55, `--months 12 --category Servc --method-code 낙030001 --min-announcements 5`)
> **대상 코드**: `RULE_REGIME_MISMATCH`, `NON_PRED_PRICE`, `LOCAL_RULE_NOT_FOUND`
> **판정 코드**: `src/app/services/evaluation_rules.py`
> **범위**: 조사 문서 한 건. 코드·규칙·원장은 변경하지 않았다.

## 1. 요약

자동 계산 차단 10,304건 중 수기심사(`MANUAL_EVALUATION`, 8,220건)를 제외한 나머지 자동 차단 상위 3종의 합계는 729건이다.
세 코드의 발생 기관·계약 법령·소관구분 분포와 판정 코드상 원인, 해소 후보 분류는 아래와 같다.

| 차단 코드 | 건수 | 기관 수 | 주 계약 법령 | 주 소관구분 | 해소 후보 |
| --- | ---: | ---: | --- | --- | --- |
| `RULE_REGIME_MISMATCH` | 391 | 86 | LOCAL 364, NATIONAL 27 | 지방자치단체 256, 교육기관 88 | 정상 차단 유지 (구판 규칙 추가 가능) |
| `NON_PRED_PRICE` | 185 | 50 | LOCAL 153, NATIONAL 10, 미상 22 | 지방자치단체 122, 지방공기업 31 | 정상 차단 유지 |
| `LOCAL_RULE_NOT_FOUND` | 153 | 48 | LOCAL 153 | 지방자치단체 107, 지방공기업 23, 교육기관 23 | 규칙 추가 필요 + 판별 보강 |

## 2. 집계 기준

원장 `institutions` 1,112곳의 `block_codes` 를 합산했다(`tail` 은 코드별 상세가 없어 제외).
기관별 합계는 원장과 정확히 일치한다(RULE_REGIME_MISMATCH 391, NON_PRED_PRICE 185, LOCAL_RULE_NOT_FOUND 153).

## 3. 차단 코드별 발생 분포

### 3.1 RULE_REGIME_MISMATCH (391건, 86곳)

공고일이 매칭된 별표의 시행일보다 앞서 해당 별표로 계산하지 않는 경우다.

상위 기관 10곳(차단 건수 순):

| 순위 | 기관 코드 | 기관명 | 건수 | 계약 법령 | 소관구분 |
| ---: | --- | --- | ---: | --- | --- |
| 1 | 6130769 | 전남광주통합특별시 무안청사 | 23 | LOCAL | 지방자치단체 |
| 2 | B551178 | 한국공항공사 | 19 | NATIONAL | 공기업 |
| 3 | 8512000 | 전남광주통합특별시교육청 여수교육지원청 | 15 | LOCAL | 교육기관 |
| 4 | 6440000 | 충청남도 | 12 | LOCAL | 지방자치단체 |
| 5 | 8662000 | 전남광주통합특별시교육청 무안교육지원청 | 12 | LOCAL | 교육기관 |
| 6 | 5860000 | 전남광주통합특별시 장흥군 | 11 | LOCAL | 지방자치단체 |
| 7 | 4520000 | 충청남도 아산시 | 10 | LOCAL | 지방자치단체 |
| 8 | 5110000 | 경상북도 상주시 | 10 | LOCAL | 지방자치단체 |
| 9 | 6441406 | 충청남도 건설본부 | 10 | LOCAL | 지방자치단체 |
| 10 | 7402000 | 전남광주통합특별시교육청 광주서부교육지원청 | 10 | LOCAL | 교육기관 |

지역(기관명 첫 토큰) 상위: 충청남도 107, 전남광주통합특별시교육청 88, 전남광주통합특별시 81, 경상북도 38, 한국공항공사 19.

코드 원인: `src/app/services/evaluation_rules.py:7864-7875` (`resolve_evaluation_rule` 말미, `announced < effective_date` 이면 `BLOCK_CODE_RULE_REGIME_MISMATCH` 로 차단).
보조 경로: `src/app/services/evaluation_rules.py:7469-7484` (`_allocate_rules_for_announcement`, 개정 전 구간 공고가 현행 벌에만 있는 이름을 쓸 때 현행 별표로 매칭해 같은 시행일 대조에서 차단).

해소 후보: 정상 차단 유지가 기본이다. 공고일이 별표 시행일보다 앞선 공고는 해당 별표로 계산하면 안 된다.
검증된 구판 규칙이 있는 경우에만 규칙 추가로 해소한다(이미 반영: 전라남도 예규 제1075호, 광주 예규 제377호, 기술용역 구판).
한국공항공사·충청남도·전남광주 계열 잔여 건은 구판 원문 확보 후 규칙 추가 대상이다.

### 3.2 NON_PRED_PRICE (185건, 50곳)

예정가격 결정 방법이 `비예가` 인 공고로, 가격점수 산출 분모가 없어 계산할 수 없는 경우다.

상위 기관 10곳(차단 건수 순):

| 순위 | 기관 코드 | 기관명 | 건수 | 계약 법령 | 소관구분 |
| ---: | --- | --- | ---: | --- | --- |
| 1 | Z007503 | 인천도시공사 | 22 | LOCAL | 지방공기업 |
| 2 | 5895000 | 전남광주통합특별시 장성군 | 13 | LOCAL | 지방자치단체 |
| 3 | 5420000 | 경상남도 고성군 | 12 | LOCAL | 지방자치단체 |
| 4 | 5855000 | 전남광주통합특별시 화순군 | 10 | LOCAL | 지방자치단체 |
| 5 | 7004263 | 서정대학 | 9 | 미상 | 교육기관 |
| 6 | 6130769 | 전남광주통합특별시 무안청사 | 8 | LOCAL | 지방자치단체 |
| 7 | B090001 | 한국개발연구원 | 8 | 미상 | 기타공공기관 |
| 8 | 4490000 | 충청남도 천안시 | 7 | LOCAL | 지방자치단체 |
| 9 | 5885000 | 전남광주통합특별시 함평군 | 7 | LOCAL | 지방자치단체 |
| 10 | 5910000 | 전남광주통합특별시 신안군 | 6 | LOCAL | 지방자치단체 |

지역(기관명 첫 토큰) 상위: 전남광주통합특별시 69, 인천도시공사 22, 경상남도 14, 경상북도 13, 서정대학 9, 강원특별자치도 8.

코드 원인: `src/app/services/evaluation_rules.py:7916-7923` (`_resolve_by_method_name` 2단계, `prearng_prce_dcsn_mthd_nm` 에 `비예가` 가 포함되면 `BLOCK_CODE_NON_PRED_PRICE` 로 차단).

해소 후보: 정상 차단 유지다. 비예가 공고는 예정가격이 없어 가격점수 분모를 만들 수 없으므로 자동 계산 대상이 아니다.
`prearngPrceDcsnMthdNm` 표기 오류가 의심되는 공고는 공고문 직접 확인으로만 풀 수 있다.

### 3.3 LOCAL_RULE_NOT_FOUND (153건, 48곳)

계약 법령이 LOCAL 인데 수요기관 시·도에 해당하는 지방계약 규칙이 없는 경우다.

상위 기관 10곳(차단 건수 순):

| 순위 | 기관 코드 | 기관명 | 건수 | 계약 법령 | 소관구분 |
| ---: | --- | --- | ---: | --- | --- |
| 1 | 5910000 | 전남광주통합특별시 신안군 | 18 | LOCAL | 지방자치단체 |
| 2 | 6130769 | 전남광주통합특별시 무안청사 | 13 | LOCAL | 지방자치단체 |
| 3 | Z008548 | 서울특별시서대문구도시관리공단 | 12 | LOCAL | 지방공기업 |
| 4 | 5790000 | 전남광주통합특별시 순천시 | 8 | LOCAL | 지방자치단체 |
| 5 | 4610000 | 충청남도 예산군 | 6 | LOCAL | 지방자치단체 |
| 6 | 5800000 | 전남광주통합특별시 광양시 | 6 | LOCAL | 지방자치단체 |
| 7 | 5885000 | 전남광주통합특별시 함평군 | 6 | LOCAL | 지방자치단체 |
| 8 | 4620000 | 충청남도 태안군 | 6 | LOCAL | 지방자치단체 |
| 9 | 8692000 | 전남광주통합특별시교육청 장성교육지원청 | 4 | LOCAL | 교육기관 |
| 10 | 8502000 | 전남광주통합특별시교육청 목포교육지원청 | 4 | LOCAL | 교육기관 |

지역(기관명 첫 토큰) 상위: 전남광주통합특별시 74, 충청남도 29, 전남광주통합특별시교육청 23, 서울특별시서대문구도시관리공단 12, 대구 3.

코드 원인: `src/app/services/evaluation_rules.py:6832-6834` (`_select_local_rule`, `_narrow_to_current_regime` 결과가 비면 `BLOCK_CODE_LOCAL_RULE_NOT_FOUND` 로 차단).
추가 경로: `src/app/services/evaluation_rules.py:6898-6899` (서비스 유형 후보가 없을 때 같은 코드로 차단).

해소 후보: 규칙 추가 필요가 주다. 시·도 자체 별표가 확보되지 않은 지역·서비스 유형 조합에 규칙을 추가해야 한다.
교육 계열 공고는 시·도 미산출 시 조달청 기준으로 대체되므로(교육청 23건은 시·도 산출 실패가 아닌 규칙 부재) 판별 보강 여지도 있다.

## 4. 해소 후보 요약

| 차단 코드 | 1순위 후보 | 2순위 후보 | 정상 차단 유지 근거 |
| --- | --- | --- | --- |
| `RULE_REGIME_MISMATCH` | 정상 차단 유지 | 검증된 구판 규칙 추가(한국공항공사·충남·전남광주 잔여) | 공고일 < 시행일이면 해당 별표로 계산 금지 |
| `NON_PRED_PRICE` | 정상 차단 유지 | 공고문 직접 확인(표기 오류) | 비예가 공고는 가격점수 분모 부재 |
| `LOCAL_RULE_NOT_FOUND` | 시·도 규칙 추가 | 서비스 유형 판별 보강(교육 계열 포함) | 행안부 기본 규칙을 만들지 않는 D8 정책 |

## 5. 부록: 재계산 스크립트

아래 한 줄을 그대로 실행하면 세 코드의 기관별 건수와 분포를 재계산할 수 있다.

```python
uv run python -c "
import yaml
from collections import Counter
d=yaml.safe_load(open('data/reference/rule_coverage_ledger.yaml',encoding='utf-8'))
for code in ['RULE_REGIME_MISMATCH','NON_PRED_PRICE','LOCAL_RULE_NOT_FOUND']:
    rows=sorted(((inst.get('block_codes',{}).get(code,0),inst) for inst in d['institutions'] if inst.get('block_codes',{}).get(code,0)),reverse=True)
    reg=Counter(); jur=Counter()
    for c,inst in rows:
        reg[inst.get('contract_regime')]+=c; jur[inst.get('jurisdiction')]+=c
    print(code,'total',sum(c for c,_ in rows),'insts',len(rows))
    print('  regime',dict(reg))
    print('  juris',dict(jur))
    for c,inst in rows[:10]:
        print(' ',c,inst['dminstt_cd'],inst['dminstt_nm'])
"
```
