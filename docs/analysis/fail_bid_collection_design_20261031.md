# 유찰 상태 신규 수집 설계

> **작성일**: 2026-10-31
> **작업 ID**: `task_879d03fb7d50`
> **브랜치**: `kwanbum217/fail-bid-design-20261031`
> **기준 커밋**: `05385ff7`
> **성격**: 설계 문서. 소스·시험·마이그레이션·DB 변경 0건, 외부 API 실호출 0회, 커밋 1건(이 문서).
> **근거**: 선행 조사 `.orca/capsules/task_fail_bid_list_metric_path_probe_20261031/design.md` 와 2026-09-29 개찰결과 API 실측 보고서 [servc_failed_bid_design_20260929.md](servc_failed_bid_design_20260929.md). 수치는 이 두 문서에 기록된 값만 인용합니다.
> **결론**: 저장은 새 테이블 `bid_openg_results` 추가 전용으로 하고, 유찰 판정 필드는 `progrsDivCdNm`(개찰결과구분명)입니다. 기존 `bid_announcements`·`bid_results` 는 컬럼·행 수 모두 그대로 둡니다.

---

## 1. 문제와 현황

### 1.1 유찰 데이터가 없다

| 확인 항목 | 결과 | 근거 |
| --- | --- | --- |
| `bid_announcements` / `bid_results` 상태 컬럼 | 양쪽 모두 없음. `bid_results` 는 낙찰 성공 행만 담음 | 선행 조사 R2·R3 |
| `raw_data` JSON 상태 키 | 양쪽 모두 없음. 낙찰 성공 정보와 공고 속성만 있음 | 선행 조사 R4 |
| `src/rag/structured_data.py` 의 유찰 조건 | `유찰`·`status` 문자열 0건 | 선행 조사 R12 |
| `bid_results` 전체 행 수 | 3,464,615 | 선행 조사 R3 |

### 1.2 "결과 없음"은 유찰의 대체 신호가 아니다

2026-09-01 ~ 2026-10-31 공사 공고 중 개찰일이 지난 17,958건 가운데 `bid_results` 매칭이 없는 행이 6,129건(34.1%)입니다(선행 조사 R17). 이 집단에는 미개찰, 취소, 수집 누락이 함께 섞여 있어 유찰로 단정할 수 없습니다. 최근 한 달 공사 공고종류 분포도 `등록공고` 8,744, `취소공고` 521, `변경공고` 516, `재공고` 52 로(선행 조사 R9), `재공고` 는 유찰의 결과일 뿐 상태 라벨이 아닙니다.

### 1.3 현행 챗봇은 미지원 안내로 막혀 있다

`src/rag/data_gap_guard.py:45-49` 의 `DATA_GAP_MESSAGES["유찰 상태"]` 가 고정 안내를 내고, 판정은 같은 파일 `:70`(`_VOID_STATUS`)과 `:117`(`_ITEM_PATTERNS`)이 담당합니다. 목록 라우팅으로 바꾸면 유찰이 아닌 공고 5건이 나오므로(선행 조사 2.1절), 데이터가 채워지기 전에는 현행 유지를 권고합니다. 이 문서는 사용자의 수집 결정에 따라 엔드포인트·저장·수집·소급·챗봇 연결을 확정합니다.

---

## 2. 후보 엔드포인트와 유찰 판정 필드

### 2.1 오퍼레이션

조달청 낙찰정보서비스(`ScsbidInfoService`, 선행 문서 기록 서비스 식별자 15129397)의 **개찰결과 목록** 오퍼레이션을 씁니다. 현재 수집기가 쓰는 낙찰현황(`getScsbidListSttus<분류>`)은 낙찰자가 있는 건만 주므로 유찰을 구조적으로 담지 못합니다. Base URL 은 기존 예비가격 상세와 같은 `https://apis.data.go.kr/1230000/as/ScsbidInfoService/` 이고 인증키도 `G2B_SERVICE_KEY` 하나로 통합니다. 아래 수치는 2026-09-29 저장소 실측이며, 이번 과제에서는 외부 API 를 다시 호출하지 않았습니다.

| 분류 | 오퍼레이션 | 2026-08-18 1일 창 totalCount | resultCode |
| --- | --- | ---: | :---: |
| 용역 | `getOpengResultListInfoServc` | 590 | 00 |
| 물품 | `getOpengResultListInfoThng` | 531 | 00 |
| 공사 | `getOpengResultListInfoCnstwk` | 364 | 00 |
| 외자 | `getOpengResultListInfoFrgcpt` | 3 | 00 |

