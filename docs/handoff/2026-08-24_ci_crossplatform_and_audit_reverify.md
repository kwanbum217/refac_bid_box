# 크로스 플랫폼 CI 복구 및 감사 재검증 인수인계

> **작성일**: 2026-08-24 (Asia/Seoul)
> **작성자**: Orca 코디네이터 (Claude Opus 5)
> **기준 브랜치**: `kwanbum217/audit-remediation-integration-896e1d5`
> **원격 CI 브랜치**: `feature/audit-remediation-896e1d5`
> **Orca Run**: `run_a70e06fe0719`
> **상태**: 크로스 플랫폼 CI 결함 3건 수정, 감사 13항목 재검증 병합 완료. 측정 3종 미수행

---

## 1. 이번 세션의 핵심 발견

**통합 브랜치가 도입한 provenance 계층이 크로스 플랫폼 CI 를 깨뜨리고 있었습니다.**

이전 세션은 로컬 macOS 게이트 4종(테스트 1,915건, ruff, 규칙 12/12, compose)만
통과시킨 상태로 종료했고, 원격 CI 는 돌려 보지 않았습니다. 이번 세션에서
`feature/audit-remediation-896e1d5` 로 push 해 실제로 돌린 결과
**Windows 와 macOS 두 job 이 실패**했습니다 (run `32701590510`).

| 실패 job | 실패 테스트 | 원인 |
| --- | --- | --- |
| windows-latest | `test_aggregate_benchmark_metrics_includes_provenance`, `test_aggregate_benchmark_metrics_provenance_keys_match_container_harness` | Windows `os` 모듈에 `getloadavg` 가 없어 `mock.patch("os.getloadavg")` 자체가 `AttributeError` |
| windows-latest | `test_cmd_create_syncs_actual_task_id_to_capsule_and_spec` | `worktree_relative_capsule_path` 가 `str(Path(...))` 를 써서 Windows 에서 역슬래시 경로를 생성 |
| macos-latest | `test_get_docker_version_returns_string` | GitHub macOS 러너에 Docker 가 없어 함수가 규약대로 `"unknown"` 을 반환하는데 테스트가 `"Docker version"` 을 단정 |

`os.fork()` 제거만으로 Windows CI 가 green 이 되리라는 추정은 **틀렸습니다.**
이전 인수인계가 "코드 수정 완료 / 원격 green 미확인" 으로 보수적으로 적어 둔
것이 옳았고, 실제로 다른 원인 3건이 남아 있었습니다.

### 1.1 수정 (`5a57428`)

| 대상 | 수정 |
| --- | --- |
| `tests/test_benchmark_arq_throughput.py` | `patch("os.getloadavg", ..., create=True)` 2곳. 속성이 없는 플랫폼에서도 패치가 성립합니다 |
| `tests/test_benchmark_arq_throughput.py` | Docker 미설치 환경을 허용하도록 `version == "unknown" or "Docker version" in version` 로 완화 |
| `scripts/orca_taskctl.py` | `worktree_relative_capsule_path` 가 `.as_posix()` 로 구분자를 POSIX 로 고정 |

세 번째는 **테스트가 아니라 운영 코드 결함**입니다. Capsule 경로는 YAML 에 적혀
플랫폼을 넘나들며 문자열로 대조되므로 구분자가 갈리면 워커와 게이트가 같은
경로를 다른 값으로 읽습니다.

### 1.1.1 2차 Windows 실패와 추가 수정 (`4d7be51`)

수정 후 재실행(run `32702409191`)에서 macOS 는 green 이 됐으나 **Windows 는 다시
실패**했습니다. 이번에는 원인이 반대쪽이었습니다. 운영 코드를 POSIX 로 고정하자
`str(Path(".orca/..."))` 로 기대값을 만들던 테스트 4건이 Windows 에서 역슬래시
문자열을 기대해 어긋났습니다.

    tests/test_orca_taskctl.py::test_build_capsule_notice_carries_path_contract_and_dispatch_id
    tests/test_orca_taskctl.py::test_build_task_spec_embeds_worktree_relative_capsule_path
    tests/test_orca_taskctl.py::test_capsule_paths_never_leak_main_repo_absolute_path
    tests/test_orca_taskctl.py::test_build_task_spec_truncates_long_objective

