# Orca 워커 모델 풀 정본

> **작성일**: 2026-08-30
> **버전**: v1.0.0
> **배정표 정본**: [`scripts/orca_model_router.py`](../../scripts/orca_model_router.py) 의 `TIER_POLICY`
> 본 문서는 배정 근거와 가용성 실측을 기록합니다. 실제 배정은 코드가 결정하며, 문서와
> 코드가 어긋나면 코드가 정본입니다.

---

## 1. 4계층 구조

| 계층 | 풀 키 | 모델 ID | 배정 대상 |
| :---: | --- | --- | --- |
| L1 범용 | `qwen-plus` | `qwen3.7-plus` | 일반 구현, 테스트 작성·수정, 문서 정합성, 읽기 전용 조사 |
| L2 전문 | `deepseek-pro` | `deepseek-v4-pro` | 복잡한 SQL·RAG·레이턴시 회귀 원인 분석, high 위험도 구현 |
| L3 리뷰 | `glm` | `glm-5.2` | 독립 검토, 교차검증, 긴 문서·로그 분석 |
| L4 상신 | `qwen-max` | `qwen3.8-max-preview` | 앞의 셋이 실패했거나 두 워커의 결론이 충돌할 때의 제3 판정 |
| fallback | `gemini-flash-*` | `gemini-3.7-flash-*` | 신규 풀 장애 시 대체. 분석·감사·측정의 검증된 이력 보유 |
| 제외 | `qwen-max-legacy` | `qwen3.7-max` | 신규 자동 배정 제외 (`auto_selectable=False`) |

리뷰어에 빌더와 같은 모델 계열을 배정하지 않습니다. 같은 추론 편향이 검토를
그대로 통과시키기 때문입니다. 그래서 빌더가 Qwen 계열일 때 리뷰어는 GLM 입니다.

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

## 3. probe 응답 본문 검사 (방어적 보강)

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

## 4. 워커 기동

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

## 5. 자동 승인 모드

Qwen Code 는 **기동 시점부터 Auto mode** 이고 `shift+tab` 은 그 모드를 벗어나는
순환 키입니다. 따라서 Antigravity 계열과 달리 모드 전환 키를 보내지 않습니다.
보내면 오히려 자동 승인을 끄게 됩니다. `orca_taskctl.py` 의
`classify_file_edit_auto_approve_support` 가 `cli_type` 또는 모델 ID 로 Qwen 계열을
판정해 fail-closed 로 전송을 건너뜁니다.

---

## 6. 워커에 위임하지 않는 판정

다음은 모델 등급과 무관하게 코디네이터가 직접 판단합니다.

- G1 데이터 무손실 판정
- G3 컷오버 판정
- `main` 병합 판정
- 승격 및 게이트 통과 판정

L4 상신 모델을 쓰더라도 이 네 가지는 위임하지 않습니다.

---

## 7. 실적 관찰 항목

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
