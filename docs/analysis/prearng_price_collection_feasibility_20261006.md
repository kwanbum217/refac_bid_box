# 개찰결과 예비가격 상세(용역) 수집 가능성 조사와 신규 테이블·수집기 설계안

> **작성일**: 2026-10-06
> **작성자**: Orca builder (task_0f6bc58780c9)
> **범위**: 나라장터 OpenAPI `개찰결과 예비가격 상세(용역)` 의 수집 가능성 조사, 소급 수집 규모 추정, 신규 테이블·수집기·사정률 분포 계산 설계안
> **코드 변경**: 없음. 본 문서만 작성한다.
> **선행 설계**: [web_feedback_redesign_20261006.md](../design/web_feedback_redesign_20261006.md) 5.3절(D-W3), 7절 4단계, 8절
> **표기 원칙**: [실측]은 이번 조사에서 직접 호출·조회한 값, [추정]은 계산·가정, [문서]는 외부 공식 문서 인용이다. 서비스 키 값은 어디에도 기록하지 않는다.

---

## 1. 결론 요약

| 질문 | 판정 | 근거 |
| --- | --- | --- |
| 개찰결과 예비가격 상세(용역)를 수집할 수 있는가 | **수집 가능** | 오퍼레이션 `getOpengResultListInfoServcPreparPcDetail` 표본 호출 성공(15행) |
| 현재 수집기와 같은 키로 호출 가능한가 | **가능** | 동일 서비스 `as/ScsbidInfoService` 소속이며 `.env` 의 기존 키로 인증 성공([실측]) |
| 사정률(예정가격 ÷ 기초금액)을 얻을 수 있는가 | **가능** | 응답에 `plnprc`(예정가격), `bssamt`(기초금액) 동시 제공. 사정률 99.6605% 검산 일치 |
| 복수예비가격 15개를 얻을 수 있는가 | **가능** | 공고당 15행, 각 행 `bsisPlnprc`(후보 예비가격), `drwtYn`(추첨여부), `drwtNum`(추첨횟수) |
| 과거분 소급이 가능한가 | **가능** | 2013-01 창의 `totalCount` 82,044건 확인([실측]). 창 상한은 약 1개월 |
| 기존 테이블을 바꾸지 않고 담을 수 있는가 | **가능** | 아래 9장의 신규 테이블 2개로 수용. 기존 테이블 무변경(G1) |
| 병합을 막는 결함이 있는가 | **없음**(candidate) | 일일 트래픽 한도 확인 등 잔여 위험은 12장으로 분리 |

**핵심 제약**: 날짜 창은 최대 약 1개월, 페이지 크기는 최대 500행, 그리고 `data.go.kr` 페이지 표기 개발계정 트래픽은 **1,000**(단위 확인 필요)이다. 소급 배치는 이 두 상한에 맞춰 창·페이지를 설계하고 일일 호출 예산을 명시적으로 예약해야 한다.

---

## 2. 조사 배경

- 설계 정본 5.3절은 최저가·최상가의 "기존 낙찰 데이터" 사정률 범위를 **같은 발주처(표본 부족 시 같은 시·도·업종) 과거 공고의 예정가격 ÷ 기초금액 최솟값·최댓값**으로 정의한다.
- 현재 `bid_results` 에는 낙찰금액·낙찰률·참가업체 수만 있고, `bid_announcements` 의 `base_amount`(기초금액)는 있어도 **예정가격이 없다**. 따라서 과거 사정률을 지금 데이터로는 계산할 수 없고, 별도 수집이 선행되어야 한다.
- 본 문서는 그 수집 경로의 실현 가능성과 설계안을 확정한다.

---

## 3. 오퍼레이션 명세

### 3.1 엔드포인트

| 항목 | 값 |
| --- | --- |
| 서비스 | 조달청_나라장터 낙찰정보서비스 (`ScsbidInfoService`, data.go.kr 15129397) |
| Base URL | `https://apis.data.go.kr/1230000/as/ScsbidInfoService` |
| 오퍼레이션(용역) | `getOpengResultListInfoServcPreparPcDetail` |
| 응답 형식 | JSON/XML (`type=json`) |
| 동일 서비스 기존 사용 | 수집기의 `getScsbidListSttusServc`(낙찰정보)와 **같은 서비스 경로** |

