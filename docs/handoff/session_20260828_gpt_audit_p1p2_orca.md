# 인수인계: 2026-08-28 GPT 감사 P1/P2 보완 (Orca Run run_94b40787bca0)

> **작성일**: 2026-08-28
> **Run**: `run_94b40787bca0`
> **코디네이터**: Claude Opus 5
> **워커**: Antigravity 4대(`gemini-3.7-flash-high` 2, `claude-sonnet-4-6` 1, `gemini-3.7-flash-medium` 1), Codex `gpt-5.6-terra` 1대
> **시작 HEAD**: `da7287c` / **종료 HEAD**: `a0b767c`
> **결과**: Task 7건 전부 병합. 통합 전량 **2537 passed**, CI 7개 job success

---

## 1. 이번 세션이 닫은 것

GPT 감사가 남긴 P1/P2 다섯 건을 전부 종결하고, 그 과정에서 드러난 게이트 결함과
조사 보고서의 권장안까지 같은 세션에서 이어 닫았습니다(8장). Task 는 모두 7건입니다.

| 감사 항목 | Task | 브랜치 | 상태 |
| --- | --- | --- | --- |
| P1 auto-approve 감시기 수명주기 + git 승인 경계 | `task_2af7054896d0` | `t1-approve-lifecycle` | **병합** |
| P2 verification 결과 동일성 게이트 | `task_49b8bc065322` | `t2-verif-identity` | **병합** |
| P2 `segment_metrics` REST 직렬화 | `task_dd956f60809d` | `t3-segment-rest` | **병합** |
| P2 CPU utilization 측정 방식 명기 | `task_9ac5a04f4eb1` | `t4-cpu-util` | **병합** |
| P1 conditional vector bypass 설계 조사 | `task_5c9b902db68f` | `t5-bypass-survey` | **병합** |

워크트리 7개, 작업 브랜치 10개를 모두 반납·삭제했습니다. 남은 워크트리는 주 저장소 하나입니다.

**RAG 32문항 x 3회 정본 재측정은 하지 않았습니다.** 4장을 보십시오. T7 이 검색 경로를 바꿨으므로 이 측정은 이제 품질 회귀 판정까지 겸합니다(8.2, 9장).

---

## 2. 코디네이터 검증에서 잡아낸 결함 두 건

**워커 보고가 통과여도 병합하기 전에 직접 돌려야 한다는 사례가 이번에 두 번 나왔습니다.**

### 2.1 T2 를 그대로 병합했으면 이후 모든 Task 가 게이트에서 막혔습니다

건수 대조가 **보고서에 없는 범주를 전부 0 으로 간주**해서, warning 건수를
적지 않은 **정직한 보고가 실패**했습니다. T1 이 실제로 쓴 형식이 그대로 걸립니다.

| 보고서 | 실제 | 원래 판정 |
| --- | --- | --- |
| `2495 passed, 6 skipped, 3 deselected` | 같은 값 + `306 warnings` | **FAIL** (warning: 보고=0, 실제=306) |

수정 내용입니다. `_COUNT_COMPARE_IGNORED = {"warning"}` 로 warning 을 대조에서
빼고, 보고서가 적지 않은 범주는 `_COUNT_OMISSION_CRITICAL = {"failed", "errors"}`
만 위반으로 봅니다. 실패와 에러는 exit code 로도 잡히므로 이중 방어입니다.
회귀 테스트 3건(`warning` 생략, `skipped` 생략, 보고된 warning 수치 차이)을
함께 넣었습니다. 위조 탐지(43 passed 를 9999 passed 로 보고)는 그대로 작동합니다.

### 2.2 T5 병합 후 통합 테스트 3건 실패

두 원인이 겹쳐 있었습니다.

| 실패 | 원인 |
| --- | --- |
| `test_validate_doc_links::test_cli_execution` | `docs/analysis/task_5c9b902db68f.md:4` 의 링크가 문서 기준 상대 경로여야 하는데 저장소 루트 기준으로 적혀 깨졌습니다 |
| `test_validate_agent_rules::...within_tolerance` | `CURRENT_STATE.md` 의 `source_commit` 이 HEAD 대비 14 커밋 뒤처져 신선도 게이트에 걸렸습니다 |

**코디네이터가 T5 병합 전에 `validate_doc_links.py` 를 돌리지 않아 놓쳤습니다.**
`validate_agent_rules.py` 만으로는 링크 정합성을 잡지 못합니다. 문서를 만드는
Task 는 병합 전에 두 검증을 모두 돌리십시오.

