# 기술용역 적격심사·협상에의한계약 DB 실측 조사 보고서

> **조사일**: 2026-09-10
> **대상 DB**: `procurement`의 `bid_announcements`, `bid_results`
> **조사 목적**: 일반용역 적격심사 중심의 현재 지원 범위를 기술용역 적격심사와 협상에의한계약으로 넓힐 때, DB에서 실측으로 확정할 수 있는 모집단·필드·결과 연결 범위를 구분합니다.
> **조사 범위**: 공고일시 `2026-05-26` 이상 `2026-09-09` 미만. 2026-05-26 제도 개정 이후 구간만 사용했습니다.
> **실행 원칙**: 모든 DB 조회는 `uv run python scripts/db_readonly_query.py --sql "<단일 SELECT/SHOW/DESC/WITH 질의>"`를 사용했으며 DB·소스·설계 코드는 수정하지 않았습니다.

## 1. 결론 요약

### 1.1 모집단

| 대상 | 모집단 정의 | 서로 다른 `sucsfbidMthdNm` | 건수 |
| --- | --- | ---: | ---: |
| 협상 문자열 전체 | `category='Servc'`, `srvceDivNm='일반용역'`, `sucsfbidMthdNm`에 `협상` 포함 | 3 | 19,406 |
| 협상에의한계약 핵심 | 위 모집단에서 `협상에의한계약-...` 두 문자열만 | 2 | 19,405 |
| 기술용역 적격심사 | `category='Servc'`, `srvceDivNm='기술용역'`, `sucsfbidMthdNm`에 `적격심사` 포함 | 44 | 3,763 |

기존 설계서에 적힌 일반용역 주류 `협상에의한계약` 16,050건은 같은 기간·같은 일반용역 조건의 첫 번째 문자열과 일치합니다. 다만 협상에의한계약(SW사업) 3,355건도 별도 문자열로 존재하므로, 지원 범위를 넓힐 때 협상 모집단을 16,050건으로만 표시하면 실제 공고를 누락합니다.

### 1.2 실측으로 확정되는 것과 확정되지 않는 것

| 대상 | 실측으로 확정 가능 | 이 DB만으로 확정 불가 |
| --- | --- | --- |
| 협상에의한계약 | 문자열별 모집단, 기술·가격 평가비율, 비율별 건수, `techAbltEvlRt`·`bidPrceEvlRt`의 필드 존재 | 가격점수의 계수 `k`, 별도 가격배점 한도 `B`의 산식 의미, 통과점수 `T`, 공고문별 세부 평가기준·가감점·동점자 기준 |
| 기술용역 적격심사 | 44개 식별 문자열, 문자열별 건수, `sucsfbidLwltRate` 최빈값·결측률·최소·최대 | 44개 문자열을 하나의 공통 배점표로 환원하는 규칙, PQ·사후PQ·지역업체·기술인평가의 세부 점수, `B`·`k`·`T` |

협상 모집단에서는 기술·가격 비율 필드가 사실상 전량에 있지만, 그것만으로 가격점수 산식을 재현할 수 없습니다. 기술용역 적격심사에서는 하한율 필드가 전량 존재해도 문자열별 값과 예외값이 달라 외부 배점표를 공통 규칙으로 채택할 근거가 없습니다.

### 1.3 낙찰 결과 연결

낙찰 결과 테이블의 실제 이름은 `bid_results`입니다. `bid_announcements`와의 논리적 조인 키는 `bid_ntce_no`, `bid_ntce_ord`, `category` 세 필드이며, 애플리케이션은 차수 앞의 0을 제거한 정규화 비교도 시도합니다.

| 모집단 | 공고 건수 | `bid_results` 연결 건수 | 연결률 |
| --- | ---: | ---: | ---: |
| 일반용역 협상 문자열 전체 | 19,406 | 4,926 | 25.38% |
| 기술용역 적격심사 | 3,763 | 1,574 | 41.83% |

따라서 공고 원문 필드로 모집단·비율·하한율을 분석하는 것은 가능하지만, 낙찰금액·낙찰률을 붙인 결과 분석은 위 연결률의 부분집합에 한정됩니다.

## 2. 조사 기준과 원천 필드

### 2.1 공통 필터

```sql
category = 'Servc'
AND bid_ntce_dt >= '2026-05-26'
AND bid_ntce_dt < '2026-09-09'
```

`raw_data`는 `longtext` JSON이며 다음 경로를 정본으로 사용했습니다.

| JSON 경로 | 의미 | 조사 용도 |
| --- | --- | --- |
| `$.srvceDivNm` | 용역 구분 | `일반용역`과 `기술용역` 모집단 분리 |
| `$.sucsfbidMthdNm` | 낙찰방법명 | 협상·적격심사 문자열 식별 |
| `$.techAbltEvlRt` | 기술능력 평가비율 | 협상 기술평가 비율 |
| `$.bidPrceEvlRt` | 입찰가격 평가비율 | 협상 가격평가 비율 |
| `$.sucsfbidLwltRate` | 낙찰하한율 | 기술용역 하한율 분포 |
| `$.sucsfbidMthdAppStd` | 낙찰방법 적용 기준 | 협상 모집단에서 값 존재 여부 확인 |

### 2.2 모집단 정의의 주의점

협상 전체 문자열 조건에는 `다수공급자계약-적격성평가 및 가격협상(다수공급자)` 1건도 포함됩니다. 이 문자열은 문자상 `협상`을 포함하지만 `협상에의한계약`은 아니므로, 표에서는 협상 문자열 전체와 핵심 협상에의한계약을 분리했습니다.

기술용역 모집단은 `srvceDivNm='기술용역'`을 먼저 적용하고 `sucsfbidMthdNm`에 `적격심사`가 포함되는 공고를 세었습니다. 따라서 일반용역 별표 14종 문자열은 기술용역 모집단에 섞이지 않습니다.

