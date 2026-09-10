# 콜드 SQL 효과 크기 판정용 측정 설계

> 작성일: 2026-09-11
>
> 상태: 측정 절차 정본
>
> 범위: 측정 도구와 판정 기준만 다룬다. 최적화 제안은 포함하지 않는다.
>
> 관련 산출물: scripts/benchmark_rag_segments.py, scripts/compare_rag_segments.py, tests/test_benchmark_segment_capture.py
>
> 배경 근거: docs/analysis/av2_coldsql_segment_measurement_20260910.md, docs/analysis/aw2_probe_removal_effect_20260911.md

---

## 1. 전제

콜드 SQL 측정의 절대 시간은 회차간 산포가 크다. 같은 쿼리가 회차마다 크게
흔들리므로 1회 실행 두 개를 빼는 방식으로는 효과 크기를 주장할 수 없다.
이 판단을 뒤집지 않는다. 근거는 docs/analysis/aw2_probe_removal_effect_20260911.md 3장이다.

잡음을 이기는 지표는 절대 시간이 아니라 구조 지표와 구성비다. 탐침 제거
전후에 cursor_count 감소와 corrupted_probe_ms 소멸은 흔들리지 않았고,
커서 실행 구성비도 흔들리지 않았다. 근거는 같은 문서 2장과
docs/analysis/av2_coldsql_segment_measurement_20260910.md 2.1절이다.

따라서 이 설계의 판정은 구조를 먼저 보고, 구성비를 참고로 보며, 절대
시간은 산포 안에 들어가는지부터 묻는다.

---

## 2. 판정 기준

비교 실행기 scripts/compare_rag_segments.py 가 두 결과 JSON 을 받아 항목을
세 등급으로 분류해 보고한다.

### 2.1 구조 차이는 확정으로 본다

다음 둘 중 하나라도 해당하면 확정으로 보고한다.

- 어떤 구간이 한쪽에만 있고 다른 쪽에 아예 없는 경우. 구간 소멸과 구간
  생성이 여기에 해당한다. 예시로 corrupted_probe_ms 가 사라진 경우가 있다.
- cursor_count 처럼 정수 카운터의 관측 범위가 겹치지 않는 경우.

구조 판정은 타이밍 잡음과 무관하므로 표본이 적어도 확정으로 본다. 다만
한쪽에 정형 트레이스가 아예 없으면 자료 부족으로 판정 불가로 보고한다.

### 2.2 구성비 차이는 참고로 본다

cursor_ms 평균 대비 각 구간 평균의 비율을 양쪽에 대해 나란히 보고한다.
우열 판정의 근거로 쓰지 않고 어디가 달라졌는지 읽는 용도로만 쓴다.

### 2.3 절대 시간 차이는 산포 대비로만 본다

각 지표(공유 구간, cursor_ms, total_ms, residual_ms)마다 다음 순서로 판정한다.

1. 조건별 트레이스 수가 하한(기본값 2건)에 못 미치면 판정 불가로 보고한다.
   구별 불가와 같은 문구로 뭉개지 않는다.
2. 두 조건의 최소값과 최대값 범위가 겹치면 구별 불가로 판정한다.
3. 범위가 겹치지 않아도 평균 차이가 두 조건 산포의 합 안에 들어가면
   구별 불가로 판정한다.
4. 범위가 겹치지 않고 평균 차이가 두 조건 산포의 합을 넘을 때만
   산포 초과(참고)로 보고한다. 표본이 적으므로 확정하지 않고 참고로만 둔다.

산포 안에 드는 시간 차이를 우열 판정으로 적지 않는다. 정규성 가정을
요구하는 통계 검정은 쓰지 않는다. 회차 수가 4 내외로 적기 때문이다.
판정 근거(건수, 범위, 평균차, 산포 합)는 사람이 읽을 수 있게 출력한다.

---

## 3. 조건 동등화 규약

2026-09-11 실패 비교는 조건이 달랐다. 다음 셋을 양쪽 측정에 동일하게
맞추지 않으면 비교를 시작하지 않는다.

