# '2억미만 1억이상' 용역 첨부 판별 2단 규칙의 홀드아웃 검증

> **작성일**: 2026-11-06
> **작업**: Orca Task `task_390d809c16fe` (builder), Run `run_8734173629f4`, Dispatch `ctx_83c6df66be3f`
> **정본 사양**: `.orca/capsules/task_band_holdout_20261106/capsule.yaml` (`ORCA_TASK_CAPSULE_V2`)
> **검증 대상**: `.orca/ref/band_2to1_attachment_classifier_design_20261106.md` (main 미병합 설계 사본, 커밋하지 않는 참조 경로) 2.3절 판정기와 2.4절 2단 판별
> **모집단**: `.cache/band_holdout/population.json` 107행에서 고유 공고번호 87건(공고번호별 최신 차수 1행). 2024-11-06 ~ 2025-11-05 용역 공고 중 `sucsfbidMthdNm` 에 '2억미만 1억이상' 포함. 실제 공고일 범위는 2025-01-07 ~ 2025-11-03입니다.
> **설계 조사와의 분리**: 설계 조사 모집단은 2025-11-07 ~ 2026-10-15 이고, 이번 홀드아웃의 최대 공고일은 2025-11-03 입니다. 두 구간은 겹치지 않습니다.
> **증거**: 첨부 181개를 `curl -sL` 로 내려받아 `.cache/band_holdout/raw/` 에만 두었습니다. 커밋하지 않았습니다. 인용은 원문에서 80자 이내로 잘랐습니다.
> **판정**: `candidate`. 결론 라벨은 `설계 2단 규칙은 홀드아웃에서 80/87(92.0%) 로 재현되며, 오류는 세부표 미지정 4건과 참고 문장 오탐 2건에 집중됩니다` 입니다.
> **역할 경계**: 코드·스키마·설정을 변경하지 않았습니다. 이번 작업의 커밋 산출물은 이 문서 한 건입니다. 판별 함수 구현은 다른 빌더가 진행 중이며, 이 문서는 그 구현의 근거가 아니라 설계 규칙의 홀드아웃 성적표입니다.
> **재현**: 부록 A 스크립트로 1절·2절·3절·4절 수치와 부록 B 를 다시 계산할 수 있습니다.

---

## 1. 요약

설계 문서 부록 A 의 `classify()` 를 **한 글자도 고치지 않고** 홀드아웃 87건에 기계 적용했습니다. 규칙을 보기 전에 원문으로 정답을 먼저 확정했고, 정답 라벨은 표에 따로 적었습니다(2절). 결과는 다음과 같습니다.

| 항목 | 이번 홀드아웃 | 설계 조사(in-sample) | 차이 |
| --- | ---: | ---: | ---: |
| 표본 | 87건 | 100건 | - |
| 완전 일치 | 80건 | 99건 | - |
| 정확도 | 80/87 = 91.95% | 99/100 = 99.0% | -7.05%p |
| 판정 확정 건(정답 기준) | 67건(77.0%) | 86건(86.0%) | -9.0%p |
| 갈래 미지정(UNSPECIFIED) | 8건(9.2%) | 3건(3.0%) | +6.2%p |
| 첨부 없음(NO_ATTACH) | 12건(13.8%) | 11건(11.0%) | +2.8%p |

핵심 결론은 네 가지입니다.

1. **2단 규칙은 홀드아웃에서도 주 갈래를 정확히 가릅니다.** 정답이 확정된 67건(학술 63, 기술·일반 4)은 규칙도 67건 모두 같은 갈래로 판정했습니다(67/67). 규칙이 확정한 71건 기준으로는 67건이 맞아 정밀도 94.4%입니다.
2. **오분류 6건은 모두 '정답이 갈래 미지정인 공고'입니다.** 학술·기술 갈래를 이미 확정한 공고에서 갈래를 뒤집은 사례는 0건입니다. 즉 이 표본에서 규칙의 실패 모드는 "모른다고 말하지 못하는 것"입니다.
3. **설계 7.1절이 지목한 in-sample 과적합 위험이 실측으로 확인됐습니다.** 99/100 이 80/87 로 내려앉았습니다(-7.05%p). 낙폭은 대부분 `UNSPECIFIED` 재현율(정답 8건 중 완전 일치 1건, 판별 불가로 묶으면 2건)에서 발생했습니다.
4. **설계가 경고한 두 함정이 홀드아웃에도 그대로 있습니다.** 참고 문장의 `제4장 물품` 문구가 결정 문장을 이겨 2건을 `MOIS4` 로 오분류했고, `[별표 4]`/`[별표 2]` 표지 없이 장(章) 이름만 적은 공고 4건은 규칙이 학술로 단정했습니다.

---

## 2. 갈래 분포(정답 기준)

### 2.1 라벨 기준

규칙을 보기 전에 공고마다 첨부 원문의 `낙찰자 결정`·`적격심사 기준`·`평가기준` 문장을 읽고 아래 기준으로 갈래를 정했습니다. 설계 문서 3.3절의 보수적 처리(발행기관·장·별표가 없으면 미지정)를 그대로 따랐습니다.

| 정답 라벨 | 확정 조건 |
| --- | --- |
| `MOIS_ACADEMIC` | 결정 문장이 행안부 예규 `제2장의2` + `[별표 4]`(학술연구용역 평가기준)를 지목하거나, `학술연구용역 적격심사 세부기준(행정안전부 예규)` 처럼 발행기관과 문서명을 함께 적음 |
| `MOIS_OTHER` | 결정 문장이 `[별표 2]` 사업수행능력평가(P.Q)를 하지 않는 기술용역을 지목(낙찰하한율 87.745%, 종합평점 95점) |
| `PPS` | 결정 문장이 `조달청 일반용역 적격심사 세부기준`(별표 1 학술연구)을 지목 |
| `LOCAL` | 결정 문장이 지자체 자체 기준(예: `경기도 일반용역 적격심사 세부기준`)을 지목 |
| `MOIS4` | 결정 문장이 `제4장 물품 적격심사 세부기준`을 지목 |
| `UNSPECIFIED` | 적용 문장은 있으나 발행기관·장·별표가 없어 갈래를 확정할 수 없음(문서명만, 장만, 취소공고, 텍스트 추출 실패 포함) |
| `NO_ATTACH` | `std_url`·`u1`~`u3` 가 모두 비어 있음 |

`UNSPECIFIED` 8건의 내역은 다음과 같습니다. 라벨 손실을 숨기지 않으려고 하위 사유를 함께 적습니다.

| 하위 사유 | 건수 | 공고번호 |
| --- | ---: | --- |
| 발행기관·장·별표 없이 문서명만(`일반용역 적격심사 세부기준 [학술연구용역 적격심사 기준]`) | 2 | R25BK00558057, R25BK00562329 |
| 장(제2장의2)만 확인, 세부표 미지정 | 4 | R25BK00633539, R25BK00877268, R25BK00877509, R25BK00880281 |
| 취소공고(적용 기준 문장 없음) | 1 | R25BK00629055 |
| 첨부는 있으나 텍스트 추출 실패(ZIP 만) | 1 | R25BK01097439 |

### 2.2 분포

