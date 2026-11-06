# MANUAL_EVALUATION 자동 추출 시범 측정

> **작성일**: 2026-11-06
> **작성**: Orca builder (worker)
> **대상**: `scripts/extract_score_params.py`, 규칙이 적용된 Servc 공고 층화 표본 120건
> **판정**: candidate. 이 문서는 측정값만 기록하며, 사용자 결정 5(9,424건 자동 추출 투자 여부)를 대신 내리지 않습니다.

---

## 1. 요약

규칙이 확정된 공고 120건에서 첨부 추출기의 B(가격 배점한도), k(평점계수), 기준비율, 통과점수(T) 추출 정확도를 시범 측정했습니다. 추출된 값은 B·k·기준비율에서 모두 정답과 일치했지만, 값을 낸 비율이 각각 11.70%, 6.32%, 3.33%로 낮았습니다. 통과점수만 추출률 63.16%로 높았고 정확도는 86.67%였으며, 오추출 8건은 전부 REGION 갈래에서 적용 규칙과 공고문 인용 문구가 다른 경우였습니다.

### 1.1 측정 조건

| 항목 | 값 |
| --- | --- |
| 조회 기간 | 2025-11-06 ~ 2026-11-06 (12개월) |
| 업무구분·낙찰방법 | Servc, 낙찰방법 코드 `낙030001` |
| 모집단 | `collect_records` 기준 31,348건. 원장 `data/reference/rule_coverage_ledger.yaml` 과 같은 값 |
| 표본 | 120건. REGION 40, PPS_DEFAULT 40, INSTITUTION 40 (시드 42, 갈래별 무작위) |
| 정답 | 적용 규칙과 공고 추정가격·공고일·낙찰방법명으로 `resolve_score_params` 를 실행한 B·k·기준비율·T |
| 추출 | `scripts/extract_score_params.py` 의 `extract_score_params` 를 그대로 호출. 공고 행은 DB `bid_announcements.raw_data` 를 쓰고 첨부만 내려받음 |
| 외부 요청 | 462회. 요청 사이 1초, 전체 상한 600회. 오류 0건 |
| 첨부 원본 | `.cache/extract_pilot/raw/` 에 저장(커밋하지 않음) |
| 측정일 | 2026-11-06 |

### 1.2 항목별 요약

| 항목 | 정답 보유 | 값을 냄 | 추출률 | 정답 일치 | 정확도 |
| --- | ---: | ---: | ---: | ---: | ---: |
| B (가격 배점한도) | 94 | 11 | 11.70% | 11 | 100.00% |
| k (평점계수) | 95 | 6 | 6.32% | 6 | 100.00% |
| 기준비율 | 120 | 4 | 3.33% | 4 | 100.00% |
| 통과점수 (T) | 95 | 60 | 63.16% | 52 | 86.67% |

- 네 항목이 모두 정답과 일치한 공고는 **4/94건(4.26%)** 입니다.
- 하나 이상 값을 낸 공고는 **72/120건(60.00%)**, 그중 오값이 하나도 없는 공고는 **64/120건(53.33%)** 입니다.
- 값을 냈지만 정답이 없어 판정할 수 없는 추출은 B 3건, T 12건입니다(전부 PPS_DEFAULT). 이 건은 추출률·정확도 분모에서 제외했습니다.
- B·k·기준비율의 정확도 100% 는 분모가 11·6·4건으로 작습니다. "틀리지 않았다"는 뜻이지 "충분히 검증됐다"는 뜻이 아닙니다.

---

## 2. 표본 구성과 정답 정의의 한계

### 2.1 모집단

`collect_records(months=12, category="Servc", method_code="낙030001")` 로 최근 12개월 공고를 읽었습니다. 결과는 31,348건이며 원장의 `totals.announcements` 와 같습니다.

| 적용 범위 | 공고 수 | 비고 |
| --- | ---: | --- |
| INSTITUTION | 82 | 기관 자체 규칙 |
| REGION | 1,856 | 시·도 자체 별표 |
| PPS_DEFAULT | 19,599 | 조달청 기본 별표 |
| BLOCKED | 9,811 | `MANUAL_EVALUATION` 9,424 포함 |
| ERROR | 0 | |

표본은 REGION·PPS_DEFAULT·INSTITUTION 에서만 뽑았습니다. `MANUAL_EVALUATION` 9,424건은 BLOCKED 에 속합니다.

### 2.2 표본 구성

| 구분 | 값 |
| --- | --- |
| 표본 | 120건 |
| 갈래 | REGION 40, PPS_DEFAULT 40, INSTITUTION 40 |
| 규칙 수 | 46종 |
| 최다 규칙 | `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526` 21건, `SERVC_LOCAL_SEOUL_20240812_ATTACH_01` 9건, `SERVC_LOCAL_GN_20230105_ATTACH_01` 8건 |
| 규칙이 B·k·T 를 선언하지 않은 공고 | 26건. 전부 PPS_DEFAULT 기술용역·PQ 계열 |