- 공고/물품/외자는 오퍼레이션의 `Servc` 부분만 `Cnstwk`/`Thng`/`Frgcpt` 로 치환한다([문서] opendata-kr MCP `endpoints.ts`). 본 과업은 용역(`Servc`)만 대상으로 한다.
- 인증키는 `.env` 의 `G2B_SERVICE_KEY`(또는 `serviceKey`)를 그대로 쓴다. 표본 호출에서 별도 승인 없이 동작했다([실측]).

### 3.2 요청 파라미터

| 이름 | 필수 | 값/형식 | 비고 |
| --- | :---: | --- | --- |
| `serviceKey` | 예 | `.env` 값 | 코드·로그·보고서에 노출 금지 |
| `inqryDiv` | 예 | `1` = 입력일시, `2` = 입찰공고번호 | [실측][문서] |
| `inqryBgnDt` / `inqryEndDt` | `inqryDiv=1` | `YYYYMMDDHHMM` | **하이픈·공백 형식은 오류**(resultCode 06, 4.4 참조) |
| `bidNtceNo` | `inqryDiv=2` | 입찰공고번호 | 단건 조회 |
| `numOfRows` | 아니오 | 최대 **500** | 501 이상은 10으로 리셋됨(4.3 참조) |
| `pageNo` | 아니오 | 1부터 | 페이지 루프 |
| `type` | 아니오 | `json`/`xml` | `json` 권장 |

- 날짜 창 최대 폭은 **약 1개월**이다. 31일 창은 성공, 45일 창은 resultCode 07(입력범위값 초과)로 실패했다([실측]).

### 3.3 응답 필드

`response.body.items` 가 15개 행(공고당)이며, 행별 필드와 15행 공통 필드가 섞여 내려온다.

| 원본 필드 | 의미 | 구분 | 예시값 |
| --- | --- | --- | --- |
| `bidNtceNo` | 입찰공고번호 | 공통/키 | `R25BK01250632` |
| `bidNtceOrd` | 입찰공고차수 | 공통/키 | `000` |
| `bidClsfcNo` | 입찰분류번호 | 공통/키 | `0` |
| `rbidNo` | 재입찰번호 | 공통/키 | `000` |
| `bidNtceNm` | 공고명 | 공통 | `PQ 후 가격입찰 공고(...)` |
| **`plnprc`** | **예정가격** | 공통 | `1974820700` |
| **`bssamt`** | **기초금액** | 공통 | `1981548000` |
| `totRsrvtnPrceNum` | 총 복수예비가격 수 | 공통 | `15` |
| `bidwinrSlctnAplBssCntnts` | 낙찰자선정적용기준내용 | 공통 | `행자부` |
| `bssamtBssUpNum` | 기초금액기준 상위갯수 | 공통 | `7` |
| `compnoRsrvtnPrceMkngDt` | 복수예비가격 작성시각 | 공통 | `2026-01-08 15:29:08` |
| `rlOpengDt` | 실제 개찰일시 | 공통 | `2026-01-08 15:34:16` |
| `inptDt` | 입력일시(`inqryDiv=1` 기준) | 공통 | `2026-01-08 15:34:16` |
| `compnoRsrvtnPrceSno` | 예비가격 순번 | 행별 | `1` ~ `15` |
| `bsisPlnprc` | 후보 예비가격 금액 | 행별 | `2037665500` |
| `drwtYn` | 추첨여부(`Y` 4개) | 행별 | `Y` |
| `drwtNum` | 추첨횟수 | 행별 | `2` |
| `PrearngPrcePurcnstcst` | (미확인) | 행별 | 표본에서 빈 값 |
| `bssAmtPurcnstcst` | (미확인) | 행별 | 표본에서 빈 값 |

- [실측] 공고 1건에 15행, `drwtYn=Y` 가 정확히 4행, `bsisPlnprc` 후보 금액 범위는 기초금액 대비 대략 ±2~3% 였다(1,927,075,300 ~ 2,037,665,500 / 기초금액 1,981,548,000).

---

## 4. 표본 호출 결과 (키 제외)

모든 호출은 표본 확인용이며 소량이다. 운영 DB 쓰기·대량 수집은 하지 않았다. 요청 URL 의 `serviceKey` 값은 마스킹했다.

### 4.1 공고번호 단건 조회 (`inqryDiv=2`)

