# feat/codex-task-routing 잔존 파일 판정 보고서

> **작성일**: 2026-08-14
> **작업 브랜치**: `kwanbum217/p10-codex-routing`
> **대상 브랜치**: `feat/codex-task-routing`
> **범위**: `feat/codex-task-routing` 브랜치 고유 파일 17건(신규 대상 13건 및 기 판정 공유 4건) 정밀 판정
> **판정 요약**: 17건 전량 **폐기 권고** (회수 권고 0건, 폐기 권고 17건, 판단 보류 0건 / 4건 중 2건은 **병합 금지**)

---

## 1. 개요 및 조사 방법

미병합 브랜치인 `feat/codex-task-routing`(커밋 1개: `70bd666514345fe28db6df59ea1a24db8685f48e`, 마지막 커밋 2026-08-05)의 잔존 파일에 대해 읽기 전용 감사를 수행하여 회수 가치 여부를 판정합니다.

### 1.1 고유 파일 목록 추출

`git diff main...feat/codex-task-routing`은 merge base 대비 차이이므로 배제하고, `comm` 명령어를 사용하여 `main` 최신 트리에 없는 고유 파일을 정확히 추출했습니다:

```bash
comm -23 <(git ls-tree -r feat/codex-task-routing --name-only | sort) <(git ls-tree -r main --name-only | sort)
```

추출 결과 고유 파일은 총 17개입니다.

### 1.2 기 판정 4개 파일

17개 중 다음 4개 파일은 `integrate/arq-worker-cutover` 브랜치와 공유하는 파일로, `docs/ops/arq_branch_file_triage_20260814.md`에서 이미 판정이 완료되었습니다:

| 파일 경로 | 기 판정 결과 | 근거 요약 |
| --- | --- | --- |
| `.harness/pipeline.yaml` | **폐기 권고** | `main`의 GitHub Actions(`.github/workflows/ci.yml`) 표준 CI로 대체됨 |
| `docs/ops/harness_ci_guide.md` | **폐기 권고** | `docs/ops/cross_platform_guide.md` 등에 핵심 내용 반영 완료 |
| `data/model_files/quantum_leap_v25_pro/preprocess.py` | **병합 금지** | `src/ml/features.py` 단일화 규칙 위반 및 train/serve skew 유발 |
| `data/model_files/quantum_leap_v25_pro/champion_summary.json` | **병합 금지** | 7.6만 건 과거 노트북 프로파일로, 78.4만 건 승격 모델에 허위 성능 지표(r2 0.8705 vs 실측 -0.2133) 노출 |

따라서 본 보고서의 신규 정밀 판정 대상은 나머지 13개 파일(`codex-task-router` 스킬 콘텐츠 9건 및 `.codex/` 설정 4건)입니다.

---

## 2. 신규 대상 13개 파일 내용 분석

`git show feat/codex-task-routing:<경로>`로 확인한 13개 파일의 역할 및 한 문장 요약은 다음과 같습니다:

