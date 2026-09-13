# 세션 인수인계: 2026-09-13 RAG 콜드 SQL 원인 규명과 CI 복구

> **작성일**: 2026-09-13
> **작성자**: Claude Opus 5 (코디네이터)
> **기준 커밋**: `128e93fe`
> **이어받은 문서**: [`docs/handoff/session_20260913_wave_z_observability_chromadb.md`](session_20260913_wave_z_observability_chromadb.md) (같은 날 전반부)

---

## 1. 한 줄 요약

RAG 정형 질의 콜드 SQL 40초의 원인을 **기관명 선행 와일드카드가 31.6GB 공고 본문을 콜드로 읽는 I/O** 로
확정하고, 기관명 2단계 해석을 구현해 해석이 적용된 문항을 3.4~7.8배 줄였습니다. 이어서 2026-09-11 이후
11회 연속 실패하던 `main` CI 를 복구했습니다. 이어서 상한 초과 기관명 경로를 실측해 상한 상향을 기각했고,
테스트가 로컬 Redis 를 오염시키던 결함을 고쳤습니다. 마지막으로 공고 기관명 커버링 인덱스를 적용해 q31 을
1초대로 줄였고, 병렬 워커로 `source_commit` 뒤처짐을 병합 단위로 세게 했습니다. 이어서 낙찰 쪽과 q03 의 원인을
실행계획 힌트 두 개로 해소하고 원장 `coldsql_rerun` 을 정본으로 종결했습니다(6장, 사용자 부재 중 권고안으로 진행).
`main` 은 `128e93fe` 입니다.

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
| `aa6f0002` | `source_commit` 갱신 | CI 전 잡 성공 |
| `11611079` | 이 문서 갱신 | CI 전 잡 성공 |
| `8b928c62` / `b5351881` | 벤치마크 fixture 전용 인자 거부, `source_commit` 갱신 | CI 공급망 잡 실패 (5.4 절, 외부 요인) |
| `0810e85b` | 런타임 이미지 gzip·libsqlite3 보안 수정 | CI 전 잡 성공 |
| `24247063` / `471834ab` | 2단계 해석 경계와 인덱스 비용 추정 기록, `source_commit` 갱신 | CI 전 잡 성공 |
| `1673ad93` | `source_commit` 뒤처짐 first-parent 계산 (Wave AA 워커) | CI 전 잡 성공 |
| `f1dad950` | 공고 기관명 커버링 인덱스 (마이그레이션, G1 기준선, 전후 실측) | CI 전 잡 성공 |
| `41c7b4e1` | 이 문서 갱신 | CI 전 잡 성공 |
| `7af63a8b` | 기관명 조건 낙찰업체 집계 그룹 인덱스 배제 힌트 | CI 전 잡 성공 |
| `9ac4fe35` / `688052e3` | 상한 초과 판정 장기 캐시, 남은 과제 준비 기록, 원장 `missing_lwlt_intervals` 종결 | CI 전 잡 성공 (`688052e3`) |
| `128e93fe` | 부분 일치 되돌림 + category 공고 집계 커버링 인덱스 강제 힌트 | CI 확인 중 (6.5 절) |

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

경계는 인천·부산·광주 추가 실측으로 **15만~22만 행**으로 확정했고, 이득이 1.3배 수준이라 판정 기준은 이름 수
상한으로 유지했습니다(분석 문서 6.1 절).

### 4.2 공고 기관명 커버링 인덱스 (사용자 합의로 적용)

`ix_bid_ann_inst_cat_ntce (dminstt_nm, category, bid_ntce_nm)` 를 `migrations/versions/afc72b545c6a` 로
넣었습니다. MySQL 에서는 `ALGORITHM=INPLACE, LOCK=NONE` 온라인 DDL 이고 리비전은 멱등입니다.

| 항목 | 결과 |
| --- | --- |
| 개발 DB 적용 | 122초, 실제 크기 762MB (추정 760MB) |
| G1 | 갱신 전 차이가 이 인덱스 하나뿐임을 대조한 뒤 `schema_signature_baseline.json` 재기록, 6항목 통과 |
| q31 (대전) | 37.6 / 16.7초 → **1.1 / 1.0초** |
| q25 | 7.5 / 7.6초 → **3.4 / 1.7초** |
| q08 (서울) | 56.4 / 44.1초 → **32.3 / 32.8초** (공고명별 집계 29~33초 → 4.5초) |

세 문항 모두 범위가 겹치지 않습니다. 적용 전 1회차는 병렬 워커 전량 테스트와 겹쳤습니다. **q08 에 남은 약 30초는
`bid_results` 쪽**(금액 합계·평균 10~12초, 낙찰자별 집계 8~10초)이며 다음 1순위입니다. 웜 회차 최대값이
25~32ms 에서 62~63ms 로 늘었는데 원인은 확인하지 않았습니다.

**운영 DB 에 적용할 때는** `alembic upgrade head` 로 넣으십시오. 원시 DDL 로 먼저 만들어도 리비전이 멱등이라
결과는 같지만, 기준선 파일은 이 저장소의 것과 일치해야 G1 검증이 통과합니다.

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

