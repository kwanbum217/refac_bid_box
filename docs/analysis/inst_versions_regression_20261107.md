# 기관 규칙 판본·구간 축·매칭 결정 회귀 (D07·D08·D09·D22·D29)

> **작성일**: 2026-11-07
> **개정**: 2026-11-07 반려 재작업 Orca Task `task_32d52bd4f706` (건설폐기물처리용역 환경부고시 배제, 9절)
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
| 판정(적용 범위·규칙 ID·차단 코드)이 바뀐 공고 | 47 |
| 그중 새로 차단된 공고 | 0 |
| 대상 집합 밖 판정 변화 | 0 |
| 변경 후 규칙 구간값 = 공고값 | 47 |
| 변경 후 규칙 구간값 != 공고값 | 0 |

바뀐 47건은 모두 한국지역난방공사 본사·지사·사업소 공고입니다. 한국농어촌공사 5건은 규칙 ID 가 그대로이고 구간값만 바뀌므로 1.2의 판정 변경 수에 들어가지 않습니다(3.3절). 반려 재작업으로 건설폐기물처리용역 14건이 종전 환경부고시 판정으로 돌아가고 `R26BK01369593` 1건이 추가로 환경부고시 규칙을 쓰게 되어, 변경 수가 60건에서 47건으로 줄었습니다(9절).

### 1.3 대상 집합 결과

| 묶음 | 대상 | 변경 | 규칙 구간값 = 공고값 | 남은 불일치 |
| --- | ---: | ---: | ---: | ---: |
| inst_band_mismatch_13 | 13 | 13 (KDHC 8 + KRC 5) | 13 | 0 |
| not_computable_9 KDHC 여객 | 1 | 1 | 1 | 0 |
| regime_lag_65 4.3 공기업 | 10 | 8 (KDHC 8) | 8 | 2 (KAC·KRC, 규칙 기본값 89.995 대 공고 87.995) |

`inst_band_mismatch_13` 의 한국농어촌공사 5건은 규칙 ID 가 바뀌지 않아 1.2의 47건에는 없지만, 구간값이 86.245에서 82.495로 바뀌어 공고값과 일치합니다.

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
- 변경 47건, 전부 한국지역난방공사(본사 9, 지사·사업소 38)입니다.
- 새로 차단된 공고는 0건입니다. 변경 전 차단 1건(`R25BK01166116`, `RULE_REGIME_MISMATCH`)은 해소되었습니다.