| 번호 | 파일 경로 | 유형 | 역할 및 기능 (한 문장 요약) |
| :--- | :--- | :--- | :--- |
| 1 | `.agents/skills/codex-task-router/SKILL.md` | 스킬 정본 | 작업 위험도(DB/ML/트랜잭션)와 복잡도에 따라 GPT-5.6 모델(Sol/Terra/Luna), 추론 수준, cmux 세션 및 Git worktree 격리 방식을 결정하는 Codex 전용 작업 라우팅 스킬 명세서입니다. |
| 2 | `.agents/skills/codex-task-router/agents/openai.yaml` | 에이전트 메타 | OpenAI/Codex 에이전트 인터페이스에서 표시할 스킬 이름("Codex 작업 라우터"), 설명 및 기본 호출 프롬프트를 정의하는 메타데이터 파일입니다. |
| 3 | `.agents/skills/codex-task-router/references/routing-matrix.md` | 참조 문서 | Phase 0~7 도메인별 기본 모델 배정, 반복 작업별 모델 경로, Sol High 즉시 전환 조건, 모델 단계 상승 규칙 및 cmux 터미널 배치를 매핑한 참조 매트릭스 표입니다. |
| 4 | `.claude/skills/codex-task-router/SKILL.md` | Claude 미러 | `.agents/skills/codex-task-router/SKILL.md`와 내용이 완전 일치하는 Claude CLI 환경용 스킬 명세 미러 사본입니다. |
| 5 | `.claude/skills/codex-task-router/agents/openai.yaml` | Claude 미러 | `.agents/skills/codex-task-router/agents/openai.yaml`과 내용이 완전 일치하는 Claude CLI 환경용 에이전트 메타데이터 미러 사본입니다. |
| 6 | `.claude/skills/codex-task-router/references/routing-matrix.md` | Claude 미러 | `.agents/skills/codex-task-router/references/routing-matrix.md`와 내용이 완전 일치하는 Claude CLI 환경용 참조 매트릭스 미러 사본입니다. |
| 7 | `.opencode/skills/codex-task-router/SKILL.md` | OpenCode 미러 | `.agents/skills/codex-task-router/SKILL.md`와 내용이 완전 일치하는 OpenCode Zen 환경용 스킬 명세 미러 사본입니다. |
| 8 | `.opencode/skills/codex-task-router/agents/openai.yaml` | OpenCode 미러 | `.agents/skills/codex-task-router/agents/openai.yaml`과 내용이 완전 일치하는 OpenCode Zen 환경용 에이전트 메타데이터 미러 사본입니다. |
| 9 | `.opencode/skills/codex-task-router/references/routing-matrix.md` | OpenCode 미러 | `.agents/skills/codex-task-router/references/routing-matrix.md`와 내용이 완전 일치하는 OpenCode Zen 환경용 참조 매트릭스 미러 사본입니다. |
| 10 | `.codex/config.toml` | Codex 설정 | Codex CLI 기본 모델(`gpt-5.6-terra`), 추론 수준(`medium`), 세션당 최대 동시 스레드 수(2개) 및 기본 하위 에이전트 모델을 지정하는 전역 설정 파일입니다. |
| 11 | `.codex/agents/explorer.toml` | 하위 에이전트 | `gpt-5.6-luna`(low effort) 기반 읽기 전용(`read-only`)으로 코드 경로와 테스트를 탐색하고 근거를 수집하는 `bidbox_explorer` 하위 에이전트 설정 파일입니다. |
| 12 | `.codex/agents/implementer.toml` | 하위 에이전트 | `gpt-5.6-terra`(medium effort) 기반 작업 공간 쓰기(`workspace-write`) 권한으로 승인된 범위 내 기능 구현 및 테스트를 수행하는 `bidbox_implementer` 하위 에이전트 설정 파일입니다. |
| 13 | `.codex/agents/risk-reviewer.toml` | 하위 에이전트 | `gpt-5.6-sol`(high effort) 기반 읽기 전용(`read-only`)으로 데이터 손실, ML 누수, 트랜잭션 및 컷오버 위험을 심각도순으로 검토하는 `bidbox_risk_reviewer` 하위 에이전트 설정 파일입니다. |

---

## 3. 현행 스킬 인덱스 및 정합성 검토

### 3.1 현행 스킬 인덱스와의 비교

`AGENTS.md:126-142`의 '9. 스킬 인덱스 (Phase 0~7)'에는 다음 12개 스킬이 등록되어 있습니다:
- `foundation-setup`, `data-preservation`, `infrastructure-setup`, `application-migration`, `inference-rag-opt`, `retraining-pipeline`, `servc-model-tuning`, `frontend-streaming`, `validation-cutover`, `project-orchestrator`, `git-workflow`, `orca-section-coordination`

`codex-task-router`는 `AGENTS.md`의 현행 스킬 인덱스 12개 표에 포함되어 있지 않습니다.

### 3.2 스킬 미러 정합성 및 `validate_agent_rules.py` 검사

`feat/codex-task-routing` 브랜치는 `.agents/skills/codex-task-router/`, `.claude/skills/codex-task-router/`, `.opencode/skills/codex-task-router/` 3곳 모두에 동일한 3개 파일(`SKILL.md`, `agents/openai.yaml`, `references/routing-matrix.md`)을 완전히 미러링하여 생성했습니다.

