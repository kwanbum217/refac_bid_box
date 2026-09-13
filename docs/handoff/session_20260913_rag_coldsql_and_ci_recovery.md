# 세션 인수인계: 2026-09-13 RAG 콜드 SQL 원인 규명과 CI 복구

> **작성일**: 2026-09-13
> **작성자**: Claude Opus 5 (코디네이터)
> **기준 커밋**: `aa6f0002`
> **이어받은 문서**: [`docs/handoff/session_20260913_wave_z_observability_chromadb.md`](session_20260913_wave_z_observability_chromadb.md) (같은 날 전반부)

---

## 1. 한 줄 요약

RAG 정형 질의 콜드 SQL 40초의 원인을 **기관명 선행 와일드카드가 31.6GB 공고 본문을 콜드로 읽는 I/O** 로
확정하고, 기관명 2단계 해석을 구현해 해석이 적용된 문항을 3.4~7.8배 줄였습니다. 이어서 2026-09-11 이후
11회 연속 실패하던 `main` CI 를 복구했습니다. 이어서 상한 초과 기관명 경로를 실측해 상한 상향을 기각했고,
테스트가 로컬 Redis 를 오염시키던 결함을 고쳤습니다. `main` 은 `aa6f0002` 이며 CI 10개 잡이 전부 성공입니다.

---

## 2. 병합 내역

| 커밋 | 내용 | 검증 |
| --- | --- | --- |
| `0faf67d6` | chromadb 1.x 업그레이드 보류 결정 | 전반부 문서 4.2 절 |
| `1337d002` | RAG 콜드 SQL 원인 규명 분석 문서 | 전량 4,658건 |
| `320ccf2c` | 기관명 2단계 해석 구현과 전후 실측 | 전량 4,666건, MySQL 동등성 6건 |
| `87ceac47` | Tailwind 스캔 누락, 미러 도구 Windows 경로 | CI 부분 해소 |
| `c395771a` | 미러 테스트 파라미터, `source_commit` 갱신 | CI 전 잡 성공 |
| `5447d856` | 이 문서 초판 | CI 전 잡 성공 |
| `f69b1f68` | 상한 초과 기관명 실측, 테스트 캐시 전역 격리 | CI `lint-and-validate` 실패 (5.3 절) |
| `aa6f0002` | `source_commit` 갱신 | **CI 전 잡 성공** |

---

## 3. RAG 콜드 SQL 원인

정본은 [`docs/analysis/rag_coldsql_root_cause_20260913.md`](../analysis/rag_coldsql_root_cause_20260913.md) 입니다.

| 확정 사항 | 근거 |
| --- | --- |
| 느린 문장은 전부 `dminstt_nm LIKE '%기관명%'` + 날짜 조건 없음 | `performance_schema` 문장 요약 |
| 인덱스 선택은 원인이 아님. 계획 3변형이 완전 콜드에서 모두 16~28초 | 교차 2회 실측 |
| `bid_announcements` 데이터 31.6GB, 버퍼풀 2GB | `information_schema.tables` |

**이전 기록 두 가지를 뒤집었습니다.**

- r13(09-07)의 "콜드 버퍼풀에서 가장 빨랐다" 는 OS 페이지 캐시를 비우지 않은 측정이었습니다.
- 캐시 미적중 SQL 이 1.6초와 41초를 오가던 분산은 계획 흔들림이 아니라 그 순간 페이지가 메모리에
  있었는지의 차이입니다.

### 3.1 완전 콜드를 만드는 절차

이 절차 없이 잰 콜드 수치는 서로 비교할 수 없습니다.

```sh
# 1. 종료 시 버퍼풀 덤프를 끈다
SET GLOBAL innodb_buffer_pool_dump_at_shutdown=OFF;
# 2. DB 를 내리고 덤프 파일을 지운다
docker compose stop app db
docker run --rm -v refac_bid_box_mysql_data:/var/lib/mysql --entrypoint rm <mysql 이미지> -f /var/lib/mysql/ib_buffer_pool
# 3. Docker VM 의 OS 페이지 캐시를 비운다 (이것이 빠지면 콜드가 아니다)
docker run --rm --privileged --entrypoint sh <mysql 이미지> -c 'sync; echo 3 > /proc/sys/vm/drop_caches'
# 4. 기동 후 Innodb_buffer_pool_pages_data 가 1,000 안팎인지 확인
docker compose start db
```

측정 뒤 `innodb_buffer_pool_dump_at_shutdown` 은 `ON` 으로 되돌렸습니다(확인 완료).

---

## 4. 기관명 2단계 해석

`src/rag/structured_data.py` 의 `_resolve_institution_names` 가 기관명 인덱스(359MB)에서 정확한 이름
목록을 먼저 구하고, 본 집계는 `dminstt_nm IN (...)` 으로 조회합니다. 1,000 종을 넘으면 종전 부분 일치로
돌아갑니다(`INSTITUTION_NAME_RESOLVE_LIMIT`). 계측 구간명은 `institution_resolve_N` 입니다.

