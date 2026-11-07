# 문서 간 숫자 불일치 4건 원인 조사

> **작성일**: 2026-11-07
> **대상**: [`decision_backlog_20261107.md`](./decision_backlog_20261107.md) 1.3절의 불일치 4건
> **작업**: Orca Task `task_6ca381494eeb` (builder), Run `run_d3fa8d51ba74`
> **정본 사양**: `.orca/capsules/task_number_mismatch_4_20261107/capsule.yaml` (`ORCA_TASK_CAPSULE_V2`)
> **코드·기존 문서 수정**: 없음. 이 문서 1개가 산출물입니다.
> **DB 접근**: `scripts/db_readonly_query.py` 와 `scripts/report_rule_coverage.py` 의 READ ONLY 경로만 사용했습니다. `docker exec`, `mysql` 직접 호출과 `raw_data LIKE` 전체 스캔은 쓰지 않았습니다.
> **재현 등급**: `확인`(두 숫자를 같은 조건에서 다시 만듦), `부분`(한쪽만 재현하거나 산술로만 복원), `미확인`(재현 실패)

---

## 1. 요약

### 1.1 원인 라벨

| 라벨 | 정의 |
| --- | --- |
| (가) 계산 시점 | 같은 창·같은 코드라도 측정 시점의 DB 수집 스냅샷이 달라 값이 갈림 |
| (나) 창 정의 | 기준일과 최근 12개월 창의 양 끝이 다름 |
| (다) 모집단 정의 | 같은 이름의 대상 집합이 실제로는 다른 집합이거나, 서로 다른 값을 한 값으로 뭉뚱그림 |
| (라) 코드 변경 | 두 측정 사이에 규칙·해석 코드가 바뀜 |

### 1.2 불일치 표

| # | 불일치 | 값 A (출처) | 값 B (출처) | 원인 | 재현 |
| ---: | --- | --- | --- | --- | --- |
| 1 | 규칙 적용 건수 | 21,546 (pps 4.2절·method 3.1절이 인용, 원출처 감사 1절) | 21,590 (method 3.1절) | (가) 계산 시점 | A `부분`, B `확인` |
| 2 | 규칙값·공고값 불일치 | 1,184 (감사 1절, method 3.1절이 인용) | 1,142 (method 3.1절) | (라) 코드 변경 −39, (나) 창 −3 | 둘 다 `확인` |
| 3 | 전체 창 공고 수 | 31,428 (entity 4절, 2025-11-06~2026-11-06) | 31,325 (method 3.1절·not_computable 1절·원장, 2025-11-07~2026-11-07) | (나) 창 정의 | 둘 다 `확인` |
| 4 | 13건 공고값 | 13건 전부 82.495 (kdhc 1.2절·4.3절) | 1번 `R26BK01369593` 은 87.745 (inst 1.1절) | (다) 모집단 정의 | 둘 다 `확인` |

### 1.3 세 줄 결론

1. 21,546 대 21,590 은 창도 낙찰방법 필터도 원인이 아닙니다. 21,546 은 감사 문서가 **2026-11-06 당일 수집이 끝나기 전 스냅샷**에서 측정한 값이고, 21,590 은 method 문서가 **다른 코드 리비전(72baaa01)의 11-07 창**에서 측정한 값입니다. 두 값의 차이 44건은 2026-11-06 접수분 안에서 정확히 설명됩니다.
2. 1,184 대 1,142 는 **코드 변경 −39건 + 창 −3건**입니다. 감사 값은 감사 커밋(`2117c58b`) 코드에서 그대로 재현되고, method 값은 `72baaa01` 코드에서 그대로 재현됩니다.
3. 31,428 대 31,325 는 **창 정의만의 차이**이고, 13건 공고값은 **13건을 단일 값으로 본 인용 오류**입니다. 실제로는 12건 82.495, 1건 87.745입니다.

---

## 2. 건별 상세

### 2.1 규칙 적용 건수: 21,546 대 21,590

#### 2.1.1 측정 조건