| 항목 | 값 |
| --- | --- |
| 요청 | `inqryDiv=2`, `bidNtceNo=R25BK01250632`, `numOfRows=100`, `pageNo=1`, `type=json` |
| HTTP | 200, 약 11.6KB |
| `totalCount` | 15 |
| 반환 행 수 | 15 |
| 결과 | 성공. 3.3 필드 전량 확인 |

### 4.2 날짜 창 조회 (`inqryDiv=1`)

| 창 | `totalCount` | 비고 |
| --- | ---: | --- |
| 2026-01-01 ~ 2026-01-10 | 13,451 | 창 조회 성공 |
| 2026-01 (1개월) | 106,710 | 성공 |
| 2025-12 | 180,662 | 성공(연말 급증) |
| 2025-11 | 83,509 | 성공 |
| 2025-10 | 60,137 | 성공 |
| 2020-01 | 103,064 | 성공 |
| 2016-01 | 71,082 | 성공 |
| 2013-01 | 82,044 | 성공(소급 하한 확인 지점) |

- `totalCount` 는 **예비가격 행 수**(공고당 15행) 기준이다. 창 조회로 과거분을 통째로 열거할 수 있다.

### 4.3 상한 실측

| 파라미터 | 시도 | 결과 |
| --- | --- | --- |
| `numOfRows` | 10/50/100/200/300/500 | 요청대로 반환 |
| `numOfRows` | **1,000** | **10으로 리셋** → 상한은 500 |
| 창 폭 | 31일 | 성공 |
| 창 폭 | 45일/2개월/3개월/6개월/1년 | resultCode **07** 입력범위값 초과 에러 |

### 4.4 오류 응답 실측

| 조건 | 응답 |
| --- | --- |
| 날짜 형식 오류(`2026-01-01`) | `{"nkoneps.com.response.ResponseError":{"header":{"resultCode":"06","resultMsg":"DATE Format 에러"}}}` |
| 창 폭 초과(45일 이상) | `{"...":{"header":{"resultCode":"07","resultMsg":"입력범위값 초과 에러"}}}` |
| 존재하지 않는 공고번호 | `totalCount=0`, `items` 없음 |

- 게이트웨이 오류는 정상 봉투(`response.header.resultCode`)가 아니라 `nkoneps.com.response.ResponseError` 로 내려온다. 수집기의 기존 오류 처리(`root.findtext(".//resultCode")`)는 XML 기준이므로 **신규 경로는 이 별도 오류 봉투를 별도로 처리해야 한다**.

### 4.5 사정률 검산

| 항목 | 값 |
| --- | --- |
| 예정가격 `plnprc` | 1,974,820,700 |
| 기초금액 `bssamt` | 1,981,548,000 |
| 사정률 = `plnprc ÷ bssamt × 100` | **99.6605%** |

- 사정률은 API 가 직접 주지 않으므로 `plnprc / bssamt` 로 계산한다. 표본에서 값이 일관되게 채워졌다.

---

## 5. 기존 수집기와의 관계

| 항목 | 현재 수집기 | 예비가격 상세 |
| --- | --- | --- |
| 모듈 | `src/app/services/api_collector.py` | 동일 모듈에 추가 가능 |
| 서비스 경로 | `as/ScsbidInfoService/getScsbidListSttus{Servc,...}` | `as/ScsbidInfoService/getOpengResultListInfo{Servc}PreparPcDetail` |
| 인증키 | `get_service_key()` | 동일 키([실측] 인증 성공) |
| 공통 인프라 | 세마포어 동시성 제한, 5회 지수 백오프, 날짜 구간 분할, `sink` 스트리밍 적재 | 재사용 가능 |
| 구간 판정 | 루프 회수/체크포인트(`collector_service.py`) | 신규 체크포인트 필요 |

- 결론: **같은 모듈·같은 키·같은 재시도/세마포어 인프라를 재사용**해 신규 스트리밍 함수를 추가하는 것이 가장 저렴하다. 신규 의존성은 필요 없다.
- 주의: 기존 `_fetch_paged` 의 `inqryDiv=1` + `inqryBgnDt`/`inqryEndDt` 조합은 낙찰정보 오퍼레이션 기준이며, 예비가격 오퍼레이션은 날짜 형식이 `YYYYMMDDHHMM` 이고 창 상한이 1개월로 더 짧다. 값이 아니라 창 분할 상수를 이 경로 전용으로 둔다.

