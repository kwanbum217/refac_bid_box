# 핸드오프 인수인계 - 챗봇 실사용 질문 개선 웨이브 2 (2026-10-26)

> **작성일**: 2026-10-26
> **작성**: 코디네이터(Claude Code, Opus 5.5). Orca Run `run_89eeda0fdf77`
> **기준 커밋**: `1f8f2331` (main, 묶음 4 병합. CI success)
> **직전 인수인계**: [handoff_20261025_chatbot_wave.md](handoff_20261025_chatbot_wave.md)
> **범위**: 묶음 4 병합, 재측정 결과, 검증 완료 미병합 브랜치 5개, 진행 중 워커 3대, 사용자 결정 5건, 운영 캐시 오염 사고와 조치
> **종료 사유**: 코디네이터 토큰 한도(5시간 사용량 80%) 근접. 묶음 5 병합과 재측정은 다음 세션으로 넘긴다

---

## 0. 요약

> **최신 상태는 9 절이다.** 0~8 절은 묶음 4 시점(`1f8f2331`) 기록이며, 3·4·7 절의 미병합 브랜치와 워커는 9 절에서 모두 처리됐다.

| 항목 | 값 |
| --- | --- |
| main | `1f8f2331` 묶음 4(6개 브랜치) 병합, 원격 반영, CI success |
| v1 점검 세트 | 70/70(일요일 `62650ad0`) -> 62/70(월요일 `1f8f2331`). 코드 회귀 아님, 2.2 절 |
| v2 점검 세트 | 12/20 -> **17/20** |
| 검증 완료 미병합 | 6개 브랜치(3 절). 묶음 5 대상 |
| 진행 중 워커 | 빌더 2대(4 절). 이 세션은 회수하지 않고 종료한다 |
| 사용자 결정 | 5건(5 절). 모두 반영 또는 반영 중 |
| 사고 | 운영 Redis 집계 캐시 오염(6 절). 캐시 197키 삭제, 근본 수정 빌더 진행 중 |
| 다음 착수 | 4 절 워커 회수·리뷰 -> 묶음 5 -> 측정 직전 rag:* 캐시 삭제 -> v1·v2 재측정 |

---

## 1. 묶음 4 (`1f8f2331`)

통합 브랜치 `kwanbum217/chat-bundle-4`(`5a7503c4`, refs/backup/chat-bundle-4-20261026)에 아래 순서로 `--no-ff` 병합했다. 매 병합 결과에서 전량 시험을 돌려 통과할 때만 커밋했다(최종 9,455 passed). coordinator Capsule `coord_chat-bundle-4-union-20261026`, strict 게이트 pass, premerge 기록 후 main 병합. source_commit 은 병합 커밋 안에서 `f35122be` 로 갱신했다.

| 순서 | 브랜치 | 커밋 | 내용 | 충돌 |
| --- | --- | --- | --- | --- |
| 1 | chat-period-compare | `ab515254` | 기간·분류 비교, 띄어 쓴 지난 달, 미해석 기관 후보, 광역 별칭 | query_planning 4구간, 양쪽 결합 |
| 2 | chat-trend-series | `45ce235a` | 낙찰률 추이 표 직접 응답 | 없음 |
| 3 | chat-winner-variant | `203a2cef` | 업체 지점 상호 건수 안내 | answer_format 2구간, 결합 |
| 4 | chat-count-conditions | `e1f995ec` | 지난 마감·이번 주 마감 창, 기간 없는 공고 질문 30일 창 | 없음 |
| 5 | chat-region-list | `9f5a575f` | 지역 나열 합집합(region_scope_names), 비교 연결어 '및' | query_planning 1구간(함수 추가 양쪽) |
| 6 | chat-max-value | `277fd6bc` | 공고 금액 최댓값 SQL 직접 응답 | 없음 |

모든 브랜치는 독립 리뷰(cmd `z-ai/glm-5.3-flash`) pass, Level 1 게이트 pass 를 거쳤다. 빌더는 cmd `deepseek/deepseek-v4.1-flash`.

---

## 2. 재측정 (`1f8f2331`, 2026-10-26 월요일)

결과 파일: `.cache/chat_measure_v1_20261026_1f8f2331.json`, `.cache/chat_measure_v2_20261026_1f8f2331.json`.

### 2.1 v2 17/20