## 3. 협상에의한계약 실측

### 3.1 문자열별 모집단과 비율 필드

| `sucsfbidMthdNm` | 건수 | `techAbltEvlRt` 값 있음 | `bidPrceEvlRt` 값 있음 | 판정 |
| --- | ---: | ---: | ---: | --- |
| 협상에의한계약-협상에 의한 낙찰자 결정 | 16,050 | 16,050 | 16,050 | 핵심 모집단 |
| 협상에의한계약-협상에 의한 낙찰자 결정(SW사업) | 3,355 | 3,355 | 3,355 | 핵심 모집단의 별도 계열 |
| 다수공급자계약-적격성평가 및 가격협상(다수공급자) | 1 | 0 | 0 | 협상 문자열에는 포함되나 별도 계약 방식 |
| **합계** | **19,406** | **19,405** | **19,405** | 핵심 협상에의한계약은 19,405건 |

`techAbltEvlRt`와 `bidPrceEvlRt`는 기술·가격 배점 비율을 식별하는 데 사용할 수 있습니다. 핵심 19,405건에서는 두 필드가 모두 100% 존재합니다. `다수공급자` 1건은 두 필드가 비어 있으므로 협상 전체를 무조건 전량 지원한다고 표현해서는 안 됩니다.

### 3.2 기술·가격 비율 조합

| 기술평가 비율 | 가격평가 비율 | 건수 |
| ---: | ---: | ---: |
| 90 | 10 | 10,614 |
| 80 | 20 | 7,975 |
| 70 | 30 | 534 |
| 100 | 0 | 130 |
| 85 | 15 | 59 |
| 50 | 50 | 29 |
| 10 | 90 | 17 |
| 60 | 40 | 14 |
| 99 | 1 | 12 |
| 95 | 5 | 7 |
| 20 | 80 | 6 |
| 30 | 70 | 3 |
| 40 | 60 | 2 |
| 75 | 25 | 2 |
| 값 없음 | 값 없음 | 1 |
| 78 | 22 | 1 |
| **합계** |  | **19,406** |

따라서 `80 대 20`, `90 대 10`과 같은 비율은 DB 필드에서 직접 식별할 수 있습니다. 그러나 비율은 배점 비율의 입력값일 뿐 가격평가의 세부 산식을 제공하지 않습니다.

### 3.3 가격점수 산식 입력의 판정

| 항목 | DB 실측 판정 | 근거 |
| --- | --- | --- |
| 기술·가격 배점 비율 | 확정 가능 | `techAbltEvlRt`, `bidPrceEvlRt` 값이 핵심 19,405건에 전량 존재 |
| 가격배점 한도 `B` | 확정 불가 | `bidPrceEvlRt`는 비율이며 가격점수 배점 한도 자체를 뜻한다고 확정할 필드가 없음 |
| 가격식 계수 `k` | 확정 불가 | JSON 키에 계수·승수·가격점수 산식 필드가 없음 |
| 통과점수 `T` | 확정 불가 | JSON 키에 통과점수·최저총점 필드가 없음 |
| 공고문별 세부 평가식 | 확정 불가 | `sucsfbidMthdAppStd` 값이 19,406건 모두 빈 문자열 |

비율 조합 중 외부 설계서의 `Nmax 70/50/30/10`, `B 30/50/70/90`과 대응시킬 수 있는 `(기술, 가격)=(70,30),(50,50),(30,70),(10,90)`도 일부 존재합니다. 그러나 실제 최다 조합은 `(90,10)` 10,614건과 `(80,20)` 7,975건이고, 외부 표의 `k`와 `T`는 DB에서 확인되지 않습니다. 그러므로 외부 표 전체를 실측 확정값으로 채택할 수 없으며, 해당 값은 검증 불가로 남겨야 합니다.

## 4. 기술용역 적격심사 실측

### 4.1 전체 분포

| 항목 | 실측 |
| --- | ---: |
| 모집단 | 3,763 |
| 서로 다른 `sucsfbidMthdNm` | 44 |
| 하한율 결측 | 0건 (0.00%) |
| 하한율 최빈값 | 79.9950 (1,030건) |
| 하한율 최소 | 1.0000 |
| 하한율 최대 | 100.0000 |

하한율 필드가 결측은 아니지만 범위가 1부터 100까지입니다. 특히 `적격심사제-관리규정외 수기심사(총점입력)` 349건은 최빈값 87.7450이어도 최소 3.0000, 최대 100.0000으로 흩어져 있어 하나의 자동 규칙으로 환원하면 안 됩니다.

### 4.2 전체 하한율 빈도

| 하한율 | 건수 | 하한율 | 건수 |
| ---: | ---: | ---: | ---: |
| 79.9950 | 1,030 | 87.7450 | 870 |
| 86.7450 | 770 | 89.7450 | 351 |
| 85.4950 | 349 | 88.7450 | 126 |
| 81.9950 | 106 | 87.4950 | 105 |
| 82.9950 | 8 | 100.0000 | 8 |
| 84.9950 | 6 | 82.9500 | 5 |
| 88.0000 | 4 | 90.0000 | 4 |
| 10.0000 | 3 | 82.4950 | 3 |
| 1.0000 | 2 | 5.0000 | 2 |
| 77.9950 | 2 | 80.4950 | 2 |
| 87.2450 | 2 | 88.8750 | 2 |
| 3.0000 | 1 | 80.4500 | 1 |
| 89.9950 | 1 |  |  |

### 4.3 식별 문자열별 건수와 하한율 분포

`최빈 하한율`은 문자열별 빈도 1위이며, 동률이면 낮은 값을 선택했습니다. 결측률은 전 항목 0.00%입니다.

