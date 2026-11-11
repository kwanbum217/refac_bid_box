# schedule_run_log 도입 (2026-11-11)

> 목적: 스케줄 실행 이력을 Redis 7일 TTL 밖에 영구 보관해 실패 원인을 사후에 확정한다.

## 1. 배경

`bidbox:worker:schedules` 는 스케줄별 마지막 실행 시각과 성공 여부만 7일간 남깁니다.
2026-10-17 이후 `prearng_daily` 가 실행되지 않은 원인을 실패 기록이 사라진 뒤에는
확정할 수 없었습니다. Redis 기록은 그대로 두고, 실행 1건마다 `schedule_run_log`
한 행을 추가로 남깁니다. 기존 테이블은 변경하지 않습니다(G1).

| 컬럼 | 의미 |
| --- | --- |
| `schedule_name` | `_record_schedule` 인자 이름 |
| `started_at`, `finished_at` | UTC naive 실행 구간 |
| `duration_ms` | 실행 시간(밀리초) |
| `success` | `success_statuses` 판정 결과 |
| `status` | 태스크가 반환한 status. 예외 경로는 NULL |
| `error_type`, `error_message` | 예외 타입·메시지(1000자에서 자름) |
| `worker_id` | 기록한 워커 식별자 |

## 2. 조회 예시

스케줄별 최근 실패:

```sql
SELECT schedule_name, started_at, duration_ms, status, error_type, error_message
FROM schedule_run_log
WHERE success = 0
ORDER BY started_at DESC
LIMIT 20;
```

최근 30일 중 daily 슬롯 공백 찾기:

```sql
WITH RECURSIVE days AS (
  SELECT UTC_DATE() - INTERVAL 29 DAY AS day
  UNION ALL
  SELECT day + INTERVAL 1 DAY FROM days WHERE day < UTC_DATE()
)
SELECT days.day
FROM days
WHERE NOT EXISTS (
  SELECT 1 FROM schedule_run_log l
  WHERE l.schedule_name = 'prearng_daily'
    AND l.started_at >= days.day
    AND l.started_at < days.day + INTERVAL 1 DAY
)
ORDER BY days.day;
```

## 3. 보존 정책

삭제하지 않습니다. 등록된 스케줄이 하루 10건 미만이라 연간 1만 행 규모이며,
인덱스 `(schedule_name, started_at)` 로 조회가 충분합니다.
