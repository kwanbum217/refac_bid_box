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

2026-11-24 16:27(KST) 에 적용 전, 적용 직후 16:28(KST) 에 적용 후를 코디네이터가 app 컨테이너에서 같은 스크립트로 측정했다.
단위는 Meilisearch `processingTimeMs`(ms)다. 적용 전 측정이 같은 검색어의 디스크 페이지를 메모리에
올려 두었으므로 적용 후 1회차는 적용 전 1회차와 공정하게 비교할 수 없다. 판정은 2·3회차 중앙값
(메모리 적재 후 계산 비용)으로 한다. 추정 총건수는 24개 조합 모두 적용 전후가 같았고, 상위 5건은
24개 모두 달라졌다(최신순 우선으로 바뀐 의도된 변화).

### 5.1 낙찰 결과 (`result_servc`)

| 검색어 | 적용 전 1회차 / 2·3회차 중앙값 | 적용 후 1회차 / 2·3회차 중앙값 | 중앙값 변화 | 추정 총건수 |
| --- | --- | --- | --- | --- |
| 정보화 | 53 / 24 | 154 / 13 | -11 | 143,374 |
| 청소 | 13 / 10 | 40 / 7 | -3 | 57,704 |
| 유지보수 용역 | 27 / 17 | 30 / 13 | -4 | 81,810 |
| 시스템 구축 | 261 / 16.5 | 68 / 15 | -1.5 | 66,024 |
| 경비 | 441 / 4.5 | 12 / 7 | +2.5 | 165,940 |
| 설계 | 317 / 3 | 3 / 3.5 | +0.5 | 158,819 |
| 감리 | 504 / 16 | 9 / 4 | -12 | 48,555 |
| 소프트웨어 | 289 / 5 | 169 / 3 | -2 | 2,513 |
| 연구 용역 | 668 / 17.5 | 15 / 7.5 | -10 | 64,331 |
| 홍보 | 441 / 4 | 52 / 2 | -2 | 16,286 |
| 교육 | 709 / 5 | 3 / 2 | -3 | 305,949 |
| 시설물 유지관리 | 538 / 4.5 | 309 / 4.5 | +0 | 18,407 |
| **합계** | - / 127 | - / 81.5 | -45.5 (-36%) | - |

### 5.2 공고 (`announcement_servc`)

| 검색어 | 적용 전 1회차 / 2·3회차 중앙값 | 적용 후 1회차 / 2·3회차 중앙값 | 중앙값 변화 | 추정 총건수 |
| --- | --- | --- | --- | --- |
| 정보화 | 1126 / 71 | 66 / 35 | -36 | 205,184 |
| 청소 | 723 / 36.5 | 11 / 8.5 | -28 | 79,788 |
| 유지보수 용역 | 1417 / 41.5 | 25 / 13.5 | -28 | 90,561 |
| 시스템 구축 | 771 / 23.5 | 62 / 11 | -12.5 | 118,601 |
| 경비 | 714 / 21 | 11 / 10 | -11 | 227,753 |
| 설계 | 440 / 35 | 8 / 6 | -29 | 193,463 |
| 감리 | 1012 / 13 | 4 / 4.5 | -8.5 | 61,901 |
| 소프트웨어 | 238 / 6 | 122 / 5.5 | -0.5 | 3,875 |
| 연구 용역 | 351 / 34 | 14 / 13 | -21 | 150,527 |
| 홍보 | 319 / 6.5 | 49 / 4 | -2.5 | 27,644 |
| 교육 | 266 / 40.5 | 10 / 13.5 | -27 | 448,638 |
| 시설물 유지관리 | 1267 / 5 | 98 / 3 | -2 | 21,568 |
| **합계** | - / 333.5 | - / 127.5 | -206 (-62%) | - |

### 5.3 해석

- 계산 비용(2·3회차 중앙값 합)은 낙찰 결과 127.0 -> 81.5ms(-36%), 공고 333.5 -> 127.5ms(-62%)로 줄었다.
- 적용 전 1회차는 낙찰 결과 13~709ms, 공고 238~1,417ms 로 2·3회차(2~81ms)보다 한두 자릿수 컸다.
  처음 검색의 지연은 순위 계산보다 메모리에 없는 색인 페이지를 디스크에서 읽는 비용이 지배한다.
  색인 23.7GB 가 Docker VM 메모리 17.5GB(Meilisearch 사용 7.4GB)에 다 올라가지 못한다.
- 따라서 처음 검색 지연의 근본 대책은 메모리(Docker Desktop 할당 증설)이고, 이 변경은 계산 비용을 줄인다.

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

**재색인은 일어나지 않는다(실측).** 2026-11-24 코디네이터가 운영 Meilisearch 1.14.0 에 임시 색인
(`bid_records` 문서 3만 건 복사, 같은 설정)을 만들어 확인했다.

| 작업 | 소요(task duration) |
| --- | --- |
| 문서 3만 건 추가 | 4,023ms |
| rankingRules 변경 | 1.4ms |
| rankingRules 되돌리기 | 2.2ms |

재색인이 있었다면 문서 추가와 같은 규모의 시간이 들었어야 한다. 임시 색인은 확인 뒤 삭제했다.
운영 `bid_records` 적용 task 도 9.9ms 에 끝났고, searchable·filterable·sortable·pagination 설정은
바뀌지 않았다. 문서 조사에서 본 1.14 모범 사례 문서의 '설정 갱신 시 전체 재색인' 문구는 이 설정에는
해당하지 않았다. 세부 경로 `PATCH /settings/ranking-rules` 는 이 버전에서 받지 않으므로 6.2 의
`PATCH /settings` 본문(`{"rankingRules": [...]}`)을 쓴다.

- 애플리케이션의 `sync_search_index` 는 `configure_index` 를 호출하므로, 코드 배포 뒤 동기화가 같은
  설정을 다시 보낸다. 운영에는 이미 같은 값이 적용되어 있어 변화는 없다.

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

- 새 검색어(메모리 미적재)에 대한 처음 검색 지연의 적용 전후 비교. 같은 검색어로는 공정 비교가 불가능하다.

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