| `sucsfbidMthdNm` | 건수 | 최빈 하한율 | 결측률 | 최소 | 최대 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 적격심사제-추정가격이 10억원 이상인 P.Q대상 기술용역의 평가기준 | 963 | 79.9950 | 0.00% | 1.0000 | 81.9950 |
| 적격심사제-추정가격이 2억원 미만 1억원 이상인 P.Q비대상 기술용역의 평가기준 | 602 | 87.7450 | 0.00% | 87.7450 | 89.7450 |
| 적격심사제-관리규정외 수기심사(총점입력) | 349 | 87.7450 | 0.00% | 3.0000 | 100.0000 |
| 적격심사제-추정가격이 5억원 미만인 P.Q 대상 기술용역의 평가기준 | 290 | 86.7450 | 0.00% | 86.7450 | 89.7450 |
| 적격심사제-추정가격이 고시금액 미만(건축사법에 따른 설계는 1억원 미만)인 기술용역 평가기준 | 287 | 89.7450 | 0.00% | 87.7450 | 100.0000 |
| 적격심사제-추정가격이 10억원 미만 5억원 이상인 P.Q 대상 기술용역의 평가기준 | 246 | 85.4950 | 0.00% | 85.4950 | 85.4950 |
| 적격심사제-추정가격이 5억원 미만인 P.Q 대상 기술용역의 평가기준(사후PQ) | 211 | 86.7450 | 0.00% | 85.4950 | 86.7450 |
| 적격심사제-추정가격이 5억원 미만 2억원 이상인 P.Q비대상 기술용역의 평가기준 | 122 | 86.7450 | 0.00% | 86.7450 | 86.7450 |
| 적격심사제-추정가격이 1억원 미만인 P.Q비대상 기술용역의 평가기준 | 118 | 87.7450 | 0.00% | 87.7450 | 87.7450 |
| 적격심사제-추정가격이 5억원 미만 고시금액 이상인 P.Q대상 기술용역 평가기준 | 85 | 88.7450 | 0.00% | 86.7450 | 88.7450 |
| 적격심사제-추정가격이 10억원 이상인 기술용역의 평가기준 | 75 | 81.9950 | 0.00% | 81.9950 | 81.9950 |
| 적격심사제-추정가격이 10억원 미만 5억원 이상인 기술용역 평가기준 | 46 | 87.4950 | 0.00% | 85.4950 | 87.4950 |
| 적격심사제-추정가격이 10억원 미만 5억원 이상인 P.Q 대상 기술용역의 평가기준(사후PQ) | 44 | 85.4950 | 0.00% | 85.4950 | 85.4950 |
| 적격심사제-추정가격이 고시금액미만(건축사법에 따른 설계는 1억원미만, 소방시설공사업법에 따른 설계·감리는 2천만원미만)인 용역 | 37 | 87.7450 | 0.00% | 87.7450 | 89.7450 |
| 적격심사제-추정가격이 5억원 미만 2억원 이상인 P.Q비대상 기술용역의 평가기준-지역업체참여도 미적용 | 34 | 86.7450 | 0.00% | 86.7450 | 86.7450 |
| 적격심사제-추정가격이 5억원 미만인 P.Q 대상 기술용역의 평가기준-지역업체참여도 미적용 | 33 | 86.7450 | 0.00% | 86.7450 | 86.7450 |
| 적격심사제-추정가격이 10억원 이상인 건설사업관리 기술용역의 평가기준(기술인평가포함) | 28 | 79.9950 | 0.00% | 79.9950 | 79.9950 |
| 적격심사제-추정가격이 10억원 미만 5억원 이상인 P.Q 비대상 기술용역의 평가기준 | 16 | 85.4950 | 0.00% | 85.4950 | 87.4950 |
| 적격심사제-추정가격이 5억원 미만 고시금액 이상인 P.Q비대상 기술용역 평기기준 | 16 | 88.7450 | 0.00% | 88.7450 | 88.7450 |
| 적격심사제-추정가격이 5억원 미만인 P.Q 대상 기술용역의 평가기준(사후PQ)-지역업체참여도 미적용 | 15 | 86.7450 | 0.00% | 86.7450 | 86.7450 |
| 적격심사제-추정가격이 5억원미만 고시금액이상(건축사법에 설계는 5억원 미만 1억원이상, 소방시설공사업법 설계감리는 5억원 미만 2천만원이상)인 용역 | 14 | 86.7450 | 0.00% | 86.7450 | 86.7450 |
| 적격심사제-추정가격이 10억원 이상인 P.Q비대상 기술용역의 평가기준 | 12 | 81.9950 | 0.00% | 79.9950 | 81.9950 |
| 적격심사제-추정가격이 5억원 미만 고시금액 이상인 기술용역 평가기준(사후PQ) | 12 | 88.7450 | 0.00% | 88.7450 | 88.7450 |
| 적격심사제-추정가격이 10억원 이상인 P.Q대상 기술용역의 평가기준-지역업체참여도 미적용 | 11 | 79.9950 | 0.00% | 79.9950 | 79.9950 |
| 적격심사제-건축사법에 따른 설계용역 5억원 미만 1억원 이상인 P.Q대상 기술용역 평가기준 | 10 | 88.7450 | 0.00% | 88.7450 | 88.7450 |
| 적격심사제-추정가격이 10억원 미만 5억원 이상인 기술용역 평가기준(사후PQ) | 10 | 87.4950 | 0.00% | 85.4950 | 87.4950 |
| 적격심사제-추정가격이 10억원 미만 5억원 이상인  P.Q비대상 기술용역 평가기준 | 9 | 87.4950 | 0.00% | 87.4950 | 87.4950 |
| 적격심사제-추정가격이 10억원미만 5억원이상인 용역 | 9 | 85.4950 | 0.00% | 85.4950 | 85.4950 |
| 적격심사제-추정가격이 10억원 이상인 용역 | 8 | 79.9950 | 0.00% | 79.9950 | 79.9950 |
| 적격심사제-추정가격이 고시금액(안전점검/정밀안전진단은 1억원, 설계/감리는 2천만원) 미만인 용역 | 7 | 87.7450 | 0.00% | 87.7450 | 87.7450 |
| 적격심사제-추정가격이 10억원 이상인 설계 기술용역의 평가기준(기술인평가포함) | 6 | 79.9950 | 0.00% | 79.9950 | 79.9950 |
| 적격심사제-추정가격이 20억원 이상인 시공단계 건설사업관리 기술용역의 평가기준(기술인평가포함) | 6 | 81.9950 | 0.00% | 81.9950 | 81.9950 |
| 적격심사제-건축사법 설계용역 5억원미만 1억원 이상인 기술용역 평가기준(사후PQ)-지역업체포함 | 5 | 88.7450 | 0.00% | 88.7450 | 89.7450 |
| 적격심사제-추정가격이 15억원 이상 40억미만인 설계(실시설계) 기술용역의 평가기준(기술인평가포함) | 5 | 81.9950 | 0.00% | 81.9950 | 81.9950 |
| 적격심사제-건축사법 설계용역 5억원미만 1억원 이상인 기술용역 평가기준(사후PQ) | 4 | 88.7450 | 0.00% | 88.7450 | 88.7450 |
| 적격심사제-추정가격이 10억원 미만 5억원 이상인 P.Q 대상 기술용역의 평가기준-지역업체참여도 미적용 | 4 | 85.4950 | 0.00% | 85.4950 | 85.4950 |
| 적격심사제-추정가격이 20억원 이상인 설계 및 시공단계 건설사업관리 기술용역의 평가기준(TP심사포함) | 4 | 81.9950 | 0.00% | 81.9950 | 81.9950 |
| 적격심사제-추정가격이 10억원 미만 5억원 이상인 용역 | 2 | 85.4950 | 0.00% | 85.4950 | 85.4950 |
| 적격심사제-추정가격이 10억원 이상인 설계 기술용역의 평가기준(TP심사포함) | 2 | 79.9950 | 0.00% | 79.9950 | 79.9950 |
| 적격심사제-추정가격이 5억원 미만 고시금액(안전점검/정밀안전진단은 1억원, 설계/감리는 2천만원) 이상인 용역 | 2 | 86.7450 | 0.00% | 86.7450 | 86.7450 |
| 적격심사제-건축사법에 따른 설계용역 5억원 미만 1억원 이상인 P.Q대상 기술용역 평가기준-지역업체포함 | 1 | 86.7450 | 0.00% | 86.7450 | 86.7450 |
| 적격심사제-추정가격이 10억원 이상 30억 미만 설계(기본계획,기본설계) 기술용역 평가기준(기술인평가포함) | 1 | 81.9950 | 0.00% | 81.9950 | 81.9950 |
| 적격심사제-추정가격이 10억원 이상인 건설사업관리 기술용역의 평가기준(TP심사포함) | 1 | 79.9950 | 0.00% | 79.9950 | 79.9950 |
| 적격심사제-추정가격이 20억원 이상인 시공단계 건설사업관리 기술용역의 평가기준(기술인평가포함)-지역업체포함 | 1 | 81.9950 | 0.00% | 81.9950 | 81.9950 |
| **합계** | **3,763** |  | **0.00%** | **1.0000** | **100.0000** |

