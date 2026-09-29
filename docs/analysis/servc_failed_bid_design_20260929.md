# 유찰 공고 분모 제외를 위한 개찰결과 API 수집 설계안 및 효과 실측 (2026-09-29)

> **작성일**: 2026-09-29
> **작성자**: Orca builder worker (task_b358e9a9b465)
> **기준 커밋**: `5cb07507`
> **기준 시각**: 2026-09-29 Asia/Seoul
> **범위**: 조달청 개찰결과 목록 API 실측, 유찰 분모 제외 효과 실측(표본), 저장 설계 대안, 수집 통합 지점, 구현 Task 분할
> **변경 없음**: 코드·설정·DB·스키마를 변경하지 않았습니다. 모든 값은 읽기 전용 조회와 조달청 API 직접 호출 결과입니다.
> **질의 방법**: DB 는 `uv run python scripts/db_readonly_query.py --sql "<질의>"`, API 는 워커 컨테이너에서 `get_service_key()` 로 키를 읽어 호출합니다. 인증키·요청 전체 URL·개인 정보(대표자명)는 기록하지 않습니다.

---

## 1. 요약 (결론)

1. **개찰결과 API 는 유찰을 돌려준다.** 조달청 `ScsbidInfoService` 의 개찰결과 목록 오퍼레이션(`getOpengResultListInfoServc`/`Thng`/`Cnstwk`/`Frgcpt`)은 `progrsDivCdNm`(개찰완료·유찰·재입찰)과 `prtcptCnum`(참가업체수)을 함께 준다. 저장소가 쓰는 낙찰현황 API(`getScsbidListSttus<분류>`)가 낙찰자 있는 건만 주는 것과 달리, 이 API 는 유찰 건을 구조적으로 포함한다.
2. **유찰은 분모에서 큰 비중을 차지한다.** 개찰 2026-08-10~2026-08-30(성숙 3주), 추정가격 2.3억 이상, 취소공고 행 제외 모집단에서 미매칭 공고를 분류별 60건씩 무작위 표본으로 개찰결과 API 로 판정했다. 표본 유찰 비율(행 기준)은 Servc 49.2%, Cnstwk 7.4%, Thng 68.3% 다.
3. **대형 매칭률 변화 추정(외삽)은 Servc +16.8%p, Thng +25.5%p, Cnstwk +1.5%p 다.** Servc 대형은 42.5% 에서 59.3% 로 올라 2026-09-28 다주 기저 51.2% 를 넘어서므로, 유찰을 분모에서 빼면 반복 경고가 소멸하는 방향이다.

   > **코디네이터 정정 (2026-09-29)**: 이 비교는 현재 주에서만 유찰을 뺀 추정치(59.3%)를 유찰을 빼지 않은 다주 기저(51.2%)와 견준 것이라 경고 소멸의 근거가 되지 못합니다. 매칭률 감시는 현재와 기저에 같은 규칙을 대칭 적용하므로, 기저에서도 유찰을 빼면 기저가 함께 오릅니다. 같은 날 오프라인 입찰 제외(E1)를 대칭으로 계산하자 용역 대형 격차가 오히려 벌어졌습니다(08-24 현재 41.0에서 47.3, 기저 49.5에서 60.4). 유찰 제외의 경고 영향은 전년 기저 주의 유찰 비율을 같은 방식으로 재야 판단할 수 있습니다. 유찰 비율이 크다는 실측과 저장 설계 비교는 유효합니다.
4. **저장은 새 테이블(대안 A)을 권고한다.** `bid_results` 에 유찰 행을 넣는 안(C)은 낙찰결과 테이블의 의미를 바꾸므로 G1 위반이고, Redis 캐시 단독(B)은 백필·감사가 불가하다.
5. **비용은 작다.** 일일 증분 수집은 3회/일(3 분류 각 1페이지), 12주 백필은 약 96회다. 공고번호별 조회 방식(3주 1,520회)보다 날짜 창 일괄 방식이 압도적으로 싸다.

---

## 2. 조사 방법과 API 호출 원장