---

## 3. Level 1 게이트의 구조적 결함 (T6 에서 해소, 8.1 절)

**`orca_taskctl.py finalize` 의 verification 재실행 타임아웃 기본값 30초는 이
저장소의 전량 테스트를 통과시킬 수 없습니다.** 전량 pytest 는 63~117초가 걸립니다.

T1 의 게이트 6 이 이 사유로 형식상 실패했습니다.

```
"violations": ["재실행 타임아웃 (30초): 'uv run pytest tests/ -q -m 'not data_assets''"]
```

리뷰어는 결함 0건 `pass` 였고, 코디네이터가 같은 명령을 직접 재실행해
`2495 passed, 6 skipped, 3 deselected in 67.28s` 를 확인한 뒤 병합했습니다.

**전량 pytest 를 검증 명령으로 요구하면서 30초에 자르면 앞으로 모든 Task 가
같은 사유로 게이트 6 을 실패합니다.** 2.1 의 건수 대조 게이트가 이제 붙었으므로,
타임아웃으로 재실행이 아예 안 되면 그 게이트도 함께 무력화됩니다. 보안을 올려
놓고 실효를 잃는 상태입니다.

**이 결함은 같은 세션의 T6 에서 해소했습니다. 8.1 절을 보십시오.**

---

## 4. RAG 정본 측정을 하지 않은 이유

GPT 감사 1순위는 e2b 32문항 x 3회 전량 재측정입니다. 이번 세션에서 하지
않았습니다.

그 측정의 전제는 **조용한 기계**입니다. 이번 세션에는 워커 5대, Docker 스택
5개 컨테이너, Vite 개발 서버, 사용자의 프론트·백엔드 확인이 같은 기계에서
동시에 돌았습니다. 여기서 재면 이전 세션과 똑같이 "부하가 섞여 상대 비교로만
읽어야 하는" 수치가 나오고 정본이 되지 못합니다.

**다음 세션의 첫 작업으로 두십시오.** 절차는
[`session_20260828_gpt_audit_followup_orca.md`](session_20260828_gpt_audit_followup_orca.md)
5절을 따릅니다. 이번에 T5 가 만든
[`conditional_vector_bypass_survey_20260828.md`](../analysis/conditional_vector_bypass_survey_20260828.md)
가 측정 대상 문항을 유형별로 분류해 두었으므로 함께 보십시오.

---

## 5. 이번에 들어간 변경의 요지

| 영역 | 무엇이 달라졌는가 |
| --- | --- |
| 자동 승인 감시기 | 터미널별 PID 레지스트리로 단일 인스턴스 보장. 감시 대상 소진 시 자기 종료. finalize 시 명시적 종료 |
| 자동 승인 경계 | git 전역 옵션(`-c`, `--exec-path`, `--git-dir`, `--work-tree` 등)이 붙으면 서브커맨드와 무관하게 hold. 서브커맨드별 허용 옵션 화이트리스트. pytest 를 읽기 명령이 아닌 코드 실행 검증 분류로 분리 |
| worker_done 게이트 | pass/fail 진위 게이트에서 **결과 동일성 게이트**로 승격. pytest 요약 건수 파싱 후 대조. 명시적 `exit_code`/`passed` 필드 우선. `stdout_digest` 기록(이번엔 판정 기준 아님) |
| `segment_metrics` | `AnswerBundle` 정식 Pydantic 필드로 승격. 동적 property `setattr` 우회 제거. 비스트리밍 REST `/api/v1/chatbot/query` 에 플래그 상태에 따라 노출 |
| CPU utilization | 방식 식별자(`proc_stat_delta` / `ps_process_sum` / `unsupported`)와 `cpu_utilization_probe_ms` 를 리포트에 기록. 실패 경로에서도 방식이 남음. 플랫폼 간 절대값 비교 금지를 문서화 |

### 5.1 남은 작은 과제

`cpu_utilization_probe_ms` 는 Linux 경로에서 의도적 sleep(기본 0.05초)을
포함하므로 macOS 의 `ps` 호출 비용과 물리적 의미가 다릅니다. 같은 방식끼리만
비교한다는 규칙이 문서에 있으므로 당장 문제는 아니지만, 관측 부하만 따로 보려면
sleep 을 제외한 순수 관측 시간을 별도 키로 두는 편이 낫습니다.

---

## 6. 워커 운용에서 새로 확인한 것

