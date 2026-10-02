# 적격심사 기관·지역·계약법령 축 독립 검토

> 작성일: 2026-10-02
> 검토자: reviewer (builder codex gpt-6-luna와 다른 계열)
> 대상: 1ae1e2c9 (비교 기준 main, `git diff main...HEAD`)
> 범위: 코드와 시험으로 재현되는 동작 결함만 defect로 판정합니다.

## 1. 대상 변경 확인

`git log --oneline main..HEAD` 출력은 `1ae1e2c9 feat: 적격심사 판정 축과 문맥 저장 구현` 1건입니다.

`git diff main...HEAD --stat` 출력은 5개 파일입니다.

- migrations/versions/a2c7e9f1b4d6_add_snapshot_rule_scope_context.py (신규 41행)
- src/app/api/v1/evaluations.py (30행 변경)
- src/app/models/evaluations.py (5행 추가)
- src/app/services/evaluation_rules.py (181행 추가)
- tests/test_evaluation_rules_scope_axis.py (신규 214행)

`git diff main...HEAD --name-only -- tests/` 출력은 `tests/test_evaluation_rules_scope_axis.py` 1건이며 기존 시험 파일 수정은 없습니다.

## 2. 직접 실행한 검증 명령과 출력 요약

- `uv run pytest tests/test_evaluation_rules_scope_axis.py tests/test_evaluation_rules_pre.py tests/test_evaluations_api.py tests/test_evaluation_rules_meta_api.py tests/test_evaluation_models.py -q` 출력 요약줄은 `154 passed in 4.32s` 입니다.
- `uv run alembic heads` 출력은 `a2c7e9f1b4d6 (head)` 단일 head입니다.
- `python3 scripts/validate_agent_rules.py --quiet` 출력 요약줄은 `검증 통과: 21/21 건` 입니다.
- 추가 확인용으로 `uv run python -c`를 실행하여 등록 규칙 42건 전수, 패턴 134건 전수, 구·신 `_is_local_contract` 11종 입력 동치를 확인했습니다. 결과는 본문 각 항목에 적었습니다.

## 3. 항목별 판정

### 3.1 existing_results_unchanged: yes

기존 규칙 42건은 전부 `institution_scope ALL`, `contract_regime None`입니다. `src/app/services/evaluation_rules.py:19-22` 상수 정의, `src/app/services/evaluation_rules.py:49-50` 기본값, `tests/test_evaluation_rules_scope_axis.py:38-42` 고정 시험으로 확인했습니다.

축 인자 없이 134개 패턴 전수를 `resolve_evaluation_rule`에 전달하면 차단 0건, `scope_stage ALL` 134건입니다. 기존 별표 판정 뒤에 축 필터가 동작하므로(`src/app/services/evaluation_rules.py:1342-1353`), 등록 규칙만으로는 선택 규칙이 바뀌지 않습니다. 동일 specificity 재선택 시 `RULE_DEFAULT` 경고문을 같은 값으로 재생성하므로(`src/app/services/evaluation_rules.py:1404-1420`) 문구도 변하지 않습니다.

`_is_local_contract`은 `extract_contract_regime(...) == "LOCAL"` 위임으로 바뀌었을 뿐(`src/app/api/v1/evaluations.py:639-642`) 11종 입력에서 구 구현과 반환값이 전부 일치함을 직접 실행으로 확인했습니다. 스냅샷 문맥 인자는 기본값 `None`이므로(`src/app/api/v1/evaluations.py:1202-1206`) 기존 호출 경로의 응답을 바꾸지 않습니다.

기존 시험 파일 무수정과 위 154건 통과가 판정 불변을 뒷받침합니다.

### 3.2 precedence_and_fallback: yes

축 필터는 `_resolve_by_method_name` 확정 뒤에 적용됩니다(`src/app/services/evaluation_rules.py:1342-1353`). 동일 `service_type`와 동일 specificity로 후보를 좁힌 뒤(`src/app/services/evaluation_rules.py:1354-1389`) `for stage in (RULE_SCOPE_INSTITUTION, RULE_SCOPE_REGION, RULE_SCOPE_ALL)` 순서로 선택합니다(`src/app/services/evaluation_rules.py:1390`).

상위 단계 후보가 없으면 다음 단계로 후퇴하고, 끝까지 없으면 `BLOCK_CODE_RULE_NOT_FOUND`로 차단합니다(`src/app/services/evaluation_rules.py:1425-1434`). 같은 단계 후보가 둘 이상이면 `BLOCK_CODE_RULE_SCOPE_AMBIGUOUS`로 차단합니다(`src/app/services/evaluation_rules.py:1392-1403`, 블록 코드 정의 `src/app/services/evaluation_rules.py:1071`). `contract_regime` 지정 규칙은 공고 regime과 다르면 후보에서 제외됩니다(`src/app/services/evaluation_rules.py:1158-1159`).

각 분기는 새 시험으로 고정됐습니다. `tests/test_evaluation_rules_scope_axis.py:45-51` 기관 우선, `tests/test_evaluation_rules_scope_axis.py:54-66` 기관·지역·공통 순서, `tests/test_evaluation_rules_scope_axis.py:69-84` 후퇴 2건, `tests/test_evaluation_rules_scope_axis.py:87-98` 모호성 차단, `tests/test_evaluation_rules_scope_axis.py:114-118` regime 미상 제외입니다.

### 3.3 regime_not_guessed: yes

