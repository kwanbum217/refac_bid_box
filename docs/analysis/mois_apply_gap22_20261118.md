# 행안부 학술 띠 조사 70건 중 미계산 22건의 원인 확정 (2026-11-18)

> **작성일**: 2026-11-18
> **작업**: Orca Task `task_0c17e17677cf` (investigator, Run `run_82a17166254d`)
> **정본 사양**: `.orca/capsules/task_gap22_cause_20261118/capsule.yaml` (`ORCA_TASK_CAPSULE_V2`)
> **작업 브랜치**: `kwanbum217/gap22` (기준 커밋 `d43865a7`)
> **대조 입력**: `.orca/gap35_changed.tsv` (53행), `.orca/gap35_survey_unchanged.tsv` (22행), `docs/analysis/mois_academic_band_old_versions_20261118.md` 3.3절 70건
> **판정 정본**: [src/app/services/evaluation_rules.py](../../src/app/services/evaluation_rules.py), [src/app/services/evaluation_rules_local.py](../../src/app/services/evaluation_rules_local.py)
> **범위**: 원인 확정 문서 1건. 제품 코드·규칙·시험·DB 는 고치지 않았습니다. DB 는 `scripts/db_readonly_query.py` 읽기 전용 SELECT 만 사용했습니다.

---

## 1. 결론

1. **22건은 제283호 구판 규칙이 적용될 자리가 아니었습니다.** 22건 전부 수요기관 시·도가 **경기도(21건)·부산광역시(1건)** 이고, 그 시·도의 자체 적격심사 별표가 먼저 확정됩니다. 행안부 학술 띠 규칙으로 내려가는 구제 분기([evaluation_rules.py:4892-4934](../../src/app/services/evaluation_rules.py:4892))는 **"규칙을 못 찾아 차단된 경우"** 에만 실행되는데, 이 22건은 **규칙을 찾았기 때문에** 그 분기에 들어가지 않습니다.
2. 찾은 시·도 별표의 시행일이 공고일보다 늦습니다. 경기도 별표는 2025-08-08, 부산광역시 별표는 2025-06-26 시행인데 공고일은 2025-01-23 ~ 2025-05-29 입니다. 마지막 시행일 대조([evaluation_rules.py:5033-5058](../../src/app/services/evaluation_rules.py:5033))가 `RULE_REGIME_MISMATCH` 로 막습니다.
3. 그래서 이 22건은 제283호 병합(`d43865a7`)의 대상이 아니었고, 기준 스냅숏과 출력 스냅숏의 판정이 같습니다. 283 규칙 값이 틀렸거나 누락된 것이 아닙니다.
4. **세션 종료 문장의 "35건"은 묶음 4(`RULE_REGIME_MISMATCH`) 해소분만 센 수치입니다.** 같은 병합에서 묶음 16(`LOCAL_RULE_NOT_FOUND`) 13건도 함께 풀렸으므로 실제 해소는 48건이고, 남은 미계산은 35건이 아니라 22건입니다(2절).

---

## 2. 70 / 53 / 48 / 22 / 5 대조

두 TSV 의 데이터 행 수는 `gap35_changed.tsv` 53행, `gap35_survey_unchanged.tsv` 22행입니다. 22행의 공고번호는 53행과 겹치지 않습니다(교집합 0). 조사 보고서 3.3절의 70건과 53건을 공고번호로 대조하면 다음과 같습니다.

| 구분 | 건수 | 근거 |
| --- | ---: | --- |
| 조사 70건 중 판정이 바뀐 건 | 48 | 53 ∩ 70 |
| 조사 70건 중 판정이 그대로인 건 | 22 | `gap35_survey_unchanged.tsv` |
| 조사 밖에서 바뀐 오계산 정정 | 5 | R25BK00633539, R25BK00825399, R25BK00880281, R25BK00934697, R26BK01402983 |
| 판정 변경 합계 | 53 | 48 + 5, `gap35_changed.tsv` |