| 갈래 | 건수 | 비율 | 판정 근거 |
| --- | ---: | ---: | --- |
| 행안부 예규 제2장의2 [별표 4] 학술연구용역 | 63 | 72.4% | `[별표4] 학술연구용역`, `학술연구용역 적격심사 세부기준(행정안전부 예규)`, `제2장의2 … 별표4` 등 |
| 행안부 예규 제2장의2 [별표 2] 기술·일반용역(학술 아님) | 4 | 4.6% | `[별표2] … P.Q를 하지 않는 기술용역`, 낙찰하한율 87.745%, 종합평점 95점 |
| 조달청 일반용역 적격심사 세부기준 [별표 1] | 0 | 0.0% | 결정 문장에서 확인된 공고 없음 |
| 지자체 자체 기준 | 0 | 0.0% | 결정 문장에서 확인된 공고 없음 |
| 행안부 예규 제4장 물품 | 0 | 0.0% | 결정 문장에서 확인된 공고 없음. 영월의료원 2건은 `참고` 문장뿐 |
| 갈래 미지정 | 8 | 9.2% | 2.1절 하위 사유 표 |
| 첨부 없음 | 12 | 13.8% | URL 자체가 없음 |
| 합계 | 87 | 100.0% | |

설계 모집단과 비교하면 학술 편중이 더 심해졌습니다(77.0% → 72.4%). PPS·LOCAL 은 이 표본의 결정 문장에 아예 등장하지 않아, 설계가 넣은 `LOCAL 우선` 우선순위는 이 홀드아웃에서 **검증되지 않았습니다**(검증 불가이지 통과가 아닙니다).

### 2.3 수집·추출 현황

| 항목 | 값 |
| --- | --- |
| 모집단 행 | 107행(중복 차수 20행 포함) |
| 고유 공고번호 | 87건 |
| 내려받은 첨부 | 181개(공고당 2개 40건, 3개 33건, 1개 2건, 0개 12건) |
| 텍스트 추출 성공 | 158개(87.3%) |
| 추출 실패 | 23개(XLSX 18, ZIP 3, PDF 2) |
| 모든 첨부가 실패한 공고 | 1건(R25BK01097439, ZIP 만 첨부) |
| 요청 예절 | `curl -sL --max-time 30`, 요청 사이 1.05초 |

---

## 3. 혼동 행렬(정답 × 규칙)

행이 사람 정답, 열이 설계 부록 A `classify()` 결과입니다. `EXTRACT_FAIL` 은 규칙 스크립트가 텍스트 없음으로 반환하는 값으로, 정답 라벨에는 없는 예측 전용 값입니다.

| 정답 \ 규칙 | MOIS_ACADEMIC | MOIS_OTHER | PPS | LOCAL | MOIS4 | UNSPECIFIED | EXTRACT_FAIL | NO_ATTACH | 합계 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MOIS_ACADEMIC | 63 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 63 |
| MOIS_OTHER | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 4 |
| PPS | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| LOCAL | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| UNSPECIFIED | 4 | 0 | 0 | 0 | 2 | 1 | 1 | 0 | 8 |
| NO_ATTACH | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 12 | 12 |
| 합계 | 67 | 4 | 0 | 0 | 2 | 1 | 1 | 12 | 87 |

- 행 합계 63 + 4 + 0 + 0 + 8 + 12 = 87 이고, 부록 B 행 수 87 과 같습니다.
- 열 합계 67 + 4 + 0 + 0 + 2 + 1 + 1 + 12 = 87 입니다.
- 완전 일치 80건(91.95%). `UNSPECIFIED` 와 `EXTRACT_FAIL` 을 같은 '판별 불가'로 묶으면 81건(93.10%)입니다.
- 정답이 확정된 67건의 재현율은 갈래별로 학술 63/63(100%), 기술·일반 4/4(100%)입니다.
- 규칙이 확정한 71건의 정밀도는 67/71(94.37%)입니다. 오탐 4건은 정답이 `UNSPECIFIED` 인 공고입니다.

---

## 4. 불일치 사례 전량

불일치 7건 전부입니다. 6건은 갈래 오분류이고, 1건은 판별 불가 처리 차이입니다.

| 공고번호 | 수요기관 | 정답 | 규칙 결과 | 원인 | 원문 인용(80자 이내) |
| --- | --- | --- | --- | --- | --- |
| R25BK00558057 | 강원특별자치도영월의료원 | UNSPECIFIED | MOIS4 | 참고 문장의 `제4장 물품` 이 R8·R9 에 매치. 점수 MOIS4 1.31 vs MOIS_ACADEMIC 0.08 | `적격심사기준 : 일반용역 적격심사 세부기준 [학술연구용역 적격심사 기준을 적용` / 오탐 문장 `물품적격심사에 적용되는 세부기준은 … 제4장 물품 적격심사 세부기준을 참고 하시기 바랍니다` |
| R25BK00562329 | 강원특별자치도영월의료원 | UNSPECIFIED | MOIS4 | 위와 동일(같은 재공고) | `적격심사기준 : 일반용역 적격심사 세부기준 [학술연구용역 적격심사 기준을 적용` |
| R25BK00633539 | 대전광역시 | UNSPECIFIED | MOIS_ACADEMIC | `기술·학술연구 용역 적격심사 세부기준` 안의 `학술연구 …` 부분 문자열이 R3 에 3회 매치(점수 7.72). 별표 표지 없음 | `행정안전부 예규「지방자치단체 입찰시 낙찰자 결정기준」의 ‘기술․학술연구 용역 적격심사 세부기준’` |
| R25BK00877268 | 충청북도 제천시 | UNSPECIFIED | MOIS_ACADEMIC | 제2장의2(R1)와 문서명(R3)로 학술 확정. `[별표 4]`·`[별표 2]` 표지 없이 띠 문구만 있음(R13) | `제2장의2 기술·학술연구 용역 적격심사 세부기준”에 의거 【추정가격 2억미만 1억이상 용역】` |
| R25BK00877509 | 충청북도 제천시 | UNSPECIFIED | MOIS_ACADEMIC | 위와 동일(같은 사업 다른 마을) | `제2장의2 기술·학술연구 용역 적격심사 세부기준”에 의거 【추정가격 2억미만 1억이상 용역】` |
| R25BK00880281 | 대전광역시 | UNSPECIFIED | MOIS_ACADEMIC | R3 3회 매치(점수 9.98). 별표 표지 없음 | `‘기술․학술연구 용역 적격심사 세부기준’에 의거 예정가격 이하로서 최저가격(80.495%이상)` |
| R25BK01097439 | 강원특별자치도삼척의료원 | UNSPECIFIED | EXTRACT_FAIL | 첨부가 `입찰공고.zip` 1개뿐이라 텍스트를 얻지 못함. 정답과 규칙 모두 '판별 불가'이며 라벨만 다름 | `(추출 실패: 입찰공고.zip)` |

해석은 세 가지입니다.

