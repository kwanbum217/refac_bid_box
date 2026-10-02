# 수요기관 계약 법령 판별 변경 독립 검토 (b52abf8d)

> 작성일: 2026-10-02
> 검토 대상: 커밋 b52abf8d (git log --oneline main..HEAD 에서 1건 확인, git diff main...HEAD 파일 15개)
> 검토 방식: 코드 행 번호, git diff, 직접 실행한 시험 출력으로만 근거 제시. 빌더 보고 인용 없음
> 판정: pass (blocking defect 없음)

## 범위

- 정본: .orca/capsules/task_2a50f0d91139/capsule.yaml 의 review_checklist 5항
- 직접 실행: uv run pytest 4파일, uv run alembic heads, python3 scripts/validate_agent_rules.py --quiet
- 금지 준수: src/tests/migrations/scripts 수정 없음, API 호출 없음, docker/DB 조작 없음, 커밋 생성 없음

## 직접 실행 결과

- pytest: `120 passed in 3.80s`
  - 명령: uv run pytest tests/test_demand_institutions.py tests/test_evaluation_rules_scope_axis.py tests/test_evaluations_api.py tests/test_scheduled_tasks.py -q
- alembic heads: `bd7c2e9a104f (head)` (단일 head)
- validate_agent_rules: `검증 통과: 21/21 건.`

## 항목별 판정

### 1. mapping_matches_spec: yes

확정 5단계가 순서대로 구현됐다. src/app/services/demand_institutions.py:140-152 에서 (1) 교육행정조직 3개 중분류 LOCAL, (2) 지방자치단체/지방공기업 LOCAL, (3) 5개 학교 대분류 + 소분류 공립 LOCAL, (4) 국가기관/공기업/준정부기관/정부투자기관 NATIONAL, (5) 그 밖 None 순이다. 중분류 strip 은 같은 파일 134-136, 소분류 strip 은 137-139 에서 처리한다. 대분류/소관구분은 _clean(src/app/services/demand_institutions.py:122-124)을 거쳐 strip 후 비교하므로 공백 변형에도 동일 판정이다.

반례 6종이 시험으로 고정됐다. tests/test_demand_institutions.py:152-187 (test_known_counterexamples)에서 부산지방국토관리청 NATIONAL, 구미도시공사 LOCAL, 지역교육청 LOCAL, 공립 초등학교 LOCAL, 사립 대학 None, 기타공공기관 None 을 단언한다. 규칙 전체 행렬은 tests/test_demand_institutions.py:119-137, API 키명 수용은 140-149 에서 고정한다. 해당 시험은 위 pytest 실행에 포함돼 통과했다.

### 2. collector_correct: yes

1년 이하 분할은 src/app/services/demand_institutions.py:25-34 (364일 창) 이고 시험 tests/test_demand_institutions.py:50-54 가 3구간과 365일 미만을 단언한다. 전체 페이지 순회는 src/app/services/demand_institutions.py:97-118 (pageNo 1부터 totalCount 도달까지, numOfRows 999) 이고 시험 tests/test_demand_institutions.py:57-90 이 2페이지 호출과 pageNo/inqryDiv 전달을 단언한다. 요청 파라미터는 같은 파일 101-109 (serviceKey, numOfRows, pageNo, type, inqryDiv, inqryBgnDt/inqryEndDt YYYYMMDDHHMM) 이다.

정상/오류 구분은 src/app/services/demand_institutions.py:53-73 (parse_response: 최상위 ResponseError 키 거부, header resultCode 00 외 거부, items 빈 리스트/단일 dict 포장) 이고 시험 tests/test_demand_institutions.py:25-47 (빈 items, 단일 item, 코드 07/08 오류)이 통과한다. upsert 멱등은 src/app/services/demand_institutions.py:200-215 (dminstt_cd 기준 db.get 후 insert/update) 이고 시험 tests/test_demand_institutions.py:93-116 이 동일 코드 재적재 1행 유지를 단언한다. 증분 기준은 src/app/services/demand_institutions.py:218-233 (max(chg_dt) 하루 전, 없으면 1950-01-01, full이면 inqryDiv 1, incremental이면 inqryDiv 2) 이며 Arq 증분 경로는 src/tasks/summary_tasks.py:60-76 에서 incremental 고정 호출한다.

### 3. fallback_unchanged: yes