| 남은 실패 | 원인(조사 `task_d177b21e3c09`) | 처리 |
| --- | --- | --- |
| v2_cpr_01 | 운영 Redis 캐시 오염으로 9·11 출력(실제 211,708 대 171,237) | 6 절, `task_3f815302b315` |
| v2_amt_01 | 공고 목록이 공고번호 중복을 안 빼 고유 4건 | `task_e3f96ac32535` |
| v2_srt_02 | 상위 챗 플래너가 최댓값 질문을 semantic_search_tool 로 보냄(답 값은 정확) | `task_e3f96ac32535` |

조사 보고서: `.orca/capsules/task_chat_v2_residual_probe_20261026/design.md`.

### 2.2 v1 62/70 은 측정 요일 효과다

`_parse_time_window` 의 "이번 주" 달력 주 해석은 `62650ad0` 에도 있었다(코드로 대조). 월요일 아침에는 이번 주 공고가 거의 없어 목록 4건(pub_ann_06, pub_ann_14, pub_res_05, blnd_ann_02)이 0건이 됐고, v1 통계 기대 SQL 일부가 `CURDATE() - INTERVAL N DAY`(N+1일)라 빠지는 날이 평일이면 2% 오차를 넘었다(pub_sta_02, pub_sta_04, pub_sta_05). pub_res_14 는 기관명 속 지역명 오인이다. 셋 다 이번 세션에서 고쳤고 3·4 절 브랜치에 있다.

---

## 3. 검증 완료 미병합 브랜치 (묶음 5 대상)

워크트리는 모두 회수했고 커밋은 브랜치와 `refs/backup/<이름>-20261026` 에 있다. 보고 파일은 주 저장소 `.orca/capsules/` 에 보존했다.

| 브랜치 | 커밋 | 기준 | 내용 | 빌더 / 리뷰 Task |
| --- | --- | --- | --- | --- |
| chat-kb-block-scope | `2f8461bf` | main | KB 색인 블록을 KB 상태 질문에만 | `task_488a7c6a9e45` / `task_eb0e0eb54219` |
| chat-kb-block-confirm | `33f1f024` | `2f8461bf` | 자동화 확인·API 응답 KB 블록 제거 | `task_a0979f0f3c7d` / `task_2173f66c4433` |
| chat-measure-mask | `5b351bc8` | main | 측정기 수치 후보 오염 구간 마스킹(기존 판정 변경 0) | `task_6ccbf38cb482` / `task_45c7bc6ab6a6` |
| chat-unresolved-failclosed | `f88c48fe` | `48eee5a8`(main 조상) | 기간 비교 미해석 기관 카탈로그 대조, fail-closed | `task_a4f1fe35126b` / `task_741fb5e653c9` |
| chat-this-week-window | `7deaea3e` | main | 이번 주 창 오늘 포함 7일, v1 N일 SQL 9건 N-1 | `task_8427f41d275b` / `task_c96cd4c048c9` |
| chat-single-metric-inst | `81408c3c` | `f88c48fe` | 단일 지표 질문의 기관명 속 지역명 오인 수정(서울대학교병원·경기도교육청·기술보증기금) | `task_5575ca5f9b75` / `task_952b6ab685a2` |

`chat-this-week-window` 의 개별 Level 1 게이트는 코디네이터가 결과 확인 전에 워크트리를 지워 끊겼다. 묶음 5 strict 게이트로 대신 검증할 것. `chat-kb-block-confirm` 은 `chat-kb-block-scope` 를 포함하므로 묶음에는 confirm 하나만 병합해도 된다.

---

## 4. 진행 중 워커 2대 (회수 안 됨)

세션 종료 시점에 작업 중이었다. **다음 세션 시작 시 `orca orchestration check --run run_89eeda0fdf77` 로 소진하고 type 을 확인한 뒤 회수할 것**(4.1 절 교훈, question 이면 회수 금지). 단일 지표 리뷰어 `task_952b6ab685a2` 는 인수인계 작성 직후 pass 를 받아 회수했고 그 브랜치는 3 절로 옮겼다.

| Task | 역할 | 워크트리 | 터미널 | 대상 |
| --- | --- | --- | --- | --- |
| `task_3f815302b315` | 빌더 deepseek max | chat-cache-key-dataset | `term_768f819c-32ac-4f08-9e71-8183b6b6a2b6` | 집계 캐시 키에 데이터셋 신원, 기간 비교 상한 반개 구간 |
| `task_e3f96ac32535` | 빌더 deepseek max | chat-list-dedupe-route | `term_94f93219-5c38-4450-a0db-b90108679816` | 공고 목록 공고번호 중복 제거, 최댓값 질문 bid_query_tool 라우팅 |