### 3.2 판정이 바뀐 공고 47건

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
| 13 | `R26BK01369593`(000) | 2026-03-04 | 한국지역난방공사(B550373) | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | PPS_DEFAULT/SERVC_QUAL_MOE_CDW_ATTACH_04 | 87.745 | 87.745 | O |
| 14 | `R26BK01394326`(000) | 2026-03-13 | 한국지역난방공사 대구지사(D325102) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_01 | INSTITUTION/SERVC_INST_KDHC_20260101_FACILITY | 87.995 | 87.995 | O |
| 15 | `R26BK01397306`(000) | 2026-03-16 | 한국지역난방공사 대구지사(D325102) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_03 | INSTITUTION/SERVC_INST_KDHC_20260101_PASSENGER | 87.995 | 87.995 | O |
| 16 | `R26BK01399835`(001) | 2026-03-19 | 한국지역난방공사 양산지사(D325117) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_08 | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | 84.245 | 84.245 | O |
| 17 | `R26BK01408405`(000) | 2026-03-19 | 한국지역난방공사 양산지사(D325117) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_08 | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | 84.245 | 84.245 | O |
| 18 | `R26BK01408776`(000) | 2026-03-19 | 한국지역난방공사 동탄지사(D325152) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_01 | INSTITUTION/SERVC_INST_KDHC_20260101_FACILITY | 87.995 | 87.995 | O |
| 19 | `R26BK01424140`(000) | 2026-03-26 | 한국지역난방공사 청주지사(D325103) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260101_REPAIR | 84.245 | 84.245 | O |
| 20 | `R26BK01426219`(000) | 2026-03-27 | 한국지역난방공사 화성지사(D325156) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_01 | INSTITUTION/SERVC_INST_KDHC_20260101_FACILITY | 87.995 | 87.995 | O |
| 21 | `R26BK01494599`(000) | 2026-04-28 | 한국지역난방공사 김해사업소(D325107) | PPS_DEFAULT/SERVC_QUAL_PRE_20250901_ATTACH_08 | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | 84.245 | 84.245 | O |
| 22 | `R26BK01542739`(000) | 2026-05-26 | 한국지역난방공사 강남지사(D325150) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260101_REPAIR | 84.245 | 84.245 | O |
| 23 | `R26BK01560111`(000) | 2026-06-04 | 한국지역난방공사 강남지사(D325150) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260101_REPAIR | 84.245 | 84.245 | O |
| 24 | `R26BK01583538`(000) | 2026-06-16 | 한국지역난방공사 김해사업소(D325107) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_04 | INSTITUTION/SERVC_INST_KDHC_20260101_SW_TARGET | 87.995 | 87.995 | O |
| 25 | `R26BK01589006`(000) | 2026-06-18 | 한국지역난방공사 양산지사(D325117) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_01 | INSTITUTION/SERVC_INST_KDHC_20260101_FACILITY | 87.995 | 87.995 | O |
| 26 | `R26BK01589351`(000) | 2026-06-18 | 한국지역난방공사 청주지사(D325103) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_01 | INSTITUTION/SERVC_INST_KDHC_20260101_FACILITY | 87.995 | 87.995 | O |
| 27 | `R26BK01596070`(000) | 2026-06-22 | 한국지역난방공사 삼송지사(D325115) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_01 | INSTITUTION/SERVC_INST_KDHC_20260101_FACILITY | 87.995 | 87.995 | O |
| 28 | `R26BK01599265`(000) | 2026-06-24 | 한국지역난방공사 양산지사(D325117) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_01 | INSTITUTION/SERVC_INST_KDHC_20260101_FACILITY | 87.995 | 87.995 | O |
| 29 | `R26BK01607658`(000) | 2026-06-29 | 한국지역난방공사 양산지사(D325117) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_01 | INSTITUTION/SERVC_INST_KDHC_20260101_FACILITY | 87.995 | 87.995 | O |
| 30 | `R26BK01631533`(000) | 2026-07-14 | 한국지역난방공사 대구지사(D325102) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260101_REPAIR | 84.245 | 84.245 | O |
| 31 | `R26BK01656148`(000) | 2026-07-29 | 한국지역난방공사 광주전남지사(D325105) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_01 | INSTITUTION/SERVC_INST_KDHC_20260101_FACILITY | 87.995 | 87.995 | O |
| 32 | `R26BK01660419`(000) | 2026-07-31 | 한국지역난방공사 강남지사(D325150) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260101_REPAIR | 84.245 | 84.245 | O |
| 33 | `R26BK01674466`(000) | 2026-08-10 | 한국지역난방공사 강남지사(D325150) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260101_REPAIR | 84.245 | 84.245 | O |
| 34 | `R26BK01681756`(000) | 2026-08-13 | 한국지역난방공사 대구지사(D325102) | PPS_DEFAULT/SERVC_QUAL_POST_20260727_ATTACH_03 | INSTITUTION/SERVC_INST_KDHC_20260101_PASSENGER | 87.995 | 87.995 | O |
| 35 | `R26BK01708025`(000) | 2026-09-01 | 한국지역난방공사 수원사업소(D325112) | INSTITUTION/SERVC_INST_KDHC_20260101_OTHER | INSTITUTION/SERVC_INST_KDHC_20260818_OTHER | 82.495 | 82.495 | O |
| 36 | `R26BK01730527`(001) | 2026-09-22 | 한국지역난방공사(B550373) | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | INSTITUTION/SERVC_INST_KDHC_20260818_WASTE | 82.495 | 82.495 | O |
| 37 | `R26BK01745985`(000) | 2026-09-28 | 한국지역난방공사(B550373) | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | INSTITUTION/SERVC_INST_KDHC_20260818_WASTE | 82.495 | 82.495 | O |
| 38 | `R26BK01747872`(000) | 2026-09-29 | 한국지역난방공사 화성지사(D325156) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260818_REPAIR | 86.245 | 86.245 | O |
| 39 | `R26BK01761398`(000) | 2026-10-07 | 한국지역난방공사(B550373) | INSTITUTION/SERVC_INST_KDHC_20260101_LEASE | INSTITUTION/SERVC_INST_KDHC_20260818_LEASE | 82.495 | 82.495 | O |
| 40 | `R26BK01764999`(000) | 2026-10-12 | 한국지역난방공사(B550373) | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | INSTITUTION/SERVC_INST_KDHC_20260818_WASTE | 82.495 | 82.495 | O |
| 41 | `R26BK01766196`(000) | 2026-10-12 | 한국지역난방공사(B550373) | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | INSTITUTION/SERVC_INST_KDHC_20260818_WASTE | 82.495 | 82.495 | O |
| 42 | `R26BK01792264`(000) | 2026-10-26 | 한국지역난방공사 김해사업소(D325107) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260818_REPAIR | 86.245 | 86.245 | O |
| 43 | `R26BK01793057`(000) | 2026-10-27 | 한국지역난방공사(B550373) | INSTITUTION/SERVC_INST_KDHC_20260101_WASTE | INSTITUTION/SERVC_INST_KDHC_20260818_WASTE | 82.495 | 82.495 | O |
| 44 | `R26BK01793122`(000) | 2026-10-27 | 한국지역난방공사 서울중앙지사(D325109) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_15 | INSTITUTION/SERVC_INST_KDHC_20260818_REPAIR | 86.245 | 86.245 | O |
| 45 | `R26BK01798610`(000) | 2026-10-29 | 한국지역난방공사 수원사업소(D325112) | PPS_DEFAULT/SERVC_QUAL_POST_20260526_ATTACH_01 | INSTITUTION/SERVC_INST_KDHC_20260818_FACILITY | 89.995 | 89.995 | O |
| 46 | `R26BK01812771`(000) | 2026-11-05 | 한국지역난방공사 광주전남지사(D325105) | PPS_DEFAULT/SERVC_QUAL_POST_20260727_ATTACH_03 | INSTITUTION/SERVC_INST_KDHC_20260818_PASSENGER | 87.995 | 87.995 | O |
| 47 | `R26BK01813749`(000) | 2026-11-05 | 한국지역난방공사(B550373) | INSTITUTION/SERVC_INST_KDHC_20260101_SW | INSTITUTION/SERVC_INST_KDHC_20260818_SW | 82.495 | 82.495 | O |

