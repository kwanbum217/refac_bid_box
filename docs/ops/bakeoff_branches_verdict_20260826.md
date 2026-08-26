# 워커 베이크오프 미병합 브랜치 회수/폐기 판정 보고서

> **작성일**: 2026-08-26
> **작성 근거**: `run_0e78bf666e8c / task_4190ee358120` 정본 사양
> **대상 브랜치 수**: 9개 (b2- 계열 5개 + bakeoff- 계열 4개)
> **마지막 커밋**: 전부 2026-08-20
> **판정 기준**: `scripts/audit_model_inventory.py` 가 main 에서 가진 기능을 회수 후보로 올리지 않는다

---

## 1. 판정 요약

| # | 브랜치 | 과제 | main 대비 고유 추가 | 회수 권고 |
| :---: | --- | --- | --- | :---: |
| 1 | `kwanbum217/b2-deepseek` | `--json` 출력 옵션 | `--json` + `_pools_report()` 분리 함수 | **폐기** (중복, 회수 가치 없음) |
| 2 | `kwanbum217/b2-laguna_xs` | `--json` 출력 옵션 | `--json` + `audit()` 3-tuple 반환 + `PoolStatus` 타입 alias | **폐기** (중복) |
| 3 | `kwanbum217/b2-mimo` | `--json` 출력 옵션 | `--json` + `_collect_pool_results()` 분리 함수 | **폐기** (중복) |
| 4 | `kwanbum217/b2-oc_nemo3ultra` | `--json` 출력 옵션 | `--json` + `audit(json_output=)` 시그니처 변경 | **폐기** (중복, 시그니처 변경은 회수 비용↑) |
| 5 | `kwanbum217/b2-or_nemoultra` | `--json` 출력 옵션 | `--json` + `_audit_with_json()` helper + `audit()` 시그니처 유지 | **회수 후보** (가장 균형 잡힌 분리) |
| 6 | `kwanbum217/bakeoff-deepseek` | 연속 미관측 기반 관측 이력 판정 | `absent_streak` + `observations` 이력 + `--state` 기본값을 `DEFAULT_STATE_PATH` 로 강제 | **폐기** (개념은 main 의 counter 와 동일) |
| 7 | `kwanbum217/bakeoff-mimo` | 연속 미관측 기반 관측 이력 판정 | `consecutive_absent` + `audit_with_state` 분리 함수 | **회수 후보** (가장 깔끔한 분리) |
| 8 | `kwanbum217/bakeoff-nemotron_ultra` | 연속 미관측 기반 관측 이력 판정 | `consecutive_absent` + `observations` + `reset_state` 파라미터 | **폐기** (개념 중복) |
| 9 | `kwanbum217/bakeoff-oc_nemotron_ultra` | 연속 미관측 기반 관측 이력 판정 | `absent_count` + `last_observation` + 의심 항목 별도 섹션 | **폐기** (개념 중복) |

총 9 개 중 회수 후보는 **2 개** (b2-or_nemoultra, bakeoff-mimo), 나머지 7 개는 **폐기 권고**입니다.

---

## 2. 판정 근거 (main 의 `scripts/audit_model_inventory.py` 상태)

`source_commit = 70a4ec4` (현재 main HEAD = `918881e`, `CURRENT_STATE.md` 기준) 가 가진 기능은 다음과 같습니다.

| 기능 | main 보유 | 비고 |
| --- | :---: | --- |
| `--state` 옵션 (사용자 정의 경로) | 보유 | line 215-220 |
| `--reset-state` 옵션 | 보유 | line 221-224 |
| `--with-agy` 옵션 | 보유 | line 210-213 |
| `_update_history()` counter 추적 | 보유 | `counter` 키, line 116-143 |
| 종료 코드 0/1/2 의미 정의 | 보유 | line 149-152 |
| `--json` 출력 옵션 | **미보유** | b2- 계열 5 개가 추가 대상 |
| `absent_streak` / `consecutive_absent` / `absent_count` 키 명명 | **미보유** | bakeoff- 계열 4 개가 추가 대상 |
| `observations` 이력 누적 (HISTORY_LIMIT) | **미보유** | 일부 bakeoff- 가 추가 대상 |
| 의심 항목 별도 섹션 | **미보유** | bakeoff-oc_nemotron_ultra 가 추가 대상 |
| `audit_with_state()` 명시적 함수 분리 | **미보유** | bakeoff-mimo 가 추가 대상 |

main 의 `_update_history()` 는 `counter` 라는 정수 키로 absent 횟수를 누적하며, `--state` 미지정 시 기본 `STATUS_PATH` ( `data/model_inventory_history.json` ) 에 저장합니다. 따라서 **연속 미관측 추적 개념 자체는 이미 main 에 들어 있습니다**. 차이는 키 명명, observations 이력 누적, 함수 분리 구조에 국한됩니다.

