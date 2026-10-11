# bandit nosec 주석 재점검 및 정리

> **작성일**: 2026-10-12
> **대상**: `src/`, `scripts/` 전체 bandit `# nosec` 주석 226건 (src 20건, scripts 206건)
> **계기**: 규칙이 더 이상 걸리지 않는 낡은 nosec 과 사유 없는 nosec 이 누적되어 오탐 억제의 근거가 흐려짐
> **판정**: 낡은 nosec 8건을 삭제하고, 불필요한 규칙 지정 9건(B607)을 정리했으며, 사유가 없던 102건에 규칙 번호와 한 줄 사유를 붙였습니다. 코드로 고칠 수 있는 위반은 없어 코드 변경은 0건입니다.
> **상태**: 완료 (marker 226 -> 218, 변경 파일 46개, 커밋 1건)

---

## 요약

저장소 정책(`pyproject.toml` `[tool.bandit]`)은 규칙을 전역·경로 단위로 끄지 않고 개별 줄에 `# nosec BXXX - 사유` 로 처리합니다. 이 정책은 유지했습니다. 점검은 두 축으로 했습니다.

첫째, 각 nosec 줄에서 마커를 하나씩 제거한 사본을 만들어 bandit 을 다시 돌렸습니다(`--ignore-nosec` 결과와 교차 확인). 제거해도 해당 규칙의 결과가 나오지 않으면 낡은 nosec 으로 판정했습니다. 여러 줄 문장은 bandit 이 문장 시작 줄이나 호출 줄로 보고하므로 줄 범위로 대조했습니다.

둘째, 남은 nosec 의 표기(`# nosec BXXX - 사유`)를 전수 검사해 규칙 번호나 사유가 빠진 줄을 찾았습니다.

결과적으로 marker 수는 226 에서 218 로 줄었고, 삭제 8건, 규칙 지정 정리 9건, 사유 보강 102건을 반영했습니다. 정리 후에도 `uv run bandit -c pyproject.toml -r src/ scripts/` 는 0건이며, 남은 모든 nosec 은 규칙 번호와 사유를 가집니다.

---

## 1. 조사 방법

bandit 은 `# nosec BXXX` 마커가 붙은 줄에서 실제로 그 규칙이 걸릴 때만 억제하고, 걸리지 않으면 `nosec encountered (BXXX), but no failed test` 경고를 냅니다. 다만 이 경고는 한 마커의 `linerange` 가 여러 줄을 덮을 때 여러 줄에 걸쳐 중복 발생하므로 낡음 판정의 근거로 쓰지 않았습니다. 대신 다음 절차를 기계로 수행했습니다.

1. `uv run bandit -c pyproject.toml -r src/ scripts/ --ignore-nosec -f json` 으로 nosec 을 무시한 전량 결과(271건)를 얻습니다.
2. 각 nosec 줄에서 그 마커만 제거한 사본을 만들어 bandit 을 다시 돌립니다.
3. 제거 후 나온 결과 중 그 마커가 선언한 규칙 번호의 결과가 있으면 필요, 없으면 낡음으로 판정합니다.
4. 여러 규칙을 선언한 마커는 규칙별로 하나씩 제거해 불필요한 규칙 지정을 가립니다.
5. `# nosec` 뒤에 규칙 번호만 있거나, 사유 대신 `# noqa` 만 있는 줄을 사유 누락으로 분류합니다.

`src/app/core/config.py` 는 다른 Task 가 수정 중이라 손대지 않았고, 그 1건(344행, 사유 있음)은 판정만 기록했습니다.

---

## 2. 규칙별 개수 (정리 전·후)

한 마커가 여러 규칙을 선언할 수 있어 합계는 marker 수와 다릅니다. `B607` 은 여러 마커에서 실행 파일이 변수/절대 경로라 실제로는 걸리지 않는 불필요 지정이었습니다.

