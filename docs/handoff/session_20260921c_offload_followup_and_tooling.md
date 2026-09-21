# 세션 인수인계: 2026-09-21 오프로드 후속, 워커 풀·게이트 보강, 백업 갱신

> **작성일**: 2026-09-21
> **작성자**: Claude Opus 5 (Orca 코디네이터)
> **기준 커밋**: `main` `cbc730ce`
> **Orca Run**: `run_0601d2861203` (Task 21건 전부 `completed`, 배달 큐 비움)
> **이어받은 문서**: [`session_20260921b_offload_latency_measurement.md`](session_20260921b_offload_latency_measurement.md)

---

## 1. 한 줄 요약

이전 인수인계 5장의 순서(L4 리뷰·병합, D8 재측정, L3 부록·병합)를 모두 마쳤고, **D8 회귀는 해소**됐습니다. 이어서 Command Code 워커 풀 확장, 리뷰어 보고 경로 결함 수정, 게이트 10 확장, 문서 명령 옵션 오류 4건 정정, 분석 색인 동기화, 원격 잔류 브랜치 정리, 전체 백업 갱신을 병합 9건으로 반영했습니다. **D2 따라잡기 판정 측정만 부하 조건 미충족으로 다음 세션에 넘깁니다.**

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
| 3 | 외부 감사(2026-09-21 Muse 보고서) 잔여 | ML-6 `data/promotion_audit.log` 4.2MB 회전 없음, QA-2 CI 경고 상한 미강제, QA-5 CI MySQL 이미지 다이제스트 미고정, FE-3 동결 React 를 CI 가 매번 빌드. 모두 코드·CI 변경이라 Task 로 등록할 것 |
| 4 | OP-3 주간 재학습 | 09-21 03:00 실행 기록이 없다. worker 컨테이너가 떠 있지 않아 돌지 않은 것이며 "승격 없음" 과 다르다 |
| 5 | D8 잔여 약 1ms | 사용자 결정 사항. 줄이려면 첫 질의에 윈도 조건을 거는 설계 변경이 필요하다 |

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

---

## 8. 자원 상태

| 대상 | 상태 |
| --- | --- |
| Git | `main` clean, 원격 반영 완료. 로컬·원격 작업 브랜치 0건(원격 잔류 8건은 전부 병합 확인 후 삭제) |
| 워크트리 | 이 문서의 `orca-h1` 외 0건 |
| Orca | Run `run_0601d2861203` Task 21건 `completed`, 배달 큐 비움, 워커 터미널 전부 회수, 상시 감시기 종료 |
| Docker | 세션 종료 시 `db`·`redis` 를 `docker compose stop` 으로 정지(볼륨 보존). Docker Desktop 의 MCP 서버 컨테이너 3개(`mcp/github` 등)는 프로젝트와 무관하므로 건드리지 않음 |
| 정리한 잔재 | `.env.bak_20260811`, `.cache/finalize_evidence_*` 3건 (모두 병합·대체 확인 후 삭제) |

---

## 9. 하지 말 것

- 부하 임계를 넘은 측정을 판정 근거로 쓰지 마십시오. 참고 기록으로도 남기지 마십시오.
- 개발 장비의 drift baseline 유실을 `generate_drift_baseline.py` 재생성으로 메우지 마십시오. 스냅샷에서 복원하십시오.
- cmd 풀의 두 새 모델을 병합 실적 없이 `TIER_POLICY` 에 올리지 마십시오.
- CI 결과를 확인하지 않고 다음 병합을 하지 마십시오.
