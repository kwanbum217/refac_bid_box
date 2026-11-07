# 비예가(NON_PRED_PRICE) 차단 문구 정정과 공고 공개값 표시

> **작성일**: 2026-11-07
> **작업**: Orca Task `task_12a56ed3bf77` (builder, `run_d3fa8d51ba74`)
> **정본 사양**: Task Capsule (`ORCA_TASK_CAPSULE_V2`)
> **근거 조사**: [non_pred_price_211_20261107.md](non_pred_price_211_20261107.md) 5절 결정
> **범위**: 문구·표시·시험·기록 문서. 판정 로직(차단 여부, 규칙 선택, 차단 코드)은 바꾸지 않았다.

---

## 1. 결정 반영

| 결정 | 반영 |
| --- | --- |
| 1. NON_PRED_PRICE 차단 유지 | 유지. `evaluation_rules.py` 판별 순서와 차단 코드 불변 |
| 2. 차단 문구 정정 | '예정가격이 없음'을 '예정가격(기초금액)이 공고에 공개되지 않음' 취지로 교체 |
| 3. 공고 공개값 표시 | 낙찰하한율(`raw_data.sucsfbidLwltRate`)·추정가격(`presmpt_prce`)을 '공고 공개값'으로 표시 |
| 4. 추정가격 기반 참고 계산 | 넣지 않음. 곱셈·시나리오·통과 금액 없음 |

---

## 2. 변경 파일

| 파일 | 변경 |
| --- | --- |
| [evaluation_rules.py:4086](../../src/app/services/evaluation_rules.py:4086) | `block_reason_message`를 "예정가격(기초금액)이 공고에 공개되지 않아 가격점수 산출 분모를 확정할 수 없습니다."로 교체 |
| [detail.html:903](../../src/app/templates/bids/detail.html:903) | 짧은 사유를 "비예가라 예정가격(기초금액)이 공개되지 않음"으로 교체 |
| [detail.html:926](../../src/app/templates/bids/detail.html:926) | 안내 문장을 "공개되지 않아 사전 계산이 불가합니다"로 교체 |
| [detail.html:282](../../src/app/templates/bids/detail.html:282) | 차단 카드에 '공고 공개값' 블록 추가. 하한율 소수 3자리, 추정가격 원 단위 천 단위 구분 |
| [detail.html:694](../../src/app/templates/bids/detail.html:694) | 템플릿에 `sucsfbidLwltRate` 상수 추가. 추정가격은 기존 `noticeEstimatedPrice` 사용 |
| [detail.html:1908](../../src/app/templates/bids/detail.html:1908) | `renderBlockedPublicValues` 로 표시·숨김 처리 |
| [test_npp_message_20261107.py](../../tests/test_npp_message_20261107.py) | 문구·표시·숨김 분기 시험 추가 |

`src/app/api/v1/evaluations.py` 와 `src/app/static/css/tailwind.css` 는 바꾸지 않았다.

- 추천 응답 변경이 필요 없었다. 템플릿 컨텍스트의 `bid` 객체에 `raw_data`와 `presmpt_prce`가 이미 전달되고 있었다(같은 파일 445행이 `bid.raw_data.get('sucsfbidMthdNm')` 을 이미 쓴다).
- 새 Tailwind 클래스를 쓰지 않아 재생성 결과가 같았다. `npm run build:css` 후에도 `tailwind.css` diff 는 0이다.

---

## 3. 표시 규칙

| 항목 | 규칙 |
| --- | --- |
| 노출 조건 | 차단 코드가 `NON_PRED_PRICE` 이고 값이 하나 이상 있을 때 |
| 낙찰하한율 | `Number(value).toFixed(3)` + `%`. 79.995 는 `79.995%` |
| 추정가격 | `toLocaleString('ko-KR')` + `원`. 5606363636 은 `5,606,363,636원` |
| 결측·0 | 해당 줄을 숨긴다. 대체값을 만들지 않는다 |
| 계산 | 하한율 × 추정가격 같은 계산값을 만들지 않는다. 안내 문장에 "이 값으로 투찰가를 계산하지 않습니다"를 함께 적는다 |

---

## 4. 검증

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_npp_message_20261107.py tests/test_bid_detail_recommend_ui.py -q` | 15 passed |
| `uv run mypy src` | Success: no issues found in 145 source files |
| `npm ci --include=dev` | 성공. 사용자 npm 설정 `omit=dev` 를 이번 실행에서만 덮었다 |
| `npm run build:css` | 성공 |
| `git diff --exit-code -- src/app/static/css/tailwind.css` | diff 없음 |
| `uv run pytest tests/ -q -m 'not data_assets'` | 10658 passed, 41 skipped, 3 deselected, 2 xfailed |
| `python3 scripts/validate_agent_rules.py --quiet` | 22/22 통과 |

---

## 5. 남긴 것

- 판정(차단 유지, 규칙 선택, 차단 코드)은 그대로다. `evaluation_rules.py` diff 는 문구 대체 한 곳뿐이다.
- 후속 가격입찰 공고 연결(5절 결정 5)과 수기심사 66건 우선순위(결정 6)는 이번 범위가 아니다.
- 하한율 특이값(100·1·10·50·70 등 37건)은 표시만 하고 검증하지 않는다. 출처 그대로 보여 준다.
- 추천 응답의 `PRED_PRICE_UNAVAILABLE` 문구는 이미 같은 취지라 손대지 않았다.
