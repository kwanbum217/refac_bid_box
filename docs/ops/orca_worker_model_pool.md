# Orca 워커 모델 풀 정본

> **작성일**: 2026-08-30
> **버전**: v1.0.0
> **배정표 정본**: [`scripts/orca_model_router.py`](../../scripts/orca_model_router.py) 의 `TIER_POLICY`
> 본 문서는 배정 근거와 가용성 실측을 기록합니다. 실제 배정은 코드가 결정하며, 문서와
> 코드가 어긋나면 코드가 정본입니다.

---

## 1. 역할별 모델 배정 정책 (TIER_POLICY)

이 표는 [`scripts/orca_model_router.py`](../../scripts/orca_model_router.py)의 `TIER_POLICY` 사본이며 불일치 시 코드가 정본입니다.

| 역할 (`role`) | 위험도 (`risk`) | 1순위 (Primary) | 2순위 (Fallback) |
| --- | :---: | --- | --- |
| `reviewer` | `high` | `qwen-plus` | `gemini-flash-high` |
| `reviewer` | `medium` | `qwen-plus` | `gemini-flash-medium` |
| `reviewer` | `low` | `qwen-plus` | `gemini-flash-medium` |
| `builder` | `high` | `gemini-flash-high` | `qwen-plus` |
| `builder` | `medium` | `gemini-flash-medium` | `qwen-plus` |
| `builder` | `low` | `gemini-flash-medium` | `qwen-plus` |
| `investigator` | `high` | `gemini-flash-high` | `qwen-plus` |
| `investigator` | `medium` | `gemini-flash-medium` | `qwen-plus` |
| `investigator` | `low` | `gemini-flash-low` | `gemini-flash-medium` |
| `benchmarker` | `high` | `gemini-flash-high` | `qwen-plus` |
| `benchmarker` | `medium` | `gemini-flash-medium` | `qwen-plus` |
| `benchmarker` | `low` | `gemini-flash-medium` | `gemini-flash-low` |
| `documenter` | `high` | `gemini-flash-high` | `qwen-plus` |
| `documenter` | `medium` | `gemini-flash-medium` | `qwen-plus` |
| `documenter` | `low` | `gemini-flash-low` | `gemini-flash-medium` |
| `__default__` | `high` | `gemini-flash-high` | `qwen-plus` |
| `__default__` | `medium` | `gemini-flash-medium` | `qwen-plus` |
| `__default__` | `low` | `gemini-flash-medium` | `qwen-plus` |

### 1.1 등록 모델 풀 현황

| 풀 키 | 모델 ID | 제공자 | 자동 배정 (`auto_selectable`) | 배정 대상 및 용도 |
| --- | --- | :---: | :---: | --- |
| `gemini-flash-high` | `gemini-3.8-flash-high` | Gemini | O (`True`) | 고난도 추론·코딩, high 위험도 전용 |
| `gemini-flash-medium` | `gemini-3.8-flash-medium` | Gemini | O (`True`) | 기본 주력 워커 (builder/investigator/benchmarker/documenter) |
| `gemini-flash-low` | `gemini-3.8-flash-low` | Gemini | O (`True`) | low 위험도 investigator/documenter 주 모델, benchmarker fallback |
| `gemini-3.7-flash-high` | `gemini-3.7-flash-high` | Gemini | X (`False`) | Gemini 3.7 Flash 수동 지정 전용 (3.8 롤백 및 비교 검증용) |
| `gemini-3.7-flash-medium` | `gemini-3.7-flash-medium` | Gemini | X (`False`) | Gemini 3.7 Flash 수동 지정 전용 (3.8 롤백 및 비교 검증용) |
| `gemini-3.7-flash-low` | `gemini-3.7-flash-low` | Gemini | X (`False`) | Gemini 3.7 Flash 수동 지정 전용 (3.8 롤백 및 비교 검증용) |
| `qwen-plus` | `qwen3.7-plus` | Alibaba | O (`True`) | reviewer 주 모델, 기타 역할의 fallback |
| `deepseek-pro` | `deepseek-v4-pro` | Alibaba | X (`False`) | 복잡한 SQL·RAG·레이턴시 회귀 분석 (자동 배정 제외, 명시 지정 전용) |
| `glm` | `glm-5.2` | Alibaba | X (`False`) | 독립 교차 검토 (자동 배정 제외, 명시 지정 전용) |
| `qwen-max` | `qwen3.8-max-preview` | Alibaba | X (`False`) | 상신/충돌 판정용 (자동 배정 제외, 명시 지정 전용) |
| `qwen-max-legacy` | `qwen3.7-max` | Alibaba | X (`False`) | 레거시 모델 (신규 자동 배정 제외) |
| `claude-sonnet` | `claude-sonnet-5` | Claude | O (`True`) | 로컬 Claude Pro 수동 보조 워커 (TIER_POLICY 자동 배정 제외, WORKER_MODEL_NOTICE 후 명시 배정) |