첨부 형식은 공고 단위 중복을 허용해 셉니다. 한 공고에 hwp 와 pdf 가 함께 있으면 양쪽에 모두 들어갑니다.

| 형식 | 공고 수 |
| --- | ---: |
| pdf | 79 |
| hwp | 77 |
| 기타(xlsx, zip, cell 등) | 56 |
| hwpx | 38 |
| 첨부 없음 | 9 |

- hwp·hwpx 계열 첨부가 하나도 없는 공고는 23건(19.17%)입니다. 이 공고는 현재 추출기로 값을 낼 수 없습니다.
- 첨부 수 분포는 0건 9, 1건 5, 2건 20, 3건 32, 4건 21, 5건 7, 6건 6, 7건 7, 8건 5, 9건 3, 10건 5입니다.

### 2.3 정답 정의

적용 규칙(`RuleResolutionResult.rule`)에 대해 다음 인자로 `resolve_score_params` 를 실행한 값을 정답으로 썼습니다.

| 인자 | 값 |
| --- | --- |
| `estimated_price` | `bid_announcements.presmpt_prce` |
| `announced_date` | `bid_announcements.bid_ntce_dt` |
| `method_name` | `cntrct_mthd_nm`, 없으면 `raw_data.sucsfbidMthdNm` |

| 항목 | 정답 필드 |
| --- | --- |
| B | `resolution.max_price_score` |
| k | `resolution.multiplier` |
| 기준비율 | `resolution.base_rate`, 없으면 `rule.base_rate` |
| T | `resolution.pass_threshold` |

정답이 `None` 인 항목은 그 공고를 해당 항목의 분모에서 제외했습니다. 기준비율은 규칙 객체의 기본값이 `0.90` 이므로 120건 모두 정답이 있습니다.

모집단의 항목별 정답 보유율은 다음과 같습니다. 갈래마다 다르므로 표본 수치를 전체로 일반화할 때 이 차이를 먼저 봐야 합니다.

| 갈래 | 공고 수 | B 정답 | k 정답 | T 정답 |
| --- | ---: | ---: | ---: | ---: |
| REGION | 1,856 | 1,856 (100%) | 1,856 (100%) | 1,856 (100%) |
| PPS_DEFAULT | 19,599 | 3,067 (15.65%) | 6,841 (34.91%) | 7,972 (40.68%) |
| INSTITUTION | 82 | 82 (100%) | 82 (100%) | 82 (100%) |

### 2.4 한계

1. **정답은 원문 재판독이 아니라 규칙 레지스트리 선언값입니다.** 첨부 원문을 사람이 다시 읽어 만든 정답이 아닙니다. 레지스트리 선언이 틀렸다면 이 문서의 "정확도"는 원문과의 일치가 아니라 레지스트리와의 일치를 잰 값입니다.
2. **규칙이 B·k·T 를 선언하지 않은 26건**은 정답이 없어 B·k·T 분모에서 빠졌습니다. 이 26건의 기준비율 정답은 규칙 기본값 `0.90` 이며, 원문으로 확인된 값이 아닙니다.
3. **표본과 `MANUAL_EVALUATION` 9,424건의 분포가 다릅니다.** 9,424건은 전부 낙찰방법명이 `적격심사제-관리규정외 수기심사(총점입력)` 이고 규칙 객체가 붙지 않아, 규칙이 적용된 공고에서 뽑은 이 표본에 들어오지 않았습니다. 첨부 구성과 자체 심사기준표 보유율이 다를 수 있으므로, 이 문서의 갈래별 수치를 9,424건에 그대로 적용할 수 없습니다.
4. **REGION·INSTITUTION 은 정답이 100% 존재하고 PPS_DEFAULT 는 일부만 존재합니다.** 그래서 전체 정답 보유 수(94·95·95)는 갈래 구성에 민감합니다.
5. **정답이 규칙과 다를 수 있습니다.** 4절의 REGION 오추출 8건은 공고문이 인용한 문구와 적용 규칙이 다릅니다. 어느 쪽이 실제 발주기관의 심사기준인지 이 문서는 판정하지 않았습니다.

---

## 3. 결과

### 3.1 항목별 전체

| 항목 | 정답 보유 | 추출 | 추출률 | 정답 일치 | 정확도 | 정답 없는 추출(판정 불가) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| B | 94 | 11 | 11.70% | 11 | 100.00% | 3 |
| k | 95 | 6 | 6.32% | 6 | 100.00% | 0 |
| 기준비율 | 120 | 4 | 3.33% | 4 | 100.00% | 0 |
| T | 95 | 60 | 63.16% | 52 | 86.67% | 12 |

네 항목 모두 일치 4/94건(4.26%). 네 항목 정답을 모두 보유한 공고 중 하나 이상 값을 낸 공고는 60건, 그중 오값 없이 하나 이상 값을 낸 공고는 52건입니다.

### 3.2 갈래별

