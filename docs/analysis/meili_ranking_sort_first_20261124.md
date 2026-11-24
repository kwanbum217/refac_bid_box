# Meilisearch bid_records 순위 규칙 sort 우선 배치 (2026-11-24)

> 작성일: 2026-11-24
> 대상: `src/app/services/search_index.py` `MeiliSearchClient.configure_index`
> 측정 스크립트: `scripts/measure_meili_ranking.py`
> 범위: 코드·측정 스크립트·문서. 운영 Meilisearch 설정 적용은 코디네이터가 리뷰 후 수행합니다.

---

## 1. 배경

낙찰 결과 목록의 응답 시간 대부분은 Meilisearch 검색입니다. 2026-11-24 실측에서 목록 요청
시간의 85~98% 가 Meilisearch 검색이었고 MySQL 조회는 9~12ms 였습니다.

| 항목 | 값 |
| --- | --- |
| 색인 | `bid_records` (공고 + 낙찰 결과) |
| 문서 수 | 약 843만 건 |
| 디스크 | 약 23.7GB |
| 엔진 | Meilisearch 1.14.0 |
| 변경 전 rankingRules | `words, typo, proximity, attribute, sort, exactness` (기본값) |

기본 순위 규칙은 `sort` 가 `attribute` 뒤에 있습니다. 정렬 파라미터가 있는 키워드 검색은
키워드에 걸린 후보(검색어에 따라 5만~14만 건) 전부에 `typo`·`proximity`·`attribute` 점수를
계산한 뒤에야 정렬합니다. 엔진이 보고한 `processingTimeMs` 는 다음과 같았습니다.

| 검색어 | 정렬 | 엔진 시간 |
| --- | --- | --- |
| 정보화 | 최신순 | 2,880ms, 7,675ms (재측정 162ms) |
| 유지보수 용역 | 최신순 | 1,886ms |
| 청소 | 최신순 | 682ms |

같은 검색어의 회차 편차가 커서 단일 측정으로 판정하지 않고, 회차별 값과 중앙값·최댓값을
함께 기록합니다.

---

## 2. 변경 내용

`configure_index` 가 보내는 설정 본문에 순위 규칙을 명시합니다. 나머지 설정 값은 바꾸지
않습니다.

```python
RANKING_RULES = ["words", "sort", "typo", "proximity", "attribute", "exactness"]
```

| 순위 | 변경 전 | 변경 후 |
| --- | --- | --- |
| 1 | words | words |
| 2 | typo | **sort** |
| 3 | proximity | typo |
| 4 | attribute | proximity |
| 5 | sort | attribute |
| 6 | exactness | exactness |

의도한 동작은 다음과 같습니다.

- 검색어가 걸린 문서 집합을 `words` 로 먼저 좁히고, 요청에 `sort` 가 있으면 그 기준으로
  정렬한 뒤 나머지 규칙을 적용합니다. 정렬 대상 후보 전부에 근접도 점수를 매기지 않습니다.
- 요청에 `sort` 가 없는 검색은 `sort` 규칙을 건너뛰므로 나머지 규칙의 상대 순서가 기본값과
  같습니다.
- 키워드 관련도보다 최신순이 우선하는 결과 순서 변화는 사용자가 승인했습니다. 공고 목록도
  같은 색인을 쓰므로 함께 바뀝니다.

---

## 3. 측정 방법

### 3.1 실행 위치와 방식

측정 스크립트는 운영 Meilisearch 에 `POST /indexes/bid_records/search` 만 보냅니다. 설정
조회·변경(`PATCH`/`PUT`/`DELETE`, `/settings`)과 문서 쓰기, task 생성은 하지 않습니다.
`MeiliSearchClient` 의 `base_url` 과 인증 헤더를 재사용하므로 별도 키를 인자로 넘기지
않으며, 출력에 키를 포함하지 않습니다.

app 컨테이너 안에서 표준입력으로 실행합니다. 스크립트는 `__file__` 경로에 의존하지 않습니다.

```sh
# 적용 전
docker compose exec -T app python - < scripts/measure_meili_ranking.py \
    > data/benchmarks/meili_ranking_before.json

# 적용 후(같은 검색어 묶음, 같은 회차 수)
docker compose exec -T app python - < scripts/measure_meili_ranking.py \
    > data/benchmarks/meili_ranking_after.json
```

인자 없이 실행하면 JSON 을 표준출력으로 냅니다. `--output`, `--rounds`(기본 3),
`--limit`(기본 20)은 선택입니다.

### 3.2 검색어 묶음

12개 검색어를 고정합니다. 공고·낙찰 두 대상에 같은 검색어를 적용합니다.

`정보화`, `청소`, `유지보수 용역`, `시스템 구축`, `경비`, `설계`, `감리`, `소프트웨어`,
`연구 용역`, `홍보`, `교육`, `시설물 유지관리`