| 사실 | 조치 |
| --- | --- |
| OpenCode Zen `nemotron-3-ultra-free` 가 `[502] Upstream error from Nvidia` 로 5회 연속 실패 | 모델 능력이 아니라 업스트림 장애. 재시도로 회복되지 않아 워커를 교체했습니다 |
| `opencode` 가 `postinstall script was not run` 으로 즉시 죽음 | `cd /opt/homebrew/lib/node_modules/opencode-ai && node postinstall.mjs` |
| `minimax-m3` 는 유료 풀 `opencode-go/` 에만 있고 세션 쿠키 미설정 | 무료 풀 대안이 아닙니다 |
| `dispatch` 의 `agent_prompt_stalled` 가 5회 전부 오탐 | 터미널을 읽으면 지시가 정상 도달해 있었습니다 |
| Antigravity 워커가 `cat << 'EOF' > file` 로 문서를 쓰면 감시기가 보류 | 리다이렉션은 화이트리스트 밖입니다. 문서 작성 Task 는 Capsule 에 편집 도구 사용을 명시하십시오 |
| `orca terminal destroy` 는 없습니다 | `orca terminal close --terminal <handle> --tab` |
| `worker-start` 에 `--repo` 를 주면 기존 워크트리에서 거부됩니다 | 생성 전용 플래그입니다. 기존 워크트리에는 `--worktree path:<경로>` 만 줍니다 |

### 6.1 워커에게 남의 실패를 자기 실패로 넘기지 마십시오

T4 워크트리가 2.2 수정 **이전**의 main 에서 갈라져 나와, 워커가 돌린 전량
테스트에 그 3건 실패가 그대로 나왔습니다. 워커가 이를 자기 잘못으로 오해하면
허용 범위 밖 문서를 고쳐 범위 이탈이 됩니다.

코디네이터가 원인과 함께 "고치지 말 것, 검증을 이 Task 범위로 좁힐 것" 을
지시했고 워커가 수용했습니다. 병합 판정은 **T4 브랜치에 main 을 먼저 병합해
같은 기준으로 맞춘 뒤** 전량 재실행(`2518 passed`, 실패 0)으로 했습니다.

기준이 다른 상태의 실패를 병합 판정 근거로 쓰지 마십시오.

---

## 7. 세션 중 기동했던 것 (종료 시 전부 내렸습니다)

세션 중 사용자의 프론트·백엔드 확인을 위해 다음을 띄웠고, 세션 종료 시
10장 절차로 전부 내렸습니다.

| 대상 | 주소 | 기동 방법 |
| --- | --- | --- |
| 백엔드 `app` | http://127.0.0.1:8000 | `docker compose up --build -d`. 루트는 `/accounts/login/?next=/` 리다이렉트 |
| Swagger | http://127.0.0.1:8000/docs | 위와 동일 |
| 프론트엔드 (Vite dev) | http://localhost:5173 | compose 밖. `make dev-fe` |
| `db` / `redis` / `meilisearch` | 3306 / 6379 / 7700 | compose |

**Redis 를 내릴 때는 `SHUTDOWN NOSAVE` 를 쓰십시오.** `dump.rdb` 재생성을 막습니다.

---

## 8. 2차 투입 (T6, T7) — 같은 세션에서 이어 처리

1차 5건을 병합·푸시하고 CI green 을 확인한 뒤, 3장의 게이트 결함과 T5 권장안을
같은 세션에서 이어 닫았습니다.

| Task | 내용 | 워커 | 병합 |
| --- | --- | --- | --- |
| `task_ea8ae09336e5` | verification 재실행 타임아웃을 명령 종류별로 분리 | Antigravity `gemini-3.7-flash-medium` | `c7fc0dd` |
| `task_7ba76bc4cb71` | conditional vector bypass 구현 | Antigravity `gemini-3.7-flash-high` | `07bc710` |

### 8.1 T6 — 3장의 게이트 교착 해소

| 명령 종류 | 적용 타임아웃 |
| --- | --- |
| pytest 계열 | `DEFAULT_VERIFY_PYTEST_TIMEOUT = 900` |
| `validate_agent_rules` 계열 | `DEFAULT_VERIFY_VALIDATE_TIMEOUT = 30` |
| 기타 미분류 | `DEFAULT_VERIFY_TIMEOUT = 30` |

**타임아웃은 여전히 fail-closed 입니다.** 타임아웃이 나면 violations 에 들어가
게이트가 실패합니다. 이 Task 는 타임아웃을 통과로 바꾼 것이 아니라 정상 소요
시간에 걸리지 않도록 값을 맞춘 것입니다.