| 문서·절 | 기준일 | 창 | 낙찰방법 필터 | 적용 정의 | 측정 코드 | 값 |
| --- | --- | --- | --- | --- | --- | ---: |
| 감사 1절·부록 B.1 | 2026-11-06 | 2025-11-06 이상 2026-11-07 미만 | 없음 | 차단·미적용 제외 | `2117c58b` 계열 | 21,546 |
| pps 4.2절 | (감사 값 인용) | 2025-11-06 ~ 2026-11-05 | 없음 | 같음 | 측정 없음(인용) | 21,546 |
| method 3.1절 | 2026-11-07 | 2025-11-07 이상 2026-11-08 미만 | `낙030001` | 차단·미적용 제외 | `72baaa01` | 21,590 |

pps 4.2절의 21,546 은 자체 측정값이 아니라 감사 문서 1절을 인용한 값입니다. 따라서 값 A 의 원출처는 감사 문서 하나입니다.

#### 2.1.2 낙찰방법 필터는 적용 건수를 바꾸지 않는다

같은 창에서 필터 유무 두 갈래를 메모리에서 함께 셌습니다. **모든 규칙 적용 건의 `sucsfbidMthdCd` 가 `낙030001` 이므로 대표 공고가 정해진 뒤에는 필터가 적용·비교가능·불일치를 바꾸지 않습니다.**

| 코드 리비전 | 창 | 필터 없음 적용 | 선정 전 필터 적용 | 필터 없음 불일치 | 선정 전 필터 불일치 |
| --- | --- | ---: | ---: | ---: | ---: |
| `2117c58b` | 2025-11-06~2026-11-06 | 21,590 | 21,590 | 1,184 | 1,184 |
| `2117c58b` | 2025-11-07~2026-11-07 | 21,531 | 21,531 | 1,181 | 1,181 |
| `72baaa01` | 2025-11-07~2026-11-07 | 21,587 | 21,590 | 1,142 | 1,142 |
| `00e963f3`/`HEAD` | 2025-11-07~2026-11-07 | 21,594 | 21,594 | 1,125 | 1,125 |

필터가 바꾸는 것은 적용 건수가 아니라 **대표 공고 선정 전 모집단**입니다. 필터를 먼저 걸면 같은 공고번호의 다른 낙찰방법 차수가 대표에서 빠지므로 공고 수는 31,318 대 31,325 로 7건 달라지고, 그중 3건이 적용 건수에 반영됩니다(`72baaa01` 21,587 → 21,590). 불일치 건수는 두 방식 모두 같습니다. method 문서가 든 "낙찰방법 코드 필터 유무"는 적용 건수 차이의 원인이 아닙니다.

#### 2.1.3 창과 코드가 만드는 차이

| 조건 | 값 | 차이 |
| --- | ---: | ---: |
| `2117c58b`, 11-06 창 | 21,590 | 기준 |
| `2117c58b`, 11-07 창 | 21,531 | −59 |
| `72baaa01`, 11-07 창 | 21,590 | +59 (코드 +56, 대표 선정 +3) |

창 이동 −59는 2025-11-06 적용 59건이 빠지고 2026-11-07 적용 0건이 들어온 결과입니다(2026-11-07 공고는 DB에 없습니다). 코드 이동 +56은 `2117c58b` → `72baaa01` 사이의 규칙·해석 변경이고, 선정 전 필터 적용으로 대표 공고가 달라져 +3이 더해집니다.

#### 2.1.4 남는 44건: 감사 시점의 DB 스냅샷

감사 커밋 코드(`2117c58b`)로 같은 창을 오늘 다시 돌리면 21,590 이 나옵니다. 감사 문서의 21,546 과의 차이 44건은 **2026-11-06 하루치 접수분** 안에 있습니다.

| 항목 | 감사 문서 | 오늘 재현 | 차이 | 2026-11-06 하루치 최종값 |
| --- | ---: | ---: | ---: | ---: |
| 대표 공고 | 192,191 | 192,749 | 558 | 609 |
| 규칙 적용 | 21,546 | 21,590 | 44 | 57 |
| 불일치 | 1,184 | 1,184 | 0 | 0 |

