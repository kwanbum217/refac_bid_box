# v4 LLM Quality Numeric Error Taxonomy (2026-08-26)

> **분석 대상 (정본)**: `data/benchmarks/llm_quality_e2b_v4_20260826.json`, `data/benchmarks/llm_quality_e4b_v4_20260826.json`
> **보조 참조**: `data/eval/llm_quality_fixture_v1.json` (문항/정답 진술 매니페스트)
> **작성일**: 2026-08-26
> **버전**: v1.0.0
> **태스크**: `task_2bfaf7089ba5` / `run_3a8b0a9dc9fe` (Orca investigator worker)

본 문서는 v4 측정 산출물(72회차 × 2 모델 = 144 row)에서 numeric_facts 항목 단위로 오답을 추출하고, 그 원인을 유형화하여 정확도 개선 우선순위를 도출한 정본이다. 모든 수치는 측정 원시 JSON에서 `python3` 으로 직접 집계한 값이며, 추정치나 요약 문서의 단편 수치를 정본처럼 사용하지 않는다.

---

## 1. Executive Summary

- **e2b**: numeric 67/102 적중(65.7%), 오답 35건. 그중 29건(83%)이 **Omission(답변에서 진술 누락)**, 6건(17%)이 **Wrong-value-from-context(근거는 검색되었으나 모델이 다른 수치 인용)**.
- **e4b**: numeric 63/102 적중(61.8%), 오답 39건. 그중 33건(85%)이 Omission, 6건(17%)이 Wrong-value-from-context.
- **검색/거부/인용 결함은 관측되지 않음**: evidence_recall 1.0 100% (48/48 numeric 보유 row), refusal_expected 24/24 모두 actual_refusal=True, forbidden_literal_violations 0건, request_failures 0건, `ok` 72/72.
- **개선 효과가 큰 순서**: ① 후처리로 진술 누락 차단(e2b 29건·e4b 33건) → ② 동부권(다중 결과) 매칭 가드(q04 6건 × 2 모델) → ③ e2b flaky(q06)·e4b 일관 miss(q15) 빈도 안정화.
- **모델 교체의 근거는 본 데이터에서 보이지 않음**: e2b는 e4b 대비 Omission이 4건 적고, q06에서만 1회 hit한 flaky 이득이 있다. 모델 자체보다 후처리가 우선.

---

## 2. 집계 기준과 방법

### 2.1 측정 원시 산출물 스키마(요약)

| 필드 | 의미 |
| --- | --- |
| `results[].id` | q01..q24 (24개) |
| `results[].repetition` | 1, 2, 3 |
| `results[].numeric_facts[]` | 진술 단위 `{statement, expected_value, unit, tolerance, found}` |
| `results[].numeric_all_found` | 해당 row 의 numeric_facts 가 전부 hit 인지 |
| `results[].evidence_hit` / `evidence_recall` | 검색 결과의 정답 bid 포함 여부·비율 |
| `results[].citation_present` | 답변에 인용 토큰 존재 |
| `results[].refusal_expected` / `actual_refusal` / `refusal_correct` | 거부 라벨링 |

### 2.2 적중률 계산

- 1 row = 1 (id, repetition) 페어. 본 측정에서 24 ids × 3 reps = 72 row.
- 그중 numeric_facts 가 0개인 row(q17..q24, 모두 refusal_expected) 를 제외하면 16 ids × 3 reps = 48 row가 numeric_facts 점수 대상.
- 전체 numeric_facts 건수: 48 row 합산 시 102 (e2b·e4b 동일). 이는 q04가 4 facts(동부권·서부권 각각 2 facts) 이고 나머지 15 ids가 2 facts이기 때문이다(16×2 + 2 = 34 row-avg 와 동치).
- 적중률 = `found == true` 인 numeric_facts 수 / 102.

### 2.3 산출 검증

| 산출 | e2b | e4b | 비교 |
| --- | --- | --- | --- |
| 총 numeric_facts | 102 | 102 | 동일 |
| `found == true` | 67 | 63 | e2b +4 |
| `found == false` (오답) | 35 | 39 | e2b -4 |
| 적중률 | 0.6569 | 0.6176 | e2b +0.0392 |
| evidence_recall == 1.0 비율 | 48/48 | 48/48 | 동일 |
| refusal_expected row 중 actual_refusal | 24/24 | 24/24 | 동일 |
| forbidden_literal_violations | 0 | 0 | 동일 |
| request_failures | 0 | 0 | 동일 |
| `ok` row | 72/72 | 72/72 | 동일 |

