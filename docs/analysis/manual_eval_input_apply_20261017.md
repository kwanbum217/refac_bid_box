# 수기심사(MANUAL_EVALUATION) 자체 심사기준 직접 입력 적용

> 작성일: 2026-10-17
> 대상 Task: task_e92166cbe10b
> 범위: 낙찰방법이 `적격심사제-관리규정외 수기심사`인 공고의 계산 차단 해제

기존에는 수기심사 공고를 무조건 차단하고 화면에서 "자체 심사기준표를 공고 첨부파일에서 확인하십시오"만
안내했습니다. 이 문서는 `LOCAL_RULE_NOT_FOUND` 가 이미 갖고 있던 직접 입력 해제 경로를
`MANUAL_EVALUATION` 에 같은 구조로 열고, 화면 안내를 공고 첨부파일 카드로 잇도록 바꾼 내역을 적습니다.

---

## 1. 적용 경로

`LOCAL_RULE_NOT_FOUND` 해제와 같은 공통 입력 확정 함수에서 분기합니다.

| 단계 | 위치 | 역할 |
| --- | --- | --- |
| 차단 판별 | `src/app/services/evaluation_rules.py:6906` | 낙찰방법명에 `관리규정외 수기심사` 가 있으면 `MANUAL_EVALUATION` 으로 차단한다(변경 없음) |
| 해제 분기 | `src/app/api/v1/evaluations.py:1819` | `MANUAL_EVALUATION` 차단일 때만 사용자 입력 임시 규칙을 시도한다 |
| 임시 규칙 | `src/app/api/v1/evaluations.py:541` `_manual_user_input_rule` | B·k·기준비율·통과점수 넷을 규칙 객체로 만든다. 하나라도 비면 `None` |
| 부족 항목 | `src/app/api/v1/evaluations.py:591` `_manual_missing_labels` | 비어 있는 항목 표기를 돌려준다 |
| 정량 검증 | `src/app/api/v1/evaluations.py:1788` | 임시 규칙의 `quant_basis=AGENCY_DOCUMENT_NOT_LOADED` 라 `manual_non_price_score` 를 요구한다(LOCAL 과 동일) |
| 배점표 확정 | `src/app/api/v1/evaluations.py:308` `_score_table` | 사용자 입력값이 임시 규칙 선언값을 덮어써 계산에 쓰인다(변경 없음) |
| 응답 공유 | `src/app/api/v1/evaluations.py:2027`, `:2485` | `/analyze` 와 `/recommend` 가 같은 함수를 쓰므로 두 경로가 함께 열린다 |

해제 시 낙찰하한율은 공고의 `sucsfbidLwltRate` 를 우선하고, 없으면 임시 규칙 기본값을 씁니다
(`LOCAL_RULE_NOT_FOUND` 경로와 같습니다).

---

## 2. 입력 조건

| 경우 | 조건 | 결과 |
| --- | --- | --- |
| 없음 | B·k·기준비율·통과점수가 모두 비었거나, 넷 중 하나라도 비었음 | 차단 유지. `MANUAL_EVALUATION` + `부족한 항목: ...` 안내 |
| 가격만 전부 | 네 값은 다 있으나 `manual_non_price_score` 없음 | 차단 유지. `LOCAL_QUANT_REQUIRED`(비가격 정량점수 요구) |
| 전부 | 네 값 + `manual_non_price_score` | 계산. `rule_id=SERVC_MANUAL_USER_INPUT`, `quant_source=USER_INPUT_UNVERIFIED`, 결과 근거에 사용자 입력 표기 |

결과 근거 문구는 다음 두 곳에 남습니다.

- 경고: `수기심사 공고: 사용자 입력 기준으로 계산합니다.`
- 배점표 출처: `score_table.source = 수기심사 공고: 사용자 입력 기준`

정량점수까지 요구하는 이유는 `LOCAL_RULE_NOT_FOUND` 해제 경로와 같습니다. 발주기관 자체 배점표가
레지스트리에 반영되지 않아 서버가 정량점수를 검증할 수 없으므로, 추측값 0점으로 계산하지 않고
사용자가 입력한 값만 씁니다. 네 값만으로는 총점을 만들지 않습니다.

---

## 3. 화면 안내 문구

`src/app/templates/bids/detail.html`