---

## 3. b2- 계열 ( `--json` 출력 옵션 ) 상세 비교

5 개 브랜치는 모두 `scripts/audit_model_inventory.py` 에 `--json` 출력 옵션을 추가하는 같은 과제를 다룹니다. 회수 가치가 가장 높은 구현을 가려냅니다.

### 3.1 구현 차이

| 브랜치 | `audit()` 시그니처 변경 | pools 데이터 구축 방식 | main 호환성 |
| --- | --- | --- | :---: |
| b2-deepseek | 변경 없음 ( `tuple[int, list[str]]` ) | 별도 `_pools_report()` 함수에서 사후 조회 | **호환** |
| b2-laguna_xs | 변경: `tuple[int, list[str], PoolStatus]` | `audit()` 내부에서 누적, `PoolStatus` 타입 alias | **비호환** (시그니처 변경) |
| b2-mimo | 변경 없음 ( `tuple[int, list[str]]` ) | 별도 `_collect_pool_results()` 함수로 분리, `audit()` 는 그 결과를 가공 | **호환** |
| b2-oc_nemo3ultra | 변경: `tuple[int, list[str] \| dict]` + `json_output` 파라미터 | `audit()` 본문에서 `if not json_output:` 가드, `pools_result` 누적 | **비호환** (시그니처 변경) |
| **b2-or_nemoultra** | 변경 없음 ( `tuple[int, list[str]]` ) | 별도 `_audit_with_json()` helper, `audit()` 는 그 helper 를 호출해 `(missing, lines, _)` 만 사용 | **호환** |

### 3.2 회수 후보 선정 ( b2- 계열 )

`b2-or_nemoultra` 를 회수 후보로 지목합니다.

근거:
- `audit()` 의 시그니처를 유지해 **기존 호출자와 테스트가 그대로 동작**합니다.
- `_audit_with_json()` helper 분리로 `--json` 분기 로직이 본문에서 빠져 가독성이 좋습니다.
- `b2-laguna_xs`, `b2-oc_nemo3ultra` 처럼 시그니처를 깨지 않습니다.
- `b2-deepseek`, `b2-mimo` 와 비교해 `pools` 데이터 소스가 단일 함수에서 한 번에 만들어져 상태 정합성이 더 명확합니다.

폐기 권고 4 개 ( b2-deepseek, b2-laguna_xs, b2-mimo, b2-oc_nemo3ultra ) 는 회수 후보 1 개와 **기능적으로 동등**합니다. 같은 과제에 여러 모델을 태운 결과물이며, 분리도가 더 낮거나 시그니처를 변경해 회수 비용만 키웁니다.

---

## 4. bakeoff- 계열 ( 연속 미관측 기반 관측 이력 판정 ) 상세 비교

4 개 브랜치는 모두 `scripts/audit_model_inventory.py` 에 관측 이력 기반 반복 확인 로직을 추가하는 같은 과제를 다룹니다. main 의 `counter` 추적은 이미 존재하므로, **추가 회수 가치가 있는 구현**은 다음 조건을 만족해야 합니다.

1. 기존 `audit()` 시그니처를 깨지 않거나 깨더라도 분리 함수로 호출자를 보호한다.
2. `observations` 같은 진정한 이력(리스트)을 누적해 단순 카운터 이상의 가치를 제공한다.
3. main 의 `counter` 추적과 의미가 호환된다 ( absent=증가, present=0, unknown=보존 ).

### 4.1 구현 차이

| 브랜치 | 핵심 키 | observations 이력 | main `audit()` 호환 | 추가 가치 |
| --- | --- | :---: | :---: | --- |
| bakeoff-deepseek | `absent_streak` | 보유 (`HISTORY_LIMIT=30`) | **비호환** ( `audit()` 시그니처 변경 + `--state` default 가 `DEFAULT_STATE_PATH` 로 강제) | 강제 상태 파일 |
| **bakeoff-mimo** | `consecutive_absent` | 미보유 (메타데이터 보너스 없음) | **호환** ( `audit()` 시그니처 유지 + `audit_with_state()` 분리) | 명시적 `audit_with_state` 분리 |
| bakeoff-nemotron_ultra | `consecutive_absent` | 보유 ( observations 리스트 ) | **비호환** ( `audit()` 시그니처 변경 + `reset_state` 파라미터 추가 ) | observations + reset |
| bakeoff-oc_nemotron_ultra | `absent_count` | 미보유 | **비호환** ( `audit()` 시그니처 변경 + `reset_state` 파라미터 ) | 의심 항목 별도 섹션 |

