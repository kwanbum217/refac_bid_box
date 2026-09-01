# Section K1-IH: kwanbum217/orca-i-h Rebase 및 동등성 검증 보고서

> **작성일**: 2026-09-01
> **Task ID**: `task_1584401ebfcf` (Section K1-IH)
> **대상 브랜치**: `kwanbum217/orca-k1-ih`
> **Rebase 대상**: 로컬 `main` (`5f09059`)
> **관련 커밋**: `d8aa9a9` (Section I-H 원본 커밋) -> rebase 후 최신 커밋
> **검증 대상**: 7개 미실측 경계값 픽스처(`tests/fixtures/ngram_edge_keywords.json`)의 `is_safe_for_ngram` fail-closed 상태 및 `tests/test_ngram_prefilter_equivalence.py` 동등성 테스트

---

## 1. 개요 및 목적

Section I-H에서 추가된 7개 특수 경계값 클래스의 fail-closed 안전 판정(`is_safe_for_ngram: false`) 및 ID 집합 동등성 검증 하네스를 로컬 `main` 최신 상태(`5f09059`) 위로 rebase 하여 충돌 없이 병합 가능한 상태로 준비합니다.

---

## 2. 7개 미실측 특수 경계값 Fail-Closed 판정 현황

`tests/fixtures/ngram_edge_keywords.json`의 7개 미실측 특수 경계값 항목은 모두 `is_safe_for_ngram: false`로 유지됨을 확인하였습니다.

| 항목 ID | 키워드 | 클래스 ID | 안전 판정 (`is_safe_for_ngram`) | Fail-Closed 배제 사유 |
| --- | --- | --- | :---: | --- |
| `edge_04` | `한국도로공사(본사)` | `parentheses` | **false** | 괄호 `()`는 FULLTEXT boolean 모드 하위 표현식 연산자 충돌 위험 |
| `edge_05` | `서울-경기` | `hyphen` | **false** | 하이픈 `-`은 FULLTEXT boolean NOT 연산자로 오해석되어 결과 누락 위험 |
| `edge_07` | `K-water2026` | `alphanumeric_mixed` | **false** | 하이픈 등 특수문자 포함 영숫자 식별자 충돌 위험 |
| `edge_09` | `100%` | `like_wildcard_percent` | **false** | `LIKE '%100%%'`와 `MATCH +"100%"`의 매칭 범위 불일치 (조용한 누락 위험) |
| `edge_10` | `공사_1차` | `like_wildcard_underscore` | **false** | `_` 단일문자 와일드카드 매칭 범위 축소/누락 위험 |
| `edge_11` | `공사's` | `single_quote` | **false** | 작은따옴표 `'` 구문 해석 및 따옴표 래핑 충돌 방지 |
| `edge_12` | `+공사*` | `boolean_operators` | **false** | `+`, `*` 등 불리언 연산자의 쿼리 제어문 오작동 위험 |

---

## 3. 검증 결과

1. **대상 동등성 테스트**:
   - `uv run pytest tests/test_ngram_prefilter_equivalence.py -v`
   - 결과: **18 passed, 9 skipped** (운영 DB probe index 미생성 상태에서 9건 mysql_integration skip 정상 동작).
2. **에이전트 규칙 검증**:
   - `python3 scripts/validate_agent_rules.py --quiet`
   - 결과: **16/16 건 전량 통과**.
3. **코드 무변경 및 안전 원칙 준수**:
   - `src/rag/structured_data.py` 무수정 유지.
   - 운영 DDL, Alembic 마이그레이션, FULLTEXT 운영 인덱스 생성 0건.
   - 신규 의존성 패키지 추가 0건.