---

## 6. 소급 수집 규모·호출 한도·소요 시간 추정

### 6.1 현재 DB 규모 ([실측], 읽기 전용 조회)

| 테이블 | Servc 행 수 | 최신/최초 |
| --- | ---: | --- |
| `bid_results` | 1,093,198 | `rl_openg_dt` 2012-12-18 ~ 2026-10-02 |
| `bid_announcements` | 2,127,638 | - |
| `bid_results` (Servc, 2020년 이후) | 697,883 | - |
| `bid_prearng_*` 테이블 | 없음 | 신규 생성 필요 |

### 6.2 API 수확량 [실측 → 추정]

- 예비가격 상세는 **공고(집행)당 15행**이다.
- 월별 행 수 실측 평균은 약 107,755행(2025-10~2026-01 4개월 평균)이며, 이를 15로 나눈 월 집행 수는 **약 7,200건**이다.
- 2013-01~2026-10 약 166개월을 전 구간 소급하면 행 약 **1,790만**, 집행 약 **119만**으로 추정된다.

### 6.3 호출 수 추정

| 경로 | 방식 | 호출 수 | 비고 |
| --- | --- | --- | --- |
| 일일 증분 | 신규 용역 공고를 `inqryDiv=2` 로 1콜/공고 | 약 **240콜/일** | 월 7,200집행 ÷ 30일 |
| 소급(날짜 창) | `inqryDiv=1`, 500행/콜, 월 1창 | 약 **215콜/월** | 107,755행 ÷ 500 |
| 소급 3년 | 36개월 창 | 약 **7,700콜** | 3.9M행 ÷ 500 |
| 소급 전 구간 | 166개월 창 | 약 **35,800콜** | 17.9M행 ÷ 500 |

- 공고번호 단건으로 전 공고(약 109만)를 소급하면 **약 109만 콜**로, 날짜 창 경로(약 3.6만 콜)의 30배다. 소급은 반드시 날짜 창 경로를 쓴다.

### 6.4 트래픽 한도 [문서 + 확인 필요]

- data.go.kr 오퍼레이션 페이지 표기: **신청 가능 트래픽 개발계정 1,000 / 운영계정은 활용사례 등록 시 증가**.
- 이 1,000 의 단위(일일 호출 수로 통용)와 실제 승인 트래픽은 **마이페이지 활용신청 현황에서 확인해야 한다**. 기존 수집기 주석은 동시 16·약 1.9 req/s 까지 올린다고 기록하고 있어, 단순 1,000/일과는 배치된다.
- 소요 시간 추정(일일 한도를 소급에만 쓸 때):

| 한도 가정 | 소급 3년 | 소급 전 구간 |
| ---: | ---: | ---: |
| 1,000콜/일 | 약 8일 | 약 36일 |
| 10,000콜/일 | 약 1일 | 약 4일 |

- 일일 증분 240콜/일이 한도를 공유하므로, 소급은 **야간 배치로 분리하고 별도 일일 예산 상한을 두는 것**을 권한다. 기존 동시성 상수 `MAX_CONCURRENT` 를 그대로 쓰되, 소급 전용으로 낮게 잡는 편이 안전하다.

---

## 7. 신규 테이블 설계안 (기존 테이블 무변경)

원칙: 기존 `bid_results`·`bid_announcements` 및 그 밖의 테이블은 **컬럼·타입·인덱스를 일절 바꾸지 않는다**. `bid_restrictions.py` 가 취한 것과 같은 방식으로 신규 테이블만 추가한다. PK 는 기존 모델과 동일하게 `PKBigInteger`(BigInteger autoincrement)를 쓴다.

### 7.1 `bid_prearng_prices` — 공고(집행)당 1행

15개 후보 예비가격은 조회 목적이 개별 검색이 아니라 표시·검증이므로 JSON 컬럼으로 압축한다. child 15행 테이블(약 1,790만 행)을 피해 저장량을 1/15 로 줄인다.