| 문항 | 해석된 기관명 | before (2회) | after (2회) | 판정 |
| --- | --- | --- | --- | --- |
| q25 | 상한 이내 | 48.2 / 53.1초 | **6.6 / 6.4초** | 약 7.8배, 범위 비중첩 |
| q31 | 대전 | 50.1 / 53.8초 | **16.2 / 14.4초** | 약 3.4배, 범위 비중첩 |
| q08 | 서울 (2,588종) | 38.1 / 41.5초 | 44.0 / 38.8초 | 상한 초과로 종전 경로, 차이 없음 |

`LIKE` 와 `IN` 의 행 집합 동등성은 `tests/test_institution_name_resolution.py` 의 `mysql_integration`
6건이 실제 MySQL 에서 id 집합으로 확인합니다. CI 기본 실행은 이 마커를 제외하므로 **해석 로직을 고치면
로컬에서 직접 돌리십시오.**

```sh
MYSQL_TEST_URL="$(uv run python -c 'from src.app.core.config import settings; print(settings.DATABASE_URL)')" \
  uv run pytest tests/test_institution_name_resolution.py -m mysql_integration
```

**`benchmark_rag_segments.py` 는 `--fixture` 없이 `--item-ids` 를 주면 조용히 무시하고 즉석 질의 5건을
보냅니다.** 이번 세션 첫 측정이 이것으로 폐기됐습니다. 반드시 `--fixture data/eval/llm_quality_fixture_v2.json`
을 함께 주십시오.

### 4.1 상한 초과 기관명: 상한을 올리지 않는다

q08 의 "서울"(공고 2,588종, 일치 442,955행)로 완전 콜드 교차 2회를 쟀습니다(분석 문서 8장).

| 문장 | `LIKE` (현재 되돌림) | 2단계 해석 |
| --- | --- | --- |
| COUNT | 2.0 / 1.3초 | 1.2 / 1.2초 |
| 공고명별 GROUP BY | 41.6 / 22.6초 | **49.7 / 48.3초 (더 느림, 범위 비중첩)** |

**2단계 해석의 효과를 가르는 것은 이름 수가 아니라 일치 행 수입니다.** 세종(7,951행) 4배, 대전(103,608행)
3.4배 빨라졌고 서울(442,955행)은 느려졌습니다. 흩어진 본문 읽기가 순차 읽기보다 비싸지는 경계가 10만~44만 행
사이에 있습니다. 현재 1,000종 상한은 그 근사치로 맞게 동작하므로 코드는 바꾸지 않았습니다.

q08 의 28초 구간 대책은 분석 문서 8.1 절의 세 선택지(`(dminstt_nm, bid_ntce_nm)` 복합 인덱스, 기관명
단위 사전 집계, 넓은 기관명 날짜 기본값) 중 **사용자 결정**이 필요합니다.

---

## 5. CI 복구

`main` CI 는 `95c1b810`(09-11) 이후 이 세션 전반부 병합까지 11회 연속 실패였습니다. **이 세션은 병합 6건을
CI 확인 없이 쌓았고 뒤늦게 발견했습니다.** 전임 인수인계가 병합 후 CI 확인을 적어 두었는데 지키지 않았습니다.

| 결함 | 원인 | 수정 |
| --- | --- | --- |
| Tailwind CSS 재현성 | Wave Y3(`afb444ec`)가 인라인 JS 를 `src/app/static/js/chat.js` 로 옮겼으나 스캔 대상이 템플릿 HTML 뿐. 재빌드 시 chat.js 전용 클래스 16개가 빠짐 | `tailwind.config.js` 스캔에 정적 JS 추가, `!container` 오탐을 `blocklist` 로 차단. 재빌드 결과가 커밋본과 바이트 동일 |
| Windows pytest | `scripts/sync_skill_mirrors.py` 가 식별자를 `str(Path)` 로 만들어 `.claude\skills` | `as_posix()` 로 전환. 첫 수정에서 테스트 파라미터 한 줄을 놓쳐 한 번 더 실패 |
| 규칙 검증 | `source_commit` 이 main HEAD 보다 6 커밋 뒤. 작업 브랜치에서는 경고, 기본 브랜치에서는 실패 | `87ceac47` 로 갱신 |

**Tailwind 결함은 CI 문제만이 아니었습니다.** 누군가 CSS 를 재빌드해 커밋했다면 챗봇 말풍선 폭
(`max-w-[70%]`, `max-w-[85%]`), 좌우 정렬(`flex-row-reverse`), 버튼 크기(`h-11`, `w-11`)가 조용히
사라졌을 것입니다. **정적 JS 에서 Tailwind 클래스를 새로 쓰면 `npm run build:css` 결과를 커밋하십시오.**