### 2.2 응답 필드와 확인 상태

네 오퍼레이션의 응답 필드 16개가 동일합니다.

| 필드 | 의미 | 확인 상태 |
| --- | --- | --- |
| `bidNtceNo` | 입찰공고번호 | 실측 (2026-09-29) |
| `bidNtceOrd` | 입찰공고차수. 3자리(`000`)로 내려와 기존 공고 테이블 규칙과 맞음 | 실측 |
| `rbidNo` / `bidClsfcNo` | 재입찰번호 / 입찰분류번호 | 필드 존재 실측 |
| `bidNtceNm` | 공고명 | 실측 |
| `dminsttNm`+`dminsttCd` / `ntceInsttNm`+`ntceInsttCd` | 수요기관명·코드 / 공고기관명·코드 | 실측 |
| `opengDt` / `inptDt` | 개찰일시(`inqryDiv=3` 축) / 입력일시(`inqryDiv=1` 축) | 실측 |
| **`progrsDivCdNm`** | **개찰결과구분명. 유찰 판정 필드** | 실측. 값 3종 확인 |
| `prtcptCnum` | 참가업체 수 | 실측. 보조 지표로만 사용 |
| `opengRsltNtcCntnts` / `rsrvtnPrceFileExistnceYn` | 개찰결과 공지내용 / 예비가격서류 존재 여부 | 필드 존재 실측. 전자는 값 의미 확인 필요, 후자는 미사용 |
| `opengCorpInfo` | 개찰 업체 정보(대표자명 등 포함) | 필드 존재 실측, 개인정보라 미사용 |

### 2.3 유찰 판정 규칙

| 질문 | 판정 | 근거 |
| --- | --- | --- |
| 유찰은 무엇으로 판정하는가 | `progrsDivCdNm == "유찰"` | 2026-08-18 1일 창 분포가 3종뿐임 |
| `prtcptCnum = 0` 으로 판정해도 되는가 | 안 된다 | `progrsDivCdNm=유찰` 이면서 `prtcptCnum>0` 인 행이 표본에 있었음(Cnstwk 4/4, Servc 1/30, Thng 3/40) |
| `재입찰` 은 유찰인가 | 아니다. 별도 상태 | 값 목록이 개찰완료·유찰·재입찰 3종 |
| 상태 분포는 | Servc 411/166/13, Thng 313/209/9, Cnstwk 352/6/6 (개찰완료/유찰/재입찰) | 2026-08-18 1일 창 실측 |

유찰은 "무응찰"만이 아니라 "참가했으나 낙찰자 없음(예정가격 초과·전원 부적격)"까지 포함합니다. 그래서 `prtcptCnum` 은 참고값이고 판정은 상태 코드로만 합니다.

### 2.4 조회 파라미터

| 파라미터 | 확인된 동작 | 확인 상태 |
| --- | --- | --- |
| `inqryDiv=1` / `2` / `3` | 입력일시 / 입찰공고게시일시 / 개찰일시 기준. 증분·소급은 `3` 을 씀 | 실측 |
| `inqryDiv=4` | 공고번호 지정. 차수별 여러 행 반환 | 실측 |
| `inqryBgnDt` / `inqryEndDt` | `YYYYMMDDHHMM`. 15일 창까지 동작 | 실측 |
| `numOfRows` / `type` | 최대 999(1,000 이상은 10건만 반환) / `json`·`xml` 모두 지원 | 실측 |

위 축·상한은 2026-09-29 호출로 얻은 기록을 인용한 값입니다. 이번 과제에서 재실측하지 않았으므로 구현 착수 시 한 번 더 확인해야 합니다.

---

## 3. 저장 설계

### 3.1 대안 비교

| 대안 | 방식 | G1 판정 | 판정 |
| --- | --- | --- | --- |
| **A. 새 테이블 `bid_openg_results`** | 개찰 사건을 독립 테이블에 적재 | 기존 테이블 무변경으로 안전 | **권고** |
| B. `bid_announcements` 에 상태 컬럼 추가 | 기존 테이블에 컬럼 1개 추가 | 스키마 100% 보존 원칙과 충돌 | 비권고 |
| C. `bid_results` 에 유찰 행 삽입 | 낙찰자 없는 행을 낙찰결과 테이블에 추가 | 테이블 의미 변경·유니크 충돌로 위반 | 금지 |

