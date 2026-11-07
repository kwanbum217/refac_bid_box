# 기관 규칙 판본·구간 축·매칭 결정 회귀 (D07·D08·D09·D22·D29)

> **작성일**: 2026-11-07
> **작업**: Orca Task `task_6de32c1c5fbf` (builder, Run `run_d3fa8d51ba74`)
> **정본 사양**: `.orca/capsules/task_inst_versions_20261107/capsule.yaml` (`ORCA_TASK_CAPSULE_V2`)
> **선행 문서**: [`decision_backlog_20261107.md`](decision_backlog_20261107.md) D07·D08·D09·D22·D29, [`inst_band_mismatch_13_20261107.md`](inst_band_mismatch_13_20261107.md), [`kdhc_krc_sources_20261107.md`](kdhc_krc_sources_20261107.md), [`not_computable_9_trace_20261107.md`](not_computable_9_trace_20261107.md), [`regime_lag_65_check_20261107.md`](regime_lag_65_check_20261107.md)
> **측정 창**: 2025-11-07 ~ 2026-11-07, 업무구분 `Servc`, 낙찰방법 코드 `낙030001`, 공고번호·업무구분별 최신 차수
> **판정**: candidate. 전수 판정 회귀에서 대상 집합 밖 판정 변화는 없습니다.
> **재현**: 6절

---

## 1. 요약

### 1.1 결정별 반영

| 결정 | 반영 내용 | 규칙 ID |
| --- | --- | --- |
| D07 (A) | 한국지역난방공사 2026-08-18판 11개 규칙을 새 ID 로 등록하고 2026-01-01판 11개 규칙을 `superseded_date="2026-08-18"` 로 끝냄. 2026-04-13판은 2026-01-01판과 값이 같아 별도 등록하지 않음 | `SERVC_INST_KDHC_20260818_*` |
| D08 (A) | 한국농어촌공사 별표 1·3·4·5의1·7·8 의 `5억원 미만` 밴드를 `고시금액` 경계로 둘로 나눠 k=4/2 반영 | `SERVC_INST_KRC_20260624_*` |
| D09 (A) | 판본마다 규칙 ID 를 두는 기존 방식을 유지 | 위와 같음 |
| D22 | 한국지역난방공사 2023-07-19판 별표 5 여객 육상운송용역 규칙 추가 | `SERVC_INST_KDHC_20230719_PASSENGER` |
| D29 (B) | 한국지역난방공사 지사·사업소 정확 코드 목록을 판본별 규칙 ID 전체로 확대. 이름 패턴·코드 대역은 쓰지 않음 | `INSTITUTION_RULE_EXACT_CODES` |

### 1.2 전수 판정 회귀 결과

| 항목 | 값 |
| --- | ---: |
| 비교 공고 수 | 31,325 |
| 판정(적용 범위·규칙 ID·차단 코드)이 바뀐 공고 | 60 |
| 그중 새로 차단된 공고 | 0 |
| 대상 집합 밖 판정 변화 | 0 |
| 변경 후 규칙 구간값 = 공고값 | 46 |
| 변경 후 규칙 구간값 != 공고값 | 14 (전부 건설폐기물, 공고값 우선이라 계산 결과 변화 없음) |

바뀐 60건은 모두 한국지역난방공사 본사·지사·사업소 공고입니다. 한국농어촌공사 5건은 규칙 ID 가 그대로이고 구간값만 바뀌므로 1.2의 판정 변경 수에 들어가지 않습니다(3.3절).

### 1.3 대상 집합 결과

| 묶음 | 대상 | 변경 | 규칙 구간값 = 공고값 | 남은 불일치 |
| --- | ---: | ---: | ---: | ---: |
| inst_band_mismatch_13 | 13 | 12 (KDHC 7 + KRC 5) | 12 | 1 (`R26BK01369593`, D10) |
| not_computable_9 KDHC 여객 | 1 | 1 | 1 | 0 |
| regime_lag_65 4.3 공기업 | 10 | 8 (KDHC 8) | 8 | 2 (KAC·KRC, 규칙 기본값 89.995 대 공고 87.995) |

`inst_band_mismatch_13` 의 한국농어촌공사 5건은 규칙 ID 가 바뀌지 않아 1.2의 60건에는 없지만, 구간값이 86.245에서 82.495로 바뀌어 공고값과 일치합니다.

---

## 2. 규칙 변경

### 2.1 한국지역난방공사 2026-08-18판 (D07·D09)

2026-08-18판 부칙은 `2026년 8월 18일부터 입찰공고되어 실시되는 용역계약의 적격심사 낙찰자 선정에 적용한다`이고 `일반용역적격심사세부기준(2026.04.13.)` 을 폐지합니다. 2026-04-13판 원문(`5da499190181...hwp`, sha256 `5da499190181ca34ff89eedd3d72880324401e4013d26482cc32c9d244a97066`)의 별표 3·4·8 값은 2026-01-01판과 같아 별도 규칙을 만들지 않았습니다.