### 5.4 기반 이미지 신규 취약점 (2026-09-13 오후)

Trivy 취약점 DB 갱신으로 CVE-2026-41992(gzip), CVE-2026-11822·11824(libsqlite3-0, FTS5 경유 임의 코드 실행)
HIGH 3건이 공급망 잡을 막았습니다. 수정본은 Debian 보안 저장소에 있으나 최신 `python:3.11-slim`(Debian 13.6)에도
아직 없어 digest 갱신만으로는 해소되지 않았습니다. `Dockerfile` runtime 단계에서 두 패키지만 `--only-upgrade`
합니다. CI 와 같은 설정의 Trivy 0.70 재스캔이 allowlist 필터를 통과했고 새 이미지의 compose 앱이 `ready` 였습니다.
**베이스 이미지가 수정본을 담으면 이 업그레이드 줄은 무해한 no-op 이 됩니다.**

### 5.5 Wave AA: `source_commit` 뒤처짐을 병합 단위로 센다

같은 날 이 검사로 푸시가 세 번 막혀, 빌더 Gemini 3.8 Flash, 리뷰어 Muse Spark 워커로 `_commits_behind_head`
에 `--first-parent` 를 넣었습니다(운영 코드 한 줄, 실제 git 저장소 테스트). 리뷰 pass 6항목 무결함. 병합 직후
인덱스 병합까지 두 번 거친 뒤에도 거리가 3 이라 기준 커밋을 따로 갱신하지 않았습니다. **이제 한도 5 는 main 병합
5회를 뜻합니다.**

Wave 로 함께 제안했던 W1(`missing_lwlt` 경고 플래그)은 착수 전 확인에서 `77773ae2` 로 **이미 구현돼 있어**
띄우지 않았습니다. 원장 `missing_lwlt_intervals` 는 여전히 active 로 남아 있어 정리가 필요합니다(6장).

**첫 Level 1 게이트 실패는 코드가 아니었습니다.** `tests/test_e2e_cutover.py` 가 챗봇 빈 응답으로 실패했고, 원인은
로컬 Ollama `gemma4:e2b` 러너가 `model: ""`, `done: false` 빈 응답을 즉시 돌려주는 고장이었습니다(e4b 는 정상).
`ollama stop gemma4:e2b` 후 재적재로 해소했습니다. **같은 E2E 가 로컬에서만 갑자기 실패하면 Ollama 직접 호출부터
확인하십시오.**

**워커 완료를 두 번 늦게 알았습니다.** 완료 대기를 셸 `&` 로 분리해 알림이 오지 않았고, 대기 스트림의
`_keepalive` 줄을 `json.load` 로 읽어 대기가 즉시 끝났습니다. 대기는 추적되는 배경 작업으로만 거십시오.

## 6. 사용자 부재 중 진행 (2026-09-13 저녁)

사용자 지시("결정해서 진행해야 하는 사항들은 네가 권장하는 방법으로")에 따라 되돌리기 쉬운 코드·문서 변경만 진행하고,
DDL 과 데이터 사전 조작은 준비와 기록까지만 했습니다. 상세는 분석 문서 10~14장입니다.

### 6.1 병합한 대책

| 대책 | 원인 | 결과 |
| --- | --- | --- |
| 낙찰업체 집계 `IGNORE INDEX (ix_bid_results_bidwinnr_nm)` (기관명 조건, 날짜 없음) | 그룹 인덱스 339만 항목 스캔 후 행마다 본문 조회 | q08 14.2~14.8초 → 8.6~8.7초 |
| 상한 초과 판정 7일 캐시 (이름 목록은 1시간 유지) | "서울" 해석 질의 1.4초를 매시간 반복 후 폐기 | 반복 제거. 되돌림은 항상 완전한 부분 일치라 정확성 위험 없음 |
| 공고 집계 `FORCE INDEX (ix_bid_ann_inst_cat_ntce)` (부분 일치 되돌림 + category, 날짜 없음) | 옵티마이저가 category 인덱스로 Servc 211만 행 본문을 흩어 읽음 | **q03 52.1~52.4초 → 7.8~7.9초** |

세 대책 모두 완전 콜드 교차 2회 실측으로 판정했고 결과 해시가 같았습니다.

### 6.2 정본 재측정과 원장

`688052e3` 에서 09-07 정본과 같은 조건(32문항 × 3회)으로 완전 콜드 정본을 쟀고 canonical 을 통과했습니다(96요청 전량).
콜드 SQL 중앙값 18ms, 최대 q03 82.5초였고 그 원인이 6.1 절 셋째 대책입니다. 원장 `coldsql_rerun` 은 이 정본으로 종결했습니다.
**힌트 병합 후 정본 재측정은 메모리 부족으로 두 번 강제 종료돼 하지 못했습니다(6.4 절).**

### 6.3 발견해서 기록만 한 것 (사용자 결정 필요)

