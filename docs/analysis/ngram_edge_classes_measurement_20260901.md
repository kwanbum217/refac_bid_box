# ngram 경계값 7 클래스 실측 (2026-09-01)

> **작성일**: 2026-09-01
> **측정 환경**: 운영 MySQL 8 컨테이너(`refac_bid_box-db-1`) 안의 격리 스키마 `test_procurement_ngram`
> **하네스**: `tests/test_ngram_prefilter_equivalence.py -m mysql_integration`
> **선행 조건**: 운영 FULLTEXT 인덱스 생성 완료 (2026-09-01)

---

## 1. 결론

**7 클래스 중 2 건이 조용한 누락(silent false-negative)을 실제로 일으킵니다.**
나머지 5 건은 표본이 있는 환경에서 ID 집합이 완전히 일치했습니다.

| ID | 키워드 | 클래스 | 실측 | `is_safe_for_ngram` 판정 |
| --- | --- | --- | :---: | :---: |
| `edge_04` | `한국도로공사(본사)` | 괄호 | 동등 | `false` 유지 (보수) |
| `edge_05` | `서울-경기` | 하이픈 | 동등 | `false` 유지 (보수) |
| `edge_07` | `K-water2026` | 영문숫자 혼합 | **누락 1건** | **`false` 필수** |
| `edge_09` | `100%` | `%` | 동등 | `false` 유지 (보수) |
| `edge_10` | `공사_1차` | `_` | 동등 | `false` 유지 (보수) |
| `edge_11` | `공사's` | 따옴표 | **누락 1건** | **`false` 필수** |
| `edge_12` | `+공사*` | boolean 연산자 | 동등 | `false` 유지 (보수) |

누락 2 건은 모두 `bid_announcements.dminstt_nm` 에서 baseline LIKE 1 건 대비 MATCH+LIKE 0 건이며,
`cat`·`date` 필터 유무와 무관하게 재현됩니다.

**픽스처 값은 바꾸지 않습니다.** 동등이 확인된 5 건도 `false` 를 유지합니다. 운영 데이터에
해당 키워드 표본이 없어(2 절) 켜서 얻을 성능 이득이 사실상 없고, 켜는 순간 위험만 도입되기
때문입니다.

---

## 2. 운영 데이터에는 6 건의 표본이 없습니다

먼저 운영 스키마(`procurement`)에서 같은 하네스를 돌렸을 때 7 클래스가 **전부 PASS** 했습니다.
그러나 이는 실측이 아닙니다. `compare_id_sets` 는 공집합끼리도 동등으로 판정합니다.

| ID | 운영 `bid_announcements` LIKE 건수 |
| --- | ---: |
| `edge_04` | 0 |
| `edge_05` | 0 |
| `edge_07` | 0 |
| `edge_09` | **39** |
| `edge_10` | 0 |
| `edge_11` | 0 |
| `edge_12` | 0 |

**표본 0 건의 PASS 를 실측으로 읽지 마십시오.** 실제 판정은 표본이 심어진 격리 픽스처
(`tests/fixtures/ngram_mysql_init.sql`)에서만 가능합니다. 토큰화 의미론은 데이터 규모와
무관하므로 소량 픽스처로도 유효합니다.

---

## 3. 이 측정을 막고 있던 결함 2 건

### 3.1 런북이 잘못된 컬럼을 지정했습니다

`ngram_fulltext_cutover_runbook.md` 3.2 절은 `bid_results` 에 `bidwinnr_nm` 인덱스를 만들라고
적었습니다. 그러나 운영 코드가 MATCH 를 거는 컬럼은 다음 둘뿐입니다.

- `src/rag/structured_data.py:138` `BidResult.dminstt_nm.match(...)`
- `src/rag/structured_data.py:163` `BidAnnouncement.dminstt_nm.match(...)`

`bidwinnr_nm` 에는 MATCH 를 걸지 않습니다. Wave F 가 보고한 `bidwinnr_nm` 2.9 배 개선은 아직
구현되지 않은 집계 경로의 probe 값입니다. 이 오기 때문에 첫 실행에서 하네스가 요구하는
`bid_results.dminstt_nm` 인덱스가 없어 7 클래스가 전부 skip 됐습니다.

운영에는 오기로 생성된 `ft_bidwinnr_nm` 이 남아 있습니다. 현재 코드가 쓰지 않으므로 조회에는
영향이 없고 쓰기 오버헤드만 있습니다. 제거 여부는 별도 판단 사항입니다.

### 3.2 격리 픽스처에 날짜 컬럼이 없었습니다

I-H 가 `cat`·`date` 필터 조합을 하네스에 추가할 때 `ngram_mysql_init.sql` 이 함께 갱신되지
않아, 격리 환경에서 `Unknown column 'bid_ntce_dt'` 로 7 건이 실패했습니다. **CI job
`mysql-ngram-integration` 도 같은 이유로 통과할 수 없는 상태였습니다.** 운영 스키마와 같은
`DATETIME(6)` 컬럼을 기본값과 함께 추가해 해소했습니다.

---

## 4. 실행 절차 재현

```bash
docker compose exec -T -e MYSQL_PWD=<pw> db \
  mysql -u root --default-character-set=utf8mb4 -e \
  "CREATE DATABASE IF NOT EXISTS test_procurement_ngram CHARACTER SET utf8mb4;"

docker compose exec -T -e MYSQL_PWD=<pw> db \
  mysql -u root --default-character-set=utf8mb4 test_procurement_ngram \
  < tests/fixtures/ngram_mysql_init.sql

MYSQL_TEST_URL="mysql+pymysql://root:<pw>@localhost:3306/test_procurement_ngram" \
  uv run pytest tests/test_ngram_prefilter_equivalence.py -m mysql_integration -v -rs
```

결과: `2 failed, 7 passed` (실패는 `edge_07`, `edge_11` 이며 이 문서 1 절의 판정 근거입니다).

---

## 5. 측정 함정

| 함정 | 실제 |
| --- | --- |
| 운영 스키마 PASS = 실측 | 표본 0 건이면 공집합끼리 자명 통과 |
| `mysql` 클라이언트 기본 charset | `--default-character-set=utf8mb4` 없으면 한글이 `?` 로 깨져 매칭이 0 이 됨 |
| CI job 존재 = 검증됨 | 픽스처 스키마가 하네스보다 뒤처져 있으면 전부 실패 |