- `gap35_changed.tsv` 의 `before_block` 은 `RULE_REGIME_MISMATCH` 35, `LOCAL_RULE_NOT_FOUND` 13, 공란(오계산 정정) 5 입니다.
- 세션 종료 문장의 "35"는 이 가운데 첫 항목만 센 값입니다. 35 + 13 = 48 이 조사 70건의 해소분이고, 48 + 22 = 70 이 조사 70건입니다.
- 따라서 "아직 풀리지 않은 건수"는 35가 아니라 **22** 입니다. 22행은 모두 기준 스냅숏에서 `block_code=RULE_REGIME_MISMATCH` 이고, 이 문서 4절의 묶음으로 설명됩니다.

---

## 3. 공통 원인 구조

### 3.1 시·도 별표가 먼저 확정되고, 확정되면 행안부 구제 분기를 타지 않습니다

`contract_regime == "LOCAL"` 이면 조달청 규칙을 배제하고 시·도 규칙을 먼저 고릅니다. 시·도 규칙을 확정하면 조달청 단계의 차단을 해제합니다.

- [evaluation_rules.py:4632-4640](../../src/app/services/evaluation_rules.py:4632) — LOCAL 이면 `_select_local_rule` 호출
- [evaluation_rules.py:4818-4829](../../src/app/services/evaluation_rules.py:4818) — `selected` 가 있으면 `is_blocked=False`, `block_reason_code=None` 으로 덮어씀

### 3.2 행안부 학술 띠 구제는 "못 찾음" 차단 코드에서만 실행됩니다

- [evaluation_rules.py:4892-4897](../../src/app/services/evaluation_rules.py:4892) — 진입 조건이 `result.is_blocked` 이고 `block_reason_code` 가 `_MOIS_ACADEMIC_BAND_FALLBACK_BLOCK_CODES` 에 속할 때
- [evaluation_rules.py:3496-3502](../../src/app/services/evaluation_rules.py:3496) — 그 집합은 `RULE_NOT_FOUND`·`LOCAL_RULE_NOT_FOUND`·`LOCAL_SERVICE_TYPE_UNRESOLVED` 세 개뿐입니다. `RULE_REGIME_MISMATCH` 는 들어 있지 않습니다.

즉 이 22건은 3.1에서 이미 차단이 해제된 상태로 3.2에 도착하므로 `result.is_blocked` 가 거짓이고, `select_mois_academic_band_rule` 이 호출되지 않습니다. 시행일 대조는 그 뒤(3.3)에 실행되므로 구제 분기가 다시 열릴 기회가 없습니다.

### 3.3 시행일 대조가 마지막에 차단합니다

- [evaluation_rules.py:5033-5058](../../src/app/services/evaluation_rules.py:5033) — `announced < effective_date` 이면 `RULE_REGIME_MISMATCH`

### 3.4 시행 전 판본도 후보에서 지워지지 않습니다

`_narrow_to_current_regime` 은 공고일이 효력 구간에 드는 판본이 하나도 없으면 **시행일이 가장 늦은 판본을 남깁니다**.

- [evaluation_rules.py:2829-2838](../../src/app/services/evaluation_rules.py:2829) — `elif not in_window: narrowed.append(max(group, key=lambda rule: rule.effective_date))`

경기도·부산광역시 규칙은 시행일이 한 개뿐이라, 공고일이 그보다 앞서도 후보에서 빠지지 않고 그대로 선택됩니다. 이 설계는 "시행일 불일치 차단 유지" 결정에 따른 것이며, 3.3에서 차단되는 이유입니다.

### 3.5 학술 GENERAL 폴백 차단 예외는 세 지역으로 고정돼 있습니다

- [evaluation_rules.py:3146-3166](../../src/app/services/evaluation_rules.py:3146) — ACADEMIC 후보가 없으면 GENERAL 별표로 폴백. 다만 `academic_band_fallback` 이 참이고 지역이 예외 집합에 들 때만 `LOCAL_RULE_NOT_FOUND` 로 넘깁니다.
- [evaluation_rules.py:3487](../../src/app/services/evaluation_rules.py:3487) — 그 예외 집합은 `{"11", "28", "30"}` (서울·인천·대전)입니다. **경기도(41)·부산광역시(26)는 들어 있지 않습니다.**

### 3.6 띠 표기 판정과 학술 분류 게이트

