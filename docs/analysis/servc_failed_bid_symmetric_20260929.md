# 유찰 공고 대칭 분모 제외 실측: 대형 매칭률 격차와 경고 영향 (2026-09-29)

> **작성일**: 2026-09-29
> **작성자**: Orca builder worker (task_1402d04f7da5)
> **기준 커밋**: `0a5428a3`
> **기준 시각**: 2026-09-29 Asia/Seoul
> **범위**: 대형(추정가격 2.3억 이상) 공고의 매칭률을 현재 주와 전년 기저에 유찰 제외를 대칭 적용해 재계산하고, 격차·경고 변화와 오프라인 동시 제외 영향을 실측
> **변경 없음**: 코드·설정·DB·스키마를 변경하지 않았습니다. 값은 읽기 전용 DB 조회와 조달청 개찰결과 목록 API 호출 결과입니다.
> **질의 방법**: DB 는 `uv run python scripts/db_readonly_query.py --sql "..."`, API 는 워커 컨테이너에서 `get_service_key()` 로 키를 읽어 호출합니다. 유찰 집합과 DB 공고 행의 교집합은 워커 컨테이너의 읽기 전용 조회로 계산했습니다. 인증키·요청 전체 URL·개인 정보(대표자명)는 기록하지 않습니다.

---

## 1. 요약 (결론)

1. **유찰을 대칭 제외해도 용역 대형 경고는 사라지지 않습니다.** 경고 판정 식은 `5주 기저 보정 비교 = 기저 5주 매칭률 - 현재 주 보정률(A2)` 이고 임계는 10.0%p 입니다. 유찰을 현재 주에서만 빼던 E2 추정(+16.8%p)과 달리, 기저에도 같은 규칙을 적용하면 Servc 08-24 격차는 11.81%p 에서 10.80%p 로, 08-17 은 12.10%p 에서 11.14%p 로 각각 약 1.0%p 만 줄어 임계를 계속 넘습니다.
2. **분자와 분모가 같은 비율로 오르기 때문입니다.** 유찰 미매칭 행은 분모에서만 빠지므로 현재 주 매칭률은 크게 오르지만(08-24 41.03% → 51.34%), 기저 5주 매칭률도 함께 오릅니다(51.18% → 59.87%). 두 값의 차이는 거의 유지됩니다.
3. **분류별 부호가 다릅니다.** 물품(Thng)은 격차가 1.2~2.3%p 줄고, 공사(Cnstwk)는 0.4~1.8%p 오히려 늘어납니다. 다만 물품·공사는 미적용 상태에서도 격차가 임계 미만이라 경고 대상이 아닙니다.
4. **올해 유찰 비율은 Servc·Thng 에서 전년보다 높습니다.** Servc 대형 유찰 비율은 올해 3주 19.78% 로 전년 7주 창 15.20% 보다 4.6%p 높고, Thng 은 28.20% 로 전년 21.86% 보다 6.3%p 높습니다. Cnstwk 은 0.87% 로 전년 2.32% 보다 낮습니다.
5. **오프라인까지 함께 제외하면 용역 격차는 더 벌어집니다.** 오프라인만 제외하면 Servc 08-24 격차가 14.45%p, 오프라인+유찰은 13.53%p 로, 미적용 11.81%p 보다 큽니다.
6. **권고**: 개찰결과 수집·저장(T1~T3)은 분모 정의 정확성과 감사·재현을 위해 권고하되, "경고 소멸"을 기대 근거로 삼으면 안 됩니다. 유찰 제외 플래그(T4)를 켜도 경고 판정은 유지되므로 경고 대응 목적의 우선순위는 낮습니다. 오프라인 플래그는 경고를 줄이려는 목적이면 역효과입니다. Servc 경고 억제(만료 2026-10-20)는 유찰·오프라인 제외로 해소되지 않으므로, 연장 여부는 분모 재정의 정책과 함께 판단해야 합니다.

---

## 2. 측정 계약과 방법

### 2.1 대상 주와 창