1. **참고 문장 오탐(2건)은 설계 2.2절이 이미 지목한 원인 그대로입니다.** 영월의료원 재공고는 실제 적용 문장이 `일반용역 적격심사 세부기준 [학술연구용역 적격심사 기준]` 인데, 뒤에 붙은 `물품적격심사에 적용되는 세부기준은 … 참고 하시기 바랍니다` 가 R8·R9 를 3.5점으로 끌어올렸습니다. 설계 in-sample 에서는 이 기관이 PPS 로 판정됐지만, 이번 차수 공고문에는 조달청 문구가 없어 MOIS4 로 떨어졌습니다. 문서명 판정이 공고문 판본에 따라 흔들린다는 뜻입니다.
2. **장(章)만 보고 세부표를 단정하는 문제(4건)는 설계 규칙에 상태 자체가 없습니다.** `기술·학술연구 용역 적격심사 세부기준` 은 학술과 기술을 함께 담은 장 이름입니다. 그런데 R1·R3 가 이 이름만으로 `MOIS_ACADEMIC` 을 확정합니다. 설계 7.1절의 `in-sample 과적합` 위험이 정확히 이 지점에서 나타났습니다.
3. **추출 실패 1건은 판정 로직의 문제가 아닙니다.** ZIP 만 첨부하는 관행이 남아 있으므로, 저장 스키마에서 `EXTRACT_FAIL` 을 `UNSPECIFIED` 와 분리해야 재시도 대상이 명확해집니다(설계 4.2절 (다) 배치).

---

## 5. 설계 규칙 보완 제안(구현하지 않음)

아래는 이번 홀드아웃에서 드러난 원인에 대한 제안이며, **이번 작업에서 코드나 규칙을 고치지 않았습니다.** 제안을 홀드아웃에 다시 적용해 수치를 재측정하지도 않았습니다. 그렇게 하면 이 문서가 다시 in-sample 이 되기 때문입니다.

| 우선 | 제안 | 근거(이번 실측) | 예상 효과 |
| --- | --- | --- | --- |
| 1 | 세부표 미지정 상태를 `UNSPECIFIED_SUBTABLE` 같은 별도 값으로 두고, `[별표 4]`·`[별표 2]` 직접 표지가 있을 때만 세부 갈래를 확정 | 장 이름만 있는 공고 4건이 학술로 단정됨(3절) | 오탐 4건 제거. 대신 정답도 미지정이므로 정확도가 오르고 '확정' 주장은 줄어듦 |
| 2 | 참고 문장 매치를 결정 창에서 폐기. 같은 문장·절에 `참고 하시기 바랍니다`·`숙지` 가 있으면 그 매치를 0 으로 | 영월의료원 2건이 `제4장 물품` 참고 문장으로 MOIS4 오분류 | 오분류 2건 제거 |
| 3 | R3(`학술…용역 적격심사 세부기준`)를 학술 확정 신호에서 보조 신호로 내리고, 확정은 R2·R4 만 사용 | R3 매치 69건 중 오탐 7건, 그중 6건이 `기술·학술연구 용역 적격심사 세부기준` 부분 문자열 | R3 의존을 줄이면 장만 있는 공고의 과신 방지 |
| 4 | `EXTRACT_FAIL` 을 `UNSPECIFIED` 와 분리 저장하고 ZIP·XLSX 를 재시도 큐로 보냄 | 삼척의료원 1건이 ZIP 만 첨부 | 재시도 대상 식별. 판별 자체는 불가 |
| 5 | 87.745 를 세부표 확정 신호로 유지하고, 80.495 는 확정 신호로 쓰지 않음(설계 판단 유지) | 87.745: 학술 0/63, 기술 4/4. 80.495: 학술 63/63 이지만 미지정 8건 중 6건에도 존재 | 설계 2.4절 선택이 홀드아웃에서도 지지됨 |
| 6 | 별표 표기 변형 사전 보강(`[별표4] 학술연구용역`, `별표 4] …`, `별표4 : 학술연구용역 평가기준` 등) | R2·R4 는 오탐 0 이지만 미검출이 각 33건 | 확정 신호의 재현율 상승. 단 R1·R3 의존을 줄이는 3번과 함께 설계해야 함 |

보조 관찰 두 가지를 남깁니다.

- **R10(지자체 기준)은 3건 매치가 전부 오탐입니다.** 용인시·세종시 2건 모두 `경기도 일반용역 적격심사 세부기준`, `세종특별자치시 일반용역 적격심사 세부기준` 이 숙지·서류 제출 문장에만 있었습니다. 설계 2.1절의 R10 오탐 5/7 과 같은 양상입니다.
- **R12(기술용역)는 11건 매치 중 9건이 오탐입니다.** 대부분 `기술·학술연구 용역 적격심사` 의 부분 문자열입니다. 설계가 R12 를 단독으로 쓰지 말라고 한 판단이 유지됩니다.

---

## 6. 한계

| 한계 | 내용 | 영향 |
| --- | --- | --- |
| 라벨러와 규칙 적용자가 같은 워커 | 정답 라벨과 규칙 실행을 한 세션에서 처리했습니다. 규칙을 보기 전에 라벨 표(2.1~2.2절)와 인용을 먼저 확정했지만, 독립 이중 라벨링이 아닙니다 | 라벨 편향을 배제하지 못함. 리뷰 시 부록 B 인용으로 재검증 필요 |
| 라벨 정책이 보수적 | 발행기관·장·별표가 없으면 `UNSPECIFIED` 로 두었습니다. 4건은 80.495% 를 근거로 학술로 볼 여지가 있습니다 | 정책을 넓히면 일치율이 달라짐. 이 문서는 정책을 고정한 값만 보고 |
| 숫자 신호를 라벨링 중 함께 확인 | 발췌 과정에서 87.745·80.495 유무를 같이 출력했습니다. 다만 갈래는 표지 유무로만 정했고, 숫자로 갈래를 확정한 행은 없습니다 | 규칙과 독립이 완전하지 않음 |
| 표본 크기와 구성 | 87건, 단일 12개월, 용역 한정, 지방계약 편중(PPS·LOCAL 결정 문장 0건) | PPS·LOCAL 우선순위는 검증 불가. 연도·기관 편중은 미확인 |
| 추출 실패 | 23개 파일 실패(XLSX 18, ZIP 3, PDF 2), 1건은 판별 불가 | 대부분 다른 첨부로 보완됐으나 ZIP·XLSX 만 있는 공고는 판별 불가 |
| PDF 파서 | pypdf 가 설치되어 있지 않고 새 라이브러리 추가가 금지되어, 설계 조사와 같은 `pdfplumber`(`pyproject.toml:44` 선언 의존성)를 사용했습니다 | 정본 사양의 `pypdf` 지정과 다름. PDF 7개 중 5개 추출 성공, 2개 실패 |
| 최신 차수만 사용 | 공고번호별 최신 차수 1행만 봤습니다 | 이전 차수의 문구 차이는 미검증 |
| 규칙 값 미확인 | MOIS_OTHER 4건의 별표 값(B·k·통과점수)은 이번 검증 범위가 아님 | 갈래 판별만 검증. 계산 가능성은 미검증 |

---

## 부록 A. 재계산 스크립트

