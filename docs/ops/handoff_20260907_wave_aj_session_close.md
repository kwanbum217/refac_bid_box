# 인수인계: 20260907 Wave AJ 세션 종료

> **작성일**: 2026-09-07
> **Run**: `run_8899573ba0ac`
> **기준 커밋**: `fbfc7e7` -> `e48f592` (커밋 17개)
> **미병합 브랜치**: 없음
> **인수 대상**: 다음 코디네이터
> **선행 문서**: [`handoff_20260907_wave_ai_session_close.md`](handoff_20260907_wave_ai_session_close.md)

---

## 1. 한 줄 요약

**선행 인수인계 8.1 후속 과제 중 착수 가능한 세 건을 빌더 3대로 병렬 처리해 병합했고,
조율 도중 발견한 통제면 결함 두 건(Intent 따옴표 절단, 문서 링크 격리 예외)을 함께
닫았습니다.** 사용자 지적을 받아 검증 병렬 실행 원칙을 정본에 명세화했습니다.

---

## 2. 닫은 항목

| Wave | 내용 | 작업 커밋 | 병합 |
| --- | --- | --- | --- |
| AJ1 | `resolve_verification_commands` 가 선언된 전량 pytest 에 `-m 'not data_assets'` 를 기계로 강제. 격리 트리 자산 예외를 `BASE_GROUND_TRUTH` 표준 항목으로 승격 | `1b2cf55` | `fbe3fca` |
| AJ1 재작업 | `parse_intent` 의 따옴표 절단 결함 수정 | `3b7121f` | `fbe3fca` |
| AJ2 | 워커 런처의 커밋 강제 고지문을 역할별로 자동 분기. 리뷰어에는 리뷰어 계약 안내 | `4fd4b34` | `29ccd08` |
| AJ3 | 자동 승인 감시기가 `$( )` 명령 치환과 `while`/`for` 루프를 재귀 판정 | `81ce5d5` | `64abe09` |
| AJ4 | 검증 병렬 실행 원칙 명세화, 문서 링크 격리 예외 제거 | `8fae1b8`, `adec2ed` | `891843d` |
| AJ6 | `source_commit` 갱신 | `59a0872` | `e48f592` |

빌더는 전부 Antigravity `gemini-3.8-flash-medium`, 리뷰 판정은 세 건 모두 `pass`,
blocking_issues 0건입니다. `main` 최종 검증은 pytest **3,952 passed / 32 skipped /
실패 0**, `validate_agent_rules` 20/20, `test_data_preservation` 3건 통과입니다.
원격 푸시까지 완료했습니다 (`fbfc7e7..e48f592`).

### 2.1 WORKER_MODEL_NOTICE

리뷰어는 사용자 지시로 Antigravity Claude 계열을 썼습니다. 세션 중반부터 Antigravity
Claude 가 **신규 세션에서 `Agent execution terminated (2008)` 로 즉시 종료**했고
`claude-sonnet-4-6` 과 `claude-opus-4-6-thinking` 둘 다 같았습니다. 소진 전에 붙은
AJ2 리뷰어 한 대만 끝까지 살았습니다. 나머지 리뷰어는 **로컬 Claude CLI
(`claude-sonnet-5`, effort medium)** 를 `worker-start` 감독 경로로 배정했습니다.
빌더가 Gemini 계열이므로 계열 분리 불변조건은 유지됩니다.

---

## 3. 조율 도중 발견한 통제면 결함

### 3.1 Intent 의 따옴표가 잘려 마커 강제가 무력화됐습니다

AJ1 을 Dispatch 한 직후 Level 1 게이트 3 이 `명령 파싱 실패: No closing quotation`
으로 거부했습니다. 이번 Wave 의 Capsule 세 건 모두에 다음이 기록돼 있었습니다.

    uv run pytest tests/ -q -m 'not data_assets

원인은 `parse_intent` 가 YAML 리스트 항목의 양끝에서 따옴표를 **집합으로** 제거한
것입니다. 값이 작은따옴표로 끝나면 닫는 따옴표까지 함께 잘립니다. 잘린 문자열은
`shlex.split` 이 실패하고 fallback 분리에서 `data_assets` 가 별도 토큰이 되어 전량
대상 판정이 거짓이 되므로, **AJ1 이 만든 마커 강제가 정작 YAML Intent 경로에서
동작하지 않았습니다.**

1차 리뷰가 이것을 `quote_stripping_fixed` fail 로 잡아냈고 재작업 `3b7121f` 이
짝이 맞는 따옴표만 벗기도록 고쳤습니다. **리뷰어가 코디네이터의 사후 관측을 실제
차단 결함으로 확인한 사례입니다.**

