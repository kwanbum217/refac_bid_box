# Wave F 인수인계 — RAG 콜드 SQL 잔여 지배 쿼리

> **작성일**: 2026-08-30
> **Run**: `run_6f582c85ef52`
> **상태**: 조사 완료, 구현 미착수
> **다음 착수 지점**: 아래 4장

---

## 1. 무엇이 확정됐는가

콜드 SQL 223.77초(Wave E4 정본)의 92%는 **사용자 검색의 선행 와일드카드
`LIKE '%키워드%'`** 하나에서 나옵니다. `category` 인덱스로 109만~163만 행까지만
좁혀진 뒤 그 전부를 훑고 `Using temporary; Using filesort` 를 수행합니다.
카테고리 필터가 없으면 풀스캔입니다.

---

## 2. 닫힌 후보와 근거

| 후보 | 판정 | 근거 |
| --- | :---: | --- |
| 접두 일치 전환 | 기각 | Wave E2. 거제시 표본 99.6% 손실 |
| Meilisearch 위임 | 기각 | Wave F2. MySQL 1,703건 대 Meili 17,162건(+908%). 토큰 매칭과 부분 일치의 의미 차이이며 편차가 -14%~+1,267% 로 요동. COUNT·GROUP BY 집계 불가 |
| 손상 필터 제거 | 무효 | Wave F1. `NOT LIKE` 유무와 무관하게 EXPLAIN 의 type·key·rows·filtered·Extra 동일. 비용 원인이 아님 |
| 기관 차원 스냅샷 확장 | 부적용 | 사용자 입력이 키가 아니라 부분 문자열. 고유 기관명 43,628종, "거제시" 는 21종 기관에 걸리고 "거제시" 라는 정확한 이름의 기관은 0건 |

**이 넷은 다시 제안하지 마십시오.** 각 판정은 실측 근거를 갖고 있습니다.

---

## 3. 채택 권고 — ngram FULLTEXT (컬럼별 선택)

격리 `ngram_probe` 스키마에 운영과 동일 행 수를 복사해 측정했습니다
(`bid_announcements` 5,490,072, `bid_results` 3,423,008, 차이 0·중복 id 0).

채택 형태는 다음과 같습니다. 기존 `LIKE` 를 **제거하지 않고 그대로 둡니다.**

```sql
WHERE MATCH(col) AGAINST('+"키워드"' IN BOOLEAN MODE)
  AND col LIKE '%키워드%'
```

| 대상 컬럼 | 현행 warm | ngram warm | 판정 |
| --- | ---: | ---: | :---: |
| `dminstt_nm` GROUP BY + cat | 1,719.6ms | **90.6ms** | **19.0배 개선. 채택** |
| `bidwinnr_nm` GROUP BY + cat | 808.7ms | **283.8ms** | **2.9배 개선. 채택** |
| `bidwinnr_nm` GROUP BY no cat | 395.5ms | 304.6ms | 1.3배 개선 |
| `bid_ntce_nm` GROUP BY + cat | 8,306.2ms | 10,417.4ms | 25% 악화. **제외** |
| `bid_ntce_nm` GROUP BY no cat | 8,076.3ms | 10,282.6ms | 27% 악화. **제외** |
| `bid_ntce_nm` COUNT + cat | 1,817.7ms | 4,126.6ms | 2.3배 악화. **제외** |
| `bid_ntce_nm` SELECT ID + cat | 0.42ms | 1,054.1ms | 2,500배 악화. **제외** |
| `dminstt_nm` SELECT ID + cat | 0.44ms | 11.7ms | 27배 악화. 단건 조회는 제외 |

인덱스 생성 비용(probe 기준): 5종 합계 1,548초. `dminstt_nm` 609초,
`bidwinnr_nm` 126초. 인덱스가 데이터의 66~87%.

상세는 [`../analysis/task_f3_ngram_fulltext_probe.md`](../analysis/task_f3_ngram_fulltext_probe.md).

---

## 4. 다음 착수 순서

1. **구현**: `src/rag/structured_data.py` 에서 `dminstt_nm`·`bidwinnr_nm` 집계 질의에
   `MATCH AGAINST` 선행 필터를 추가합니다. 기존 `LIKE` 는 유지합니다.
   `bid_ntce_nm` 과 단건 `SELECT ID` 경로는 건드리지 않습니다.
2. **누락 탐지 회귀 테스트**: 아래 5장의 위험 때문에 필수입니다. 이것 없이 병합하지
   않습니다.
3. **운영 인덱스 생성**: 사용자 승인 후 별도 수행. 5장의 재구축 주의 참조.
4. **개선 확인**: `scripts/measure_coldsql_attribution.py` 로 콜드 SQL 정본을
   재측정합니다. E4 와 동일 규약(fixture v2 32문항 x 3회, `--flush-cache`).

---

## 5. 반드시 알아야 할 위험 2건

### 5.1 누락이 유일한 실패 양식이며 조용히 틀립니다

`MATCH(...) AND LIKE` 는 구조상 **항상 현행 `LIKE` 결과의 부분집합**입니다.
따라서 "초과 0건" 은 측정 결과가 아니라 설계상 당연합니다. **실제 위험은 누락뿐**이며,
누락이 생기면 답이 조용히 줄어듭니다. Wave E1 회귀와 같은 실패 양식입니다.

F3 이 보고한 50 케이스 누락 0건은 **워커 측정이며 코디네이터 재현은 하지 못했습니다.**
Capsule 이 요구한 대로 probe 스키마가 삭제되어 인덱스가 사라졌기 때문입니다.
검증 요구와 정리 요구를 한 Capsule 에 함께 넣은 설계 문제였습니다.

### 5.2 첫 FULLTEXT 추가는 테이블을 재구축합니다

두 테이블 모두 현재 FULLTEXT 인덱스가 없습니다. MySQL 8 에서 첫 FULLTEXT 를 추가하면
숨은 `FTS_DOC_ID` 컬럼이 생기며 **테이블 전체가 재구축**되고 그동안 쓰기가 차단됩니다.

| 테이블 | 데이터 크기 | 영향 |
| --- | ---: | --- |
| `bid_results` | 1,060MB | 재구축 부담 작음 |
| `bid_announcements` | **27,272MB** | 계획된 작업으로 수행. 수집이 멈춘 시간대 선택 |

2026-08-30 디스크 정리로 호스트 여유 8.5GB -> 66GB 를 확보해 공간 제약은 해소됐습니다
(빌드 캐시 27GB, 미사용 이미지 16.5GB, 미사용 볼륨 32.4GB 회수).

---

## 6. 조율 기록

| Task | 모델 | 결론 |
| --- | --- | --- |
| F1 `task_f50eb8c4d5c0` | gemini-3.7-flash-medium | 손상 필터는 비용 원인이 아님 |
| F2 `task_bdb4581217d3` | qwen3.7-plus | Meilisearch 위임 불가 |
| F3 `task_c138f15bf6a3` | gemini-3.7-flash-high | ngram 컬럼별 선택 채택 권고 |

워커 계약 위반 기록은 [`orca_do_not_repeat.md`](orca_do_not_repeat.md) 와 함께
다음 Capsule 작성 시 참고하십시오. 이번 Wave 에서 확인된 것은 검증 명령 미실행,
`worker_done` 누락, 절대 경로 사용, DB 비밀번호 명령줄 노출입니다.