| 항목 | 내용 |
| --- | --- |
| 코드 정본 | `src/app/services/api_collector.py`(수집기), `src/app/services/collector_service.py`(수집 실행·클램프), `src/app/services/result_coverage.py`(매칭률·경고), `src/app/models/bids.py`(테이블 정의), `src/tasks/automation_steps.py`(수집 스텝), `src/tasks/scheduled_tasks.py`·`src/tasks/coverage_tasks.py`(크론) |
| DB | `uv run python scripts/db_readonly_query.py` 로 SELECT 만 실행. 쓰기 없음 |
| API | 워커 컨테이너에서 `src.app.services.api_collector.get_service_key()` 로 키를 읽어 `httpx` 로 호출. 호출 사이 0.25~0.3초 대기 |
| 개인정보 | `opengCorpInfo` 원문은 출력·기록하지 않고 `progrsDivCdNm`·`prtcptCnum`·`bidNtceNo`·`bidNtceOrd` 만 사용 |

### 2.1 API 호출 원장 (총 330회, 계약 상한 400회 이내)

| 계열 | 용도 | 호출 수 |
| --- | --- | ---: |
| A | 분류별 엔드포인트 존재·`inqryDiv` 축·날짜 창·페이지 상한·상태값 실측 | 24 |
| B | 표본 유찰 판정(3 분류 x 60건) | 180 |
| C | 표본 재집계(Cnstwk·Servc 120건, 출력 잘림으로 집계 재확보) | 120 |
| D | 15일 창 물량(totalCount) 측정 | 6 |
| 합계 | | **330** |

- 계열 C 는 계열 B 의 첫 실행에서 표준출력이 잘려 집계 줄을 놓쳐 재실행한 것입니다. 판정 규칙은 동일합니다.
- 분류별 표본은 DB 선택 질의 결과에 `MD5(CONCAT('fb20260929', bid_ntce_no))` 정렬로 60건을 뽑아 재현 가능하게 고정했습니다(4.2절).

---

## 3. 개찰결과 API 실측 (조사 항목 1·2)

### 3.1 오퍼레이션과 응답 필드

| 분류 | 오퍼레이션 | 2026-08-18 1일 창 totalCount | resultCode |
| --- | --- | ---: | :---: |
| 용역 | `getOpengResultListInfoServc` | 590 | 00 |
| 물품 | `getOpengResultListInfoThng` | 531 | 00 |
| 공사 | `getOpengResultListInfoCnstwk` | 364 | 00 |
| 외자 | `getOpengResultListInfoFrgcpt` | 3 | 00 |

- 네 오퍼레이션 모두 정상 응답하며 응답 필드 16개가 동일합니다: `bidClsfcNo`, `bidNtceNm`, `bidNtceNo`, `bidNtceOrd`, `dminsttCd`, `dminsttNm`, `inptDt`, `ntceInsttCd`, `ntceInsttNm`, `opengCorpInfo`, `opengDt`, `opengRsltNtcCntnts`, `progrsDivCdNm`, `prtcptCnum`, `rbidNo`, `rsrvtnPrceFileExistnceYn`.
- `bidNtceOrd` 는 3자리(`000`)로 내려와 기존 `bid_announcements` 차수 규칙과 맞습니다.

### 3.2 `inqryDiv` 값별 동작 (실측)

2026-08-18 하루 창(inqryBgnDt=`202608180000`, inqryEndDt=`202608182359`), Servc, `numOfRows=999` 기준입니다.

| inqryDiv | totalCount | 응답에서 창 안에 든 축 | 해석 |
| :---: | ---: | --- | --- |
| 1 | 590 | `inptDt` 590/590 이 2026-08-18 | 입력일시(등록일시) 기준 |
| 2 | 535 | `opengDt` 27/535, `inptDt` 21/535 만 08-18 | 응답에 없는 축(입찰공고게시일시) 기준 |
| 3 | 634 | `opengDt` 634/634 가 2026-08-18 | 개찰일시 기준 |
| 4 | (없음) | `bidNtceNo` 필수. 없이 호출하면 resultCode·totalCount 없음 | 공고번호 기준 |

- `inqryDiv=2` 축 확인: DB 에 결과가 있는 `R26BK01617066`(공고게시일 2026-07-06, 개찰일 2026-08-18)을 창 `20260706` 로 조회하면 검출되고(총 570건), 창 `20260818` 로 조회하면 미검출(총 535건)입니다. `inqryDiv=3` 은 반대입니다(창 `20260706` 미검출 522건, 창 `20260818` 검출 634건). 따라서 2는 입찰공고게시일시, 3은 개찰일시입니다.