| 별표 | service_type | B (5억원 이상/미만) | k (고시금액 이상/미만) | 기준비율 | 통과점수 | 하한율 (이상/미만) | 새 규칙 ID |
| --- | --- | --- | --- | ---: | ---: | --- | --- |
| 1 | ACADEMIC | 60 / 70 | 2 / 4 | 90 | 85 | 82.495 / 86.245 | `SERVC_INST_KDHC_20260818_ACADEMIC` |
| 2 | FACILITY | 60 / 70 | 5 | 93 | 85 | 89.995 | `SERVC_INST_KDHC_20260818_FACILITY` |
| 3 | SW | 60 / 70 | 2 / 4 | 90 | 85 | 82.495 / 86.245 | `SERVC_INST_KDHC_20260818_SW` |
| 3의2 | SW_SME | 60 / 70 | 4 | 91 | 88 | 87.995 | `SERVC_INST_KDHC_20260818_SW_TARGET` |
| 4 | WASTE | 60 / 70 | 2 / 4 | 90 | 85 | 82.495 / 86.245 | `SERVC_INST_KDHC_20260818_WASTE` |
| 5 | PASSENGER_TRANSPORT | 60 / 70 | 4 | 91 | 88 | 87.995 | `SERVC_INST_KDHC_20260818_PASSENGER` |
| 5의2 | FREIGHT | 60 / 70 | 2 / 4 | 90 | 85 | 82.495 / 86.245 | `SERVC_INST_KDHC_20260818_FREIGHT` |
| 6 | INSURANCE | 60 / 70 | 0.375 | 88 | 85 | 47.995 | `SERVC_INST_KDHC_20260818_INSURANCE` |
| 7 | REPAIR_INSPECTION | 60 / 70 | 2 / 4 | 90 | 85 | 82.495 / 86.245 | `SERVC_INST_KDHC_20260818_REPAIR` |
| 8 | LEASE | 70 | 2 / 4 | 90 | 85 | 82.495 / 86.245 | `SERVC_INST_KDHC_20260818_LEASE` |
| 9 | GENERAL | 50 / 80 | 2 / 4 | 90 | 85 | 82.495 / 86.245 | `SERVC_INST_KDHC_20260818_OTHER` |

- 근거: `docs/analysis/kdhc_krc_sources_20261107.md` 3.2.1(값 표), 3.2.2(원문 행·PDF 쪽), 4.1.
- 원문: 나라장터 공고 `R26BK01730527` 첨부 `5. 일반용역적격심사세부기준(260818).pdf`(sha256 `60ea20722555c39898dfc4ed07c11fc8d62259173a47aeb9a4285ff57c3beda0`, 912,748 bytes, 72쪽)와 `R26BK01793057` 첨부 HWP(sha256 `2b55300798d0be844c1dbd5ab17e35393b35e8efb931db7a1d9d201549495200`, 425,984 bytes).
- 2026-01-01판 11개 규칙은 `superseded_date="2026-08-18"` 로 끝냈습니다. 2026-08-17 까지는 2026-01-01판, 2026-08-18 부터는 2026-08-18판이 선택됩니다.
- 2026-08-18판 심사항목 배점표 명세가 없어 11개 규칙 모두 `quant_table=False` 로 두었습니다. 정량점수 직접 입력은 7.1절에 남깁니다.

### 2.2 한국농어촌공사 고시금액 축 (D08)

별표 1·3·4·5의1·7·8 은 배점한도 B 가 `추정가격 5억원 이상/미만` 두 열이고, 평점계수 k 가 `추정가격 고시금액 이상/미만` 두 행입니다. 기존 규칙은 5억원 미만 전체에 k=4 를 붙여 `5억원 미만·고시금액 이상` 칸을 86.245로 계산했습니다. 이번 변경으로 세 구간이 됩니다.

| 별표 | 구간 | B | k | 기준비율 | 통과점수 | 하한율 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1·3·4·5의1·7 | 고시금액 미만 | 70 | 4 | 90 | 85 | 86.245 |
| 1·3·4·5의1·7 | 고시금액 이상 5억원 미만 | 70 | 2 | 90 | 85 | 82.495 |
| 1·3·4·5의1·7 | 5억원 이상 | 60 | 2 | 90 | 85 | 82.495 |
| 8 | 고시금액 미만 | 70 | 4 | 90 | 85 | 86.245 |
| 8 | 고시금액 이상 5억원 미만 | 70 | 2 | 90 | 85 | 82.495 |
| 8 | 5억원 이상 | 70 | 2 | 90 | 85 | 82.495 |

- 근거: `docs/analysis/kdhc_krc_sources_20261107.md` 3.3.1(값 표), 3.3.2(원문 행), 3.5(하한율 대입).
- 원문: `data/sources/qualification/files/krc/47bd22d69013_일반용역 적격심사 세부기준(20260624).hwp`(sha256 `47bd22d690136e4716e3e00660b4e718544cbfdca0930a847541868ff66862c6`).
- 별표 2·3의1·5·6 은 k 가 단일이라 5억원 경계 둘만 유지합니다.

### 2.3 한국지역난방공사 2023-07-19판 여객 (D22)

| 항목 | 값 | 근거 |
| --- | --- | --- |
| 별표 | 5 여객 육상운송용역 | `inst_predecessor_attach_20261019.md` 4절 |
| B | 원문 미인쇄 (None) | 같은 절 54-59행 |
| k | 4 (단일) | 같은 절 57행 |
| 기준비율 | 91 | 같은 절 57행 |
| 가격점수 고정 구간 상한 투찰률 | 94% | 같은 절 57행 |
| 통과점수 | 88 | 같은 절 61행, `not_computable_9_trace_20261107.md` 3.2 |
| 낙찰하한율 | 원문 미인쇄, 계산값 87.995 (91-(100-88)/4=88.0, 0.005 차감) | `kdhc_krc_sources_20261107.md` 3.5, 공고 `R25BK01166116` 인쇄값 87.995 |

- 규칙 ID `SERVC_INST_KDHC_20230719_PASSENGER`, 시행 2023-07-19, `superseded_date="2026-01-01"`.
- 원문: 나라장터 공고 `R25BK01166116` 첨부 `4. 일반용역 적격심사세부기준(개정전문).hwp`(sha256 `132ff7b89ba5fdd782f3316bbe6d2dfdb156987c822826516643e549f8ee697b`, 409,600 bytes).

### 2.4 공기업 지사·사업소 코드 매칭 (D29)