900 을 `orca_level1_gate.py` 에서 임포트하지 않고 `orca_contract.py` 에 상수로
중복 정의했습니다. `level1_gate` 가 `contract` 를 임포트하므로 역방향 임포트는
순환이 됩니다. 근거 주석을 남긴 중복이 옳은 선택입니다. **코디네이터가 작성한
review_checklist 의 `magic_number_duplicated` 항목이 이 점에서 틀렸습니다.**

### 8.2 T7 — conditional vector bypass

실행 순서가 `SQL -> Lexical -> Vector` 로 바뀌었습니다. 정확 제목 적중 시
`vector_docs` 가 채워져 `retrieve_semantic_context` 호출이 생략됩니다.

폴백은 코드로 확인했습니다. 적중 0건, `plan.use_lexical` 거짓, Meilisearch 장애
어느 경우에도 `if plan.use_vector and not vector_docs:` 가 참이 되어 기존 후보 30
조회와 `_rerank_by_exact_title` 재순위가 그대로 동작합니다. `vector_filter_provenance`
와 `vector_hints` 는 블록 앞에서 초기화되어 건너뛴 요청에 오염되지 않습니다.
회귀 테스트 6건을 넣었습니다.

**동작이 실제로 달라진 변경입니다.** 정확 제목 적중 시 이전에는 lexical 결과에
vector 문서를 `target_k` 까지 채웠으나, 이제는 lexical 결과만 반환합니다. 설계
의도대로이고 T5 보고서 3장이 q01~q24 를 단일 공고 사실 조회로 분류한 근거가
있지만, **품질 회귀 여부는 32문항 실측으로만 확인됩니다. 테스트 통과는 품질
보증이 아닙니다.**

레이턴시 개선 수치는 만들지 않았습니다. Capsule 에 금지 조항을 두었고 워커가
지켰습니다.

---

## 9. 다음 착수 순위

| 순위 | 작업 | 비고 |
| --- | --- | --- |
| 1 | 조용한 기계에서 e2b 32문항 x 3회 전량 재측정 | 4장. **T7 품질 회귀 판정을 겸합니다** |
| 2 | 구간 계측으로 q03 잔여 41.9초 분해 | REST 노출까지 열렸습니다 |
| 3 | `benchmark_rag_segments.py` 규약 레이턴시 재측정 | G3 판정 정본 |
| 4 | Servc 3,589 OOS 현 Champion 고정 평가 | 재학습 게이트 3,098 을 491 초과 |
| 5 | Windows Docker Desktop 실기 | 장비 확보 시. G2 완전 PASS 조건 |

**1 순위의 성격이 이번 세션으로 바뀌었습니다.** 이전에는 레이턴시 정본 갱신만이
목적이었으나, 이제 T7 이 검색 경로를 바꿨으므로 **품질(numeric, evidence, refusal)
회귀 여부 판정이 함께 걸려 있습니다.** 품질이 떨어지면 T7 을 되돌리거나 조건을
좁혀야 합니다. 측정 전에는 T7 을 완료로 선언하지 마십시오.

측정 전 준비입니다.

1. Docker 스택과 프론트엔드 개발 서버를 내립니다 (10장).
2. Orca 워커를 전부 종료합니다.
3. 저장소를 동결합니다. 측정 중 병합하지 않습니다.
4. `uv run python scripts/measure_llm_quality.py --model-label e2b --expected-model <값> --repetitions 3 --output <경로>`
5. `LATENCY_SEGMENT_LOGGING` 을 켜고 구간 계측을 함께 수집합니다.

---

## 10. 세션 종료 시 정리 절차

컴퓨터를 끄기 전에 다음을 수행합니다.

```bash
docker compose exec redis redis-cli SHUTDOWN NOSAVE   # dump.rdb 재생성 방지
docker compose down
```

프론트엔드 개발 서버(`npm run dev`, 포트 5173)는 별도 프로세스이므로 함께
종료합니다. Orca 터미널은 `orca terminal close --terminal <handle> --tab` 으로
닫습니다.

**Redis 를 그냥 내리면 `dump.rdb` 가 다시 생깁니다.** 반드시 `SHUTDOWN NOSAVE`
를 먼저 보내십시오.

---

## 11. 푸시 상태

1차 5건은 `da7287c..185ac1e`, 2차 2건은 `185ac1e..a0b767c` 로 `origin/main` 에
푸시 완료했습니다. 두 푸시 모두 GitHub Actions 7개 job 전부 success 입니다
(run `33154033954`, `33157232612`).