| 구분 | 값 |
| --- | --- |
| 기준 시각(as_of) | 2026-09-29, `min_elapsed_days=28` 이므로 최신 성숙 주는 2026-08-24 |
| 대상 개찰 주(현재) | 2026-08-10, 2026-08-17, 2026-08-24 (월요일 시작) |
| 단일 주 기저 | 각 주 −364일 중심 주: 2025-08-11, 2025-08-18, 2025-08-25 |
| 5주 기저 창 | 중심 주 앞뒤 2주 합산. 08-10→(07-28, 08-04, 08-11, 08-18, 08-25), 08-17→(08-04, 08-11, 08-18, 08-25, 09-01), 08-24→(08-11, 08-18, 08-25, 09-01, 09-08) |
| 대형 기준 | `src/app/services/result_coverage.py` `LARGE_PRICE_THRESHOLD = 230_000_000` |
| 기타 고정 | `exclude_later_cancelled=False`, `exclude_offline_bids=False` (수동 계산), 취소공고 행 제외 |

### 2.2 유찰 판정

- 조달청 `ScsbidInfoService/getOpengResultListInfo<분류>` (분류: Servc·Thng·Cnstwk) 를 `inqryDiv=3`(개찰일시 기준), `numOfRows=999`, `pageNo` 페이징으로 호출했습니다.
- 응답 항목의 `progrsDivCdNm` 이 `유찰` 이면 유찰입니다. 날짜 창은 15일 단위로 쪼개고 호출 사이에 0.25초를 쉬었습니다.
- 판정 단위는 공고번호입니다. DB 에서 뽑은 대형 공고의 (공고번호, 분류) 가 해당 개찰 주의 유찰 공고번호 집합에 있으면 그 공고의 미매칭 행을 유찰로 봤습니다. 유찰 행은 매칭되지 않으므로 분모에서만 빠지고 분자는 변하지 않습니다.

### 2.3 API 호출 원장

| 계열 | 용도 | 호출 수 |
| --- | --- | ---: |
| A | 응답 필드·`inqryDiv=3`·`progrsDivCdNm` 형식 확인(탐침) | 1 |
| B | 유찰 집합 수집(현재 3주 2창 + 전년 5주 창 4창, 3분류 18창) | 73 |
| C | 기준 주별 원시 유찰 집계 재확보(전년 중심 주별 비율) | 73 |
| 합계 | | **147** |

- 계약 상한 400회 이내입니다. 유찰 집합은 창당 약 4천~5천 건을 받아 페이지당 999건으로 페이징했습니다.
- 분류별 창당 유찰 건수(결과 아님, 참고): Servc 1,088~1,314, Cnstwk 45~87, Thng 1,228~1,883.

---

## 3. 대칭 유찰 제외 매칭률 (3주 x 3분류 대형)

표기: `매칭/분모 (%)`. 보정률은 기저 5주 방식 구성비로 현재 주 방식별 매칭률을 가중한 값(A2)이고, 경고 격차는 `5주 기저 − 보정률` 입니다. 모든 값은 8.3절 컨테이너 파이프라인으로 재계산되며, 미적용 열과 오프라인 제외 열은 `compute_result_match_rates` 출력과 일치합니다.

### 3.1 용역(Servc) 대형

| 개찰 주 | 유찰 제외 | 현재 주 | 단일 주 기저(2025) | 5주 기저 | 보정률 | 경고 격차 |
| --- | :---: | --- | --- | --- | ---: | ---: |
| 2026-08-10 | 미적용 | 46.88 (248/529) | 53.41 (235/440) | 52.42 (1255/2394) | 45.89 | +6.53 |
| 2026-08-10 | 적용 | 58.22 (248/426) | 62.17 (235/378) | 62.28 (1255/2015) | 56.36 | +5.92 |
| 2026-08-17 | 미적용 | 39.02 (183/469) | 52.40 (284/542) | 51.83 (1233/2379) | 39.73 | +12.10 |
| 2026-08-17 | 적용 | 48.67 (183/376) | 62.14 (284/457) | 61.04 (1233/2020) | 49.90 | +11.14 |
| 2026-08-24 | 미적용 | 41.03 (192/468) | 49.49 (194/392) | 51.18 (1189/2323) | 39.37 | +11.81 |
| 2026-08-24 | 적용 | 51.34 (192/374) | 58.61 (194/331) | 59.87 (1189/1986) | 49.07 | +10.80 |

- 제외된 유찰 미매칭 행: 08-10 103, 08-17 93, 08-24 94. 5주 창 제외 행: 08-24 기준 337(=2025-08-11 62 + 08-18 85 + 08-25 61 + 09-01 72 + 09-08 57).
- 재현: 현재·기저 분모/매칭은 8.1절 DB 질의, 유찰 교집합과 보정률은 8.3절 파이프라인.

### 3.2 물품(Thng) 대형