- [evaluation_rules.py:3803-3806](../../src/app/services/evaluation_rules.py:3803) — `_is_band_only_method` 는 `2억미만` 과 `1억이상` 이 함께 있을 때만 참입니다. `1억미만`·`2억이상` 표기는 거짓입니다.
- [evaluation_rules.py:3038-3051](../../src/app/services/evaluation_rules.py:3038) — 학술 분류 띠 표기를 감지하면 세부유형을 `GENERAL/UNRESOLVED` 로 되돌려 GENERAL 별표로 보냅니다.
- [evaluation_rules.py:2593-2597](../../src/app/services/evaluation_rules.py:2593) — `2억미만 1억이상` 띠는 조달분류가 학술연구 계열일 때만 학술 열로 확정합니다.
- [evaluation_rules.py:2685-2694](../../src/app/services/evaluation_rules.py:2685) — 그 학술 분류는 조달분류 네 필드만 보고, 공고의 적용 기준 표기(`sucsfbidMthdAppStd`)는 근거로 쓰지 않습니다.

---

## 4. 22건 묶음과 규칙 선택 분기

### 4.1 묶음 요약

| 묶음 | 건수 | 선택된 별표 | 시행일 | 차단 지점 |
| --- | ---: | --- | --- | --- |
| A. 경기도 일반 별표 폴백 (조달분류 학술연구·미판정) | 20 | `SERVC_LOCAL_GG_20250808_ATTACH_1_6` | 2025-08-08 | `evaluation_rules.py:5054` |
| B. 경기도 폐기물 별표 (조달분류 폐기물) | 1 | `SERVC_LOCAL_GG_20250808_ATTACH_1_3` | 2025-08-08 | `evaluation_rules.py:5054` |
| C. 부산광역시 일반 별표 폴백 (조달분류 학술연구) | 1 | `SERVC_LOCAL_BUSAN_20250626_ATTACH_01` | 2025-06-26 | `evaluation_rules.py:5054` |
| **합계** | **22** | | | |

### 4.2 묶음 A — 경기도 일반 별표 폴백 20건

분기 사슬은 다음과 같습니다.

1. 수요기관 시·도가 경기도(41)라 시·도 규칙 후보가 잡힙니다([evaluation_rules.py:4632-4640](../../src/app/services/evaluation_rules.py:4632)).
2. 경기도에는 ACADEMIC 별표가 없습니다. `2억미만 1억이상` 표기는 `_is_band_only_method` 가 참이라([evaluation_rules.py:3803-3806](../../src/app/services/evaluation_rules.py:3803)) `mois_academic_band` 조건의 `not _is_band_only_method` 가 거짓이 되고([evaluation_rules.py:3038-3043](../../src/app/services/evaluation_rules.py:3038)), `1억미만`·`2억이상` 표기는 `mois_academic_band` 가 참이 되어 세부유형이 `GENERAL/UNRESOLVED` 로 바뀝니다([evaluation_rules.py:3047-3051](../../src/app/services/evaluation_rules.py:3047)). 두 경우 모두 ACADEMIC 후보가 없습니다.
3. GENERAL 폴백 분기에서 `academic_band_fallback` 은 참이지만 지역 41 이 예외 집합에 없으므로 차단으로 넘어가지 않고 경기도 GENERAL 별표를 후보로 씁니다([evaluation_rules.py:3146-3166](../../src/app/services/evaluation_rules.py:3146), [evaluation_rules.py:3487](../../src/app/services/evaluation_rules.py:3487)).
4. 경기도 일반용역 별표는 시행일 2025-08-08 한 판본뿐입니다([evaluation_rules_local.py:1950-1964](../../src/app/services/evaluation_rules_local.py:1950)). 공고일이 그보다 앞서므로 시행일 대조에서 `RULE_REGIME_MISMATCH` 로 막힙니다([evaluation_rules.py:5054-5058](../../src/app/services/evaluation_rules.py:5054)).