### 4.2 회수 후보 선정 ( bakeoff- 계열 )

`bakeoff-mimo` 를 회수 후보로 지목합니다.

근거:
- `audit()` 시그니처 ( `tuple[int, list[str]]` ) 가 **main 과 동일**하여 기존 호출자 ( 테스트, CLI, 다른 스크립트 ) 가 깨지지 않습니다.
- `audit_with_state()` 라는 **명시적 신규 함수**로 상태 기반 로직이 분리되어, 기존 path 와 신규 path 가 공존합니다. `--state` 지정 시에만 신규 path 가 활성화되므로 점진적 도입이 가능합니다.
- `_update_consecutive_absent()` 헬퍼가 absent=증가, present=0, unknown=보존 의 세 가지 상태 규칙을 한 곳에 모아 main 의 `_update_history` 와 의미가 일치합니다.
- `observations` 이력 자체는 없지만, `consecutive_absent` 카운터 + `status` 키 조합으로 회수 가치가 충분합니다.

폐기 권고 3 개 ( bakeoff-deepseek, bakeoff-nemotron_ultra, bakeoff-oc_nemotron_ultra ) 의 사유:
- 모두 `audit()` 시그니처를 변경해 **호환성 회귀**를 일으킵니다.
- bakeoff-deepseek 는 `--state` default 를 `DEFAULT_STATE_PATH` 로 강제해 기존 호출자 ( `--state` 없이 호출 ) 가 의도와 다르게 동작할 수 있습니다.
- bakeoff-nemotron_ultra 는 `audit()` 에 `reset_state` 파라미터를 추가해 책임이 섞입니다.
- bakeoff-oc_nemotron_ultra 의 의심 항목 별도 섹션은 UX 개선일 뿐 회수 가치가 낮습니다.

---

## 5. 종합 권고

| 계열 | 회수 후보 1 | 회수 후보 2 | 폐기 권고 |
| --- | --- | --- | --- |
| b2- ( `--json` ) | `kwanbum217/b2-or_nemoultra` ( commit `5dc2a2b` ) | - | b2-deepseek, b2-laguna_xs, b2-mimo, b2-oc_nemo3ultra |
| bakeoff- ( 연속 미관观测 ) | `kwanbum217/bakeoff-mimo` ( commit `c95cd60` ) | - | bakeoff-deepseek, bakeoff-nemotron_ultra, bakeoff-oc_nemotron_ultra |

회수 후보 2 개는 **서로 다른 과제**를 다룹니다. 두 회수를 동시에 진행할 때 충돌이 없도록 작업 트리를 분리하고 한 브랜치씩 검증·병합하는 것이 안전합니다.

### 5.1 회수 시 유의 사항 ( 다음 Task 참고 )

1. **b2-or_nemoultra 의 `_audit_with_json()` 적용 시** main 의 `audit()` 호출자 ( `tests/test_audit_model_inventory.py` 등 ) 가 `(missing, lines)` 만 받도록 되어 있는지 확인이 필요합니다. 시그니처는 동일하므로 직접적인 호환성 문제는 없으나, `pools_json` 의 키 명명 ( `streak` ) 이 main 의 `counter` 와 다르므로 보고용 출력의 의미가 일치하는지 확인이 필요합니다.
2. **bakeoff-mimo 의 `audit_with_state()` 적용 시** `--state` 미지정 경로가 main 의 동작과 동일한지 ( `--state` 없으면 카운터 추적 OFF ) 검증이 필요합니다. main 의 기본 동작은 `--state` 없이 호출해도 `STATUS_PATH` 에 기록되므로, 두 동작이 같은지·다른지 명시적 합의가 필요합니다.
3. **두 회수 모두** PR 절차 없이 ( 1인 작업 ) 작업 브랜치에서 검증 후 `main` 에 `git merge --no-ff` 로 병합합니다.
4. **이 보고서는 회수·폐기 권고만 포함합니다.** 브랜치 자체의 삭제는 본 Task 범위가 아니므로, 회수·폐기 결정은 코디네이터가 별도 Task 로 분리해 실행해야 합니다.

---

## 6. 메타데이터

| 항목 | 값 |
| --- | --- |
| source_commit ( main ) | `918881e` |
| `docs/context/CURRENT_STATE.md` source_commit | `70a4ec4` |
| 마지막 검증 시각 | 2026-08-26 (KST) |
| 검증 명령 | `git diff main..<branch> -- scripts/audit_model_inventory.py` ( 각 9 회 ) |
| 회수 후보 수 | 2 ( b2-or_nemoultra, bakeoff-mimo ) |
| 폐기 권고 수 | 7 |