### 3.3 기관별 집계

| 기관(코드) | 변경 | 규칙값 = 공고값 | 규칙값 != 공고값 |
| --- | ---: | ---: | ---: |
| 한국지역난방공사(B550373) | 9 | 9 | 0 |
| 한국지역난방공사 광주전남지사(D325105) | 7 | 7 | 0 |
| 한국지역난방공사 강남지사(D325150) | 6 | 6 | 0 |
| 한국지역난방공사 양산지사(D325117) | 6 | 6 | 0 |
| 한국지역난방공사 대구지사(D325102) | 5 | 5 | 0 |
| 한국지역난방공사 김해사업소(D325107) | 3 | 3 | 0 |
| 한국지역난방공사 서울중앙지사(D325109) | 3 | 3 | 0 |
| 한국지역난방공사 수원사업소(D325112) | 2 | 2 | 0 |
| 한국지역난방공사 청주지사(D325103) | 2 | 2 | 0 |
| 한국지역난방공사 화성지사(D325156) | 2 | 2 | 0 |
| 한국지역난방공사 동탄지사(D325152) | 1 | 1 | 0 |
| 한국지역난방공사 삼송지사(D325115) | 1 | 1 | 0 |
| **합계** | **47** | **47** | **0** |


규칙값 != 공고값 0건입니다. 반려 전 표에 있던 건설폐기물처리용역 14건은 공고문이 환경부고시 「건설폐기물처리용역 적격업체 평가기준」을 인용하므로 KDHC 별표 4 대신 고시 경로로 돌아갔고, 규칙 구간값과 공고값이 모두 일치합니다(9절).

### 3.4 inst_band_mismatch_13 (13건)

| # | 공고번호 | 기관 | 변경 후 규칙 | 규칙값 | 공고값 | 일치 |
| ---: | --- | --- | --- | ---: | ---: | :---: |
| 1 | `R26BK01369593` | 한국지역난방공사 | `SERVC_QUAL_MOE_CDW_ATTACH_04` | 87.745 | 87.745 | O |
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

- 13/13 일치. `R26BK01369593` 은 공고명이 `건설폐기물 처리용역`이고 첨부 `5. (환경부고시) 건설폐기물처리용역 적격업체 평가기준(2025.10.01).pdf` 를 붙이며 하한율이 87.745% 라, 9절의 배제 규칙으로 고시 제4호를 씁니다.
- 한국농어촌공사 5건은 규칙 ID 가 그대로이고 밴드값만 86.245에서 82.495로 바뀌었습니다. 3.1의 판정 축(규칙 ID)이 바뀌지 않아 47건 표에는 없습니다.

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

- 47건 모두 한국지역난방공사 본사·지사·사업소 공고입니다.
- 다른 기관(한국농어촌공사·한국공항공사 포함)의 적용 범위·규칙 ID·차단 코드는 바뀌지 않았습니다.
- 2026-01-01판 이전 지사 공고 10건은 지사 코드가 새로 붙기 전과 같이 PPS 기본값을 유지합니다. 2.4절의 시행 전 판본 제외 규칙 때문입니다.
- 새로 차단된 공고는 0건입니다.

---

## 5. 기존 시험 단언 변경