1. 스냅샷 재구축 금지 구간. 두 측정 사이에 ranking 스냅샷 재구축을 돌리지
   않는다. 재구축은 마커 분포와 버퍼풀 상태를 양쪽에서 다르게 만든다.
   재구축이 필요하면 양쪽 측정 전에 미리 끝내고 그 뒤로는 건드리지 않는다.
2. Redis 초기화 대칭. 캐시를 비울 거면 양쪽 측정 직전에 같은 방식으로
   비운다. 한쪽에만 적용하지 않는다.
3. 반복 회차 확보. 각 조건은 1회 실행으로 끝내지 않는다. 산포 추정에 필요한
   최소 2회 이상을 양쪽에 동일하게 적용하고, 기존 측정 관행에 맞춰 4회
   내외를 권장한다. 회차가 부족하면 비교기는 판정 불가를 내린다.

---

## 4. 측정 절차

다음 순서대로 실행한다. 벤치마크 실행과 결과 비교를 같은 조건에서 한다.

1. 적용 전 측정을 저장한다.

   ```sh
   uv run python scripts/benchmark_rag_segments.py \
     --item-ids q03,q08,q25,q31 --repetitions 3 \
     --expected-llm-model gemma4:e4b \
     --output data/benchmarks/rag_segments_coldsql_before.json
   ```

2. 적용 후 측정을 같은 인자로 저장한다. 3장의 세 항목(재구축 없음, Redis
   대칭, 동일 반복)을 먼저 확인한다.

   ```sh
   uv run python scripts/benchmark_rag_segments.py \
     --item-ids q03,q08,q25,q31 --repetitions 3 \
     --expected-llm-model gemma4:e4b \
     --output data/benchmarks/rag_segments_coldsql_after.json
   ```

3. 비교 판정을 실행한다. 기본 범위는 cold 다.

   ```sh
   uv run python scripts/compare_rag_segments.py \
     data/benchmarks/rag_segments_coldsql_before.json \
     data/benchmarks/rag_segments_coldsql_after.json --scope cold
   ```

4. 출력을 위에서 아래로 읽는다. 구조 확정 항목이 있으면 그 줄만 확정
   사실로 인용한다. 구성비는 참고로 읽는다. 절대 시간 항목이 구별 불가면
   그 지표로는 우열을 주장하지 않는다. 판정 불가가 나오면 표본을 늘려
   1단계부터 다시 측정한다.

---

## 5. 산출물 읽기

결과 JSON 에는 기존 키를 그대로 두고 다음 키가 추가된다.

- structured_sql_traces. 트레이스별 원값 목록이다. trace_id, segments,
  cursor_ms, cursor_count, total_ms, residual_ms 를 담고 cold와 warm
  구분(is_cold)과 문항(item_id)도 함께 담는다.
- structured_sql_summary. all, cold, warm 별 구간 집계다. 구간별 건수와
  최소값, 최대값, 평균, cursor_count 분포, 구성비 참고값을 담는다.

corrupted_probe_ms 는 top_rows_N 안에 중첩된 부분합이다. 최상위 구간
소계에 더하면 안 된다. 집계는 구간별로만 하고 합산하지 않는다. 구성비의
합이 100%를 넘을 수 있는 것은 이 중첩 때문이다.

---

## 6. 금지 사항

- 산포 안에 드는 시간 차이를 우열 판정으로 적지 않는다.
- 판정 불가(표본 부족)와 구별 불가(산포 안 차이)를 같은 문구로 뭉개지 않는다.
- 1회 실행 두 개의 차감으로 효과 크기를 주장하지 않는다.
- corrupted_probe_ms 를 최상위 구간 소계에 더하지 않는다.
- 이 문서에 성능 수치를 새로 적지 않는다. 수치가 필요하면
  docs/analysis/aw2_probe_removal_effect_20260911.md 와
  docs/analysis/av2_coldsql_segment_measurement_20260910.md 를 가리킨다.
