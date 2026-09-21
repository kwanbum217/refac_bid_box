# 세션 인수인계: 2026-09-21 오프로드 후속, 워커 풀·게이트 보강, 백업 갱신

> **작성일**: 2026-09-21
> **수정일**: 2026-09-21 (W1~W3 웨이브와 테스트 환경 기동 반영, 10장 추가)
> **작성자**: Claude Opus 5 (Orca 코디네이터)
> **기준 커밋**: `main` `15106c89` (최초 작성 시 `cbc730ce`)
> **Orca Run**: `run_0601d2861203` (Task 28건 전부 `completed`, 배달 큐 비움)
> **이어받은 문서**: [`session_20260921b_offload_latency_measurement.md`](session_20260921b_offload_latency_measurement.md)

---

## 1. 한 줄 요약

이전 인수인계 5장의 순서(L4 리뷰·병합, D8 재측정, L3 부록·병합)를 모두 마쳤고, **D8 회귀는 해소**됐습니다. 이어서 Command Code 워커 풀 확장, 리뷰어 보고 경로 결함 수정, 게이트 10 확장, 문서 명령 옵션 오류 4건 정정, 분석 색인 동기화, 원격 잔류 브랜치 정리, 전체 백업 갱신을 병합 9건으로 반영했습니다. 이어서 외부 감사(Muse) 잔여를 W1~W3 웨이브로 처리해 감사 로그 테스트 누출 차단, CI 보강 3건, 문서 종결 4건을 병합했습니다(10장). **D2 따라잡기 판정 측정만 부하 조건 미충족으로 다음 세션에 넘깁니다.** 세션 종료 시점에 사용자 브라우저 테스트용으로 `app` 스택이 기동 중입니다.

---

## 2. 이번 세션 병합 (first-parent)

| 병합 커밋 | 내용 | 검증 |
| --- | --- | --- |
| `9a110ae3` | L4 D8 점진 확대 재작성 + `source_commit` 갱신 | 리뷰 pass, Level 1 11/11, 전량 5,255 |
| `0f5e4ec9` | L3 오프로드 실측 보고서 + D8 재측정 부록 B | 리뷰 pass 2회, Level 1 11/11, 전량 5,254 |
| `ea4800a0` | M1 cmd 풀에 GLM-5.3 Flash, Hy4 Preview 명시 지정 전용 등록, 런처 모델별 effort 검사 | 리뷰 pass, Level 1 11/11, 전량 5,266 |
| `3d181afa` | D1 보고서 부록 A.5 의 `--json` 을 `--output` 으로 정정 | 규칙 21/21, premerge 5,255 |
| `3f7a46bd` | A1 기동 고지의 report_path 를 Capsule, Intent, 역할별 기본값 순으로 | 리뷰 pass, Level 1 11/11, 전량 5,259 |
| `8c9fec4d` | G1 게이트 10 이 저장소 파이썬 스크립트 옵션을 AST 로 검사 + `source_commit` 갱신 | 리뷰 pass, Level 1 11/11, 전량 5,269 |
| `fdda657b` | E1 문서 명령 옵션 오류 2건 정정 | 새 게이트 10 이 수정 전 2건 위반, 수정본 0건 |
| `964b3c84` | X1 분석 색인 누락 28건 추가, 총 422건 | 리뷰가 추가 28행 전부 원문 대조 pass |
| `cbc730ce` | F1 고지 기본 경로를 Windows 에서도 `/` 로 (`as_posix`) | premerge 5,284, CI Run 35570374697 전 잡 성공(windows-latest 포함) |
| `2279476c` | 이 인수인계 문서 최초본 | 규칙 21/21, CI 성공 |
| `a5bd003f` | W3 외부 감사 문서 조치 네 건과 보안 예외 상호 포인터 | 리뷰 pass, Level 1 11/11. **CI lint-and-validate 실패**(10장) |
| `f0df521b` | W1 승격 감사 로그 테스트 격리 + `source_commit` 갱신 | 리뷰 pass, Level 1 11/11, 전량 5,290, CI 성공 |
| `15106c89` | W2 CI MySQL 이미지 다이제스트 고정, 동결 React 조건부 실행, 경고 예산 강제 | 리뷰 pass, Level 1 11/11(actionlint 포함), 전량 5,291, CI 11잡 성공 |

워커 모델: 빌더 Command Code `deepseek/deepseek-v4.1-flash`, 리뷰어 OpenCode `opencode/muse-spark-1.3-contributor-free`. 전부 터미널 부착 비감독 경로이며 회수는 `release-worker` 후 `orca terminal close` 로 했습니다. D1, E1, F1 은 두 줄 이하 수정이라 코디네이터가 직접 작성했습니다.