대안 C 가 금지인 이유는 세 가지입니다. 첫째, `bid_results` 는 낙찰업체·낙찰금액·낙찰률을 담는 "낙찰 결과" 테이블인데 유찰 행은 세 값이 모두 NULL 이라 의미가 바뀝니다. 둘째, (공고번호, 차수, 분류) 유니크 제약 때문에 `000` 차수가 유찰 행으로 선점되면 뒤늦게 도착하는 같은 차수의 낙찰 결과를 저장할 수 없습니다. 셋째, 챗봇 집계·기관별 낙찰률·ML 라벨이 모두 이 테이블을 낙찰 통계로 읽습니다.

### 3.2 새 테이블 정의 (초안)

| 컬럼 | 타입 | NULL | 설명 |
| --- | --- | :---: | --- |
| `id` | BIGINT PK (sqlite 는 INTEGER) | N | 자동 증가 |
| `bid_ntce_no` | VARCHAR(50) | N | 입찰공고번호 |
| `bid_ntce_ord` | VARCHAR(10) | N | 차수. 기본 `000` |
| `rbid_no` / `bid_clsfc_no` | VARCHAR(10) / VARCHAR(20) | N | 재입찰번호(`000`) / 입찰분류번호(`0`) |
| `category` | VARCHAR(10) | N | 업무구분 |
| `progrs_div_cd_nm` | VARCHAR(30) | N | 개찰결과구분명. `유찰` 판정 원천 |
| `prtcpt_cnum` | INTEGER | Y | 참가업체 수 |
| `bid_ntce_nm` / `dminstt_nm` | VARCHAR(500) / VARCHAR(200) | Y | 공고명 / 수요기관명 |
| `openg_dt` | DATETIME | Y | 개찰일시 |
| `raw_data` | JSON | Y | 응답 원문 |
| `first_seen_at` / `last_seen_at` | DATETIME | N | 처음·마지막 관측 시각 |
| `collected_at` | DATETIME | N | 적재 시각 |

키와 인덱스는 다음 다섯 개로 시작합니다. 유니크 키는 응답 1건이 `(공고번호, 차수, 재입찰번호, 분류)` 로 유일하다는 가정이며, `rbidNo` 가 같은 공고·차수에서 중복되는 사례는 실측하지 않아 **확인 필요**입니다.

| 이름 | 컬럼 | 용도 |
| --- | --- | --- |
| `uq_bid_openg_results` | (`bid_ntce_no`, `bid_ntce_ord`, `rbid_no`, `category`) | 멱등 적재·상태 갱신 기준 |
| `ix_openg_cat_dt` | (`category`, `openg_dt`) | 분류·기간 증분 조회 |
| `ix_openg_status_dt` | (`progrs_div_cd_nm`, `openg_dt`) | 유찰 목록·비율 집계 |
| `ix_openg_inst_cat_dt` | (`dminstt_nm`, `category`, `openg_dt`) | 기관 조건 목록 |
| `ix_openg_notice` | (`bid_ntce_no`, `category`) | 공고 join |

### 3.3 상태 갱신 정책

`progrsDivCdNm` 은 시간에 따라 바뀔 수 있습니다(재입찰 → 개찰완료). 현행 `_bulk_insert`(`src/app/services/collector_service.py:206-228`)는 `INSERT IGNORE` 라 첫 관측값이 영구 고정되고, 이러면 늦게 확정된 낙찰이 영원히 "유찰"로 남습니다. 따라서 이 테이블만 **upsert**(`ON DUPLICATE KEY UPDATE progrs_div_cd_nm, prtcpt_cnum, last_seen_at, raw_data`)로 적재하고, 첫 관측 시각을 `first_seen_at` 에 남겨 이력 추적 근거를 유지합니다. 기존 테이블의 `INSERT IGNORE` 동작은 건드리지 않으며, upsert 헬퍼는 `_ignore_prefix`(`:202-203`)처럼 dialect 를 분기합니다(sqlite 는 `ON CONFLICT DO UPDATE`, MySQL 은 `ON DUPLICATE KEY UPDATE`).

### 3.4 마이그레이션 초안

기존 테이블은 `ALTER` 하지 않고 `create_table`·`create_index` 만 씁니다. 작성 시점의 alembic head 는 `b7c8d9e0f1a2` 입니다(`migrations/versions` 23개 리비전의 단일 head).

