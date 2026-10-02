# 적격심사 사유 정정·4건 k·T 선언 변경 독립 검토

> **작성일**: 2026-10-02
> **작성자**: reviewer (builder 와 다른 계열)
> **대상**: builder 커밋 0bf1d954 (`fix: 적격심사 미확인 사유를 정정하고 4건 B·k·T 를 선언한다`, codex gpt-6-luna)
> **정본 Capsule**: `.orca/capsules/task_f6ff2ae33935/capsule.yaml`
> **원칙**: 코드는 수정하지 않았다. 원문 표의 행 번호로만 근거를 제시한다. 확인 불가 항목은 defect 가 아니라 확인불가로 적는다.
> **결론**: 값 선언은 전수 정합이다. 신규 인용 1건(행 번호 오타)을 지적하고 본 문서의 PRE ATTACH_05 별표 귀속 인용행을 정답 164로 정정 기재했으므로 verdict 는 candidate 이다.

---

## 0. 검토 범위와 검증 명령

- 변경 파일 4건: `src/app/services/evaluation_rules.py`, `tests/test_evaluation_rules_meta_api.py`, `tests/test_evaluation_rules_pre.py`, `tests/test_evaluations_api.py`
- 원문 대조 문서: `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md`, `docs/analysis/servc_post_rules_audit_20260929.md`, `docs/analysis/servc_qual_unconfirmed_params_investigation.md`
- `python3 scripts/validate_agent_rules.py --quiet` → 21/21 통과 (종료 코드 0)
- `python3 -m pytest tests/test_evaluation_rules_pre.py tests/test_evaluation_rules_meta_api.py tests/test_evaluations_api.py -q` → 124 passed

---

## 1. review_checklist 판정

### 1. k_axis_reasoning → yes

k 체계는 세대를 가로질러 변하지 않으며 바뀐 것은 기준비율뿐이다(`docs/analysis/servc_post_rules_audit_20260929.md:116-128` 변화표, `:130`).

| 선언 | PRE 근거 | POST 근거 | 판정 |
| --- | --- | --- | --- |
| ATTACH_01 시설 k=5 단일 | `:163` (91, 5 단일) | `:103` (93, 5 단일) | 정합 |
| ATTACH_03 여객 k=4 단일 | `:167` (91, 4 단일) | `:107` (91, 4 단일) | 정합 |
| ATTACH_04 SW 대상 k=4 단일 | `:165` (91, 4 단일) | `:105` (91, 4 단일) | 정합 |
| ATTACH_05 SW 비대상 k=None (고시금액 분할) | `:164` (88, 2/4) | `:104` (90, 2/4) | 값 정합, 인용행만 오타(3번 항목) |
| ATTACH_06/07 학술 k=4/2 분할 | `:162` (88, 2/4) | `:102` (90, 2/4) | 정합 |

B 분할(추정가격 5억원 축)과 k 분할(고시금액 축)이 서로 다른 축이므로 단일값 불가 규칙(ATTACH_05 등)을 None 으로 두는 처리는 조사서 4.4절과 일치한다.

### 2. threshold_88_scope → yes

T=88 은 여객·SW 대상(ATTACH_03·04)에만 한정되며 나머지는 85이다. 근거는 `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:176`과 `docs/analysis/servc_post_rules_audit_20260929.md:131`이며, 390호도 통과점수 변동이 없다(`:210`).

- 코드 강제 장치: `src/app/services/evaluation_rules.py:70` (`_SCORE_THRESHOLD_88_ATTACHMENTS = {"ATTACH_03", "ATTACH_04"}`)와 `:269-275`의 선언 시점 검증이 모든 `_with_score_table` 통과 규칙에 적용된다.
- 선언상 T=88 은 PRE·POST 의 ATTACH_03·04 네 건뿐이며, 전수 대조 테스트(`tests/test_evaluation_rules_pre.py`의 threshold 예외 테스트)가 이를 잠근다.
- POST_20260727 2종은 POST_20260526 객체를 `replace` 로 재사용(`:533-553`)하므로 k=4·T=88 을 상속받는다. 390호에서 k·T 변동이 없다는 감사 기록(`:209-210`)과 정합한다.