### 4.4 기술용역 확장 판정

하한율만 놓고 보면 `sucsfbidLwltRate`를 공고에서 읽는 것은 가능합니다. 그러나 다음 세 가지 때문에 일반용역의 14종처럼 하나의 고정 레지스트리로 즉시 확정할 수 없습니다.

1. 식별 문자열이 44개로 분절되어 있고 PQ, 사후PQ, 지역업체 참여도, 기술인평가, TP심사가 혼재합니다.
2. 같은 계열에서도 하한율이 여러 값으로 나타나며, 특히 관리규정 외 수기심사는 3.0000부터 100.0000까지입니다.
3. 하한율 외 배점·통과점수·세부 평가식은 공고 JSON에 구조화되어 있지 않습니다.

## 5. `bid_results` 연결 실측

### 5.1 테이블과 조인 키

`SHOW TABLES`에서 낙찰 결과 테이블은 `bid_results`로 확인했습니다. 두 테이블의 `DESC` 결과에서 다음 공통 필드가 확인됩니다.

| 필드 | `bid_announcements` | `bid_results` | 용도 |
| --- | --- | --- | --- |
| `bid_ntce_no` | `varchar(50)`, NOT NULL, MUL | `varchar(50)`, NOT NULL, MUL | 공고번호 |
| `bid_ntce_ord` | `varchar(10)`, NOT NULL | `varchar(10)`, NOT NULL | 공고 차수 |
| `category` | `varchar(10)`, NOT NULL, MUL | `varchar(10)`, NOT NULL, MUL | 업무 구분 |
| `sucsf_bid_amt` | 없음 | `bigint`, NULL, MUL | 낙찰금액 |
| `sucsf_bid_rate` | 없음 | `decimal(10,4)`, NULL, MUL | 낙찰률 |

실제 연결은 다음 세 조건을 모두 사용합니다.

```sql
r.bid_ntce_no = a.bid_ntce_no
AND r.bid_ntce_ord = a.bid_ntce_ord
AND r.category = a.category
```

애플리케이션의 차수 보정까지 고려하면 `bid_ntce_ord`의 앞쪽 0을 제거한 값도 비교하지만, 결과는 위 조사 구간에서 동일했습니다.

### 5.2 연결률의 의미

| 모집단 | 공고 | 정확한 복합키 조인 결과 | 연결률 |
| --- | ---: | ---: | ---: |
| 일반용역 협상 문자열 전체 | 19,406 | 4,926 | 25.38% |
| 기술용역 적격심사 | 3,763 | 1,574 | 41.83% |