| 개찰 주 | 유찰 제외 | 현재 주 | 단일 주 기저(2025) | 5주 기저 | 보정률 | 경고 격차 |
| --- | :---: | --- | --- | --- | ---: | ---: |
| 2026-08-10 | 미적용 | 49.80 (247/496) | 60.90 (190/312) | 62.40 (1271/2037) | 55.86 | +6.54 |
| 2026-08-10 | 적용 | 69.77 (247/354) | 78.51 (190/242) | 79.54 (1271/1598) | 74.25 | +5.29 |
| 2026-08-17 | 미적용 | 53.09 (258/486) | 65.52 (306/467) | 62.36 (1221/1958) | 55.14 | +7.22 |
| 2026-08-17 | 적용 | 74.78 (258/345) | 82.48 (306/371) | 80.28 (1221/1521) | 75.38 | +4.90 |
| 2026-08-24 | 미적용 | 53.96 (245/454) | 65.04 (266/409) | 63.23 (1216/1923) | 55.51 | +7.72 |
| 2026-08-24 | 적용 | 73.80 (245/332) | 80.85 (266/329) | 80.53 (1216/1510) | 74.01 | +6.52 |

### 3.3 공사(Cnstwk) 대형

| 개찰 주 | 유찰 제외 | 현재 주 | 단일 주 기저(2025) | 5주 기저 | 보정률 | 경고 격차 |
| --- | :---: | --- | --- | --- | ---: | ---: |
| 2026-08-10 | 미적용 | 73.81 (341/462) | 74.71 (390/522) | 73.48 (2048/2787) | 74.54 | -1.06 |
| 2026-08-10 | 적용 | 73.97 (341/461) | 76.32 (390/511) | 75.52 (2048/2712) | 74.79 | +0.72 |
| 2026-08-17 | 미적용 | 72.13 (365/506) | 71.97 (416/578) | 73.72 (2014/2732) | 72.21 | +1.51 |
| 2026-08-17 | 적용 | 72.85 (365/501) | 73.63 (416/565) | 75.66 (2014/2662) | 73.05 | +2.61 |
| 2026-08-24 | 미적용 | 72.48 (295/407) | 74.16 (373/503) | 75.13 (2060/2742) | 71.77 | +3.35 |
| 2026-08-24 | 적용 | 73.57 (295/401) | 76.59 (373/487) | 76.69 (2060/2686) | 72.97 | +3.73 |

### 3.4 격차 변화 요약

| 분류 | 개찰 주 | 격차 미적용 | 격차 적용 | 변화 |
| --- | --- | ---: | ---: | ---: |
| Servc | 2026-08-10 | +6.53 | +5.92 | -0.61 |
| Servc | 2026-08-17 | +12.10 | +11.14 | -0.96 |
| Servc | 2026-08-24 | +11.81 | +10.80 | -1.01 |
| Thng | 2026-08-10 | +6.54 | +5.29 | -1.25 |
| Thng | 2026-08-17 | +7.22 | +4.90 | -2.33 |
| Thng | 2026-08-24 | +7.72 | +6.52 | -1.21 |
| Cnstwk | 2026-08-10 | -1.06 | +0.72 | +1.78 |
| Cnstwk | 2026-08-17 | +1.51 | +2.61 | +1.10 |
| Cnstwk | 2026-08-24 | +3.35 | +3.73 | +0.37 |

- 임계 10.0%p 를 넘는 조합은 Servc 08-17·08-24 뿐이고, 유찰 제외 후에도 넘습니다.
- 차수 단위 판정(`progrsDivCdNm=유찰` 인 (공고번호, 차수)만 제외)으로 바꾼 민감도는 Servc 08-24 기준 격차 +10.63%p 로, 공고번호 단위(+10.80%p)와 방향이 같습니다. 차이가 0.2%p 미만이라 결론은 바뀌지 않습니다.

---

## 4. 전년 대비 유찰 비율 비교와 판정

대형 행 기준이며, 유찰은 그 주에 개찰된 대형 공고 행 중 유찰 공고번호에 속한 미매칭 행 수입니다.