한국지역난방공사 지사·사업소 정확 코드 목록에 다음 3개를 더했습니다.

| 코드 | 수요기관명 | 근거 |
| --- | --- | --- |
| `D325103` | 한국지역난방공사 청주지사 | `regime_lag_65_check_20261107.md` 3.1, 읽기 전용 DB 조회 |
| `D325105` | 한국지역난방공사 광주전남지사 | 같은 문서 3.1·3.2, 읽기 전용 DB 조회 |
| `D325117` | 한국지역난방공사 양산지사 | 같은 문서 3.1, 읽기 전용 DB 조회 |

- 기존 12개(`D325102`, `D325104`, `D325107`, `D325109`, `D325112`, `D325114`, `D325115`, `D325116`, `D325150`, `D325152`, `D325156`, `D325160`)와 합쳐 15개입니다.
- 이 목록을 2023-07-19판 3개, 2026-01-01판 11개, 2026-08-18판 11개 규칙 ID 전체에 붙였습니다. 이름 접두·코드 대역은 쓰지 않습니다.
- 지사 코드로만 걸린 후보 가운데 아직 시행되지 않은 판본은 `_select_institution_rule` 에서 후보에서 뺍니다. 그래야 2026-01-01판 이전 지사 공고가 새 판본과 코드만 맞아 `RULE_REGIME_MISMATCH` 로 뒤집히지 않습니다. 본청 코드·이름으로 직접 맞은 기관은 종전처럼 시행일 대조에서 차단합니다(시행일 불일치 차단 유지).
- 한국공항공사 김포공항(`Z013741`, `R26BK01565307`)과 한국농어촌공사 토지개발사업단(`D151901`, `R26BK01585377`)은 코드를 넣지 않았습니다. 두 공고일(2026-06-08, 2026-06-16)에 적용되는 기관 판본은 각각 2026-03-02판 시설분야와 2025-10-01판 시설분야인데, 이 판본의 시설분야 값이 이번 작업의 원문 범위에 없습니다. 코드만 넣으면 2026-08-14판·2026-06-24판이 선택되어 `RULE_REGIME_MISMATCH` 가 되므로, 규칙 ID 귀속은 PPS 기본값을 유지했습니다. 두 건 모두 공고값 우선으로 계산 결과는 87.995 그대로입니다.

---

## 3. 전수 판정 회귀

### 3.1 방법

`scripts/report_rule_coverage.py` 의 `collect_records(months=12, category="Servc", method_code="낙030001", today=date(2026, 11, 7))` 를 메모리에서 돌리고, `_to_record` 를 감싸 `bid_ntce_no-bid_ntce_ord` 키를 붙였습니다. 판정 축은 `classify_result` 의 `applied_scope`·`rule_id`·`block_code` 입니다. DB 세션은 `collect_records` 가 여는 `SET SESSION TRANSACTION READ ONLY` 를 그대로 썼고, 파일·DB 쓰기는 없습니다.

- 비교 공고: 31,325건
- 변경 전 스냅샷과 변경 후 스냅샷의 키 집합은 같습니다.
- 변경 60건, 전부 한국지역난방공사(본사 8, 지사·사업소 52)입니다.
- 새로 차단된 공고는 0건입니다. 변경 전 차단 1건(`R25BK01166116`, `RULE_REGIME_MISMATCH`)은 해소되었습니다.

### 3.2 판정이 바뀐 공고 60건