| 갈래 | 공고 | 항목 | 정답 보유 | 추출 | 추출률 | 일치 | 정확도 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| REGION | 40 | B | 40 | 0 | 0.00% | 0 | - |
| REGION | 40 | k | 40 | 0 | 0.00% | 0 | - |
| REGION | 40 | 기준비율 | 40 | 0 | 0.00% | 0 | - |
| REGION | 40 | T | 40 | 25 | 62.50% | 17 | 68.00% |
| PPS_DEFAULT | 40 | B | 14 | 0 | 0.00% | 0 | - |
| PPS_DEFAULT | 40 | k | 15 | 0 | 0.00% | 0 | - |
| PPS_DEFAULT | 40 | 기준비율 | 40 | 0 | 0.00% | 0 | - |
| PPS_DEFAULT | 40 | T | 15 | 10 | 66.67% | 10 | 100.00% |
| INSTITUTION | 40 | B | 40 | 11 | 27.50% | 11 | 100.00% |
| INSTITUTION | 40 | k | 40 | 6 | 15.00% | 6 | 100.00% |
| INSTITUTION | 40 | 기준비율 | 40 | 4 | 10.00% | 4 | 100.00% |
| INSTITUTION | 40 | T | 40 | 25 | 62.50% | 25 | 100.00% |

네 항목 모두 일치 비율은 REGION 0/40, PPS_DEFAULT 0/14, INSTITUTION 4/40 입니다.

- REGION 은 B·k·기준비율을 한 건도 추출하지 못했습니다. 공고문이 지역 별표의 계산식을 싣지 않고 표준 별표 문구만 인용하는 경우가 많기 때문입니다.
- PPS_DEFAULT 도 B·k·기준비율 추출이 0건입니다. 정답이 있는 14~15건의 공고문에 적격심사 세부기준 별표가 첨부되지 않았거나, 첨부가 PDF 뿐이었습니다.
- INSTITUTION 은 추출률은 낮지만 낸 값은 전부 정답이었습니다. 기관 자체 별표가 hwp·hwpx 첨부에 실려 있는 경우입니다.

### 3.3 첨부 형식별

공고 단위 중복 허용 집계입니다. 예를 들어 hwp 와 pdf 가 모두 있는 공고는 두 행에 들어갑니다. 추출기는 PDF 를 명시적으로 지원하지 않으므로(`extract_document_text` 가 PDF 에 사유를 반환), pdf 행의 추출값은 같은 공고의 hwp·hwpx 첨부에서 나온 것입니다.

| 형식 | 공고 | B 추출률/정확도 | k 추출률/정확도 | 기준비율 추출률/정확도 | T 추출률/정확도 |
| --- | ---: | --- | --- | --- | --- |
| hwpx | 38 | 34.38% / 100.00% | 18.75% / 100.00% | 10.53% / 100.00% | 81.25% / 84.62% |
| pdf | 79 | 6.45% / 100.00% | 4.76% / 100.00% | 1.27% / 100.00% | 63.49% / 90.00% |
| hwp | 77 | 13.79% / 100.00% | 10.34% / 100.00% | 5.19% / 100.00% | 81.03% / 85.11% |
| 기타 | 56 | 9.30% / 100.00% | 4.65% / 100.00% | 3.57% / 100.00% | 69.77% / 93.33% |
| 첨부 없음 | 9 | 0.00% / - | 0.00% / - | 0.00% / - | 0.00% / - |

hwpx 가 hwp 보다 B·k 추출률이 높습니다. 두 형식 모두 T 추출률이 80%를 넘지만, 정확도는 84~85%로 B·k 보다 낮습니다.

### 3.4 실패 사유

정답이 있는데 값을 내지 못한 건의 사유입니다. 한 공고가 여러 사유에 걸리지 않도록 주 사유 하나로 셉니다.

| 사유 | B | k | 기준비율 | T |
| --- | ---: | ---: | ---: | ---: |
| 문서에서 해당 문구를 찾지 못함 | 56 | 56 | 94 | 17 |
| 후보가 복수이고 공고 구간을 확정할 수 없음 | 10 | 15 | 0 | 0 |
| 공고에 첨부된 적격심사 세부기준·공고문이 없음 | 7 | 7 | 9 | 7 |
| 첨부가 기계 판독 불가(주로 PDF 단독) | 10 | 11 | 13 | 11 |
| 추출 성공 | 11 | 6 | 4 | 60 |

- B·k·기준비율의 최대 실패 원인은 "문서에 계산식이 없다"입니다. 추출기 버그가 아니라, 공고문이 적격심사 세부기준 별표를 첨부하지 않고 문구만 인용한 경우입니다.
- "후보가 복수"는 기술용역·PQ 계열에서 표에 구간이 여러 개인데 공고 구간을 확정할 수 없을 때 발생합니다. 해당 10·15건은 정답이 있는 건입니다.
- PDF 단독 첨부는 현재 파서가 읽지 못합니다. hwp·hwpx 계열이 없는 공고 23건이 이 경로에 걸립니다.