연결되지 않은 공고가 다수이므로 낙찰 결과의 부재를 낙찰 실패로 해석하면 안 됩니다. 이 보고서에서 확정한 모집단과 비율·하한율은 공고 테이블의 원천 필드 기준입니다.

## 6. 지원 범위 확장을 위한 확정 가능성 표

### 6.1 협상에의한계약

| 기능·판정 항목 | 확정 상태 | 근거 및 제한 |
| --- | --- | --- |
| 협상 공고 판별 | 확정 가능 | `sucsfbidMthdNm` 문자열에 `협상` 포함 |
| 일반용역과 기술용역 분리 | 확정 가능 | `srvceDivNm` 값 |
| 기술·가격 비율 표시 | 확정 가능 | 핵심 19,405건에서 `techAbltEvlRt`, `bidPrceEvlRt` 전량 존재 |
| 비율별 사용자 안내 | 확정 가능 | 90/10, 80/20 등 16개 조합 실측 |
| 가격점수 배점 한도 `B` | 확정 불가 | 비율 필드와 배점 한도를 동일시할 근거 없음 |
| 가격식 계수 `k` | 확정 불가 | 구조화 필드 없음 |
| 통과점수 `T` | 확정 불가 | 구조화 필드 없음 |
| 공고문 세부 배점·가감점 | 확정 불가 | 적용기준 필드가 빈 문자열 |
| 낙찰금액·낙찰률 연결 | 부분 확정 | `bid_results` 연결률 25.38% |

### 6.2 기술용역 적격심사

| 기능·판정 항목 | 확정 상태 | 근거 및 제한 |
| --- | --- | --- |
| 기술용역 적격심사 판별 | 확정 가능 | `srvceDivNm='기술용역'` 및 `sucsfbidMthdNm`의 `적격심사` |
| 식별 문자열과 모집단 건수 | 확정 가능 | 44개 문자열, 3,763건 |
| 공고별 낙찰하한율 | 확정 가능 | `sucsfbidLwltRate` 결측 0건 |
| 문자열별 최빈·최소·최대 | 확정 가능 | 4.3 표 실측값 |
| 단일 공통 하한율 | 확정 불가 | 문자열별·수기심사별 편차가 큼 |
| 일반용역 14종 규칙 재사용 | 확정 불가 | 기술용역 문자열 계열과 제도 구성이 다름 |
| 기술·가격 배점 `B`·계수 `k`·통과점수 `T` | 확정 불가 | 원천 JSON에 구조화 필드 없음 |
| 낙찰금액·낙찰률 연결 | 부분 확정 | `bid_results` 연결률 41.83% |

## 7. 외부 배점표 검증 결과

외부 통합설계서의 기술용역 표 `Nmax 70/50/30/10`, `B 30/50/70/90`, `k 1/2/4/20`, `T 92/95/95/95`는 이번 DB 실측만으로 재현되지 않습니다.

| 검증 대상 | 실측 결과 | 판정 |
| --- | --- | --- |
| 기술·가격 비율 | 90/10, 80/20이 최다이며 70/30·50/50·30/70·10/90도 일부 존재 | 일부 조합의 존재만 확인 |
| `Nmax`·가격배점 `B` | 원천 JSON에 해당 구조화 필드 없음 | 검증 불가 |
| 계수 `k` | 원천 JSON에 해당 구조화 필드 없음 | 검증 불가 |
| 통과점수 `T` | 원천 JSON에 해당 구조화 필드 없음 | 검증 불가 |
| 배점표 전체의 계열별 적용 | 44개 문자열과 PQ·사후PQ·기술인평가 등이 혼재 | 검증 불가 |

따라서 위 표의 숫자를 기술용역의 기본값으로 코드나 보고서에 확정해서는 안 됩니다. 지원 화면에서는 실측으로 읽을 수 있는 비율·하한율을 표시하고, 산식에 필요한 값을 공고문 확인 또는 사용자 입력으로 분리하는 것이 현재 증거에 맞습니다.

## 8. 재현용 질의와 결과 원문

아래 질의는 모두 `scripts/db_readonly_query.py`를 통해 실행했습니다. 결과는 표 변환 전 원문을 유지했습니다.

### 8.1 테이블 목록

```text
질의: SHOW TABLES

Tables_in_procurement
--------------------
account_emailaddress
account_emailconfirmation
accounts_customuser
accounts_customuser_groups
accounts_customuser_user_permissions
alembic_version
auth_group
auth_group_permissions
auth_permission
automation_requests
automation_subscriptions
bid_announcements
bid_dataset_summaries
bid_evaluation_evidence
bid_evaluation_profiles
bid_evaluation_snapshots
bid_ranking_snapshots
bid_results
chat_session_states
django_admin_log
django_content_type
django_migrations
django_session
django_site
institution_win_rate_stats
knowledge_base_status
pipeline_executions
prediction_results
retrain_logs
servc_inst_verify
socialaccount_socialaccount
socialaccount_socialapp
socialaccount_socialapp_sites
socialaccount_socialtoken
```

### 8.2 공고·낙찰 결과 테이블 구조

```text
질의: DESC bid_announcements

Field          | Type          | Null | Key | Default | Extra
id             | bigint        | NO   | PRI | None    | auto_increment
bid_ntce_nm    | varchar(500) | YES  |     | None    |
bid_ntce_no    | varchar(50)  | NO   | MUL | None    |
bid_ntce_ord   | varchar(10)  | NO   |     | None    |
ntce_instt_nm  | varchar(200) | YES  |     | None    |
dminstt_nm     | varchar(200) | YES  | MUL | None    |
presmpt_prce   | bigint       | YES  |     | None    |
bid_ntce_dt    | datetime(6)  | YES  | MUL | None    |
bid_clse_dt    | datetime(6)  | YES  |     | None    |
openg_dt       | datetime(6)  | YES  |     | None    |
ntce_kind_nm   | varchar(100) | YES  |     | None    |
bid_methd_nm   | varchar(100) | YES  |     | None    |
cntrct_mthd_nm | varchar(100) | YES  |     | None    |
category       | varchar(10)  | NO   | MUL | None    |
raw_data       | longtext     | YES  |     | None    |
collected_at   | datetime(6)  | NO   | MUL | None    |
base_amount    | bigint       | YES  |     | None    |
```