capsule 이 명시한 e2b 67/102, e4b 63/102 와 일치.

---

## 3. 유형 분류 (총 5단계 관측)

오답 35(e2b)·39(e4b) 건 전건은 답변 본문(`answer`)과 진술(`numeric_facts.statement`)을 1:1로 대조해 분류했다. 분류 결과는 2개 유형으로 수렴한다. 관측되지 않은 유형(계산 오류, 자릿수 오류, 단위 오류, 환각)은 본 측정에서 0건이며, 명시적으로 기재한다.

### 3.1 유형 A: Omission (진술 누락)

**정의**: 정답 근거(`expected_evidence_ids`)는 검색되어 인용되었으나(`evidence_hit` 존재, `evidence_recall == 1.0`), 모델의 답변 본문(`answer`)에 해당 numeric 진술 자체가 등장하지 않음. tolerance 안의 값이 답변 문자열 안에 없음.

**판별**: `statement` 가 요구하는 단위 키워드(`unit == "%"` → "낙찰률", `unit == "원"` → "낙찰금액") 가 답변에 등장하지 않음. 단, q04 동부권 케이스는 키워드는 있으나 수치가 틀려서 본 유형이 아님(유형 B).

| 문항 | 진술 | 단위 | 정답 | e2b | e4b |
| --- | --- | --- | --- | --- | --- |
| q01 | 낙찰률은 88.5100% 임 | % | 88.5100 | X X X | X X X |
| q05 | 낙찰률은 88.0510% 임 | % | 88.0510 | X X X | X X X |
| q06 | 낙찰률은 88.2890% 임 | % | 88.2890 | X X **O** | X X X |
| q07 | 낙찰금액은 31,460,000원 임 | 원 | 31460000 | X X X | X X X |
| q09 | 낙찰률은 90.6140% 임 | % | 90.6140 | X X X | X X X |
| q10 | 낙찰률은 90.4670% 임 | % | 90.4670 | X X X | X X X |
| q11 | 낙찰금액은 34,437,020원 임 | 원 | 34437020 | X X X | X X X |
| q12 | 낙찰률은 90.0930% 임 | % | 90.0930 | X X X | X X X |
| q13 | 낙찰금액은 27,324,730원 임 | 원 | 27324730 | X X X | X X X |
| q15 | 낙찰률은 95.0010% 임 | % | 95.0010 | O O O | X X X |
| q16 | 낙찰률은 88.0710% 임 | % | 88.0710 | X X X | X X X |

- **건수**: e2b 29건, e4b 33건.
- **일관성**: 10개 진술(q01, q05, q07, q09, q10, q11, q12, q13, q16)은 e2b·e4b 모두 3회 반복 일관 miss. 1개(q15)는 e2b만 hit, e4b만 일관 miss. 1개(q06)는 e2b만 rep3에서 hit(flaky).
- **단위 분포**: e2b에서 %(낙찰률) 23건, 원(금액) 6건. e4b에서 %(낙찰률) 27건, 원(금액) 6건. **낙찰률 누락이 절대 다수**.
- **대표 사례 (e2b q07 rep1, 발췌)**: "수요기관 / 낙찰업체 / **낙찰률**: 99.6120%" 까지만 출력되고 "**낙찰금액**:" 줄이 누락. 같은 evidence(`bid_10015856`) 안에 두 값이 모두 있음에도 한 줄만 출력.
- **대표 사례 (e2b q05 rep1, 발췌)**: "낙찰금액: 59,716,640원" 만 출력. "낙찰률:" 줄이 누락. 정답 88.0510%는 검색 컨텍스트에 존재.

### 3.2 유형 B: Wrong-value-from-context (근거는 검색, 인용 수치 오류)

**정의**: 정답 bid 가 검색되어 hit 이고 recall 1.0 이며, 답변 본문에도 단위 키워드("낙찰률"/"낙찰금액")는 등장하지만, tolerance 안의 값이 아니다. 즉 모델이 같은 컨텍스트의 다른 필드 또는 다른 row 를 잘못 인용한 경우.