| 규칙 | 정리 전 | 정리 후 | 비고 |
| --- | ---: | ---: | --- |
| B104 | 3 | 3 | 바인딩 아님(로컬 호스트 판별) |
| B105 | 11 | 11 | 비밀번호 아님(플래그 키·표기 문자열) |
| B107 | 1 | 1 | 인자명 오탐 |
| B108 | 1 | 1 | 경로 허용 목록 상수 |
| B110 | 5 | 2 | typed 예외 3건이 실제로 미발생 |
| B112 | 2 | 2 | 의도적 건너뜀 |
| B202 | 2 | 1 | `filter="data"` 경로 1건 미발생 |
| B310 | 10 | 7 | `Request` 구성 줄 3건 미발생 |
| B311 | 1 | 1 | 재현용 시드(암호 아님) |
| B314 | 1 | 1 | 정화한 내부 응답만 파싱 |
| B404 | 46 | 46 | 내부 도구 실행용 |
| B405 | 2 | 2 | 신뢰 응답만 파싱 |
| B603 | 94 | 94 | shell 없이 고정 인자 |
| B606 | 11 | 11 | 셸 교체 호출 |
| B607 | 62 | 53 | 불필요 지정 9건 정리 |
| B608 | 31 | 30 | 비보간 SQL 1건 미발생 |
| B704 | 5 | 5 | escape 후 Markup |
| **marker 합계** | **226** | **218** | 삭제 8건 |

---

## 3. 삭제한 낡은 nosec (8건)

| 파일 | 줄 | 규칙 | 낡은 이유 |
| --- | ---: | --- | --- |
| `scripts/backup_recovery_core.py` | 378 | B202 | `filter="data"` 를 넘겨 B202 가 걸리지 않습니다(같은 함수 380행 폴백 줄에는 유지). |
| `scripts/benchmark_compare_stats.py` | 265 | B310 | `Request(...)` 구성 줄은 B310 대상이 아니며, 실제 `urlopen` 은 272행에서 별도 처리합니다. |
| `scripts/benchmark_rag_segments.py` | 652 | B310 | `Request(...)` 구성 줄은 B310 대상이 아니며, 실제 `urlopen` 은 660행에서 별도 처리합니다. |
| `scripts/measure_llm_quality.py` | 101 | B310 | `Request(...)` 구성 줄은 B310 대상이 아니며, 실제 `urlopen` 은 109행에서 별도 처리합니다. |
| `scripts/orca_prepare_worktree.py` | 332 | B110 | `except (subprocess.SubprocessError, OSError)` 로 typed 예외라 B110 이 발생하지 않습니다. |
| `scripts/orca_scope_guard.py` | 54 | B110 | typed 예외(`subprocess.SubprocessError, OSError`)라 B110 이 발생하지 않습니다. |
| `scripts/orca_scope_guard.py` | 70 | B110 | typed 예외(`subprocess.SubprocessError, OSError`)라 B110 이 발생하지 않습니다. |
| `scripts/verify_servc_institution.py` | 221 | B608 | 보간 없는 리터럴 SQL 이라 B608 이 발생하지 않습니다(보간 있는 문장은 유지). |

## 3.1 불필요한 규칙 지정 정리 (9건, B607)

실행 파일이 `sys.executable` 이거나 변수라 부분 경로가 아니어서 B607 이 걸리지 않는 마커에서 B607 만 제거했습니다(해당 2건은 기존 사유 유지, 나머지 7건은 사유 보강과 함께 정리).