```python
revision = "c1d2e3f4a5b6"
down_revision = "b7c8d9e0f1a2"
PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")

def upgrade() -> None:
    op.create_table(
        "bid_openg_results",
        sa.Column("id", PK, primary_key=True, autoincrement=True),
        sa.Column("bid_ntce_no", sa.String(50), nullable=False),
        sa.Column("bid_ntce_ord", sa.String(10), nullable=False, server_default="000"),
        sa.Column("progrs_div_cd_nm", sa.String(30), nullable=False),
        sa.Column("raw_data", sa.JSON()),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("collected_at", sa.DateTime(), nullable=False),
        # 나머지 컬럼과 기본값은 3.2절 표를 그대로 옮긴다.
        sa.UniqueConstraint("bid_ntce_no", "bid_ntce_ord", "rbid_no", "category",
                            name="uq_bid_openg_results"),
    )
    for name, cols in (
        ("ix_openg_cat_dt", ["category", "openg_dt"]),
        ("ix_openg_status_dt", ["progrs_div_cd_nm", "openg_dt"]),
        ("ix_openg_inst_cat_dt", ["dminstt_nm", "category", "openg_dt"]),
        ("ix_openg_notice", ["bid_ntce_no", "category"]),
    ):
        op.create_index(name, "bid_openg_results", cols)

def downgrade() -> None:
    op.drop_table("bid_openg_results")
```

G1 영향은 명확합니다. `bid_announcements`·`bid_results` 는 컬럼·인덱스·행 수 모두 불변이고, 신규 테이블 1개만 추가됩니다. ML 특징(`src/ml/features.py`)에는 연결하지 않습니다.

---

## 4. 수집 경로

### 4.1 api_collector.py 추가분

기존 `_run_ranges`·`_fetch_paged`·`_make_request_with_retry`·`sanitize_xml_text` 를 그대로 재사용합니다. `type=xml` 경로를 유지하면 기존 XML 살균·오류 봉투 처리를 그대로 씁니다.

| 추가 항목 | 내용 |
| --- | --- |
| `OPENG_RESULT_URLS` / `_map_openg_result_item(category)` | 분류별 개찰결과 URL dict / 2.2절 필드를 평평한 dict 로 변환. `bid_ntce_ord` 는 `normalize_bid_ntce_ord` 로 3자리 정규화 |
| `stream_openg_results(start, end, sink, category)` | `_run_ranges` 호출. 15일 창 분할·동시 16·재시도 정책 자동 상속 |
| `_fetch_paged(..., inqry_div="1")` | 현재 문자열 `"1"` 하드코딩. 기본값 있는 매개변수로 빼서 `3` 을 넘길 수 있게 함(기존 호출 동작 불변) |

### 4.2 collector_service.py 연결 위치

`collect_bids`(`src/app/services/collector_service.py:313`)의 실행 순서는 공고(`:388-413`) → 낙찰정보(`:415-436`) → 면허제한·참가지역입니다. 낙찰정보 스텝 바로 뒤에 개찰결과 스텝(`bid_openg_results` upsert)을 넣습니다. 추가할 지표 키는 `openg_result_count`, `failed_count`, `failed_ranges` 의 `kind="openg_result"` 이고, 부분 실패는 기존 `RangeCollectionError` 처리와 같게 하되 실패 구간의 체크포인트를 전진시키지 않습니다.

체크포인트와 주기는 다음과 같습니다.

| 항목 | 내용 |
| --- | --- |
| 체크포인트 | 기존 `resolve_collection_window`(같은 파일 `:76`)의 MIN of MAX 규칙을 개찰결과에도 적용. 기준 컬럼은 `bid_openg_results.openg_dt` 의 분류별 MAX |
| 자동 회수 상한 | 기존 `MAX_CATCHUP_DAYS = 7` 을 그대로 적용. 7일을 넘는 공백은 수동 소급으로 넘김 |
| 기본 주기 | 매일 02:00 `nightly_schedule_task`·`development_data_refresh_task`(`src/tasks/scheduled_tasks.py:243`, `:324`)에 포함 |
| 지연 보정 | 개찰 상태는 늦게 바뀌므로 최근 7일 창을 매일 `inqryDiv=3` 으로 재조회(upsert 로 중복 무해) |
| 서비스 키 없음 | 기존 `collect_bids` 처럼 `status="error"` 로 조기 반환하고 새 테이블은 건드리지 않음 |

---

## 5. 과거분 소급

### 5.1 대상 기간과 호출 수

15일 창 1개당 페이지 수는 2026-09-29 실측값(15일 Servc 5,185 → 6p, Thng 5,205 → 6p, Cnstwk 3,524 → 4p)을 씁니다. 분류 3개, 외자 제외 기준입니다.

