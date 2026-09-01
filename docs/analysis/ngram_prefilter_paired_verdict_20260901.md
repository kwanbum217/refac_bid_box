# ngram 선행필터 쌍대 판정: 기각 (2026-09-01)

> **작성일**: 2026-09-01
> **동결 HEAD**: `d3cad6c` (양쪽 측정 동일, `git_dirty=false`)
> **규약**: E4 동일. fixture `llm_quality_fixture_v2` 32문항 전량, 3회 반복, `--flush-cache`, 요청 실패 0
> **원시 JSON**: [`coldsql_post_ngram_20260901.json`](../../data/benchmarks/coldsql_post_ngram_20260901.json) (ON),
> [`coldsql_flag_off_20260901.json`](../../data/benchmarks/coldsql_flag_off_20260901.json) (OFF)

---

## 1. 판정

**`NGRAM_PREFILTER_ENABLED` 를 기각합니다.** 같은 HEAD 에서 플래그만 바꾼 쌍대 측정에서
콜드 SQL 총 비용이 줄지 않았고, 오히려 소폭 늘었습니다.

| 지표 | 플래그 OFF | 플래그 ON | 차이 |
| --- | ---: | ---: | ---: |
| cold 총 SQL 소비 | **333.19초** | **339.57초** | **+6.38초 (1.02배)** |
| warm 총 SQL 소비 | 0.148초 | 0.142초 | 사실상 동일 |
| 최대 단일 쿼리 delta | 49.28초 | 49.79초 | +0.51초 |
| 요청 실패 | 0 | 0 | - |

양쪽 모두 `canonical=true`, `failed_gates=[]` 입니다.

**개선이 없으므로 운영 FULLTEXT 인덱스와 선행필터를 유지할 근거가 없습니다.**

---

## 2. MATCH 를 붙이면 그 쿼리가 더 비쌉니다

MATCH 를 포함한 digest 의 delta 합계는 ON 에서 **112.29초**이고 OFF 에는 존재하지 않습니다.
OFF 에서 같은 자리를 차지하는 기관명 집계는 41.89초입니다.

| 순위 | OFF | ON |
| ---: | --- | --- |
| 1 | 49.28초 업체명 집계 | **49.79초 기관명 집계 (MATCH)** |
| 2 | 43.00초 공고 건수 | 41.53초 공고 ID 조회 |
| 3 | **41.89초 기관명 집계** | 41.05초 공고명 집계 |
| 6 | 38.47초 공고 ID 조회 | **32.66초 기관명 집계 (MATCH)** |

즉 선행필터는 기관명 집계 한 경로를 **41.89초에서 105.66초(세 digest 합)로 늘렸고**,
그만큼 다른 경로의 비용이 상대적으로 줄어 총합이 비슷해졌을 뿐입니다.

---

## 3. 왜 probe 예측(19.0배)이 빗나갔는가

EXPLAIN 은 의도대로 나옵니다. 옵티마이저가 `ft_dminstt_nm` 을 골라 `type=fulltext`,
추정 `rows=1` 입니다.

```
type=fulltext  key=ft_dminstt_nm
Extra: Using where; Ft_hints: no_ranking; Using temporary; Using filesort
```

**그런데도 콜드에서 느립니다.** 두 가지가 남기 때문입니다.

1. **`Using temporary; Using filesort` 가 사라지지 않습니다.** `GROUP BY dminstt_nm` +
   `ORDER BY COUNT(*) DESC` 는 후보를 좁혀도 정렬 비용을 그대로 냅니다.
2. **콜드에서는 ngram 인덱스 자체를 디스크에서 읽어 와야 합니다.** `bid_announcements`
   인덱스는 1.4GB 규모이고, "거제시" 같은 흔한 토큰은 posting list 가 방대합니다. 이
   적재 비용이 스캔 절감분을 상쇄하고 초과합니다.

Wave F3 의 19.0배는 **소규모 probe 스키마의 warm 비교**였습니다. 운영 27GB 콜드 경로를
대표하지 못합니다. warm 에서는 양쪽 모두 0.14초로 차이가 없어, probe 가 본 이득은
운영에서 이미 캐시가 처리하고 있던 구간이었습니다.

> **측정 함정**: probe 스키마의 warm 배율을 운영 cold 개선치로 옮겨 적지 마십시오.
> 규모와 캐시 상태가 둘 다 다르면 배율은 이전되지 않습니다.

---

## 4. 함께 드러난 별개 사실: 콜드 총량이 E4 대비 늘었습니다

| 측정 | HEAD | cold 총 SQL |
| --- | --- | ---: |
| E4 (2026-08-30) | `7dcc771` | 223.77초 |
| 이번 OFF | `d3cad6c` | **333.19초** |

**이 차이는 ngram 과 무관합니다.** 플래그 OFF 끼리의 비교이며, 그 사이 Wave E5~K 의
코드 변경과 측정 환경(버퍼풀 상태, 디스크 여유)이 함께 달라졌습니다. 원인 분해는
별도 과업이며 이 문서의 판정 대상이 아닙니다. **G3 컷오버 판정 전에 조사해야 합니다.**

---

## 5. 후속 조치

| 조치 | 상태 |
| --- | --- |
| `NGRAM_PREFILTER_ENABLED=false` | **적용 완료** (기본값이자 현재 운영값) |
| 운영 FULLTEXT 인덱스 3개 제거 | **완료 (2026-09-01 14:45).** 사용자 승인 후 수행 |
| Wave F 권고 기각 기록 | 이 문서 |
| 콜드 총량 증가(4절) 원인 조사 | 미착수 |

제거 대상 인덱스는 다음 셋입니다.

```sql
ALTER TABLE bid_announcements DROP INDEX ft_dminstt_nm;
ALTER TABLE bid_results DROP INDEX ft_result_dminstt_nm;
ALTER TABLE bid_results DROP INDEX ft_bidwinnr_nm;   -- 런북 오기로 생성, 코드가 쓰지 않음
```

### 5.1 제거 실측 (2026-09-01)

**제거는 생성과 달리 즉시 끝났습니다.** 생성은 `bid_announcements` 914초 + `bid_results`
52초였으나, 제거는 세 인덱스 모두 5초 이내입니다. 27GB 재구축이 한 번 더 일어날 것으로
예상했으나 발생하지 않았습니다.

| 조작 | 소요 |
| --- | ---: |
| `bid_results` 인덱스 2개 제거 (한 문장) | 1초 미만 |
| `bid_announcements` 인덱스 제거 | 5초 |

제거 후 확인 결과입니다.

| 항목 | 값 |
| --- | ---: |
| 잔여 FULLTEXT 인덱스 | **0** |
| 잔여 `FTS_*` 숨은 컬럼 | **0** |
| `bid_announcements` 행 수 | **5,490,072** (불변) |
| `bid_results` 행 수 | **3,423,008** (불변) |

행 수가 컷오버 전 정본과 같아 **G1 데이터 무손실이 유지**됩니다. 수집 워커와 API 를 내린
상태에서 수행했고 이후 전 컨테이너를 healthy 로 복구했습니다.

**선행필터 코드 자체는 남겨 둡니다.** 기본값 OFF 이므로 질의 경로를 바꾸지 않고,
집계 경로를 재설계할 때 다시 검토할 근거가 됩니다.