### 3.3 날짜 창과 페이지 상한

| 항목 | 실측 | 근거 |
| --- | --- | --- |
| 1일 창 | `inqryDiv` 1·2·3 + `inqryBgnDt`/`inqryEndDt`(YYYYMMDDHHMM) 로 하루(`0000`~`2359`) 조회 가능 | 3.2절 3개 창 모두 데이터 반환 |
| 15일 창 | 동일 파라미터로 15일 창 조회 가능 | 4.4절 totalCount(예: Servc 5,185) |
| 페이지 상한 | `numOfRows` 최대 999. 1,000·2,000 은 10건만 반환(상한 초과 시 기본값) | 3.4절 |
| 페이징 | `pageNo` 로 다음 페이지. 590건은 999행 1페이지로 전량 반환 | 3.4절 |

### 3.4 페이지 상한 확인 (Servc, 2026-08-18 1일 창, totalCount 590)

| numOfRows | totalCount | 반환 건수 |
| ---: | ---: | ---: |
| 999 | 590 | 590 |
| 1000 | 590 | 10 |
| 2000 | 590 | 10 |

### 3.5 `progrsDivCdNm` 값 목록과 의미 (2026-08-18 1일 창, inqryDiv=1)

| 분류 | 조회 건수 | 개찰완료 | 유찰 | 재입찰 |
| --- | ---: | ---: | ---: | ---: |
| Servc | 590 | 411 | 166 | 13 |
| Thng | 531 | 313 | 209 | 9 |
| Cnstwk | 364 | 352 | 6 | 6 |

- 값은 3종입니다. **개찰완료**는 낙찰자가 정해진 상태, **유찰**은 낙찰자가 없는 상태, **재입찰**은 재공고/재입찰 상태입니다.
- **유찰은 "참가 0" 만이 아닙니다.** 표본(4.2절)에서 `progrsDivCdNm=유찰` 이면서 `prtcptCnum>0` 인 건이 Cnstwk 4/4, Servc 1/30, Thng 3/40 있었습니다. 즉 유찰은 "무응찰"과 "참가했으나 낙찰자 없음(예정가격 초과·전원 부적격 등)"을 함께 뜻하므로, 분모 제외 판정은 `progrsDivCdNm` 으로 하고 `prtcptCnum` 은 보조 지표로만 쓰는 것이 맞습니다.

---

## 4. 유찰 분모 제외 효과 실측 (조사 항목 3)

### 4.1 모집단 (실측)

개찰 2026-08-10~2026-08-30(성숙 3주), 추정가격 2.3억 이상, 취소공고 행 제외. 대형 기준은 `src/app/services/result_coverage.py` 의 `LARGE_PRICE_THRESHOLD = 230_000_000` 입니다.

| 분류 | 공고 행(분모) | 매칭 | 매칭률 | 미매칭 행 | 미매칭 공고번호(취소공고 차수 보유분 제외) | 미매칭 행(동) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Servc | 1,466 | 623 | 42.5% | 843 | 621 | 689 |
| Cnstwk | 1,375 | 1,001 | 72.8% | 374 | 203 | 226 |
| Thng | 1,460 | 750 | 51.4% | 710 | 541 | 605 |

- 매칭은 `result_coverage.py` 정본과 같이 (공고번호, 분류, 정규화 차수)로 `bid_results` 존재 여부를 봅니다.
- 미매칭 행은 취소공고 행만 뺀 값(843·374·710)이고, 그중 공고번호에 취소공고 차수가 하나라도 있는 건(154·148·105행)을 빼면 순수 후보(689·226·605)가 됩니다.

### 4.2 표본 방법 (재현 가능)

- 순수 미매칭 공고번호(621·203·541)에서 분류별 60건을 `MD5(CONCAT('fb20260929', bid_ntce_no))` 오름차순으로 뽑습니다. 시드가 고정되어 재실행 시 같은 표본이 나옵니다.
- 각 공고번호를 개찰결과 API 로 `inqryDiv=4`(공고번호) 조회해 `progrsDivCdNm` 를 읽습니다. 응답에 `유찰` 이 포함되면 유찰로 판정합니다.
- 판정 단위는 공고번호이고, 분모 환산에는 그 공고번호의 미매칭 행 수를 가중치로 씁니다.