### 3.5 처리 비용

| 항목 | 값 |
| --- | ---: |
| 표본 | 120건 |
| 외부 요청 | 462회 |
| 요청 간 간격 | 1초 |
| 공고당 평균 처리 시간 | 3.85초 |
| 공고당 최대 처리 시간 | 10.1초 |
| 표본 전체 처리 시간 | 약 8분 |
| 예외·오류 | 0건 |

---

## 4. 오추출 사례

정답과 추출값이 다르면서 양쪽 모두 값이 있는 사례는 8건입니다. 전부 T, 전부 REGION 갈래입니다. "상위 10건" 조건에 해당하는 사례가 8건뿐이어서 전량을 적습니다.

| 공고번호 | 항목 | 정답 | 추출 | 근거 문구(요약) | 원인 추정 |
| --- | --- | ---: | ---: | --- | --- |
| R26BK01718717 | T | 85 | 95 | `공고문[엄정천 소하천정비사업 건설폐기물 운반 및 처리용역].hwpx`: 환경부 고시 별표4, 추정가격 2억원 미만, 종합평점 95점 | 공고문이 인용한 별표(2억원 미만, 95점)와 적용 규칙(85점)이 다름 |
| R26BK01308988 | T | 95 | 88 | `2026학년도 광주선우학교 통학버스 학생운송용역 공고문.hwpx`: 종합평점이 88점 이상 | 공고문 문구(88점)와 적용 지역 규칙(95점)이 다름 |
| R26BK01281601 | T | 95 | 88 | `[일반용역 입찰 긴급 공고] 2026학년도 에듀버스 임차 용역(삼향동초).hwp`: 종합평점 88점 | 공고문 문구(88점)와 적용 지역 규칙(95점)이 다름 |
| R26BK01295631 | T | 95 | 85 | `공고문(2026년 평창군청 직원 단체보장보험 가입).hwp`: 종합평점이 85점 이상 | 공고문 문구(85점)와 적용 지역 규칙(95점)이 다름 |
| R25BK01165663 | T | 95 | 85 | `공고문_2026년도 직원 단체보험 용역.hwp`: 종합평점이 85점 이상 | 공고문 문구(85점)와 적용 지역 규칙(95점)이 다름 |
| R26BK01522164 | T | 95 | 85 | `1. 입찰공고문.hwp`: 종합평점 85점 이상 | 공고문 문구(85점)와 적용 지역 규칙(95점)이 다름 |
| R26BK01270671 | T | 95 | 85 | `입찰공고문.hwp`: 종합평점 85점 이상 | 공고문 문구(85점)와 적용 지역 규칙(95점)이 다름 |
| R26BK01716319 | T | 95 | 85 | `공고문.hwpx`: 종합평점이 85점 이상 | 공고문 문구(85점)와 적용 지역 규칙(95점)이 다름 |

공통 원인은 파싱 오류가 아니라 **적용 규칙 판별과 첨부 문구의 불일치**입니다. 추출기는 첨부에 적힌 문구를 정확히 읽었습니다. 다만 그 문구가 서비스가 적용할 규칙과 같은지 확인할 방법이 없습니다. 이 8건은 규칙 레지스트리를 정답으로 잡은 결과이며, 실제 발주기관 기준이 어느 쪽인지는 이 문서가 판정하지 않았습니다.

B·k·기준비율에는 오추출이 0건입니다. 값을 낸 11·6·4건은 모두 정답과 일치했습니다.

---

## 5. 사용자 결정 5 선택지별 함의

이 절은 선택지를 고르지 않습니다. 측정값이 각 선택지에 대해 말해 주는 것만 적습니다.

### 5.1 (가) 현 입력 경로 유지

- 추가 개발 비용이 없습니다. 현재 사용자 입력 경로는 이미 계산을 열어 줍니다.
- 이 표본에서는 B·k·기준비율을 자동으로 채울 수 있는 비율이 각각 11.70%, 6.32%, 3.33%입니다. 사용자는 여전히 네 항목 중 3개 안팎을 직접 입력해야 합니다.
- 자동 추출을 붙이지 않아도 계산 기능은 그대로 동작합니다.

### 5.2 (나) 첨부 추출 시범 적용

- 값을 낸 B·k·기준비율은 정확도 100%(11·6·4건)입니다. "확실할 때만 채운다"는 조건을 걸면 잘못된 값을 채울 위험을 낮출 수 있습니다.
- 전체 추출을 그대로 허용하면 하나 이상 값을 받는 공고가 72/120건(60.00%)이고, 그중 오값이 있는 공고가 8/120건(6.67%)입니다. 오값은 전부 REGION T 입니다.
- REGION T 만 자동 채움에서 제외하면 하나 이상 값을 받는 공고가 47/120건(39.17%)으로 줄고, 오값이 있는 공고는 0건이 됩니다.
- 다만 네 항목을 모두 채우는 공고는 4/94건(4.26%)뿐입니다. 시범 적용의 효과는 "입력 부담 감소"이지 "무입력 자동 계산"이 아닙니다.
- 통과점수는 추출률이 63.16%로 가장 높아, T 만 먼저 채우는 부분 적용도 가능합니다. 다만 T 하나만으로는 계산이 열리지 않습니다.