---

## 3. D8 재측정 확정 결과 (`main` `9a110ae3`)

측정 조건: Docker 는 `db`·`redis` 만 기동, 정규화 load average 20.93%(규약 5.3 안), 버퍼풀 2GB, 공고 5,515,517행. 원시 결과 `data/benchmarks/offload_latency_20260921/home_recent_progressive.json` (sha256 앞 12자리 `1067ccd0f701`). 첫 재측정은 부하 32.93% 로 임계를 넘어 폐기했습니다.

| 시나리오 | 회귀 전 current 최악 | 새 current 최악 | legacy 최악 | SQL current / legacy |
| --- | ---: | ---: | ---: | :---: |
| all | 35.26ms | 2.11ms | 1.89ms | 1 / 1 |
| Cnstwk | 52.02ms | 2.38ms | 1.11ms | 1 / 1 |
| Servc | 33.86ms | 2.04ms | 1.07ms | 1 / 1 |
| Thng | 33.37ms | 2.18ms | 1.08ms | 1 / 1 |
| Frgcpt | 31.19ms | 1.99ms | 1.74ms | 1 / 2 |

선별 결과는 전 시나리오·전 회차에서 legacy 와 같습니다. **회귀는 해소**됐고 예열 1회당 추가 비용은 약 175.74ms 에서 3.81ms 가 됐습니다. 카테고리 네 시나리오의 약 1ms 잔여 차이는 실행 계획으로 원인을 확인했습니다. legacy 는 1일 윈도 조건으로 인덱스 범위 스캔(Servc 10행)이고, 새 구현은 전역 접두 50행을 읽습니다. 설계 계약의 비용이며 결함이 아닙니다. 줄일지는 사용자 결정 사항입니다.

---

## 4. 도구·규칙 변경

| 변경 | 효과 | 남은 것 |
| --- | --- | --- |
| cmd 풀 `cmd-glm-flash`, `cmd-hy4-preview` | 둘 다 `auto_selectable: False`, reviewer 아님. GLM 은 low/high/max, Hy4 는 low/medium/high | 실과제 실적 없음. 자동 배정 승격은 병합 실적이 쌓인 뒤 |
| 런처 effort 검사 | 모델이 받지 않는 등급을 cmd 기동 전에 종료 코드 2 로 거부. 미등록 모델은 default 만 | 짧은 이름(`deepseek-v4.1-flash`)은 미등록으로 판정되어 거부된다. 기동 명령은 전체 ID 를 쓸 것 |
| 고지 report_path | 리뷰 Intent 에 report_path 를 손으로 적지 않아도 `review_done.json` 을 가리킨다 | 없음 |
| 게이트 10 확장 | `uv run python`·`python3`·`python` + `scripts/*.py` 명령의 줄 이음을 합쳐 argparse 옵션과 대조. 셸 연산자·명령 치환 뒤는 제외, 인라인 코드 닫는 백틱은 떼고 검사 | 저장소 전수 조사 위반 5건 중 4건은 정정 완료, 1건은 기존 docker 경로가 테스트 주석 줄을 잡은 오탐(`tests/test_orca_level1_gate.py:1228`) |

GOAT($10) 요금제에서는 저가 모델만 워커 후보로 봅니다. GLM-5.3, Qwen 3.8 Max 0902 는 사용자 결정으로 제외했습니다. 리뷰어 독립성은 CLI 단위 provider 분리를 유지합니다(리뷰어는 OpenCode Muse 무료 경로).

---

## 5. 백업과 드리프트 baseline

| 대상 | 상태 |
| --- | --- |
| 새 스냅샷 | `data/backups/snapshots/snapshot_20260921_061612/` 약 4.96GB. `verify` PASS, `recovery_trusted: True`, `row_count_status: verified` |
| 보존 | 09-11 과 09-21 두 세대를 유지합니다(사용자 결정). 다음 백업 때 가장 오래된 것부터 지웁니다 |
| drift baseline 3종 | 09-15 에 만든 Servc·Cnstwk·Thng baseline 이 09-11 스냅샷에 없어 유일본이었습니다. 새 스냅샷의 파일 6개가 원본과 sha256 전부 일치합니다 |
| 운영 이관 | `docs/ops/ml_registry_production_bootstrap.md` 대로 운영 DB 에서 레짐 이후 구간 baseline 을 재생성하는 것이 설계된 절차입니다. 개발 장비 유실 대비는 스냅샷 복원입니다. 둘은 다른 상황입니다 |