| 분류 | 올해 3주 합 (유찰/행, %) | 올해 주별 (%) | 전년 중심 주별 (%) | 전년 7주 창 (유찰/행, %) | 판정 |
| --- | --- | --- | --- | --- | --- |
| Servc | 19.78 (290/1466) | 19.47 / 19.83 / 20.09 | 14.09 / 15.68 / 15.56 | 15.20 (508/3343) | 올해 4.6%p 높음 |
| Cnstwk | 0.87 (12/1375) | 0.22 / 0.99 / 1.47 | 2.11 / 2.25 / 3.18 | 2.32 (91/3926) | 올해 1.5%p 낮음 |
| Thng | 28.20 (405/1436) | 28.63 / 29.01 / 26.87 | 22.44 / 20.56 / 19.56 | 21.86 (606/2772) | 올해 6.3%p 높음 |

- 전년 7주 창은 2025-07-28~2025-09-08 로, 세 기저 창의 합집합입니다.
- **판정**: 올해 Servc·Thng 은 유찰이 전년보다 늘어 매칭률 수준을 끌어내린 것은 맞습니다. 그러나 유찰을 대칭 제외하면 전년 기저도 같은 폭으로 올라, "올해 유찰 증가"가 전년 대비 격차(경고 판정)를 설명하지는 못합니다. Servc 08-24 기준 현재 주와 5주 기저의 차이는 미적용 10.15%p, 적용 8.53%p(원 매칭률 기준)로 오히려 좁혀집니다.
- 재현: 8.1절 DB 질의(분모·매칭)와 8.2절 유찰 창 호출로 행별 유찰 수를 재집계합니다.

---

## 5. 오프라인·유찰 동시 제외

규칙: 오프라인은 입찰방식(`bid_methd_nm`)이 `전자` 로 시작하지 않는 직찰·우편 계열입니다(값 없음·공백은 온라인 취급). 두 제외는 각각 독립이며 함께 켤 수 있습니다.

### 5.1 현재 주 매칭률 비교

| 분류 | 개찰 주 | 미적용 | 오프라인만 | 유찰만 | 오프라인+유찰 |
| --- | --- | --- | --- | --- | --- |
| Servc | 2026-08-10 | 46.88 (248/529) | 53.04 (227/428) | 58.22 (248/426) | 67.96 (227/334) |
| Servc | 2026-08-17 | 39.02 (183/469) | 46.67 (168/360) | 48.67 (183/376) | 61.31 (168/274) |
| Servc | 2026-08-24 | 41.03 (192/468) | 47.31 (176/372) | 51.34 (192/374) | 60.90 (176/289) |
| Cnstwk | 2026-08-10 | 73.81 (341/462) | 75.44 (341/452) | 73.97 (341/461) | 75.61 (341/451) |
| Cnstwk | 2026-08-17 | 72.13 (365/506) | 73.00 (365/500) | 72.85 (365/501) | 73.74 (365/495) |
| Cnstwk | 2026-08-24 | 72.48 (295/407) | 72.66 (295/406) | 73.57 (295/401) | 73.75 (295/400) |
| Thng | 2026-08-10 | 49.80 (247/496) | 52.38 (242/462) | 69.77 (247/354) | 74.69 (242/324) |
| Thng | 2026-08-17 | 53.09 (258/486) | 54.64 (253/463) | 74.78 (258/345) | 77.61 (253/326) |
| Thng | 2026-08-24 | 53.96 (245/454) | 56.58 (245/433) | 73.80 (245/332) | 77.78 (245/315) |

### 5.2 경고 격차 비교 (5주 기저 − 보정률, 임계 10.0%p)

| 분류 | 변형 | 2026-08-24 격차 | 2026-08-17 격차 | 경고 |
| --- | --- | ---: | ---: | :---: |
| Servc | 미적용 | +11.81 | +12.10 | 경고 |
| Servc | 유찰만 | +10.80 | +11.14 | 경고 |
| Servc | 오프라인만 | +14.45 | +13.77 | 경고 |
| Servc | 오프라인+유찰 | +13.53 | +12.44 | 경고 |
| Cnstwk | 미적용 | +3.35 | +1.51 | 없음 |
| Cnstwk | 유찰만 | +3.73 | +2.61 | 없음 |
| Cnstwk | 오프라인+유찰 | +3.81 | +2.70 | 없음 |
| Thng | 미적용 | +7.72 | +7.22 | 없음 |
| Thng | 유찰만 | +6.52 | +4.90 | 없음 |
| Thng | 오프라인+유찰 | +5.65 | +5.59 | 없음 |

