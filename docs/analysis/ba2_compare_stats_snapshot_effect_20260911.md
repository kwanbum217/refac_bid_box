# BA2 compare-stats 사전 집계 전환 효과 실측

> **작성일**: 2026-09-11
> **작성자**: 코디네이터 직접 측정 (Task 로 위임하지 않음)
> **아티팩트**: [`data/benchmarks/compare_stats_segments_after_snapshot_20260911.json`](../../data/benchmarks/compare_stats_segments_after_snapshot_20260911.json)
> **기준선**: [`az3_compare_stats_attribution_20260911.md`](az3_compare_stats_attribution_20260911.md)

---

## 1. 결론

**캐시 미적중 종단이 3,725ms 에서 505ms 가 됐습니다.**

| 지표 | 전환 전 (AZ3) | 전환 후 (BA2) |
| --- | ---: | ---: |
| 정상상태 wall P50 | 3,724.8ms | **505.0ms** |
| 정상상태 범위 | 3,672.1~4,181.8 | **492~509** |
| 정상상태 산포 | 510ms | **18ms** |
| 가열 회차 | 6,972.8 / 4,655.3 | 662 / 567 |
| 유효 표본 | 12/12 | **12/12** |

**판정은 둘로 나누어 적습니다.**

- **구조 차이는 확정입니다.** `agency_announce_top10` 과 `matched_count` 두 구간이
  **0.0ms** 입니다. 실시간 집계가 그 구간에서 더 이상 실행되지 않는다는 구조적
  사실이며 타이밍 잡음과 무관합니다.
- **절대 시간 차이는 산포 초과(참고)입니다.** 두 조건의 범위가 겹치지 않고
  (3,672~4,182 대 492~509) 평균차 3,272ms 가 산포 합 528ms 를 크게 넘지만,
  이 저장소의 판정 규칙상 시간 분기에 확정은 없습니다.

---

## 2. 구간별 이동

| 구간 | 전환 전 P50 | 전환 후 P50 | 비중 변화 |
| --- | ---: | ---: | --- |
| `agency_announce_top10` | 2,097.1ms | **0.0ms** | 56.3% -> 0.0% |
| `matched_count` | 1,135.5ms | **0.0ms** | 30.5% -> 0.0% |
| `announce_by_month` | 338.9ms | 340.1ms | 9.1% -> **67.7%** |
| `result_by_month` | 157.9ms | 154.8ms | 4.2% -> **30.8%** |
| `announcement_summary` | 1.2ms | 1.2ms | 0.0% |
| `result_summary` | 0.5ms | 0.5ms | 0.0% |
| `residual_ms` | 3.7ms | 2.9ms | - |

**월별 두 집계는 값이 변하지 않았습니다.** 이번 변경의 범위 밖이므로 당연하며,
절대값이 그대로인 것이 오히려 측정의 신뢰도를 뒷받침합니다. 비중만 13.3% 에서
**98.5%** 로 올라갔습니다. 다음 최적화 대상입니다.

`cursor_count` 는 전후 모두 **8** 입니다. 무거운 집계 두 건이 사라진 자리에
스냅샷 기본키 조회 두 건이 들어갔기 때문입니다.

---

## 3. 결과 동등성은 런타임으로 확인했습니다

코드 대조(독립 검토)만으로 끝내지 않고 같은 DB 에서 두 경로를 직접 돌려
비교했습니다.

| 항목 | 결과 |
| --- | --- |
| 기관 상위 10 리스트 | 스냅샷과 실시간이 **완전 일치** |
| `matched_count` | 326,716. 2026-09-11 `EXPLAIN ANALYZE` 실측 행 수와 일치 |

---

## 4. 재집계 비용

최초 재집계는 **8.72초** 입니다(`window_days=365`, 두 스냅샷). 야간과 수집 직후에
한 번씩 돌므로 요청 경로에서 3.2초를 걷어내는 대가로 하루 몇 차례 8.7초를
씁니다.

---

## 5. 운영 반영 시 걸린 함정

**컨테이너에 볼륨 마운트가 없습니다.** `docker-compose.yml` 의 `app` 서비스는
소스를 이미지에 구워 넣습니다. 병합 직후 `alembic upgrade head` 를 돌렸더니
성공한 것처럼 보였지만 실제로는 컨테이너에 새 리비전 파일이 없어 아무 일도
일어나지 않았습니다. `alembic current` 가 `a1b2c3d4e5f6` 그대로였습니다.

**`SHOW TABLES LIKE` 의 출력 형식에도 주의하십시오.** 결과가 0행일 때도
`Tables_in_procurement (bid_compare_stats_snapshots)` 라는 헤더가 나오므로 이것을
결과 행으로 오독하면 테이블이 생긴 것으로 착각합니다. 이번에 실제로 한 번
오독했고 `DESC` 로 다시 확인해 바로잡았습니다.

절차는 다음과 같습니다.

```sh
docker compose build app && docker compose up -d app
docker compose exec -T app alembic upgrade head
uv run python scripts/db_readonly_query.py --sql "DESC bid_compare_stats_snapshots"
```

---

## 6. 다음 단계

1. `announce_by_month`(340ms)와 `result_by_month`(155ms)가 이제 종단의 98.5% 입니다.
   같은 사전 집계 방식이 적용 가능한지 검토합니다.
2. 남은 종단 505ms 중 비 SQL 구간은 `residual_ms` 2.9ms 뿐입니다. SQL 밖에서
   얻을 것은 여전히 없습니다.
3. 개선 판정 시 이 문서의 정상상태 10회차(산포 18ms)를 기준선으로 삼으십시오.
   가열 2회차를 섞지 마십시오.