- 리뷰어(GLM)는 라우터 비등록이라 비감독 경로(`orca_cmd_launch.py --role reviewer` 터미널 + `orchestration dispatch --return-preamble` + 고유 이름 `preamble_<task>_<dispatch>_<nonce>.txt`)로 띄웠다. 회수는 `orca_taskctl.py release-worker --dispatch <id> --terminal <h> && orca terminal close --terminal <h>`.
- 두 빌더의 리뷰 Intent 는 아직 없다. 빌더 Intent(`.orca/intents/chat_cache_key_dataset_20261026.yaml`, `chat_list_dedupe_extreme_route_20261026.yaml`)의 review_checklist 를 그대로 쓰고, 리뷰 Intent ground_truth 에 반드시 캐시 우회 문장(6 절)을 넣을 것.
- dispatch ID 는 `orca orchestration dispatch-show --task <id> --json` 으로 얻는다.

---

## 5. 사용자 결정 (2026-10-26)

| # | 결정 | 반영 |
| --- | --- | --- |
| 1 | "이번 주 마감" 창은 오늘~7일 뒤 | `e1f995ec`(main) |
| 2 | 기간 없는 공고 건수·최댓값·금액 정렬 목록 기본 창은 최근 30일, 낙찰 통계·추이는 5년 유지 | `e1f995ec`, `277fd6bc`(main) |
| 3 | KB 색인 상태 블록은 명시적 KB 상태 질문에만, 응답 JSON kb_status 필드는 유지 | `2f8461bf`, `33f1f024`(미병합) |
| 4 | 마감이 아닌 "이번 주" 목록도 최근 7일(오늘 포함) | `7deaea3e`(미병합) |
| 5 | N일 창 경계는 오늘 포함 N일, v1 기대 SQL 을 INTERVAL N-1 로 | `7deaea3e`(미병합) |

코디네이터 설계 판단(사용자에게 고지함): 지역만 나열한 질문은 합집합 한 숫자로 답하고 지역별 표는 "비교" 를 붙일 때만 낸다. 미해석 기관은 전체 값 대신 안내로 끝낸다(fail-closed).

---

## 6. 사고: 운영 Redis 집계 캐시 오염

- 증상: v2_cpr_01 이 9건 대 11건으로 답함.
- 원인: `_stmt_cache_key`(src/rag/structured_data.py 약 1093행)가 리터럴 SQL 문자열만 해시한다. 리뷰·조사 워커가 "SQLite 픽스처로 직접 센다" 지시에 따라 `uv run python -c` 로 `retrieve_structured_data` 를 부르면, pytest 격리 픽스처 밖이라 운영 Redis(localhost:6379/0)에 소형 값을 남긴다. pytest 는 `tests/conftest.py` `_isolate_process_cache` 로 격리돼 원인이 아니다.
- 조치: 2026-10-26 코디네이터가 `rag:top:` 101, `rag:agg:` 72, `rag:rows:` 24 키만 삭제(다른 키 11개 유지). 근본 수정은 `task_3f815302b315`.
- **근본 수정 병합 전 규칙**: (1) 리뷰·조사 Intent 에 "직접 확인 스크립트 첫 줄에서 `from src.app.core.cache import cache; cache._conn._client = None; cache._conn._next_attempt_at = float('inf'); cache._local = {}`" 를 넣는다. (2) 측정 직전 `docker compose exec -T redis redis-cli --scan --pattern 'rag:*'` 로 나온 rag:top·agg·rows·inst 키를 지운다.

---

## 7. 다음 세션 절차

1. `docker compose ps`(5개 running 확인, 이 세션은 Docker 를 내리지 않았다), `gh run list --branch main --limit 1`.
2. 4 절 빌더 2대: 메시지 소진, type 확인, worker_done 이면 다이제스트(`summarize_worker_done.py`)·Level 1 게이트·회수. 각각 리뷰어(GLM)를 띄운다.
3. 3 절 6개 + 4 절 통과분으로 묶음 5 통합 브랜치를 만든다. 순서 제안: kb-block-confirm(scope 포함) -> measure-mask -> this-week-window -> unresolved-failclosed -> single-metric-inst(`f88c48fe` 기반) -> cache-key-dataset -> list-dedupe-route. 매 병합 결과 전량 시험을 종료 코드로 막는다. coordinator-capsule 범위는 합집합으로 새 slug.
4. strict 게이트 `--record-evidence`, 통합 워크트리에서 `premerge_full_suite_gate.py --record`, main 병합 커밋 안에서 source_commit 갱신, push, CI 확인, `docker compose restart app`.
5. 측정 직전 rag:* 캐시 삭제(6 절) 후 v1·v2 재측정. 측정 중 main 동결. 기대: v1 70/70 근접, v2 20/20 근접.