| 파일 | 위치 | 변경 전 | 변경 후 | 이유 |
| --- | --- | --- | --- | --- |
| `tests/test_institution_rules.py` | 186행 | `assert code_total == 137` | `assert code_total == 143` | D08 로 한국농어촌공사 6개 별표에 구간이 6개 늘었습니다. YAML·코드 구간 수를 함께 맞췄습니다. |
| `tests/test_evaluation_quant_institution.py` | 50행 | `KDHC_NO_TABLE_IDS = ("SERVC_INST_KDHC_20230719_WASTE",)` | 2026-08-18판 11개 ID 추가 (9.6절에서 다시 축소) | D07 로 새 규칙 ID 가 생겼고 2026-08-18판 배점표 명세가 없어 `quant_table=False`(정량점수 직접 입력)입니다. |
| `tests/test_evaluation_rules_split_invariance.py` | 43행 | `"INSTITUTION_RULES": "d7cabe0e33a1e8cf"` | `"8a8c340f61ca94b1"` | D07·D08·D22·D29 로 기관 규칙 벌이 의도적으로 바뀌었습니다. 다른 규칙 상수 지문과 `list_all_rules()` 지문은 그대로입니다. |
| `tests/test_evaluation_rules_split_invariance.py` | 45행 | `"INSTITUTION_RULES": "8a8c340f61ca94b1"` | `"0b25ba9cff246172"` | 반려 재작업으로 한국지역난방공사 폐기물 규칙 3개에 `cdw_exclusion="named"` 를 선언했습니다. 다른 규칙 상수 지문과 `list_all_rules()` 지문은 그대로입니다. |
| `tests/test_evaluation_quant_institution.py` | 50행 | 2026-08-18판 11개 ID 포함 | `KDHC_NO_TABLE_IDS = ("SERVC_INST_KDHC_20230719_WASTE",)` | D07 (A) 연장으로 2026-08-18판 별표 1~9 배점표를 등록해 정량표 없음이 해소됐습니다(9.6절). |
| `tests/test_evaluation_quant_institution.py` | 85행 | `assert len(table_ids) == 65` | `assert len(table_ids) == 76` | 위 등록으로 기관 배점표가 11개 늘었습니다(9.6절). |
| `tests/test_inst_versions_20261107.py` | 150행 | `assert rule.quant_basis == QUANT_BASIS_AGENCY_DOCUMENT_NOT_LOADED` | `assert rule.quant_basis == QUANT_BASIS_INSTITUTION` | 2026-08-18판 11개 규칙이 기관 배점표를 쓰게 됐습니다(9.6절). |
| `tests/test_evaluation_rules_split_invariance.py` | 48행 | `"INSTITUTION_RULES": "0b25ba9cff246172"` | `"05814ed65e4b5fa1"` | 2026-08-18판 11개 규칙의 `quant_table` 을 False -> True 로 바꿔 `quant_basis` 가 INSTITUTION 이 되었습니다. 다른 규칙 상수 지문과 `list_all_rules()` 지문은 그대로입니다(9.6절). |
| `tests/test_institution_rules.py` | `test_kac_subunit_alias_matches_only_without_code` | 코드 `Z013741` 이면 기관 규칙 미선택 | 변경 없음 | D29 는 지사·사업소(한국지역난방공사)만 넓혔고 한국공항공사 코드는 넣지 않았습니다. 2.4절 이유. |

새 시험 `tests/test_inst_versions_20261107.py` 는 (a) 2026-08-18 경계, (b) 농어촌 고시금액 축, (c) 2023-07-19 여객, (d) 지사 코드 매칭, (e) 목록 밖 코드 미매칭, (f) 공고문이 환경부고시를 인용한 건설폐기물처리용역의 고시 규칙 적용, (g) 공고명에 건설폐기물이 없을 때 공사 별표 4 유지를 단언합니다. 기존 `tests/test_kdhc_band_axis.py`, `tests/test_kdhc_predecessor.py`, `tests/test_rule_not_found_32_fix.py`, `tests/test_cdw_exclusion_regions.py` 는 단언을 바꾸지 않고 통과합니다.

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
| KDHC 폐기물 규칙 3개의 `cdw_exclusion="named"` | 선언값(수치 아님) | 공고문 R26BK01621293·R26BK01629748·R26BK01644144 인용문과 sha256, 9.1절. KDHC 원문에는 건설폐기물 제외 문구가 없습니다 |
| 고시금액 경계 | 2026년 230,000,000원 | `src/ml/notice_amount.py` `notice_amount_for_year(2026)`, 기존 기관 규칙과 같은 상수 |

역산·대입으로 얻은 하한율은 원문에 인쇄된 값이 아니며, 2.1·2.2·2.3절의 계산식을 그대로 따랐습니다. 원문에 없는 값을 추정해 넣은 상수는 없습니다.

---

## 7. 검증

### 7.1 남은 일

1. **한국지역난방공사 2026-08-18판 정량평가 배점표**: 11개 규칙이 `quant_table=False` 라 정량점수 직접 입력이 필요합니다. `institution_quant_tables_20261013.yaml` 에 2026-08-18판 명세를 추가하는 후속 작업이 필요합니다.
2. **KAC 김포공항·KRC 토지개발사업단 코드**: 2.4절 이유로 넣지 않았습니다. 2026-03-02판·2025-10-01판 시설분야 규칙을 먼저 등록해야 합니다.

건설폐기물처리용역 귀속(반려 전 3.3절의 14건)과 `R26BK01369593` 은 9절의 환경부고시 배제 규칙으로 해소되었습니다.

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
| `uv run pytest tests/ -q -m 'not data_assets'` | 10,539 passed, 41 skipped, 3 deselected, 2 xfailed (272.24s) |
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

```sh
# 반려 재작업 회귀(9.3절). 기관 규칙의 cdw_exclusion 만 끈 판정과 현재 판정을 같은 수집에서 비교합니다.
uv run python - <<'PY'
from dataclasses import replace
from datetime import date
import scripts.report_rule_coverage as rc
from src.app.services import evaluation_rules

after_rules = evaluation_rules.INSTITUTION_RULES
before_rules = tuple(
    replace(rule, cdw_exclusion=None) if rule.cdw_exclusion else rule
    for rule in after_rules
)
original = rc._to_record


def judge(result):
    outcome = rc.classify_result(result)
    return (outcome.applied_scope, outcome.rule_id, outcome.block_code)


def patched(row, institutions, attachment_regime=None):
    key = f"{row.bid_ntce_no}-{row.bid_ntce_ord}"
    evaluation_rules.INSTITUTION_RULES = before_rules
    try:
        before = original(row, institutions, attachment_regime)
    finally:
        evaluation_rules.INSTITUTION_RULES = after_rules
    after = original(row, institutions, attachment_regime)
    record = dict(after)
    record["key"] = key
    record["before"] = judge(before["result"])
    record["after"] = judge(after["result"])
    return record


rc._to_record = patched
records = rc.collect_records(
    months=12,
    category="Servc",
    method_code="낙030001",
    today=date(2026, 11, 7),
)
changed = {r["key"]: (r["before"], r["after"]) for r in records if r["before"] != r["after"]}
print(len(records), len(changed))
for key, (before, after) in sorted(changed.items()):
    print(key, before, "->", after)
PY
```

