# `rebuild_knowledge_base` 메모리 폭주로 인한 워커 컨테이너 소멸

> **작성일**: 2026-09-08
> **작성자**: 코디네이터 (직접 실측)
> **대상 커밋**: `301a164`
> **판정**: 코드 결함. 전체 문서 집합을 메모리에 한 번에 적재합니다

---

## 1. 결론

`update_kb_task` 실행 시 worker 컨테이너가 **10.5GB** 를 사용하고 소멸합니다.
Docker VM 총량 15.6GiB 에서 app 2.6GB, db 2.1GB 와 겹쳐 한계에 도달합니다.

로그에 나타나는 `sqlite3.OperationalError: disk I/O error` 는 **증상이며 원인이
아닙니다.** 컨테이너가 회수되는 과정에서 진행 중이던 SQLite 커밋이 끊긴 결과입니다.

**Docker 메모리 상향으로는 해결되지 않습니다.** 14GiB 에서 16GiB 로 올린 뒤에도
재현됐습니다. 데이터가 늘면 다시 깨지므로 스트리밍 처리로 바꿔야 합니다.

---

## 2. 실측 곡선

`update_kb_task` 투입(19:05:35)부터 컨테이너 소멸까지 1초 간격 샘플입니다.
측정은 `docker exec <컨테이너> cat /sys/fs/cgroup/memory.current` 입니다.

| 시각 | worker | app | db | 구간 |
| --- | ---: | ---: | ---: | --- |
| 19:05:31 | 352MB | 2,750MB | 2,431MB | 유휴 |
| 19:05:35 | 438MB | 2,752MB | 2,431MB | **작업 투입** |
| 19:06:01 | 1,326MB | 2,692MB | 2,432MB | 완만 상승 (약 33MB/초) |
| 19:06:05 | 1,920MB | 2,690MB | 2,581MB | **변곡점** |
| 19:06:16 | 5,089MB | 2,693MB | 3,612MB | 급상승 (약 280MB/초) |
| 19:06:24 | 6,839MB | 2,690MB | 4,566MB | db 도 동반 상승 |
| 19:06:32 | 9,444MB | 2,690MB | 2,673MB | |
| **19:06:37** | **10,509MB** | 2,565MB | 2,101MB | **직후 소멸** |

19:06:05 의 변곡점에서 db 메모리가 2.4 -> 4.5GB 로 함께 오릅니다. 대량 쿼리가
그 지점에서 시작된다는 뜻입니다.

---

## 3. 인과 사슬

```
update_kb_task (rebuild_knowledge_base, full=False)
  -> 최근 1년 공고·낙찰 문서를 리스트로 전량 적재       (1.3GB -> 급상승)
  -> documents / metadatas / ids 리스트를 통째로 보유
  -> HNSW 세그먼트 2.1GB 적재까지 겹침
  -> worker 10.5GB, VM 15.6GB 한계 도달
  -> 컨테이너 회수 (cgroup memory.max 는 max 이므로 OOMKilled=false, ExitCode=0)
  -> 진행 중이던 SQLite 커밋 절단
  -> sqlite3.OperationalError: disk I/O error
```

`memory.max` 가 `max`(무제한)이라 cgroup OOM 킬러가 아니라 VM 수준 회수입니다.
그래서 Docker 가 정상 종료로 기록하고 `OOMKilled` 도 false 입니다.

---

## 4. 기각한 가설

각 가설을 반증한 실측입니다.

| 가설 | 반증 근거 |
| --- | --- |
| 디스크 공간 부족 | 컨테이너 안에서 신규 SQLite 5,000행 커밋 성공, 기존 `chroma.sqlite3` DDL 커밋 성공. SQLite 는 공간 부족 시 `SQLITE_FULL`(`database or disk is full`)을 내며 관측된 것은 `SQLITE_IOERR` 로 코드가 다름 |
| 대량 배치 upsert | `INDEX_BATCH_SIZE` 는 100. 정본 `_flush` 로 1,000건 upsert 가 bge-m3 로 19.1초에 성공 |
| SQLite 잠금 경합 | 정지 시점에 worker 가 `chroma.sqlite3` 를 fd 로 열고 있지도 않았음 (app 은 7개) |
| bge-m3 임베딩 문제 | 같은 `OllamaEmbeddingFunction` 으로 새 컬렉션 1,000건 성공 |
| Docker 메모리 상향으로 해결 | 13.63 -> 15.60GiB 상향 후 격리 시험은 통과했으나 전체 파이프라인은 73초 만에 재현. **필요조건이나 충분조건 아님** |

**주의**: 코디네이터가 처음에 `df` 94% 를 보고 디스크 공간 부족으로 단정했습니다.
상관을 인과로 읽은 오진이며 사용자 지적으로 바로잡았습니다. SQLite 오류 코드를
먼저 구분했어야 합니다.

---

## 5. 격리 시험이 통과한 이유

코디네이터의 격리 시험은 `_load_existing_index` + `_flush` 200건만 돌려 1GB 대에서
끝났습니다. 전체 파이프라인에는 그 앞에 최근 1년치 문서를 DB 에서 읽어 메모리에
쌓는 단계가 있고 그것이 폭주 구간입니다.

| 시험 | 최대 메모리 | 결과 |
| --- | ---: | --- |
| 컬렉션 열기 + `count()` | 미미 | 성공 0.2초 |
| `_load_existing_index` 536,002건 | 미미 | 성공 22.6초 |
| 읽기 후 `_flush` 200건 | 약 1GB | 성공 (16GiB 조건) |
| **전체 `update_kb_task`** | **10.5GB** | **소멸** |

---

## 6. 데이터 무결성

조사 전 구간에서 G1 을 유지했습니다.

- `bidding_kb` 536,002건 불변
- probe 컬렉션과 probe 문서 잔존 0건
- `bid_announcements` 5,500,771행 (따라잡기 수집분 +1,812 포함)
- 데이터 볼륨 3종 보존

`full=False` 이므로 `kb_builder.py:254` 의 `delete_collection` 경로는 타지 않습니다.

---

## 7. 수정 방향

`rebuild_knowledge_base` 가 문서 집합 전체를 리스트로 보유하지 않고 청크 단위로
읽어 바로 `_flush` 에 넘기고 버리는 구조여야 합니다. `_load_existing_index` 가
반환하는 해시 맵(536,002건)도 메모리에 상주하므로 함께 검토해야 합니다.

**Docker 메모리를 더 올리는 것은 해법이 아닙니다.** 데이터가 늘면 같은 지점에서
다시 깨집니다.