- 감사 시점에는 2026-11-06 접수분 609건 가운데 51건(적용 13건)만 있었고, 나머지 558건(적용 44건)이 나중에 들어왔다는 뜻입니다.
- 그날 적용 57건의 불일치가 0건이므로, 44건이 늦게 들어와도 불일치 1,184 는 그대로 유지됩니다. 그래서 감사 문서의 21,546 과 1,184 는 서로 모순이 아닙니다.
- `collected_at` 을 보면 2026-11-06 접수분은 2026-11-07 03:48:51 배치에 들어 있습니다. `collected_at` 은 마지막 수집 시각이라 최초 수집 시점을 복원할 수는 없습니다. 그래서 21,546 을 그대로 다시 만드는 것은 `부분` 재현입니다.

**판정**: 원인은 (가) 계산 시점입니다. 창·필터·코드가 아닙니다. 21,590 은 method 문서의 별개 측정값이고, 감사 창을 오늘 같은 코드로 재현한 값과 우연히 같습니다.

#### 2.1.5 재현 명령

```sh
# 감사 창(11-06) 재현. 코드 리비전은 2.1.4절 스크립트의 REV 로 바꿉니다.
uv run python scripts/db_readonly_query.py --format json --limit 0 --sql "SELECT COUNT(*) AS announcements FROM (SELECT bid_ntce_no, category FROM bid_announcements WHERE category='Servc' AND bid_ntce_dt >= '2025-11-06' AND bid_ntce_dt < '2026-11-07' AND JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.sucsfbidMthdCd'))='낙030001' GROUP BY bid_ntce_no, category) t"
```

적용 건수와 불일치는 판정 함수를 거쳐야 하므로 부록 A.1 의 스크립트로 셉니다.

### 2.2 규칙값·공고값 불일치: 1,184 대 1,142

#### 2.2.1 측정 조건

두 값 모두 적용 정의가 같습니다. 공고값 `raw_data.sucsfbidLwltRate` 와 규칙이 선언한 값(구간 인쇄값이 있으면 그 값, 없으면 대표값)을 소수 3자리로 비교하고, 규칙값이 없는 건은 비교에서 뺍니다.

| 문서·절 | 기준일 | 창 | 필터 | 코드 | 값 |
| --- | --- | --- | --- | --- | ---: |
| 감사 1절 | 2026-11-06 | 2025-11-06~2026-11-06 | 없음 | `2117c58b` 계열 | 1,184 |
| method 3.1절 | 2026-11-07 | 2025-11-07~2026-11-07 | `낙030001` | `72baaa01` | 1,142 |

#### 2.2.2 코드 리비전별 측정

| 코드 리비전 | 커밋 요지 | 11-06 창 불일치 | 11-07 창 불일치 |
| --- | --- | ---: | ---: |
| `2117c58b` | 감사 문서 커밋 | **1,184** | 1,181 |
| `49ed4d78` | 지방공기업 특수법인을 조달청 경로로 해석 | 1,186 | 1,183 |
| `15d7e873` | PPS 2억미만 1억이상 띠 학술연구 구제 추가 | 1,167 | 1,164 |
| `3b37288e` | 경북 폐기물(2026) 대표 하한율 정정 | 1,143 | 1,140 |
| `72baaa01` | gb-waste 병합 | 1,145 | **1,142** |
| `00e963f3` = `HEAD` | 조달청 기준 인용 지방공기업을 기관 단위로 이동 | 1,128 | 1,125 |

#### 2.2.3 차이 분해

| 단계 | 값 | 차이 | 원인 |
| --- | ---: | ---: | --- |
| `2117c58b`, 11-06 창 | 1,184 | 기준 | 감사 문서 값 |
| `2117c58b`, 11-07 창 | 1,181 | −3 | (나) 창 정의 |
| `72baaa01`, 11-07 창 | 1,142 | −39 | (라) 코드 변경 |
| `72baaa01`, 11-07 창, 필터 적용 | 1,142 | 0 | 필터 영향 없음 |