- 오프라인+유찰 5주 기저: Servc 08-24 73.64 (1070/1453), 08-17 75.12 (1108/1475), 08-10 76.25 (1130/1482).
- **오프라인 제외는 Servc 격차를 키웁니다.** 미적용 11.81 → 오프라인만 14.45 → 오프라인+유찰 13.53. 지난 E1 실측(현재 41.0→47.3, 기저 49.5→60.4)과 같은 방향입니다.
- 물품·공사는 어느 변형에서도 임계 미만입니다.

---

## 6. 결론과 권고

### 6.1 경고 영향

| 질문 | 실측 답 |
| --- | --- |
| 유찰 제외가 경고를 없애는가 | 아니다. Servc 는 08-17·08-24 두 주 모두 임계를 유지한다 |
| 줄이는가 | 아주 조금 줄인다. Servc 격차 -0.6~-1.0%p, Thng -1.2~-2.3%p |
| 키우는가 | Cnstwk 에서만 0.4~1.8%p 키운다(경고 대상 아님). 오프라인 제외는 Servc 를 키운다 |

원인은 대칭성 자체입니다. 유찰은 현재 주와 기저에 같은 규칙으로 빠지므로 양쪽 매칭률이 함께 오르고, 그 차(격차)는 거의 보존됩니다.

### 6.2 T1~T5 구현 권고

| Task | 권고 | 근거 |
| --- | --- | --- |
| T1~T3 (모델·수집기·백필) | 권고 | 분모 정의를 실제 개찰 상태에 맞추고 백필·감사·재현을 가능하게 한다. 단 "경고 소멸"을 기대 근거로 삼으면 안 된다 |
| T4 (유찰 분모 제외 플래그) | 조건부 | 켜도 경고 판정이 유지되고 매칭률 수준만 실제에 가까워진다. 경고 대응 목적이면 우선순위 낮음, 데이터 정확성 목적이면 켜되 경고 정책과 분리 판단 |
| T5 (문서·CURRENT_STATE) | T4 결정에 맞춰 | 유찰 제외가 경고를 없애지 못한다는 실측을 함께 남긴다 |

### 6.3 오프라인 플래그 (`RESULT_COVERAGE_EXCLUDE_OFFLINE_BIDS`)

- 켜면 Servc 대형 격차가 11.81→14.45(08-24), 12.10→13.77(08-17)로 확대됩니다. 경고를 줄이려는 목적이면 역효과입니다.
- 다만 분모에서 나라장터 전자개찰 대상이 아닌 공고를 빼는 정의 자체는 정확성 측면에서 타당합니다. 켠 상태와 끈 상태 수치를 함께 남기는 현 관례를 유지하는 편이 판단에 낫습니다.

### 6.4 경고 억제 연장 (Servc:large, 만료 2026-10-20)

- 유찰 제외, 오프라인 제외, 두 제외의 결합 어느 것으로도 Servc 경고가 사라지지 않습니다. 억제 만료 후 경고는 재발합니다.
- 억제 연장만으로는 근본 대응이 아닙니다. 분모 재정의(유찰·직찰·협상 지연을 경고 기준 분모에서 제외하는 정의를 채택할지)와 경고 임계·판정식 조정을 함께 판단해야 합니다. 억제를 연장한다면 그 사이에 이 정책 결정을 끝내야 합니다.

---

## 7. 추정과 한계

- 이 보고서의 모든 수치는 **실측**입니다. E2 4.4절의 +16.8%p 는 표본 외삽 **추정**이었고, 이번 대칭 재계산은 유찰 판정을 API 로 직접 해 확정한 값입니다.
- **유찰 판정의 하한성**: 개찰결과 API 가 돌려준 개찰일 창 기준입니다. API 미등록 유찰은 잡히지 않으며, 협상·적격심사 지연(개찰완료·미등록)은 제외하지 않았습니다. 따라서 유찰 제외 매칭률은 상한, 격차는 하한 성격입니다.
- **공고번호 단위 판정**: 한 공고번호의 여러 차수 중 하나라도 유찰이면 그 공고번호의 미매칭 행을 모두 뺐습니다. 차수 단위 판정과 비교하면 Servc 08-24 기준 374 대 378 로 차이가 작고 결론이 바뀌지 않습니다(3.4절).
- **`exclude_later_cancelled=False` 고정**: 측정 계약입니다. 운영 `.env` 는 `RESULT_COVERAGE_EXCLUDE_LATER_CANCELLED=true` 이므로 운영 경고 재현 시 값이 다를 수 있습니다.
- 매칭 조인은 (공고번호, 분류, 정규화 차수) 기준이며, 결과 행의 `rl_openg_dt` 창 조건까지 정본과 같게 맞췄습니다(8.1절 질의가 정본과 1행도 다르지 않음을 확인).