추출 함수는 `cntrctCnclsMthdNm`과 `cntrct_mthd_nm`을 이어 `지방` 포함 시에만 `LOCAL`을 돌려주고 그 밖에는 `None`입니다(`src/app/services/evaluation_rules.py:1134-1141`). 함수 전체에 `NATIONAL` 문자열이 없으며 직접 실행한 9종 입력에서도 `NATIONAL`은 0건입니다.

`_is_local_contract` 위임 전후 동치는 11종 입력(빈 문자열, None, 비딕셔너리, 숫자 0, `cntrct_mthd_nm`만 `지방`인 경우 포함)에서 전부 일치(`ALL_MATCH`)함을 직접 실행으로 확인했습니다. 새 시험 `tests/test_evaluation_rules_scope_axis.py:100-111`은 비지방 5종이 `None`·`False`임과 지방 표기 동치를 고정합니다. `resolve_evaluation_rule_from_raw_data`는 추출값을 그대로 전달하고 `NATIONAL` 추정을 하지 않습니다(`src/app/services/evaluation_rules.py:1733`).

### 3.4 migration_safety: yes

리비전은 `revision a2c7e9f1b4d6`, `down_revision 9d4e2b7a1c63`입니다(`migrations/versions/a2c7e9f1b4d6_add_snapshot_rule_scope_context.py:12-13`). `upgrade`는 `bid_evaluation_snapshots`에 nullable 컬럼 5개만 `add_column`합니다(`migrations/versions/a2c7e9f1b4d6_add_snapshot_rule_scope_context.py:18-33`). 타입과 길이는 `contract_regime VARCHAR(20)`, `institution_code VARCHAR(100)`, `institution_name VARCHAR(255)`, `region_code VARCHAR(100)`, `region_name VARCHAR(255)`이며 인덱스 생성, 기존 컬럼 변경, 데이터 UPDATE가 없습니다. `downgrade`는 같은 5개만 역순 `drop_column`합니다(`migrations/versions/a2c7e9f1b4d6_add_snapshot_rule_scope_context.py:36-41`).

ORM 정의는 `src/app/models/evaluations.py:97-101`에서 `String(20)`, `String(100)`, `String(255)`, `String(100)`, `String(255)`를 `nullable=True`로 선언하여 마이그레이션과 일치합니다. 기존 인덱스 블록(`src/app/models/evaluations.py:77-83`)에 변경이 없습니다. `uv run alembic heads`는 단일 head `a2c7e9f1b4d6`이며 새 시험 `tests/test_evaluation_rules_scope_axis.py:204-214`가 head 단일성과 `down_revision` 문자열을 고정합니다.

### 3.5 snapshot_context_path: yes

`_analyze_bid`는 `institution_name_fallback=bid.dminstt_nm`, `cntrct_mthd_nm=bid.cntrct_mthd_nm`을 resolver에 전달합니다(`src/app/api/v1/evaluations.py:1266-1271`). `analyze_evaluation`은 `success`·`blocked` 모두 같은 입력으로 문맥을 다시 구한 뒤(`src/app/api/v1/evaluations.py:1398-1405`) `_save_snapshot_async`에 5개 문맥값을 전달합니다(`src/app/api/v1/evaluations.py:1427-1431`). 따라서 차단 응답 스냅샷에도 추출된 문맥이 남습니다.

`_save_snapshot_async` 문맥 인자 5개는 기본값 `None`이며(`src/app/api/v1/evaluations.py:1202-1206`) 모델 생성자에 그대로 전달됩니다(`src/app/api/v1/evaluations.py:1214-1218`). 인자 생략 시 `NULL` 저장은 `tests/test_evaluation_rules_scope_axis.py:196-201`, 정상 기록은 `tests/test_evaluation_rules_scope_axis.py:184-195`로 고정됐습니다.

메타 API 응답 형식은 바뀌지 않았습니다. `SERVC_RULE_META_SCOPE_NOTE` 문구와 `_serialize_rule_meta` 12개 키는 `git show main:src/app/api/v1/evaluations.py`와 현재 파일에서 동일함을 직접 대조했습니다(노트 `src/app/api/v1/evaluations.py:1444-1447`, 직렬화 `src/app/api/v1/evaluations.py:1450-1476`, 응답 조립 `src/app/api/v1/evaluations.py:1505-1509`).

## 4. 차단 결함

없습니다. `verdict`는 `pass`입니다.

## 5. 비차단 제안

- `resolve_evaluation_rule`의 축 재선택 구간에서 `result.rule`과 `selected`가 같은 객체일 때도 경고문을 재생성합니다(`src/app/services/evaluation_rules.py:1406-1420`). 현재 값이 같아 동작은 같지만, 객체 동일 시 재생성을 건너뛰면 불필요한 리스트 복사를 줄일 수 있습니다.
- `analyze_evaluation`이 `_analyze_bid` 내부 resolver 결과와 별도로 스냅샷용 resolver를 한 번 더 호출합니다(`src/app/api/v1/evaluations.py:1400-1405`). 현재는 결정론적 순수 함수라 결과가 같지만, `_analyze_bid`가 문맥을 함께 반환하면 중복 호출을 없앨 수 있습니다.

## 6. 남은 작업

- 운영 MySQL에 `a2c7e9f1b4d6` 적용 후 G1 스키마 기준선을 생성해야 합니다. `tests/test_g1_baseline_drift_gate.py` 2건 실패는 본 검토 범위 밖이며 defect로 세지 않았습니다.
- `REGION` 추출값은 원천에 발주기관 지역 코드 필드가 없어 항상 `None`이며, `contract_regime`도 실데이터에서 사실상 항상 `None`입니다. 둘 다 의도된 동작으로 확인했습니다.
