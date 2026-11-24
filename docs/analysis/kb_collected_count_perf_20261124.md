# KB 수집일 폴백 건수 질의 비용 축소 (2026-11-24)

> 작성일: 2026-11-24
> 작업: `task_fc0160a0262f` / 브랜치 `kwanbum217/kb-count-perf`
> 대상: `src/app/services/kb_document_builder.py` `_resolve_announcements`

---

## 1. 요약

`_resolve_announcements` 의 수집일 폴백 건수 질의를 `min(count, limit)` 만 정확하면
되도록 상한 집계로 바꿨다. 선택되는 공고 집합·순서·`total` 은 바뀌지 않는다.
운영 DB 에서 상한 집계가 520,001건에서 멈추는 것을 확인했고, 이는 곧
`total = min(count, 520,000) = 520,000` 이 기존과 같다는 증명이다.

| 항목 | 변경 전 | 변경 후 |
| --- | --- | --- |
| 폴백 건수 질의 형태 | 후보 전량 `COUNT(*)` | `LIMIT limit+1` 파생 테이블 `COUNT(*)` |
| 후보 행 수(운영, 2026-11-24 기준) | 5,599,322 | 최대 520,001 |
| 소요(운영, 웜) | 113초(2026-11-23 기록), 516.6초 미완료(이번 실측) | 9.43초, 4.25초, 1.87초 |
| `total` | `min(count, 520,000)` | `min(min(count, 520,001), 520,000)` = 동일 |

---

## 2. 원인

`_resolve_announcements` 는 공고일(`bid_ntce_dt`) 창의 건수가 0일 때만 수집일
(`collected_at`) 창의 건수를 센다. 문제의 질의는 다음 두 조건을 함께 건다.

- `similar_announcement_latest_filter`: 같은 `(bid_ntce_no, category)` 그룹에 더 새로운
  차수가 있는지 행마다 `NOT EXISTS` 로 판정한다.
- `not_cancelled_clause`: 최신 차수가 취소공고인 행을 제외한다.

운영 DB 실측(2026-11-24):

| 구분 | 값 |
| --- | --- |
| `bid_announcements` 전체 행 | 5,599,322 |
| `collected_at` 범위 | 2026-03-01 ~ 2026-11-24 |
| `bid_ntce_dt` 범위 | 2015-01-01 ~ 2026-11-23 |
| 공고일 1년 창 후보 | 510,252 |
| 수집일 1년 창 후보 | 5,599,322 (전체) |

`EXPLAIN` 은 외부 테이블을 `ix_bid_ann_collected` 범위 스캔(추정 1,066,982행)으로,
상관 서브쿼리를 유니크 인덱스 `bid_announcements_bid_ntce_no_bid_ntce_ord_5d538568_uniq`
의 `bid_ntce_no` 접두 참조(`key_len` 202)로 풀었다. 서브쿼리는 행마다 `category`,
`bid_ntce_dt`, `collected_at`, `ntce_kind_nm` 을 클러스터드 인덱스에서 다시 읽어야 하고,
외부 행 자체도 같은 컬럼이 필요해 후보 1행당 임의 읽기가 2회 이상 발생한다.

공고일 경로는 창 자체가 510,252행으로 상한(520,000)보다 작아 같은 형태라도 비용이
1/10 이다. 수집일 폴백만 후보가 전체 테이블이라 5,599,322행을 돈다. 운영
`innodb_buffer_pool_size` 는 2GB 로 테이블보다 작아, 콜드 상태에서는 이 임의 읽기가
디스크로 떨어진다.

이번 실측에서 변경 전 질의(동등한 손 SQL)는 516.6초에 완료되지 못하고
`(2013, 'Lost connection to MySQL server during query')` 로 끊겼다. 끊긴 원인은
확인하지 못했다(서버 재시작은 아님). 2026-11-23 빌더가 기록한 113초는 웜 상태의
값으로 본다.

---

## 3. 변경 내용

`total` 은 `PagedQuerySequence` 의 길이와 `min(count, limit)` 에만 쓰인다. 따라서
건수를 `limit` 에서 끊어 세도 결과가 같다. 상한 집계는 `limit+1` 건을 찾는 즉시
스캔을 멈춘다.

```python
def _count_announcements_capped(db: Session, stmt: Any, limit: int) -> int:
    capped = db.scalar(select(func.count()).select_from(stmt.limit(limit + 1).subquery()))
    return min(capped or 0, limit)
```

수집일 폴백 건수만 이 함수로 바꿨다. 공고일 경로의 건수 질의는 후보가 창 크기로
제한되어 이득이 없고 정상 경로이므로 기존 전량 집계를 그대로 둔다. 선택 질의
(`base_query`), keyset 페이징, 정렬, `total` 계산식은 손대지 않았다.

동등성:

- 참 건수를 `C`, 상한을 `L` 이라 하면 새 함수의 반환값은 `min(C, L+1, L) = min(C, L)`.
- `C = 0` 이면 폴백 미사용 판정도, `C > 0` 이면 폴백 사용 판정도 그대로다.
- 반환 시퀀스는 `min(C, L)` 길이의 keyset 페이징이며, 상한이 걸린 경우에도 실제
  매칭 행이 `L` 이상 존재하므로 첫 `L` 건의 집합·순서는 같다.