```text
질의: DESC bid_results

Field          | Type          | Null | Key | Default | Extra
id             | bigint        | NO   | PRI | None    | auto_increment
bid_ntce_nm    | varchar(500) | YES  |     | None    |
bid_ntce_no    | varchar(50)  | NO   | MUL | None    |
bid_ntce_ord   | varchar(10)  | NO   |     | None    |
bidwinnr_nm    | varchar(200) | YES  | MUL | None    |
sucsf_bid_amt  | bigint       | YES  | MUL | None    |
sucsf_bid_rate | decimal(10,4) | YES  | MUL | None    |
rl_openg_dt    | datetime(6)  | YES  | MUL | None    |
dminstt_nm     | varchar(200) | YES  | MUL | None    |
category       | varchar(10)  | NO   | MUL | None    |
raw_data       | longtext     | YES  |     | None    |
collected_at   | datetime(6)  | NO   | MUL | None    |
```

### 8.3 협상 문자열별 건수

```sql
SELECT JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidMthdNm')) AS sucsfbid_mthd_nm,
       COUNT(*) AS announcement_count
FROM bid_announcements
WHERE category = 'Servc'
  AND bid_ntce_dt >= '2026-05-26'
  AND bid_ntce_dt < '2026-09-09'
  AND JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.srvceDivNm')) = '일반용역'
  AND JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidMthdNm')) LIKE '%협상%'
GROUP BY JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidMthdNm'))
ORDER BY announcement_count DESC, sucsfbid_mthd_nm
```

```json
[
  {"sucsfbid_mthd_nm":"협상에의한계약-협상에 의한 낙찰자 결정","announcement_count":"16050"},
  {"sucsfbid_mthd_nm":"협상에의한계약-협상에 의한 낙찰자 결정(SW사업)","announcement_count":"3355"},
  {"sucsfbid_mthd_nm":"다수공급자계약-적격성평가 및 가격협상(다수공급자)","announcement_count":"1"}
]
```

### 8.4 협상 비율 필드별 존재 건수

```sql
SELECT JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidMthdNm')) AS sucsfbid_mthd_nm,
       COUNT(*) AS announcement_count,
       SUM(CASE WHEN NULLIF(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.techAbltEvlRt')), '') IS NOT NULL THEN 1 ELSE 0 END) AS tech_score_present,
       SUM(CASE WHEN NULLIF(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.bidPrceEvlRt')), '') IS NOT NULL THEN 1 ELSE 0 END) AS price_score_present
FROM bid_announcements
WHERE category = 'Servc'
  AND bid_ntce_dt >= '2026-05-26'
  AND bid_ntce_dt < '2026-09-09'
  AND JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.srvceDivNm')) = '일반용역'
  AND JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidMthdNm')) LIKE '%협상%'
GROUP BY JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidMthdNm'))
ORDER BY announcement_count DESC
```

```json
[
  {"sucsfbid_mthd_nm":"협상에의한계약-협상에 의한 낙찰자 결정","announcement_count":"16050","tech_score_present":"16050","price_score_present":"16050"},
  {"sucsfbid_mthd_nm":"협상에의한계약-협상에 의한 낙찰자 결정(SW사업)","announcement_count":"3355","tech_score_present":"3355","price_score_present":"3355"},
  {"sucsfbid_mthd_nm":"다수공급자계약-적격성평가 및 가격협상(다수공급자)","announcement_count":"1","tech_score_present":"0","price_score_present":"0"}
]
```

### 8.5 협상 기술·가격 비율 조합

```sql
SELECT JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.techAbltEvlRt')) AS tech_score_ratio,
       JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.bidPrceEvlRt')) AS price_score_ratio,
       COUNT(*) AS announcement_count
FROM bid_announcements
WHERE category = 'Servc'
  AND bid_ntce_dt >= '2026-05-26'
  AND bid_ntce_dt < '2026-09-09'
  AND JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.srvceDivNm')) = '일반용역'
  AND JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidMthdNm')) LIKE '%협상%'
GROUP BY JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.techAbltEvlRt')),
         JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.bidPrceEvlRt'))
ORDER BY announcement_count DESC, tech_score_ratio, price_score_ratio
```

```json
[
  {"tech_score_ratio":"90","price_score_ratio":"10","announcement_count":"10614"},
  {"tech_score_ratio":"80","price_score_ratio":"20","announcement_count":"7975"},
  {"tech_score_ratio":"70","price_score_ratio":"30","announcement_count":"534"},
  {"tech_score_ratio":"100","price_score_ratio":"0","announcement_count":"130"},
  {"tech_score_ratio":"85","price_score_ratio":"15","announcement_count":"59"},
  {"tech_score_ratio":"50","price_score_ratio":"50","announcement_count":"29"},
  {"tech_score_ratio":"10","price_score_ratio":"90","announcement_count":"17"},
  {"tech_score_ratio":"60","price_score_ratio":"40","announcement_count":"14"},
  {"tech_score_ratio":"99","price_score_ratio":"1","announcement_count":"12"},
  {"tech_score_ratio":"95","price_score_ratio":"5","announcement_count":"7"},
  {"tech_score_ratio":"20","price_score_ratio":"80","announcement_count":"6"},
  {"tech_score_ratio":"30","price_score_ratio":"70","announcement_count":"3"},
  {"tech_score_ratio":"40","price_score_ratio":"60","announcement_count":"2"},
  {"tech_score_ratio":"75","price_score_ratio":"25","announcement_count":"2"},
  {"tech_score_ratio":"","price_score_ratio":"","announcement_count":"1"},
  {"tech_score_ratio":"78","price_score_ratio":"22","announcement_count":"1"}
]
```