| # | 공고번호(차수) | 공고일 | 수요기관(코드) | 변경 전 | 변경 후 | 규칙 구간값 | 공고값 | 일치 |
| ---: | --- | --- | --- | --- | --- | ---: | ---: | :---: |
| 1 | `R25BK01166116`(000) | 2025-11-19 | 한국지역난방공사(B550373) | BLOCKED/RULE_REGIME_MISMATCH | INSTITUTION/SERVC_INST_KDHC_20230719_PASSENGER | 87.995 | 87.995 | O |
| 2 | `R25BK01203258`(000) | 2025-12-04 | 한국지역난방공사 대구지사(D325102) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_09 | INSTITUTION/SERVC_INST_KDHC_20230719_WASTE | 80.495 | 80.495 | O |
| 3 | `R25BK01228334`(000) | 2025-12-15 | 한국지역난방공사 서울중앙지사(D325109) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_03 | INSTITUTION/SERVC_INST_KDHC_20230719_PASSENGER | 87.995 | 87.995 | O |
| 4 | `R26BK01279112`(000) | 2026-01-16 | 한국지역난방공사 강남지사(D325150) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260101_REPAIR | 84.245 | 84.245 | O |
| 5 | `R26BK01295288`(000) | 2026-01-26 | 한국지역난방공사 강남지사(D325150) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260101_REPAIR | 84.245 | 84.245 | O |
| 6 | `R26BK01319275`(000) | 2026-02-05 | 한국지역난방공사 양산지사(D325117) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260101_REPAIR | 84.245 | 84.245 | O |
| 7 | `R26BK01320348`(000) | 2026-02-05 | 한국지역난방공사 광주전남지사(D325105) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260101_REPAIR | 84.245 | 84.245 | O |
| 8 | `R26BK01335678`(000) | 2026-02-12 | 한국지역난방공사 서울중앙지사(D325109) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260101_REPAIR | 84.245 | 84.245 | O |
| 9 | `R26BK01339430`(000) | 2026-02-13 | 한국지역난방공사 광주전남지사(D325105) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260101_REPAIR | 84.245 | 84.245 | O |
| 10 | `R26BK01339675`(000) | 2026-02-13 | 한국지역난방공사 광주전남지사(D325105) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_01 | INSTITUTION/SERVC_INST_KDHC_20260101_FACILITY | 87.995 | 87.995 | O |
| 11 | `R26BK01358920`(000) | 2026-02-26 | 한국지역난방공사 광주전남지사(D325105) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_01 | INSTITUTION/SERVC_INST_KDHC_20260101_FACILITY | 87.995 | 87.995 | O |
| 12 | `R26BK01360583`(000) | 2026-02-27 | 한국지역난방공사 광주전남지사(D325105) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_01 | INSTITUTION/SERVC_INST_KDHC_20260101_FACILITY | 87.995 | 87.995 | O |
| 13 | `R26BK01394326`(000) | 2026-03-13 | 한국지역난방공사 대구지사(D325102) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_01 | INSTITUTION/SERVC_INST_KDHC_20260101_FACILITY | 87.995 | 87.995 | O |
| 14 | `R26BK01397306`(000) | 2026-03-16 | 한국지역난방공사 대구지사(D325102) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_03 | INSTITUTION/SERVC_INST_KDHC_20260101_PASSENGER | 87.995 | 87.995 | O |
| 15 | `R26BK01399835`(001) | 2026-03-19 | 한국지역난방공사 양산지사(D325117) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_08 | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | 84.245 | 84.245 | O |
| 16 | `R26BK01408405`(000) | 2026-03-19 | 한국지역난방공사 양산지사(D325117) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_08 | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | 84.245 | 84.245 | O |
| 17 | `R26BK01408776`(000) | 2026-03-19 | 한국지역난방공사 동탄지사(D325152) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_01 | INSTITUTION/SERVC_INST_KDHC_20260101_FACILITY | 87.995 | 87.995 | O |
| 18 | `R26BK01424140`(000) | 2026-03-26 | 한국지역난방공사 청주지사(D325103) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260101_REPAIR | 84.245 | 84.245 | O |
| 19 | `R26BK01426219`(000) | 2026-03-27 | 한국지역난방공사 화성지사(D325156) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_01 | INSTITUTION/SERVC_INST_KDHC_20260101_FACILITY | 87.995 | 87.995 | O |
| 20 | `R26BK01494599`(000) | 2026-04-28 | 한국지역난방공사 김해사업소(D325107) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_08 | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | 84.245 | 84.245 | O |
| 21 | `R26BK01542739`(000) | 2026-05-26 | 한국지역난방공사 강남지사(D325150) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260101_REPAIR | 84.245 | 84.245 | O |
| 22 | `R26BK01560111`(000) | 2026-06-04 | 한국지역난방공사 강남지사(D325150) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260101_REPAIR | 84.245 | 84.245 | O |
| 23 | `R26BK01583538`(000) | 2026-06-16 | 한국지역난방공사 김해사업소(D325107) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_04 | INSTITUTION/SERVC_INST_KDHC_20260101_SW_TARGET | 87.995 | 87.995 | O |
| 24 | `R26BK01589006`(000) | 2026-06-18 | 한국지역난방공사 양산지사(D325117) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_01 | INSTITUTION/SERVC_INST_KDHC_20260101_FACILITY | 87.995 | 87.995 | O |
| 25 | `R26BK01589351`(000) | 2026-06-18 | 한국지역난방공사 청주지사(D325103) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_01 | INSTITUTION/SERVC_INST_KDHC_20260101_FACILITY | 87.995 | 87.995 | O |
| 26 | `R26BK01596070`(000) | 2026-06-22 | 한국지역난방공사 삼송지사(D325115) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_01 | INSTITUTION/SERVC_INST_KDHC_20260101_FACILITY | 87.995 | 87.995 | O |
| 27 | `R26BK01599265`(000) | 2026-06-24 | 한국지역난방공사 양산지사(D325117) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_01 | INSTITUTION/SERVC_INST_KDHC_20260101_FACILITY | 87.995 | 87.995 | O |
| 28 | `R26BK01607658`(000) | 2026-06-29 | 한국지역난방공사 양산지사(D325117) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_01 | INSTITUTION/SERVC_INST_KDHC_20260101_FACILITY | 87.995 | 87.995 | O |
| 29 | `R26BK01621293`(000) | 2026-07-07 | 한국지역난방공사 동탄지사(D325152) | PPS_DEFAULT/SERVC_QUAL_MOE_CDW_ATTACH_04 | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | 84.245 | 87.745 | X |
| 30 | `R26BK01624792`(000) | 2026-07-09 | 한국지역난방공사 김해사업소(D325107) | PPS_DEFAULT/SERVC_QUAL_MOE_CDW_ATTACH_04 | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | 84.245 | 87.745 | X |
| 31 | `R26BK01629748`(000) | 2026-07-13 | 한국지역난방공사 강남지사(D325150) | PPS_DEFAULT/SERVC_QUAL_MOE_CDW_ATTACH_03 | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | 84.245 | 86.745 | X |
| 32 | `R26BK01631533`(000) | 2026-07-14 | 한국지역난방공사 대구지사(D325102) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260101_REPAIR | 84.245 | 84.245 | O |
| 33 | `R26BK01633123`(000) | 2026-07-14 | 한국지역난방공사 세종지사(D325104) | PPS_DEFAULT/SERVC_QUAL_MOE_CDW_ATTACH_04 | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | 84.245 | 87.745 | X |
| 34 | `R26BK01633356`(000) | 2026-07-14 | 한국지역난방공사 화성지사(D325156) | PPS_DEFAULT/SERVC_QUAL_MOE_CDW_ATTACH_04 | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | 84.245 | 87.745 | X |
| 35 | `R26BK01633843`(000) | 2026-07-15 | 한국지역난방공사 삼송지사(D325115) | PPS_DEFAULT/SERVC_QUAL_MOE_CDW_ATTACH_04 | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | 84.245 | 87.745 | X |
| 36 | `R26BK01638207`(000) | 2026-07-16 | 한국지역난방공사 서울중앙지사(D325109) | PPS_DEFAULT/SERVC_QUAL_MOE_CDW_ATTACH_04 | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | 84.245 | 87.745 | X |
| 37 | `R26BK01644144`(000) | 2026-07-22 | 한국지역난방공사 평택지사(D325160) | PPS_DEFAULT/SERVC_QUAL_MOE_CDW_ATTACH_04 | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | 84.245 | 87.745 | X |
| 38 | `R26BK01645094`(000) | 2026-07-22 | 한국지역난방공사 수원사업소(D325112) | PPS_DEFAULT/SERVC_QUAL_MOE_CDW_ATTACH_04 | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | 84.245 | 87.745 | X |
| 39 | `R26BK01648695`(000) | 2026-07-24 | 한국지역난방공사 대구지사(D325102) | PPS_DEFAULT/SERVC_QUAL_MOE_CDW_ATTACH_04 | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | 84.245 | 87.745 | X |
| 40 | `R26BK01649356`(000) | 2026-07-24 | 한국지역난방공사 청주지사(D325103) | PPS_DEFAULT/SERVC_QUAL_MOE_CDW_ATTACH_04 | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | 84.245 | 87.745 | X |
| 41 | `R26BK01649977`(000) | 2026-07-24 | 한국지역난방공사 동탄지사(D325152) | PPS_DEFAULT/SERVC_QUAL_MOE_CDW_ATTACH_04 | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | 84.245 | 87.745 | X |
| 42 | `R26BK01655100`(000) | 2026-07-28 | 한국지역난방공사 판교지사(D325114) | PPS_DEFAULT/SERVC_QUAL_MOE_CDW_ATTACH_04 | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | 84.245 | 87.745 | X |
| 43 | `R26BK01656148`(000) | 2026-07-29 | 한국지역난방공사 광주전남지사(D325105) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_01 | INSTITUTION/SERVC_INST_KDHC_20260101_FACILITY | 87.995 | 87.995 | O |
| 44 | `R26BK01656556`(000) | 2026-07-29 | 한국지역난방공사 서울중앙지사(D325109) | PPS_DEFAULT/SERVC_QUAL_MOE_CDW_ATTACH_04 | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | 84.245 | 87.745 | X |
| 45 | `R26BK01660419`(000) | 2026-07-31 | 한국지역난방공사 강남지사(D325150) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260101_REPAIR | 84.245 | 84.245 | O |
| 46 | `R26BK01674466`(000) | 2026-08-10 | 한국지역난방공사 강남지사(D325150) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260101_REPAIR | 84.245 | 84.245 | O |
| 47 | `R26BK01681756`(000) | 2026-08-13 | 한국지역난방공사 대구지사(D325102) | PPS_DEFAULT/SERVC_QUAL_POST_20260727_ATTACH_03 | INSTITUTION/SERVC_INST_KDHC_20260101_PASSENGER | 87.995 | 87.995 | O |
| 48 | `R26BK01708025`(000) | 2026-09-01 | 한국지역난방공사 수원사업소(D325112) | INSTITUTION/SERVC_INST_KDHC_20260101_OTHER | INSTITUTION/SERVC_INST_KDHC_20260818_OTHER | 82.495 | 82.495 | O |
| 49 | `R26BK01730527`(001) | 2026-09-22 | 한국지역난방공사(B550373) | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | INSTITUTION/SERVC_INST_KDHC_20260818_WASTE | 82.495 | 82.495 | O |
| 50 | `R26BK01745985`(000) | 2026-09-28 | 한국지역난방공사(B550373) | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | INSTITUTION/SERVC_INST_KDHC_20260818_WASTE | 82.495 | 82.495 | O |
| 51 | `R26BK01747872`(000) | 2026-09-29 | 한국지역난방공사 화성지사(D325156) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260818_REPAIR | 86.245 | 86.245 | O |
| 52 | `R26BK01761398`(000) | 2026-10-07 | 한국지역난방공사(B550373) | INSTITUTION/SERVC_INST_KDHC_20260101_LEASE | INSTITUTION/SERVC_INST_KDHC_20260818_LEASE | 82.495 | 82.495 | O |
| 53 | `R26BK01764999`(000) | 2026-10-12 | 한국지역난방공사(B550373) | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | INSTITUTION/SERVC_INST_KDHC_20260818_WASTE | 82.495 | 82.495 | O |
| 54 | `R26BK01766196`(000) | 2026-10-12 | 한국지역난방공사(B550373) | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | INSTITUTION/SERVC_INST_KDHC_20260818_WASTE | 82.495 | 82.495 | O |
| 55 | `R26BK01792264`(000) | 2026-10-26 | 한국지역난방공사 김해사업소(D325107) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260818_REPAIR | 86.245 | 86.245 | O |
| 56 | `R26BK01793057`(000) | 2026-10-27 | 한국지역난방공사(B550373) | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | INSTITUTION/SERVC_INST_KDHC_20260818_WASTE | 82.495 | 82.495 | O |
| 57 | `R26BK01793122`(000) | 2026-10-27 | 한국지역난방공사 서울중앙지사(D325109) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260818_REPAIR | 86.245 | 86.245 | O |
| 58 | `R26BK01798610`(000) | 2026-10-29 | 한국지역난방공사 수원사업소(D325112) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_01 | INSTITUTION/SERVC_INST_KDHC_20260818_FACILITY | 89.995 | 89.995 | O |
| 59 | `R26BK01812771`(000) | 2026-11-05 | 한국지역난방공사 광주전남지사(D325105) | PPS_DEFAULT/SERVC_QUAL_POST_20260727_ATTACH_03 | INSTITUTION/SERVC_INST_KDHC_20260818_PASSENGER | 87.995 | 87.995 | O |
| 60 | `R26BK01813749`(000) | 2026-11-05 | 한국지역난방공사(B550373) | INSTITUTION/SERVC_INST_KDHC_20260101_SW | INSTITUTION/SERVC_INST_KDHC_20260818_SW | 82.495 | 82.495 | O |