호스트 `mysqldump` 26.7 은 인증 플러그인 오류로 백업이 실패합니다. `MYSQL_CLIENT_CONTAINER=$(docker inspect -f '{{.Name}}' $(docker compose ps -q db) | tr -d /)` 를 주고 실행하십시오.

---

## 6. 다음 세션 할 일

| 순서 | 할 일 | 근거와 주의 |
| --- | --- | --- |
| 1 | **D2 따라잡기 판정 측정** | 설계는 `.orca/capsules/task_9fa87a60df20/findings.md`(주 저장소). 판정 함수만 부르면 실제 수집은 돌지 않는다(`src/tasks/scheduled_tasks.py:1287` 에서만 시작). `AUTOMATION_SCHEDULE_CATCHUP_ENABLED=true` 와 `false` 로 `--targets D2.catchup_check --rounds 3 --repeats 20 --warmup 2 --interval-ms 1` 을 쌍대 실행. 측정 전 쿨다운 키 `bidbox:schedule:catchup_cooldown` 부재와 데이터 갱신 스케줄 켜짐을 기록한다. 결과는 해상도 이하일 가능성이 크며 목적은 "운영 조건에서 수집이 돌지 않는다" 확인이다 |
| 2 | 부하 확인 | 이번 세션 종료 시점에 macOS StorageManagement 프로세스가 CPU 약 120~170% 를 40분 넘게 썼다. 측정 전 정규화 부하 30% 이하를 먼저 확인할 것 |
| 3 | **감사 로그 정리 결정** | `data/promotion_audit.log` 9,245줄 중 9,244줄이 테스트의 `test_model` 기록이고 실제 승격 기록은 `servc_institution_v1` 1건이다. 누출은 `f0df521b` 에서 막았으나 쌓인 기록은 그대로다. 감사 로그라 사용자 결정 전에는 손대지 말 것. 정리한다면 원본을 백업에 보존한 뒤 실제 기록만 남기는 방식을 권한다 |
| 4 | **경고 예산 여유 결정** | CI 경고 예산 잡이 4건(예산 5)으로 통과했다. 로컬은 3건이다. 출처는 `tests/test_evaluation_ui.py` 의 `PytestRemovedIn10Warning` 이며 하나만 늘어도 CI 가 막힌다. 출처를 고칠지 결정할 것 |
| 5 | frontend 건너뛰기 첫 관측 | W2 변경 판정은 `ci.yml` 이 바뀐 푸시에서 frontend 단계를 실행하는 것까지 확인했다. frontend 와 `ci.yml` 이 모두 바뀌지 않은 푸시에서 5단계가 `skipped` 로 나오는지 다음 문서 전용 병합에서 확인할 것 |
| 6 | OP-3 주간 재학습 | 09-21 03:00 실행 기록이 없다. worker 컨테이너가 떠 있지 않아 돌지 않은 것이며 "승격 없음" 과 다르다 |
| 7 | D8 잔여 약 1ms | 사용자 결정 사항. 줄이려면 첫 질의에 윈도 조건을 거는 설계 변경이 필요하다 |

외부 감사(2026-09-21 Muse 보고서)의 조치 항목 ML-6, QA-2, QA-5, FE-3, SEC-1, RAG-1, DOC-1, DOC-2, QA-3, QA-6, SEC-2, SEC-3, GIT-1, GIT-2 는 이번 세션에 처리했습니다. ML-6 은 보고서의 "회전" 이 아니라 원인인 테스트 누출을 막는 것으로 처리했습니다. RAG-3(Meili·DB 건수 야간 대조), BE-1(스테이징 CORS), INF-3(운영 RTO 실측)은 남아 있습니다.

---

## 7. 이번 세션에서 드러난 사실