### 8.6 가격점수 관련 키와 적용기준 값

점수 산식 입력의 부재는 다음 키 검색으로 확인했습니다.

```sql
SELECT jt.key_name, COUNT(*) AS row_count
FROM bid_announcements a
JOIN JSON_TABLE(JSON_KEYS(a.raw_data), '$[*]' COLUMNS (key_name VARCHAR(128) PATH '$')) jt
WHERE a.category = 'Servc'
  AND a.bid_ntce_dt >= '2026-05-26'
  AND a.bid_ntce_dt < '2026-09-09'
  AND JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.srvceDivNm')) = '일반용역'
  AND JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.sucsfbidMthdNm')) LIKE '%협상%'
  AND LOWER(jt.key_name) REGEXP 'score|point|threshold|factor|coef|formula|calc|pricepoint|prcescore'
GROUP BY jt.key_name
ORDER BY jt.key_name
```

```text
key_name | row_count
---------+----------
(결과 없음)
```

```sql
SELECT JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidMthdAppStd')) AS method_standard,
       COUNT(*) AS announcement_count
FROM bid_announcements
WHERE category = 'Servc'
  AND bid_ntce_dt >= '2026-05-26'
  AND bid_ntce_dt < '2026-09-09'
  AND JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.srvceDivNm')) = '일반용역'
  AND JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidMthdNm')) LIKE '%협상%'
GROUP BY JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidMthdAppStd'))
```

```json
[{"method_standard":"","announcement_count":"19406"}]
```

### 8.7 기술용역 문자열별 건수

```sql
SELECT JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidMthdNm')) AS sucsfbid_mthd_nm,
       COUNT(*) AS announcement_count
FROM bid_announcements
WHERE category = 'Servc'
  AND bid_ntce_dt >= '2026-05-26'
  AND bid_ntce_dt < '2026-09-09'
  AND JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.srvceDivNm')) = '기술용역'
  AND JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidMthdNm')) LIKE '%적격심사%'
GROUP BY JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidMthdNm'))
ORDER BY announcement_count DESC, sucsfbid_mthd_nm
```

```json
[
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 10억원 이상인 P.Q대상 기술용역의 평가기준","announcement_count":"963"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 2억원 미만 1억원 이상인 P.Q비대상 기술용역의 평가기준","announcement_count":"602"},
  {"sucsfbid_mthd_nm":"적격심사제-관리규정외 수기심사(총점입력)","announcement_count":"349"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 5억원 미만인 P.Q 대상 기술용역의 평가기준","announcement_count":"290"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 고시금액 미만(건축사법에 따른 설계는 1억원 미만)인 기술용역 평가기준","announcement_count":"287"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 10억원 미만 5억원 이상인 P.Q 대상 기술용역의 평가기준","announcement_count":"246"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 5억원 미만인 P.Q 대상 기술용역의 평가기준(사후PQ)","announcement_count":"211"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 5억원 미만 2억원 이상인 P.Q비대상 기술용역의 평가기준","announcement_count":"122"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 1억원 미만인 P.Q비대상 기술용역의 평가기준","announcement_count":"118"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 5억원 미만 고시금액 이상인 P.Q대상 기술용역 평가기준","announcement_count":"85"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 10억원 이상인 기술용역의 평가기준","announcement_count":"75"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 10억원 미만 5억원 이상인 기술용역 평가기준","announcement_count":"46"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 10억원 미만 5억원 이상인 P.Q 대상 기술용역의 평가기준(사후PQ)","announcement_count":"44"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 고시금액미만(건축사법에 따른 설계는 1억원미만, 소방시설공사업법에 따른 설계·감리는 2천만원미만)인 용역","announcement_count":"37"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 5억원 미만 2억원 이상인 P.Q비대상 기술용역의 평가기준-지역업체참여도 미적용","announcement_count":"34"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 5억원 미만인 P.Q 대상 기술용역의 평가기준-지역업체참여도 미적용","announcement_count":"33"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 10억원 이상인 건설사업관리 기술용역의 평가기준(기술인평가포함)","announcement_count":"28"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 10억원 미만 5억원 이상인 P.Q 비대상 기술용역의 평가기준","announcement_count":"16"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 5억원 미만 고시금액 이상인 P.Q비대상 기술용역 평기기준","announcement_count":"16"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 5억원 미만인 P.Q 대상 기술용역의 평가기준(사후PQ)-지역업체참여도 미적용","announcement_count":"15"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 5억원미만 고시금액이상(건축사법에 설계는 5억원 미만 1억원이상, 소방시설공사업법 설계감리는 5억원 미만 2천만원이상)인 용역","announcement_count":"14"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 10억원 이상인 P.Q비대상 기술용역의 평가기준","announcement_count":"12"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 5억원 미만 고시금액 이상인 기술용역 평가기준(사후PQ)","announcement_count":"12"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 10억원 이상인 P.Q대상 기술용역의 평가기준-지역업체참여도 미적용","announcement_count":"11"},
  {"sucsfbid_mthd_nm":"적격심사제-건축사법에 따른 설계용역 5억원 미만 1억원 이상인 P.Q대상 기술용역 평가기준","announcement_count":"10"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 10억원 미만 5억원 이상인 기술용역 평가기준(사후PQ)","announcement_count":"10"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 10억원 미만 5억원 이상인  P.Q비대상 기술용역 평가기준","announcement_count":"9"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 10억원미만 5억원이상인 용역","announcement_count":"9"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 10억원 이상인 용역","announcement_count":"8"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 고시금액(안전점검/정밀안전진단은 1억원, 설계/감리는 2천만원) 미만인 용역","announcement_count":"7"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 10억원 이상인 설계 기술용역의 평가기준(기술인평가포함)","announcement_count":"6"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 20억원 이상인 시공단계 건설사업관리 기술용역의 평가기준(기술인평가포함)","announcement_count":"6"},
  {"sucsfbid_mthd_nm":"적격심사제-건축사법 설계용역 5억원미만 1억원 이상인 기술용역 평가기준(사후PQ)-지역업체포함","announcement_count":"5"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 15억원 이상 40억미만인 설계(실시설계) 기술용역의 평가기준(기술인평가포함)","announcement_count":"5"},
  {"sucsfbid_mthd_nm":"적격심사제-건축사법 설계용역 5억원미만 1억원 이상인 기술용역 평가기준(사후PQ)","announcement_count":"4"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 10억원 미만 5억원 이상인 P.Q 대상 기술용역의 평가기준-지역업체참여도 미적용","announcement_count":"4"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 20억원 이상인 설계 및 시공단계 건설사업관리 기술용역의 평가기준(TP심사포함)","announcement_count":"4"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 10억원 미만 5억원 이상인 용역","announcement_count":"2"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 10억원 이상인 설계 기술용역의 평가기준(TP심사포함)","announcement_count":"2"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 5억원 미만 고시금액(안전점검/정밀안전진단은 1억원, 설계/감리는 2천만원) 이상인 용역","announcement_count":"2"},
  {"sucsfbid_mthd_nm":"적격심사제-건축사법에 따른 설계용역 5억원 미만 1억원 이상인 P.Q대상 기술용역 평가기준-지역업체포함","announcement_count":"1"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 10억원 이상 30억 미만 설계(기본계획,기본설계) 기술용역 평가기준(기술인평가포함)","announcement_count":"1"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 10억원 이상인 건설사업관리 기술용역의 평가기준(TP심사포함)","announcement_count":"1"},
  {"sucsfbid_mthd_nm":"적격심사제-추정가격이 20억원 이상인 시공단계 건설사업관리 기술용역의 평가기준(기술인평가포함)-지역업체포함","announcement_count":"1"}
]
```