### 4.3 표본 결과 (실측)

| 분류 | 표본 공고번호 | 표본 행 | 유찰 공고번호 | 유찰 행 | 개찰완료 | 결과 없음 | 재입찰만 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Servc | 60 | 65 | 30 (50.0%) | 32 (49.2%) | 16 | 14 | 0 |
| Cnstwk | 60 | 68 | 4 (6.7%) | 5 (7.4%) | 53 | 3 | 0 |
| Thng | 60 | 63 | 40 (66.7%) | 43 (68.3%) | 13 | 7 | 0 |

- "결과 없음"은 응답이 0건인 건으로, 직찰·설계공모·취소 등 나라장터 전자개찰 대상이 아닌 경우입니다(선행 대조표 4.1절과 같은 해석).
- "개찰완료"는 낙찰자가 정해졌으나 DB 반영이 늦은 지연 성분입니다. 유찰과 달리 분모에서 빼지 않습니다.

### 4.4 매칭률 변화 추정 (표본 외삽, 추정)

표본이 모집단 미매칭 행 전체를 대표한다고 보고 외삽한 값입니다. **추정이며 실측이 아닙니다.**

- 미매칭 행 = 공고 행 - 매칭
- 유찰률(행 가중) = 표본 유찰 행 / 표본 행
- 추정 유찰 행 = 미매칭 행 x 유찰률
- 새 분모 = 공고 행 - 추정 유찰 행, 새 매칭률 = 매칭 / 새 분모

| 분류 | 현재 매칭률(실측) | 유찰률(표본 실측) | 추정 유찰 행 | 새 분모(추정) | 새 매칭률(추정) | 변화(추정) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Servc | 42.5% | 32/65 = 49.2% | 415 | 1,051 | 59.3% | +16.8%p |
| Cnstwk | 72.8% | 5/68 = 7.4% | 28 | 1,348 | 74.3% | +1.5%p |
| Thng | 51.4% | 43/63 = 68.3% | 485 | 975 | 76.9% | +25.5%p |

### 4.5 서비스 경고에 대한 함의

- 2026-09-28 기준 Servc 대형 경고는 보정 38.5% / 다주 기저 51.2% 입니다(`docs/analysis/servc_upstream_recheck_20260928.md` 4.5절). 이번 창의 Servc 대형 실측 42.5% 는 같은 구간대이고, 유찰을 분모에서 빼면 추정 59.3% 로 기저를 넘습니다. **경고는 수집 결함이 아니라 분모 구성(유찰·직찰·협상 지연) 때문**이라는 대조표 4.1절 판단과 일치합니다. (기저 비대칭 비교라는 한계는 1절 코디네이터 정정 참조)
- Thng 는 효과가 가장 큽니다(+25.5%p). 물품은 무응찰·예정가격 초과 유찰이 많은 것으로 보입니다(3.5절 Servc 166 대비 Thng 209, 08-18 1일 기준).
- Cnstwk 는 유찰률 7.4% 로 영향이 작습니다.

### 4.6 한계 (모두 추정·표본)

- 유찰률은 분류별 60건 표본 외삽입니다. 95% 신뢰구간을 붙이면 Servc 표본 30/60 은 약 37~63% 로 넓어, 새 매칭률 추정도 흔들립니다. 실측 확정은 개찰결과를 전량 수집한 뒤 재계산해야 합니다.
- 표본은 "취소공고 차수를 가진 공고번호"를 제외한 순수 미매칭 모집단에서 뽑았습니다. 분모에는 그 154·148·105행이 남아 있어, 표본 비율을 전체 미매칭 행에 그대로 곱하면 약간 과대/과소 추정이 생길 수 있습니다.
- 공고번호 단위 판정이라, 한 공고번호에 유찰 차수와 비유찰 차수가 섞인 경우 그 행 전체를 유찰로 셌습니다. 표본 대부분이 행 1개라 영향은 작지만 0 은 아닙니다.
- 개찰결과 API 는 `inqryDiv=4` 로 공고번호를 지정해도 차수별 여러 행을 줍니다. 구현 시 차수까지 맞춰 행 단위로 판정해야 이 오차가 사라집니다.

---

## 5. 저장 설계 대안 비교 (조사 항목 4)

### 5.1 대안