`gemini-3.7-flash-*`, `deepseek-pro`, `glm`, `qwen-max` 모델은 `auto_selectable=False`로 설정되어 자동 배정되지 않으며, `--model` 명시 지정과 `WORKER_MODEL_NOTICE`를 거쳐야 사용됩니다.

리뷰어에 빌더와 같은 모델 계열을 배정하지 않습니다. 같은 추론 편향이 검토를 그대로 통과시키기 때문입니다. 현재 정책에서 빌더가 Gemini 계열(`gemini-flash-*`)인 동안 리뷰어는 `qwen-plus`(Alibaba Token Plan)입니다.

---

## 2. 가용성 실측 (2026-08-30, Qwen Code v0.22.3)

등록 전에 이 저장소에서 `qwen -m <ID> -p ping` 으로 직접 확인한 결과입니다.

| 모델 ID | 결과 | 조치 |
| --- | :---: | --- |
| `qwen3.7-plus` | 응답 | 등록 (L1) |
| `deepseek-v4-pro` | 응답 | 등록 (L2) |
| `glm-5.2` | 응답 | 등록 (L3) |
| `qwen3.8-max-preview` | 응답 | 등록 (L4) |
| `qwen3.7-max` | 응답 | 등록하되 자동 배정 제외 |
| `qwen3.8-max` | **401 인증 오류** | **미등록** |
| `qwen3.8-flash` | **401 인증 오류** | **미등록** |

두 가지를 기록해 둡니다.

첫째, 공개 문서는 `qwen3.8-max-preview` 를 쓰면 `qwen3.8-max` 로 라우팅된다고
안내하므로 ID 를 `qwen3.8-max` 로 갱신하는 것이 옳아 보입니다. **이 계정에서는
반대입니다.** 동작하는 것은 preview ID 이고 `qwen3.8-max` 는 401 입니다. 문서가
안내하는 ID 가 이 계정에서 동작한다는 보장이 없으므로 등록 전 probe 가 필수입니다.
이것이 이번 조사에서 실제로 막은 유일한 오배정입니다.

둘째, `qwen3.8-flash` 는 경량·대량 워커의 비용을 한 단계 더 내릴 후보였으나 이
계정에서는 쓸 수 없습니다. Token Plan 등급이 바뀌면 다시 probe 해서 판단합니다.

---

## 3. 가용성 실측 (2026-09-04, Claude Code v2.1.259)

등록 전에 이 환경의 로컬 Claude Code CLI(`/opt/homebrew/bin/claude`)로 직접 확인한 결과입니다.

| 모델 ID | 결과 | canonicalModel | provider | contextWindow | 조치 |
| --- | :---: | :---: | :---: | :---: | --- |
| `claude-sonnet-5` | 응답 (코드 0) | `claude-sonnet-5` | `firstParty` | 1,000,000 | 풀 등록 (`claude-sonnet`) |
| `sonnet` | 응답 (코드 0) | `claude-sonnet-5` | `firstParty` | 1,000,000 | 별칭 확인 |

핵심 확인 사실 및 운용 정책:

1. **실행 환경 및 실측 결과**: `/opt/homebrew/bin/claude` 2.1.259 (Claude Code)가 Claude Pro 구독 기반으로 canonical model `claude-sonnet-5`, contextWindow 1,000,000, effort `medium`에서 정상 응답함을 확인했다.
2. **성공 호출 형식**: `claude -p ping --model claude-sonnet-5 --effort medium --output-format json --tools "" --no-session-persistence --safe-mode` 형식으로 호출하며 정상 응답(`result: pong`, 종료 코드 0)을 수신한다.
3. **전송 경로와 모델 패밀리 분리**: 기존 `claude-sonnet-4-6`은 Antigravity(`agy`) 경로였으며 이번 워커 대상이 아니다. `claude-opus-thinking` 등 Antigravity Claude 풀은 `agy` probe 경로를 유지하고, `claude-sonnet` 풀만 로컬 Claude CLI(`claude-cli`) 전용 probe 전송 경로를 사용한다. 리뷰어 독립성 판정을 위한 모델 패밀리 `provider_for_model`은 `claude` 값을 그대로 유지한다.
4. **수동 보조 워커 정책**: Gemini `TIER_POLICY` 자동 배정은 변경하지 않으며, `claude-sonnet`은 자동 fallback에 추가되지 않는다. Claude Pro Sonnet 5는 `WORKER_MODEL_NOTICE`를 남긴 후 `--model claude-sonnet-5 --effort medium`으로 명시 배정하는 수동 보조 워커로 운용한다.

---

## 4. probe 응답 본문 검사 (방어적 보강)

