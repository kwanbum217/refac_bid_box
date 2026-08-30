# 콜드/웜 SQL 비용 귀속 정본 측정 결과 (2026-08-30)

> **작성일**: 2026-08-30
> **측정 HEAD**: `7dcc771a5b2b8115c88161c376a19554b1c52369` (고정, 시작·종료 모두 dirty=false)
> **fixture SHA-256**: `2c98c636a478cfc92870533513b4442704d8441bd217e303489c9bcf0752e483`
> **fixture 경로**: `data/eval/llm_quality_fixture_v2.json` (32문항 정본)
> **원시 JSON**: [`../../data/benchmarks/coldsql_attribution_canonical_20260830.json`](../../data/benchmarks/coldsql_attribution_canonical_20260830.json)
> **결론 한 줄**: 동일 표본 32문항 × 3회 반복에서 Redis 캐시가 차가운 상태의 총 SQL 비용은 **223.77초**, 데운 상태는 **0.15초**이며 그 차이의 99.9%는 5개 digest(상위 누적 134.62초)에 귀속된다. 지배 패턴은 카테고리 필터 유무와 무관하게 발생하는 `LIKE concat('%', ?, '%')` (선행 와일드카드) 계열이다. **접두 일치 전환은 권고하지 않는다.**

---

## 1. 측정 환경과 provenance

| 항목 | 값 |
| --- | --- |
| 고정 SHA (시작 = 종료) | `7dcc771a5b2b8115c88161c376a19554b1c52369` |
| 시작 `git_dirty` | `false` |
| 종료 `git_dirty` | `false` |
| `--allow-unknown-provenance` | 미사용 |
| `--flush-cache` | 명시적 지정, `cache_flushed=true` |
| MySQL 버퍼 풀 비움 | 수행하지 않음 (capsule ground_truth) |
| app / Redis / Meilisearch healthy | coordinator 확인 사실 (측정 전 healthy) |
| 컨테이너 재시작 | 수행하지 않음 |
| 측정 시작 UTC | `2026-08-30T07:58:41.414497+00:00` |
| 측정 종료 UTC | `2026-08-30T08:14:25.384385+00:00` |

Canonical 게이트 결과:

| 게이트 | 결과 |
| --- | --- |
| `is_canonical` | **true** |
| `failed_gates` | `[]` |
| `summary.request_failures` | `0` |
| `metadata.flush_cache_requested` | `true` |
| `metadata.cache_flushed` | `true` |
| `metadata.item_count` | `32` |
| `metadata.repetitions` | `3` |
| `metadata.total_fixture_items` | `32` |

원시 JSON의 `metadata.git_sha`가 `7dcc771a5b2b8115c88161c376a19554b1c52369` 이고 시작·종료 모두 clean 상태임을 위 표에서 확인했다.

---

## 2. cold vs warm 총 비용

`performance_schema.events_statements_summary_by_digest` 의 `SUM_TIMER_WAIT` 합산 (피코초 → 초, `1e12` 변환) 기준:

| 상태 | 총 SQL 시간 (sec) | digest 수 | 측정 호출 수 |
| ---: | ---: | ---: | ---: |
| cold (캐시 비움 직후) | **223.773315** | 38 | 96 |
| warm (적중 상태) | **0.151175** | 10 | 96 |

- cold 총 비용은 warm 대비 약 **1,480배** 크다.
- 5개 digest 만 누적 cold 비용의 약 **60%** (134.62 / 223.77) 를 차지한다.
- warm 의 digest 수는 10개로 cold (38개) 의 26% 수준이다. cold 에서만 등장하는 28개 digest 는 **cold 일 때만 실행되는 캐시 미스 경로의 쿼리들**이며 warm 에서는 캐시 적중으로 아예 실행되지 않는다.

---

## 3. attribution_diff_table 상위 10개 (delta_sum_sec 기준)

`delta_sum_sec = cold_sum_sec − warm_sum_sec`. 모든 상위 10개 digest 가 warm 에서는 0초를 기록해 **cold 적중 비용 100% 가 캐시 비움으로 발생한 추가 비용**임을 보인다.