---

## 8. 이 세션 운영 교훈

| 교훈 | 내용 |
| --- | --- |
| 워크트리 회수 시점 | 묶음 병합 방식이면 main 병합을 기다리지 말고 리뷰 pass 시점에 refs/backup 고정 후 제거(사용자 지적). 단 그 워크트리에서 도는 게이트가 끝났는지 먼저 본다 |
| 배경 대기 재무장 | 배치 ack 뒤 `check --wait` 를 다시 걸지 않아 완료 2건을 늦게 받았다. ack 와 재무장을 한 응답에 묶는다 |
| 고정 preamble 거부 | cmd 런처는 `.orca/preamble.txt` 를 거부한다. 고유 이름으로 써야 하고, 실패한 시도가 남긴 빈 preamble 파일도 다중 후보로 거부된다 |
| 진단은 근거로 | Intent 에 "금액 조건 누락" 으로 적었으나 실제 원인은 5년 기본 창이었다. 빌더가 사실 불일치 조항으로 바로잡았다 |
| 측정 요일 | 일요일 측정은 "이번 주"·N일 경계 결함을 숨긴다. 평일 측정을 기준으로 삼는다 |

---

## 9. 갱신: 묶음 5 병합과 재측정 (2026-10-26 오후)

### 9.1 묶음 5 (`27c33a67`)

통합 브랜치 `kwanbum217/chat-bundle-5`(`c1950eeb`, refs/backup/chat-bundle-5-20261026)에 7개 브랜치를 차례로 병합했고, 매 병합 결과 전량 시험을 통과했다(최종 9,534 passed). coordinator Capsule `coord_chat-bundle-5-20261026`, strict 게이트 pass, premerge 기록, main 병합 커밋 안에서 source_commit 갱신, 원격 반영.

| 순서 | 브랜치 | 커밋 | 내용 | 리뷰 |
| --- | --- | --- | --- | --- |
| 1 | chat-kb-block-confirm | `33f1f024`(`2f8461bf` 포함) | KB 색인 블록을 KB 상태 질문에만, 자동화 응답 포함 | `task_eb0e0eb54219`, `task_2173f66c4433` pass |
| 2 | chat-measure-mask | `5b351bc8` | 측정기 수치 후보 오염 구간 마스킹 | `task_45c7bc6ab6a6` pass |
| 3 | chat-this-week-window | `7deaea3e` | 이번 주 창 오늘 포함 7일, v1 N일 SQL 9건 | `task_c96cd4c048c9` pass |
| 4 | chat-single-metric-inst | `81408c3c`(`f88c48fe` 포함) | 단일 지표 기관 해석, 미해석 기관 fail-closed | `task_952b6ab685a2`, `task_741fb5e653c9` pass |
| 5 | chat-cache-key-dataset | `a0b46b62` | 집계 캐시 키에 데이터셋 신원, 기간 비교 반개 구간 | `task_88abb337e666` pass |
| 6 | chat-list-dedupe-route | `b4b7bdea` | 공고 목록 공고번호 중복 제거, 최댓값 질문 bid_query_tool | `task_1e5d762ce9e5` pass |

6 절 캐시 오염의 근본 수정(`a0b46b62`)이 main 에 들어갔다. 이후 시험·시드 DB 값은 다른 키를 쓴다. 측정 직전 rag:* 삭제는 이제 필수가 아니지만 첫 측정은 지운 상태로 했다(0키).

### 9.2 재측정 (`27c33a67`, 월요일)

결과 파일: `.cache/chat_measure_v1_20261026_27c33a67.json`, `.cache/chat_measure_v2_20261026_27c33a67.json`.

| 세트 | `62650ad0`(일) | `1f8f2331`(월) | `27c33a67`(월) |
| --- | ---: | ---: | ---: |
| v1 | 70/70 | 62/70 | **67/70** |
| v2 | 12/20 | 17/20 | **19/20** |

| 남은 실패 | 원인 | 처리 |
| --- | --- | --- |
| v1 pub_sta_04 '최근 7일 동안 올라온 공고 총 몇 건' | **회귀.** 관형형 '올라온' 이 기관 후보로 잡혀 미해석 안내(묶음 5 의 `81408c3c` 후보 규칙) | `task_beb97106b674` 진행 중 |
| v2 v2_dln_02 '내일 마감인 공고 몇 건' | 같은 회귀. 서술격 '마감인' 이 기관 후보 | 같은 Task 에 추가 지시 전송 |
| v1 pub_res_14 '{기관}의 최근 60일 용역 평균 낙찰률' | 세부 행정구역 기관(서울특별시 ○○구)이 '서울' 로 넓어짐 | 미착수. 실사용 조사 P2 와 같은 결함 |
| v1 blnd_ann_04 '부산 쪽 최근 공고 5개' | 기대 4건 대 답 5건. 원인 미조사 | 미착수 |