### 3.3 검색 대상과 파라미터

목록 화면 기본 조건과 같게 맞춥니다.

| 대상 | 필터 | 정렬 |
| --- | --- | --- |
| `result_servc` | `dataset = "result" AND category = "Servc"` | `rl_openg_dt:desc`, `source_id:desc` |
| `announcement_servc` | `dataset = "announcement" AND category = "Servc" AND is_cancelled != true` | `bid_ntce_dt:desc`, `source_id:desc` |

검색 본문은 `q`, `filter`, `sort`, `offset=0`, `limit=20`,
`attributesToRetrieve=["source_id"]` 입니다.

### 3.4 기록 항목

검색어·대상 조합마다 3회 실행해 다음을 JSON 으로 남깁니다.

- 회차별 `processingTimeMs`, `estimatedTotalHits`, 상위 5건 `source_id`
- 회차별 지연의 중앙값(`median_ms`)과 최댓값(`max_ms`)
- 마지막 회차의 추정 총건수와 상위 5건 원본 PK
- 코드가 선언한 순위 규칙(`expected_ranking_rules_from_code`). 서버 설정을 조회한 값이
  아니므로 적용 여부 판정에 쓰지 않습니다.

---

## 4. 판정 기준

적용 전·후 JSON 을 같은 검색어·대상 조합으로 짝지어 비교합니다.

1. **주 판정: 중앙값 비교.** 조합별 `median_ms` 가 적용 후 감소해야 합니다.
2. **보조 판정: 최댓값 비교.** 회차 편차가 크므로 `max_ms` 도 함께 봅니다. 중앙값은
   줄었지만 최댓값이 늘어난 조합은 개선으로 단정하지 않습니다.
3. **유의 기준.** 3회 표본에서 중앙값 감소가 20% 미만이면 노이즈와 구분하지 못한 것으로
   봅니다. 반대로 중앙값이 2배 이상 늘어난 조합이 있으면 순위 규칙 변경을 되돌립니다.
4. **결과 정합성.** 상위 5건 `source_id` 는 순위 규칙에 따라 달라질 수 있습니다. 달라진
   상위 결과가 실제로 최신순인지 눈으로 확인하고, `estimatedTotalHits` 는 적용 전후가
   같아야 합니다. 추정 건수가 달라지면 필터·색인 상태를 먼저 확인합니다.
5. **전체 판정.** 24개 조합(12 검색어 x 2 대상) 중 과반에서 중앙값이 감소하고, 2배 이상
   악화된 조합이 없으면 적용 유지로 판정합니다.

---

## 5. 측정 결과

코디네이터가 적용 전후에 스크립트를 실행해 아래 표를 채웁니다. 값은 `median_ms / max_ms`
형식이고, 괄호는 추정 총건수입니다.

### 5.1 낙찰 결과 (`result_servc`)

| 검색어 | 적용 전 | 적용 후 | 중앙값 변화 |
| --- | --- | --- | --- |
| 정보화 |  |  |  |
| 청소 |  |  |  |
| 유지보수 용역 |  |  |  |
| 시스템 구축 |  |  |  |
| 경비 |  |  |  |
| 설계 |  |  |  |
| 감리 |  |  |  |
| 소프트웨어 |  |  |  |
| 연구 용역 |  |  |  |
| 홍보 |  |  |  |
| 교육 |  |  |  |
| 시설물 유지관리 |  |  |  |

### 5.2 공고 (`announcement_servc`)

| 검색어 | 적용 전 | 적용 후 | 중앙값 변화 |
| --- | --- | --- | --- |
| 정보화 |  |  |  |
| 청소 |  |  |  |
| 유지보수 용역 |  |  |  |
| 시스템 구축 |  |  |  |
| 경비 |  |  |  |
| 설계 |  |  |  |
| 감리 |  |  |  |
| 소프트웨어 |  |  |  |
| 연구 용역 |  |  |  |
| 홍보 |  |  |  |
| 교육 |  |  |  |
| 시설물 유지관리 |  |  |  |

---

## 6. 운영 적용 절차

코디네이터가 리뷰 후 수행합니다. 빌더는 운영 Meilisearch 에 접속하지 않았습니다.

### 6.1 적용 전 측정

3.1 의 적용 전 측정을 먼저 실행해 기준선 JSON 을 남깁니다.

### 6.2 순위 규칙만 변경

설정 전체를 다시 보내지 않고 `rankingRules` 만 PATCH 합니다.

```sh
curl -sS -X PATCH "$MEILI_URL/indexes/bid_records/settings" \
  -H "Authorization: Bearer $MEILI_MASTER_KEY" \
  -H "Content-Type: application/json" \
  --data-binary '{"rankingRules":["words","sort","typo","proximity","attribute","exactness"]}'
```