---

## 9. 반려 재작업: 건설폐기물처리용역 환경부고시 경로 복원

반려 사유는 이전 시도의 전수 판정 비교에서 변경 60건 중 14건이 환경부고시 건설폐기물 규칙(`SERVC_QUAL_MOE_CDW_ATTACH_03`·`_04`)에서 한국지역난방공사 폐기물 규칙(`SERVC_INST_KDHC_*_WASTE`)으로 넘어간 것입니다. 2026-10-19 결정은 건설폐기물에 환경부 고시 경로를 쓰도록 정하고 있습니다.

### 9.1 근거 확인

#### 9.1.1 한국지역난방공사 세부기준 원문

`data/sources/qualification/files/kdhc` 의 2023-07-19·2026-01-01·2026-08-18판 텍스트 추출본에서 `건설폐기물` 을 찾은 결과는 0건입니다. 폐기물처리용역 정의와 적용 범위에 제외 문구가 없습니다.

- `e2313784645a_kdhc_yongyeok_2026-01-01.txt:16` — "5. “폐기물처리용역”이란 쓰레기, 연소재, 오니(汚泥: 오염된 침전물), 폐유, 폐산, 폐알카리 및 동물의 사체 등으로서 사람의 생활이나 산업활동에 필요하지 아니하게 된 물질(폐기물)을 폐기물관리법 제25조에 의한 환경부장관 또는 시·도지사의 ‘폐기물처리업’ 허가를 받은 ‘폐기물처리업자’가 폐기물을 수집, 운반, 보관, 재활용, 처분(소각, 중화, 파쇄, 고형화 등) 등의 방법으로 처리하는 영업을 말한다."
- `762d7992a046_kdhc_eq.txt:12` (2026-08-18판 추출) — 같은 문장.
- `e2313784645a_kdhc_yongyeok_2026-01-01.txt:63` — "4. 폐기물처리용역 평가기준 : 별표 4". 건설폐기물 예외 없음.

따라서 원문만으로는 배제 근거가 없습니다. 아래 공고문이 환경부고시를 직접 인용하므로 그 공고에 한해 고시 경로를 씁니다.

#### 9.1.2 공고문 인용과 하한율

반려 목록 14건은 모두 낙찰방법명이 환경부고시 [별표] 구간명(`적격심사제-추정가격 2억원 미만인 용역`, `적격심사제-추정가격 5억원 미만 2억원 이상인 용역`)이고, 첨부에 환경부고시 `건설폐기물처리용역 적격업체 평가기준` 이 있습니다. 그중 4개 파일을 1초 간격으로 내려받아(`.cache/cdw14`, 커밋 제외) 인용문과 하한율을 확인했습니다.

| 공고번호 | 내려받은 첨부 | sha256 | 인용문 | 공고 하한율 |
| --- | --- | --- | --- | ---: |
| `R26BK01621293` | `1. 입찰공고문(불연성).pdf` (1132801 bytes) | `3f91db9ef432defae2e3ca22a94112227a12010b8babe82bd39a10acfa3ad910` | "가. 기후에너지환경부 “건설폐기물처리용역 적격업체 평가기준”에 의하여 낙찰자를 결정하므로 동 기준을 반드시 사전에 열람하여야 합니다." | 87.745 |
| `R26BK01629748` | `0.입찰공고문.pdf` (943668 bytes) | `0f294575cdcfd854b6a851c4f98134f72da5da121a533f9075370145ee82be78` | "가. 적격심사 낙찰제로서 환경부고시 “건설폐기물처리용역 적격업체 평가기준”에 의하여 낙찰자를 결정하므로 동 기준을 반드시 사전 열람하여야 합니다." | 86.745 |
| `R26BK01644144` | `1. 입찰공고문(PDF).pdf` (834112 bytes) | `3e129290cb3d74106fc325b6a94b0761668a896783d82a76fbab47e1a98a3262` | "가. 적격심사 낙찰제로서 건설폐기물처리용역 적격업체 평가기준(환경부고시 제2025-165호)에 의하여 낙찰자를 결정하므로 동 기준을 반드시 사전 열람하여야 합니다." | 87.745 |
| `R26BK01633356` | `5. 건설폐기물처리용역 적격업체 평가기준(환경부고시)(제2025-165호)(20251007).pdf` (882831 bytes) | `2c39ad6ae811d2ffe47a3b2d3701d39cfc17f9924dd72596fd9541d1b3db003b` | "[시행 2025. 10. 7.] [환경부고시 제2025-165호, 2025. 10. 1., 일부개정]" / "제1조(목적) ... 건설폐기물처리용역의 적격업체를 선정하기 위한 평가기준" | 87.745 |