저장소 루트에서 실행합니다. 첨부가 이미 있으면 `--download` 없이 추출·판정·집계만 다시 합니다. 새로 받으려면 `--download` 를 붙입니다. 요청 사이 1.05초 대기, 회당 최대 30초, 첨부는 `.cache/band_holdout/raw/` 에만 씁니다. `LABELS` 는 2.1절 기준으로 확정한 정답이고, `classify()` 는 설계 문서 부록 A 와 같습니다.

```python
"""낙찰방법명 '2억미만 1억이상' 용역 홀드아웃 판별 재계산.

사용:
  uv run python .cache/band_holdout/reproduce_all.py            # 내려받은 첨부로 재계산
  uv run python .cache/band_holdout/reproduce_all.py --download # 첨부부터 다시 받기

규칙은 설계 문서 부록 A 의 classify() 를 그대로 옮겼고, 정규식·가중치·판정 순서를
홀드아웃에 맞춰 고치지 않았다. LABELS 는 규칙을 보기 전에 원문으로 확정한 정답이다.
"""

from __future__ import annotations

import argparse
import io
import json
import pathlib
import re
import subprocess
import sys
import time
import zipfile
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache/band_holdout"
RAW = CACHE / "raw"
TEXT = CACHE / "text"
sys.path.insert(0, str(ROOT))

import pdfplumber

from scripts.extract_score_params import extract_document_text

OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
MAX_PDF_PAGES = 60

LABELS = {
    "MOIS_OTHER": ["R25BK00609576", "R25BK00613676", "R25BK00651689", "R25BK01038745"],
    "UNSPECIFIED": [
        "R25BK00558057", "R25BK00562329", "R25BK00629055", "R25BK00633539",
        "R25BK00877268", "R25BK00877509", "R25BK00880281", "R25BK01097439",
    ],
    "NO_ATTACH": [
        "R25BK00593514", "R25BK00599032", "R25BK00606227", "R25BK00646559",
        "R25BK00646797", "R25BK00680649", "R25BK00695984", "R25BK00728491",
        "R25BK00804208", "R25BK01041705", "R25BK01041821", "R25BK01108529",
    ],
}

PATTERNS = [
    ("R1", "MOIS_ACADEMIC", r"제\s*2\s*장\s*의\s*2"),
    ("R2", "MOIS_ACADEMIC", r"별표\s*4\s*(?:의)?\s*[^.]{0,20}학술연구"),
    ("R3", "MOIS_ACADEMIC", r"학술(?:[·ㆍ.]?\s*연구)?\s*용역\s*적격심사\s*세부\s*기준"),
    ("R4", "MOIS_ACADEMIC", r"학술연구용역\s*평가\s*기준"),
    ("R5", "MOIS_COMMON", r"지방자치단체\s*입찰시\s*낙찰자\s*결정\s*기준"),
    ("R6", "PPS", r"조달청\s*일반용역\s*적격심사\s*세부기준"),
    ("R7", "PPS", r"별표\s*1\s*[^.]{0,12}학술연구"),
    ("R8", "MOIS4", r"제\s*4\s*장\s*물품"),
    ("R9", "MOIS4", r"물품\s*적격심사\s*세부기준"),
    ("R10", "LOCAL", r"(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)[가-힣]{0,8}\s*(?:광역시|특별시|특별자치시|특별자치도|도|시|군|구)?\s*일반\s*용역\s*등?\s*적격심사"),
    ("R11", "LOCAL", r"시\s*[·ㆍ.]\s*도\s*일반\s*용역\s*등?\s*적격심사"),
    ("R12", "MOIS_OTHER", r"기술\s*용역\s*적격심사|추정가격\s*2\s*억\s*원?\s*미만인\s*일반\s*용역|사업수행능력평가\s*\(?P\.?Q\)?[^.]{0,30}기술용역"),
    ("R13", "BAND", r"추정가격\s*2\s*억\s*원?\s*미만\s*1\s*억\s*원?\s*이상"),
]
TARGET = {
    "MOIS_ACADEMIC": {"MOIS_ACADEMIC"}, "MOIS_COMMON": {"MOIS_ACADEMIC", "MOIS_OTHER"},
    "PPS": {"PPS"}, "MOIS4": {"MOIS4"}, "LOCAL": {"LOCAL"},
    "MOIS_OTHER": {"MOIS_OTHER"}, "BAND": {"MOIS_ACADEMIC", "MOIS_OTHER"},
}
VERB = re.compile(r"적용|따르|따라|의거|의하|의함|의하며|준용|평가합니다|평가하며|결정합니다")
DECISIVE = re.compile(r"낙찰자\s*(?:결정|선정)|계약상대자\s*결정|적격심사")
NOISE = re.compile(r"숙지|참고\s*(?:하|하시)|양식|목록|문의")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\u200b", "").replace("\xa0", " ").replace("\u3000", " "))


def population() -> dict[str, dict]:
    best = {}
    for r in json.load(open(CACHE / "population.json")):
        no = r["bid_ntce_no"]
        if no not in best or int(r["bid_ntce_ord"] or 0) > int(best[no]["bid_ntce_ord"] or 0):
            best[no] = r
    return best


def download(best: dict[str, dict]) -> None:
    for no, r in sorted(best.items()):
        seen = set()
        for slot, key in (("std", "std_url"), ("f1", "u1"), ("f2", "u2"), ("f3", "u3")):
            url = r.get(key)
            if not url or url in seen:
                continue
            seen.add(url)
            out = RAW / no / f"{slot}.bin"
            out.parent.mkdir(parents=True, exist_ok=True)
            if out.exists() and out.stat().st_size > 0:
                continue
            subprocess.run(
                ["curl", "-sL", "--max-time", "30", "-o", str(out),
                 "-w", "%{http_code} %{size_download} %{time_total}", url],
                capture_output=True, text=True, check=False,
            )
            time.sleep(1.05)


def sniff(data: bytes) -> str:
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except Exception:
            return "zip-broken"
        if "Contents/content.hpf" in names or "mimetype" in names:
            return "hwpx"
        if any(n.startswith("xl/") for n in names):
            return "xlsx"
        return "zip"
    if data.startswith(b"<?xml"):
        return "hwpml"
    if data.startswith(OLE):
        return "hwp"
    if b"<html" in data[:4000].lower():
        return "html"
    return "unknown"


def extract_all() -> list[dict]:
    TEXT.mkdir(parents=True, exist_ok=True)
    records = []
    for d in sorted(p for p in RAW.iterdir() if p.is_dir()):
        for f in sorted(d.glob("*.bin")):
            data = f.read_bytes()
            kind = sniff(data)
            text = ""
            if kind in ("hwp", "hwpx", "hwpml"):
                doc = extract_document_text(data)
                text = doc.flat if doc.ok else ""
            elif kind == "pdf":
                try:
                    with pdfplumber.open(io.BytesIO(data)) as pdf:
                        if len(pdf.pages) <= MAX_PDF_PAGES:
                            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
                except Exception:
                    text = ""
            records.append({
                "bid_no": d.name, "slot": f.stem, "bytes": len(data), "kind": kind,
                "ok": bool(text.strip()), "chars": len(text),
            })
            if text.strip():
                (TEXT / f"{d.name}__{f.stem}.txt").write_text(text, encoding="utf-8")
    return records


def classify(b: str, by_bid: dict, texts: dict) -> str:
    if not by_bid.get(b):
        return "NO_ATTACH"
    if not texts[b]:
        return "EXTRACT_FAIL"
    text = texts[b]
    weight = {
        "MOIS_ACADEMIC": [("R1", 2.0), ("R2", 2.0), ("R3", 2.0), ("R4", 2.0), ("R5", 0.2)],
        "PPS": [("R6", 2.0), ("R7", 2.0)],
        "MOIS4": [("R8", 2.0), ("R9", 1.5)],
        "LOCAL": [("R10", 2.0), ("R11", 1.5)],
        "MOIS_OTHER": [("R12", 2.0)],
    }
    pmap = {pid: re.compile(p) for pid, _, p in PATTERNS}
    scores = defaultdict(float)
    for branch, items in weight.items():
        for pid, w in items:
            for m in pmap[pid].finditer(text):
                win = text[max(0, m.start() - 160): m.end() + 160]
                if not VERB.search(win):
                    continue
                mult = 0.25 if NOISE.search(win) else 1.0
                if DECISIVE.search(win):
                    mult *= 1.5
                scores[branch] += w * mult
    order = ["MOIS4", "PPS", "LOCAL", "MOIS_OTHER", "MOIS_ACADEMIC"]
    if not scores or max(scores.values()) <= 0:
        return "UNSPECIFIED"
    branch = max(order, key=lambda k: (scores[k], -order.index(k)))
    if branch == "MOIS_ACADEMIC" and re.search(r"87\.745", text):
        branch = "MOIS_OTHER"
    return branch


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    args = ap.parse_args()

    best = population()
    if args.download:
        download(best)
    records = extract_all()
    by_bid = defaultdict(list)
    for rec in records:
        by_bid[rec["bid_no"]].append(rec)

    truth = {b: "MOIS_ACADEMIC" for b in best}
    for label, bids in LABELS.items():
        for b in bids:
            truth[b] = label

    texts = {}
    for b in best:
        chunks = []
        for rec in by_bid.get(b, []):
            p = TEXT / f"{b}__{rec['slot']}.txt"
            if p.exists():
                chunks.append(norm(p.read_text(errors="ignore")))
        texts[b] = norm(" ".join(chunks))

    print("== 모집단 ==")
    print("rows", len(json.load(open(CACHE / "population.json"))), "unique", len(best))
    print("files", len(records), "ok", sum(r["ok"] for r in records),
          "kinds", dict(Counter(r["kind"] for r in records)))
    print("truth", dict(Counter(truth.values())))

    print("\n== 패턴별 적중·오탐 ==")
    print("id\tbranch\tmatched\thit\tfp\tmiss")
    for pid, branch, pat in PATTERNS:
        rx = re.compile(pat)
        matched = {b for b, t in texts.items() if t and rx.search(t)}
        hit = {b for b in matched if truth[b] in TARGET[branch]}
        fp = matched - hit
        miss = {b for b in truth if truth[b] in TARGET[branch] and b not in matched}
        print(pid, branch, len(matched), len(hit), len(fp), len(miss), sep="\t")

    pred = {b: classify(b, by_bid, texts) for b in best}
    print("\n== 최종 판정 ==")
    print("pred ", dict(Counter(pred.values())))
    print("correct", sum(truth[b] == pred[b] for b in best), "/", len(best))

    cols = ["MOIS_ACADEMIC", "MOIS_OTHER", "PPS", "LOCAL", "MOIS4", "UNSPECIFIED", "EXTRACT_FAIL", "NO_ATTACH"]
    rows = ["MOIS_ACADEMIC", "MOIS_OTHER", "PPS", "LOCAL", "UNSPECIFIED", "NO_ATTACH"]
    print("\n== 혼동 행렬 ==")
    print("truth\\pred\t" + "\t".join(cols) + "\ttotal")
    for r in rows:
        counts = [sum(1 for b in best if truth[b] == r and pred[b] == c) for c in cols]
        print(r + "\t" + "\t".join(map(str, counts)) + f"\t{sum(counts)}")
    print("total\t" + "\t".join(str(sum(1 for b in best if pred[b] == c)) for c in cols) + f"\t{sum(1 for b in best)}")

    print("\n== 불일치 ==")
    for b in sorted(best):
        if truth[b] != pred[b]:
            print(b, truth[b], pred[b], sep="\t")


if __name__ == "__main__":
    main()
```