| 대안 | 방식 | 마이그레이션 | G1 판정 | 장점 | 단점 |
| --- | --- | :---: | :---: | --- | --- |
| **A. 새 테이블 `bid_openg_results`** | 분류·공고번호·차수·`progrsDivCdNm`·`prtcptCnum`·`opengDt`·`raw_data` 저장 | 필요(신규 리비전) | **안전** | 영속·백필·재현·감사 가능, 기존 테이블 무변경, 매칭률 재계산에 조인 | 신규 테이블·인덱스 추가, 조인 비용 |
| B. Redis 캐시만 | 공고번호 -> 상태를 TTL 캐시 | 불필요 | 안전 | 즉시 도입, DB 무변경 | 휘발성(TTL·재시작 시 소실), 백필·이력·감사 불가, 매칭률 계산이 캐시 미스에 취약 |
| C. `bid_results` 에 유찰 행 삽입 | 낙찰결과 테이블에 낙찰자 없는 행 추가 | 불필요(스키마 동일) | **위반** | 테이블 1개 | 아래 5.2 |

### 5.2 대안 C 는 G1 위반이다

- **컬럼·의미 불변 위반**: `bid_results` 는 `comment="낙찰 결과 테이블"` 이고 `bidwinnr_nm`·`sucsf_bid_amt`·`sucsf_bid_rate`(낙찰업체·낙찰금액·낙찰률)를 담습니다(AGENTS.md 3.5, `src/app/models/bids.py`). 유찰 행은 이 셋이 모두 NULL 이므로 테이블의 의미가 "낙찰 결과"에서 "개찰 결과"로 바뀝니다.
- **유니크 제약 충돌**: `bid_results` 는 (공고번호, 차수, 분류) 유니크입니다. 000 차수가 유찰이면 그 자리를 유찰 행이 차지해, 뒤에 도착하는 같은 차수의 낙찰 결과(낙찰자가 뒤늦게 정해지는 협상 케이스)를 저장할 수 없습니다.
- **하류 오염**: RAG 정형 집계, `compare_stats_snapshots`, 기관별 낙찰률(`institution_win_rate_stats`), 챗봇 통계가 모두 `bid_results` 를 낙찰 통계로 읽습니다. 낙찰률 평균·합계금액에 NULL 행이 섞이면 값이 왜곡됩니다.
- **ML 경로**: `src/ml/dataset.py` 는 `bid_results` 를 라벨 원천으로 조인하며 `sucsf_bid_rate.is_not(None)` 로 거릅니다(같은 파일 230행). 유찰 행은 걸러지지만, "낙찰결과 테이블"이라는 정의가 흔들리면 train/serve 정의가 갈릴 위험이 있습니다(AGENTS.md 3.6).

### 5.3 변형안 (비권고)

- **D. `bid_announcements` 에 상태 컬럼 추가**: 기존 컬럼명·타입은 안 바꾸지만 테이블 스키마가 바뀌어 G1 "스키마 100% 보존"과 충돌 소지가 있고, 개찰결과는 공고가 아니라 개찰 사건에 속하므로 소유가 어긋납니다. 권고하지 않습니다.

### 5.4 권고

대안 A(새 테이블)를 권고합니다. 기존 테이블을 전혀 건드리지 않아 G1 이 명확하고, 백필·재계산·감사가 가능합니다. Redis(B)는 보조 캐시로만 두고 원천은 새 테이블로 둡니다.

---

## 6. 수집기 통합 지점과 호출량 (조사 항목 5)

### 6.1 코드 통합 지점 (읽기 근거)

| 지점 | 파일·함수 | 내용 |
| --- | --- | --- |
| API 계층 | `src/app/services/api_collector.py` | `BID_CATEGORIES` 옆에 개찰결과 오퍼레이션 매핑 추가. 매퍼(`_map_openg_result_item`)와 수집 함수(`stream_openg_results`)를 기존 `_run_ranges`/`_fetch_paged` 위에 얹음(15일 분할 `RANGE_DAYS=15`, 동시 `MAX_CONCURRENT=16`, 재시도·XML 살균 재사용) |
| 수집 실행 | `src/app/services/collector_service.py` | `collect_bids` 에 개찰결과 스텝 추가, `_bulk_insert` 로 새 테이블 적재. `MAX_CATCHUP_DAYS=7` 클램프와 체크포인트 규칙 동일 적용 |
| 파이프라인 스텝 | `src/tasks/automation_steps.py:39` `_step_collect` | `collect_bids` 를 호출하는 야간 수집 스텝. 여기서 개찰결과가 함께 돌아감 |
| 크론 | `src/tasks/scheduled_tasks.py` | `nightly_schedule_task`(매일 02:00), `development_data_refresh_task`(매일 02:00). 기동 따라잡기 `check_schedule_catchup_needed` |
| 감시 | `src/app/services/result_coverage.py:288` `compute_result_match_rates` | 분모 산출 시 개찰결과를 조인해 유찰 행 제외. 크론 `src/tasks/coverage_tasks.py`(월 05:00) |

