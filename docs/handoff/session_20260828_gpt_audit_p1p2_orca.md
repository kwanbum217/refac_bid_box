# 인수인계: 2026-08-28 GPT 감사 P1/P2 보완 (Orca Run run_94b40787bca0)

> **작성일**: 2026-08-28
> **Run**: `run_94b40787bca0`
> **코디네이터**: Claude Opus 5
> **워커**: Antigravity 4대(`gemini-3.7-flash-high` 2, `claude-sonnet-4-6` 1, `gemini-3.7-flash-medium` 1), Codex `gpt-5.6-terra` 1대
> **시작 HEAD**: `da7287c` / **종료 HEAD**: `ba45c1f`
> **결과**: Task 5건 전부 병합. 통합 전량 **2521 passed**, `validate_agent_rules.py` **12/12**, `validate_doc_links.py` 통과

---

## 1. 이번 세션이 닫은 것

GPT 감사가 남긴 P1/P2 다섯 건을 전부 종결했습니다.

| 감사 항목 | Task | 브랜치 | 상태 |
| --- | --- | --- | --- |
| P1 auto-approve 감시기 수명주기 + git 승인 경계 | `task_2af7054896d0` | `t1-approve-lifecycle` | **병합** |
| P2 verification 결과 동일성 게이트 | `task_49b8bc065322` | `t2-verif-identity` | **병합** |
| P2 `segment_metrics` REST 직렬화 | `task_dd956f60809d` | `t3-segment-rest` | **병합** |
| P2 CPU utilization 측정 방식 명기 | `task_9ac5a04f4eb1` | `t4-cpu-util` | **병합** |
| P1 conditional vector bypass 설계 조사 | `task_5c9b902db68f` | `t5-bypass-survey` | **병합** |

워크트리 5개, 작업 브랜치 7개를 모두 반납·삭제했습니다. 남은 워크트리는 주 저장소 하나입니다.

**RAG 32문항 x 3회 정본 재측정은 하지 않았습니다.** 4장을 보십시오.

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

## 3. Level 1 게이트의 구조적 결함 (다음 세션이 반드시 고칠 것)

**`orca_taskctl.py finalize` 의 verification 재실행 타임아웃 기본값 30초는 이
저장소의 전량 테스트를 통과시킬 수 없습니다.** 전량 pytest 는 63~117초가 걸립니다.

T1 의 게이트 6 이 이 사유로 형식상 실패했습니다.

```
"violations": ["재실행 타임아웃 (30초): 'uv run pytest tests/ -q -m 'not data_assets''"]
```

리뷰어는 결함 0건 `pass` 였고, 코디네이터가 같은 명령을 직접 재실행해
`2495 passed, 6 skipped, 3 deselected in 67.28s` 를 확인한 뒤 병합했습니다.

**전량 pytest 를 검증 명령으로 요구하면서 30초에 자르면 앞으로 모든 Task 가
같은 사유로 게이트 6 을 실패합니다.** 명령별 타임아웃을 두거나 기본값을
올려야 합니다. 2.1 의 건수 대조 게이트가 이제 붙었으므로, 타임아웃으로 재실행이
아예 안 되면 그 게이트도 무력화됩니다.

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

## 7. 현재 기동 상태

| 대상 | 주소 | 비고 |
| --- | --- | --- |
| 백엔드 `app` | http://127.0.0.1:8000 | healthy. 루트는 `/accounts/login/?next=/` 리다이렉트 |
| Swagger | http://127.0.0.1:8000/docs | |
| 프론트엔드 (Vite dev) | http://localhost:5173 | compose 밖. `make dev-fe` 로 별도 기동 |
| `db` / `redis` / `meilisearch` | 3306 / 6379 / 7700 | 전부 healthy |

**Redis 를 내릴 때는 `SHUTDOWN NOSAVE` 를 쓰십시오.** `dump.rdb` 재생성을 막습니다.

---

## 8. 다음 착수 순위

| 순위 | 작업 | 비고 |
| --- | --- | --- |
| 1 | `finalize` verification 재실행 타임아웃 교정 | 3장. 이걸 두면 이후 모든 Task 의 게이트가 형식 실패합니다 |
| 2 | 조용한 기계에서 e2b 32문항 x 3회 전량 재측정 | 4장 |
| 3 | 구간 계측으로 q03 잔여 41.9초 분해 | 이번에 REST 노출까지 열렸습니다 |
| 4 | `benchmark_rag_segments.py` 규약 레이턴시 재측정 | G3 판정 정본 |
| 5 | conditional vector bypass 구현 | T5 보고서 7장의 권장안 |
| 6 | Servc 3,589 OOS 현 Champion 고정 평가 | 재학습 게이트 3,098 을 491 초과 |
| 7 | Windows Docker Desktop 실기 | 장비 확보 시. G2 완전 PASS 조건 |

---

## 9. 미푸시 상태

`main` 이 `origin/main` 대비 크게 앞서 있습니다. 푸시는 담당자 확인 후 수행합니다.