### 3.3 기관별 집계

| 기관(코드) | 변경 | 규칙값 = 공고값 | 규칙값 != 공고값 |
| --- | ---: | ---: | ---: |
| 한국지역난방공사(B550373) | 8 | 8 | 0 |
| 한국지역난방공사 강남지사(D325150) | 7 | 7 | 0 |
| 한국지역난방공사 광주전남지사(D325105) | 7 | 7 | 0 |
| 한국지역난방공사 대구지사(D325102) | 6 | 6 | 0 |
| 한국지역난방공사 양산지사(D325117) | 6 | 6 | 0 |
| 한국지역난방공사 서울중앙지사(D325109) | 5 | 4 | 1 |
| 한국지역난방공사 김해사업소(D325107) | 4 | 3 | 1 |
| 한국지역난방공사 동탄지사(D325152) | 3 | 1 | 2 |
| 한국지역난방공사 수원사업소(D325112) | 3 | 3 | 0 |
| 한국지역난방공사 청주지사(D325103) | 3 | 2 | 1 |
| 한국지역난방공사 화성지사(D325156) | 3 | 2 | 1 |
| 한국지역난방공사 삼송지사(D325115) | 2 | 1 | 1 |
| 한국지역난방공사 세종지사(D325104) | 1 | 0 | 1 |
| 한국지역난방공사 판교지사(D325114) | 1 | 0 | 1 |
| 한국지역난방공사 평택지사(D325160) | 1 | 0 | 1 |
| **합계** | **60** | **46** | **14** |