기대 문자열을 리터럴 POSIX 경로로 바꿨습니다(`4d7be51`).

### 1.1.2 Windows CI green 확인 (종결)

run `32703096829` (`bd6212c`) 에서 **ubuntu·macOS·windows-latest 전부 green**
입니다. 잔여 과업 "수정 후 원격 Windows CI green 확인" 은 실측으로 종결했습니다.

    success | Test (windows-latest)
    success | Test (macos-latest)
    success | Test (ubuntu-latest)
    success | lint-and-validate
    success | Docker 이미지 빌드 검증

**세 라운드가 필요했습니다.** 한 라운드의 수정이 다음 라운드의 실패를 만들었으므로
(운영 코드를 POSIX 로 고정하자 테스트 기대값이 어긋남), 크로스 플랫폼 수정은
한 번의 CI 통과를 볼 때까지 완료로 선언하지 마십시오.

### 1.2 남은 크로스 플랫폼 위험 (미수정)

`scripts/run_p9_sse_rebaseline.py:55` 는 `sysctl` 실패 시 `os.getloadavg()` 로
떨어지며 Windows 에서 `AttributeError` 를 냅니다. CI 가 실행하지 않는 측정 전용
스크립트라 이번 범위에서 제외했습니다. **Windows 에서 이 스크립트를 돌릴 계획이
생기면 먼저 고쳐야 합니다.**

---

## 2. GPT 외부 감사 13항목 재검증

Orca Task `task_8915e5d1e53f` (워커: OpenCode Zen `mimo-v2.5-free`) 가
항목별로 파일·행 근거를 붙여 판정했고 통합 브랜치에 병합했습니다.
산출물은 [`../analysis/gpt_audit_reverification_20260824.md`](../analysis/gpt_audit_reverification_20260824.md) 입니다.

워커 판정은 **13항목 전부 해소** 이며, 코디네이터가 표본 3건을 직접 대조해
일치를 확인했습니다.

| 표본 | 확인 내용 |
| --- | --- |
| 1번 Compose 모델 override | `docker-compose.yml` 62·114 행 모두 `${OLLAMA_MODEL:-gemma4:e4b}` |
| 6번 partial 실패 exit code | `benchmark_rag_segments.py` 가 `return 2` 4곳, 실패 시 `exit_code = 1` |
| 11번 trust lock fail-closed | `orca_trust_worktree.py` 가 잠금 모듈 부재 시 `RuntimeError` |

**나머지 10항목은 코디네이터가 직접 대조하지 않았습니다.** 워커 보고를 그대로
완결로 읽지 마십시오. 다음 세션이 `main` 병합을 판정할 때 최소한 8·9·12번
(Arq source provenance, 4계층 schema 일치, 경로 containment)은 직접 봐야 합니다.

---

## 3. 미수행 항목과 그 이유

| 항목 | 상태 | 이유 |
| --- | --- | --- |
| Windows CI green 확인 | **완료** | run `32703096829` 에서 windows-latest success |
| Arq Docker synthetic 3회 raw 재측정 | **미수행** | 워커 2대와 CI 폴링이 동시에 도는 오염된 부하에서 측정하면 GPT 가 지적한 규약 위반을 그대로 반복합니다 |
| Ollama 부하 규약 준수 재측정 | **미수행** | 같은 이유. median 30% / max 50% 게이트를 만족하는 조용한 호스트가 필요합니다 |
| 강화된 RAG 하네스 재측정 | **미수행** | 같은 이유. `--expected-llm-model` 지정이 필수입니다 |
| Arq 정식 기준선 캘리브레이션 설계 | **차단** | Orca Task `task_5e354d395d04` (Kimi K2.7 Code) 가 40분간 산출물 0건으로 정체. 미완 |
| Windows Docker Desktop 실기 | 차단 | 장비 부재 |
| `main` 병합 | 미수행 | Windows CI green 확인과 사용자 승인이 선행 조건 |