### 6.2 호출량 추정 (실측 totalCount 기반)

| 시나리오 | 계산 | 호출 수 |
| --- | --- | ---: |
| 일일 증분(당일 1일 창, `inqryDiv=3`) | Servc 634/999 + Thng 522/999 + Cnstwk 364/999 = 각 1페이지 | 3회/일 |
| 지연 보정(최근 7일 재조회) | Servc 약 4p + Thng 약 4p + Cnstwk 약 3p | 약 11회/일 |
| 12주 백필 | 15일 구간 6개 x (Servc 6p + Thng 6p + Cnstwk 4p = 16p) | 약 96회 |
| (참고) 공고번호별 조회 | 3주 미매칭 1,520건 x 1회 | 약 1,520회 |

- 15일 창 실측: Servc 5,185(6페이지), Thng 5,205(6페이지), Cnstwk 3,524(4페이지). 1일 창 실측: Servc 634, Thng 522, Cnstwk 364.
- 날짜 창 일괄 방식이 공고번호별 방식보다 약 16배 저렴합니다. 일일 증분 + 7일 재조회 + 12주 백필을 합쳐도 약 1,800회 수준이며 하루 단위로 흩어져 있으므로 상한 부담이 없습니다.
- 지연: 999행 1페이지 응답은 수 초 내입니다. 백필 96회도 `MAX_CONCURRENT=16` 병렬로 수 분입니다.

---

## 7. 권고안과 구현 Task 분할 (조사 항목 6)

### 7.1 권고

1. 개찰결과를 새 테이블(대안 A)에 수집하고, `result_coverage.py` 분모에서 `progrsDivCdNm='유찰'` 행만 뺀다. 개찰완료·재입찰은 빼지 않는다.
2. 분모 제외는 설정 플래그로 켜고, 켠 상태와 끈 상태 수치를 함께 남겨 비교 가능하게 한다(기존 억제·보조 지표 관례).
3. 직찰·오프라인 제외(별도 워커 구현 중)와 순서가 겹치므로, 두 필터를 각각 독립 플래그로 두어 상호 간섭을 막는다.

### 7.2 구현 Task 분할

| Task | 내용 | 선행 | 검증 |
| --- | --- | --- | --- |
| T1 | `bid_openg_results` 모델 + alembic 신규 리비전(새 테이블만, 기존 테이블 불변) | - | 스키마 diff 무변경, upgrade/downgrade, G1 행 수 보존 |
| T2 | `api_collector.py` 개찰결과 매퍼·수집 함수 + 단위 테스트(모의 응답) | T1 | 파싱·차수 정규화·상태 매핑 테스트 |
| T3 | `collector_service.py` 통합 + 12주 백필 + 멱등성(유니크 제약) | T2 | 재실행 시 중복 0, 체크포인트·클램프 동작 |
| T4 | `result_coverage.py` 유찰 분모 제외 플래그 + 실측 재계산 | T3 | 새 매칭률이 4.4절 추정과 같은 방향, 경고 판정 회귀 |
| T5 | 운영 문서·CURRENT_STATE 반영 | T4 | 규칙 검사·문서 정합성 |

- T1~T5 는 직렬입니다. T1 이 데이터 무손실 검증을 통과해야 T2 이후를 시작합니다(AGENTS.md 7.9).

---

## 8. 재현 명령

### 8.1 DB 질의 (읽기 전용)

`uv run python scripts/db_readonly_query.py --sql "<질의>"` 로 실행합니다.

분모·매칭(4.1절):