규칙값 != 공고값 14건은 모두 건설폐기물처리용역입니다. KDHC 별표 4 구간값은 84.245이고 공고는 환경부 고시 값을 87.745(일부 86.745)로 인쇄합니다. 공고값 우선 원칙에 따라 유효 하한율은 공고값 그대로이며 계산 결과는 바뀌지 않습니다. 규칙 귀속(환경부 고시 대 KDHC 별표 4)은 이번 결정 범위 밖입니다.

### 3.4 inst_band_mismatch_13 (13건)

| # | 공고번호 | 기관 | 변경 후 규칙 | 규칙값 | 공고값 | 일치 |
| ---: | --- | --- | --- | ---: | ---: | :---: |
| 1 | `R26BK01369593` | 한국지역난방공사 | `SERVC_INST_KDHC_20260101_WASTE` | 84.245 | 87.745 | X |
| 2 | `R26BK01634862` | 한국농어촌공사 | `SERVC_INST_KRC_20260624_LEASE` | 82.495 | 82.495 | O |
| 3 | `R26BK01730527` | 한국지역난방공사 | `SERVC_INST_KDHC_20260818_WASTE` | 82.495 | 82.495 | O |
| 4 | `R26BK01745985` | 한국지역난방공사 | `SERVC_INST_KDHC_20260818_WASTE` | 82.495 | 82.495 | O |
| 5 | `R26BK01761398` | 한국지역난방공사 | `SERVC_INST_KDHC_20260818_LEASE` | 82.495 | 82.495 | O |
| 6 | `R26BK01764999` | 한국지역난방공사 | `SERVC_INST_KDHC_20260818_WASTE` | 82.495 | 82.495 | O |
| 7 | `R26BK01766196` | 한국지역난방공사 | `SERVC_INST_KDHC_20260818_WASTE` | 82.495 | 82.495 | O |
| 8 | `R26BK01764484` | 한국농어촌공사 | `SERVC_INST_KRC_20260624_ACADEMIC` | 82.495 | 82.495 | O |
| 9 | `R26BK01768949` | 한국농어촌공사 | `SERVC_INST_KRC_20260624_ACADEMIC` | 82.495 | 82.495 | O |
| 10 | `R26BK01784481` | 한국농어촌공사 | `SERVC_INST_KRC_20260624_ACADEMIC` | 82.495 | 82.495 | O |
| 11 | `R26BK01793057` | 한국지역난방공사 | `SERVC_INST_KDHC_20260818_WASTE` | 82.495 | 82.495 | O |
| 12 | `R26BK01793641` | 한국농어촌공사 | `SERVC_INST_KRC_20260624_ACADEMIC` | 82.495 | 82.495 | O |
| 13 | `R26BK01813749` | 한국지역난방공사 | `SERVC_INST_KDHC_20260818_SW` | 82.495 | 82.495 | O |

- 12/13 일치. 남은 1건은 D10(낙찰방법명에 세부유형이 없어 공고명으로 유형 추론)이며 이번 결정 범위 밖입니다.
- 한국농어촌공사 5건은 규칙 ID 가 그대로이고 밴드값만 86.245에서 82.495로 바뀌었습니다. 3.1의 판정 축(규칙 ID)이 바뀌지 않아 60건 표에는 없습니다.

### 3.5 not_computable_9 (9건)