`probe_model` 은 종료 코드로 가용성을 판정합니다. 2026-08-30 실측에서 Qwen Code
CLI 는 인증 실패와 미지원 모델에 **종료 코드 1 과 stderr 오류**를 돌려주므로 기존
게이트가 이미 올바르게 거부합니다. `qwen3.8-max` 와 `qwen3.8-flash` 도 이 경로로
걸러졌습니다.

`STDOUT_ERROR_MARKERS` 는 실재한 구멍을 막은 것이 아니라 **앞으로 등록될 CLI 를
위한 방어적 보강**입니다. 종료 코드 0 으로 끝내면서 오류를 응답 본문에 적는 CLI 가
들어오면 종료 코드만으로는 죽은 모델을 걸러내지 못합니다. 그때 본문의 오류 표지를
함께 보고 fail-closed 로 막습니다.

> **측정 함정 기록**: 최초 조사에서 이 동작을 "종료 코드 0, stdout 에 오류" 로
> 잘못 기록했습니다. 원인은 CLI 가 아니라 확인에 쓴 셸 명령입니다.
> `out=$(cmd 2>&1 | tail -3); echo $?` 는 `cmd` 가 아니라 **`tail` 의 종료 코드**를
> 읽고, `2>&1` 이 stderr 를 stdout 처럼 보이게 합니다. CLI 의 종료 코드와 스트림을
> 확인할 때는 파이프와 `2>&1` 없이 파일로 분리해 측정하십시오.

---

## 5. 워커 기동

Qwen Code 워커는 [`scripts/orca_qwen_launch.py`](../../scripts/orca_qwen_launch.py)
로 띄웁니다. 터미널을 먼저 만들고 나중에 명령을 밀어 넣으면 Orca 가 그 터미널을
에이전트 터미널로 등록하지 않아 좌측 목록에 워커 행이 생기지 않고, 사용자가 진행을
눈으로 볼 수 없습니다.

```bash
orca terminal create --worktree path:<워크트리> --title "<섹션명>" \
  --command "uv run python scripts/orca_qwen_launch.py --model qwen-plus"
orca orchestration dispatch --task <task_id> --to <handle> --return-preamble --json
# 결과의 preamble 을 <워크트리>/.orca/preamble.txt 로 쓰면 런처가 이어받습니다
```

런처는 등록되지 않은 모델 ID 를 기동 전에 거부합니다. 미등록 ID 로 띄우면 화면에는
워커가 뜬 채 인증 오류만 답하므로 사람이 원인을 찾기 어렵습니다.

Kimi 런처와 다른 점은 기본이 `-i` 라는 것입니다. 지시문을 실행한 뒤 대화형 세션이
남으므로 코디네이터가 `orca terminal send` 로 후속 지시와 반려 사유를 같은 세션에
보낼 수 있습니다. `--one-shot` 을 주면 `-p` 단발 실행으로 바뀝니다.

---

## 6. 자동 승인 모드

Qwen Code 는 **기동 시점부터 Auto mode** 이고 `shift+tab` 은 그 모드를 벗어나는
순환 키입니다. 따라서 Antigravity 계열과 달리 모드 전환 키를 보내지 않습니다.
보내면 오히려 자동 승인을 끄게 됩니다. `orca_taskctl.py` 의
`classify_file_edit_auto_approve_support` 가 `cli_type` 또는 모델 ID 로 Qwen 계열을
판정해 fail-closed 로 전송을 건너뜁니다.

---

## 7. 워커에 위임하지 않는 판정

다음은 모델 등급과 무관하게 코디네이터가 직접 판단합니다.

- G1 데이터 무손실 판정
- G3 컷오버 판정
- `main` 병합 판정
- 승격 및 게이트 통과 판정

L4 상신 모델을 쓰더라도 이 네 가지는 위임하지 않습니다.

---

## 8. 실적 관찰 항목

단가만으로 워커를 고르지 않습니다. **싼 워커가 코디네이터 검증을 30분 더 쓰게
만들면 실제로는 비싼 워커입니다.** 이 저장소의 조율 설계는 코디네이터 검증 비용을
핵심 자원으로 봅니다. 다음을 관찰해 배정표를 갱신합니다.

| 항목 | 의미 |
| --- | --- |
| Task 성공률 | 반려 없이 acceptance 를 통과한 비율 |
| 재작업 횟수 | rework Task 발급 건수 |
| `worker_done` 까지 wall-clock | 대기 시간 포함 실제 소요 |
| 코디네이터가 고친 LOC | 워커 산출물 보정량 |
| 계약 위반 | 커밋 누락, 허용 범위 이탈, 검증 명령 미실행 |

2026-08-30 E4 사례를 기준선으로 둡니다. 무료 풀 `or-free/minimax-m3` 워커가 측정
자체는 완주했으나 분석 문서에서 원시 JSON 과 어긋나는 수치 4건을 냈고 Capsule 이
지정한 검증 명령 2개 중 1개를 실행하지 않았습니다. 코디네이터가 전량 검산해야
했습니다.