| # | 공고번호 | 공고일 | 낙찰방법 띠 | 조달분류 중분류 | 선택 별표 |
| ---: | --- | --- | --- | --- | --- |
| 1 | `R25BK00601627` | 2025-01-23 | 2억미만 1억이상 | 학술연구서비스 | `SERVC_LOCAL_GG_20250808_ATTACH_1_6` |
| 2 | `R25BK00613676` | 2025-02-04 | 2억미만 1억이상 | 학술연구서비스 | 위와 같음 |
| 3 | `R25BK00649138` | 2025-02-17 | 1억미만 | 학술연구서비스 | 위와 같음 |
| 4 | `R25BK00654280` | 2025-02-18 | 2억미만 1억이상 | 학술연구서비스 | 위와 같음 |
| 5 | `R25BK00668071` | 2025-02-24 | 2억미만 1억이상 | 학술연구서비스 | 위와 같음 |
| 6 | `R25BK00672163` | 2025-02-26 | 2억미만 1억이상 | 학술연구서비스 | 위와 같음 |
| 7 | `R25BK00717341` | 2025-03-17 | 1억미만 | 학술연구서비스 | 위와 같음 |
| 8 | `R25BK00741984` | 2025-03-25 | 2억이상 | 학술연구서비스 | 위와 같음 |
| 9 | `R25BK00817387` | 2025-04-28 | 2억미만 1억이상 | 학술연구서비스 | 위와 같음 |
| 10 | `R25BK00823009` | 2025-04-30 | 1억미만 | 학술연구서비스 | 위와 같음 |
| 11 | `R25BK00823744` | 2025-05-01 | 2억미만 1억이상 | 학술연구서비스 | 위와 같음 |
| 12 | `R25BK00825238` | 2025-05-01 | 2억미만 1억이상 | 학술연구서비스 | 위와 같음 |
| 13 | `R25BK00827163` | 2025-05-02 | 2억이상 | 학술연구서비스 | 위와 같음 |
| 14 | `R25BK00830776` | 2025-05-07 | 2억미만 1억이상 | 학술연구서비스 | 위와 같음 |
| 15 | `R25BK00840356` | 2025-05-12 | 1억미만 | 학술연구서비스 | 위와 같음 |
| 16 | `R25BK00842054` | 2025-05-13 | 2억미만 1억이상 | 학술연구서비스 | 위와 같음 |
| 17 | `R25BK00846794` | 2025-05-15 | 2억미만 1억이상 | 학술연구서비스 | 위와 같음 |
| 18 | `R25BK00862330` | 2025-05-22 | 2억미만 1억이상 | 학술연구서비스 | 위와 같음 |
| 19 | `R25BK00874792` | 2025-05-28 | 2억미만 1억이상 | 학술연구서비스 | 위와 같음 |
| 20 | `R25BK00876178` | 2025-05-29 | 2억이상 | 운영 및 유지관리(ICT) | 위와 같음 |

`R25BK00649138`(광주도시관리공사)은 이름과 달리 **광주광역시 소속이 아니라 경기도 광주시 소속 지방공기업**입니다. 수요기관 코드 `Z003653` 의 지역은 `rgn_cd=41610`(경기도 광주시), 최상위 기관은 `경기도` 입니다. 따라서 경기도 별표 경로를 탑니다.

`R25BK00876178`(경기도 수원시)은 공고문이 학술연구용역 기준을 인용하지만 조달분류가 `ICT 서비스/운영 및 유지관리` 입니다. 학술 분류가 아니어도 `2억이상` 표기는 분류 게이트를 보지 않으므로([evaluation_rules.py:2607-2614](../../src/app/services/evaluation_rules.py:2607)) 같은 경기도 GENERAL 별표로 확정됩니다.

### 4.3 묶음 B — 경기도 폐기물 별표 1건

1. `R25BK00651689`(남양주도시공사)는 조달분류 중분류가 `폐기물 처리` 입니다. 세부유형이 WASTE 로 확정되어 후보가 경기도 폐기물 별표로 좁혀집니다([evaluation_rules.py:3123](../../src/app/services/evaluation_rules.py:3123), [evaluation_rules.py:3179](../../src/app/services/evaluation_rules.py:3179)).
2. 경기도 폐기물 별표는 시행일 2025-08-08 한 판본입니다([evaluation_rules_local.py:1879-1905](../../src/app/services/evaluation_rules_local.py:1879)).
3. 공고일 2025-02-18 이 시행일보다 앞서 `RULE_REGIME_MISMATCH` 로 막힙니다([evaluation_rules.py:5054-5058](../../src/app/services/evaluation_rules.py:5054)).

이 건은 조달분류가 학술연구 계열이 아니므로, 설령 구제 분기에 닿았더라도 `2억미만 1억이상` 띠의 학술 확정은 일어나지 않습니다([evaluation_rules.py:2593-2597](../../src/app/services/evaluation_rules.py:2593)). 공고문의 적용 기준 표기(`학술연구용역 적격심사 세부기준`)는 확정 근거로 쓰지 않는 설계입니다([evaluation_rules.py:2685-2694](../../src/app/services/evaluation_rules.py:2685)).