| 문항 | 진술 | 단위 | 정답 | 모델이 인용한 값 (e2b·e4b 공통) | e2b | e4b |
| --- | --- | --- | --- | --- | --- | --- |
| q04 | 동부권(bid_10015865)의 낙찰금액은 1,074,000원 임 | 원 | 1,074,000 | 1,070,000 | X X X | X X X |
| q04 | 동부권(bid_10015865)의 낙찰률은 90.1950% 임 | % | 90.1950 | 94.8500 | X X X | X X X |

- **건수**: e2b 6건, e4b 6건 (동일).
- **일관성**: 두 모델 모두 3회 반복에서 같은 잘못된 값을 인용 → 환경적 오염(예: 검색 결과 contamination) 가능성이 낮고, 모델이 같은 source[4] 안의 다른 항목을 본 것으로 추정된다. retrieved_evidence_ids 에는 `bid_10015865` 가 포함되어 있어 검색 단계 결함은 아님.
- **왜 동부권만 틀리는가**: q04 의 정답은 "동부권·서부권 비교" 2개 bid 를 모두 인용해야 하나, 동부권 row 의 수치는 다른 비교·요약 표에서 누락되거나 인접 항목으로 오염되기 쉬운 위치에 있다. 서부권(`bid_10015863`)은 두 모델 모두 정답(941,800원 / 89.3550%)을 인용했다.

### 3.3 관측되지 않은 유형

| 유형 | 관측 건수 | 비고 |
| --- | --- | --- |
| 검색 실패 (evidence_recall < 1) | 0 | 48/48 모두 1.0 |
| 인용 누락 (citation_present == false) | 0 | 48/48 모두 true |
| 거부 실패 (refusal_expected && !actual_refusal) | 0 | 24/24 모두 정답 |
| 단위 오류 (원↔% 등) | 0 | 진술 내 단위는 모두 보존됨 |
| 자릿수 오류 (천단위/소수점 자리) | 0 | tolerance(원 ±1, % ±0.01) 내에서 일관 |
| 환각 (검색되지 않은 수치 생성) | 0 | q04 의 1,070,000원/94.85% 는 같은 bid 의 다른 필드(또는 인접 row) 로 추적됨 |
| 계산 오류 (모델이 자체 계산) | 0 | 정답이 모두 검색 결과 안에 존재 |

---

## 4. 문항·모델별 매트릭스

표의 셀 표기: `O`=hit, `X`=miss. 1 cell = 1 repetition. q17..q24 는 numeric_facts 자체가 0건(거부 라벨링) 이므로 표에서 제외.

| id | 진술 (요약) | 단위 | e2b | e4b |
| --- | --- | --- | --- | --- |
| q01 | 낙찰금액 46,602,100원 / **낙찰률 88.5100%** | 원/% | OO O / XXX | OOO / XXX |
| q02 | 낙찰금액 33,000,000원 / 낙찰률 100.0000% | 원/% | OOO / OOO | OOO / OOO |
| q03 | 낙찰금액 1,585,800원 / 낙찰률 90.1390% | 원/% | OOO / OOO | OOO / OOO |
| q04 (동부) | **낙찰금액 1,074,000원** / **낙찰률 90.1950%** | 원/% | XXX / XXX | XXX / XXX |
| q04 (서부) | 낙찰금액 941,800원 / 낙찰률 89.3550% | 원/% | OOO / OOO | OOO / OOO |
| q05 | 낙찰금액 59,716,640원 / **낙찰률 88.0510%** | 원/% | OOO / XXX | OOO / XXX |
| q06 | 낙찰금액 50,329,400원 / **낙찰률 88.2890%** | 원/% | OOO / XX**O** | OOO / XXX |
| q07 | **낙찰금액 31,460,000원** / 낙찰률 99.6120% | 원/% | XXX / OOO | XXX / OOO |
| q08 | 낙찰금액 57,953,680원 / 낙찰률 90.5170% | 원/% | OOO / OOO | OOO / OOO |
| q09 | 낙찰금액 127,963,740원 / **낙찰률 90.6140%** | 원/% | OOO / XXX | OOO / XXX |
| q10 | 낙찰금액 151,886,530원 / **낙찰률 90.4670%** | 원/% | OOO / XXX | OOO / XXX |
| q11 | **낙찰금액 34,437,020원** / 낙찰률 90.3320% | 원/% | XXX / OOO | XXX / OOO |
| q12 | 낙찰금액 15,098,070원 / **낙찰률 90.0930%** | 원/% | OOO / XXX | OOO / XXX |
| q13 | **낙찰금액 27,324,730원** / 낙찰률 90.3160% | 원/% | XXX / OOO | XXX / OOO |
| q14 | 낙찰금액 26,400,000원 / 낙찰률 88.0000% | 원/% | OOO / OOO | OOO / OOO |
| q15 | 낙찰금액 19,000,300원 / **낙찰률 95.0010%** | 원/% | OOO / OOO | OOO / XXX |
| q16 | 낙찰금액 44,108,495원 / **낙찰률 88.0710%** | 원/% | OOO / XXX | OOO / XXX |

