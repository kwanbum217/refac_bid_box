# 개찰결과 재입찰번호(rbidNo) 유니크 키 실측

> **작성일**: 2026-11-02
> **대상 테이블**: `bid_openg_results`
> **가정 키**: (공고번호, 차수, 재입찰번호, 분류) = `bid_ntce_no`, `bid_ntce_ord`, `rbid_no`, `category`
> **판정**: 표본 0건. 위반 0건은 공허하며 **유니크 키 유지 여부는 미검증**입니다.
> **DB 접근**: 읽기 전용. `scripts/db_readonly_query.py` 로만 질의했고 쓰기·적재·API 호출·마이그레이션은 없습니다.

---

## 1. 목적

`docs/analysis/fail_bid_collection_design_20261031.md` 8항이 남긴 확인 필요 사항을 닫습니다. 개찰결과 적재가 `(bid_ntce_no, bid_ntce_ord, rbid_no, category)` 를 유니크 키로 가정하는데, 같은 공고·차수·분류 안에서 `rbid_no` 가 중복되는지 운영 DB 에서 실측합니다. 이번 작업은 적재와 나라장터 API 호출을 하지 않습니다.

## 2. 측정 환경

| 항목 | 값 | 확인 방법 |
| --- | --- | --- |
| DB | `procurement` | `SELECT DATABASE()` |
| 서버 | MySQL 8.0.46, 포트 3306 | `SELECT VERSION(), @@port` |
| 접속 경로 | `uv run python scripts/db_readonly_query.py --sql "..."` | 단일 문장, `READ ONLY` 트랜잭션 |
| 실행일 | 2026-11-02 | - |

## 3. 실제 스키마의 키 구성

| 인덱스 | 컬럼 | 유니크 |
| --- | --- | :---: |
| `uq_bid_openg_results` | `bid_ntce_no`, `bid_ntce_ord`, `rbid_no`, `category` | 예 |
| `PRIMARY` | `id` | 예 |
| `ix_openg_cat_dt` | `category`, `openg_dt` | 아니오 |
| `ix_openg_status_dt` | `progrs_div_cd_nm`, `openg_dt` | 아니오 |
| `ix_openg_inst_cat_dt` | `dminstt_nm`, `category`, `openg_dt` | 아니오 |
| `ix_openg_notice` | `bid_ntce_no`, `category` | 아니오 |

가정 키의 "분류"는 실제 인덱스에서 `category` 입니다. `bid_clsfc_no`(분류번호)는 컬럼으로 존재하지만 **유니크 키에 포함되지 않습니다.** 설계 문서가 `bid_clsfc_no` 를 의도했다면 키 정의 자체가 어긋나므로 별도 확인이 필요합니다.

## 4. 측정 결과

### 4.1 적재 상태

| 지표 | 값 |
| --- | ---: |
| `bid_openg_results` 행 수 | **0** |
| 가정 키 전체 조합 수 | 0 |
| `(bid_ntce_no, bid_ntce_ord, category)` 조합 수 | 0 |
| `rbid_no` 종류 수 | 0 |
| `AUTO_INCREMENT` | 1 |
| `CREATE_TIME` | 2026-10-31 12:02:25 |
| `UPDATE_TIME` | NULL |

`AUTO_INCREMENT = 1` 과 `UPDATE_TIME = NULL` 은 테이블 생성 이후 실제 INSERT 가 한 번도 커밋되지 않았음을 뜻합니다. 표본이 0건이므로 아래 중복 건수는 모두 공허한 0 입니다.

### 4.2 가정 키 중복

```sql
SELECT COUNT(*) AS dup_groups, COALESCE(SUM(n - 1), 0) AS dup_rows
FROM (
  SELECT bid_ntce_no, bid_ntce_ord, rbid_no, category, COUNT(*) AS n
  FROM bid_openg_results
  GROUP BY bid_ntce_no, bid_ntce_ord, rbid_no, category
  HAVING COUNT(*) > 1
) AS g
```