| 소급 범위 | 15일 창 수 | 페이지 환산 | 총 호출 수 |
| --- | ---: | --- | ---: |
| 12주(84일) | 6 | 6 x 16p | 약 96회 |
| 1년(365일) | 25 | 25 x 16p | 약 400회 |
| 3년(1,095일) | 74 | 74 x 16p | 약 1,184회 |
| (참고) 공고번호별 3주 미매칭 1,520건 | - | 1건 1회 | 약 1,520회 |

날짜 창 일괄 방식이 공고번호별 방식보다 약 16배 저렴합니다.

### 5.2 일일 한도 대비

| 항목 | 값 | 확인 상태 |
| --- | --- | --- |
| 일일 증분 + 7일 지연 보정 | 3~4회/일 + 약 11회/일 | 추정 |
| 개발계정 표기 트래픽 | 1,000 (단위 확인 필요) | 저장소 문서 인용, **확인 필요** |
| 1년 소급 / 3년 소급 | 약 400회(1일) / 약 1,184회(2일 분할) | 추정 |

기존 수집기 주석은 동시 16에서 약 1.9 req/s 를 기록하고 있어 단순 1,000/일과는 배치됩니다. 구현 착수 전에 마이페이지 활용신청 현황에서 실제 승인 트래픽을 확인해야 합니다. 저장량은 15일 창 물량을 연간으로 환산하면 분류 3개 합계 약 34만 행/년이고(Servc 5,185 x 24.3 + Thng 5,205 x 24.3 + Cnstwk 3,524 x 24.3), 3년 소급이면 약 100만 행, `raw_data` JSON 때문에 수 GB 규모로 **추정**됩니다. 실측 적재 후 재계산해야 합니다.

### 5.3 실행 방식

신규 `scripts/backfill_openg_results.py`(기존 `scripts/backfill_from_g2b.py` 관례)에 `--start`, `--end`, `--categories`, `--dry-run` 을 둡니다. 15일 창, `inqryDiv=3`, `numOfRows=999`, `MAX_CONCURRENT=16` 으로 분할하고, 창 단위 실패를 원장에 남겨 재실행 가능하게 합니다. 부분 성공을 성공으로 보고하지 않으며, 유니크 키 + upsert 로 같은 창 재실행이 안전합니다.

---

## 6. 챗봇 연결

### 6.1 가드 해제 조건

`data_gap_guard` 의 "유찰 상태" 항목은 아래 세 조건을 모두 만족할 때만 해제합니다. 조건 1 의 기준선은 소급 전에는 정할 수 없고, 34.1% 라는 "결과 없음" 비율을 커버리지 기준으로 쓰면 안 됩니다.

| 조건 | 판정 기준 | 검증 방법 |
| --- | --- | --- |
| 1. 적재 커버리지 | 최근 30일 개찰 공고 중 개찰결과 행이 있는 비율을 측정해 기준선을 정하고, 그 기준을 넘음 | 소급 후 DB 집계 |
| 2. 목록 정확성 | 유찰 조건 목록 상위 N건이 전부 `progrs_div_cd_nm="유찰"` | 표본 질의·시험 |
| 3. 회귀 시험 | 정의 질문("유찰이 뭐야")은 계속 LLM 경로로 통과 | `tests/test_data_gap_guard.py` |

### 6.2 data_gap_guard 변경 위치

| 위치 | 변경 |
| --- | --- |
| `src/rag/data_gap_guard.py:117` | `_ITEM_PATTERNS` 에서 `("유찰 상태", (_VOID_STATUS,), True)` 제거 |
| `src/rag/data_gap_guard.py:70` | `_VOID_STATUS` 정규식이 미사용이 되므로 함께 제거 |
| `src/rag/data_gap_guard.py:45-49` | `DATA_GAP_MESSAGES["유찰 상태"]` 는 남긴다. 적재 공백 구간의 폴백 문구로 재사용 |

`_EXPLANATION` 우회(`:148-149`)는 손대지 않습니다. 정의 질문은 데이터 유무와 무관하게 LLM 답변이 맞습니다.

### 6.3 structured_data 조건 추가 위치