**측정을 하지 않은 것이 게으름이 아니라 판정입니다.** 오염된 부하에서 낸 숫자를
기준선으로 올리면 이번 감사가 지적한 문제를 되풀이합니다.

---

## 4. 다음 세션 순서

1. Windows CI 는 이미 green 이고 SSOT 도 run `32703096829` 근거로 갱신했습니다. 다시 확인할 필요가 없습니다.
2. **워커와 다른 부하를 모두 내린 조용한 호스트**에서 측정 3종을 순차 수행합니다. 동시에 돌리지 마십시오. Ollama 는 생성을 직렬화하므로 동시 요청이 상대 P95 에 섞입니다.
3. Arq 캘리브레이션 설계는 Task 를 새로 만들어 재배정하거나 코디네이터가 직접 씁니다. 정체한 Task 에 2차 `worker_done` 을 태우지 마십시오.
4. GPT 감사 8·9·12번을 코디네이터가 직접 대조합니다.
5. 전 게이트 통과와 사용자 승인 후 `main` 에 `git merge --no-ff` 로 병합합니다. Pull Request 는 만들지 않습니다.

---

## 5. 자원 상태

| 자원 | 상태 |
| --- | --- |
| `audit-remediation-integration-896e1d5` 워크트리 | **보존.** 다음 세션 재개 지점 |
| `gpt-audit-reverify` 워크트리·터미널 | 병합 완료. 정리 대상 |
| `arq-calib-design` 워크트리·터미널 | **보존.** Task 미완이라 정리하지 않았습니다 |
| Docker | 기동 상태. 측정을 하지 않았으므로 컨테이너는 띄우지 않았습니다 |
| 원격 브랜치 `feature/audit-remediation-896e1d5` | CI 트리거용. `main` 병합 후 삭제합니다 |

---

## 6. 운영 교훈

1. **로컬 게이트 통과를 크로스 플랫폼 통과로 읽지 마십시오.** macOS 로컬에서
   1,915건이 전부 통과한 브랜치가 Windows 에서 3건 실패했습니다. 작업 브랜치를
   `feature/**` 로 push 하면 `main` 병합 전에 CI 3 플랫폼을 미리 받을 수 있습니다.
2. **DeepSeek V4 Flash 는 현재 무료 풀에 없습니다.** `opencode/deepseek-v4-flash-free`
   는 `Model not found` 이고, `opencode-go/deepseek-v4-flash` 와 `deepseek-v4-pro` 는
   중국 호스팅 **명시적 opt-in** 을 요구해 거부됩니다. `opencode-go` 풀 자체는
   정상이며 `opencode-go/kimi-k2.7-code` 는 probe 통과했습니다.
3. **`opencode-go` 는 유료 풀입니다.** 무료 워커만 쓰려면 `opencode/mimo-v2.5-free`
   같은 `opencode/` 접두 모델을 쓰십시오.
4. **`taskctl dispatch` 가 주입하는 TASK 블록의 Capsule 경로는 Intent 파일명에서
   파생됩니다.** `--task-id` 로 실제 Orca ID 를 줘도 주입 문구는 파생 경로를 가리켜
   워커가 없는 파일을 엽니다. 파생 경로에 Capsule 사본을 두거나 Dispatch 직후
   `terminal send` 로 정정하십시오.
5. **`agent_prompt_stalled` 는 오탐입니다.** 두 워커 모두 이 오류 뒤에 정상적으로
   지시를 받아 작업했습니다. 터미널을 읽어 도달을 확인하고 진행하십시오.