```sql
CREATE TABLE bid_prearng_prices (
    id            BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    bid_ntce_no   VARCHAR(50)  NOT NULL COMMENT '입찰공고번호',
    bid_ntce_ord  VARCHAR(10)  NOT NULL DEFAULT '000' COMMENT '입찰공고차수',
    bid_clsfc_no  VARCHAR(20)  NOT NULL DEFAULT '0'   COMMENT '입찰분류번호',
    rbid_no       VARCHAR(10)  NOT NULL DEFAULT '000' COMMENT '재입찰번호',
    category      VARCHAR(10)  NOT NULL DEFAULT 'Servc' COMMENT '업무구분',
    bid_ntce_nm   VARCHAR(500) NULL COMMENT '공고명',
    dminstt_nm    VARCHAR(200) NULL COMMENT '수요기관명(적재 시 공고에서 해석)',
    bssamt        BIGINT       NULL COMMENT '기초금액',
    plnprc        BIGINT       NULL COMMENT '예정가격',
    sajeong_rate  NUMERIC(10,4) NULL COMMENT '사정률(퍼센트) = plnprc/bssamt*100',
    tot_prce_num  INT          NULL COMMENT '총 복수예비가격 수',
    drwt_prce_num INT          NULL COMMENT '추첨 예비가격 수',
    bss_up_num    INT          NULL COMMENT '기초금액기준 상위갯수',
    slctn_bss     VARCHAR(100) NULL COMMENT '낙찰자선정적용기준내용',
    items         JSON         NULL COMMENT '예비가격 15개 [{sno,bsis_plnprc,drwt_yn,drwt_num}]',
    rl_openg_dt   DATETIME     NULL COMMENT '실제 개찰일시',
    mkng_dt       DATETIME     NULL COMMENT '복수예비가격 작성시각',
    inpt_dt       DATETIME     NULL COMMENT '입력일시',
    raw_data      JSON         NULL COMMENT '전체 원본 데이터',
    collected_at  DATETIME     NOT NULL COMMENT '수집일시',
    UNIQUE KEY uq_bid_prearng_prices (
        bid_ntce_no, bid_ntce_ord, bid_clsfc_no, rbid_no, category
    ),
    KEY ix_prearng_inst_dt (dminstt_nm, category, rl_openg_dt),
    KEY ix_prearng_dt_cat (rl_openg_dt, category),
    KEY ix_prearng_collected (collected_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

- 유니크 키는 API 복합키(공고번호+차수+분류+재입찰번호)에 `category` 를 더한 것으로, `INSERT IGNORE` 적재 시 멱등성을 보장한다.
- `dminstt_nm` 은 API 응답에 없다. 적재 시 `bid_announcements`(또는 `bid_results`)에서 `(bid_ntce_no, 정규화 차수, category)` 로 해석해 채운다. 실제 분포 집계의 조회 성능을 위해 비정규화한다.
- `sajeong_rate` 는 계산값이지만, 분포·최저/최상가 질의가 `plnprc/bssamt` 재계산 없이 인덱스로 끝나도록 저장한다.

### 7.2 `institution_sajeong_rate_stats` — 발주처별 분포 사전집계

`institution_win_rate_stats` 와 같은 패턴으로, 최저가·최상가 조회가 원장 스캔 없이 PK/유니크 조회로 끝나게 한다.

```sql
CREATE TABLE institution_sajeong_rate_stats (
    id               BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    scope            VARCHAR(20)  NOT NULL DEFAULT 'institution' COMMENT 'institution|region|category',
    institution_name VARCHAR(200) NOT NULL DEFAULT '' COMMENT '수요기관명 또는 지역명',
    category         VARCHAR(10)  NOT NULL DEFAULT '' COMMENT '업무구분(전체는 빈 문자열)',
    window_days      INT          NOT NULL DEFAULT 1095 COMMENT '집계 창(일)',
    sample_count     BIGINT       NOT NULL DEFAULT 0 COMMENT '표본 건수',
    min_rate         NUMERIC(10,4) NULL COMMENT '사정률 최솟값',
    max_rate         NUMERIC(10,4) NULL COMMENT '사정률 최댓값',
    p10_rate         NUMERIC(10,4) NULL,
    p50_rate         NUMERIC(10,4) NULL,
    p90_rate         NUMERIC(10,4) NULL,
    rebuilt_at       DATETIME     NOT NULL COMMENT '집계 갱신 시각',
    UNIQUE KEY uq_inst_sajeong (scope, institution_name, category, window_days),
    KEY ix_inst_sajeong_lookup (scope, institution_name, category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

- 최저가·최상가는 `min_rate`/`max_rate` 만 쓰면 되고, 필요 시 백분위를 근거 문장에 더한다.
- `scope` 로 발주처 → 시·도 → 업종 순 대체(fallback)를 같은 테이블에서 표현한다.

---

## 8. 수집기 설계안

### 8.1 경로 두 개

| 경로 | 함수(안) | 용도 | 호출 |
| --- | --- | --- | --- |
| 일일 증분 | `stream_servc_prearng_by_notices(notices, sink)` | 신규 용역 공고 | 1콜/공고 (`inqryDiv=2`) |
| 과거 소급 | `stream_servc_prearng_range(start, end, sink)` | 과거 창 열거 | 월 창 + 500행 페이지 (`inqryDiv=1`) |

- 두 함수 모두 기존 `_make_request_with_retry`, 세마포어, `sink` 스트리밍 패턴을 재사용한다.
- 매퍼는 15행을 **1행으로 집약**한다: `plnprc`, `bssamt`, `sajeong_rate`, `items`(15개 JSON), `drwt_prce_num`(=`drwtYn=Y` 개수), 공통 필드.
- 적재는 기존 `_bulk_insert` + `INSERT IGNORE`(MySQL)로 멱등 처리한다.

### 8.2 창 분할·페이지

- 소급은 달력 월 단위(1일 00:00 ~ 말일 23:59)로 자른다. API 창 상한 약 1개월보다 짧게 유지한다.
- 각 창에서 1페이지로 `totalCount` 를 확인한 뒤 `ceil(totalCount/500)` 페이지를 순회한다.
- `numOfRows` 는 500 고정(1,000은 리셋됨).
- 날짜 파라미터는 반드시 `YYYYMMDDHHMM` 로 조립한다.

### 8.3 오류·체크포인트

- 오류 봉투가 두 종류다: 정상 봉투의 `response.header.resultCode != "00"` 과 게이트웨이의 `nkoneps.com.response.ResponseError`. 신규 경로는 **둘 다** 검사해야 한다.
- `resultCode 06/07` 은 재시도해도 실패하므로 즉시 해당 창을 실패로 기록하고 다음 창으로 넘어간다(기존 `RangeCollectionError` 와 같은 부분 실패 원장).
- 체크포인트는 `MAX(rl_openg_dt)` 또는 별도 수집 상태로 두되, 실패 창을 조용히 건너뛰지 않도록 기존 `failed_ranges` 원장 방식을 따른다.

### 8.4 검증(적재 후)

- 기초 sanity: `plnprc > 0`, `bssamt > 0`, `sajeong_rate` 가 이론 범위(대략 90~105%) 안인지.
- 공고당 행 집약 결과가 15개 `items` 를 갖는지, `drwtYn=Y` 가 4개인지.
- `bid_announcements` 와 (공고번호, 차수, 카테고리) 매칭률을 기록해 커버리지를 측정한다(12장 위험).

---

## 9. 사정률 분포 계산안

### 9.1 정의

- 사정률(%) = `plnprc / bssamt × 100`, `NUMERIC(10,4)` 반올림.
- 대상: `bid_prearng_prices` 의 용역 집행 중 `bssamt > 0` 인 행.

### 9.2 집계 단계

| 우선순위 | scope | 키 | 최소 표본(안) |
| --- | --- | --- | --- |
| 1 | `institution` | `dminstt_nm` + `category` | 30건 |
| 2 | `region` | 시·도 + `category` | 50건 |
| 3 | `category` | `category` | - |

- 창(window)은 기본 최근 3년(1,095일)으로 두고, `window_days` 컬럼으로 확장·축소 여지를 남긴다.
- 표본이 최소치 미만이면 다음 우선순위로 대체하고, 근거 문장에 "표본 부족으로 시·도/업종 평균으로 대체" 를 표시한다(설계 5.4절).
- 최저가·최상가는 선택된 scope 의 `min_rate`/`max_rate` 를 그대로 쓴다.

### 9.3 시·도 매핑

- API 응답에는 지역 정보가 없다. 발주처명(`dminstt_nm`)에서 시·도를 유도해야 하며, 기관명 규칙(예: `경기도청`, `인천광역시`)이 불규칙하다.
- 기존 RAG 의 `refresh_institution_name_catalogs`(기관명 카탈로그)를 참고하되, 시·도 매핑은 **별도 상수·규칙**으로 두고 매핑 실패 시 3순위(업종)로 떨어뜨린다.
- 이는 설계 8절 남은 확인 항목 "참가가능지역 '행 없음' 의 의미" 와 같은 계열의 미해결 입력이다.

### 9.4 현재 평가 엔진과의 연결

- 설계 5.3절대로 사정률 분포가 준비되기 전에는 기존 이론 범위(기초금액 ±2%/±3%, `src/app/services/evaluation_scoring.py:292`)를 유지하고 "과거 실측 아님" 을 표시한다.
- 분포가 준비된 뒤에는 `invert_pass_bid_range` 재사용 경로에 `min_rate`/`max_rate` 를 주입한다. 이 연결은 본 과업 코드 범위 밖이다.

---

## 10. 데이터 무손실(G1) 준수 점검

| 항목 | 상태 |
| --- | --- |
| 기존 테이블 컬럼·타입·인덱스 변경 | 없음. 신규 테이블 2개만 추가 |
| 기존 수집 경로 영향 | 없음. 신규 함수 추가만 |
| 운영 DB 쓰기 | 없음. 조사 중 읽기 전용 조회만 수행 |
| 벡터DB·모델 가중치 | 접촉 없음 |
| 특징 단일화 | 해당 없음(추론 특징 생성 아님) |

---

## 11. 구현 순서 제안

| 단계 | 작업 | 선행 |
| --- | --- | --- |
| 1 | 신규 테이블 2개 Alembic 마이그레이션(기존 무변경) | 없음 |
| 2 | `api_collector.py` 에 예비가격 매퍼·창/페이지 함수 추가 | 1 |
| 3 | 소급 스크립트(`scripts/`)·체크포인트·실패 원장 | 2 |
| 4 | 일일 증분 수집을 기존 수집 파이프라인에 연결 | 2 |
| 5 | `institution_sajeong_rate_stats` 재집계 작업 | 3, 4 |
| 6 | 평가 엔진 사정률 분포 주입(별도 설계) | 5 |

---

## 12. 미확인 사항과 잔여 위험

| 항목 | 상태 | 영향 |
| --- | --- | --- |
| 실제 승인 트래픽 한도 | 미확인(페이지 표기 개발계정 1,000, 단위 확인 필요) | 소급 일정 |
| `dminstt_nm` 매칭률 | 미측정 | 발주처 분포 표본 수 |
| 시·도 매핑 규칙 | 미정 | fallback 정확도 |
| 유찰·예비가격 미작성 공고 비율 | 미측정 | 커버리지 |
| `PrearngPrcePurcnstcst`, `bssAmtPurcnstcst` 의미 | 미확인(표본 빈 값) | 무시 가능(핵심 필드 아님) |
| 적격심사 외(협상 등) 공고의 예비가격 존재 여부 | 미확인 | 커버리지 |

---

## 13. 근거

| 구분 | 자료 |
| --- | --- |
| 오퍼레이션·필드 | [opendata-kr/narajangteo-opening-mcp](https://github.com/opendata-kr/narajangteo-opening-mcp) `endpoints.ts`, `schema.ts` |
| 필드 매핑·표본 | [kyong-ho/bid-result-viewer docs/g2b-api.md](https://github.com/kyong-ho/bid-result-viewer/blob/main/docs/g2b-api.md) |
| 트래픽·서비스 개요 | [조달청_나라장터 낙찰정보서비스](https://www.data.go.kr/data/15129397/openapi.do) |
| 실측 표본 | 본 조사에서 `.env` 키로 직접 호출(4장). 키 값 비기재 |
| DB 규모 | 운영 MySQL 읽기 전용 `COUNT/GROUP BY`(6.1) |
| 기존 코드 | `src/app/services/api_collector.py`, `src/app/services/collector_service.py`, `src/app/models/bids.py`, `src/app/models/bid_restrictions.py` |
| 설계 정본 | [web_feedback_redesign_20261006.md](../design/web_feedback_redesign_20261006.md) 5.3절, 7절 4단계, 8절 |

**Sources:** [opendata-kr/narajangteo-opening-mcp](https://github.com/opendata-kr/narajangteo-opening-mcp), [kyong-ho/bid-result-viewer g2b-api.md](https://github.com/kyong-ho/bid-result-viewer/blob/main/docs/g2b-api.md), [조달청_나라장터 낙찰정보서비스](https://www.data.go.kr/data/15129397/openapi.do)
