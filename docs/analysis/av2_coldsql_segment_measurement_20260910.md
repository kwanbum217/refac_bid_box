# 콜드 SQL 90초의 구간 귀속 실측

> 측정일: 2026-09-10
>
> 상태: 원인 확정
>
> 대상: `retrieve_structured_data`(`src/rag/structured_data.py`) 의 live 집계 경로
>
> 방법: AU2 에서 추가한 구간 계측(`LATENCY_SEGMENT_LOGGING`)을 켜고
> `scripts/benchmark_rag_segments.py --item-ids q03,q08,q25,q31 --repetitions 3` 실행
>
> 원시 데이터: `data/benchmarks/rag_segments_coldsql_r20_20260910.json`

---

## 1. 결론

**콜드 SQL 90초는 대기가 아니라 실제 SQL 실행입니다.** 그리고 그 절반 가까이가
**손상 문자 탐침(`corrupted_probe`)** 입니다.

| 확정 사항 | 값 | 의미 |
| --- | --- | --- |
| `cursor_ms / sql_ms` | **99.9%** | 커서 실행이 전부다 |
| `residual_ms` | **85~126ms** | connection checkout 대기와 파이썬 비용은 0.1% 미만 |
| `corrupted_probe_ms` | 전체의 **36~38%** | 단일 최대 항목 |

**connection pool 대기 가설과 파이썬 부수 비용 가설은 기각됩니다.** 12만 ms 중
잔여가 92ms 입니다. 남은 것은 SQL 자체뿐입니다.

---

## 2. 구간 귀속 (최악 트레이스, `sql_ms` 113,300ms)

| 구간 | ms | 비중 | 비고 |
| --- | ---: | ---: | --- |
| `top_rows_2` (기관별) | 43,852.8 | 38.7% | 최상위 |
| `top_rows_3` (공고명별) | 42,613.2 | 37.6% | 최상위 |
| `cached_aggregate_2` | 22,070.1 | 19.5% | 최상위 |
| `cached_aggregate_1` | 2,466.7 | 2.2% | 최상위 |
| `top_rows_1` (낙찰자별) | 2,276.5 | 2.0% | 최상위 |
| `cache_lookup_ms` | 6.5 | 0.0% | 최상위 |
| `result_assembly_ms` | 0.1 | 0.0% | 최상위 |
| **소계** | **113,285.9** | **100%** | `cursor_ms` 113,208 과 일치 |
| `corrupted_probe_ms` | 42,990.3 | 37.9% | **중첩**. `top_rows_2`·`top_rows_3` 안에 포함 |

**`corrupted_probe_ms` 를 위 소계에 더하지 마십시오.** `_top_rows`(505행)가
`@_measure_call("top_rows")` 로 감싸여 있고 탐침은 그 함수 **안에서**(553-569행)
따로 기록됩니다. 즉 `top_rows_2 + top_rows_3` 의 86,466ms 가운데 **42,990ms 가
탐침**이고 나머지 43,476ms 가 집계 본체입니다.

### 2.1 4회 반복 재현성

| 트레이스 | `sql_ms` | `cursor_ms` 비중 | `residual_ms` | `corrupted_probe` 비중 |
| --- | ---: | ---: | ---: | ---: |
| 1 | 113,300 | 99.9% | 92.2 | 37.9% |
| 2 | 111,998 | 99.9% | 91.9 | 36.7% |
| 3 | 91,883 | 99.9% | 125.7 | 35.8% |
| 4 | 75,564 | 99.9% | 85.2 | 36.5% |

**네 트레이스 모두 같은 구조입니다.** 커서 실행 99.9%, 잔여 0.1% 미만, 탐침
36~38%. 값은 흔들려도 구성비는 흔들리지 않습니다.

웜 회차는 `sql_ms` 23ms 이며 `cursor_count` 가 1 입니다(콜드는 11~12).
`cached_aggregate` 와 `top_rows` 가 전부 Redis 캐시에 적중해 SQL 이 한 번만 나갑니다.

---

## 3. 왜 탐침이 느린가

탐침은 세 곳에서 같은 형태로 만들어집니다(`structured_data.py` 852행, 875행, 897행).

```python
corrupted_probe=select(BidAnnouncement.id).where(
    BidAnnouncement.dminstt_nm.contains(REPLACEMENT_CHAR), *announcement_conditions
)
```

`contains` 는 **선행 와일드카드** `LIKE '%<U+FFFD>%'` 로 번역됩니다. 인덱스를 쓸 수
없습니다. `.limit(1)` 이 붙지만(566행) **손상 행이 없으면 조기 종료가 일어나지
않아 조건에 걸린 집합을 끝까지 훑습니다.** 손상 행이 없는 정상 데이터일수록 느립니다.

탐침의 용도는 `dropped` 판정 하나입니다. 결과 값이 아니라 **provenance 표시**에만
쓰입니다. 40초를 쓰는 대가로 얻는 것이 그것입니다.

**이 문서는 원인 확정까지이며 수정을 제안하지 않습니다.** 개선안은 별도 Task 에서
정하십시오. 다만 선택지를 고를 때 아래를 전제로 삼으십시오.

- 탐침을 없애면 `dropped` 표시가 사라집니다. 그것이 허용되는지가 먼저입니다.
- `.limit(1)` 은 이미 있습니다. 조기 종료가 안 되는 것은 데이터가 깨끗하기 때문입니다.
- 선행 와일드카드는 일반 인덱스로 해결되지 않습니다.

---

## 4. 뒤집힌 기존 가설

| 가설 | 출처 | 이번 실측 |
| --- | --- | --- |
| 이벤트 루프 블로킹 | AT2 에서 이미 기각 | 유지. 기각 |
| connection checkout 대기 | AT2 잔여 가설 | **기각**. 잔여 92ms |
| 파이썬 조립·직렬화 | AT2 잔여 가설 | **기각**. `result_assembly_ms` 0.1ms |
| 다중 SQL 누적 | AT2 잔여 가설 | **부분 성립**. 다만 균등 누적이 아니라 두 항목 집중 |
| `corrupted_probe` 기여 | AT2 가 "작으면 후보에서 내린다"고 적음 | **최대 단일 항목**. 내리면 안 됐다 |

AT2 의 실험 설계는 탐침을 낮은 우선순위 후보로 뒀습니다. 실측은 반대였습니다.

---

## 5. 남은 것

- 탐침 제거 또는 대체의 가부 판정. `dropped` provenance 를 포기할 수 있는지가 선결입니다.
- `cached_aggregate_2` 22초와 집계 본체 43초의 내부 구성. 이번 계측은 호출 단위까지만 봅니다.
- 웜 전환 조건. `cursor_count` 가 11에서 1로 떨어지는 경계를 확인하지 않았습니다.
