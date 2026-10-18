# 통합 이전 전남광주 공고가 전신 기준을 받지 못하는 원인 조사

> **작성일**: 2026-10-18
> **작업**: Orca `task_13f5efeaa6e3` (investigator)
> **정본 사양**: `.orca/capsules/task_predecessor_rules_b_20261018/capsule.yaml`
> **기준 원장**: `.cache/blocks.json` (191건, `RULE_REGIME_MISMATCH`, Servc, 낙030001, 최신 차수, 2025-10-18~2026-10-18)
> **판정 코드**: `src/app/services/evaluation_rules.py`, `src/app/services/demand_institutions.py`
> **범위**: 조사 문서 한 건. 코드·규칙·원장은 변경하지 않았다.

---

## 1. 요약

1. 191건 모두 공고일이 `SERVC_LOCAL_JNGJ_20260716_ATTACH_*` 의 시행일(2026-07-16)보다 앞서 `RULE_REGIME_MISMATCH` 로 차단되었다. 이 공고들은 통합 지침 시행 전 공고이므로 전신 기준(전라남도 예규 제1075호, 광주 예규 제377호)이 적용되어야 하나, 코드상 전신 기준 후보에 오르지 못한다.
2. 직접 원인은 지역 코드 판별이다. 수요기관이 통합 뒤 `전남광주통합특별시` 명칭으로 등록되어 `region_code` 가 `"12"` 로 남고, 통합 코드에서 옛 코드로 가는 `REGION_CODE_EQUIVALENTS` 는 `"12" -> {"46","29"}` 한 방향뿐이라 옛 코드(46/29) 규칙은 `"12"` 공고의 후보에 들지 못한다. `institution_sido` 도 통합 명칭만으로는 옛 계열(전라남도/광주)을 복원하지 못한다.
3. 그 결과 `_select_local_rule` 이 현행 JNGJ 규칙만 골라 `_narrow_to_current_regime` 에서 공고일 대조로 차단한다(`evaluation_rules.py:7864-7875`).
4. 191건 중 178건은 WASTE·LAND_TRANSPORT 로, 두 전신 기준 모두 해당 별표를 가지므로 판별 보강만으로 풀 수 있다. 13건은 FACILITY·SW 로, 광주 전신 기준에는 해당 별표가 없고 전라남도 전신 기준에는 있으나 미등록이라 원문 확보가 필요하다.

---

## 2. 코드 원인 (file:line)

### 2.1 지역 코드가 통합 코드로 고정된다

- `demand_institutions.py:260-266` `SIDO_ALIASES`: `"전라남도"`, `"광주광역시"` 를 `"전남광주통합특별시"` 로 정규화한다.
- `demand_institutions.py:271-274` `PRE_MERGE_SIDO_CODES`: 옛 계열 코드(`"46"`, `"29"`) 는 `toplvl_instt_nm` 또는 `rgn_nm` 첫 토큰이 옛 이름일 때만 반환한다.
- `demand_institutions.py:297-332` `institution_sido`: 통합 명칭만 있는 기관은 `rgn_nm` 첫 토큰이 `"전남광주통합특별시"` 라 `PRE_MERGE_SIDO_CODES` 에 없어 통합 코드 `"12"` 를 그대로 반환한다. 옛 계열 복원 실패.

### 2.2 지역 코드 등가가 한 방향이다

- `evaluation_rules.py:7307-7313` `REGION_CODE_EQUIVALENTS`: `MERGED_REGION_CODE "12" -> {"46","29"}` 만 정의되어 있다. 전신 기준 규칙(`region_code` `"46"`/`"29"`)이 `"12"` 공고 후보에 들지 못한다.
- `evaluation_rules.py:6774-6834` `_select_local_rule`: `base_candidates` 가 `sido_code`/`region_name` 축으로 필터링되므로 `"12"` 공고에는 JNGJ 규칙만 남는다. 전신 기준 후보가 없다.

### 2.3 전신 기준 후보가 좁혀지지 않는다

- `evaluation_rules.py:6719-6748` `_narrow_to_current_regime`: 같은 세부유형 그룹에서 공고일이 효력 구간에 드는 규칙만 남긴다. 후보 자체에 전신 기준이 없으므로 JNGJ 규칙만 남는다.
- `evaluation_rules.py:7463-7484` `_allocate_rules_for_announcement`: 낙찰방법명이 전신 기준 패턴과 맞더라도 `_select_local_rule` 이 지역 축으로 JNGJ 로 덮어쓴다.

### 2.4 시행일 대조에서 차단된다

- `evaluation_rules.py:7864-7875` `resolve_evaluation_rule` 말미: `announced < effective_date`(JNGJ 2026-07-16) 이면 `BLOCK_CODE_RULE_REGIME_MISMATCH` 로 차단한다.

---

## 3. 공고 단위 분류

| 구분 | 건수 | region_name | matched_rule_id (JNGJ) | 세부유형 |
| --- | ---: | --- | --- | --- |
| 판별 보강 대상 (Bucket A) | 178 | 전남광주통합특별시 178 | ATTACH_03 92, ATTACH_05 86 | WASTE, LAND_TRANSPORT |
| 원문 필요 (Bucket B) | 13 | 전남광주통합특별시 7, 전라남도 6 | ATTACH_01 11, ATTACH_02 2 | FACILITY, SW |
| 합계 | 191 | 전남광주통합특별시 185, 전라남도 6 | ATTACH_03 92, ATTACH_05 86, ATTACH_01 11, ATTACH_02 2 | - |