---

## 8. 재현 명령

### 8.1 DB 질의 (읽기 전용)

`uv run python scripts/db_readonly_query.py --limit 0 --format json --sql "<질의>"` 로 실행합니다. 아래 질의는 `compute_result_match_rates` 와 취소공고 제외·차수 정규화·공고일시·결과 창 조건을 같게 맞춘 것으로, 표의 미적용·오프라인 분모와 매칭을 재현합니다.

```sql
SELECT a.category,
       DATE(DATE_SUB(a.openg_dt, INTERVAL WEEKDAY(a.openg_dt) DAY)) AS wk,
       COUNT(*) AS ann,
       SUM(CASE WHEN r.bid_ntce_no IS NOT NULL THEN 1 ELSE 0 END) AS matched,
       SUM(CASE WHEN a.bid_methd_nm IS NOT NULL AND TRIM(a.bid_methd_nm) <> ''
                 AND TRIM(a.bid_methd_nm) NOT LIKE '전자%' THEN 1 ELSE 0 END) AS offline
FROM bid_announcements a
LEFT JOIN bid_results r
  ON r.bid_ntce_no = a.bid_ntce_no AND r.category = a.category
 AND RIGHT(CONCAT('000', TRIM(LEADING '0' FROM a.bid_ntce_ord)), 3)
   = RIGHT(CONCAT('000', TRIM(LEADING '0' FROM r.bid_ntce_ord)), 3)
WHERE a.category IN ('Servc','Cnstwk','Thng') AND a.presmpt_prce >= 230000000
  AND (
    (a.openg_dt >= '2026-08-10 00:00:00' AND a.openg_dt < '2026-08-31 00:00:00'
     AND a.bid_ntce_dt >= '2025-08-10 00:00:00' AND a.bid_ntce_dt <= '2026-08-30 23:59:59')
    OR
    (a.openg_dt >= '2025-07-28 00:00:00' AND a.openg_dt < '2025-09-15 00:00:00'
     AND a.bid_ntce_dt >= '2024-07-28 00:00:00' AND a.bid_ntce_dt <= '2025-09-14 23:59:59')
  )
  AND (a.ntce_kind_nm IS NULL OR a.ntce_kind_nm <> '취소공고')
GROUP BY a.category, wk
ORDER BY a.category, wk;
```

### 8.2 API 창별 유찰 건수 확인 (하루 창 검증 예시)

리뷰어가 하루 창만 재호출해 표와 대조할 때 씁니다. 인증키·전체 URL 은 출력하지 않습니다.

```sh
docker compose -p refac_bid_box exec -T worker python - <<'EOF'
import time, httpx
from src.app.services.api_collector import get_service_key
KEY = get_service_key()
BASE = 'https://apis.data.go.kr/1230000/as/ScsbidInfoService/'
OPS = {'Servc':'getOpengResultListInfoServc','Thng':'getOpengResultListInfoThng','Cnstwk':'getOpengResultListInfoCnstwk'}
for cat, op in OPS.items():
    time.sleep(0.25)
    p = {'serviceKey':KEY,'type':'json','numOfRows':'999','pageNo':'1','inqryDiv':'3',
         'inqryBgnDt':'202608240000','inqryEndDt':'202608242359'}
    b = (httpx.get(BASE+op, params=p, timeout=30).json().get('response',{}) or {}).get('body',{}) or {}
    it = b.get('items') or []
    if isinstance(it, dict): it = it.get('item')
    if isinstance(it, dict): it = [it]
    n = sum(1 for i in (it or []) if '유찰' in str(i.get('progrsDivCdNm') or ''))
    print(cat, 'totalCount=', b.get('totalCount'), '유찰=', n)
EOF
```

### 8.3 컨테이너 결합 파이프라인 (유찰 교집합 + 대칭 제외 표)

유찰 집합과 DB 대형 공고 행을 결합해 3장·5장 표를 재계산합니다. 컨테이너에서 실행하며 파일을 만들지 않습니다. `exclude_later_cancelled=False`, `exclude_offline_bids=False` 로 고정합니다.

