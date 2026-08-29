# 공고 상세 유사공고 쿼리 전후 실측 (2026-08-30)

> **측정일**: 2026-08-30
> **대상 커밋**: `49bb224` (P2 `similar_announcement_latest_filter` 병합 후)
> **환경**: Docker compose, MySQL 8.0.46, `bid_announcements` 5,490,072행 / `bid_results` 3,423,008행
> **표본 행**: `id=10187639`, `category=Servc`, 동일 기관·카테고리 후보 2,894건

---

## 1. 결론

| 구현 | 실행 시간 | 접근 경로 |
| --- | ---: | --- |
| 구 `latest_announcement_filter` | **60초 상한 내 미완료** (한 행도 반환 못 함) | 테이블 풀스캔 5.49M행(23.75초) 후 전역 정렬 |
| 신 `similar_announcement_latest_filter` | **5.09ms** | `dminstt_nm` 인덱스 범위 스캔 후 유니크 인덱스 antijoin |

2026-08-28 측정 중 관측된 `db` 컨테이너 175% CPU 의 정체가 이 쿼리로 **확정**됐습니다.
원인 특정에 그쳤던 이전 기록과 달리, 이번에 실행 계획과 소요 시간으로 확인했습니다.

---

## 2. EXPLAIN ANALYZE 요약

### 2.1 구 구현 (window 랭킹)

```
-> Limit: 5 row(s)  (actual time=60300..60300 rows=0 loops=1)
    -> Nested loop inner join  (actual time=60300..60300 rows=0 loops=1)
        -> Index range scan on bid_announcements using bid_announcements_dminstt_nm_952da702
           (actual time=0.152..1.25 rows=453 loops=1)
        -> Covering index lookup on latest_ann using <auto_key0> (never executed)
            -> Materialize (never executed)
                -> Window aggregate: row_number() OVER (PARTITION BY bid_ntce_no, category ...)
                   (actual time=60299..60299 rows=0 loops=1)
                    -> Sort: bid_ntce_no, category, bid_ntce_ord DESC, ...
                       (cost=1.96e+6 rows=2.18e+6) (actual time=60299..60299 rows=0 loops=1)
                        -> Table scan on bid_announcements
                           (actual time=0.0608..23753 rows=5.49e+6 loops=1)
```

기관 인덱스 스캔은 1.25ms 에 453행으로 끝납니다. 시간을 쓰는 것은 그 뒤의
**전체 테이블 스캔과 전역 정렬**이며, `MAX_EXECUTION_TIME(60000)` 상한에 걸려
materialize 를 끝내지 못했습니다. 상한이 없었다면 그대로 더 돌았을 것입니다.

### 2.2 신 구현 (NOT EXISTS antijoin)

```
-> Limit: 5 row(s)  (cost=23059 rows=5) (actual time=4.26..5.09 rows=5 loops=1)
    -> Nested loop antijoin  (actual time=4.26..5.08 rows=5 loops=1)
        -> Index range scan on bid_announcements using bid_announcements_dminstt_nm_952da702
           (actual time=0.252..3.91 rows=459 loops=1)
        -> Filter: (더 최신 차수 존재 여부)  (actual time=0.164..0.164 rows=0.286 loops=7)
            -> Index lookup on bid_announcements_1
               using bid_announcements_bid_ntce_no_bid_ntce_ord_5d538568_uniq
               (bid_ntce_no=...)  (actual time=0.162..0.162 rows=1.43 loops=7)
```

후보를 먼저 좁히므로 `LIMIT 5` 를 채우는 데 antijoin 이 7회만 돕니다.
기존 유니크 제약 인덱스가 상관 서브쿼리를 그대로 받아 **추가 인덱스가 필요하지 않습니다.**

---

## 3. 상세 API 레이턴시 실측

`GET /api/v1/bids/{pk}` 5개 공고 x 24회, warmup 제외, 120표본.

| 지표 | 값 (ms) |
| ---: | ---: |
| 최소 | 8.66 |
| P50 | **10.34** |
| P95 | **47.98** |
| 최대 | 58.66 |

수정 전에는 유사 공고 조회 SQL 하나가 60초를 넘겨 이 엔드포인트의 전후 비교
측정 자체가 불가능했습니다. 따라서 전후 비율이 아니라 **미완료 -> P95 47.98ms**
로 기록합니다.

---

## 4. 인덱스 판단

추가 인덱스는 **두지 않습니다.** 신 구현이 이미 기존 인덱스 두 개
(`bid_announcements_dminstt_nm_952da702`, 유니크 제약 인덱스)만으로 5ms 대에
끝나므로, `(category, dminstt_nm)` 복합 인덱스는 쓰기 비용만 늘립니다.
필요해지는 시점은 단일 기관 후보 수가 현재의 2,894건에서 크게 늘어날 때입니다.

---

## 5. 재현 명령

```bash
docker compose exec -T db mysql -uroot -p<암호> --default-character-set=utf8mb4 < /tmp/new_explain.sql
uv run python /tmp/measure_detail.py
```

`@cat`, `@dmi` 는 `collate utf8mb4_unicode_ci` 로 선언해야 합니다. 선언하지 않으면
`Illegal mix of collations` 로 실패합니다.