Bucket B 중 전라남도 6건은 `region_code "46"` 공고이나 `_select_local_rule` 이 FACILITY 세부유형에서 전신 기준 미등록으로 JNGJ 만 골라 같은 차단에 떨어졌다.

---

## 4. 판별 보강으로 풀리는 몫 (Bucket A, 178건)

- 대상 세부유형: WASTE(92), LAND_TRANSPORT(86).
- 두 전신 기준 모두 해당 별표를 등록해 두었다.
  - 전라남도 예규 제1075호: 별표 4 폐기물처리용역, 별표 5 육상운송용역 (`evaluation_rules.py:2767-2870`, `sido_code="46"`).
  - 광주 예규 제377호: 별표 1-3 폐기물처리용역, 별표 1-5 육상운송용역 (`evaluation_rules.py:2873-2944`, `sido_code="29"`).
- 따라서 지역 코드만 옛 계열로 복원하면 기존 등록 규칙으로 계산할 수 있다. 새 원문 추출이 필요 없다.
- 필요한 보강: `institution_sido` 또는 보고 경로에서 통합 명칭 기관의 옛 계열(46/29)을 결정하는 판별(기관 코드 대역, 소재지, 수요기관 변경 이력 등)과 `REGION_CODE_EQUIVALENTS` 양방향화 또는 등가 확장. 구체 구현은 다음 Task 범위다.

---

## 5. 전신 기준에 없는 별표, 원문이 필요한 몫 (Bucket B, 13건)

- 대상 세부유형: FACILITY(11), SW(2).
- 광주 전신 기준(예규 제377호)에는 폐기물·육상운송 별표만 있어 시설분야·정보통신 별표가 없다(광주 원문 조사 3절·4절).
- 전라남도 전신 기준(예규 제1075호)에는 별표 1 시설분야용역, 별표 3 정보통신용역이 있으나 코드에 등록된 규칙은 WASTE·LAND_TRANSPORT 뿐이다. 등록을 위해서는 별표 값 추출이 필요하다.
- 따라서 이 몫은 (a) 전라남도 별표 1·3 값을 원문에서 추출해 규칙으로 등록하거나, (b) 광주 계열에 대해 다른 기준(국가/조달청 또는 다른 예규)을 원문으로 확인해야 한다. 어느 쪽이든 원문이 필요하다.

---

## 6. 필요한 원문 목록

| 라벨 | 문서 | URL | 수령 시각 | sha256 | 상태 |
| --- | --- | --- | --- | --- | --- |
| 원문 확보 | 광주광역시 일반용역 적격심사 세부 기준 (예규 제377호, 시행 2022-11-15) | https://www.elis.go.kr/allalr/selectAlrBdtOne?alrNo=29000068001145&histNo=007 | 2026-10-17 | (gwangju_predecessor_source_20261017.md 참조) | 원문 확보. 폐기물·육상운송 값 확인. 시설분야·정보통신 별표 없음 |
| 일부 확보 | 전라남도 일반용역 적격심사 세부기준 (예규 제1075호, 시행 2023-03-02) 본문 | https://www.elis.go.kr/allalr/selectAlrBdtOne?alrNo=46000007006065&histNo=005 | 2026-10-18 | 4758640fecd696a2844019edef64e659969217eaea89204606149528e92be7d0 | 별표 목록 확인(1 시설분야, 2 어장정화·정비, 3 정보통신, 4 폐기물처리, 5 육상운송, 6 생활폐기물 수집·운반 대행). 값 미추출 |
| 미확보 | 전라남도 예규 제1075호 별표 1 (시설분야용역) 첨부 | 위 histNo=005 페이지의 별표 첨부(attlist) | - | - | FACILITY 11건 등록용 값 추출 필요 |
| 미확보 | 전라남도 예규 제1075호 별표 3 (정보통신용역) 첨부 | 위 histNo=005 페이지의 별표 첨부(attlist) | - | - | SW 2건 등록용 값 추출 필요 |
| 미확보 | 광주 계열 시설분야·정보통신 별표 대체 기준(다른 예규 또는 국가 기준) | 자치법규정보시스템·국가법령정보센터 검색 | - | - | 광주 전신 기준에 해당 별표가 없어 대체 근거 확인 필요 |

---

## 7. 부록: 재계산 스크립트

아래 한 줄을 그대로 실행하면 191건의 분류와 건수를 재계산할 수 있다.

```python
uv run python -c "
import json, collections
d=json.load(open('.cache/blocks.json'))
assert len(d)==191
bucket_a={'SERVC_LOCAL_JNGJ_20260716_ATTACH_03','SERVC_LOCAL_JNGJ_20260716_ATTACH_05'}
bucket_b={'SERVC_LOCAL_JNGJ_20260716_ATTACH_01','SERVC_LOCAL_JNGJ_20260716_ATTACH_02'}
a=[x for x in d if x['matched_rule_id'] in bucket_a]
b=[x for x in d if x['matched_rule_id'] in bucket_b]
print('total',len(d),'bucket_a',len(a),'bucket_b',len(b))
print('A by rule',collections.Counter(x['matched_rule_id'] for x in a))
print('B by rule',collections.Counter(x['matched_rule_id'] for x in b))
print('B by region',collections.Counter(x['region_name'] for x in b))
print('region_name all',collections.Counter(x['region_name'] for x in d))
"
```

실행 결과: `total 191 bucket_a 178 bucket_b 13`, A by rule ATTACH_03 92·ATTACH_05 86, B by rule ATTACH_01 11·ATTACH_02 2, B by region 전남광주통합특별시 7·전라남도 6.