- 인용문은 환경부고시가 적용 기준임을 밝히고, 하한율은 고시 제4호(2억원 미만) 87.745%·제3호(5억원 미만 2억원 이상) 86.745% 와 같습니다.
- 나머지 10건도 첨부 파일명이 `(환경부고시) 건설폐기물처리용역 적격업체 평가기준` 또는 `건설폐기물처리용역 적격업체 평가기준(환경부고시 제2025-165호)` 이고 하한율이 같은 값입니다.

### 9.2 수정 내용

| 파일 | 수정 |
| --- | --- |
| `src/app/services/evaluation_rules_institution.py` | `_institution_rule` 에 `cdw_exclusion` 인자를 추가하고, `SERVC_INST_KDHC_20230719_WASTE`·`SERVC_INST_KDHC_20260101_WASTE`·`SERVC_INST_KDHC_20260818_WASTE` 에 `cdw_exclusion="named"` 를 선언했습니다. 인용문·sha256 은 `_KDHC_CDW_CITATION` 상수와 주석에 남겼습니다. |
| `src/app/services/evaluation_rules.py` | 시·도 경로의 인라인 `_cdw_excluded` 를 모듈 함수 `_is_cdw_excluded(rule, bid_name)` 로 옮겼습니다. `_select_institution_rule` 은 낙찰방법명이 환경부고시 띠 표기이고 공고명에 `건설폐기물` 이 있으면 그 기관 폐기물 규칙을 후보에서 빼고, 후보가 없으면 종전 조달청·환경부고시 경로로 넘깁니다. |
| `tests/test_inst_versions_20261107.py` | (f) 건설폐기물처리용역이 고시 제4호로 계산되는지, (g) 공고명에 건설폐기물이 없으면 공사 별표 4 를 유지하는지 시험을 추가했습니다. |
| `tests/test_evaluation_rules_split_invariance.py` | `INSTITUTION_RULES` 지문을 `0b25ba9cff246172` 로 갱신했습니다(5절). |
| `docs/analysis/inst_versions_regression_20261107.md` | 1.2·1.3·3.2·3.3·3.4·4·5·6·7.1절 수치를 재작업 결과로 갱신하고 9절을 추가했습니다. |

- 시·도 규칙의 `cdw_exclusion` 판정은 값과 순서가 그대로입니다(`LOCAL_RULES` 지문 불변, `tests/test_cdw_exclusion_regions.py` 통과).
- 이름 패턴으로 지사·기관을 고르는 코드는 추가하지 않았습니다. 배제 판정은 공고명의 `건설폐기물` 표기와 낙찰방법명 띠 표기만 봅니다.

### 9.3 재작업 후 전수 판정 회귀

기관 규칙의 `cdw_exclusion` 만 끈 판정(반려 전 상태)과 현재 판정을 같은 31,325건 수집에서 비교했습니다. 재현은 9.4절입니다.

| # | 공고번호(차수) | 변경 전(반려 전) | 변경 후 | 규칙 구간값 | 공고값 | 일치 |
| ---: | --- | --- | --- | ---: | ---: | :---: |
| 1 | `R26BK01369593`(000) | INSTITUTION/`SERVC_INST_KDHC_20260101_WASTE` | PPS_DEFAULT/`SERVC_QUAL_MOE_CDW_ATTACH_04` | 87.745 | 87.745 | O |
| 2 | `R26BK01621293`(000) | INSTITUTION/`SERVC_INST_KDHC_20260101_WASTE` | PPS_DEFAULT/`SERVC_QUAL_MOE_CDW_ATTACH_04` | 87.745 | 87.745 | O |
| 3 | `R26BK01624792`(000) | INSTITUTION/`SERVC_INST_KDHC_20260101_WASTE` | PPS_DEFAULT/`SERVC_QUAL_MOE_CDW_ATTACH_04` | 87.745 | 87.745 | O |
| 4 | `R26BK01629748`(000) | INSTITUTION/`SERVC_INST_KDHC_20260101_WASTE` | PPS_DEFAULT/`SERVC_QUAL_MOE_CDW_ATTACH_03` | 86.745 | 86.745 | O |
| 5 | `R26BK01633123`(000) | INSTITUTION/`SERVC_INST_KDHC_20260101_WASTE` | PPS_DEFAULT/`SERVC_QUAL_MOE_CDW_ATTACH_04` | 87.745 | 87.745 | O |
| 6 | `R26BK01633356`(000) | INSTITUTION/`SERVC_INST_KDHC_20260101_WASTE` | PPS_DEFAULT/`SERVC_QUAL_MOE_CDW_ATTACH_04` | 87.745 | 87.745 | O |
| 7 | `R26BK01633843`(000) | INSTITUTION/`SERVC_INST_KDHC_20260101_WASTE` | PPS_DEFAULT/`SERVC_QUAL_MOE_CDW_ATTACH_04` | 87.745 | 87.745 | O |
| 8 | `R26BK01638207`(000) | INSTITUTION/`SERVC_INST_KDHC_20260101_WASTE` | PPS_DEFAULT/`SERVC_QUAL_MOE_CDW_ATTACH_04` | 87.745 | 87.745 | O |
| 9 | `R26BK01644144`(000) | INSTITUTION/`SERVC_INST_KDHC_20260101_WASTE` | PPS_DEFAULT/`SERVC_QUAL_MOE_CDW_ATTACH_04` | 87.745 | 87.745 | O |
| 10 | `R26BK01645094`(000) | INSTITUTION/`SERVC_INST_KDHC_20260101_WASTE` | PPS_DEFAULT/`SERVC_QUAL_MOE_CDW_ATTACH_04` | 87.745 | 87.745 | O |
| 11 | `R26BK01648695`(000) | INSTITUTION/`SERVC_INST_KDHC_20260101_WASTE` | PPS_DEFAULT/`SERVC_QUAL_MOE_CDW_ATTACH_04` | 87.745 | 87.745 | O |
| 12 | `R26BK01649356`(000) | INSTITUTION/`SERVC_INST_KDHC_20260101_WASTE` | PPS_DEFAULT/`SERVC_QUAL_MOE_CDW_ATTACH_04` | 87.745 | 87.745 | O |
| 13 | `R26BK01649977`(000) | INSTITUTION/`SERVC_INST_KDHC_20260101_WASTE` | PPS_DEFAULT/`SERVC_QUAL_MOE_CDW_ATTACH_04` | 87.745 | 87.745 | O |
| 14 | `R26BK01655100`(000) | INSTITUTION/`SERVC_INST_KDHC_20260101_WASTE` | PPS_DEFAULT/`SERVC_QUAL_MOE_CDW_ATTACH_04` | 87.745 | 87.745 | O |
| 15 | `R26BK01656556`(000) | INSTITUTION/`SERVC_INST_KDHC_20260101_WASTE` | PPS_DEFAULT/`SERVC_QUAL_MOE_CDW_ATTACH_04` | 87.745 | 87.745 | O |