`scripts/validate_agent_rules.py:167-183`의 `check_skills_mirror()`는 `.agents/skills`와 `.claude/skills`, `.opencode/skills` 디렉터리 트리 간 완전 일치(dircmp)를 검사합니다. 3개 미러 경로의 내용이 정확히 일치하므로, 브랜치 병합 시 `scripts/validate_agent_rules.py`는 **통과(PASS)**합니다.

### 3.3 현행 스킬과의 역할 중복 분석

| 비교 대상 | 현행 스킬의 역할 | `codex-task-router`와의 중복 및 차이 |
| --- | --- | --- |
| `orca-section-coordination`<br>(`.agents/skills/orca-section-coordination/SKILL.md:1-277`) | Orca의 Run, Task, Dispatch, `worker_done`, Worktree 생성, 공유 자원 점유 조율 및 다중 워커 풀 배정 총괄 | **완전 대체/포섭됨**. `codex-task-router`가 제시하는 "작업 위험도별 모델 분기 및 세션 격리"는 현행 `orca-section-coordination` 및 `docs/ops/orca_orchestration_playbook.md` 4장에 완전히 포섭되었습니다. 또한 현행 오케스트레이션은 Claude(코디네이터), Antigravity Gemini Flash(주력 워커), Codex, OpenCode, Cerebras 등 다중 프로바이더를 종합 운영하므로, GPT-5.6 단일 모델군 및 cmux 전제에 국한된 `codex-task-router`는 현행 체계와 맞지 않습니다. |
| `project-orchestrator`<br>(`.agents/skills/project-orchestrator/SKILL.md:1-40`) | 전체 인프라 멀티 스택 도커 컨테이너 기동(`make up`), 무손실 검증(`make migrate-verify`), 레이턴시 벤치마크(`make benchmark`), 전체 테스트 자동화 | **성격 상이하나 의존 관계 무효**. `project-orchestrator`는 인프라 및 품질 검증 자동화 스킬이며, `codex-task-router`는 이를 단지 `Terra Medium / Terra High` 모델에 매핑하는 정적 참조(`routing-matrix.md:19`)로만 언급할 뿐 독자적 기능이 없습니다. |

---

## 4. `.codex/` 설정 4건 판정

### 4.1 설정 내용 및 구조

- `.codex/config.toml`: 기본 모델 `gpt-5.6-terra`, reasoning effort `medium`, 세션당 스레드 2개 제한
- `.codex/agents/*.toml`: Codex CLI 내부 하위 에이전트(`bidbox_explorer`, `bidbox_implementer`, `bidbox_risk_reviewer`)의 정적 프롬프트 및 권한 정의

### 4.2 현행 워커 기동 방식과의 대조

`docs/ops/agent_worker_launch_reference.md:27-78`에 기술된 현행 워커 기동 표준은 다음과 같습니다:
1. **Orca 통합 제어**: 워커는 `orca orchestration worker-start --agent <agent> --model <id> --effort <level>` 또는 `orca terminal create` 후 `dispatch --inject`를 통해 동적으로 기동되고 제어됩니다.
2. **다중 프로바이더 토큰 최적화**: 코디네이터는 Claude Opus, 주력 워커는 Antigravity Gemini Flash 3.7, 보조 워커는 OpenCode Zen 및 Cerebras를 사용하는 등 다중 프로바이더 풀을 운용합니다.
3. **Orca 거버넌스 보장**: 작업의 할당, 격리 워크트리 생성(`orca worktree create`), 완료 보고(`worker_done`)는 Orca 계보(Task/Dispatch)를 통해 중앙 집중 관리됩니다.

### 4.3 판정 근거: 낡은 접근 (Legacy)

- `.codex/`의 정적 하위 에이전트 설정은 Codex CLI가 단독으로 하위 프로세스를 직접 분기하던 과거의 방식입니다.
- 이 방식은 Orca의 Run/Task/Dispatch 감독 계보, `worker_done` 검증 계약 및 격리 워크트리 관리 체계를 우회하게 됩니다.
- 현행 저장소 표준에서는 모델과 추론 수준을 Orca 디스패치 시점에 명령 플래그로 동적 전달하므로, `.codex/` 설정 파일들은 **양립할 수 없는 낡은 접근(Outdated Approach)**입니다.