기관 없음/미매칭 시 문맥은 변경 전과 같다. src/app/services/evaluation_rules.py:1134-1142 (extract_contract_regime: 계약방법명에 지방 포함이면 LOCAL, 아니면 institution_regime 그대로이므로 둘 다 없으면 None) 와 tests/test_evaluation_rules_scope_axis.py:100-104, tests/test_demand_institutions.py:190-196 (기관값 None이면 None)이 이를 고정한다. resolve 기본값도 tests/test_evaluation_rules_scope_axis.py:133-144 에서 region None/contract_regime None 을 단언한다.

범위는 src/app/services/evaluation_scoring.py:294-302 에서 LOCAL이면 0.03, 아니면 0.02 로 기존 상수 그대로이며, 호출부 src/app/api/v1/evaluations.py:653-696 (_scenario_prices, institution_regime None이면 _is_local_contract False) 을 통한다. LOCAL 전용 ±3% 와 미상 ±2% 는 tests/test_demand_institutions.py:216-229 에서 단언한다. 지방 표기 최우선은 tests/test_demand_institutions.py:190-196 (기관 NATIONAL이어도 계약방법 지방이면 LOCAL) 으로 고정한다.

공고당 조회 1회는 src/app/api/v1/evaluations.py:647-650 (_demand_institution_for_bid, db.get 1회), 1408-1413 (analyze_evaluation에서 1회 조회 후 institution_loaded=True로 전달), 1265-1290 (_analyze_bid는 미로드 시에만 조회) 으로 확인한다. 동일 흐름이 1514-1530 (list_evaluation_rules_meta) 에서도 1회다.

### 4. secret_not_leaked: yes

git diff main...HEAD 에서 64자리 16진수 패턴 검색 결과 0건이다 (grep -E -c [0-9a-f]{64} 출력 0). 설정은 이름으로만 읽는다: src/app/core/config.py:158 (G2B_USRINFO_SERVICE_KEY 기본 빈 문자열), .env.example:206 (값 비움), scripts/collect_demand_institutions.py:25-26 (키 비면 RuntimeError), src/tasks/summary_tasks.py:60-62 (키 비면 skipped 반환). 시험 tests/test_demand_institutions.py:232-241 이 skipped 경로를 고정한다.

오류/로그 경로에 키가 없다. 수집 실패는 src/app/services/demand_institutions.py:110-116 에서 원인 예외를 끊고 (from None) 일반 문구만 던지며, Arq 로그 src/tasks/summary_tasks.py:75 는 결과 집계(mode/start/end/counts/distribution)만 기록한다. 키가 params 딕트(src/app/services/demand_institutions.py:101-109)에만 들어가고 로그·문서·시험에는 값이 없다.

### 5. migration_safe: yes

migrations/versions/bd7c2e9a104f_add_g2b_demand_institutions.py:12-13 에서 revision bd7c2e9a104f, down_revision a2c7e9f1b4d6 이다. upgrade(18-36)는 g2b_demand_institutions 생성만, downgrade(39-40)는 같은 테이블 삭제만 하며 기존 테이블 언급이 없다. ORM(src/app/models/demand_institutions.py:15-32)과 컬럼 14개가 타입/길이/nullable까지 일치한다 (문자열 길이 20/500/100/200/300/10, chg_dt DateTime nullable, raw_json JSON not null, fetched_at DateTime not null). 등록은 src/app/models/__init__.py:20 에서 import된다. uv run alembic heads 출력은 bd7c2e9a104f (head) 단일이다. tests/test_evaluation_rules_scope_axis.py:204-209 의 단일 head 단언도 통과한다 (head 고정값 단언 제거는 승인된 변경).

## 비차단 제안 (verdict 미반영)

- 수집 실패 시 from None 으로 원인을 끊어 07/08 구분이 로그에 남지 않는다. 재시도 판단용으로 resultCode만 마스킹 기록하면 운영 진단에 도움이 된다.
- incremental_start의 today 인자가 미사용이다. 제거 또는 사용 중 하나로 정리하면 혼란이 줄어든다.
- inqryDiv=2 증분 경로와 max(chg_dt) 경계(-1일) 직접 시험이 없다. FakeDB로 경계 1건 추가를 권장한다.
- 학교 대분류 중 유치원/특수학교/고등학교 LOCAL 분기와 중분류 시 도교육청 직속기관 LOCAL 분기는 코드에 있으나 대표 시험 행이 없다. 반례 목록에는 없어 차단이 아니나 행 추가를 권장한다.

## verdict

pass. 5항 모두 yes 이며 재현되는 동작 결함이 없다.