응답은 `202 Accepted` 와 `taskUid` 입니다. 같은 본문을 다시 보내도 결과가 같습니다.

### 6.3 task 완료 확인

```sh
curl -sS "$MEILI_URL/tasks/{taskUid}" -H "Authorization: Bearer $MEILI_MASTER_KEY"
```

`status` 가 `succeeded`, `type` 이 `settingsUpdate`, `indexUid` 가 `bid_records` 인지
확인합니다. `failed`·`canceled` 이면 `error` 를 확인하고 6.5 로 되돌립니다. task 대기 중에는
검색 결과가 이전 설정 기준일 수 있으므로 측정을 시작하지 않습니다.

### 6.4 적용 후 측정과 판정

3.1 의 적용 후 측정을 실행해 4장 기준으로 판정합니다.

### 6.5 되돌리기

기본 순위 규칙으로 되돌리는 PATCH 본문입니다.

```json
{"rankingRules": ["words", "typo", "proximity", "attribute", "sort", "exactness"]}
```

되돌린 뒤에도 6.3 과 같은 방법으로 task 완료를 확인합니다.

### 6.6 재색인 발생 여부

Meilisearch 1.14 문서의 색인 모범 사례 문서는 "ranking rules 를 비롯한 설정을 갱신하면
Meilisearch 가 모든 문서의 재색인을 유발한다"고 적습니다. 따라서 1.14.0 운영 인스턴스에서
이 PATCH 는 약 843만 건 전체 재색인을 동반할 것으로 예상합니다. 재색인 소요 시간과 검색
가용성 영향은 이 저장소에서 측정하지 못했으므로 **미확인**입니다.

- 근거: `meilisearch/documentation` 태그 `v1.14`,
  `learn/indexing/indexing_best_practices.mdx` —
  "Whenever you update settings such as ranking rules, Meilisearch will trigger a reindexing
  of all your documents."
- 같은 태그의 `reference/api/settings.mdx` 는 기본 `rankingRules` 를
  `["words","typo","proximity","attribute","sort","exactness"]` 로 적고, 재색인을 유발하는
  개별 설정으로 distinct·filterable·searchable·sortable·stop words 를 나열합니다.
  rankingRules 재색인 문구는 이 참조 문서에는 없고 위 모범 사례 문서에만 있습니다.
- 최신 문서(1.58 계열)는 "ranking rules 변경은 전체 재색인을 유발하지 않는다"고 적습니다.
  1.14.0 에서는 이 최신 동작을 가정하지 않습니다. 버전별 동작 차이는 **미확인**입니다.
- 애플리케이션의 `sync_search_index` 는 `configure_index` 를 호출하므로, 코드 배포 뒤
  전체 동기화를 실행하면 같은 PATCH 가 다시 전송됩니다. 문서 upsert 는 별도 경로입니다.

---

## 7. 영향과 유의사항

- 정렬이 있는 키워드 검색은 키워드 일치 수(`words`)가 같은 문서끼리 최신순으로 정렬된 뒤
  typo·proximity·attribute·exactness 가 적용됩니다. 즉 관련도보다 최신순이 우선합니다.
  사용자가 승인한 순서 변화입니다.
- 정렬이 없는 검색은 기존과 같은 규칙 순서로 평가됩니다.
- `estimatedTotalHits` 는 순위 규칙과 무관하므로 적용 전후가 같아야 합니다. 다르면 필터나
  색인 상태를 먼저 확인합니다.
- 색인 문서·DB 스키마·원본 데이터는 바뀌지 않습니다. `rankingRules` 는 색인 설정입니다.
- 재색인 중에는 검색 지연이 늘 수 있습니다. 측정은 task 완료 뒤에 합니다.

---

## 8. 미확인 사항

- 1.14.0 에서 이 설정 변경의 실제 재색인 소요 시간과 그동안의 검색 지연.
- 적용 후 24개 조합의 실제 측정값(5장 표는 비어 있음).
- 되돌리기 PATCH 도 1.14 에서 전체 재색인을 유발하는지. 위 모범 사례 문서 문구상 그렇게
  예상하지만 직접 확인하지 못했습니다.

---

## 9. 참고

- `src/app/services/search_index.py` — `RANKING_RULES`, `configure_index`
- `scripts/measure_meili_ranking.py` — 읽기 전용 측정 스크립트
- `tests/test_meili_ranking_rules_20261124.py` — 순위 규칙·설정 불변·읽기 전용 검증
- Meilisearch 문서 태그 `v1.14`:
  - `learn/indexing/indexing_best_practices.mdx`
  - `reference/api/settings.mdx`
  - `learn/relevancy/ranking_rules.mdx`
  - URL: https://github.com/meilisearch/documentation/tree/v1.14