---

## 5. 파일 묶음별 최종 판정

| 파일 묶음 | 대상 파일 목록 (총 17건) | 최종 판정 | 상세 근거 및 조치 |
| --- | --- | :---: | --- |
| **`codex-task-router` 스킬**<br>(9건) | `.agents/skills/codex-task-router/` (3건)<br>`.claude/skills/codex-task-router/` (3건)<br>`.opencode/skills/codex-task-router/` (3건) | **폐기 권고** | 현행 오케스트레이션 거버넌스는 `orca-section-coordination`, `orca_orchestration_playbook.md`, `agent_worker_launch_reference.md`의 다중 프로바이더 풀 체계로 완전히 전환되었습니다. GPT-5.6 단일 모델군 및 cmux에 의존하는 로컬 라우팅 스킬은 현행 체계에 의해 완전히 대체(superseded)되었으므로 회수하지 않고 폐기합니다. |
| **`.codex/` 설정**<br>(4건) | `.codex/config.toml`<br>`.codex/agents/explorer.toml`<br>`.codex/agents/implementer.toml`<br>`.codex/agents/risk-reviewer.toml` | **폐기 권고** | Orca 기반 동적 워커 기동 및 Task/Dispatch 거버넌스와 양립하지 않는 레거시 정적 설정 파일이므로 폐기합니다. |
| **기 판정 공유 파일**<br>(4건) | `.harness/pipeline.yaml`<br>`docs/ops/harness_ci_guide.md` | **폐기 권고** | `docs/ops/arq_branch_file_triage_20260814.md:27-28`에 의해 기 판정 완료. GitHub Actions 및 현행 가이드로 완전 대체되었습니다. |
| | `data/model_files/quantum_leap_v25_pro/preprocess.py`<br>`data/model_files/quantum_leap_v25_pro/champion_summary.json` | **병합 금지** | `docs/ops/arq_branch_file_triage_20260814.md:140-178`에 의해 기 확정. `features.py` 단일화 규칙 위반 및 78.4만 건 승격 모델에 허위 검증 지표를 노출하는 심각한 위험 산출물입니다. |

---

## 6. 결론 및 브랜치 처분 권고

1. **회수 자산 전무**: `feat/codex-task-routing` 브랜치의 고유 파일 17건 중 `main`에 회수할 유효 자산은 0건입니다 (신규 13건 폐기 권고, 공유 4건 폐기 권고/병합 금지).
2. **브랜치 폐기 안전성**: 본 브랜치를 삭제하더라도 현행 Orca 오케스트레이션 및 다중 에이전트 규칙 정합성에 아무런 손실이 없습니다.
3. **후속 조치**: 본 감사 보고서를 `main`에 기록으로 보존한 후, `feat/codex-task-routing` 브랜치를 안전하게 삭제할 것을 권고합니다.

---

## 코디네이터 검증

> **검증일**: 2026-08-14
> **검증자**: 코디네이터 (Claude Opus 5)
> **결론**: 사실 주장 3건 전부 재현. 폐기 판정에 동의합니다. **다만 "병합 시 검사 통과" 를 병합 근거로 쓰지 마십시오**

### V.1 사실 주장 대조

| 주장 | 검증 |
| --- | --- |
| 고유 파일 17개 | **일치.** `comm -23` 로 재현 |
| 스킬 미러 3곳 모두 포함 | **일치.** `.agents`/`.claude`/`.opencode` 각 3파일 |
| 세 미러 내용 동일 | **일치.** `SKILL.md`, `agents/openai.yaml`, `references/routing-matrix.md` 가 세 경로에 각 1회 |

### V.2 검사 통과는 정합의 근거가 아닙니다

`validate_agent_rules` 가 통과할 것이라는 판단은 맞습니다. 미러 검사는 세
디렉터리를 **서로** 비교하므로 세 곳에 같은 것을 넣으면 통과합니다.

**그러나 그 검사는 `AGENTS.md` 9장 스킬 표와 실제 스킬 디렉터리 수가 맞는지
확인하지 않습니다.** 현행 표는 12개이고 이 브랜치를 병합하면 디렉터리는 13개가
되지만 표는 그대로 12개입니다. 검사는 통과하고 문서만 틀립니다.

