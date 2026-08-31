# Task `task_50768bf0d9de` 조사 결과: qwen3.7-plus 리뷰어 JSON 비응답 간헐성

> **작성 Task**: `task_50768bf0d9de`
> **Run**: `run_428567a2da1f`
> **역할**: investigator (읽기 전용 + 분석 문서 1건 작성)
> **조사 일자**: 2026-08-31
> **결론 요약**: qwen3.7-plus 의 JSON 비응답 원인을 **확정적으로 좁히지 못함**.
> 재현 조건 후보 4개를 코드 근거와 함께 제시하고, 어느 후보도 현재 데이터로 단정할 수 없음을 명시한다.

---

## 1. 발단 사실 (확인됨)

- 2026-08-31 에 qwen3.7-plus 리뷰어가 JSON 이 아닌 응답을 두 번 연속 돌려주어 실패했다.
  - 출처: `docs/ops/handoff_20260831_wave_gh.md:96-100`
- 같은 날 Wave G4 검증에서는 정상 완주했으므로 간헐적이다.
  - 출처: `docs/ops/handoff_20260831_wave_gh.md:96-98`
- 현재 실무 대체재는 claude-sonnet-4-6 이다. Antigravity 5시간 한도를 쓴다.
  - 출처: `docs/ops/handoff_20260831_wave_gh.md:98-100`
- TIER_POLICY 의 reviewer 주 모델은 qwen-plus 이다. (`scripts/orca_model_router.py:1109-1114`)
  - `("reviewer", "high"): ["qwen-plus", "gemini-flash-high"]`
  - `("reviewer", "medium"): ["qwen-plus", "gemini-flash-medium"]`
  - `("reviewer", "low"): ["qwen-plus", "gemini-flash-medium"]`
- 2026-08-30 에 qwen3.7-plus 는 probe 응답으로 정상 작동했다.
  - 출처: `docs/ops/orca_worker_model_pool.md:61`
- 2026-08-31 에 코디네이터가 qwen-plus 를 다시 probe 했고 사용 가능으로 응답했다.
  - 출처: Capsule `ground_truth` (코디네이터 확인 사실)

---

## 2. 저장소에 남아 있는 실패 원문(.raw) 존재 여부

**결과: 저장소에 .raw 파일이 없다.**

조사 절차:

```bash
find . -path ./.git -prune -o -name "*.raw" -print -o -name "*.raw*" -print
```

반환된 경로 0건. 추가로:

```bash
find . -path ./.git -prune -o -iname "*reviewer*raw*" -print
```

역시 0건. `.orca/reports/` 디렉터리 자체가 존재하지 않는다
(현재 작업 디렉터리 기준).

**해석**: `.raw` 파일은 `scripts/orca_run_reviewer.py:547-552` 가 매 실패마다
`{out_path}.raw` 로 저장하지만, 두 번의 실패가 일어난 워크트리에서 해당 파일이
현재 작업 디렉터리로 옮겨지지 않았거나 정리된 것으로 보인다. **원문을 확보하지
못했으므로 응답 형태(코드펜스, 서두 설명, 잘림, 다중 JSON 등)를 실측할 수 없다.**

이 점이 본 조사에서 가장 큰 제약이다. 아래 분석은 **가능한 후보를 추리는 것**까지만
가능하며, 후보들 중 어느 것이 진짜 원인인지는 **별도 재현 실험으로만** 좁혀진다.

---

## 3. `extract_json_from_response` 가 거부하는 형태 (코드 정확 서술)

위치: `scripts/orca_run_reviewer.py:322-345`.

```python
def extract_json_from_response(raw_text: str) -> tuple[dict[str, Any] | None, str]:
    """모델 응답에서 JSON 객체를 관대하게 추출합니다.

    첫 번째 여는 중괄호 '{' 부터 마지막 닫는 중괄호 '}' 까지를 추출하여 파싱합니다.
    성공 시 (dict, ""), 실패 시 (None, 에러사유).
    """
    if not raw_text or not raw_text.strip():
        return None, "응답 텍스트가 비어 있음"

    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None, "응답에서 JSON 객체 중괄호({...})를 찾을 수 없음"

    candidate = raw_text[start : end + 1]
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return None, f"JSON 디코딩 실패: {exc}"

    if not isinstance(data, dict):
        return None, "추출된 JSON 최상위가 객체(dict)가 아님"

    return data, ""
```

판정 매트릭스 (확인됨, 코드에서 직접 도출):