- 반려 목록 `.orca/cdw14.txt` 의 14건이 모두 변경 후 환경부고시 판정으로 돌아왔습니다(키 집합 일치 확인).
- 15번째 `R26BK01369593` 은 `inst_band_mismatch_13` 의 한국지역난방공사 1건으로, 공고명이 `건설폐기물 처리용역(건설오니)` 이고 첨부가 `5. (환경부고시) 건설폐기물처리용역 적격업체 평가기준(2025.10.01).pdf`, 하한율이 87.745% 입니다. 반려 전 공사 별표 4(84.245%)와 불일치하던 값이 고시 제4호와 일치하게 되었습니다.
- 전수 변경은 60건에서 47건이 되었습니다(14건 복귀 + 1건 추가). 1.2·3.2·3.3절 표를 이 값으로 갱신했습니다.
- 새로 차단된 공고 0건, 대상 집합 밖 판정 변화 0건입니다.
- 시·도(`REGION`)·다른 기관 판정은 바뀌지 않았습니다. 반려 전 변경 60건 중 남은 46건의 변경 전·후 값도 3.2절 그대로입니다.

### 9.4 재현

8절 마지막 코드 블록이 9.3절 비교를 그대로 재현합니다.

### 9.5 반려 사유 대응 요약

| 반려 지시 | 처리 |
| --- | --- |
| (1) KDHC 원문의 건설폐기물 제외 문구 확인 | 3개 판본 추출문 `건설폐기물` 0건. 제외 문구 없음(9.1.1). |
| (2) 14건 중 3건 이상 공고 첨부 확인 | 4개 파일 내려받아 인용문·하한율 확인(9.1.2). 모두 환경부고시 인용, 하한율 87.745·86.745. |
| (3) `cdw_exclusion="named"` 선언 또는 고시 우선 경로 수정 | KDHC 폐기물 규칙 3개에 `cdw_exclusion="named"` 선언, 기관 규칙 선택에서 배제(9.2). |
| (4) 전수 회귀 재실행, 14건 복귀·변경 건수 확인 | 변경 47건(60-14+1), 14건 복귀 확인(9.3). 추가 1건은 대상 집합 안이며 규칙값이 공고값과 일치. |

---

## 9.6 D07 (A) 연장: 한국지역난방공사 2026-08-18판 정량평가 배점표 등록

2.1절에서 `quant_table=False`(정량점수 직접 입력)로 남겨 둔 2026-08-18판 규칙 11개의
정량표 없음 상태를 해소했습니다. 상세 근거는 별도 문서
[`docs/analysis/kdhc_quant_20260818_20261107.md`](kdhc_quant_20260818_20261107.md) 에 있고,
이 절은 이 과업이 바꾼 규칙 상수와 시험 단언만 정리합니다.

### 9.6.1 변경 요약