| 위치 | 추가 내용 |
| --- | --- |
| `src/rag/structured_data.py:604-660` `_announcement_conditions` | `filters["outcome"] == "유찰"` 이면 `BidOpengResult` 를 EXISTS 서브쿼리로 조인해 `progrs_div_cd_nm == "유찰"` 조건 추가. 조인 키는 (공고번호, 차수, 분류) |
| `src/rag/structured_data.py:2317-2383` `_fetch_sample_announcements` | 조건은 인자로 이미 전달되므로 select 변경 없음. 표에 유찰 라벨을 보여주려면 `progrs_div_cd_nm` 을 outer join 으로 추가 |
| `src/rag/structured_data.py:3089-3295` 목록 분기 | `announcement_limit` 이 있는 경로에서 outcome 조건이 자동 적용되는지 확인. 집계(total_count)도 같은 조건을 써야 목록과 건수가 어긋나지 않음 |
| `src/rag/structured_data.py:876-898` `_result_availability_conditions` | 변경 없음. 유찰은 낙찰결과 테이블 축이 아님 |

### 6.4 계획 계층 의존

목록 경로가 실제로 동작하려면 계획이 `filters["outcome"]="유찰"` 을 실어야 합니다. 현재 `ANNOUNCEMENT_RESULT_STATUS_MARKERS`(`src/rag/query_planning.py:1749`)가 `유찰` 을 포함해 유찰 질문을 공고 목록에서 제외하므로(선행 조사 1.6절), 이 표지에 유찰+목록 예외를 두는 별도 변경이 필요합니다. 이 파일은 이번 조사 범위 밖이라 위치만 기록하고 설계는 확정하지 않습니다.

---

## 7. 결정이 필요한 항목

| 번호 | 항목 | 선택지 | 권고 | 영향 |
| ---: | --- | --- | --- | --- |
| 1 | 수집 분류 범위 | 3분류 / 4분류(외자 포함) | 3분류 | 외자는 1일 3건으로 효용이 낮고 페이지 1장을 상시 씀 |
| 2 | 상태 변경 처리 | upsert / 첫 관측 고정 | upsert | 고정하면 늦게 확정된 낙찰이 영구 유찰로 남음 |
| 3 | `opengCorpInfo` 저장 | `raw_data` 전체 / 제외 | 제외 또는 마스킹 | 개인정보(대표자명 등). G1 은 기존 테이블 대상이므로 신규 테이블에서 선택 가능 |
| 4 | 소급 기간 | 12주 / 1년 / 3년 | 1년 | 한도 안에서 하루에 끝나고 최근 추세 분석에 충분 |
| 5 | 재입찰 포함 여부 | 유찰만 / 유찰+재입찰 | 유찰만 | 재입찰을 유찰로 세면 지표가 과대해짐 |
| 6 | 승인 트래픽 확인 | - | 착수 전 확인 | 1,000/일 표기의 단위가 미확인 |
| 7 | 챗봇 노출 범위 | 목록만 / 통계까지 | 목록만 | 통계는 분모 정의(개찰 대기·취소 제외) 합의가 선행 필요 |
| 8 | 유니크 키 확정 | (공고,차수,재입찰,분류) | 실측 후 확정 | `rbidNo` 중복 사례 미확인 |

---

## 8. 단계별 구현 계획

| Task | 내용 | 선행 | 검증 |
| --- | --- | --- | --- |
| T1 | `BidOpengResult` 모델 + 마이그레이션(신규 테이블만) | - | upgrade/downgrade, 기존 테이블 스키마 diff 0, 행 수 보존 |
| T2 | `api_collector` 매퍼·수집 함수 + 모의 응답 단위 시험 | T1 | 필드 매핑, 차수 3자리 정규화, 상태 3종 매핑, 오류 봉투 처리 |
| T3 | `collector_service` 통합 + upsert 적재 + 멱등성 | T2 | 같은 창 2회 실행 시 행 수 불변, 상태 변경이 반영됨 |
| T4 | `scripts/backfill_openg_results.py` + 1년 소급 | T3 | 창별 실패 원장, 재실행 안전, 적재 행 수·상태 분포 보고 |
| T5 | `data_gap_guard` 해제 + `structured_data` outcome 조건 + 계획 예외 | T4, 6.1절 조건 충족 | 유찰 목록 5건이 전부 유찰, 정의 질문 회귀 통과, 기존 미지원 안내 시험 갱신 |
| T6 | 운영 문서·`CURRENT_STATE` 반영, 수집 지표 대시보드 | T5 | `python3 scripts/validate_agent_rules.py --quiet`, 문서 정합성 |

T1~T4 는 직렬입니다. T5 는 데이터 적재가 끝나고 6.1절 세 조건을 만족한 뒤에만 착수하며, 그 전에는 현행 미지원 안내를 유지합니다. T6 은 병합 직전 `main` HEAD 기준으로 `source_commit` 을 갱신합니다.