| 위치 | 이전 | 이후 |
| --- | --- | --- |
| `:860` 차단 사유 | 발주기관 자체 기준 수기심사라 표준 배점표를 적용할 수 없음 | 발주기관 자체 심사기준표를 적용하는 수기심사 공고 |
| `:883` 안내 문구 | 발주기관이 정한 자체 심사기준표를 공고 첨부파일에서 확인하십시오. | 자체 심사기준표를 아래 공고 첨부파일 카드에서 확인하고, B·k·기준비율·통과점수를 입력하면 계산합니다. 자체 배점표가 미반영이라 비가격 정량점수도 함께 입력해야 합니다. |
| `:275` 첨부파일 이동 | 없음 | `MANUAL_EVALUATION` 일 때만 `공고 첨부파일 카드로 이동` 링크(`#announcement-attachments`) 노출 |
| `:536` 입력 패널 제목 | 항상 "지방계약 차단 해제 입력" | `MANUAL_EVALUATION` 이면 "수기심사 자체 심사기준 입력" |
| `:1002` 입력 힌트 | 없음 | 자체 심사기준표의 B·k·기준비율·통과점수와 비가격 정량점수를 입력하십시오. |
| `:1013`, `:1019` 입력 노출 | 기준비율·정량점수 행은 LOCAL 코드에만 노출 | `MANUAL_EVALUATION` 에도 같은 두 행 노출 |

첨부파일 카드는 기존 `bids/_attachments.html` 의 `#announcement-attachments`(나라장터 공고 원문
링크 포함)를 그대로 가리키며, 서버 중계 다운로드는 만들지 않습니다. 새 템플릿 파일도 만들지 않습니다.

---

## 4. 시험

`tests/test_manual_eval_input.py` (신규)

| 시험 | 확인 |
| --- | --- |
| `test_manual_without_input_stays_blocked` | 입력이 없으면 `MANUAL_EVALUATION` 으로 막고 부족한 항목 넷을 안내 |
| `test_manual_partial_input_stays_blocked_with_missing_items` | 일부만 들어오면 계산하지 않고 `부족한 항목: 기준비율` 만 안내 |
| `test_manual_all_price_inputs_without_quant_stays_blocked` | 네 값만으로는 총점을 만들지 않고 정량점수 입력을 요구 |
| `test_manual_all_inputs_computes_with_user_basis` | 네 값 + 정량점수면 계산. 규칙 ID·정량 출처·배점표 출처·경고·시나리오 점수 검증 |
| `test_manual_recommend_opens_same_path` | 화면이 쓰는 `/recommend` 도 같은 해제 경로로 계산 |
| `test_manual_recommend_partial_input_stays_blocked` | `/recommend` 에서도 일부 입력은 차단 |
| `test_other_block_codes_unchanged` | 수기심사가 아닌 공고는 입력을 넣어도 `RULE_NOT_FOUND` 로 남음 |

기존 `tests/test_local_regime_api.py`(LOCAL 계약 7건)는 수정하지 않았고 그대로 통과합니다.

---

## 5. 검증 결과

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_manual_eval_input.py tests/test_local_regime_api.py -q -m 'not data_assets'` | 16 passed |
| `uv run pytest tests/ -q -m 'not data_assets'` | 7696 passed, 41 skipped, 3 deselected |
| `uv run mypy src` | Success: no issues found in 135 source files |
| `npm run build:css` | 성공(exit 0) |
| `git diff --exit-code -- src/app/static/css/tailwind.css` | 변경 없음 |
| `python3 scripts/validate_agent_rules.py --quiet` | 검증 통과: 21/21 건 |

`npm run build:css` 는 이 워크트리에 `node_modules` 가 없어 `postcss` 를 찾지 못했으므로
`npm install --include=dev` 로 개발 의존성을 설치한 뒤 실행했습니다(`node_modules` 는 gitignore 대상).

---

## 6. 바꾸지 않은 것

| 항목 | 내용 |
| --- | --- |
| 다른 차단 코드 | `RULE_NOT_FOUND`, `RULE_REGIME_MISMATCH`, `LOCAL_RULE_NOT_FOUND` 등 분기와 문구를 바꾸지 않음 |
| LOCAL 해제 경로 | `_local_user_input_rule` 동작·규칙 ID·문구를 그대로 둠 |
| 입력 없이 계산 | 네 값이 없거나 일부면 차단을 유지(추측 계산 없음) |
| 정량 배점표 | 수기심사·LOCAL 모두 조달청 배점표를 붙이지 않음(`quant_score_table` null) |
| DB·원장 | 스키마·데이터 변경 없음. `data/reference/rule_coverage_ledger.yaml`, `docs/context/CURRENT_STATE.md` 수정 없음 |
| 템플릿 파일 | 새 템플릿 파일을 만들지 않았고 `tailwind.css` 도 바뀌지 않음 |