### 5.3 (다) 전량 자동화

- 이 표본은 전량 자동화를 지지하지 않습니다. 네 항목 모두 맞은 공고가 4.26%입니다.
- 구조적 상한이 있습니다. hwp·hwpx 계열 첨부가 없는 공고가 23/120건(19.17%), 첨부 자체가 없는 공고가 9/120건(7.50%)입니다. 현재 추출기는 PDF 를 읽지 않습니다.
- 정답 자체가 없는 공고도 있습니다. 표본 26건은 적용 규칙이 B·k·T 를 선언하지 않았습니다. 자동화하려면 이 규칙들의 값을 먼저 확정해야 합니다.
- 전량 자동화에는 최소 세 가지 별도 투자가 필요합니다. PDF 텍스트 레이어 파서, 적용 규칙과 첨부 별표의 대응 판별, 기술용역·PQ 규칙의 B·k·T 레지스트리 확장입니다. 현재 추출기의 정확도를 더 높이는 일만으로는 4.26%가 크게 오르지 않습니다.

### 5.4 판단에 필요한 남은 확인

- 이 표본은 `MANUAL_EVALUATION` 9,424건이 아니라 규칙이 적용된 공고에서 뽑았습니다. 9,424건의 첨부 구성과 자체 심사기준표 보유율을 같은 방식으로 소규모 확인하면, (나)의 실제 적용 범위를 더 정확히 가늠할 수 있습니다.
- 정답을 규칙 레지스트리 대신 원문 사람 판독으로 삼으면, 이 문서의 "정확도"가 달라질 수 있습니다.

---

## 부록 A. 실행 명령

```bash
# 표본 120건 측정. .cache/extract_pilot/results.json 과 attachments.json 을 쓴다.
uv run python .cache/extract_pilot/run.py

# 결과 집계 표 출력
uv run python .cache/extract_pilot/report.py
```

측정 스크립트는 `.cache/` 아래에 두어 커밋하지 않습니다. 아래 부록 B·C 가 실행한 전문입니다.

---

## 부록 B. 측정 스크립트 전문