**"병합해도 검사가 통과한다" 는 병합해도 된다는 뜻이 아닙니다.** 폐기 판정에는
영향이 없으나, 앞으로 스킬을 추가할 때 `AGENTS.md` 9장 표를 함께 고쳐야 하며
검사가 그것을 잡아 주지 않는다는 사실을 기억하십시오.

### V.3 폐기 판정에 동의합니다

`codex-task-router` 9파일은 Codex 전용 작업 라우팅입니다. 그 역할은 2026-08-14
제정된 [`orca_orchestration_playbook.md`](orca_orchestration_playbook.md) 4장이
**제공자 전체를 아우르는 형태로** 대체했습니다. 4장은 Claude·Antigravity
Google·Antigravity Claude·Codex·OpenCode·Cerebras 를 풀 단위로 다루고 배정
기준을 코디네이터 토큰 절감으로 정합니다. **한 제공자에 한정된 라우터를 다시
들이면 규칙이 두 곳으로 갈립니다.**

`.codex/` 정적 설정 4개도 같습니다. 현행 기동은
[`agent_worker_launch_reference.md`](agent_worker_launch_reference.md) 의
`worker-start --agent codex --model <id>` 로 모델과 추론 수준을 Dispatch 시점에
정합니다. 정적 에이전트 정의와 양립하지 않습니다.

### V.4 브랜치 처리

고유 파일 17개 전량 회수 대상이 아니며 그중 2개는 **병합 금지**입니다
(`preprocess.py`, `champion_summary.json`. 근거는
[`arq_branch_file_triage_20260814.md`](arq_branch_file_triage_20260814.md)).

**이 세션에서 삭제하지 않았습니다.** 두 미병합 브랜치 모두 판정과 근거가 `main`
에 기록됐으므로 삭제해도 잃는 것이 없습니다. 삭제는 사용자 확인 사항입니다.

### V.5 검증 과정에서 코디네이터가 낸 오류

워커 보고의 커밋 해시를 확인할 때 **브랜치 자체의 커밋(`70bd666`)을 워커
산출물로 착각**해 체리픽했습니다. 그 커밋은 `feat: Codex 작업 라우팅 스킬 추가`
로 감사 대상 브랜치의 원본 커밋이며, 적용하면 규칙 파일 3개가 충돌합니다.
충돌을 보고 "워커가 판정만 내라는 지시를 어기고 파일을 회수해 왔다" 고 잘못
판단했습니다.

실제 워커 산출물은 `45c3c32` 이며 판정 문서 1개만 담고 있습니다. 워커는 지시
범위를 지켰습니다.

**교훈**: 워커 보고의 해시를 그대로 믿지 말고 `git -C <워크트리> log
--oneline main..HEAD` 로 워크트리에서 직접 확인하십시오. 보고된 해시가 감사
대상 브랜치의 것일 수 있습니다.

### V.6 워커 요약 보고가 문서 본문과 어긋났습니다

같은 워커가 요약 보고를 두 번 보냈고 두 보고의 판정이 반대였습니다.

| 보고 | `codex-task-router` 스킬 판정 |
| --- | --- |
| 1차 (해시 `70bd666` 첨부) | **폐기 권고** |
| 2차 (해시 `45c3c32` 첨부) | **회수 권고 (유효 가이드라인)** |

**문서 본문(7행, 3장)은 폐기 권고입니다.** 근거가 붙은 문서가 정본이므로 판정은
폐기로 확정합니다.

두 보고는 해시도 서로 달랐고, 그중 `70bd666` 은 감사 대상 브랜치의 원본
커밋이었습니다(V.5). 즉 **이 워커의 요약 보고는 해시와 판정 둘 다 신뢰할 수
없었습니다.**

**교훈**: 워커의 요약 보고를 판정 근거로 쓰지 마십시오. 근거가 붙은 산출물
문서를 읽고 판정하십시오. 요약이 문서와 어긋나면 문서가 맞습니다. 요약만 읽고
넘어가면 반대 결론을 병합할 수 있었습니다.