---

## 4. 운영 DB 측정

측정 조건:

- MySQL 8, `innodb_buffer_pool_size` = 2GB, 읽기 전용 세션(`scripts/db_readonly_query.py`).
- 기준 시각 2026-11-24, `KB_MAX_DOCUMENTS` 기본값 520,000.
- 질의는 한 번에 하나만 직렬 실행했다.
- 변경 전/후 모두 같은 손 SQL(ORM 컴파일 결과와 동일 술어)을 사용했다. 변경 전
  측정 SQL 은 `collected_at`/`id` 동률 비교 두 항을 생략한 형태로, 실제 질의 비용의
  하한이다.

| 단계 | 조건 | 소요 | 결과 |
| --- | --- | --- | --- |
| 변경 전 1회차 | 후보 5,599,322 | 516.60초 후 연결 종료 | 미완료, 원인 미확인(서버 재시작은 아님) |
| 변경 전 참고 | 2026-11-23 빌더 기록(웜) | 113초 | - |
| 변경 후 1회차 | 첫 실행, 상한 520,001 | 69.41초 | 520,001 |
| 변경 후 2회차 | 웜 | 9.43초 | 520,001 |
| 변경 후 3회차(정확 SQL) | 웜 | 4.25초 | 520,001 |
| 변경 후 4회차(정확 SQL) | 웜 | 1.87초 | 520,001 |

측정 시점의 버퍼 풀 상태는 확인하지 못했다. 변경 전 1회차는 완료되지 않아 값을
얻지 못했고, 변경 후 회차는 앞선 회차가 버퍼를 채운 뒤의 연속 실행이다.

변경 후 질의가 520,001건을 반환했다는 것은 참 건수 `C >= 520,001` 의 직접 증거다.
따라서 기존 `total = min(C, 520,000) = 520,000` 과 새 `total = 520,000` 은 같다.
전량 `COUNT(*)` 는 다시 돌리지 않았다. 후보 5.6M행을 도는 질의가 공유 DB 에 큰
부담이 될 수 있어, 상한 반환값 자체로 동등성을 증명하는 편이 안전하다.

해석:

- 웜 기준 113초 -> 1.87~9.43초로 약 12~60배 줄었다. 변경 전 1회차(516.60초 후 연결
  종료, 미완료) 대비로는 69.41초에 끝났다.
- 남은 비용은 실제로 색인할 문서 수(최대 520,000)에 비례하는 상한이다. 후보 테이블
  크기가 더 커져도 폴백 건수 질의 비용은 늘지 않는다.
- 근본 비용은 `collected_at` 범위를 `(category, collected_at, bid_ntce_dt, id)` 등
  커버링 인덱스로 좁히면 더 줄일 수 있지만, 이번 작업 범위는 인덱스 추가·스키마
  변경이 아니다. 필요하면 별도 승인 과제로 다룬다.

---

## 5. 시험

`tests/test_kb_collected_count_perf_20261124.py` (인메모리 SQLite, 로컬 .env 미사용):

| 시험 | 확인 내용 |
| --- | --- |
| `test_capped_count_returns_min_of_count_and_limit` | 상한 함수가 `min(count, limit)` 을 반환 |
| `test_collected_fallback_total_matches_exact_count_below_limit` | 상한 미만일 때 `total` == 전량 집계값, 실행 SQL 에 `LIMIT` 존재 |
| `test_collected_fallback_total_caps_at_limit_and_keeps_newest_order` | 상한 초과 시 `total` == limit, 반환 행은 최신 수집 순 상위 limit 건 |
| `test_collected_fallback_latest_ord_and_cancelled_semantics_unchanged` | 최신 차수 1건만 선택, 최신 차수가 취소공고면 이전 차수 미대체 |
| `test_notice_path_count_query_stays_exact_and_uncapped` | 공고일 경로는 기존 전량 집계(`LIMIT` 없음) 유지 |
| `test_collected_fallback_unavailable_when_no_rows` | 후보 0건이면 `announcements_unavailable` 유지 |

---

## 6. 검증 명령 결과

| 명령 | 결과 |
| --- | --- |
| `uv run pytest -q -m 'not data_assets' tests/test_kb_collected_count_perf_20261124.py tests/test_kb_builder.py` | 24 passed |
| `uv run mypy src` | Success: no issues found in 156 source files |
| `python3 scripts/validate_agent_rules.py --quiet` | 22/22 통과 |
| `uv run pytest -q -m 'not data_assets' tests/` | 11,633 passed, 41 skipped, 3 deselected, 2 xfailed (593.77초) |

전량 시험은 커밋 전 최종 실행에서 통과했다.

---

## 7. 범위 밖 / 남은 위험

- 인덱스 추가와 스키마 변경은 하지 않았다. `collected_at` 폴백의 잔여 비용은
  커버링 인덱스 후보 과제로 남긴다.
- 공고일 경로의 건수 질의는 종전과 같다. 창이 상한을 넘으면 같은 비용 문제가
  생길 수 있으나, 현재 후보는 510,252행으로 상한 미만이다.
- 폴백 경로는 비상 경로라 운영에서 상시 타지는 않는다. 이번 변경은 그 비상 시
  색인 작업이 수 분 멈추는 위험을 상한 비용으로 바꾼 것이다.