### 4.4 묶음 C — 부산광역시 일반 별표 폴백 1건

1. `R25BK00671447`(부산광역시)은 조달분류가 학술연구서비스이고 `2억미만 1억이상` 표기입니다. 부산광역시에는 ACADEMIC 별표가 없어 묶음 A 와 같은 GENERAL 폴백 분기를 탑니다([evaluation_rules.py:3146-3166](../../src/app/services/evaluation_rules.py:3146)). 지역 26 역시 예외 집합 `{"11","28","30"}` 에 없습니다([evaluation_rules.py:3487](../../src/app/services/evaluation_rules.py:3487)).
2. 선택된 부산광역시 일반용역 별표는 시행일 2025-06-26 입니다([evaluation_rules_local.py:2002-2022](../../src/app/services/evaluation_rules_local.py:2002)).
3. 공고일 2025-02-25 가 시행일보다 앞서 `RULE_REGIME_MISMATCH` 로 막힙니다([evaluation_rules.py:5054-5058](../../src/app/services/evaluation_rules.py:5054)).

---

## 5. 재현과 확인

### 5.1 대조 산술

```sh
awk -F'\t' 'NR>1' .orca/gap35_changed.tsv | wc -l          # 53
awk -F'\t' 'NR>1' .orca/gap35_survey_unchanged.tsv | wc -l # 22
```

두 파일의 공고번호 집합은 겹치지 않습니다(교집합 0). `gap35_changed.tsv` 의 `before_block` 집계는 `RULE_REGIME_MISMATCH` 35, `LOCAL_RULE_NOT_FOUND` 13, 공란 5 입니다.

### 5.2 판정 재현

읽기 전용 DB 조회로 22건의 원문 필드와 수요기관 지역을 읽고, `resolve_evaluation_rule` 을 `contract_regime="LOCAL"`, 수요기관 최상위 시·도 코드(경기도 41, 부산광역시 26)로 직접 호출했습니다. 22건 전부 다음 두 값이 재현됐습니다.

| 항목 | 결과 |
| --- | --- |
| `is_blocked` | 22건 전부 참 |
| `block_reason_code` | 22건 전부 `RULE_REGIME_MISMATCH` |
| `rule.rule_id` | 경기도 일반 20, 경기도 폐기물 1, 부산광역시 일반 1 |

호출은 저장소 코드를 바꾸지 않았고, 운영 Redis 캐시를 쓰지 않는 순수 해석 함수만 사용했습니다. DB 질의는 `uv run python scripts/db_readonly_query.py` 와 같은 읽기 전용 세션(`run_query`)으로 `bid_announcements`·`g2b_demand_institutions` 만 SELECT 했습니다.

### 5.3 규칙 검증

| 명령 | 결과 |
| --- | --- |
| `python3 scripts/validate_agent_rules.py --quiet` | 22/22 통과 |

---

## 6. 확인하지 못한 것과 남은 일

1. **경기도·부산광역시 구판본 원문은 이 작업 범위 밖입니다.** 이 22건을 제283호 학술 규칙으로 계산하려면 시·도 우선 원칙을 깨야 하므로, 해소 방법은 둘 중 하나입니다. (가) 경기도·부산광역시 예규의 2025-08-08·2025-06-26 이전 판본을 원문으로 확보해 등록한다. (나) 학술 띠 공고의 GENERAL 폴백 예외 지역을 넓히는 정책을 결정한다.
2. **`R25BK00651689` 는 학술 띠가 아닙니다.** 조달분류가 폐기물 처리이고 공고 하한율도 87.745% 입니다. 구판본 등록 대상은 경기도 폐기물 별표이지 행안부 학술 별표가 아닙니다.
3. **이 문서는 원인 확정만 합니다.** 코드·규칙·시험은 고치지 않았고, 판정 덤프도 다시 돌리지 않았습니다. 위 결정은 코디네이터·사용자 몫입니다.

---

## 7. 변경 파일

| 경로 | 내용 |
| --- | --- |
| `docs/analysis/mois_apply_gap22_20261118.md` | 이 문서 1건 |