**`bid_results` 데이터 사전에 `.ibd` 파일 없는 FULLTEXT 보조 테이블 6개가 있습니다**(tablespace 156~161). MySQL 은 기동마다
경고 6줄을 남기고 `information_schema.INNODB_INDEXES` 조인은 `ERROR 1812` 로 실패합니다. 기각된 ngram FULLTEXT 제거의 흔적으로
보이며, 테이블 재구축 DDL·물리 백업·업그레이드에서 문제가 될 수 있습니다. 사전 조작은 되돌리기 어려워 손대지 않았습니다.
**`bid_results` 에 DDL 을 걸기 전에 반드시 이 항목부터 정리 방법을 정하십시오.**

낙찰 금액 집계 커버링 인덱스 `(dminstt_nm, sucsf_bid_rate, sucsf_bid_amt)` 는 약 300MB 로 추정만 하고 위 사유로 보류했습니다.

### 6.4 측정 환경 제약 두 가지

- **호스트 파일 캐시**: VM 안 `drop_caches` 는 macOS 호스트 캐시를 비우지 못해 1.46GB 급 테이블은 완전 콜드가 되지 않습니다.
  호스트 `purge` 는 관리자 암호가 필요합니다. 그 전까지 소규모 테이블은 같은 회차 안 교차 비교로만 판정하십시오.
- **메모리**: 호스트 24GB 에 Docker VM 13.6GB 와 Ollama 모델이 상주합니다. `gemma4:e2b`(7GB)와 `bge-m3` 가 `keep_alive`
  무기한으로 남아 있었고, 전체 fixture 측정이 `gemma4:e4b` 를 올리면 **하네스가 배경 작업을 메모리 부족으로 강제 종료**합니다.
  측정 전 `curl localhost:11434/api/ps` 로 확인하고 `{"model":"...","keep_alive":0}` 로 내리십시오. 모델을 내려도 전체 fixture
  측정은 끝까지 가지 못했습니다(4문항·2문항 측정은 완주).

### 6.5 확인하지 못한 것

- `128e93fe` CI 는 대기 작업이 메모리 부족으로 종료돼 결과를 받지 못했습니다. 마지막 조회 시 진행 중이었습니다.

## 7. 다음 착수 순서

| 순서 | 작업 | 선행 조건 |
| :---: | --- | --- |
| 1 | `128e93fe` CI 결과 확인 (6.5 절) | 없음 |
| 2 | `bid_results` 고아 FULLTEXT 사전 항목 정리 방법 결정과 복제본 검증 (6.3 절) | 사용자 결정 |
| 3 | 낙찰 금액 집계 커버링 인덱스 약 300MB (6.3 절) | 2, DDL 합의 |
| 4 | 힌트 병합 후 정본 재측정. 메모리 확보(다른 앱 종료, Docker VM 메모리 조정) 뒤 | 메모리 |
| 5 | 셸 명령 자동 승인 실동작 확인. **Wave AA 에서 미확인**: 상시 감시기는 W2 터미널을 `승인 대기` 로 두 번 표시했으나 자동 승인 로그에는 설문 해제 한 줄뿐이었고 워커는 진행했습니다. 누가 승인했는지 확인되지 않았습니다 | 다음 워커 기동 |
| 6 | Windows 실기 검증 | 장비. G2 유일 잔여 조건 |
| 7 | chromadb 상류 수정 버전 재확인 | 2026-12-31 또는 권고 갱신 |

`coldsql_rerun`(`current_state_facts.yaml`, active)은 이번 측정이 canonical 게이트(`item_count_full`)를
충족하지 않아 원장 상태를 바꾸지 않았습니다. 정본 수치로 닫으려면 전 문항 측정이 필요합니다.

---

## 8. 자원 상태

| 대상 | 상태 |
| --- | --- |
| Docker | `app`, `db`, `redis`, `meilisearch` 가동 중. 관측성 프로파일은 내림 |
| 앱 설정 | `LATENCY_SEGMENT_LOGGING=false`, `OLLAMA_MODEL=gemma4:e2b` (`.env` 기본값, 확인 완료) |
| MySQL | `innodb_buffer_pool_dump_at_shutdown=ON` 복원 확인 |
| 워크트리 | 주 저장소 하나 |
| 브랜치 | `main` 과 다른 세션 소유 `kwanbum217/orca-r15-verify` |
| Redis | 테스트는 로컬 Redis 에 쓰지 않음. 남은 `rag:*` 키는 측정 중 앱이 만든 정상 캐시 (TTL 1시간) |
| Ollama | `gemma4:e2b` 러너 재적재 후 정상 |
| MySQL 리비전 | 개발 DB `afc72b545c6a` (인덱스 적용) |
| 감시기 | 공용 상시 감시기 `orca_worker_watch`(PID 10801) 하나. 이 세션의 URL 승인 루프는 종료 |
| Orca Run `run_d38c5a224e54` | Task 2건 `completed`, 워커 터미널 회수 완료 |
| Orca Run `run_3c37e482a894` | Task 2건(`task_de96a1306bd7` 빌더, `task_9c39416a7b85` 리뷰) `completed`, 터미널 회수, 워크트리·브랜치 제거 |
| 원격 | `origin/main` = `128e93fe` (이 문서 병합 전), CI 확인 중 |