| 사실 | 조치 |
| --- | --- |
| **CI 를 확인하지 않고 연달아 병합했다.** A1 이후 windows-latest 만 3회 연속 실패했고 로컬 macOS premerge 는 전부 통과했다. 원인은 `str(Path(...).parent)` 의 역슬래시 | F1(`cbc730ce`)에서 `as_posix` 로 수정. 병합 사이마다 `gh run list --branch main --limit 3` 을 볼 것 |
| 규약 5.3 부하 임계를 코디네이터가 잘못 읽었다(35% 를 기준 안으로 판단) | 빌더가 질문으로 잡아 폐기 후 재측정. 임계는 중앙값 30% 이하다 |
| Capsule 의 `verification_commands` 에 `git diff` 를 넣으면 게이트 3 이 허용 목록 위반으로 막는다 | 범위 확인은 게이트 1·2 가 한다. 검증 명령에는 pytest, mypy, validate_agent_rules 류만 넣을 것 |
| Capsule 에 `changed_files` 기준을 적지 않으면 워커가 자기 커밋 파일만 적어 게이트 6 이 막는다 | "`git diff --name-only main...HEAD` 결과 전부" 를 Capsule 에 못 박을 것 |
| 조사 워커를 런처 `--role auto` 로 띄우면 빌더용 커밋 고지가 붙는다 | 커밋 없는 조사는 역할을 명시하고, Capsule 에 커밋 금지를 적을 것 |
| `git merge -F -` 는 지원되지 않는다 | `git merge --no-ff --no-commit` 뒤 `git commit -F -` |
| zsh 는 변수를 공백으로 나누지 않는다 | 여러 인자는 배열(`${(f)...}`)로 넘길 것 |
| `orca worktree create` 는 워크트리마다 빈 셸 창(`Terminal 1`)을 연다 | 워크트리 정리 때 함께 닫을 것. 감시 도구가 "터미널 2개" 로 표시한다 |
| Dispatch 가 띄운 상시 워커 감시기는 워크트리를 지워도 남는다 | 세션 종료 시 `pgrep -fl orca_worker_watch` 로 확인해 종료. 이번 세션 7개 종료 |
| 게이트 1 차 실패의 테스트 건수 불일치는 DB 기동 여부 차이였다 | Docker 가 내려가면 MySQL 통합 테스트 9건이 skip 된다. 같은 조건에서 재실행해 판정할 것 |
| **Intent 를 `yaml.safe_dump` 로 쓰면 Capsule 이 기본값으로 조용히 채워진다.** 목록이 들여쓰기 없이 나와 확장기가 읽지 못했고, W1~W3 Capsule 의 쓰기 범위가 `src/...`, `tests/...`, ground_truth 가 기본 4건, 체크리스트가 빈 목록이 됐다. 종료 코드는 0 이었다 | W3 가 범위 모순을 질문해 드러났다. 두 칸 들여쓰기와 따옴표로 다시 쓰고 `orca_taskctl.py expand --task-id <기존 ID>` 로 같은 ID 에 재생성했다. **create 직후 Capsule 의 쓰기 범위, ground_truth 건수, 체크리스트 id 를 반드시 출력해 대조할 것** |
| **병합 커밋을 만들기 전에 규칙 검증을 돌리면 source_commit 거리가 하나 적게 나온다** | W3 병합 전 검증은 거리 5 로 통과였고 커밋 뒤 6 이 되어 `a5bd003f` CI 가 실패했다. 다음 병합 커밋 안에서 갱신해 복구했다. 거리 판정은 커밋 뒤에 다시 돌릴 것 |
| 다른 세션이 정본 스킬 영수증을 덮어써 Dispatch 가 종료 코드 4 로 거부됐다 | 영수증의 `coordinator_handle` 이 이미 닫힌 터미널이었다. 활성 세션이 없음을 확인하고 `python3 scripts/orca_skill_receipt.py issue` 로 재발급했다. 두 코디네이터가 번갈아 발급하면 서로의 Dispatch 를 막는다 |
| 외부 보고서 수치를 확인 없이 Capsule 에 옮겼다 | 벤치마크 규모 229건·33MB 는 틀렸고 실측은 추적 346개(JSON 315)·약 24MB 였다. W3 가 잡아 문서에 수치를 적지 않았다. ground_truth 에는 실측한 값만 넣을 것 |
| `gh run list --limit 1` 은 최신 실행을 돌려준다는 보장이 없다 | 9월 7일 실행이 맨 위로 나와 병합을 잠시 멈췄다. `--jq 'sort_by(.createdAt)|reverse'` 또는 `--commit <sha>` 로 조회할 것 |
| 리뷰어 Capsule 의 `allowed_write_files` 가 비어 있는 것은 정상이다 | 리뷰어는 `artifact_paths` 의 `review_done.json` 하나만 쓴다 |
| `.github/workflows/` 를 바꾼 브랜치의 게이트는 `workflow_lint` 능력을 요구한다 | `.github/workflows/` 가 바뀌면 `--verify "uv run actionlint"` 를 게이트에 넘길 것 |

---

## 8. 자원 상태