```sql
SELECT a.category, COUNT(*) AS ann,
       SUM(CASE WHEN r.bid_ntce_no IS NOT NULL THEN 1 ELSE 0 END) AS matched
FROM bid_announcements a
LEFT JOIN bid_results r
  ON r.bid_ntce_no = a.bid_ntce_no AND r.category = a.category
 AND RIGHT(CONCAT('000', TRIM(LEADING '0' FROM a.bid_ntce_ord)), 3)
   = RIGHT(CONCAT('000', TRIM(LEADING '0' FROM r.bid_ntce_ord)), 3)
WHERE a.category IN ('Servc','Cnstwk','Thng') AND a.presmpt_prce >= 230000000
  AND a.openg_dt >= '2026-08-10 00:00:00' AND a.openg_dt < '2026-08-31 00:00:00'
  AND (a.ntce_kind_nm IS NULL OR a.ntce_kind_nm <> '취소공고')
GROUP BY a.category;
```

순수 미매칭 후보(4.1절):

```sql
WITH cancelled AS (
  SELECT DISTINCT bid_ntce_no, category FROM bid_announcements WHERE ntce_kind_nm = '취소공고'
)
SELECT a.category, COUNT(*) AS miss_rows, COUNT(DISTINCT a.bid_ntce_no) AS miss_notices
FROM bid_announcements a
LEFT JOIN bid_results r
  ON r.bid_ntce_no = a.bid_ntce_no AND r.category = a.category
 AND RIGHT(CONCAT('000', TRIM(LEADING '0' FROM a.bid_ntce_ord)), 3)
   = RIGHT(CONCAT('000', TRIM(LEADING '0' FROM r.bid_ntce_ord)), 3)
LEFT JOIN cancelled c ON c.bid_ntce_no = a.bid_ntce_no AND c.category = a.category
WHERE a.category IN ('Servc','Cnstwk','Thng') AND a.presmpt_prce >= 230000000
  AND a.openg_dt >= '2026-08-10 00:00:00' AND a.openg_dt < '2026-08-31 00:00:00'
  AND (a.ntce_kind_nm IS NULL OR a.ntce_kind_nm <> '취소공고')
  AND r.bid_ntce_no IS NULL AND c.bid_ntce_no IS NULL
GROUP BY a.category;
```

표본 60건(4.2절, 시드 고정):

```sql
WITH cancelled AS (
  SELECT DISTINCT bid_ntce_no, category FROM bid_announcements WHERE ntce_kind_nm = '취소공고'
), miss AS (
  SELECT a.bid_ntce_no AS bid_ntce_no, a.category AS category, COUNT(*) AS miss_rows
  FROM bid_announcements a
  LEFT JOIN bid_results r
    ON r.bid_ntce_no = a.bid_ntce_no AND r.category = a.category
   AND RIGHT(CONCAT('000', TRIM(LEADING '0' FROM a.bid_ntce_ord)), 3)
     = RIGHT(CONCAT('000', TRIM(LEADING '0' FROM r.bid_ntce_ord)), 3)
  LEFT JOIN cancelled c ON c.bid_ntce_no = a.bid_ntce_no AND c.category = a.category
  WHERE a.category IN ('Servc','Cnstwk','Thng') AND a.presmpt_prce >= 230000000
    AND a.openg_dt >= '2026-08-10 00:00:00' AND a.openg_dt < '2026-08-31 00:00:00'
    AND (a.ntce_kind_nm IS NULL OR a.ntce_kind_nm <> '취소공고')
    AND r.bid_ntce_no IS NULL AND c.bid_ntce_no IS NULL
  GROUP BY a.bid_ntce_no, a.category
), ranked AS (
  SELECT category, bid_ntce_no, miss_rows,
         ROW_NUMBER() OVER (PARTITION BY category ORDER BY MD5(CONCAT('fb20260929', bid_ntce_no))) AS rn
  FROM miss
)
SELECT category, bid_ntce_no, miss_rows FROM ranked WHERE rn <= 60 ORDER BY category, rn;
```

### 8.2 API 실측 (워커 컨테이너, 인증키·전체 URL 미출력)

`inqryDiv` 축·상태값(3.2·3.5절):