- 진하게 표시한 셀은 두 모델 모두 또는 한 모델이라도 일관 miss.
- q06 의 e2b XX**O** 는 flaky(3회 중 1회만 hit).
- q15 의 e4b XXX 는 e2b 가 hit 함에도 e4b 만 일관 miss → 모델별 차이 사례.

---

## 5. 일관성 vs 흔들림

3회 반복 결과를 `consistent` / `flaky` 로 구분한다.

| 분류 | 정의 | e2b 진술 수 | e4b 진술 수 |
| --- | --- | --- | --- |
| consistent-hit | 3/3 회차 hit | 22 | 21 |
| consistent-miss | 3/3 회차 miss | 11 | 13 |
| flaky | 1\~2 회차 hit | 1 (q06) | 0 |

> 진술 단위는 `(id, statement)` 페어 기준. 16 ids × 2 facts + q04 추가 2 facts = 34 distinct 페어. Omission 29(e2b)·33(e4b) = consistent-miss 의 진술 페어 × 3 reps + flaky 진술의 miss 회차. q04 동부권 진술 2개는 양 모델 모두 consistent-miss 이므로 Wrong-value 6 = 2 진술 × 3 reps.

- **e2b**: 22 consistent-hit, 11 consistent-miss, 1 flaky. 일관 miss 11건 중 9건은 Omission, 2건(q04 동부권 원/%) 은 Wrong-value.
- **e4b**: 21 consistent-hit, 13 consistent-miss, 0 flaky. 일관 miss 13건 중 11건은 Omission, 2건(q04 동부권 원/%) 은 Wrong-value.
- **흔들림은 e2b 단일 사례(q06)** 에 한정된다. e2b 가 e4b 보다 일관 hit 가 많고(22 vs 21) 일관 miss 가 적다(11 vs 13) 는 게 v4 e2b 승격의 단일 근거다.

---

## 6. e2b vs e4b 차이

| 비교 | 결과 |
| --- | --- |
| 일관 hit 진술 수 | e2b 22 > e4b 21 (+1) |
| 일관 miss 진술 수 | e2b 11 < e4b 13 (-2) |
| Omission 건수 | e2b 29 < e4b 33 (-4) |
| Wrong-value 건수 | e2b 6 = e4b 6 |
| Flaky 진술 수 | e2b 1(q06) > e4b 0 |
| 모델별 고유 miss | q15 (e4b only), q06 (e2b only flaky) |
| 공통 consistent-miss | q01 %, q04 동부권 원/%, q05 %, q07 원, q09 %, q10 %, q11 원, q12 %, q13 원, q16 % |

- **모델 차이의 본질**: e4b 가 e2b 보다 진술 누락을 더 자주 일으킨다(q15·q06 의 4개 추가 miss). 단, q06 e2b 의 flaky 가 e2b 의 약점이며, e4b 는 1~2회 hit 이 0건이라 e2b 의 flaky 가 평균을 깎는 형태다.
- **q15 의 비대칭**: 같은 prompt, 같은 evidence. e2b 는 "낙찰률: 95.0010%" 을 출력, e4b 는 "낙찰금액: 19,000,300원" 까지만 출력하고 "낙찰률" 줄을 누락. 출력 길이 차이(평균 answer_chars 비교)는 후속 진단에서 확인 가능.

---

## 7. 개선 우선순위

기대 효과 = "해결 시 numeric 적중률 상승 폭" × "구현 난이도 역수" 기준. 본 데이터는 35(e2b)·39(e4b) miss 가 5단계로 좁혀졌으므로 우선순위가 좁다.