코드 변경 −39는 주로 `15d7e873`(−19)와 `3b37288e`(−24)이고, `49ed4d78`·`72baaa01` 의 증가분(+4)이 일부 상쇄했습니다. method 문서 부록 B.6 은 차이 원인으로 "낙찰방법 코드 필터, 기준일, 규칙 인쇄값 비교 방식"을 들었지만, 재현 결과 **필터 0건, 기준일 −3건, 비교 방식 0건**이고 나머지 −39건은 코드 리비전 차이입니다.

**판정**: 원인은 (라) 코드 변경이 지배적이고 (나) 창 정의가 보조적입니다.

#### 2.2.4 재현 명령

부록 A.1 의 스크립트에서 `REV` 와 기준일을 바꿔 실행합니다. `72baaa01`·2026-11-07·`낙030001` 조합이 `31,325 / 21,590 / 1,142` 를 냅니다.

### 2.3 전체 창 공고 수: 31,428 대 31,325

#### 2.3.1 측정 조건

| 문서·절 | 기준일 | 창 | 업무구분 | 필터 | 값 |
| --- | --- | --- | --- | --- | ---: |
| entity 4절·문서 머리말 | 2026-11-06 | 2025-11-06~2026-11-06 | `Servc` | `낙030001` | 31,428 |
| method 3.1절 | 2026-11-07 | 2025-11-07~2026-11-07 | `Servc` | `낙030001` | 31,325 |
| not_computable 1절 | (원장 인용) | 원장 `filter.window_from=2025-11-07` | `Servc` | `낙030001` | 31,325 |

`data/reference/rule_coverage_ledger.yaml` 의 `filter` 블록도 `window_from: '2025-11-07'`, `window_to: '2026-11-07'`, `method_code: 낙030001`, `totals.announcements: 31325` 로 같습니다.

#### 2.3.2 차이 103건의 정체

| 경계일 | 대표 공고 | 처리 |
| --- | ---: | --- |
| 2025-11-06 | 103 | 감사 창에만 포함되어 빠짐 |
| 2026-11-07 | 0 | method 창에만 포함되어 들어오지만 DB에 없음 |
| 순변화 | −103 | 31,428 − 103 = 31,325 |

두 문서 모두 같은 필터와 같은 대표 공고 규칙(공고번호·업무구분별 최신 차수)을 썼습니다. 오직 기준일과 창의 양 끝만 다릅니다. 대표 공고 원행 수는 37,506 → 37,391 입니다.

**판정**: 원인은 (나) 창 정의입니다. 결정 백로그가 이미 `불일치(창 상이)`로 표시한 그대로입니다.

#### 2.3.3 재현 명령

```sh
# 감사 창: 31,428
uv run python scripts/db_readonly_query.py --format json --limit 0 --sql "SELECT COUNT(*) AS announcements FROM (SELECT bid_ntce_no, category FROM bid_announcements WHERE category='Servc' AND bid_ntce_dt >= '2025-11-06' AND bid_ntce_dt < '2026-11-07' AND JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.sucsfbidMthdCd'))='낙030001' GROUP BY bid_ntce_no, category) t"

# method·원장 창: 31,325
uv run python scripts/db_readonly_query.py --format json --limit 0 --sql "SELECT COUNT(*) AS announcements FROM (SELECT bid_ntce_no, category FROM bid_announcements WHERE category='Servc' AND bid_ntce_dt >= '2025-11-07' AND bid_ntce_dt < '2026-11-08' AND JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.sucsfbidMthdCd'))='낙030001' GROUP BY bid_ntce_no, category) t"
```

### 2.4 13건 공고값: 13건 전부 82.495 대 1번 87.745

#### 2.4.1 실제 값

13건은 감사 4.6절의 기관 규칙 불일치 목록입니다. 공고값은 둘로 갈립니다.

