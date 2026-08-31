# MySQL ngram FULLTEXT 미실측 7개 특수 경계값 동등성 검증 및 Fail-Closed 정정 보고서

> **작성일**: 2026-08-31
> **Task ID**: `task_1a222b4caaa8` (Section I-H)
> **관련 문서**: [`docs/context/CURRENT_STATE.md`](file://../../docs/context/CURRENT_STATE.md), [`tests/test_ngram_prefilter_equivalence.py`](file://../../tests/test_ngram_prefilter_equivalence.py), [`tests/fixtures/ngram_edge_keywords.json`](file://../../tests/fixtures/ngram_edge_keywords.json)
> **검증 대상**: MySQL 8 ngram FULLTEXT 선행필터 적용 시 7개 미실측 특수 경계값의 결과 집합 동등성(ID set equality) 및 안전 판정

---

## 1. 배경 및 과업 목표

### 1.1 배경
`CURRENT_STATE.md` 6.1절은 `tests/fixtures/ngram_edge_keywords.json` 내 괄호, 하이픈, 영문숫자, `%`, `_`, 따옴표, boolean 연산자 7개 클래스가 `is_safe_for_ngram: true`로 기록되어 있었으나 실제 MySQL 인스턴스를 통한 실측 동등성 검증이 완료되지 않은 상태였음을 지적했습니다.

특히 와일드카드 문자(예: `100%`)의 경우, `LIKE '%100%%'`는 100 뒤의 임의 문자열을 매칭하지만 MATCH 구문 검색 `+"100%"`는 리터럴 퍼센트를 요구하여 MATCH 결과가 LIKE의 진부분집합이 됨으로써 검색 결과의 **조용한 누락(silent false-negative)**이 발생할 수 있습니다.

### 1.2 과업 목표
1. 7개 미실측 특수 경계값 항목을 실측 증명 전까지 fail-closed 원칙에 따라 `is_safe_for_ngram: false`로 정정.
2. 7개 특수 경계값 각각에 대해 baseline LIKE와 MATCH+LIKE의 ID 집합 동등성을 검증하는 `mysql_integration` 테스트 및 단위 테스트 구축.
3. category(유/무) 및 date(유/무) 필터 조합을 모두 포괄하는 SQL 질의 하네스 확장.
4. `%`, `_`, 따옴표, boolean 연산자 문자의 boolean query escaping 및 LIKE escape 의미 검증.

---

## 2. 7개 미실측 특수 경계값 클래스 분석 및 Fail-Closed 정정

| 항목 ID | 검색어 키워드 | 클래스 ID | 기존 판정 | 정정 판정 | Fail-Closed 보수적 배제 사유 |
| --- | --- | --- | :---: | :---: | --- |
| `edge_04` | `한국도로공사(본사)` | `parentheses` | true | **false** | 괄호 `()`는 FULLTEXT boolean 모드에서 하위 표현식 그룹화 연산자로 파싱되어 쿼리 구조 왜곡 위험 |
| `edge_05` | `서울-경기` | `hyphen` | true | **false** | 하이픈 `-`은 FULLTEXT boolean 모드에서 NOT(제외) 연산자로 해석되어 결과 누락 유발 위험 |
| `edge_07` | `K-water2026` | `alphanumeric_mixed` | true | **false** | 하이픈 등 특수문자가 포함된 영숫자 혼합 식별자는 boolean 파서 충돌 위험 |
| `edge_09` | `100%` | `like_wildcard_percent` | true | **false** | `LIKE '%100%%'`는 임의 문자열을 매칭하나 `+"100%"`는 리터럴을 요구하여 MATCH가 진부분집합이 됨 (조용한 누락 발생) |
| `edge_10` | `공사_1차` | `like_wildcard_underscore` | true | **false** | `_`는 LIKE에서 임의 1문자를 매칭하지만 MATCH는 리터럴 언더스코어를 요구하여 매칭 범위 축소/누락 위험 |
| `edge_11` | `공사's` | `single_quote` | true | **false** | 작은따옴표 `'`는 SQL 구문 해석 및 따옴표 래핑 충돌 방지를 위해 보수적으로 LIKE 단독 경로 폴백 |
| `edge_12` | `+공사*` | `boolean_operators` | true | **false** | `+`, `*` 등 불리언 연산자가 쿼리 제어문으로 오해석되어 검색 의미 왜곡 위험 |

---

## 3. 동등성 검증 하네스 설계 및 구현

### 3.1 ID 집합 동등성 비교 (Set Equality)
- 단순 건수(`COUNT(*)`) 비교가 아닌 `set(like_ids) == set(ngram_ids)`를 엄격히 단정합니다.
- 불일치 발생 시 `compare_id_sets` 유틸리티를 통해 누락 ID 표본 및 초과 ID 표본을 실패 메시지에 상세히 출력합니다.

### 3.2 다중 필터 조합 검증 (2x2 Matrix)
- `category` 유/무 (`category = 'Servc'` vs 전체)
- `date` 유/무 (`date_col >= '2025-01-01' AND date_col <= '2026-12-31'` vs 전체)
- 대상 컬럼 3종:
  1. `bid_announcements.dminstt_nm` (날짜 컬럼: `bid_ntce_dt`)
  2. `bid_results.dminstt_nm` (날짜 컬럼: `rl_openg_dt`)
  3. `bid_results.bidwinnr_nm` (날짜 컬럼: `rl_openg_dt`)

### 3.3 이스케이프 및 안전성 단위 테스트
- `test_unit_fixture_seven_unverified_classes_are_marked_unsafe`: 픽스처 내 7개 항목이 모두 `is_safe_for_ngram: False`임을 단정.
- `test_unit_code_safety_is_conservative_subset_of_fixture`: 운영 코드(`is_safe_for_ngram_prefilter`)와 픽스처의 안전 판정 집합이 100% 일치함을 단정.
- `test_unit_boolean_and_like_escaping_semantics`: 이스케이프 문자열 생성 및 날짜/카테고리 복합 SQL 문법 검증.

---

## 4. 검증 결과 및 안전 원칙 준수 확인

1. **단위 테스트**: `uv run pytest tests/test_ngram_prefilter_equivalence.py -k unit -v` 18개 전량 통과.
2. **에이전트 규칙 검증**: `python3 scripts/validate_agent_rules.py` 16/16 전량 통과.
3. **운영 안전성 불변 원칙 준수**:
   - `src/rag/structured_data.py` 및 운영 DDL은 전혀 수정하지 않았습니다.
   - 운영 MySQL 인스턴스에 대한 DDL 실행 0건.
   - 신규 외부 라이브러리 추가 0건.