### 9.3 진행 중·대기 (2026-10-26 오후, 사용자 자리 비움 중 자율 진행)

| Task | 역할 | 워크트리 | 상태 |
| --- | --- | --- | --- |
| `task_beb97106b674` | 빌더 deepseek max | chat-candidate-verb | 관형형·수량어·서술격 기관 후보 회귀 수정. **다음 묶음 최우선** |
| `task_862cee9d590b` | 빌더 deepseek high | chat-bid-no-order | 차수 접미사 공고번호(`R26BK...-001`)를 공고번호+차수 단건 조회 |
| `task_c85d850e9801` | 조사 deepseek high | chat-inst-alias-probe | 기관 약칭 사전(도로공사->한국도로공사 등)과 분야어 판정 규칙. 사용자 결정용 |
| `task_08abb599ec4c` | 빌더(완료, 회수됨) | chat-half-open-bounds | `0c2ea56c` 기간 상한 반개 구간 통일. **리뷰 미착수**, 게이트 실행 중 |

완료된 조사 보고서(주 저장소 `.orca/capsules/` 보존):

| 조사 | 보고서 | 요지 |
| --- | --- | --- |
| 실사용 질문 발굴 `task_85d85a2d6e15` | `task_chat_real_query_mining_20261026/design.md`, `v3_draft.json`(25문항) | 고유 질문 412개 중 신규 14유형. P1: 축별 집계('수요기관별 낙찰 금액 상위')·규정 지식이 벡터로 샘, 차수 접미사 공고번호. P2: 기관+분야 목록, 빠른 실행 명령(#공고추천), 세부 행정구역, 미보유 조건, 제목 낱말 건수 |
| 분야어 오탐 `task_7fca2a7c4147` | `task_chat_field_word_fp_probe_20261026/design.md` | '도로공사·전기공사·통신공사' 가 부분 일치 기관으로 조용히 좁혀지고, '학교 급식 공고 몇 건' 은 전체 508,851행. 권고: 정확 일치 카탈로그로만 기관 판정, 나머지 '<분야>공사' 는 공고명 키워드 |

### 9.4 사용자 결정 대기

| 결정 | 근거 | 권고 |
| --- | --- | --- |
| '도로공사' 처럼 기관 약칭이면서 공사 종류로도 읽히는 낱말을 어떻게 다룰지 | 분야어 조사, 약칭 조사(`task_c85d850e9801` 완료 후 보고서) | 약칭 조사 결과를 보고 결정. 분야어 키워드 전환 빌더는 이 결정 뒤 |

### 9.5 다음 절차

1. 진행 중 Task 완료 처리(회수, 게이트, GLM 리뷰). 반개 구간 `0c2ea56c` 리뷰를 띄운다.
2. 회귀 수정 `task_beb97106b674` 가 pass 하면 반개 구간·차수 공고번호와 묶음 6 으로 병합하고 v1·v2 를 재측정한다. 기대: v1 68/70 이상, v2 20/20.
3. 실사용 조사 P1 축별 집계·동향 라우팅, P2 세부 행정구역(pub_res_14), blnd_ann_04 조사를 이어서 띄운다.
4. v3 초안은 knowledge 카테고리 확장이 필요해 dry-run 5건 오류 상태다. 측정기 확장과 v3 확정은 사용자 확인 뒤.

### 9.6 교훈

| 교훈 | 내용 |
| --- | --- |
| 후보 규칙 리뷰 반례 | 접미사 무관 후보 규칙을 넣을 때 리뷰 반례에 관형형(올라온, 등록된)·서술격(마감인)을 넣지 않아 회귀가 통과했다. 기관 후보를 넓히는 Intent 에는 관형형·수량어 반례 20개를 필수로 넣는다 |
| safe_dump Intent | yaml.safe_dump 로 쓴 Intent 는 목록이 들여쓰기되지 않아 확장기가 review_checklist 를 못 읽고, 다시 읽으면 yes 가 True 로 바뀐다. 기존 Intent 와 같은 손 형식(들여쓴 목록, defect_when: yes)으로 쓴다 |