| 구분 | 공고번호 | 공고일 | 낙찰방법명 | 공고값 |
| --- | --- | --- | --- | ---: |
| 나머지 12건 | `R26BK01634862`·`R26BK01730527`·`R26BK01745985`·`R26BK01761398`·`R26BK01764999`·`R26BK01766196`·`R26BK01764484`·`R26BK01768949`·`R26BK01784481`·`R26BK01793057`·`R26BK01793641`·`R26BK01813749` | 2026-07-15 ~ 2026-11-05 | 기관 별표 세부유형 표기 | 82.495 |
| 1건 | `R26BK01369593` | 2026-03-04 | `적격심사제-추정가격 2억원 미만인 용역` | **87.745** |

#### 2.4.2 어느 문서가 무엇을 셌는가

| 문서·절 | 서술 | 판정 |
| --- | --- | --- |
| kdhc 1.2절 2번 | "2026-08-18판 … 하한율 대입값은 82.495·86.245입니다. 13건의 공고값 82.495와 일치합니다" | 13건을 단일 값으로 봄. 1건 때문에 틀림 |
| kdhc 4.3절 표 | 마지막 열 이름이 `13건 공고값`, 모든 행 82.495 | 같은 단일화. 표 행은 판본·별표 조합이라 13건 개별 대응이 아님 |
| inst 1.1절 | 13행을 공고번호별로 적고 1번을 87.745 로 표기 | 정본 |
| inst 1.3절 3번 | 1번은 "공고가 기관 세부기준 밖의 띠를 적용"했고 87.745 는 조달청 일반용역 2억원 미만 띠 값 | 원인 설명 |

#### 2.4.3 원인

`R26BK01369593` 은 2026-08-18판 시행 전(2026-03-04) 공고이고, 첨부도 기관 세부기준이 아니라 환경부 고시입니다. 낙찰방법명도 세부유형이 없는 `추정가격 2억원 미만인 용역` 입니다. 87.745 는 조달청 일반용역 2억원 미만 띠 규칙(`SERVC_QUAL_POST_20260526_ATTACH_12`)의 값과 같습니다. inst 1.3절 3번이 같은 판정을 적고 있습니다.

따라서 kdhc 문서의 "13건 전부 82.495" 는 **판본별 계수 대입값(82.495·86.245)으로 설명되는 12건과, 기관 판본 밖의 별건 1건을 한 모집단으로 묶은 정의 오류**입니다. 13건 집합 자체는 감사 4.6절의 기관 규칙 불일치 목록이 맞고, 값만 12 대 1로 갈립니다.

**판정**: 원인은 (다) 모집단 정의입니다. (가) 기준일은 1번이 2026-08-18판 시행 전이라는 사실을 설명하는 보조 조건입니다.

#### 2.4.4 재현 명령

```sh
uv run python scripts/db_readonly_query.py --format json --limit 0 --sql "SELECT bid_ntce_no, bid_ntce_ord, bid_ntce_dt, JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.sucsfbidLwltRate')) AS lwlt, JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.sucsfbidMthdNm')) AS mthd FROM bid_announcements WHERE category='Servc' AND bid_ntce_no IN ('R26BK01369593','R26BK01634862','R26BK01730527','R26BK01745985','R26BK01761398','R26BK01764999','R26BK01766196','R26BK01764484','R26BK01768949','R26BK01784481','R26BK01793057','R26BK01793641','R26BK01813749') ORDER BY bid_ntce_no, bid_ntce_ord"
```

---

## 3. 문서 갱신 제안 (고치지 않음)

