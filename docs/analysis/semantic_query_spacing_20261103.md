# 의미 검색 질의의 기간 표지·조사 공백 결함 분석

> **작성일**: 2026-11-03
> **대상**: `src/rag/query_planning.py` 의 `_split_attached_period`
> **관련 Task**: `task_1fbb0bd491b7` (builder)

---

## 1. 증상과 재현

챗봇 의미 검색 경로에서 기간 표현이 붙어 들어오면 질의 문자열이 `최근 에` 처럼
기간 표지와 조사 사이에서 끊겼습니다. `build_retrieval_plan` 을 직접 호출해
재현했습니다. 앱, Docker, LLM, Redis, ChromaDB 는 사용하지 않았습니다.

재현 명령:

```bash
uv run python -c "
from src.rag.query_planning import build_retrieval_plan
print(build_retrieval_plan('최근에 올라온 용역 공고').semantic_query)
"
```

| 입력 | 수정 전 `semantic_query` | 수정 후 `semantic_query` |
| --- | --- | --- |
| `최근에 올라온 용역 공고` | `최근 에 올라온 용역 공고` | `최근에 올라온 용역 공고` |
| `올해는 어떤 사업이 있나` | `올해 는 어떤 사업이 있나` | `올해는 어떤 사업이 있나` |
| `이번달에 올라온 공고` | `이번달 에 올라온 공고` | `이번달에 올라온 공고` |
| `요즘은 어떤 공고` | `요즘 은 어떤 공고` | `요즘은 어떤 공고` |
| `지난해에는 어떤 공고가 있었어` | `지난해 에는 어떤 공고가 있었어` | `지난해에는 어떤 공고가 있었어` |
| `v25 모델로 최근에 수집된 물품 공고 투찰가 예측해줘` | `v25 모델로 최근 에 수집된 물품 공고 투찰가 예측해줘` | `v25 모델로 최근에 수집된 물품 공고 투찰가 예측해줘` |
| `2025년 1월부터 3월까지 물품 공고 건수` | `2025년 1월 부터 3월 까지 물품 공고 건수` | `2025년 1월부터 3월까지 물품 공고 건수` |

---

## 2. 원인 위치

`build_retrieval_plan` 은 정규화 직후 `_split_attached_period` 를 적용하고 그
결과를 `semantic_query` 로 넘깁니다 (`src/rag/query_planning.py:3080`).

`_split_attached_period` (`src/rag/query_planning.py:3059`) 는 `10월서울` 처럼
기간 표지 뒤에 기관·지역명이 붙은 경우 공백을 넣어 기관 후보 추출을 돕습니다.
문제는 이 함수가 표지 뒤에 붙은 글자가 조사인지 구분하지 않은 점입니다.
`_ATTACHED_PERIOD_CONTINUATIONS` 는 `년`·`월`·`분기`·`일`·`주`·`개월` 로 끝나는
표지만 걸러 냈으므로, `최근`·`요즘`·`올해`·`이번달` 같은 표지 뒤의 `에`·`는`·`부터`
는 기관·지역명처럼 취급되어 공백이 삽입됐습니다.

---

## 3. 수정 내용

`_followed_by_period_particle` (`src/rag/query_planning.py:3044`) 을 추가해,
표지 뒤에 붙은 글자가 조사이고 그 조사 뒤가 낱말 경계(공백·끝·문장부호)이면
공백을 넣지 않습니다. 조사 뒤에 한글이 이어지는 `최근이천시` 는 조사가 아니라
지명으로 보아 기존처럼 분리합니다. 기존 `_ATTACHED_PERIOD_CONTINUATIONS` 규칙은
그대로 두었습니다.

기간 표지·수량 표지의 분리 규칙 자체는 유지되므로 날짜 창 계산, SQL 경로,
라우팅 분기 결과는 바뀌지 않습니다.

---

## 4. 검증

기준일 고정 질의 41건에 대해 수정 전후 `RetrievalPlan` 전체를 비교했습니다.
달라진 필드는 `semantic_query` 하나뿐이었고 `use_sql`, `use_vector`,
`date_from`, `date_to`, `time_bucket`, `filters`, `route_reason` 은 동일했습니다.

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_query_planning.py tests/test_chatbot_planner.py -q` | 통과 |
| `uv run mypy src` | 통과 |
| `uv run pytest tests/ -q -m 'not data_assets'` | 통과 |
| `python3 scripts/validate_agent_rules.py --quiet` | 통과 |

회귀 시험은 `tests/test_query_planning.py` 의
`test_period_marker_keeps_trailing_particle_in_semantic_query`,
`test_period_marker_still_splits_attached_place_name` 과
`tests/test_chatbot_planner.py` 의
`test_semantic_search_step_keeps_period_particle_attached` 에 추가했습니다.
기존 시험의 기대값은 변경하지 않았습니다.

---

## 5. 남은 범위

`src/app/services/tools/semantic_search_tool.py` 는 `RetrievalPlan` 을 만들 때
원본 질의를 `semantic_query` 로 그대로 넘깁니다. 이번 수정은 그 앞단의 계획
문자열을 바로잡는 것이므로 도구 동작은 바꾸지 않았습니다. 의미 검색 도구가
계획된 `semantic_query` 를 써야 하는지는 별도 판단 사항입니다.