| 파일 | 변경 |
| --- | --- |
| `data/reference/institution_quant_tables_20261013.yaml` | 한국지역난방공사 항목에 `SERVC_INST_KDHC_20260818_*` 규칙 11개를 추가했습니다. 근거 `kdhc_2608`(60ea20722555_kdhc_20260818.txt) 줄 번호를 `sources` 와 각 항목 `source` 에 적었습니다. |
| `src/app/services/evaluation_quant_institution.py` | 생성기 `scripts/build_institution_quant_tables.py` 로 재생성했습니다(표 65 -> 76). 손으로 고치지 않았습니다. |
| `src/app/services/evaluation_rules_institution.py` | 2026-08-18판 규칙 11곳의 `quant_table` 만 `False` -> `True` 로 바꿨습니다. 2023-07-19판 규칙은 그대로 `False` 입니다. |
| `tests/test_evaluation_quant_institution.py` | 50행 `KDHC_NO_TABLE_IDS` 를 구판 1개로 축소하고, 85행 표 개수를 76 으로 맞췄습니다. |
| `tests/test_inst_versions_20261107.py` | 150행 `quant_basis` 단언을 `AGENCY_DOCUMENT_NOT_LOADED` -> `INSTITUTION` 으로 바꿨습니다. |
| `tests/test_kdhc_quant_20261107.py` | 새 시험. 규칙 11개가 모두 표를 조회하는지, 구간별 항목 배점한도가 원문 표와 같은지 단언합니다. |
| `tests/test_evaluation_rules_split_invariance.py` | `INSTITUTION_RULES` 지문만 `0b25ba9cff246172` -> `05814ed65e4b5fa1` 로 갱신했습니다. |

### 9.6.2 판단 근거: 배점표가 두 판본에서 같은 이유

2026-08-18판 별표 1~9 의 심사항목 배점한도는 원문 표에서 2026-01-01판과 같습니다.
두 판본에서 달라진 것은 배점표가 아니라 입찰가격 기준비율과 별표 6 등급 경계입니다.

| 항목 | 2026-01-01판 | 2026-08-18판 | 근거 |
| --- | --- | --- | --- |
| 입찰가격 기준비율 | 88(별표 2는 93, 별표 3의2·5는 91, 별표 6은 88) | 90(별표 2는 93, 별표 3의2·5는 91, 별표 6은 88) | 2.1절에서 이미 규칙에 반영 |
| 별표 6 지급여력비율 A 기준선 | 150% 이상 | 130% 이상 | `kdhc_2608:1488-1490` |

별표 2 만 표에 실린 항목 구성이 다릅니다. 2026-08-18판 원문은 결격사유 -20 행을
인쇄하는데(`kdhc_2608:610-616`) 2026-01-01판 명세가 그 행을 싣지 않았습니다. 원문에
있는 값만 쓴다는 원칙에 따라 새 표는 원문을 따랐고, 2026-01-01판 항목은 건드리지
않았습니다. 결격사유는 배점 합계 검산에서 제외되므로 합계 100 은 그대로입니다.

### 9.6.3 지문 변경이 이 변경 때문임을 확인한 방법

`INSTITUTION_RULES` 지문이 바뀐 원인이 `quant_table` 플래그 변경뿐임을 아래처럼
확인했습니다. 플래그만 되돌리면 지문이 종전 값으로 정확히 복원됩니다.

| 상태 | `sha256(repr(INSTITUTION_RULES))[:16]` |
| --- | --- |
| `quant_table=True` (11개, 현재) | `05814ed65e4b5fa1` |
| `quant_table=False` (11개, 변경 전) | `0b25ba9cff246172` |

재현은 아래 두 줄입니다. 첫 줄은 11개 플래그를 다시 `False` 로 되돌린 사본을 만들어
지문을 재고, 둘째 줄은 현재 상태의 지문을 잽니다.

```sh
sed 's/quant_table=True,/quant_table=False,/' src/app/services/evaluation_rules_institution.py \
  > /tmp/_probe_inst.py && cp src/app/services/evaluation_rules_institution.py /tmp/_backup_inst.py \
  && cp /tmp/_probe_inst.py src/app/services/evaluation_rules_institution.py \
  && uv run python -c "import hashlib, src.app.services.evaluation_rules as e; print(hashlib.sha256(repr(e.INSTITUTION_RULES).encode()).hexdigest()[:16])" \
  ; cp /tmp/_backup_inst.py src/app/services/evaluation_rules_institution.py
uv run python -c "import hashlib, src.app.services.evaluation_rules as e; print(hashlib.sha256(repr(e.INSTITUTION_RULES).encode()).hexdigest()[:16])"
```

`quant_basis` 는 `EvaluationRule` 의 필드라 값이 바뀌면 `repr` 이 바뀌고, 다른 규칙
상수(`POST_20260526_RULES`·`POST_20260727_RULES`·`MOE_CDW_RULES`·`PRE_*`·`LOCAL_RULES`·
`MOIS_ACADEMIC_BAND_RULES`)와 `list_all_rules()` 지문은 그대로입니다.

### 9.6.4 검증

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_kdhc_quant_20261107.py tests/test_evaluation_quant_institution.py tests/test_inst_versions_20261107.py -q` | 27 passed |
| `uv run python scripts/build_institution_quant_tables.py --check` | 생성본이 YAML 과 일치 |
| `uv run mypy src` | Success: no issues found in 145 source files |
| `python3 scripts/validate_agent_rules.py --quiet` | 검증 통과 22/22 |
| `uv run pytest tests/ -q -m 'not data_assets'` | 전량 통과 |