```sh
docker compose -p refac_bid_box exec -T worker python - <<'EOF'
import json, time, collections
from datetime import date, datetime, time as dtime, timedelta
import httpx
from sqlalchemy import or_
from src.app.core.db import SessionLocal
from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services.api_collector import get_service_key
from src.app.services.result_coverage import (
    _mature_week_starts, _baseline_window, _query_blocks, _with_mysql_execution_limit,
    week_start, normalize_ord, _is_offline_bid, LARGE_PRICE_THRESHOLD, TARGET_CATEGORIES,
    BASELINE_OFFSET_DAYS, NOTICE_LOOKBACK_DAYS, NULL_METHOD_LABEL,
)
AS_OF = date(2026, 9, 29)
mature = _mature_week_starts(AS_OF, 3, 28)
blocks = _query_blocks(mature)
target_weeks = set(mature)
for s in mature:
    target_weeks.update(_baseline_window(s - timedelta(days=BASELINE_OFFSET_DAYS)))
chunks = []
for bs, be in blocks:
    d = bs
    while d <= be:
        e = min(d + timedelta(days=14), be); chunks.append((d, e)); d = e + timedelta(days=1)
KEY = get_service_key()
BASE = 'https://apis.data.go.kr/1230000/as/ScsbidInfoService/'
OPS = {'Servc':'getOpengResultListInfoServc','Cnstwk':'getOpengResultListInfoCnstwk','Thng':'getOpengResultListInfoThng'}
def fetch(op, bgn, end):
    items, page = [], 1
    while True:
        p = {'serviceKey':KEY,'type':'json','numOfRows':'999','pageNo':str(page),
             'inqryDiv':'3','inqryBgnDt':bgn,'inqryEndDt':end}
        time.sleep(0.25)
        b = (httpx.get(BASE+op, params=p, timeout=40).json().get('response',{}) or {}).get('body',{}) or {}
        it = b.get('items') or []
        if isinstance(it, dict): it = it.get('item')
        if isinstance(it, dict): it = [it]
        it = it or []; items.extend(it)
        tc = int(b.get('totalCount') or 0)
        if not it or len(items) >= tc or page >= 60: break
        page += 1
    return items
failed_global = set()
for cat in TARGET_CATEGORIES:
    for cs, ce in chunks:
        for i in fetch(OPS[cat], cs.strftime('%Y%m%d')+'0000', ce.strftime('%Y%m%d')+'2359'):
            if '유찰' in str(i.get('progrsDivCdNm') or ''):
                failed_global.add((cat, str(i.get('bidNtceNo') or '')))
db = SessionLocal()
try:
    ann_rows, res_rows = [], []
    for bs, be in blocks:
        bsd = datetime.combine(bs, dtime.min); bed = datetime.combine(be, dtime.max)
        ann_rows.extend(_with_mysql_execution_limit(db.query(
            BidAnnouncement.bid_ntce_no, BidAnnouncement.bid_ntce_ord, BidAnnouncement.category,
            BidAnnouncement.presmpt_prce, BidAnnouncement.openg_dt, BidAnnouncement.bid_methd_nm
        ).filter(
            BidAnnouncement.bid_ntce_dt >= datetime.combine(bs - timedelta(days=NOTICE_LOOKBACK_DAYS), dtime.min),
            BidAnnouncement.bid_ntce_dt <= bed,
            BidAnnouncement.openg_dt >= bsd, BidAnnouncement.openg_dt <= bed,
            BidAnnouncement.category.in_(TARGET_CATEGORIES),
            or_(BidAnnouncement.ntce_kind_nm.is_(None), BidAnnouncement.ntce_kind_nm != '취소공고'),
        )).all())
        res_rows.extend(_with_mysql_execution_limit(db.query(
            BidResult.bid_ntce_no, BidResult.bid_ntce_ord, BidResult.category
        ).filter(BidResult.category.in_(TARGET_CATEGORIES),
                 BidResult.rl_openg_dt >= datetime.combine(bs - timedelta(days=14), dtime.min),
                 BidResult.rl_openg_dt <= datetime.combine(be + timedelta(days=90), dtime.max))).all())
    result_keys = {(no, cat, normalize_ord(o)) for no, o, cat in res_rows}
finally:
    db.close()
recs = []
for no, o, cat, price, openg_dt, method in ann_rows:
    if openg_dt is None: continue
    w = week_start(openg_dt.date())
    if w not in target_weeks: continue
    band = 'large' if (price or 0) >= LARGE_PRICE_THRESHOLD else 'small'
    norm = normalize_ord(o)
    recs.append((cat, w.isoformat(), band, (no, cat, norm) in result_keys, _is_offline_bid(method),
                 (cat, no) in failed_global, method if method is not None else NULL_METHOD_LABEL))
V = {
    'base':     lambda m, o, f: True,
    'failed':   lambda m, o, f: not (f and not m),
    'offline':  lambda m, o, f: not o,
    'combined': lambda m, o, f: (not o) and not (f and not m),
}
OUT = {k: (collections.defaultdict(lambda: [0, 0]), collections.defaultdict(lambda: [0, 0])) for k in V}
for cat, w, band, matched, offline, failed, method in recs:
    for k, pred in V.items():
        if not pred(matched, offline, failed): continue
        o_, m_ = OUT[k]
        b = o_[(cat, w, band)]; b[0] += 1
        if matched: b[1] += 1
        mm = m_[(cat, w, band, method)]; mm[0] += 1
        if matched: mm[1] += 1
def rate(m, a): return None if a <= 0 else round(m / a, 4)
def adjusted(cat, ws, outv, methv):
    ann, matched = outv[(cat, ws, 'large')]
    if ann <= 0: return None
    overall = matched / ann
    wset = {d.isoformat() for d in _baseline_window(date.fromisoformat(ws) - timedelta(days=BASELINE_OFFSET_DAYS))}
    bm, cur = collections.defaultdict(lambda: [0, 0]), collections.defaultdict(lambda: [0, 0])
    for (c, w2, b, ml), v in methv.items():
        if c != cat or b != 'large': continue
        if w2 == ws: cur[ml][0] += v[0]; cur[ml][1] += v[1]
        if w2 in wset: bm[ml][0] += v[0]; bm[ml][1] += v[1]
    tot = sum(x[0] for x in bm.values())
    if tot <= 0: return None
    return round(sum((v[0]/tot) * (overall if (cur.get(ml) is None or cur[ml][0] <= 0) else cur[ml][1]/cur[ml][0])
                     for ml, v in bm.items()), 4)
for cat in TARGET_CATEGORIES:
    for ws in sorted(s.isoformat() for s in mature):
        center = (date.fromisoformat(ws) - timedelta(days=BASELINE_OFFSET_DAYS)).isoformat()
        window = [d.isoformat() for d in _baseline_window(date.fromisoformat(center))]
        for k in V:
            o_, m_ = OUT[k]
            ann, matched = o_[(cat, ws, 'large')]
            sa, sm = o_[(cat, center, 'large')]
            ma = sum(o_[(cat, x, 'large')][0] for x in window)
            mm = sum(o_[(cat, x, 'large')][1] for x in window)
            print(json.dumps({'cat': cat, 'week': ws, 'rule': k, 'ann': ann, 'matched': matched,
                'rate': rate(matched, ann), 'single': rate(sm, sa), 'multi': rate(mm, ma),
                'adj': adjusted(cat, ws, o_, m_), 'gap': None if rate(mm, ma) is None else round(rate(mm, ma) - adjusted(cat, ws, o_, m_), 4)},
                ensure_ascii=False))
EOF
```