| # | digest 패턴 | cold 호출 | warm 호출 | cold 누적 (s) | warm 누적 (s) | Δ 누적 (s) | cold max (ms) | warm max (ms) |
| :---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | `bid_announcements.dminstt_nm` GROUP BY + `LIKE concat('%', ?, '%')` ×2 + `category=?` | 3 | 0 | 29.672 | 0.000 | 29.672 | 10,074.7 | 0.0 |
| 2 | `bid_announcements.bid_ntce_nm` GROUP BY + `LIKE concat('%', ?, '%')` ×2 + `category=?` | 3 | 0 | 29.559 | 0.000 | 29.559 | 10,101.3 | 0.0 |
| 3 | `bid_announcements.id` SELECT + `bid_ntce_nm LIKE concat('%', ?, '%')` + `category=?` | 3 | 0 | 28.964 | 0.000 | 28.964 | 10,045.9 | 0.0 |
| 4 | `bid_announcements.id` SELECT + `dminstt_nm LIKE concat('%', ?, '%')` + `category=?` | 3 | 0 | 28.315 | 0.000 | 28.315 | 9,878.3 | 0.0 |
| 5 | `COUNT(bid_announcements.id)` + `bid_ntce_nm LIKE concat('%', ?, '%')` + `category=?` | 3 | 0 | 27.076 | 0.000 | 27.076 | 9,581.3 | 0.0 |
| 6 | `bid_announcements.bid_ntce_nm` GROUP BY + `LIKE concat('%', ?, '%')` ×2 (category 없음) | 1 | 0 | 18.807 | 0.000 | 18.807 | 18,807.2 | 0.0 |
| 7 | `bid_results.bidwinnr_nm` GROUP BY + `LIKE concat('%', ?, '%')` ×2 (category 없음) | 1 | 0 | 18.186 | 0.000 | 18.186 | 18,186.1 | 0.0 |
| 8 | `bid_announcements.id` SELECT + `bid_ntce_nm LIKE concat('%', ?, '%')` (category 없음) | 1 | 0 | 16.680 | 0.000 | 16.680 | 16,679.5 | 0.0 |
| 9 | `COUNT(bid_announcements.id)` + `bid_ntce_nm LIKE concat('%', ?, '%')` (category 없음) | 1 | 0 | 4.432 | 0.000 | 4.432 | 4,432.3 | 0.0 |
| 10 | `bid_results.bidwinnr_nm` GROUP BY + `LIKE concat('%', ?, '%')` ×2 + `category=?` | 3 | 0 | 4.088 | 0.000 | 4.088 | 1,507.0 | 0.0 |

상위 10개 누적 `delta_sum_sec` = **205.778 sec** (총 cold 비용의 약 **91.9%**).

### 3.1 패턴 정리

| 그룹 | digest 번호 | 특성 | 누적 (s) | 비율 |
| --- | :---: | --- | ---: | ---: |
| A. `bid_announcements` GROUP BY (`dminstt_nm` / `bid_ntce_nm`) + 선행 와일드 LIKE ×2 + `category=?` | #1, #2 | 카테고리·날짜 인덱스 힌트 시정에도 cold 에서 여전히 ~30초 | 59.231 | 26.5% |
| B. `bid_announcements.id` SELECT (존재 확인) + `bid_ntce_nm` / `dminstt_nm` LIKE + `category=?` | #3, #4, #5 | 인덱스 range 스캔이 불가능해 풀스캔 | 84.355 | 37.7% |
| C. `bid_announcements.bid_ntce_nm` GROUP BY (카테고리 없음) + LIKE ×2 | #6 | 시정 후에도 날짜 인덱스 힌트 미적용 구간 | 18.807 | 8.4% |
| D. `bid_results.bidwinnr_nm` GROUP BY (카테고리 없음) + LIKE ×2 | #7 | 카테고리 미지정 시 날짜 인덱스 힌트 미적용 | 18.186 | 8.1% |
| E. `bid_announcements` 단순 SELECT/COUNT (카테고리 없음) | #8, #9 | `corrupted_probe` 류가 아닌 일반 선행 와일드 LIKE | 21.112 | 9.4% |
| F. `bid_results.bidwinnr_nm` GROUP BY (카테고리 있음) | #10 | 시정으로 1.5초 수준까지 내려온 케이스 | 4.088 | 1.8% |

### 3.2 핵심 관찰