실행 결과(이번 측정값)는 다음과 같습니다.

```text
rows 107 unique 87
files 181 ok 158 kinds {'hwp': 143, 'zip': 3, 'xlsx': 18, 'hwpx': 10, 'pdf': 7}
truth {'UNSPECIFIED': 8, 'NO_ATTACH': 12, 'MOIS_OTHER': 4, 'MOIS_ACADEMIC': 63}
pred  {'MOIS4': 2, 'UNSPECIFIED': 1, 'MOIS_ACADEMIC': 67, 'NO_ATTACH': 12, 'MOIS_OTHER': 4, 'EXTRACT_FAIL': 1}
correct 80 / 87
```

패턴별 적중·오탐은 다음과 같습니다.

| ID | 목표 갈래 | 매치 | 적중 | 오탐 | 미검출 |
| --- | --- | ---: | ---: | ---: | ---: |
| R1 | MOIS_ACADEMIC | 51 | 45 | 6 | 18 |
| R2 | MOIS_ACADEMIC | 30 | 30 | 0 | 33 |
| R3 | MOIS_ACADEMIC | 69 | 62 | 7 | 1 |
| R4 | MOIS_ACADEMIC | 30 | 30 | 0 | 33 |
| R5 | MOIS 공통 | 68 | 62 | 6 | 5 |
| R6 | PPS | 0 | 0 | 0 | 0 |
| R7 | PPS | 0 | 0 | 0 | 0 |
| R8 | MOIS4 | 2 | 0 | 2 | 0 |
| R9 | MOIS4 | 2 | 0 | 2 | 0 |
| R10 | LOCAL | 3 | 0 | 3 | 0 |
| R11 | LOCAL | 0 | 0 | 0 | 0 |
| R12 | MOIS_OTHER | 11 | 2 | 9 | 2 |
| R13 | 띠 문구 | 44 | 42 | 2 | 25 |

---

## 부록 B. 공고별 결과 전량

`첨부` 열은 내려받은 파일 수입니다. `정답` 은 2.1절 기준으로 원문을 읽어 확정한 값이고, `규칙` 은 부록 A `classify()` 결과입니다. 인용은 원문에서 80자 이내로 잘랐으며 모두 추출 텍스트의 부분 문자열임을 확인했습니다(추출 실패 1건 제외). 표는 공고번호 오름차순입니다.