| 문서·절 | 현재 표기 | 제안 표기 | 근거 |
| --- | --- | --- | --- |
| decision_backlog 1.3절 1행 | 21,546 과 21,590 을 `불일치`로 병기 | "감사 21,546 은 2026-11-06 수집 완료 전 스냅샷, method 21,590 은 별개 측정"으로 각주 | 2.1.4절. 차이 44건이 2026-11-06 접수분 안에 있음 |
| decision_backlog 1.3절 2행 | 원인 표기 없음 | "코드 리비전 차이 −39, 창 차이 −3" 명시 | 2.2.3절 |
| decision_backlog 1.3절 3행 | `불일치(창 상이)` 유지 | 유지. 103건 = 2025-11-06 제외 + 2026-11-07 0건 추가 각주 | 2.3.2절 |
| decision_backlog 1.3절 4행 | 13건 전부 대 1번 87.745 | "12건 82.495, 1건 87.745"로 정정 | 2.4.1절 |
| method 3.1절 | "낙찰방법 코드 필터 유무와 기준일 차이" | "낙찰방법 필터는 적용·불일치 건수에 영향 없음. 기준일 −3, 코드 리비전 −39" | 2.1.2·2.2.3절 |
| method 부록 B.6 | 필터·기준일·비교 방식 세 가지를 원인으로 나열 | 필터 0, 기준일 −3, 비교 방식 0, 코드 리비전 −39 | 2.2.3절 |
| pps 4.2절 | 21,546 을 자체 창의 값처럼 서술 | "감사 문서 1절 인용"임을 명시 | 2.1.1절. pps 창은 2025-11-06~2026-11-05 |
| kdhc 1.2절 2번·4.3절 | "13건의 공고값 82.495" | "12건 82.495, 1건(`R26BK01369593`) 87.745, 라벨 (다)" | 2.4.3절 |
| inst 1.1절·1.3절 | 이미 공고별 값과 1번 예외를 적음 | 유지(정본) | 2.4.2절 |

`data/reference/rule_coverage_ledger.yaml` 은 31,325 와 `window_from 2025-11-07` 을 이미 정확히 적고 있으므로 갱신 대상이 아닙니다.

---

## 4. 한계

1. **감사 스냅샷 미보존**: 21,546 을 만든 DB 상태는 남아 있지 않습니다. 44건·558건이 2026-11-06 접수분 범위 안에 있다는 산술 복원까지만 확인했고, 값 자체를 다시 만들지는 못했습니다(`부분`).
2. **`collected_at` 은 마지막 수집 시각**입니다. 2026-11-06 접수분이 2026-11-07 03:48:51 배치에 몰려 있어 최초 수집 시점은 복원되지 않습니다.
3. **과거 코드 재현 방식**: `git show <rev>:src/app/services/*.py` 로 해당 리비전의 5개 모듈(`evaluation_rules_core`, `evaluation_rules_local`, `evaluation_rules_institution`, `evaluation_rules`, `demand_institutions`)을 메모리에 적재해 실행했습니다. 저장소 파일은 바꾸지 않았습니다.
4. **DB 상태 기준일**: 모든 재현은 2026-11-07 현재 `bid_announcements` 기준입니다. 이후 수집이 과거 공고일 행을 추가하면 공고 수는 다시 달라질 수 있습니다.
5. **13건 밖 기관 규칙**: 이 문서는 감사 4.6절의 13건만 다룹니다. inst 1.4절이 적은 표 밖 2건은 다루지 않았습니다.

---

## 부록 A. 재현 스크립트

### A.1 적용 건수·불일치 재현

`REV` 와 `TODAY` 만 바꿔 실행합니다. `REV=72baaa01`, `TODAY=2026-11-07`, `METHOD=낙030001` 이 method 문서의 `31,325 / 21,590 / 1,142` 를 냅니다.