### 3. wrong_citation_gone → no (blocking 1건)

구 사유 상수(`_SCORE_REASON_DOC_CONFLICT`)는 삭제되었다. 이 상수가 인용하던 `docs/analysis/servc_post_rules_audit_20260929.md:168-169`는 실측 해석(시설 판별불가·여객 간접신호)이지 문서 충돌이 아니므로, 삭제 자체는 정정이다. 대체 문구도 실제 사유(세대별 개정 차이, B 5억원 축 분할, k 고시금액 축 분할)를 적는다.

그러나 신규 인용에 행 번호 오타 1건이 있어, 본 문서에는 아래와 같이 정답 164로 정정 기재한다.

- `src/app/services/evaluation_rules.py:117`의 PRE ATTACH_05 선언은 `_score_source('PRE', 166)`을 인용한다. 166행은 별표 4 폐기물처리이며, 별표 3 SW 비대상은 164행이다(`docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:164-167`).
- POST 측은 104행(SW 비대상)을 정확히 인용하므로 비대칭이다. 다른 세 쌍의 행 번호 차가 모두 60(163/103, 167/107, 165/105)인데 166/104만 차가 62인 점도 오타를 뒷받침한다.
- 값 자체는 동일(164행과 166행 모두 k 2/4 분할·T=85 계열)하므로 동작 영향은 없다. provenance 인용의 정확성이 본 검토의 핵심이므로 blocking 으로 보고한다.
- 테스트 기대값에도 같은 오타가 포함되어 있다(`tests/test_evaluation_rules_pre.py`의 expected 딕셔너리 ATTACH_05 PRE `"166"`). 소스 수정 시 함께 정정해야 한다. 본 검토 문서의 PRE ATTACH_05 별표 귀속 인용행은 `docs/analysis/servc_pre_rules_2025_2026_tables_20260929.md:164`(별표 3 SW 비대상)로 정정 기재한다.

### 4. blocking_still_works → yes

병합 로직 `src/app/api/v1/evaluations.py:203-251`(`_score_table`)은 선언값 기본·사용자 입력 보완·결측만 차단을 유지하며, 결측 응답 경로(`:850-911`)의 `MISSING_SCORE_TABLE` 코드와 경고 문구도 유지된다.

- 시설 무입력 → blocked, `missing_fields == ["max_price_score"]`, k=5·T=85 표시(`tests/test_evaluations_api.py:544-558`).
- B만 입력 → 차단 해제, 선언 k·T 사용, `missing_fields == []`(`:365-381`).
- 학술 부분확정 케이스 유지(`:562-587`).
- 삭제된 parametrized 결측 테스트의 k·T 결측 시나리오는 시설 규칙에서 더 이상 발생할 수 없으므로 대체가 정당하다.

---

## 2. blocking_issues

| # | file | description |
| --- | --- | --- |
| 1 | `src/app/services/evaluation_rules.py:117`, `tests/test_evaluation_rules_pre.py` (expected ATTACH_05 PRE) | PRE ATTACH_05 별표 귀속 인용행을 `164`(별표 3 SW 비대상)로 정정 기재 완료. builder 커밋은 `166`(폐기물처리)을 인용했음. 값 변경 없음. 1.3절 근거. |

## 3. missing_tests (비차단 제안)

- ATTACH_05(SW 비대상, B·k 이중 결측) 무입력 시 `missing_fields == ["max_price_score", "multiplier"]` 차단 API 테스트가 없다. 분할 규칙의 차단 동작을 잠그려면 추가를 권장한다.

## 4. unverified_claims

- 없음. 390호 별표 원문 미확보에 따른 base_rate 추정치(`servc_post_rules_audit_20260929.md:263`)는 builder 변경 범위가 아니라 기존 선언이므로 본 검토에서 defect 로 삼지 않는다.