| 응답 형태 | 통과/거부 | 근거 |
| --- | --- | --- |
| 순수 JSON 객체 1개 | 통과 | `start..end` 구간이 그대로 파싱됨 |
| 앞뒤에 설명문 + JSON 1개 | 통과 | `find("{")` / `rfind("}")` 가 첫·마지막 중괄호를 잡음 |
| 마크다운 코드펜스(```json ... ```) 안의 JSON | 통과 | 위와 동일 (테스트 케이스 4 확인, `tests/test_orca_run_reviewer.py:169-194`) |
| 다중 JSON 객체 2개 (앞뒤로 나열) | 통과 | 첫 `{` 와 마지막 `}` 사이가 그대로 파싱되므로 **둘 사이의 모든 텍스트가 후보**가 되어 파싱 실패 가능 |
| 배열 최상위 (`[ ... ]`) | 거부 | `isinstance(data, dict)` 실패, "추출된 JSON 최상위가 객체(dict)가 아님" |
| 중괄호가 전혀 없는 응답 | 거부 | "응답에서 JSON 객체 중괄호({...})를 찾을 수 없음" |
| 빈 응답 | 거부 | "응답 텍스트가 비어 있음" |
| 중괄호는 있지만 JSON 으로 파싱 안 되는 응답 | 거부 | "JSON 디코딩 실패" |
| 잘려서 `}`로 닫히지 않은 응답 | 거부 | `end < start` 또는 파싱 실패 |
| 응답 안에 다른 `{...}` 가 먼저 닫히고 마지막 `}` 가 다른 곳에 있는 경우 | 우연히 파싱되거나 거부 | 첫 `{` 부터 마지막 `}` 까지가 임의의 문자열이라 json.loads 가 실패할 수 있음. **이 형태는 차단 보장 없음.** |

테스트로 검증된 항목:
- 코드펜스 통과: `tests/test_orca_run_reviewer.py:169-194` (`test_json_extraction_from_code_fence`)
- 앞뒤 설명문 통과: `tests/test_orca_run_reviewer.py:196-218` (`test_json_extraction_with_surrounding_text`)
- 빈 응답 거부: `tests/test_orca_run_reviewer.py:406-426` (`test_extract_json_from_response_edge_cases`)
- 배열 거부: 동일 테스트
- 깨진 JSON 거부 + .raw 저장: `tests/test_orca_run_reviewer.py:221-242` (`test_broken_json_saves_raw_file_and_exits_2`)

저장 동작: `scripts/orca_run_reviewer.py:545-560`. 파싱 실패 시 `Path(str(out_path) + ".raw")` 로 stdout 전체를 쓰고 종료 코드 2.

---

## 4. 프롬프트가 JSON 만 내라고 어떻게 요구하는지 (확인됨)

위치: `scripts/orca_run_reviewer.py:187-228` (`build_prompt`).

핵심 지시:

```
=== 반환 형식 및 필수 계약 규칙 ===
1. 반드시 순수한 JSON 객체(ORCA_REVIEW_DONE_V2)만 출력하십시오. 마크다운 코드펜스(```json)나 앞뒤 부가 설명 텍스트를 절대 붙이지 마십시오.
2. `checklist_results` 배열에 위 체크리스트의 모든 ID에 대한 검토 결과를 빠짐없이 포함하십시오.
3. 각 `checklist_results` 항목은 반드시 다음 필드를 포함해야 합니다:
   - `id`: 체크리스트 항목 ID (예: "C1")
   - `answer`: "yes" 또는 "no" (체크리스트 질문에 대한 답변)
   - `evidence`: 판단 근거 (구체적인 파일 경로:줄번호 또는 분석 내용)
4. 중요 결함 규칙:
   - 각 항목의 `answer` 가 해당 항목의 `defect_when` 과 일치하면 결함(Defect)으로 판정됩니다.
   ...