### 3.2 문서 링크 하나가 격리 트리 전량 테스트를 깨고 있었습니다

워커 3대의 전량 테스트가 전부 `tests/test_validate_doc_links.py::test_cli_execution`
한 건으로만 실패했습니다. `docs/analysis/task_6304378e4a69.md:5` 가 gitignore 대상인
`.orca/capsules/` 아래 파일을 마크다운 링크로 참조했기 때문이며, 주 저장소에서는
그 디렉터리가 있어 통과합니다.

다른 보고서 열 곳은 원래부터 인라인 코드로 참조하고 있었습니다. 예외를 문서에
적어 두는 대신 **그 한 줄을 인라인 코드로 고쳐 예외 자체를 없앴습니다.** 이 수정
전에는 premerge 게이트가 증거의 종료 코드 0 을 요구하므로 어느 브랜치도 병합할 수
없었습니다.

---

## 4. 명세화한 것 (사용자 지시)

세션 중 사용자가 두 가지를 지적했습니다. 첫째는 워커 완료를 직렬로 기다리며
검증한 것이고, 둘째는 그것을 지적받지 않아도 지키도록 명세화하라는 것입니다.

[`AGENTS.md`](../../AGENTS.md) 4장에 조항 8 을 넣고,
[`orca-section-coordination`](../../.agents/skills/orca-section-coordination/SKILL.md)
스킬에 4.3 절을 추가했습니다. 요지는 다음과 같습니다.

| 단계 | 병렬 여부 |
| --- | --- |
| Level 1 게이트 | 병렬 (워크트리별 읽기 전용) |
| Level 2 리뷰어 Dispatch | 병렬 (리뷰어는 쓰기 워커 상한에 포함되지 않음) |
| Level 3 코디네이터 diff 검토 | 병렬 |
| `main` 병합 | **직렬** |

전량 pytest 는 회차당 약 2분이므로 3건 직렬은 6분, 병렬은 2분입니다.

---

## 5. 이번 세션의 코디네이터 과실

### 5.1 리뷰 체크리스트 id 를 빌더 Capsule 과 맞추지 않았습니다

리뷰 Intent 를 쓸 때 체크리스트 항목을 임의로 추가하고 이름을 바꿨습니다
(`scope_expanded`, `quote_stripping_fixed`, `detection_false_positive`,
`bypass_input_exists`). Level 1 게이트 5 는 `review_done.json` 의
`checklist_results` id 집합이 **빌더 Capsule 의 `review_checklist` 와 정확히 일치**
할 것을 요구하므로 세 건 모두 처음에 실패했습니다.

여기에 극성 문제까지 겹쳤습니다. 같은 id 라도 `defect_when` 이 다르면 게이트가
정상 판정을 결함으로 읽습니다. AJ1 의 `targeted_command_preserved` 가 그랬습니다.

**추가로 묻고 싶은 항목은 체크리스트가 아니라 `ground_truth` 나 `acceptance` 에
넣으십시오.** 체크리스트는 빌더 Capsule 을 그대로 복사하는 자리입니다.

정정에 리뷰어 재기동이 세 번 더 들었습니다. AJ2 는 두 번인데, 첫 정정에서 `answer`
필드를 판정값(`pass`)으로 적어 게이트가 `yes/no` 로 읽지 못했기 때문입니다.
**`answer` 는 판정이 아니라 그 항목 `question` 에 대한 답입니다.**

### 5.2 워크트리에 다른 Task 의 Capsule 을 복사했습니다

리뷰 Capsule 세 개를 세 워크트리 전부에 복사했다가 되돌렸습니다. 유사 이름 Capsule
이 같은 트리에 있으면 워커가 엉뚱한 것을 여는 사고가 이미 기록돼 있습니다. **한
워크트리에는 그 Task 의 Capsule 만 두십시오.**

### 5.3 Dispatch 직후 Capsule 경로가 워크트리에 없었습니다

TASK 블록은 슬러그 이름 Capsule(`task_aj1_capsule_data_assets_marker/`)을 가리키는데
워크트리에는 `task_<id>/` 만 배치됩니다. 세 워크트리에 슬러그 사본을 수동 복사해
해소했습니다. `taskctl create` 가 안내문으로 알려 주지만 자동 배치는 하지 않습니다.

### 5.4 배경 실행에 `nohup ... &` 를 썼다가 결과를 잃었습니다

게이트를 `&` 로 띄웠더니 호출이 끝나는 순간 프로세스가 죽어 결과 파일이 0바이트로
남았습니다. 배경 실행은 도구의 `run_in_background` 를 쓰십시오.