```sh
docker compose -p refac_bid_box exec -T worker python - <<'EOF'
import time, httpx
from collections import Counter
from src.app.services.api_collector import get_service_key
KEY = get_service_key()
BASE = 'https://apis.data.go.kr/1230000/as/ScsbidInfoService/'
def call(op, **extra):
    p = {'serviceKey': KEY, 'type': 'json', 'numOfRows': '999', 'pageNo': '1'}; p.update(extra)
    time.sleep(0.3)
    j = httpx.get(BASE + op, params=p, timeout=30).json()
    b = j.get('response', {}).get('body', {}) or {}
    it = b.get('items') or []
    if isinstance(it, dict): it = it.get('item')
    if isinstance(it, dict): it = [it]
    return b.get('totalCount'), it or []
for div in ('1', '2', '3'):
    tc, items = call('getOpengResultListInfoServc', inqryDiv=div,
                     inqryBgnDt='202608180000', inqryEndDt='202608182359')
    print(f'div={div} totalCount={tc}',
          dict(Counter(str(i.get('progrsDivCdNm')) for i in items)))
tc, items = call('getOpengResultListInfoServc', inqryDiv='4', bidNtceNo='R26BK01617066')
print('div=4 R26BK01617066', tc, [(i.get('bidNtceOrd'), i.get('progrsDivCdNm'), i.get('prtcptCnum')) for i in items])
EOF
```

표본 유찰 판정(4.3절, 60건 x 3분류). 아래 `SAMPLE` 은 8.1 절 표본 질의 결과를 `분류:공고번호:미매칭행수` 로 이어 붙인 값입니다.

```sh
docker compose -p refac_bid_box exec -T -e SAMPLE="$SAMPLE" worker python - <<'EOF'
import os, time, httpx
from src.app.services.api_collector import get_service_key
KEY = get_service_key()
BASE = 'https://apis.data.go.kr/1230000/as/ScsbidInfoService/'
OPS = {'Servc':'getOpengResultListInfoServc','Cnstwk':'getOpengResultListInfoCnstwk','Thng':'getOpengResultListInfoThng'}
res = {}
for item in os.environ['SAMPLE'].split(';'):
    cat, no, miss = item.split(':')
    time.sleep(0.25)
    j = httpx.get(BASE+OPS[cat], params={'serviceKey':KEY,'type':'json','numOfRows':'50','pageNo':'1',
        'inqryDiv':'4','bidNtceNo':no}, timeout=30).json()
    b = j.get('response',{}).get('body',{}) or {}
    it = b.get('items') or []
    if isinstance(it, dict): it = it.get('item')
    if isinstance(it, dict): it = [it]
    st = {str(i.get('progrsDivCdNm')) for i in (it or [])}
    a = res.setdefault(cat, [0,0,0,0])
    a[0] += int(miss); a[1] += 1
    if '유찰' in st: a[2] += int(miss); a[3] += 1
for cat, v in res.items():
    print(cat, 'sampled_rows=%d sampled_notices=%d failed_rows=%d failed_notices=%d' % (v[0], v[1], v[2], v[3]))
EOF
```

15일·1일 창 물량(6.2절): 8.2절 첫 스크립트의 `call` 을 `inqryDiv='3'`, 창 `202608100000~202608242359`(15일)와 `202608180000~202608182359`(1일)로 각 분류에 실행합니다.

---

## 9. 작성 범위와 한계

- 코드·설정·DB·스키마를 변경하지 않았습니다. 저장 설계는 실행 근거이며 코드는 작성하지 않았습니다.
- 4.4절의 매칭률 변화는 표본 외삽 **추정**이고, 3장·4.1·4.2·4.3절은 **실측**입니다. 확정 수치는 개찰결과 전량 수집 후 재계산으로 얻습니다.
- 표본은 분류별 60건(모집단의 약 10~30%)입니다. 유찰률 신뢰구간이 넓어 방향성 판단용입니다.
- 직찰·오프라인 공고 분모 제외(A)는 별도 워커 범위이며 이 보고서에 포함하지 않았습니다.
- API 호출은 총 330회로 계약 상한 400회 이내입니다.

---

## 10. 참고 문서

- `docs/analysis/servc_g2b_manual_checklist_20260928.md`: 25건 대조표와 유찰 10건 판정(4.1절)
- `docs/analysis/servc_upstream_recheck_20260928.md`: 표본 25건, 매칭률 동결, 경고 수치(4.2·4.5절)
- `docs/context/CURRENT_STATE.md`: 수집 파이프라인·게이트 운영 정본