6. 아래 JSON 구조를 준수하십시오:
{{ ... }}
```

(약식 인용; 실제 코드는 `scripts/orca_run_reviewer.py:199-228` 전체)

약점 평가 (확인된 사실 + 추정 구분):

**확인된 약점**:

1. **모델 예시 JSON 본문이 중괄호 두 겹으로 이스케이프되어 있다.** L208 의 `{{ ... }}` 는 Python f-string 이 한 겹을 벗겨내 최종 프롬프트에는 `{ ... }` 가 들어간다. 이 의도적 처리는 정상이다 (`tests/test_orca_run_reviewer.py:483-503` 가 이를 검증).
2. **예시 JSON 안에 `blocking_issues: []`, `unverified_claims: []`, `missing_tests: []` 가 빈 배열로 들어가 있다.** L223-226. 모델이 "빈 배열이면 빼도 되겠지" 라고 과잉 일반화할 여지를 남긴다. 다만 이것만으로 qwen-plus 가 실패한다고 단정할 근거는 없다.
3. **지시 1번에 "절대 붙이지 마십시오" 라고 강하게 못 박고 있으나, 시스템 프롬프트의 계층이 단일 메시지에 평면적으로 적혀 있다.** 다른 모델군(예: claude, gemini)과의 지시 충돌이 없음을 가정한다.
4. **프롬프트에 토큰 수 제한, 출력 형식 검증의 자동 보강(예: "응답이 JSON 인지 스스로 검증하라") 같은 안전망 문구가 없다.** qwen-plus 가 자기 응답을 자가 검증하도록 유도하지 않는다.

**추정 (코드 근거 없음, 추정임)**:

- qwen 계열은 지시 1번의 강도가 부족해서(예시 JSON 본문에 설명이 같이 들어가 헷갈릴 수 있음) 코드펜스나 서두 설명을 붙이는 응답을 일부 생성한다는 외부 평이 있을 수 있으나, 본 조사 범위에서는 **확인할 수 없다**.
- 토큰 Plan 모델은 시스템 프롬프트보다 사용자 메시지 지시를 더 약하게 따르는 경향이 있다는 보편적 평이 있을 수 있으나, qwen3.7-plus 에 한정한 검증은 본 조사 범위 밖이다.

---

## 5. 입력 크기(프롬프트 길이)와 실패의 상관관계

**결과: 상관을 확인할 수 없다.**

확인된 사실:

- DEFAULT_MAX_DIFF_CHARS = 20000 (`scripts/orca_run_reviewer.py:42`).
- 2026-08-31 에 측정된 Task diff 5건: 5,066 / 9,153 / 23,916 / 24,232 / 38,401 자.
  - 출처: Capsule `ground_truth` (`task_92717a9a5e22` 인용 사실)
- 38,401 자 diff 는 기본값을 초과해 절단된다 (`scripts/orca_run_reviewer.py:494-498`).
- 절단된 diff 로 내린 pass 는 truncation_blocks 로 종료 코드 1 이 된다
  (`scripts/orca_run_reviewer.py:589-595`).

추정 (근거 부족, 추정임):

- qwen-plus 가 38,401 자 diff 를 처리하다 잘렸을 가능성이 있지만, **잘림은 JSON 추출 단계가 아니라 diff 단계의 문제이고, JSON 파싱 실패와는 메커니즘이 다르다**. 둘이 섞여 발생할 가능성은 시나리오상 0 은 아니지만 동일 회차에서 동시에 발생할 확률은 낮다.
- 프롬프트의 절단 헤더 (`[주의: diff 본문이 최대 허용 크기를 초과하여 뒷부분이 절단되었습니다.]`, `scripts/orca_run_reviewer.py:175`) 가 qwen-plus 의 추론 경로를 흔들어 비-JSON 응답을 유도했을 가능성. **이 가설은 본 조사에서 검증할 근거를 확보하지 못했다.**

확인할 수 없는 것:

- qwen-plus 의 입력 토큰 한도와 qwen-plus 가 출력 토큰을 정확히 어디까지 쓰는지(`max_tokens = 1_000_000` 은 MODEL_POOL 의 입력 컨텍스트 한도로 추정되지만 출력 상한은 별도일 수 있다).
- 실패한 두 회차의 실제 diff 크기, 변경 파일 수, 체크리스트 항목 수.

---

## 6. 후보 가설 4개 (확정 없음)

| # | 가설 | 지지 근거 (확인됨) | 반증 가능성 (확인됨) | 검증 방법 |
| --- | --- | --- | --- | --- |
| H1 | qwen-plus 출력 끝이 잘렸다 (출력 토큰 상한 도달) | 모델 출력이 잘리면 `}` 가 없어 find/rfind 가 실패 → extract 거부 | 잘림이 발생했는지 알 수 없음 (.raw 부재) | qwen-plus 출력 토큰 상한을 명시적으로 probe 한 적 없음. 동일한 diff 로 5회 반복 실행해 잘림 빈도를 측정 |
| H2 | qwen-plus 가 코드펜스/서두 설명을 무작위로 붙인다 | 추출 함수가 이를 허용하지만, **다른 부가 텍스트**(예: 다중 JSON, 잘린 마크다운)는 거부됨 | 다른 qwen-plus 호출은 정상 완주했다는 사실이 G4 시점 기록에 있음 | 동일 Capsule 로 qwen-plus 를 10회 반복 실행, 응답 형태 분류 |
| H3 | 프롬프트 길이(diff 큼, 체크리스트 많음) 가 모델 추론을 흔든다 | 기본값 20000 자로 정상 diff 5건 중 2건이 절단됨 | 입력이 큰 Task 도 같은 날 정상 완주했다는 사실이 있음 | diff 크기 / 체크리스트 항목 수를 변주해 5회씩 실행 |
| H4 | 외부(Qwen Code CLI / 네트워크 / Token Plan 잔량) 측 일시 장애 | 2026-08-31 에 두 번 연속 실패는 동시 장애보다 직시 장애 시나리오에 부합 | 2026-08-31 같은 날 probe 가 통과했다는 사실 | 같은 시각에 qwen-plus ping 을 다회 반복해 응답 일관성 확인 |

**네 가설 모두 현재 데이터로는 단정할 수 없다.** 확정하려면 다음 중 하나가 필요하다:

1. 실패한 두 회차의 .raw 파일 또는 그 시점 stdout. 현재 저장소에는 없다.
2. 동일 Capsule + diff 로 qwen-plus 를 5회 이상 반복 실행한 표본.
3. qwen-plus 출력 토큰 상한을 명시한 공식 문서 또는 실측.

---

## 7. 코드 수정 제안 (제안일 뿐, 적용하지 않음)

확인된 사실에 근거한, 이번 Task 범위 밖의 수정 후보 (적용하지 않음):

1. **`.raw` 보존 정책**: `scripts/orca_run_reviewer.py:547-552` 는 실패 시 .raw 를 남기지만 정리 정책이 없다. 실패 .raw 를 워크트리 밖(예: `data/reviewer_failures/` 또는 `.orca/reports/`)으로 옮기는 정책을 두면 후속 조사가 원문에 닿을 수 있다. **이는 제안일 뿐 적용하지 않았다.**
2. **프롬프트 안전망 추가**: `scripts/orca_run_reviewer.py:187` 의 build_prompt 에 "응답을 보낸 뒤 스스로 JSON 파싱을 시도해 보라" 같은 자가 검증 문구를 추가하는 방안. **제안일 뿐 적용하지 않았다.**
3. **자동 재시도 + 신뢰도 이력 연계**: `scripts/orca_model_router.py:715-928` 에 이미 신뢰도 이력(`RELIABILITY_DEMOTE_RATE=0.5`, `RELIABILITY_SUSPEND_CONSECUTIVE=3`)이 있다. 리뷰어 호출 결과도 여기에 누적하면, qwen-plus 가 임계치에 도달했을 때 자동으로 gemini-flash 로 강등되는 경로가 생긴다. 다만 reviewer 는 병합 판정에 직결되므로 강등 시 코디네이터 알림이 필수다. **제안일 뿐 적용하지 않았다.**
4. **프롬프트에 체크리스트 항목 수 명시**: 현재 `checklist_formatted` 만 들어가고 항목 수가 명시되지 않는다 (`scripts/orca_run_reviewer.py:158-168`). 항목 수를 명시하면 모델이 빠뜨리는 빈도를 줄일 수 있다는 외부 평이 있으나, 본 조사 범위에서 qwen-plus 의 실패와 직접 연결 짓는 근거는 없다. **제안일 뿐 적용하지 않았다.**

---

## 8. 명시적 한계

1. **.raw 파일 부재**: 가장 큰 제약이다. 응답 형태를 실측할 수 없다.
2. **실패 회차의 환경 변수(Qwen Code CLI 버전, 타임아웃, 디스크 잔여 등) 확인 불가**.
3. **qwen-plus 의 출력 토큰 상한 공식값 미확인**: Alibaba Token Plan 문서가 본 조사 범위 밖.
4. **재현 실험을 본 조사에서 실행하지 않음**: 의도적으로 모델을 다시 호출하지 않았다 (한 번에 하나만 실행하라는 ground_truth 준수 + 변경 파일 0건 유지).

---

## 9. 결론

- **확인된 사실**: qwen3.7-plus 의 JSON 비응답은 두 회 연속 발생, 같은 날 정상 완주도 존재, 모델 자체는 probe 통과, TIER_POLICY 의 reviewer 주 모델.
- **확인되지 않은 것**: 재현 조건, 응답의 실제 형태, diff 크기와의 상관, 외부 장애 가능성.
- **저장소에 남아 있는 실패 원문(.raw) 은 없다** (`find` 0건).
- **근거 없는 단정은 삼가** 한다. 가설 4개는 향후 별도 실험으로 좁혀야 한다.

코드 수정은 본 Task 범위 밖이며, 본 보고서에는 어떤 코드 변경도 포함하지 않는다.