### 8.4 유찰 창별 건수(2.3절 원장 재현)

8.3절 파이프라인에 창 루프 로그(창별 `items`, `failed`, 누적 호출 수)를 넣으면 2.3절 호출 원장과 창별 건수를 재현합니다.

---

## 9. 참고 문서

- `docs/analysis/servc_failed_bid_design_20260929.md`(E2): 개찰결과 API 실측, 유찰 표본 비율, 저장 설계 대안, T1~T5 분할. 1절 코디네이터 정정(비대칭 비교 한계)의 후속 실측이 이 문서입니다.
- `docs/analysis/servc_g2b_manual_checklist_20260928.md`(4.1절): 25건 대조와 유찰 10건, 오프라인(직찰·설계공모) 분모 왜곡 판정.
- `src/app/services/result_coverage.py`: 매칭률·경고 정본. `compute_result_match_rates`, `evaluate_match_rate_alerts`, `_is_offline_bid`, `BASELINE_OFFSET_DAYS=364`, `BASELINE_WINDOW_WEEKS=2`, `RATE_DROP_ALERT=0.10`, `MIN_WEEK_SAMPLES=100`, `LARGE_PRICE_THRESHOLD=230000000`.
- `docs/context/CURRENT_STATE.md`: 수집 파이프라인·게이트 운영 정본.