| 대상 | 상태 |
| --- | --- |
| Git | `main` clean, 원격 반영 완료. 로컬·원격 작업 브랜치 0건(원격 잔류 8건은 전부 병합 확인 후 삭제) |
| 워크트리 | 이 문서 보강용 `orca-h2` 외 0건 |
| Orca | Run `run_0601d2861203` Task 28건 `completed`, 배달 큐 비움, 워커 터미널 전부 회수, 상시 감시기 종료(웨이브 전 7개, 웨이브 후 4개) |
| Docker | **사용자 브라우저 테스트용으로 `app`·`db`·`redis`·`meilisearch` 기동 중**(http://localhost:8000). `worker` 는 따라잡기 수집·주간 재학습이 켜져 있어 사용자 결정(A안)으로 띄우지 않았다. 테스트가 끝나면 `docker compose stop` 으로 정지한다(볼륨 보존). Docker Desktop 의 MCP 서버 컨테이너 3개(`mcp/github` 등)는 프로젝트와 무관하므로 건드리지 않음 |
| 알 수 없는 프로세스 | 웨이브 종료 무렵 대화형 셸에서 뜬 `opencode` 프로세스 1개가 있었다. 이 세션이 띄운 것이 아니라 두었다 |
| 정리한 잔재 | `.env.bak_20260811`, `.cache/finalize_evidence_*` 3건 (모두 병합·대체 확인 후 삭제) |

---

## 9. 하지 말 것

- 부하 임계를 넘은 측정을 판정 근거로 쓰지 마십시오. 참고 기록으로도 남기지 마십시오.
- 개발 장비의 drift baseline 유실을 `generate_drift_baseline.py` 재생성으로 메우지 마십시오. 스냅샷에서 복원하십시오.
- cmd 풀의 두 새 모델을 병합 실적 없이 `TIER_POLICY` 에 올리지 마십시오.
- CI 결과를 확인하지 않고 다음 병합을 하지 마십시오.
- `data/promotion_audit.log` 를 사용자 결정 없이 정리하거나 지우지 마십시오. 감사 기록입니다.
- Intent 를 `yaml.safe_dump` 로 쓰지 마십시오. 쓰더라도 create 직후 Capsule 을 대조하십시오.

---

## 10. W1~W3 웨이브 (외부 감사 잔여)

2026-09-21 Muse Spark 1.3 외부 감사 보고서(기준 커밋 `3f7a46bd`)를 검증한 뒤 조치 항목을 세 워커로 병렬 처리했습니다. 보고서 38개 항목 중 틀린 판정 5건(GIT-2 활성 워크트리 제거 권고, 기동 상태 app·worker, OP-3 "승격 없음", 규칙 17항목, ML-6 원인)을 먼저 걸렀습니다.

| 워커 | Task | 결과 | 검증 |
| --- | --- | --- | --- |
| W1 | `task_d7fb9e792d10` (보고 재작업 `task_234a82a6c0f6`) | `tests/conftest.py` autouse fixture 로 테스트 중 감사 로그 기본 경로를 tmp_path 로 격리. 누출 원인은 `tests/test_promotion_gate.py::test_same_version_repromotion_kill_preserves_serving_set` 의 `monkeypatch.undo()` 와 `scripts/promote_model` 의 import 시점 경로 복사 | 리뷰(`task_0403c20984cc`)가 전량·단독 실행 전후 로그 줄 수 동일을 실측. 첫 보고는 `note` 1,129자로 게이트 6 위반이라 보고서만 재작업 |
| W2 | `task_af4d9cdc3be8` | CI MySQL 이미지 compose 다이제스트 고정, `git diff` fail-open 변경 판정으로 frontend 5단계 조건부 실행, 새 잡 `pytest-warning-budget` 이 경고 5건 초과 시 실패. 새 서드파티 action·의존성 없음 | 리뷰(`task_22fd87a3a5a1`)가 판정 네 경우와 요약 줄 다섯 형태를 재현. CI Run 35574530429 에서 경고 4건 통과, frontend 단계 실행 확인 |
| W3 | `task_c493a0ece580` | nanoid 해소(`d68078a7`) 기록과 chromadb 2026-12-31 재확인 시점, `data/benchmarks/README.md` 보존 정책, `docs/ops/g1_baseline_procedure.md` G1 증적 절차, `pyproject.toml`·`scripts/orca_auto_approve.py` 상호 포인터 주석 | 리뷰(`task_b0ad43eef36a`)가 Makefile 대상·만료일·주석 전용 변경을 원본 대조 |

웨이브 도중 세 Capsule 이 Intent 형식 문제로 기본값이 되어 계약 없이 작업이 시작됐습니다. 코디네이터가 같은 Task ID 로 재생성해 워커에게 다시 읽게 했고, 워커가 이미 만든 테스트 파일 이름을 계약에 맞춰 반영했습니다(7장).