```python
#!/usr/bin/env python3
"""MANUAL_EVALUATION 자동 추출 시범 측정.

규칙이 적용된 Servc 공고에서 층화 표본 120건을 뽑아, 정답(적용 규칙의 B·k·기준비율·T)과
scripts/extract_score_params.py 의 추출값을 비교한다. 코드는 고치지 않고, 추출기는
공고 행을 DB 에서 받아 첨부만 내려받도록 fetch_announcement 만 바꿔 끼운다.

실행:
    uv run python .cache/extract_pilot/run.py
    uv run python .cache/extract_pilot/run.py --limit 3
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import sys
import time
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import extract_score_params as esp  # noqa: E402
import report_rule_coverage as rrc  # noqa: E402
from sqlalchemy import bindparam, text  # noqa: E402

from src.app.core.db import engine  # noqa: E402
from src.app.services.evaluation_rules import resolve_score_params  # noqa: E402

CATEGORY = "Servc"
METHOD_CODE = "낙030001"
MONTHS = 12
SEED = 42
PER_SCOPE = 40
SCOPES = ("REGION", "PPS_DEFAULT", "INSTITUTION")
ITEMS = ("B", "k", "base_rate", "T")
ITEM_FIELD = {
    "B": "max_price_score",
    "k": "multiplier",
    "base_rate": "base_rate",
    "T": "pass_threshold",
}
CACHE = ROOT / ".cache" / "extract_pilot"
RAW_DIR = CACHE / "raw"
MANIFEST_PATH = CACHE / "attachments.json"
RESULT_PATH = CACHE / "results.json"

REQUEST_INTERVAL = 1.0
MAX_REQUESTS = 600
ANNOUNCEMENT_TIMEOUT = 240

STATE: dict[str, object] = {
    "row": None,
    "url_names": {},
    "requests": 0,
    "last_request": 0.0,
    "manifest": [],
}


def parse_raw(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", "replace")
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def attachment_format(name: str, data: bytes | None = None) -> str:
    suffix = Path(name).suffix.lower().lstrip(".")
    if suffix in {"hwp", "hwpx", "pdf"}:
        return suffix
    if data:
        if data.startswith(b"%PDF"):
            return "pdf"
        if data.startswith(b"PK\x03\x04"):
            return "hwpx"
        if data.startswith(b"\xd0\xcf\x11\xe0"):
            return "hwp"
    return "기타"


def instrument_records() -> None:
    """collect_records 가 공고번호를 남기도록 _to_record 를 감싼다."""
    original = rrc._to_record

    def patched(row, institutions, attachment_regime=None):
        record = original(row, institutions, attachment_regime)
        record["bid_ntce_no"] = row.bid_ntce_no
        record["bid_ntce_ord"] = row.bid_ntce_ord
        return record

    rrc._to_record = patched


def stratified_sample(records: list[dict]) -> list[dict]:
    pools: dict[str, list[dict]] = {scope: [] for scope in SCOPES}
    for record in records:
        outcome = rrc.classify_result(record.get("result"), record.get("error_type"))
        if outcome.applied_scope in pools:
            record["applied_scope"] = outcome.applied_scope
            record["rule_id"] = outcome.rule_id
            pools[outcome.applied_scope].append(record)
    rng = random.Random(SEED)
    sample: list[dict] = []
    for scope in SCOPES:
        pool = sorted(pools[scope], key=lambda item: item["bid_ntce_no"])
        sample.extend(rng.sample(pool, min(PER_SCOPE, len(pool))))
    return sample


def latest_rows(bid_nos: list[str]) -> dict[str, dict]:
    sql = text(
        """
        SELECT bid_ntce_no, bid_ntce_ord, category, dminstt_nm, cntrct_mthd_nm,
               presmpt_prce, bid_ntce_dt, raw_data
        FROM bid_announcements
        WHERE category = :category AND bid_ntce_no IN :nos
        """
    ).bindparams(bindparam("nos", expanding=True))
    with engine.connect() as conn:
        conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
        rows = conn.execute(sql, {"category": CATEGORY, "nos": bid_nos}).mappings().all()

    best: dict[str, dict] = {}
    for row in rows:
        raw = parse_raw(row["raw_data"])
        if str(raw.get("sucsfbidMthdCd") or "").strip() != METHOD_CODE:
            continue
        current = best.get(row["bid_ntce_no"])
        if current is None or rrc._ord_key(row["bid_ntce_ord"]) > rrc._ord_key(
            current["bid_ntce_ord"]
        ):
            item = dict(row)
            item["raw"] = raw
            best[row["bid_ntce_no"]] = item
    return best


def truth_of(record: dict, row: dict) -> tuple[dict, object]:
    rule = record["result"].rule
    price = row.get("presmpt_prce")
    price = Decimal(str(price)) if price not in (None, "") else None
    method = row.get("cntrct_mthd_nm") or row["raw"].get("sucsfbidMthdNm")
    resolution = resolve_score_params(rule, price, row.get("bid_ntce_dt"), method)
    base_rate = resolution.base_rate
    if base_rate is None:
        base_rate = getattr(rule, "base_rate", None)
    return {
        "B": resolution.max_price_score,
        "k": resolution.multiplier,
        "base_rate": base_rate,
        "T": resolution.pass_threshold,
    }, resolution


async def fake_fetch_announcement(
    bid_no: str, bgn_dt: str, end_dt: str, category: str = "Servc", *, client=None
):
    return STATE["row"]


async def rate_limited_download(url: str, *, client=None) -> bytes:
    now = time.monotonic()
    wait = REQUEST_INTERVAL - (now - float(STATE["last_request"]))
    if wait > 0:
        await asyncio.sleep(wait)
    if int(STATE["requests"]) >= MAX_REQUESTS:
        raise RuntimeError(f"외부 호출 상한 초과: {MAX_REQUESTS}")
    STATE["requests"] = int(STATE["requests"]) + 1
    STATE["last_request"] = time.monotonic()
    data = await esp._original_download(url, client=client)
    name = str(STATE["url_names"].get(url) or Path(url).name or "attachment")
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)[:80]
    path = RAW_DIR / f"{digest}_{safe}"
    path.write_bytes(data)
    STATE["manifest"].append(
        {
            "bid_no": STATE["row"].get("bidNtceNo"),
            "name": name,
            "url": url,
            "bytes": len(data),
            "sha1": hashlib.sha1(data).hexdigest(),
            "format": attachment_format(name, data),
            "saved": str(path.relative_to(ROOT)),
        }
    )
    return data


def install_extractor_hooks() -> None:
    esp._original_download = esp.download_document
    esp.fetch_announcement = fake_fetch_announcement
    esp.download_document = rate_limited_download


def quote(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def same_value(left: Decimal | None, right: Decimal | None) -> bool:
    if left is None or right is None:
        return False
    return quote(left) == quote(right)


def evidence_format(evidence: str | None, documents: list[str]) -> str:
    if not evidence:
        return "없음"
    name = evidence.split(":", 1)[0].strip()
    if name not in documents:
        return "기타"
    return attachment_format(name)


async def measure(sample: list[dict], rows: dict[str, dict]) -> list[dict]:
    results: list[dict] = []
    total = len(sample)
    for index, record in enumerate(sample, 1):
        bid_no = record["bid_ntce_no"]
        row = rows.get(bid_no)
        if row is None:
            results.append(
                {
                    "bid_no": bid_no,
                    "scope": record["applied_scope"],
                    "rule_id": record.get("rule_id"),
                    "error": "DB 행 없음",
                }
            )
            continue
        truth, _resolution = truth_of(record, row)
        row_dict = {key: str(value) for key, value in row["raw"].items() if value is not None}
        row_dict.setdefault("presmptPrce", str(row.get("presmpt_prce") or ""))
        row_dict.setdefault("sucsfbidMthdNm", str(row.get("cntrct_mthd_nm") or ""))
        row_dict.setdefault("bidNtceNo", bid_no)
        attachments = esp.announcement_attachments(row_dict)
        STATE["row"] = row_dict
        STATE["url_names"] = {url: name for name, url in attachments}

        value: dict[str, Decimal | None] = {item: None for item in ITEMS}
        reasons: dict[str, str | None] = {}
        evidence: dict[str, str | None] = {}
        documents: list[str] = []
        error = None
        started = time.monotonic()
        try:
            params = await asyncio.wait_for(
                esp.extract_score_params(
                    bid_no,
                    row["bid_ntce_dt"].strftime("%Y%m%d"),
                    row["bid_ntce_dt"].strftime("%Y%m%d"),
                    CATEGORY,
                ),
                timeout=ANNOUNCEMENT_TIMEOUT,
            )
            value = {
                "B": params.max_price_score,
                "k": params.multiplier,
                "base_rate": params.base_rate,
                "T": params.pass_threshold,
            }
            reasons = dict(params.reasons)
            evidence = dict(params.evidence)
            documents = list(params.documents)
        except Exception as exc:  # 추출 실패도 측정값이다.
            error = f"{type(exc).__name__}: {exc}"[:300]

        formats = sorted(
            {
                attachment_format(name)
                for name in documents
                or [name for name, _url in attachments]
            }
        )
        results.append(
            {
                "bid_no": bid_no,
                "scope": record["applied_scope"],
                "rule_id": record.get("rule_id"),
                "estimated_price": row.get("presmpt_prce"),
                "method": row_dict.get("sucsfbidMthdNm"),
                "attachments": documents or [name for name, _url in attachments],
                "formats": formats,
                "truth": {item: quote(truth[item]) for item in ITEMS},
                "extracted": {item: quote(value[item]) for item in ITEMS},
                "evidence": evidence,
                "reasons": reasons,
                "error": error,
                "elapsed": round(time.monotonic() - started, 2),
            }
        )
        print(
            f"[{index}/{total}] {bid_no} {record['applied_scope']} "
            f"truth={[truth[i] for i in ITEMS]} extracted={[value[i] for i in ITEMS]} "
            f"{'ERROR' if error else ''}",
            flush=True,
        )
    return results


def rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def aggregate(results: list[dict], key: str) -> dict:
    out: dict[str, dict] = {}
    buckets: dict[str, list[dict]] = {}
    for item in results:
        if key == "scope":
            names = [item.get("scope") or "미상"]
        elif key == "format":
            names = item.get("formats") or ["첨부없음"]
        else:
            names = ["전체"]
        for name in names:
            buckets.setdefault(name, []).append(item)

    for name, items in buckets.items():
        entry: dict[str, object] = {"announcements": len(items)}
        for axis in ITEMS:
            with_truth = [i for i in items if i.get("truth", {}).get(axis) is not None]
            extracted = [
                i
                for i in with_truth
                if i.get("extracted", {}).get(axis) is not None
            ]
            correct = [
                i
                for i in extracted
                if same_value(
                    Decimal(i["extracted"][axis]), Decimal(i["truth"][axis])
                )
            ]
            entry[axis] = {
                "truth_n": len(with_truth),
                "extracted_n": len(extracted),
                "correct_n": len(correct),
                "extraction_rate": rate(len(extracted), len(with_truth)),
                "accuracy": rate(len(correct), len(extracted)),
            }
        all_truth = [
            i
            for i in items
            if all(i.get("truth", {}).get(axis) is not None for axis in ITEMS)
        ]
        all_correct = [
            i
            for i in all_truth
            if all(
                i.get("extracted", {}).get(axis) is not None
                and same_value(Decimal(i["extracted"][axis]), Decimal(i["truth"][axis]))
                for axis in ITEMS
            )
        ]
        entry["all_four"] = {
            "truth_n": len(all_truth),
            "correct_n": len(all_correct),
            "accuracy": rate(len(all_correct), len(all_truth)),
        }
        entry["errors_n"] = sum(1 for i in items if i.get("error"))
        out[name] = entry
    return out


def mis_extractions(results: list[dict]) -> list[dict]:
    cases: list[dict] = []
    for item in results:
        for axis in ITEMS:
            truth = item.get("truth", {}).get(axis)
            extracted = item.get("extracted", {}).get(axis)
            if truth is None or extracted is None:
                continue
            if same_value(Decimal(extracted), Decimal(truth)):
                continue
            cases.append(
                {
                    "bid_no": item["bid_no"],
                    "scope": item.get("scope"),
                    "item": axis,
                    "truth": truth,
                    "extracted": extracted,
                    "evidence": item.get("evidence", {}).get(axis),
                    "reason": item.get("reasons", {}).get(axis),
                    "formats": item.get("formats"),
                }
            )
    cases.sort(key=lambda case: abs(Decimal(case["extracted"]) - Decimal(case["truth"])), reverse=True)
    return cases


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="표본 대신 앞 N건만 측정")
    parser.add_argument("--only-scope", default="", help="특정 갈래만 측정")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    instrument_records()
    install_extractor_hooks()

    print("collect_records 실행 중...", flush=True)
    records = rrc.collect_records(months=MONTHS, category=CATEGORY, method_code=METHOD_CODE)
    sample = stratified_sample(records)
    if args.only_scope:
        sample = [item for item in sample if item["applied_scope"] == args.only_scope]
    if args.limit:
        sample = sample[: args.limit]
    print(f"표본 {len(sample)}건", flush=True)

    rows = latest_rows([record["bid_ntce_no"] for record in sample])
    print(f"DB 행 {len(rows)}건", flush=True)

    results = await measure(sample, rows)
    payload = {
        "generated_at": date.today().isoformat(),
        "filter": {
            "months": MONTHS,
            "category": CATEGORY,
            "method_code": METHOD_CODE,
            "seed": SEED,
            "per_scope": PER_SCOPE,
        },
        "sample_size": len(results),
        "requests": STATE["requests"],
        "scope": aggregate(results, "scope"),
        "format": aggregate(results, "format"),
        "overall": aggregate(results, "all"),
        "mis_extractions": mis_extractions(results),
        "results": results,
    }
    RESULT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    MANIFEST_PATH.write_text(
        json.dumps(STATE["manifest"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"overall": payload["overall"], "requests": payload["requests"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

---

## 부록 C. 집계 스크립트 전문

```python
#!/usr/bin/env python3
"""results.json 을 문서 표로 접는다."""

