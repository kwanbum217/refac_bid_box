> 문서: compare-stats 구간 계측 구조와 하네스 사용 절차
> 작성일: 2026-09-11
> 상태: 계측 도구만 작성함. 측정을 실행하지 않았으므로 새 성능 수치를 주장하지 않음

---

## 1. 목적

GET /api/v1/bids/compare-stats 의 캐시 미적중 종단 wall time 이 어느 쿼리에서
오는지 귀속할 도구가 없어, 쿼리별 계측과 전용 측정 하네스를 둡니다. 최적화는
하지 않습니다.

---

## 2. 계측 구조

| 구성 | 파일 | 역할 |
| --- | --- | --- |
| 공용 레코더 | `src/app/core/latency_segments.py` | contextvars 기반 요청별 레코더, 명명 구간 기록, SQLAlchemy 커서 리스너 |
| 계측 대상 | `src/app/services/dashboard.py` | `get_compare_stats_data` 안에서 아홉 구간을 감쌈 |
| 측정 하네스 | `scripts/benchmark_compare_stats.py` | 회차별 wall time 과 로그 줄 짝짓기, 결과 JSON 작성 |
| 고정 테스트 | `tests/test_compare_stats_segments.py` | 플래그 개폐, 구간 이름, 캐시 적중 표시, 짝짓기 경계 고정 |

### 2.1 구간 이름

`announcement_summary`, `result_summary`, `cache_lookup`, `matched_count`,
`announce_by_month`, `result_by_month`, `agency_announce_top10`, `cache_store`,
`result_assembly` 다. 각 구간은 밀리초 실수이며 소수 둘째 자리로 반올림합니다.
여기에 `cursor_ms`, `cursor_count`, `total_ms`, `residual_ms` 를 함께 남기며,
`residual_ms` 는 `total_ms` 에서 `cursor_ms` 를 뺀 값입니다.

### 2.2 로그 줄 형식

```text
compare_stats_segments={"cache_hit": false, "cursor_count": 7, "cursor_ms": 1234.56, "residual_ms": 12.34, "segments": {...}, "total_ms": 1246.90}
```

JSON 은 한 줄로 직렬화합니다. 캐시 적중이라 쿼리를 한 건도 돌지 않은 회차도
반드시 그 줄을 남기고 `cache_hit` 을 참으로 표시합니다.

### 2.3 안전 장치

- 계측은 `settings.LATENCY_SEGMENT_LOGGING` 뒤에 있으며 기본값은 거짓입니다.
  꺼져 있으면 레코더가 아무 일도 하지 않고 로그도 남기지 않습니다.
- 계측 내부 예외는 요청을 실패시키지 않고 경고만 남긴 뒤 삼킵니다.
- 반환 데이터의 키와 값, 캐시 키 산출, TTL 판정은 계측 여부와 무관하게
  동일합니다.
- `src/rag` 아래 파일은 수정하지 않았습니다. RAG 경로의 정본과 기준선을
  오염시키지 않기 위해 레코더를 별도 파일로 두었으며, 중복은 의도된 것입니다.

---

## 3. 하네스 사용 절차

다음 측정자가 그대로 따를 수 있는 명령 형태입니다.

### 3.1 계측 켜기

```sh
# .env 에 LATENCY_SEGMENT_LOGGING=true 를 넣고 app 을 재기동합니다.
# 측정 후에는 원래 값으로 되돌립니다.
docker logs refac_bid_box-app-1 2>&1 | grep 'compare_stats_segments=' | tail -3
```

### 3.2 측정 실행

```sh
# 기본값은 캐시를 지우지 않습니다. 캐시 적중과 미적중을 구분해 읽으십시오.
uv run python scripts/benchmark_compare_stats.py --rounds 5 --output /tmp/compare_stats_segments.json

# 캐시 미적중 회차를 강제로 만들 때만 --evict-cache 를 붙입니다.
uv run python scripts/benchmark_compare_stats.py --rounds 5 --evict-cache --output /tmp/compare_stats_segments.json
```

주요 인자는 `--base-url`, `--rounds`, `--timeout-sec`,
`--target-container`, `--redis-container`, `--cache-key-pattern`,
`--evict-cache`, `--output` 입니다.

### 3.3 결과 JSON 읽기

결과 JSON 은 회차별 원값(`rounds`), 구간별 집계(`summary.by_segment`의 P50,
최소, 최대, 합계), `git_sha`, 측정 시각(`measured_at`), 캐시 적중 여부
(`cache_hit`, `cache_hits`, `cache_misses`)를 담습니다.

### 3.4 짝짓기 규칙

각 회차 호출 직전의 로그 위치를 기억하고 그 이후에 새로 나타난 줄만 후보로
삼습니다. 후보가 없거나 둘 이상이면 그 회차를 유효한 표본으로 세지 않고
이유(`no_candidate`, `ambiguous`, `parse_error`)와 함께 결과 JSON 에
기록합니다. 조용히 버리거나 추측으로 채우지 않습니다.

### 3.5 금지 사항

- 이 하네스는 Redis 키 삭제와 컨테이너 로그 읽기를 하므로 읽기 전용이
  아닙니다. `scripts/orca_auto_approve.py` 의 자동 승인 화이트리스트에
  등록하지 마십시오.
- 벤치마크 실행과 DB 접근은 다른 워커의 타이밍 측정을 오염시킬 수 있으므로,
  코디네이터 지시 없이 이 문서의 명령을 실행하지 마십시오.

---

## 4. 검증 명령

```sh
uv run pytest tests/test_compare_stats_segments.py tests/test_dashboard_compare_stats_exists.py tests/test_dashboard_stats_parity.py -q
uv run pytest tests/ -q -m 'not data_assets'
uv run mypy src
python3 scripts/validate_agent_rules.py --quiet
```

---

## 5. 측정 여부 명시

본 작업에서는 측정을 실제로 실행하지 않았습니다. 따라서 이 문서에는 새 성능
수치가 없으며, 배경 수치가 필요하면 Task 캡슐의 ground_truth 에 기록된
코디네이터 확인 사실을 따르십시오.