### 5.1 병합 절차에 더할 것

```sh
# main 에서 병합한 직후. 규칙 검증이 통과해야만 푸시한다 (; 로 잇지 말 것)
python3 scripts/validate_agent_rules.py --quiet && git push origin main
gh run list --commit "$(git rev-parse HEAD)" --workflow ci.yml --limit 1   # run 을 찾아 완료까지 대기
```

### 5.2 테스트가 로컬 Redis 를 오염시키던 결함

상한 초과 실측을 병합하려다 `tests/test_rag_engine.py` 두 건이 **로컬에서만** 실패했습니다. RAG 캐시 키는 SQL
문자열 해시라 DB 가 달라도 같은데, 테스트가 로컬 Redis 에 값을 써서 이전 실행의 sqlite 테스트 데이터로 만든
기관명 목록을 다음 실행이 받아 갔습니다. CI 에는 Redis 가 없어 드러나지 않았습니다.

전량 실행 한 번이 `rag:*` 키 116개를 남겼습니다(`test_rag_singleflight` 104, E2E 두 파일 12). **이 값은 로컬
개발용 앱의 답도 최대 1시간 오염시킬 수 있었습니다.** `tests/conftest.py` 에 autouse `_isolate_process_cache`
를 넣어 모든 테스트가 메모리 캐시를 쓰게 했고, 전량 실행 후 잔류 키 0 을 확인했습니다. 특정 캐시 상태가 필요한
테스트는 그 뒤에 다시 덮어씁니다.

### 5.3 규칙 검증 실패 상태로 푸시한 커밋

`f69b1f68` 병합 뒤 main 에서 `validate_agent_rules.py` 가 `source_commit` 8 커밋 뒤처짐으로 `[FAIL]` 을 냈는데,
명령을 `;` 로 이어 붙여 푸시가 그대로 실행됐습니다. 그 커밋의 CI `lint-and-validate` 가 실패했고 나머지 잡은
전부 통과했습니다. `aa6f0002` 로 기준 커밋을 갱신해 해소했고 그때부터 푸시를 규칙 검증 성공에 걸었습니다.
**한 브랜치에 커밋이 여러 개 쌓이면 병합 시점에 한도 5 를 넘기 쉽습니다.**

---

## 6. 다음 착수 순서

| 순서 | 작업 | 선행 조건 |
| :---: | --- | --- |
| 1 | 넓은 기관명 GROUP BY 대책 방향 결정 (분석 문서 8.1 절, 이 문서 4.1 절). 상한 상향은 실측으로 기각 | 사용자 결정 |
| 2 | `(dminstt_nm, category)` 복합 커버링 인덱스 효과·쓰기 비용 실측 (q31 잔여 11~13초) | DDL 사용자 합의 |
| 3 | 2단계 해석 경계를 일치 행 수로 확정 (10만~44만 행 사이) | 없음 |
| 4 | `benchmark_rag_segments.py` 가 fixture 없는 `--item-ids` 를 거부 | 없음 |
| 5 | 셸 명령 자동 승인 실동작 확인 | 다음 워커 기동 |
| 6 | Windows 실기 검증 | 장비. G2 유일 잔여 조건 |
| 7 | chromadb 상류 수정 버전 재확인 | 2026-12-31 또는 권고 갱신 |

`coldsql_rerun`(`current_state_facts.yaml`, active)은 이번 측정이 canonical 게이트(`item_count_full`)를
충족하지 않아 원장 상태를 바꾸지 않았습니다. 정본 수치로 닫으려면 전 문항 측정이 필요합니다.

---

## 7. 자원 상태

| 대상 | 상태 |
| --- | --- |
| Docker | `app`, `db`, `redis`, `meilisearch` 가동 중. 관측성 프로파일은 내림 |
| 앱 설정 | `LATENCY_SEGMENT_LOGGING=false`, `OLLAMA_MODEL=gemma4:e2b` (`.env` 기본값, 확인 완료) |
| MySQL | `innodb_buffer_pool_dump_at_shutdown=ON` 복원 확인 |
| 워크트리 | 주 저장소 하나 |
| 브랜치 | `main` 과 다른 세션 소유 `kwanbum217/orca-r15-verify` |
| Redis | `rag:*` 키 0. 테스트는 이제 로컬 Redis 에 쓰지 않음 |
| 감시기 | 공용 상시 감시기 `orca_worker_watch`(PID 10801) 하나. 이 세션의 URL 승인 루프는 종료 |
| Orca Run `run_d38c5a224e54` | Task 2건 `completed`, 워커 터미널 회수 완료 |
| 원격 | `origin/main` = `aa6f0002`, CI 전 잡 성공 |