from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

CACHE = Path(__file__).resolve().parent
ITEMS = ("B", "k", "base_rate", "T")


def pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.2f}%"


def main() -> None:
    payload = json.loads((CACHE / "results.json").read_text(encoding="utf-8"))
    results = payload["results"]

    print("== 표본 구성 ==")
    print("표본", len(results))
    print("갈래", Counter(item.get("scope") for item in results))
    print("규칙", Counter(item.get("rule_id") for item in results).most_common())
    formats = Counter()
    for item in results:
        for name in item.get("formats") or ["첨부없음"]:
            formats[name] += 1
    print("형식(중복 허용)", dict(formats.most_common()))
    print("첨부 없음", sum(1 for item in results if not item.get("attachments")))
    print("오류", sum(1 for item in results if item.get("error")))
    print("외부 요청", payload["requests"])

    print("\n== 갈래별 ==")
    for name, entry in payload["scope"].items():
        print(name, json.dumps(entry, ensure_ascii=False))

    print("\n== 형식별 ==")
    for name, entry in payload["format"].items():
        print(name, json.dumps(entry, ensure_ascii=False))

    print("\n== 항목별 전체 ==")
    overall = payload["overall"]["전체"]
    for item in ITEMS:
        entry = overall[item]
        unjudged = sum(
            1
            for row in results
            if row.get("extracted", {}).get(item) is not None
            and row.get("truth", {}).get(item) is None
        )
        print(
            item,
            f"정답 {entry['truth_n']}",
            f"추출 {entry['extracted_n']}",
            f"정답일치 {entry['correct_n']}",
            f"추출률 {pct(entry['extraction_rate'])}",
            f"정확도 {pct(entry['accuracy'])}",
            f"정답없는추출 {unjudged}",
        )
    print("네 항목", json.dumps(overall["all_four"], ensure_ascii=False))

    print("\n== 정답 보유(항목별) ==")
    print(
        {
            item: sum(1 for row in results if row.get("truth", {}).get(item) is not None)
            for item in ITEMS
        }
    )

    print("\n== 오추출 상위 15 ==")
    for case in payload["mis_extractions"][:15]:
        print(
            case["bid_no"],
            case["scope"],
            case["item"],
            "정답",
            case["truth"],
            "추출",
            case["extracted"],
            "|",
            str(case.get("evidence"))[:90],
            "|",
            case.get("reason"),
            case.get("formats"),
        )

    print("\n== 정답대비 오차 분포 ==")
    diff = Counter()
    for row in results:
        for item in ITEMS:
            truth = row.get("truth", {}).get(item)
            got = row.get("extracted", {}).get(item)
            if truth is None or got is None:
                continue
            if Decimal(truth) == Decimal(got):
                diff[(item, "일치")] += 1
            else:
                diff[(item, "불일치")] += 1
    for key, value in sorted(diff.items()):
        print(key, value)


if __name__ == "__main__":
    main()
```