| 공고번호 | 변경 전 | 변경 후 | 비고 |
| --- | --- | --- | --- |
| `R25BK01166116` | BLOCKED/RULE_REGIME_MISMATCH | INSTITUTION/`SERVC_INST_KDHC_20230719_PASSENGER` | D22 로 해소, 규칙값·공고값 87.995 일치 |
| `R25BK01139979` | BLOCKED/RULE_NOT_FOUND | 변화 없음 | 범위 밖 |
| `R25BK01197545` | BLOCKED/RULE_NOT_FOUND | 변화 없음 | 범위 밖 |
| `R26BK01310604` | BLOCKED/RULE_NOT_FOUND | 변화 없음 | 범위 밖 |
| `R26BK01345718` | BLOCKED/RULE_NOT_FOUND | 변화 없음 | 범위 밖 |
| `R26BK01372508` | BLOCKED/RULE_REGIME_MISMATCH | 변화 없음 | 범위 밖 |
| `R26BK01375736` | BLOCKED/RULE_REGIME_MISMATCH | 변화 없음 | 범위 밖 |
| `R26BK01560778` | BLOCKED/RULE_NOT_FOUND | 변화 없음 | 범위 밖 |
| `R26BK01577453` | BLOCKED/RULE_NOT_FOUND | 변화 없음 | 범위 밖 |

### 3.6 regime_lag_65 4.3 공기업 (10건)

| 공고번호 | 기관 | 변경 후 규칙 | 규칙값 | 공고값 | 일치 |
| --- | --- | --- | ---: | ---: | :---: |
| `R26BK01589006` | 한국지역난방공사 양산지사 | `SERVC_INST_KDHC_20260101_FACILITY` | 87.995 | 87.995 | O |
| `R26BK01589351` | 한국지역난방공사 청주지사 | `SERVC_INST_KDHC_20260101_FACILITY` | 87.995 | 87.995 | O |
| `R26BK01596070` | 한국지역난방공사 삼송지사 | `SERVC_INST_KDHC_20260101_FACILITY` | 87.995 | 87.995 | O |
| `R26BK01599265` | 한국지역난방공사 양산지사 | `SERVC_INST_KDHC_20260101_FACILITY` | 87.995 | 87.995 | O |
| `R26BK01607658` | 한국지역난방공사 양산지사 | `SERVC_INST_KDHC_20260101_FACILITY` | 87.995 | 87.995 | O |
| `R26BK01656148` | 한국지역난방공사 광주전남지사 | `SERVC_INST_KDHC_20260101_FACILITY` | 87.995 | 87.995 | O |
| `R26BK01681756` | 한국지역난방공사 대구지사 | `SERVC_INST_KDHC_20260101_PASSENGER` | 87.995 | 87.995 | O |
| `R26BK01812771` | 한국지역난방공사 광주전남지사 | `SERVC_INST_KDHC_20260818_PASSENGER` | 87.995 | 87.995 | O |
| `R26BK01565307` | 한국공항공사 김포공항 | `SERVC_QUAL_POST_20260526_ATTACH_01` | 89.995 | 87.995 | X |
| `R26BK01585377` | 한국농어촌공사 토지개발사업단 | `SERVC_QUAL_POST_20260526_ATTACH_01` | 89.995 | 87.995 | X |

- 8/10 일치. KAC·KRC 2건은 규칙 ID 가 PPS 기본값 그대로이고, `공고 하한율(87.995%)이 별표 기본값(89.995%)과 일치하지 않아 공고 하한율을 우선 적용합니다` 경고가 남습니다. 유효 하한율은 공고값 87.995입니다(2.4절).

---

## 4. 대상 집합 밖 판정 변화

없습니다.

- 60건 모두 한국지역난방공사 본사·지사·사업소 공고입니다.
- 다른 기관(한국농어촌공사·한국공항공사 포함)의 적용 범위·규칙 ID·차단 코드는 바뀌지 않았습니다.
- 2026-01-01판 이전 지사 공고 10건은 지사 코드가 새로 붙기 전과 같이 PPS 기본값을 유지합니다. 2.4절의 시행 전 판본 제외 규칙 때문입니다.
- 새로 차단된 공고는 0건입니다.

---

## 5. 기존 시험 단언 변경

| 파일 | 위치 | 변경 전 | 변경 후 | 이유 |
| --- | --- | --- | --- | --- |
| `tests/test_institution_rules.py` | 186행 | `assert code_total == 137` | `assert code_total == 143` | D08 로 한국농어촌공사 6개 별표에 구간이 6개 늘었습니다. YAML·코드 구간 수를 함께 맞췄습니다. |
| `tests/test_evaluation_quant_institution.py` | 50행 | `KDHC_NO_TABLE_IDS = ("SERVC_INST_KDHC_20230719_WASTE",)` | 2026-08-18판 11개 ID 추가 | D07 로 새 규칙 ID 가 생겼고 2026-08-18판 배점표 명세가 없어 `quant_table=False`(정량점수 직접 입력)입니다. |
| `tests/test_evaluation_rules_split_invariance.py` | 43행 | `"INSTITUTION_RULES": "d7cabe0e33a1e8cf"` | `"8a8c340f61ca94b1"` | D07·D08·D22·D29 로 기관 규칙 벌이 의도적으로 바뀌었습니다. 다른 규칙 상수 지문과 `list_all_rules()` 지문은 그대로입니다. |
| `tests/test_institution_rules.py` | `test_kac_subunit_alias_matches_only_without_code` | 코드 `Z013741` 이면 기관 규칙 미선택 | 변경 없음 | D29 는 지사·사업소(한국지역난방공사)만 넓혔고 한국공항공사 코드는 넣지 않았습니다. 2.4절 이유. |

새 시험 `tests/test_inst_versions_20261107.py` 는 (a) 2026-08-18 경계, (b) 농어촌 고시금액 축, (c) 2023-07-19 여객, (d) 지사 코드 매칭, (e) 목록 밖 코드 미매칭을 단언합니다. 기존 `tests/test_kdhc_band_axis.py`, `tests/test_kdhc_predecessor.py`, `tests/test_rule_not_found_32_fix.py` 는 단언을 바꾸지 않고 통과합니다.

---

## 6. 새 상수 근거