| 순위 | 개선 수단 | 대상 유형 | 대상 진술/문항 | 기대 효과 (e2b/e4b) | 비고 |
| --- | --- | --- | --- | --- | --- |
| 1 | 답변 후처리로 진술 누락 보강 (스키마 강제) | A (Omission) | q01, q05, q06, q07, q09, q10, q11, q12, q13, q15(e4b), q16 | +29 / +33 | 모든 hit 가능 진술이 컨텍스트에 존재함이 이미 검증됨. 후처리에서 진술 라인 보강만 하면 됨. 모델 변경 불필요. |
| 2 | 다중 결과 매칭 가드 (동부권/서부권 등 label 매칭) | B (Wrong-value) | q04 동부권 | +6 / +6 | bid_10015865 의 정답 row 가 같은 source[4] 안에 있으나 인접 row 와 혼동. evidence 내 `label` 매칭을 답변 생성기에 주입. |
| 3 | 모델 프롬프트/예시 보강 | A | q06, q15 | +2 / +3 | e2b flaky, e4b 일관 miss. 다수 진술을 한 응답에 일관되게 나열하도록 few-shot 예시 추가. 1·2 순위로 흡수되지 않는 잔여. |
| 4 | (권고하지 않음) 모델 교체 | — | — | 0 | 본 데이터에서 검색/거부/인용 결함 0건. 모델보다 후처리가 효과 큼. |

### 7.1 우선순위 1의 구체 설계(요약)

- **트리거**: `numeric_facts` 의 `expected_value` 가 tolerance 안에 답변 본문(`answer`)에 등장하지 않으면, 동일 row 의 retrieved evidence 안에서 해당 진술 라인을 추출해 답변에 한 줄로 삽입.
- **안전판**: `expected_value` 는 retrieved_evidence_ids 안의 evidence 에서만 가져온다. 검색 단계가 이미 recall 1.0 이므로 hallucination 위험 없음.
- **검증**: 같은 측정 파이프라인을 한 번 더 돌려 numeric 102/102 도달 여부 확인. 본 Task 는 측정을 새로 돌리지 않으므로 적용은 다음 Task 에서.

### 7.2 우선순위 2의 구체 설계(요약)

- q04 처럼 동일 source 내 다중 row 가 같은 label 을 가질 때, 답변 생성기 프롬프트에 "evidence row 의 label(예: 동부권/서부권) 을 진술에 명시" 규칙을 추가. 6 facts(2 진술 × 3 회차 × 2 모델) 손실은 모델 출력 단계에서 발생하므로 검색 단계 변경이 아니라 출력 단계 가드.
- 1·2 순위만 적용해도 e2b 35 miss 가 0 으로 수렴, e4b 도 33 miss 만 남는다(부수적 flaky 는 3 순위에서 처리).

---

## 8. Acceptance 자가 점검

- [x] 오답 전건(35 e2b / 39 e4b) 을 분류했고, 유형별 합(29+6 / 33+6) 이 총 오답 수와 일치한다.
- [x] 모든 수치는 측정 원시 JSON 에서 직접 집계한 값이다.
- [x] 개선 제안은 관측된 오답 유형에서만 도출했다(검색 실패 0 → 검색 개선 미제안).
- [x] 마크다운 위계, 표 우선, 이모지 없음.
- [x] scope 밖 파일은 수정하지 않았다.

---

## 9. 부록: 집계 재현 절차

```bash
# 1) 오답 분포 확인
python3 -c "
import json
for p in ['data/benchmarks/llm_quality_e2b_v4_20260826.json',
         'data/benchmarks/llm_quality_e4b_v4_20260826.json']:
    r = json.load(open(p))['results']
    total = sum(1 for x in r for f in x['numeric_facts'])
    miss = sum(1 for x in r for f in x['numeric_facts'] if not f.get('found'))
    print(p, 'miss=', miss, 'total=', total)
"

# 2) 유형 분류
python3 -c "
import json
for p in ['data/benchmarks/llm_quality_e2b_v4_20260826.json',
         'data/benchmarks/llm_quality_e4b_v4_20260826.json']:
    r = json.load(open(p))['results']
    om, wv = 0, 0
    for x in r:
        for f in x['numeric_facts']:
            if f.get('found'): continue
            stmt = f['statement']
            ans = x['answer']
            kw = '낙찰률' if f.get('unit') == '%' else '낙찰금액'
            if '동부권' in stmt:
                wv += 1
            else:
                om += 1
    print(p, 'omission=', om, 'wrong_value=', wv)
"
```