| 파일 | 줄 | 정리 |
| --- | ---: | --- |
| `scripts/backup_recovery.py` | 440 | `B603, B607` -> `B603` |
| `scripts/backup_recovery_core.py` | 227 | `B603, B607` -> `B603` |
| `scripts/backup_recovery_core.py` | 327 | `B603, B607` -> `B603` |
| `scripts/backup_recovery_core.py` | 386 | `B603, B607` -> `B603` |
| `scripts/backup_recovery_drill.py` | 62 | `B603, B607` -> `B603` |
| `scripts/benchmark_arq_container.py` | 431 | `B603 B607` -> `B603` |
| `scripts/orca_prepare_worktree.py` | 243 | `B603 B607` -> `B603` |
| `scripts/orca_read_scope_audit.py` | 267 | `B603 B607` -> `B603` |
| `scripts/validate_agent_rules.py` | 1452 | `B603 B607` -> `B603` |

---

## 4. 사유를 붙인 nosec (102건)

규칙 번호는 있었으나 사유가 없던 98건과, 사유 자리에 `# noqa` 지시문만 있던 4건에 한 줄 사유를 추가했습니다. 규칙 지정은 띄어쓰기로 통일했습니다.

| 파일 | 줄 | 규칙 | 사유 |
| --- | ---: | --- | --- |
| `scripts/backup_recovery.py` | 9 | B404 | 내부 백업 도구 실행용으로만 subprocess 를 가져옵니다 |
| `scripts/backup_recovery.py` | 440 | B603 | sys.executable 로 내부 스크립트를 shell 없이 실행합니다 |
| `scripts/backup_recovery_core.py` | 10 | B404 | 내부 백업 도구 실행용으로만 subprocess 를 가져옵니다 |
| `scripts/backup_recovery_core.py` | 75 | B603 B607 | 고정 인자 목록으로 mysql 클라이언트를 shell 없이 실행합니다 |
| `scripts/backup_recovery_core.py` | 144 | B608 | 테이블명이 DEFAULT_TABLES 상수로만 정해집니다 |
| `scripts/backup_recovery_core.py` | 227 | B603 | 고정 인자 목록으로 mysql 클라이언트를 shell 없이 실행합니다 |
| `scripts/backup_recovery_core.py` | 327 | B603 | 고정 인자 목록으로 mysql 클라이언트를 shell 없이 실행합니다 |
| `scripts/backup_recovery_core.py` | 380 | B202 | 멤버 경로와 링크를 사전 검증한 뒤 추출합니다 |
| `scripts/backup_recovery_core.py` | 386 | B603 | 고정 인자 목록으로 mysql 클라이언트를 shell 없이 실행합니다 |
| `scripts/backup_recovery_drill.py` | 8 | B404 | 내부 복구 드릴 도구 실행용으로만 subprocess 를 가져옵니다 |
| `scripts/backup_recovery_drill.py` | 62 | B603 | 고정 인자 목록으로 외부 명령을 shell 없이 실행합니다 |
| `scripts/backup_recovery_drill.py` | 143 | B603 | 고정 인자 목록으로 mysql 클라이언트를 shell 없이 실행합니다 |
| `scripts/benchmark_arq_container.py` | 29 | B404 | docker 와 git 명령 실행용으로만 subprocess 를 가져옵니다 |
| `scripts/benchmark_arq_container.py` | 206 | B603 B607 | git rev-parse 를 shell 없이 고정 인자로 실행합니다 |
| `scripts/benchmark_arq_container.py` | 217 | B603 B607 | docker --version 을 shell 없이 고정 인자로 실행합니다 |
| `scripts/benchmark_arq_container.py` | 241 | B603 B607 | docker inspect 를 shell 없이 고정 인자로 실행합니다 |
| `scripts/benchmark_arq_container.py` | 431 | B603 | docker 명령을 shell 없이 인자 목록으로 실행합니다 |
| `scripts/benchmark_arq_container.py` | 436 | B603 B607 | docker inspect 를 shell 없이 인자 목록으로 실행합니다 |
| `scripts/benchmark_arq_container.py` | 454 | B603 B607 | docker logs 를 shell 없이 인자 목록으로 실행합니다 |
| `scripts/benchmark_arq_container.py` | 470 | B603 B607 | docker rm 을 shell 없이 인자 목록으로 실행합니다 |
| `scripts/benchmark_arq_throughput.py` | 27 | B404 | docker 와 git 명령 실행용으로만 subprocess 를 가져옵니다 |
| `scripts/benchmark_arq_throughput.py` | 145 | B603 B607 | docker --version 을 shell 없이 고정 인자로 실행합니다 |
| `scripts/benchmark_arq_throughput.py` | 387 | B603 B607 | git rev-parse 를 shell 없이 고정 인자로 실행합니다 |
| `scripts/benchmark_compare_stats.py` | 27 | B404 | 내부 벤치마크 명령 실행용으로만 subprocess 를 가져옵니다 |
| `scripts/benchmark_compare_stats.py` | 272 | B310 | 내부에서 정한 고정 compare-stats URL 만 엽니다 |
| `scripts/benchmark_compare_stats.py` | 301 | B603 | 고정 인자 목록으로 명령을 shell 없이 실행합니다 |
| `scripts/benchmark_home_recent_selection.py` | 44 | B404 | 내부 벤치마크 명령 실행용으로만 subprocess 를 가져옵니다 |
| `scripts/benchmark_home_recent_selection.py` | 422 | B603 | 호출부가 넘긴 고정 인자 목록으로 shell 없이 실행합니다 |
| `scripts/benchmark_latency.py` | 28 | B404 | 내부 벤치마크 명령 실행용으로만 subprocess 를 가져옵니다 |
| `scripts/benchmark_latency.py` | 206 | B603 | 호출부가 넘긴 고정 인자 목록으로 shell 없이 실행합니다 |
| `scripts/benchmark_offload_loop_lag.py` | 43 | B404 | sysctl 조회용으로만 subprocess 를 가져옵니다 |
| `scripts/benchmark_offload_loop_lag.py` | 348 | B603 B607 | sysctl 을 shell 없이 고정 인자로 실행합니다 |
| `scripts/benchmark_offload_loop_lag.py` | 359 | B603 B607 | sysctl 을 shell 없이 고정 인자로 실행합니다 |
| `scripts/benchmark_provenance.py` | 25 | B404 | git 과 sysctl 명령 실행용으로만 subprocess 를 가져옵니다 |
| `scripts/benchmark_provenance.py` | 152 | B603 B607 | git rev-parse 를 shell 없이 고정 인자로 실행합니다 |
| `scripts/benchmark_provenance.py` | 160 | B603 B607 | git status 를 shell 없이 고정 인자로 실행합니다 |
| `scripts/benchmark_provenance.py` | 213 | B603 B607 | sysctl 을 shell 없이 고정 인자로 실행합니다 |
| `scripts/benchmark_provenance.py` | 465 | B603 | 호출부가 넘긴 고정 인자 목록으로 shell 없이 실행합니다 |
| `scripts/benchmark_provenance.py` | 946 | B603 | 호출부가 넘긴 고정 인자 목록으로 shell 없이 실행합니다 |
| `scripts/benchmark_rag_segments.py` | 26 | B404 | 내부 벤치마크 명령 실행용으로만 subprocess 를 가져옵니다 |
| `scripts/benchmark_rag_segments.py` | 170 | B603 | 호출부가 넘긴 고정 인자 목록으로 shell 없이 실행합니다 |
| `scripts/benchmark_rag_segments.py` | 660 | B310 | 내부에서 정한 고정 질의 URL 만 엽니다 |
| `scripts/benchmark_read_path_concurrency.py` | 24 | B404 | 컨테이너 재시작 명령 실행용으로만 subprocess 를 가져옵니다 |
| `scripts/benchmark_read_path_concurrency.py` | 546 | B603 | 고정 인자 목록으로 컨테이너 재시작 명령을 shell 없이 실행합니다 |
| `scripts/benchmark_read_path_concurrency.py` | 565 | B603 | 고정 인자 목록으로 컨테이너 재시작 명령을 shell 없이 실행합니다 |
| `scripts/build_llm_fixture_manifest.py` | 163 | B608 | placeholders 는 물음표만 반복 생성하며 값은 바인딩합니다 |
| `scripts/eval_cnstwk_year_holdout.py` | 25 | B404 | git 명령 실행용으로만 subprocess 를 가져옵니다 |
| `scripts/eval_cnstwk_year_holdout.py` | 280 | B603 B607 | git rev-parse 를 shell 없이 고정 인자로 실행합니다 |
| `scripts/extract_score_params.py` | 32 | B405 | 정화한 조달청 OpenAPI 응답만 파싱합니다 |
| `scripts/extract_score_params.py` | 536 | B314 | 정화한 조달청 OpenAPI 응답만 파싱합니다 |
| `scripts/measure_coldsql_attribution.py` | 341 | B310 | 내부에서 정한 고정 URL 만 엽니다 |
| `scripts/measure_llm_quality.py` | 32 | B404 | docker 명령 실행용으로만 subprocess 를 가져옵니다 |
| `scripts/measure_llm_quality.py` | 109 | B310 | 내부에서 정한 고정 질의 URL 만 엽니다 |
| `scripts/measure_llm_quality.py` | 415 | B603 B607 | docker exec 을 shell 없이 고정 인자로 실행합니다 |
| `scripts/measure_llm_quality.py` | 460 | B603 B607 | docker inspect 를 shell 없이 고정 인자로 실행합니다 |
| `scripts/orca_agy_launch.py` | 178 | B606 | 셸을 거치지 않고 코디네이터가 만든 인자로 프로세스를 교체합니다 |
| `scripts/orca_auto_approve.py` | 1480 | B603 B607 | orca CLI 를 shell 없이 고정 인자로 실행합니다 |
| `scripts/orca_auto_approve.py` | 1494 | B603 B607 | orca CLI 를 shell 없이 고정 인자로 실행합니다 |
| `scripts/orca_claude_launch.py` | 79 | B606 | 터미널 유지를 위한 대화형 셸 교체 호출입니다 |
| `scripts/orca_claude_launch.py` | 182 | B606 | 셸을 거치지 않고 코디네이터가 만든 인자로 프로세스를 교체합니다 |
| `scripts/orca_cmd_launch.py` | 123 | B606 | 터미널 유지를 위한 대화형 셸 교체 호출입니다 |
| `scripts/orca_cmd_launch.py` | 250 | B606 | 셸을 거치지 않고 코디네이터가 만든 인자로 프로세스를 교체합니다 |
| `scripts/orca_contract.py` | 23 | B404 | git 명령 실행용으로만 subprocess 를 가져옵니다 |
| `scripts/orca_contract.py` | 488 | B603 B607 | git 명령을 shell 없이 인자 목록으로 실행합니다 |
| `scripts/orca_contract.py` | 826 | B603 | 화이트리스트 명령을 shell 없이 인자 목록으로 실행합니다 |
| `scripts/orca_grok_launch.py` | 78 | B606 | 터미널 유지를 위한 대화형 셸 교체 호출입니다 |
| `scripts/orca_grok_launch.py` | 180 | B606 | 셸을 거치지 않고 코디네이터가 만든 인자로 프로세스를 교체합니다 |
| `scripts/orca_kimi_launch.py` | 108 | B606 | 터미널 유지를 위한 대화형 셸 교체 호출입니다 |
| `scripts/orca_level1_gate.py` | 654 | B603 | 실행기 도움말을 shell 없이 고정 인자로 조회합니다 |
| `scripts/orca_opencode_launch.py` | 123 | B606 | 터미널 유지를 위한 대화형 셸 교체 호출입니다 |
| `scripts/orca_opencode_launch.py` | 251 | B606 | 셸을 거치지 않고 코디네이터가 만든 인자로 프로세스를 교체합니다 |
| `scripts/orca_prepare_worktree.py` | 284 | B603 B607 | git config 를 shell 없이 고정 인자로 실행합니다 |
| `scripts/orca_prepare_worktree.py` | 292 | B603 B607 | git config 를 shell 없이 고정 인자로 실행합니다 |
| `scripts/orca_prepare_worktree.py` | 299 | B603 B607 | git config 를 shell 없이 고정 인자로 실행합니다 |
| `scripts/orca_prepare_worktree.py` | 323 | B603 B607 | git config --get 을 shell 없이 고정 인자로 실행합니다 |
| `scripts/orca_qwen_launch.py` | 107 | B606 | 터미널 유지를 위한 대화형 셸 교체 호출입니다 |
| `scripts/orca_read_scope_audit.py` | 67 | B108 | 시스템 경로 허용 목록 상수이지 임시 파일 생성이 아닙니다 |
| `scripts/orca_read_scope_audit.py` | 267 | B603 | 고정 인자 목록으로 명령을 shell 없이 실행합니다 |
| `scripts/orca_scope_guard.py` | 20 | B404 | git 명령 실행용으로만 subprocess 를 가져옵니다 |
| `scripts/orca_scope_guard.py` | 46 | B603 B607 | git config 를 shell 없이 고정 인자로 실행합니다 |
| `scripts/orca_scope_guard.py` | 62 | B603 B607 | git diff 를 shell 없이 고정 인자로 실행합니다 |
| `scripts/orca_settled_session_audit.py` | 99 | B112 | 깨진 영수증 파일은 건너뛰고 다음 파일로 진행합니다 |
| `scripts/orca_taskctl.py` | 1069 | B110 | JSON 배열 파싱 실패는 정상 흐름이라 무시합니다 |
| `scripts/orca_worker_done_guard.py` | 17 | B404 | 검증 명령 실행용으로만 subprocess 를 가져옵니다 |
| `scripts/orca_worker_done_guard.py` | 319 | B603 | 고정 인자 목록으로 검증 명령을 shell 없이 실행합니다 |
| `scripts/orca_worker_watch.py` | 318 | B603 | 호출부가 넘긴 고정 인자 배열로 shell 없이 실행합니다 |
| `scripts/run_p9_sse_rebaseline.py` | 14 | B404 | sysctl 조회용으로만 subprocess 를 가져옵니다 |
| `scripts/run_p9_sse_rebaseline.py` | 45 | B603 B607 | sysctl 을 shell 없이 고정 인자로 실행합니다 |
| `scripts/run_p9_sse_rebaseline.py` | 54 | B603 B607 | sysctl 을 shell 없이 고정 인자로 실행합니다 |
| `scripts/validate_llm_quality_fixture.py` | 139 | B608 | placeholders 는 물음표만 반복 생성하며 값은 바인딩합니다 |
| `scripts/verify_migration.py` | 24 | B404 | git 명령 실행용으로만 subprocess 를 가져옵니다 |
| `scripts/verify_migration.py` | 988 | B603 B607 | git rev-parse 를 shell 없이 고정 인자로 실행합니다 |
| `src/app/core/templating.py` | 203 | B704 | JS 이스케이프를 거친 값만 Markup 으로 감쌉니다 |
| `src/app/core/templating.py` | 222 | B704 | JS 이스케이프를 거친 값만 Markup 으로 감쌉니다 |
| `src/app/services/api_collector.py` | 19 | B405 | 신뢰하는 공공데이터 XML 응답만 파싱합니다 |
| `src/app/services/auth_forms.py` | 46 | B704 | escape 를 거친 값만 Markup 으로 감쌉니다 |
| `src/app/services/auth_forms.py` | 96 | B704 | escape 를 거친 값만 Markup 으로 감쌉니다 |
| `src/app/services/auth_forms.py` | 100 | B704 | escape 를 거친 값만 Markup 으로 감쌉니다 |
| `src/app/services/automation_callbacks.py` | 55 | B104 | 바인딩이 아니라 로컬 호스트 판별용 비교입니다 |
| `src/app/services/kb_builder.py` | 132 | B110 | 없는 컬렉션 삭제 실패는 정상 흐름이라 무시합니다 |
| `src/ml/institution_history.py` | 107 | B112 | 파싱 실패한 후보 키는 건너뛰고 다음 키를 봅니다 |
| `src/tasks/automation_tasks.py` | 75 | B107 | 비밀번호가 아니라 확인 토큰 기본값 인자입니다 |