---

## 6. 워커 감시에서 실제로 막혔던 지점

사용자가 자리를 비운 동안 다음을 처리했습니다. 전부 코디네이터가 먼저 발견했습니다.

| 워커 | 막힌 이유 | 조치 |
| --- | --- | --- |
| AJ2 리뷰어 | `cat > <절대경로>/review_done.json` 히어독 쓰기가 자동 승인 밖 | 승인 전송 |
| AJ3 리뷰어 | `python3 -c` 인라인 실행이 자동 승인 밖 | 승인 전송 |
| AJ2 리뷰어 | 커밋 강제 고지문과 리뷰어 계약 충돌로 `question` 정지 | `reply` 로 커밋 금지 확정 |
| AJ3 리뷰어 | 에이전트 실행 오류로 턴 종료 | 재기동 후 모델 소진 확인, 로컬 Claude 로 교체 |

**첫 두 건은 자동 승인 화이트리스트의 구멍입니다.** 리다이렉트 대상이 워크트리
안이라도 절대 경로면 `REDIRECT_DENY` 가 `^/` 로 거부합니다. 리뷰어는 보고 파일을
쓸 때 절대 경로를 자주 만들므로 매번 사람이 풀어야 합니다. AJ3 이 명령 치환과 루프를
열었지만 이 두 형태는 아직 열려 있지 않습니다.

---

## 7. 남은 항목

| ID | 내용 | 선행 조건 |
| --- | --- | --- |
| **R-12** | G2 Windows Docker Desktop 실기 | Windows 장비. `worker-start --on <saved-environment>` 원격 워커 경로가 열려 있다 |
| **R-13 정본 측정** | canonical 게이트 충족 측정 | HTTP 실패 0, trace 대조 전량, 문항·회차 정본 기준 충족. 저장소 동결 필요 |

### 7.1 후속 과제 (이 세션이 만든 것)

| 출처 | 내용 |
| --- | --- |
| 5.1 | `orca_taskctl.py` 가 리뷰 Intent 를 확장할 때 `target_task` 의 빌더 Capsule `review_checklist` 를 그대로 복사하고, Intent 가 다른 id 를 선언하면 거부하도록 한다. 지금은 작성자가 기억해야 하고 잊으면 리뷰어를 다시 띄워야 한다 |
| 5.1 | `review_done.json` 의 `answer` 를 `yes`/`no` 로만 받도록 `validate_review_report.py` 가 작성 시점에 거부한다 |
| 6장 | 자동 승인 화이트리스트에서 워크트리 내부를 가리키는 절대 경로 리다이렉트와 `python3 -c` 인라인 실행을 판정 대상으로 넣는다. AJ3 이 연 재귀 판정 구조를 그대로 쓸 수 있다 |
| 5.3 | `taskctl create` 가 슬러그 Capsule 사본을 워크트리에 자동 배치하거나, TASK 블록이 `task_<id>` 경로를 가리키게 한다 |
| 선행 AI 8.1 | `evidence.complete` 관측치 축적 후 감사 도구 ack 편입 판단, codex 런처 대기 표지, baseline 생성, R-10 2단계 Prometheus |
| 선행 AI 4장 | 게이트 8 은 `main..branch` 만 검사한다. 과거 이력의 영어 제목은 그대로 남아 있다 |

---

## 8. 정리 상태

**모든 자원을 회수했습니다.** 빌더 3대와 리뷰어 6대(정정 재기동 포함) 전부
`worker_done` ack 직후 회수했습니다. 런처 경로로 띄운 워커는 `worker-release` 가
`retained` / `no_owned_resource` 로 돌아와 `orca terminal close --terminal` 로 창
단위 종료했고(`--tab` 미사용), `worker-start` 감독 경로로 띄운 워커는 `released`
로 정상 반환됐습니다.

워크트리 `wave-aj1`, `wave-aj2`, `wave-aj3` 는 `main` 병합 확인 후 제거했고 브랜치
다섯 개는 `git branch -d` 로 삭제했습니다. `orca_settled_session_audit.py` 는 잔류
없음, `git worktree list` 는 주 저장소 한 줄입니다.

**정리하지 않은 것이 하나 있습니다.** 이전 세션이 남긴 grok 터미널
(`term_ff628ffc`, 주간 한도 소진 상태)은 이번 Run 소유가 아니라 건드리지 않았습니다.

Run `run_8899573ba0ac` 의 Task 는 빌더 3건, 빌더 재작업 1건, 리뷰 6건입니다.