### 8.8 기술용역 전체 하한율 통계

```sql
SELECT COUNT(*) AS population_count,
       SUM(CASE WHEN JSON_EXTRACT(raw_data, '$.sucsfbidLwltRate') IS NULL
                     OR NULLIF(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidLwltRate')), '') IS NULL
                THEN 1 ELSE 0 END) AS missing_count,
       ROUND(100 * SUM(CASE WHEN JSON_EXTRACT(raw_data, '$.sucsfbidLwltRate') IS NULL
                                  OR NULLIF(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidLwltRate')), '') IS NULL
                             THEN 1 ELSE 0 END) / COUNT(*), 2) AS missing_pct,
       MIN(CAST(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidLwltRate')), '') AS DECIMAL(10,4))) AS min_rate,
       MAX(CAST(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidLwltRate')), '') AS DECIMAL(10,4))) AS max_rate
FROM bid_announcements
WHERE category = 'Servc'
  AND bid_ntce_dt >= '2026-05-26'
  AND bid_ntce_dt < '2026-09-09'
  AND JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.srvceDivNm')) = '기술용역'
  AND JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidMthdNm')) LIKE '%적격심사%'
```

```text
population_count | missing_count | missing_pct | min_rate | max_rate
-----------------+---------------+-------------+----------+---------
3763             | 0             | 0.00        | 1.0000   | 100.0000
```

최빈값 질의의 원문 결과는 다음과 같습니다.

```text
lwlt_rate | rate_count
----------+-----------
79.9950   | 1030
87.7450   | 870
86.7450   | 770
89.7450   | 351
85.4950   | 349
88.7450   | 126
81.9950   | 106
87.4950   | 105
82.9950   | 8
100.0000  | 8
84.9950   | 6
82.9500   | 5
88.0000   | 4
90.0000   | 4
10.0000   | 3
82.4950   | 3
1.0000    | 2
5.0000    | 2
77.9950   | 2
80.4950   | 2
87.2450   | 2
88.8750   | 2
3.0000    | 1
80.4500   | 1
89.9950   | 1
```

### 8.9 낙찰 결과 연결률

협상 모집단과 기술용역 모집단 각각에 대해 다음 형태의 단일 질의를 실행했습니다.

```sql
SELECT COUNT(*) AS announcement_count,
       COUNT(r.id) AS matched_result_count,
       ROUND(100 * COUNT(r.id) / COUNT(*), 2) AS matched_pct
FROM bid_announcements a
LEFT JOIN bid_results r
  ON r.bid_ntce_no = a.bid_ntce_no
 AND r.bid_ntce_ord = a.bid_ntce_ord
 AND r.category = a.category
WHERE ...모집단 조건...
```

```text
일반용역 협상:
announcement_count | matched_result_count | matched_pct
-------------------+----------------------+------------
19406              | 4926                 | 25.38

기술용역 적격심사:
announcement_count | matched_result_count | matched_pct
-------------------+----------------------+------------
3763               | 1574                 | 41.83
```

## 9. 최종 판정

현재 DB만으로는 협상에의한계약의 기술·가격 배점 비율과 기술용역 적격심사의 공고별 낙찰하한율을 읽어 지원 범위를 넓힐 근거가 충분합니다. 반면 가격점수 산식의 `B`, `k`, `T`와 기술용역의 공통 배점표는 실측으로 확정할 수 없으므로, 외부 설계서 숫자를 기본값으로 넣거나 44개 문자열을 하나의 규칙으로 합치면 안 됩니다.

구현은 이 조사 범위에 포함하지 않았습니다. 다음 단계에서 구현을 추진한다면 협상은 비율 표시 후 산식 입력을 별도 취급하고, 기술용역은 문자열 계열·수기심사·PQ 여부를 분리한 뒤 공고문 근거가 없는 점수 계산을 차단하는 정책이 이 보고서의 실측 범위와 일치합니다.