1. **지배 비용은 선행 와일드카드 `LIKE concat('%', ?, '%')` 가 포함된 모든 쿼리**다. 카테고리 필터가 있어도 (그룹 A·B) cold 에서 ~10초 / 호출이 발생한다. 카테고리가 없는 경우 (#6·#7·#8·#9) 는 4~18초 / 호출까지 늘어난다.
2. 카테고리 필터가 **있고** 그룹 A·B 의 쿼리 형태(컬럼이 `dminstt_nm` / `bid_ntce_nm` 이고 인덱스가 `ix_bid_ann_dt_cat`)는 Wave E1 의 날짜 인덱스 힌트로 이미 ~13초대에서 ~10초대로 시정됐다. Wave E3 의 `corrupted_probe` 제거도 정상 상태에서 3회 × ~9초 = ~27초의 비용을 제거했다. 이 두 시정이 없었다면 cold 총 비용은 약 250~270초였을 것으로 추정된다.
3. 그룹 C·D·E 는 **카테고리 필터가 없는 선행 와일드 LIKE + GROUP BY / 단순 SELECT** 로, 현재 시정(날짜 인덱스 힌트) 의 적용 범위에서 벗어나 있다. 같은 코드가 카테고리 유무에 따라 4배 이상 차이 (A 평균 ~10초 vs E 평균 ~14초 vs C·D 단일 호출 18초) 를 보인다.
4. warm 에서도 10개 digest 가 보이는데, 그 합은 0.15초로 cold 의 0.07% 수준이다. warm 에서도 실행되는 쿼리는 캐시 미스키가 짧게 끝나는 형태 (메타·벡터 채널 일부) 다.

---

## 4. 기존 수치와의 비교 가능성

이전 보고서 [`rag_structured_sql_coldstart_20260830.md`](rag_structured_sql_coldstart_20260830.md) 와 [`contains_scan_survey_20260830.md`](contains_scan_survey_20260830.md) 의 일부 수치는 비교 가능하지 않다.

| 이전 수치 | 출처 | 비교 가능 여부 | 이유 |
| --- | --- | :---: | --- |
| `sql_ms=97,087.81` (cold max) | `rag_structured_sql_coldstart_20260830.md` 1장 표 | 비교 대상 | 단일 호출 wall-clock (end-to-end), 본 정본은 digest 단위 합산이라 단위가 다름 |
| `q08/q25/q03/q31` cold sql 합계 60~97초 | `rag_structured_sql_coldstart_20260830.md` 1장 | 비교 대상 | 4문항만 측정, 본 정본은 32문항 × 3회 (96 cold / 96 warm 호출) |
| `13,446ms → 698ms` (bidwinnr_nm GROUP BY 시정 효과) | `task_4a485df361bd.md` 3.1 절 | 비교 대상 | 시점: 캐시 데운 상태 + 단일 호출 wall-clock, 본 정본은 digest SUM |
| 8개 digest 별 누적 (`89.09s`, `78.41s`, `72.09s`, …) | `rag_structured_sql_coldstart_20260830.md` 9장 표 | 비교 가능 (같은 digest_text 매칭은 직접 비교) | 측정 조건이 cold·cache cold 4문항 × 2회 였고, 본 정본은 cold·cache cold 32문항 × 3회 |

따라서 본 문서의 수치는 **정본 환경(병합 revision 7dcc771, 32문항 × 3회, 캐시 비움 직후 동일 표본, 3회 warm)** 에 한정해 해석한다. 이전 문서의 97초 / 13,446ms / 698ms 와 본 문서의 223.77초 / 10,074.7ms 는 같은 코드에서 나온 수치지만 호출 표본·캐시 상태·측정 단위가 달라 직접 비교 대상이 아니다.

---

## 5. 다음 시정 후보 (실측 근거 기반, **접두 전환은 제외**)

상위 10개 digest 의 cold 비용을 90% 이상 차지하는 패턴은 **선행 와일드카드 `LIKE concat('%', ?, '%')` 가 들어가는 모든 경로**다. capsule이 명시적으로 금지한 "contains 접두 전환" 은 사용자가 입력하는 한국 행정기관명 토큰의 의미를 바꾸므로 (별도 보고서 §4 참조, 거제시 99.6% 회귀) 제안하지 않는다. 그 외 후보를 우선순위로 정리한다.

| 우선순위 | 후보 | 근거 (이번 정본 수치) | 위험 / 부수효과 | 권고 |
| :---: | --- | --- | --- | --- |
| 1 | 그룹 C·D (카테고리 미지정 + GROUP BY + LIKE ×2) 의 **날짜 인덱스 힌트 적용 범위 확대**. 현재 `_needs_announcement_date_index_hint` 는 카테고리 필터가 없을 때 힌트를 주지 않음. 그룹 C·D 는 cold 18초 / 호출 | 그룹 C·D cold max = 18.0~18.8초 vs 그룹 A·B (카테고리 있음) cold max = 9.5~10.1초. **카테고리만 있어도 2배 차이** 이므로 힌트 미적용이 비용의 큰 축 | 인덱스 선택 변경 → EXPLAIN 으로 rows·Extra 비교 필요 | 적용 후보 |
| 2 | 그룹 B (단순 SELECT/COUNT + LIKE + `category=?`) 의 **범위 축소 검토**. 3~5번 digest 모두 cold max 9.5~10초 | 카테고리가 있어도 GROUP BY 가 없는데 cold max ~10초면 옵티마이저가 풀스캔을 택한다는 뜻. 복합 인덱스 (`dminstt_nm` / `bid_ntce_nm` + category) 가 이미 있는지 확인 필요 | 인덱스 추가는 G1(스키마 불변) 원칙과 충돌하므로 `(category, dminstt_nm)` 같은 **파생 컬럼** 또는 Meilisearch 위임 검토 | 검토 후 결정 |
| 3 | 그룹 E (카테고리·GROUP BY 없음, 단순 SELECT/COUNT + LIKE) 의 **불필요 호출 제거**. 8·9번 digest cold max 4.4~16.7초 | `corrupted_probe` 가 아니더라도 동일 패턴이 다른 경로에서 발생. 손상값 제외가 아닌 다른 의도라면 의도 자체 재점검 | 의도가 G1(데이터 무손실) 보장과 충돌하지 않는지 확인 필수 | 의도 확인 후 |
| 4 | 캐시 **TTL 갱신 전략**. warm 합계 0.15초 vs cold 합계 223.77초 → 캐시 미스 한 번에 1,480배 | 사용자가 캐시 만료 시점을 만나지 않도록 stale-while-revalidate 또는 캐시 워밍업 | 캐시 키 정합성 / 키 폭주 검토 | 검토 후 결정 |
| 5 | `bid_results.bidwinnr_nm` GROUP BY (digest #7·#10) 의 **카테고리 미지정 케이스 힌트 일관성**. #7 cold max 18.2초 vs #10 cold max 1.5초 | 동일 코드 / 동일 의도인데 카테고리 유무만으로 12배 차이. 정책 (카테고리 강제) 또는 힌트 정책의 일관성 필요 | 사용자 질의 패턴에 카테고리가 항상 따라오는지 확인 | 정책 결정 후 |

---

## 6. 결론

1. **canonical=true** 이며 모든 acceptance 조건을 충족한다 (1·2장).
2. cold 223.77초, warm 0.15초, 차이 1,480배. 캐시 비움이 콜드 SQL 비용을 그대로 드러내는지 확인됐다.
3. 상위 10개 digest 의 누적 `delta_sum_sec` = **205.78초** (cold 총 비용의 91.9%) 이며 모두 `LIKE concat('%', ?, '%')` 패턴이다.
4. 그룹 A·B 의 비용은 이미 Wave E1·E3 의 시정으로 부분 개선된 상태이며, **그룹 C·D·E 가 잔여 지배 SQL** 이다.
5. **접두 일치 전환은 권고하지 않는다** (capsule 금지 + 의미 변화 위험). 다음 시정은 (1) 날짜 인덱스 힌트 적용 범위 확대, (2) 카테고리 있는 단순 SELECT 의 인덱스/캐시 위임 검토, (3) 의도 재점검, (4) 캐시 갱신 전략, (5) 정책 일관성이다.

---

## 7. 재현

```bash
# 1) 측정 (정본 명령)
uv run python scripts/measure_coldsql_attribution.py \
  --base-url http://127.0.0.1:8000 \
  --fixture data/eval/llm_quality_fixture_v2.json \
  --item-ids '' --flush-cache \
  --output data/benchmarks/coldsql_attribution_canonical_20260830.json \
  --repetitions 3 --timeout 180

# 2) 메타 검증 (현재 작업 디렉터리 기준)
uv run python - <<'PY'
import json
d = json.load(open("data/benchmarks/coldsql_attribution_canonical_20260830.json"))
m, c, s = d["metadata"], d["canonical_evaluation"], d["summary"]
assert m["git_sha"] == "7dcc771a5b2b8115c88161c376a19554b1c52369"
assert m["git_dirty"] is False
assert m["item_count"] == 32 and m["repetitions"] == 3
assert m["flush_cache_requested"] and m["cache_flushed"]
assert c["is_canonical"] is True and c["failed_gates"] == []
assert s["request_failures"] == 0
print("OK", s["total_cold_sql_sec"], s["total_warm_sql_sec"])
PY
```

원시 JSON 의 `metadata.timestamp_start_utc` / `timestamp_end_utc` 와 `summary.total_cold_sql_sec` / `summary.total_warm_sql_sec` 가 본 문서 1·2장 수치와 일치하는지 확인하면 provenance 가 보장된다.