| 중복 그룹 수 | 중복 초과 행 수 | 표본 |
| ---: | ---: | ---: |
| 0 | 0 | 0 |

중복이 0건이므로 예시 키는 없습니다. 다만 이 0 은 "중복이 없다"가 아니라 **"검사할 데이터가 없다"** 입니다.

### 4.3 `rbid_no` 중복 관점

가정 키를 `(bid_ntce_no, bid_ntce_ord, category)` 로 줄이고 그 안에서 `rbid_no` 가 여러 번 나타나는지를 같은 방식으로 집계했으나, 행이 0건이라 그룹 자체가 생기지 않았습니다. `rbid_no` 값 분포(예: 항상 `000` 인지)도 표본이 없어 판정할 수 없습니다.

### 4.4 대조군: 기존 수집 테이블

| 테이블 | 행 수 | 키 | 키 조합 수 | 중복 |
| --- | ---: | --- | ---: | ---: |
| `bid_results` | 3,464,615 | `bid_ntce_no`, `bid_ntce_ord`, `category` | 3,464,615 | 0 |
| `bid_announcements` | 5,560,232 | `bid_ntce_no`, `bid_ntce_ord`, `category` | 5,560,232 | 0 |

기존 두 테이블은 해당 키에서 완전 유니크입니다. 그러나 `bid_results` 에는 `rbid_no` 와 `bid_clsfc_no` 컬럼이 없고 `raw_data` 도 NULL 이라, 재입찰번호 중복 여부를 대신 측정할 대체 모집단이 되지 못합니다.

## 5. 판정

1. **중복 건수 0건, 표본 0건.** 운영 DB 의 `bid_openg_results` 가 비어 있어 가정 키 위반은 관측되지 않았지만, 이는 가정을 지지하는 증거가 아닙니다.
2. **유니크 키는 잠정 유지합니다.** 현재 위반이 없고, 키를 바꿀 근거도 없습니다. 다만 `uq_bid_openg_results` 가 실제로 유지 가능한지는 소급 적재 이후에만 판정할 수 있습니다.
3. **미검증 항목.** (a) 같은 공고·차수·분류에서 `rbid_no` 가 실제로 여러 값으로 갈리는지, (b) `rbid_no` 가 상수(예: `000`)라 키가 사실상 `(bid_ntce_no, bid_ntce_ord, category)` 로 축소되는지, (c) 설계 의도의 "분류"가 `category` 인지 `bid_clsfc_no` 인지.
4. **선행 조건.** 소급 적재(`scripts/backfill_openg_results.py --execute`)는 사용자 승인 전이므로 실행하지 않았습니다.

## 6. 적재 후 재검증 절차

`--execute` 승인과 적재 완료 후, 같은 읽기 전용 진입점으로 아래를 순서대로 실행해 판정을 확정합니다.

1. 4.2 의 중복 집계 질의를 다시 실행해 `dup_groups` 와 `dup_rows` 를 기록합니다.
2. 키 컬럼 NULL/빈 문자열 여부를 확인합니다. 네 컬럼 모두 `NOT NULL` 이지만 빈 문자열은 별도로 셉니다.
3. `SELECT rbid_no, COUNT(*) FROM bid_openg_results GROUP BY rbid_no ORDER BY 2 DESC` 로 값 분포를 확인해 상수 여부를 판정합니다.
4. 중복이 1건 이상이면 예시 키를 5건 이하로 문서에 남기고, `progrs_div_cd_nm`·`prtcpt_cnum` 추가로 해소되는지 확인합니다.
5. 중복이 0건이고 `rbid_no` 가 단일 값이 아니면 유니크 키 유지를 확정합니다.

## 7. 변경 범위

문서 1건만 추가했습니다. 코드·스키마·데이터 변경은 없습니다.