---

## 5. 코드로 고친 목록

없습니다. 이번 조사에서 억제된 결과는 아래 후보를 제외하면 전부 오탐(문자열 상수 오인, typed 예외, escape 된 값의 Markup, 보간 없는 SQL 등)이거나 내부 도구 실행처럼 의도된 패턴이었습니다. 한두 줄로 끝나면서 동작을 바꾸지 않는 수정이 없어 코드는 변경하지 않았습니다.

---

## 6. 남긴 후보 목록

동작이 바뀔 수 있거나 새 의존성이 필요한 항목이라 코드를 고치지 않고 후보로만 남깁니다.

| 항목 | 위치 | 내용 | 사유 |
| --- | --- | --- | --- |
| XML 파서 교체 | `scripts/extract_score_params.py:32,536`, `src/app/services/api_collector.py:19` | `xml.etree.ElementTree` 를 `defusedxml` 로 교체 | 새 의존성 추가는 사전 합의 필요(B405/B314) |
| tar 추출 폴백 | `scripts/backup_recovery_core.py:380` | Python 3.12 미만 폴백에 `filter="data"` 적용 또는 하한 상향 | 멤버 경로·링크 사전 검증이 있어 현재도 완화되나, 필터 적용은 동작 변경(B202) |
| URL 스킴 검증 | `scripts/benchmark_compare_stats.py:272`, `scripts/benchmark_rag_segments.py:660`, `scripts/check_release_readiness.py:156`, `scripts/measure_coldsql_attribution.py:341`, `scripts/measure_llm_quality.py:109`, `scripts/measure_predict_rss.py:91,125` | `urlopen` 전에 http/https 스킴 화이트리스트 검증 | 로컬·내부 주소만 열지만 검증 추가는 동작 변경(B310) |
| 예외 로깅 | `scripts/orca_taskctl.py:1069`, `src/app/services/kb_builder.py:132`, `scripts/orca_settled_session_audit.py:99`, `src/ml/institution_history.py:107` | `except: pass`/`continue` 를 로깅으로 대체 | 정상 흐름이라 로깅 추가는 동작·로그 변경(B110/B112) |
| 실행 파일 절대 경로 | B607 을 유지한 다수 `subprocess` 호출 | `shutil.which` 로 절대 경로 해석 | PATH 탐색 동작이 바뀌므로 후보로만 유지(B607) |

`src/app/core/config.py:344` 의 B105 1건은 기본 비밀번호 사용을 거부하는 비교 문자열로 오탐이며, 다른 Task 수정 대상이라 손대지 않았습니다.

---

## 7. 검증 결과

| 명령 | 결과 |
| --- | --- |
| `uv run bandit -c pyproject.toml -r src/ scripts/` | 0건 (exit 0) |
| `uv run pytest tests/ -q -m 'not data_assets'` | 7147 passed, 49 skipped, 3 deselected |
| `uv run mypy src` | Success: no issues found in 131 source files |
| `python3 scripts/validate_agent_rules.py --quiet` | 검증 통과 21/21 건 |
| `uv run ruff check src scripts` | All checks passed |

변경은 전부 1:1 줄 치환(추가 112줄 = 삭제 112줄)이며, 주석 외 코드 줄은 바뀌지 않았습니다. `git diff` 기준 변경 파일 46개는 모두 nosec 주석 줄입니다.