```python
import importlib.util, subprocess, sys, types
from datetime import date, datetime, timedelta
from datetime import time as day_time
from decimal import Decimal
from pathlib import Path

REV = "2117c58b"           # 2117c58b, 49ed4d78, 15d7e873, 3b37288e, 72baaa01, 00e963f3
TODAY = date(2026, 11, 6)  # 2026-11-06, 2026-11-07
METHOD = ""                # "" 또는 "낙030001"
SERVICES = [
    "evaluation_rules_core.py", "evaluation_rules_local.py",
    "evaluation_rules_institution.py", "evaluation_rules.py", "demand_institutions.py",
]

# 과거 리비전 모듈을 메모리에 적재합니다. 저장소 파일은 바꾸지 않습니다.
for rel in SERVICES:
    name = "src.app.services." + rel[:-3]
    sys.modules.pop(name, None)
    src = subprocess.check_output(["git", "show", f"{REV}:src/app/services/{rel}"], text=True)
    mod = types.ModuleType(name)
    mod.__file__ = f"src/app/services/{rel}"
    mod.__package__ = "src.app.services"
    sys.modules[name] = mod
    exec(compile(src, mod.__file__, "exec"), mod.__dict__)

spec = importlib.util.spec_from_file_location("rrc", Path.cwd() / "scripts/report_rule_coverage.py")
rrc = importlib.util.module_from_spec(spec)
sys.modules["rrc"] = rrc
spec.loader.exec_module(rrc)
er = sys.modules["src.app.services.evaluation_rules"]

from sqlalchemy import text
from src.app.core.db import engine

window_from = rrc._months_ago(TODAY, 12)
window_end = TODAY + timedelta(days=1)
sql = rrc.ANNOUNCEMENT_SQL.replace("SELECT bid_ntce_no,", "SELECT bid_ntce_dt, bid_ntce_no,", 1)

# 필터를 먼저 걸고, 같은 공고번호·업무구분의 최신 차수만 대표로 남깁니다.
best_rows, current_key, best_row, best_ord = [], None, None, -1
with engine.connect() as conn:
    conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
    institutions = rrc._load_institutions(conn)
    result = conn.execution_options(stream_results=True).execute(
        text(sql),
        {"category": "Servc",
         "window_from": datetime.combine(window_from, day_time.min),
         "window_end": datetime.combine(window_end, day_time.min)},
    )
    for row in result:
        raw = rrc._as_dict(row.raw_data)
        if METHOD and str(raw.get("sucsfbidMthdCd") or "").strip() != METHOD:
            continue
        key = (row.bid_ntce_no, row.category)
        if key != current_key:
            if best_row is not None:
                best_rows.append(best_row)
            current_key, best_row, best_ord = key, None, -1
        ord_key = rrc._ord_key(row.bid_ntce_ord)
        if best_row is None or ord_key > best_ord:
            best_row, best_ord = row, ord_key
    if best_row is not None:
        best_rows.append(best_row)
    result.close()
    regimes = rrc.lookup_attachment_regimes(
        conn, (rrc.attachment_regime_key(row) for row in best_rows)
    )

applied = comparable = mismatch = 0
for row in best_rows:
    raw = rrc._as_dict(row.raw_data)
    record = rrc._to_record(row, institutions, regimes.get(rrc.attachment_regime_key(row)))
    res = record.get("result")
    if res is None or res.is_blocked or res.rule is None:
        continue
    applied += 1
    notice = str(raw.get("sucsfbidLwltRate") or "").strip()
    if not notice:
        continue
    band, _label, _reason = er._band_lwlt_rate(res.rule, er._normalized_price(row.presmpt_prce))
    rule_rate = band if band is not None else res.rule.lwlt_rate
    if rule_rate is None:
        continue
    comparable += 1
    if Decimal(notice).quantize(Decimal("0.001")) != rule_rate.quantize(Decimal("0.001")):
        mismatch += 1

print({"rev": REV, "today": str(TODAY), "window_from": str(window_from),
       "announcements": len(best_rows), "applied": applied,
       "comparable": comparable, "mismatch": mismatch})
```

### A.2 2026-11-06 접수분 분해

같은 스크립트에서 `row.collected_at` 을 함께 읽어 `2026-11-06` 공고일 행만 세면 609건·적용 57건·불일치 0건입니다. 감사 문서의 21,546 과 오늘 재현 21,590 의 차이 44건, 공고 192,191 과 192,749 의 차이 558건이 모두 이 하루치 안에 들어갑니다.

### A.3 검증 명령

```sh
uv run pytest tests/test_validate_doc_links.py -q
python3 scripts/validate_agent_rules.py --quiet
```
