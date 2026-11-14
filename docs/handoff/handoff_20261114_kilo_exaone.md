# 핸드오프 인수인계 - 2026-11-14 Kilo 워커 모델 등록 세션

> **작성일**: 2026-11-14
> **작성**: 코디네이터(Claude Opus 5.5). Orca Run `run_694b12aced4c`
> **기준 커밋**: `main` 은 `55a56e96` 그대로입니다. 이 세션의 변경은 브랜치 `chore/router-kilo-exaone-coarena` 에만 있습니다(main 미병합).
> **워커**: 0대. 시험 워커 1대는 회수했고 워크트리 `exaone-probe` 는 제거했습니다.
> **이전 문서**: [`handoff_20261114_session_close.md`](handoff_20261114_session_close.md) 0절의 과업은 그대로 유효합니다. 단 같은 문서 0절 4행(Docker 스택 유지)은 이번 세션 종료 때 사용자 지시로 스택을 내렸으므로 다음 세션 시작 시 다시 올려야 합니다.

---

## 0. 다음 세션이 바로 할 일

| 우선 | 과업 | 방법 |
| --- | --- | --- |
| 1 | Docker 스택 재기동 | 이번 종료 때 사용자 지시로 정지했습니다. `web-platform-launch` 스킬 절차로 올립니다 |
| 2 | `chore/router-kilo-exaone-coarena` 병합 여부 결정 | 사용자 결정 대기. 병합 시 Level 1 strict 증거와 source_commit 갱신 절차를 따릅니다 |
| 3 | K-EXAONE 2.5 워커 재시험 | 사용자 결정: 서버 혼잡이 일시적인지 판단할 수 없으므로 추후 재시험. 다른 시간대에 단발 `kilo run` 몇 회로 혼잡률부터 확인한 뒤 워커 시험 |
| 4 | Coarena DeepSeek V4.1 Flash 워커 시험 | 등록과 probe 만 통과. 워커 전 주기는 미시험 |
| 5 | 이전 문서 0절 1~3행 | 예비가격 소급, 주간 재학습 후보 판정, `RedisConnection.invalidate()` 관찰 |

---

## 1. 라우터 등록 (`chore/router-kilo-exaone-coarena`)

| 커밋 | 내용 |
| --- | --- |
| `1daf1186` | `scripts/orca_model_router.py` 에 `kilo-exaone`(`exaone/k-exaone_v2.5`), `kilo-coarena-deepseek-flash`(`coarena/deepseek-v4-1-flash-1017`) 추가. 둘 다 `auto_selectable` False, `suitable_for` 는 investigator·reviewer. `PROBE_CONFIG["kilo"]`(`kilo run -m {model} ping`), 제공자 접두사 `exaone/`·`coarena/`, probe 실패 표지 `service is busy` 추가. `scripts/audit_model_inventory.py` 목록 조회에 `kilo models` 경로 추가 |
| `bb647cdc` | EXAONE 항목 notes 에 워커 시험 실패 결과 기록 |

검증: 두 모델 probe 실호출 통과, `tests/test_orca_model_router.py`·`tests/test_orca_run_reviewer.py`·taskctl·인벤토리 시험 585건 통과, ruff·mypy 통과, `validate_agent_rules.py` 22/22.

제공자는 실행기(kilo)와 분리해 `exaone`, `coarena` 로 두었습니다. Coarena 의 DeepSeek 은 cmd 의 `deepseek/` 와 제공자가 다르므로 리뷰어 독립성 판정에서 다른 계열로 취급됩니다.

---

## 2. K-EXAONE 2.5 워커 시험 결과

| 단계 | 결과 |
| --- | --- |
| 단발 `kilo run` 3회 | 성공 1회(약 19초), 실패 2회 `service is busy, too many concurrent requests(600)` |
| 런처 기동(`orca_opencode_launch.py --binary kilo --variant high`) | 성공, preamble 수신 확인(`verified_launcher_pickup`) |
| Capsule 읽기, 파일 조회 도구 호출 | 동작 |
| 완료 | 실패. 같은 혼잡 오류로 kilo 자동 재시도를 소진하고 보고서 없이 정지. Task `task_6c9c1bf77544` 는 failed 처리 |

---

## 3. 운영 메모

| 메모 | 내용 |
| --- | --- |
| Kilo 워커 기동 | `orca_taskctl.py` 의 `LAUNCHER_ROUTING_BY_PROVIDER` 에 exaone·coarena 가 없으므로 `dispatch --launcher scripts/orca_opencode_launch.py --no-probe` 를 명시합니다 |
| 키 공급 | 터미널 명령 앞에 `source ~/.config/kilo/exaone.env &&` 를 붙입니다. `~/.zshrc` 가 읽지만 이미 떠 있던 셸에는 반영되지 않습니다. Coarena 는 `coarena.env` |
| 감시 스크립트 | kilo 는 혼잡 오류를 화면에 띄운 채 자동 재시도하므로 문구만으로 실패 판정하면 오탐입니다. 재시도 회차와 화면 정체 시간으로 판정합니다 |
| 설정 파일 | `~/.config/kilo/kilo.jsonc` 의 MCP 항목 일부에 토큰이 평문으로 있습니다. 저장소와 무관하나 사용자에게 고지했습니다 |