| 공고번호 | 수요기관 | 공고일 | 정답 | 규칙 | 근거 인용(80자 이내) | 첨부 |
| --- | --- | --- | --- | --- | --- | ---: |
| R25BK00558057 | 강원특별자치도영월의료원 | 2025-01-07 | UNSPECIFIED | MOIS4 | 적격심사기준 : 일반용역 적격심사 세부기준 [학술연구용역 적격심사 기준을 적용 | 3 |
| R25BK00562329 | 강원특별자치도영월의료원 | 2025-01-07 | UNSPECIFIED | MOIS4 | 적격심사기준 : 일반용역 적격심사 세부기준 [학술연구용역 적격심사 기준을 적용 | 3 |
| R25BK00593514 | 경기도 화성시 | 2025-01-21 | NO_ATTACH | NO_ATTACH | (첨부 없음) | 0 |
| R25BK00599032 | 경기도 화성시 | 2025-01-23 | NO_ATTACH | NO_ATTACH | (첨부 없음) | 0 |
| R25BK00601627 | 경기도 화성시 | 2025-01-23 | MOIS_ACADEMIC | MOIS_ACADEMIC | [학술연구용역 적격심사 세부기준(추정가격이 2억원 미만 1억원 이상인 학술연구용역 평가기준)] | 2 |
| R25BK00606227 | 전남광주통합특별시 여수시 | 2025-02-03 | NO_ATTACH | NO_ATTACH | (첨부 없음) | 0 |
| R25BK00608073 | 제주특별자치도 | 2025-01-31 | MOIS_ACADEMIC | MOIS_ACADEMIC | 학술용역 적격심사 세부기준(행정안전부 예규)에 의거 『추정가격이 2억원 미만 1억원 이상 학술연구용역 적격심사 기준』 | 3 |
| R25BK00608905 | 충청남도 보령시 | 2025-01-31 | MOIS_ACADEMIC | MOIS_ACADEMIC | “학술연구용역 적격심사 세부기준”(행정안전부 예규)에 의거 【추정가격 2억미만 1억이상 용역】 | 3 |
| R25BK00609027 | 충청남도 보령시 | 2025-01-31 | MOIS_ACADEMIC | MOIS_ACADEMIC | “학술연구용역 적격심사 세부기준”(행정안전부 예규)에 의거 【추정가격 2억미만 1억이상 용역】 | 3 |
| R25BK00609576 | 인천환경공단 | 2025-02-04 | MOIS_OTHER | MOIS_OTHER | <별표 2> 사업수행능력평가(P.Q)를 하지 않는 기술용역에 따라 추정가격 2억원 미만 1억원 이상인 기술용역 평가기준 | 2 |
| R25BK00613676 | 경기도 성남시 | 2025-02-04 | MOIS_OTHER | MOIS_OTHER | [별표2] 사업수행능력 평가(P.Q)를 하지 않는 기술용역 4. 추정가격이 2억 원 미만 1억 원 이상인 기술용역의 평가 기준 | 3 |
| R25BK00620081 | 전남광주통합특별시 여수시 | 2025-02-05 | MOIS_ACADEMIC | MOIS_ACADEMIC | 기술․학술연구용역 적격심사세부기준[별표4] 학술연구용역 평가기준 추정가격이 2억원 미만 1억원 이상인 기준 | 3 |
| R25BK00629055 | 경기도 광주시 | 2025-02-14 | UNSPECIFIED | UNSPECIFIED | 취소사유 : 과업지시서 내용 누락(입찰참가자의 보유 기술인력 평가) | 1 |
| R25BK00633539 | 대전광역시 | 2025-02-11 | UNSPECIFIED | MOIS_ACADEMIC | 행정안전부 예규「지방자치단체 입찰시 낙찰자 결정기준」의 ‘기술․학술연구 용역 적격심사 세부기준’ | 2 |
| R25BK00646559 | 강원특별자치도 강릉시 | 2025-02-19 | NO_ATTACH | NO_ATTACH | (첨부 없음) | 0 |
| R25BK00646797 | 경기도교육청 경기도고양교육지원청 | 2025-02-18 | NO_ATTACH | NO_ATTACH | (첨부 없음) | 0 |
| R25BK00651689 | 남양주도시공사 | 2025-02-18 | MOIS_OTHER | MOIS_OTHER | [별표2]‘추정가격이 2억원 미만 1억원 이상인 기술용역의 평가기준’ | 3 |
| R25BK00654280 | 경기도 용인시 | 2025-02-18 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 기술·학술연구 용역 적격심사 세부기준 [별표4] 추정가격 2억원 미만 1억 이상 | 3 |
| R25BK00658333 | 강원특별자치도 강릉시 | 2025-02-19 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 기술·학술연구 용역 적격심사 세부기준 [별표4] 학술연구용역 추정가격이 2억 원 미만 1억 원 이상인 학술용역의 평가기준 | 2 |
| R25BK00660943 | 제주특별자치도 | 2025-02-20 | MOIS_ACADEMIC | MOIS_ACADEMIC | 학술용역 적격심사 세부기준(행정안전부 예규)에 의거 『추정가격이 2억원 미만 1억원 이상 학술연구용역 적격심사 기준』 | 3 |
| R25BK00664422 | 세종특별자치시 | 2025-02-21 | MOIS_ACADEMIC | MOIS_ACADEMIC | 기술·학술연구 용역 적격심사 세부기준 <별표4> 학술연구용역 평가기준 “추정가격 2억미만 1억이상” | 2 |
| R25BK00668071 | 경기도 양평군 | 2025-02-24 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 기술·학술연구 용역 적격심사 세부기준 [별표4] 학술·연구용역 평가기준 “추정가격 2억미만 1억이상” | 2 |
| R25BK00668734 | 충청남도 태안군 | 2025-02-26 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2「기술·학술연구용역 적격심사 세부기준」<별표4> 학술연구용역 평가기준 추정가격 2억 미만 1억이상 | 3 |
| R25BK00671447 | 부산광역시 | 2025-02-25 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 기술 ·학술연구 용역 적격심사 세부기준 제2장의2 [별표4] 추정가격 2억원 미만 1억원 이상을 적용 | 3 |
| R25BK00672163 | 경기도 광주시 | 2025-02-26 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 ‘기술·학술연구용역 적격심사 세부기준’ <별표 4> 추정가격 2억 미만 1억 이상인 학술연구용역 평가 기준 | 2 |
| R25BK00676684 | 충청북도 청주시 | 2025-02-27 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2기술·학술연구용역 적격심사 세부기준 〈별표4〉 “추정가격 2억미만 1억이상 적격심사 세부기준” | 2 |
| R25BK00680649 | 경상남도 함안군 | 2025-03-10 | NO_ATTACH | NO_ATTACH | (첨부 없음) | 0 |
| R25BK00695984 | 대구광역시 | 2025-03-12 | NO_ATTACH | NO_ATTACH | (첨부 없음) | 0 |
| R25BK00699158 | 경상남도 진주시 | 2025-03-10 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 기술·학술연구용역 적격심사 세부기준<별표4> [학술연구용역 평가기준] | 3 |
| R25BK00699246 | 경상남도 함안군 | 2025-03-10 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의 2 기술·학술연구용역 적격심사 세부기준 <별표4> 추정가격 2억원 미만 1억원 이상 기준 | 2 |
| R25BK00704741 | 대구광역시 | 2025-03-12 | MOIS_ACADEMIC | MOIS_ACADEMIC | “제2장의2 기술·학술 용역 적격심사 학술연구용역(추정가격이 2억원 미만 1억원 이상) 평가기준” | 2 |
| R25BK00706906 | 경상남도 거제시 | 2025-03-12 | MOIS_ACADEMIC | MOIS_ACADEMIC | [별표4] 추정가격 2억 미만 1억 이상인 학술연구용역의 평가기준을 적용 | 2 |
| R25BK00724566 | 충청남도 천안시 | 2025-03-18 | MOIS_ACADEMIC | MOIS_ACADEMIC | 행정안전부 예규) 학술연구용역 적격심사 세부기준 [별표4] “추정가격이 2억원 미만 1억원 이상인 학술용역의 평가기준” | 2 |
| R25BK00728491 | 충청남도 서천군 | 2025-03-26 | NO_ATTACH | NO_ATTACH | (첨부 없음) | 0 |
| R25BK00731622 | 전북특별자치도 정읍시 | 2025-03-20 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 기술 ·학술연구 용역 적격심사 세부기준 제2장의2 [별표4] 추정가격 2억원 미만 1억원 이상을 적용 | 2 |
| R25BK00733294 | 강원특별자치도 정선군 | 2025-03-21 | MOIS_ACADEMIC | MOIS_ACADEMIC | 학술연구용역 적격심사 세부기준(행정안전부 예규)에 따라 평가한 결과 종합평점이 85점 이상인 자 | 2 |
| R25BK00740552 | 전남광주통합특별시 광주청사 | 2025-03-25 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의 2 기술·학술연구 용역 적격심사 세부기준(행정안전부 예규)」별표 4. | 3 |
| R25BK00756020 | 경상남도 창원시 | 2025-04-01 | MOIS_ACADEMIC | MOIS_ACADEMIC | 지방자치단체 기술·학술연구 용역 적격심사 세부기준 [별표 4] 학술연구용역 평가기준 | 2 |
| R25BK00764185 | 충청남도 서천군 | 2025-04-03 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의 2 기술·학술연구 용역 적격심사 세부기준 [별표4] 학술연구용역 평가기준 | 2 |
| R25BK00764540 | 충청남도 태안군 | 2025-04-04 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2「기술·학술연구용역 적격심사 세부기준」<별표4> 학술연구용역 평가기준 추정가격 2억 미만 1억이상 | 3 |
| R25BK00764543 | 충청남도 태안군 | 2025-04-04 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2「기술·학술연구용역 적격심사 세부기준」<별표4> 학술연구용역 평가기준 추정가격 2억 미만 1억이상 | 3 |
| R25BK00764551 | 충청남도 태안군 | 2025-04-04 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2「기술·학술연구용역 적격심사 세부기준」<별표4> 학술연구용역 평가기준 추정가격 2억 미만 1억이상 | 3 |
| R25BK00798730 | 전남광주통합특별시 광주청사 | 2025-04-18 | MOIS_ACADEMIC | MOIS_ACADEMIC | [별표 4] 학술연구용역 평가기준 추정가격 2억미만 1억이상을 적용 | 2 |
| R25BK00804208 | 경기도 김포시 | 2025-04-28 | NO_ATTACH | NO_ATTACH | (첨부 없음) | 0 |
| R25BK00817387 | 경기도 평택시 | 2025-04-28 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 기술·학술연구 용역 적격심사 세부기준 <별표4> 추정가격 2억원 미만 1억원이상 기준 | 2 |
| R25BK00823744 | 경기도 김포시 | 2025-05-01 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 기술·학술연구용역 적격심사 세부기준<별표4> [학술연구용역 평가기준] | 3 |
| R25BK00825238 | 경기도 여주시 | 2025-05-01 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 기술․학술연구 용역 적격심사 세부기준 <별표4> 추정가격 2억미만 1억이상 기준 | 2 |
| R25BK00825399 | 인천광역시 | 2025-05-01 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 기술·학술연구 용역 적격심사 세부기준 [별표4] 학술연구용역 평가기준 | 2 |
| R25BK00830776 | 경기도 광주시 | 2025-05-07 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 ‘기술·학술연구용역 적격심사 세부기준’ <별표 4> 추정가격 2억 미만 1억 이상인 학술연구용역 평가 기준 | 2 |
| R25BK00842054 | 경기도 평택시 | 2025-05-13 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 기술·학술연구 용역 적격심사 세부기준 <별표4> 추정가격 2억원 미만 1억원이상 기준 | 2 |
| R25BK00846794 | 경기도 광주시 | 2025-05-15 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 ‘기술·학술연구용역 적격심사 세부기준’ <별표 4> 추정가격 2억 미만 1억 이상인 학술연구용역 평가 기준 | 2 |
| R25BK00855868 | 경상남도 함양군 | 2025-05-20 | MOIS_ACADEMIC | MOIS_ACADEMIC | 기술·학술연구용역 적격심사 세부기준> [학술연구용역 평가기준 4. 추정가격 2억원미만 1억원이상이상】 | 2 |
| R25BK00857686 | 전남광주통합특별시 광주청사 | 2025-05-20 | MOIS_ACADEMIC | MOIS_ACADEMIC | [별표 4] 학술연구용역 평가기준 추정가격 2억미만 1억이상을 적용 | 2 |
| R25BK00862330 | 경기도 광주시 | 2025-05-22 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 ‘기술·학술연구용역 적격심사 세부기준’ <별표 4> 추정가격 2억 미만 1억 이상인 학술연구용역 평가 기준 | 2 |
| R25BK00865748 | 세종특별자치시 | 2025-05-23 | MOIS_ACADEMIC | MOIS_ACADEMIC | 기술·학술연구 용역 적격심사 세부기준 <별표4> 학술연구용역 평가기준 “추정가격 2억미만 1억이상” | 2 |
| R25BK00874792 | 경기도 여주시 | 2025-05-28 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 기술․학술연구 용역 적격심사 세부기준 <별표4> 추정가격 2억미만 1억이상 기준 | 2 |
| R25BK00877268 | 충청북도 제천시 | 2025-05-29 | UNSPECIFIED | MOIS_ACADEMIC | 제2장의2 기술·학술연구 용역 적격심사 세부기준”에 의거 【추정가격 2억미만 1억이상 용역】 | 2 |
| R25BK00877509 | 충청북도 제천시 | 2025-05-29 | UNSPECIFIED | MOIS_ACADEMIC | 제2장의2 기술·학술연구 용역 적격심사 세부기준”에 의거 【추정가격 2억미만 1억이상 용역】 | 2 |
| R25BK00880281 | 대전광역시 | 2025-06-04 | UNSPECIFIED | MOIS_ACADEMIC | ‘기술․학술연구 용역 적격심사 세부기준’에 의거 예정가격 이하로서 최저가격(80.495%이상) | 2 |
| R25BK00889310 | 경상남도 진주시 | 2025-06-05 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 기술·학술연구용역 적격심사 세부기준<별표4> [학술연구용역 평가기준] | 3 |
| R25BK00927731 | 전남광주통합특별시 무안군 | 2025-06-25 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 기술·학술연구 용역 적격심사 세부기준【별표 4】 | 3 |
| R25BK00934697 | 서울교통공사 | 2025-06-30 | MOIS_ACADEMIC | MOIS_ACADEMIC | [별표 4. 학술연구용역 평가기준(추정가격 2억미만 1억이상) | 3 |
| R25BK00936613 | 전남광주통합특별시 광주청사 | 2025-07-01 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의 2 기술·학술연구 용역 적격심사 세부기준(행정안전부 예규)」 별표 4. | 3 |
| R25BK00936619 | 전남광주통합특별시 광주청사 | 2025-07-01 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의 2 기술·학술연구 용역 적격심사 세부기준(행정안전부 예규)」 별표 4. | 3 |
| R25BK00939573 | 전남광주통합특별시 신안군 | 2025-07-02 | MOIS_ACADEMIC | MOIS_ACADEMIC | 세부평가기준표는 [별표 4] 학술연구용역 적격심사 기준의 추정가격 2억미만 1억이상에 따릅니다 | 3 |
| R25BK00941539 | 경상북도 안동의료원 | 2025-07-03 | MOIS_ACADEMIC | MOIS_ACADEMIC | 【별표 4】학술연구용역(추정가격 1억원 이상 2억원 미만) 평가기준을 적용 | 3 |
| R25BK00952544 | 충청남도 아산시 | 2025-07-10 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 기술·학술연구 용역 적격심사 세부기준 [별표 4] 학술연구용역 평가기준 ‘추정가격 2억 미만 1억 이상 평가기준’ | 2 |
| R25BK00975718 | 경기도 시흥시 | 2025-07-23 | MOIS_ACADEMIC | MOIS_ACADEMIC | [별표 4] (추정가격이 2억 원 미만 1억 원 이상인 기술용역의 평가기준) | 3 |
| R25BK01004727 | 전남광주통합특별시 광주청사 | 2025-08-11 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의 2 기술·학술연구 용역 적격심사 세부기준(행정안전부 예규)」 별표 4. | 3 |
| R25BK01016608 | 충청남도 아산시 | 2025-08-19 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 기술·학술연구 용역 적격심사 세부기준 [별표 4] 학술연구용역 평가기준 ‘추정가격 2억 미만 1억 이상 평가기준’ | 2 |
| R25BK01016737 | 충청남도 아산시 | 2025-08-19 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 기술·학술연구 용역 적격심사 세부기준 [별표 4] 학술연구용역 평가기준 ‘추정가격 2억 미만 1억 이상 평가기준’ | 2 |
| R25BK01025566 | 전남광주통합특별시 강진군 | 2025-08-25 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 기술·학술연구 용역 적격심사 세부기준 [별표4]』(행정안전부 예규 제325호) | 3 |
| R25BK01038745 | 인천광역시 | 2025-09-02 | MOIS_OTHER | MOIS_OTHER | ‘제2장의2 기술용역 적격심사 세부기준’ 중 <별표2> 사업수행능력 평가(P.Q)를 하지 않는 기술용역 | 3 |
| R25BK01041705 | 전남광주통합특별시 광양시 | 2025-09-09 | NO_ATTACH | NO_ATTACH | (첨부 없음) | 0 |
| R25BK01041821 | 전남광주통합특별시 광양시 | 2025-09-09 | NO_ATTACH | NO_ATTACH | (첨부 없음) | 0 |
| R25BK01043518 | 전북특별자치도 남원시 | 2025-09-04 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 기술·학술연구 용역 적격심사 세부기준 [별표4] (행정안전부 예규 제325호) | 3 |
| R25BK01048089 | 경상남도 하동군 | 2025-09-08 | MOIS_ACADEMIC | MOIS_ACADEMIC | 학술연구용역 적격심사 세부기준(행정안전부 예규)에 따라 적격 심사하여 종합평점이 85점 이상인 자 | 2 |
| R25BK01052873 | 전남광주통합특별시 광양시 | 2025-09-10 | MOIS_ACADEMIC | MOIS_ACADEMIC | 학술연구용역 적격심사 세부기준(행정안전부 예규) 학술연구용역 적격심사 기준 추정가격이 2억 원 미만 1억 원 이상 | 3 |
| R25BK01052900 | 전남광주통합특별시 광양시 | 2025-09-10 | MOIS_ACADEMIC | MOIS_ACADEMIC | 학술연구용역 적격심사 세부기준(행정안전부 예규) 학술연구용역 적격심사 기준 추정가격이 2억 원 미만 1억 원 이상 | 3 |
| R25BK01085812 | 경상북도 영천시 | 2025-10-13 | MOIS_ACADEMIC | MOIS_ACADEMIC | 제2장의2 기술용역 적격심사 세부기준(별표4 : 학술연구용역 평가기준) 적용 | 2 |
| R25BK01094834 | 경상북도 상주시 | 2025-10-16 | MOIS_ACADEMIC | MOIS_ACADEMIC | 기술·학술연구용역 적격심사 세부기준> [학술연구용역 평가기준 4. 추정가격 2억원미만 1억원이상이상】 | 2 |
| R25BK01096038 | 경상북도 상주시 | 2025-10-16 | MOIS_ACADEMIC | MOIS_ACADEMIC | 기술·학술연구용역 적격심사 세부기준> [학술연구용역 평가기준 4. 추정가격 2억원미만 1억원이상이상】 | 2 |
| R25BK01097439 | 강원특별자치도삼척의료원 | 2025-10-17 | UNSPECIFIED | EXTRACT_FAIL | (추출 실패: 입찰공고.zip) | 1 |
| R25BK01108529 | 충청남도 홍성군 | 2025-10-23 | NO_ATTACH | NO_ATTACH | (첨부 없음) | 0 |
| R25BK01111217 | 충청남도 홍성군 | 2025-10-23 | MOIS_ACADEMIC | MOIS_ACADEMIC | [별표 4] 학술연구용역 평가기준』 적격심사 항목 및 배점한도에 의거 적격심사를 실시 | 3 |
| R25BK01115825 | 충청남도 천안시 | 2025-10-27 | MOIS_ACADEMIC | MOIS_ACADEMIC | 학술연구용역 적격심사 세부기준 [별표4] “추정가격이 2억원 미만 1억원 이상인 학술용역의 평가기준” | 2 |
| R25BK01130396 | 전남광주통합특별시 광양시 | 2025-11-03 | MOIS_ACADEMIC | MOIS_ACADEMIC | 학술연구용역 적격심사 세부기준(행정안전부 예규) 학술연구용역 적격심사 기준 추정가격이 2억 원 미만 1억 원 이상 | 2 |

---

## 부록 C. 검증

| 항목 | 값 |
| --- | --- |
| 변경 파일 | `docs/analysis/band_2to1_classifier_holdout_20261106.md` |
| 모집단 | 107행, 고유 공고번호 87건 |
| 첨부 다운로드 | 181파일, HTTP 실패 0건 |
| 텍스트 추출 | 181파일 중 158 성공, 23 실패 |
| 갈래 합계(정답) | 63 + 4 + 0 + 0 + 8 + 12 = 87 |
| 혼동 행렬 합계 | 87, 부록 B 행 수 87 과 일치 |
| 완전 일치 | 80/87(91.95%) |
| 검증 명령 | `uv run pytest tests/test_validate_doc_links.py -q`, `python3 scripts/validate_agent_rules.py --quiet` |