| 대상 | 값 | 원문·문서 근거 |
| --- | --- | --- |
| KDHC 2026-08-18 별표 1·3·4·5의2·7 | B 60/70, k 2/4, 기준 90, T 85, 하한 82.495/86.245 | `kdhc_krc_sources_20261107.md` 3.2.1·3.2.2, PDF 18·24·28·34·38쪽 |
| KDHC 2026-08-18 별표 2 | B 60/70, k 5, 기준 93, T 85, 하한 89.995 | 같은 문서 3.2.1, PDF 21쪽 |
| KDHC 2026-08-18 별표 3의2·5 | B 60/70, k 4, 기준 91, T 88, 하한 87.995 | 같은 문서 3.2.1, PDF 26·31쪽 |
| KDHC 2026-08-18 별표 6 | B 60/70, k 0.375, 기준 88, T 85, 하한 47.995 | 같은 문서 3.2.1, PDF 36쪽 |
| KDHC 2026-08-18 별표 8 | B 70, k 2/4, 기준 90, T 85, 하한 82.495/86.245 | 같은 문서 3.2.1, PDF 41쪽 |
| KDHC 2026-08-18 별표 9 | B 50/80, k 2/4, 기준 90, T 85, 하한 82.495/86.245 | 같은 문서 3.2.1, PDF 43쪽 |
| KDHC 2023-07-19 별표 5 | B 미인쇄, k 4, 기준 91, 상한 투찰률 94, T 88, 하한 87.995(계산) | `inst_predecessor_attach_20261019.md` 4절 54-61행, `not_computable_9_trace_20261107.md` 3.2, `kdhc_krc_sources_20261107.md` 3.5 |
| KRC 별표 1·3·4·5의1·7 | B 60/70, k 4(고시금액 미만)/2(이상), 기준 90, T 85, 하한 86.245/82.495 | `kdhc_krc_sources_20261107.md` 3.3.1·3.3.2·3.5, `servc_formula_userfiles_agency_20261004.md:4.2` |
| KRC 별표 8 | B 70, k 4(고시금액 미만)/2(이상), 기준 90, T 85, 하한 86.245/82.495 | 같은 문서 3.3.1·3.3.2·3.5 |
| KDHC 지사 코드 `D325103`·`D325105`·`D325117` | 명시 코드 | `regime_lag_65_check_20261107.md` 3.1·3.2, `uv run python scripts/db_readonly_query.py` 읽기 전용 조회 |
| 고시금액 경계 | 2026년 230,000,000원 | `src/ml/notice_amount.py` `notice_amount_for_year(2026)`, 기존 기관 규칙과 같은 상수 |

역산·대입으로 얻은 하한율은 원문에 인쇄된 값이 아니며, 2.1·2.2·2.3절의 계산식을 그대로 따랐습니다. 원문에 없는 값을 추정해 넣은 상수는 없습니다.

---

## 7. 검증

### 7.1 남은 일

1. **한국지역난방공사 2026-08-18판 정량평가 배점표**: 11개 규칙이 `quant_table=False` 라 정량점수 직접 입력이 필요합니다. `institution_quant_tables_20261013.yaml` 에 2026-08-18판 명세를 추가하는 후속 작업이 필요합니다.
2. **건설폐기물 처리용역 귀속**: 3.3절의 14건은 KDHC 별표 4 가 아니라 환경부 고시를 적용한 공고입니다. 규칙 귀속은 D10·D03 계열 후속 결정입니다.
3. **KAC 김포공항·KRC 토지개발사업단 코드**: 2.4절 이유로 넣지 않았습니다. 2026-03-02판·2025-10-01판 시설분야 규칙을 먼저 등록해야 합니다.
4. **`R26BK01369593`**: D10(세부유형 추론) 그대로입니다.

### 7.2 검증 명령

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_evaluation_rules_split_invariance.py tests/test_rule_coverage_ledger.py -q` | 32 passed |
| `uv run mypy src` | Success: no issues found in 145 source files |
| `uv run pytest tests/ -q -m 'not data_assets'` | 7.3절 |
| `python3 scripts/validate_agent_rules.py --quiet` | 7.3절 |

### 7.3 전체 시험·규칙 검증

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/ -q -m 'not data_assets'` | 10,537 passed, 41 skipped, 3 deselected, 2 xfailed (274.83s) |
| `python3 scripts/validate_agent_rules.py --quiet` | 검증 통과: 22/22 건 |

---

## 8. 재현

```sh
# 전수 판정 스냅샷(변경 전/후 같은 스크립트). DB 세션은 collect_records 가 READ ONLY 로 엽니다.
uv run python - <<'PY'
import json
from datetime import date
import scripts.report_rule_coverage as rc

original = rc._to_record

def patched(row, institutions, attachment_regime=None):
    record = original(row, institutions, attachment_regime)
    record["key"] = f"{row.bid_ntce_no}-{row.bid_ntce_ord}"
    return record

rc._to_record = patched
records = rc.collect_records(
    months=12,
    category="Servc",
    method_code="낙030001",
    today=date(2026, 11, 7),
)
snapshot = []
for record in records:
    outcome = rc.classify_result(record.get("result"), record.get("error_type"))
    snapshot.append(
        {
            "key": record["key"],
            "scope": outcome.applied_scope,
            "rule_id": outcome.rule_id,
            "block_code": outcome.block_code,
        }
    )
print(len(snapshot))
json.dump(snapshot, open("judgments.json", "w"), ensure_ascii=False)
PY
```

```sh
# 대상 집합 확인
uv run pytest tests/test_inst_versions_20261107.py -q
uv run pytest tests/test_kdhc_band_axis.py tests/test_kdhc_predecessor.py tests/test_rule_not_found_32_fix.py -q
```
