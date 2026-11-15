# 한국지역난방공사 지사·사업소 코드 추가와 미선택 4건 원인 조사

> **작성일**: 2026-11-15
> **작업**: Orca Task `task_336d712decf7` (builder). 지사 코드 3개 추가, 회귀 시험, 조사 보고서.
> **정본 사양**: `.orca/capsules/task_kdhc_branch_codes_20261115/capsule.yaml` (`ORCA_TASK_CAPSULE_V2`)
> **작업 브랜치**: `kwanbum217/kdhcbr`
> **입력 자료**: 2026-11-15 기준 12개월 `Servc`·낙찰방법 `낙030001` 판정 덤프 27,638행(`scripts/judge_snapshot_diff.py dump --as-of 2026-11-15`)의 변경 전·후 스냅샷
> **판정**: candidate

---

## 0. 요약

1. `_KDHC_BRANCH_CODES` 에 용인지사 `D325100`·파주지사 `D325101`·고양사업소 `D325111` 을 더했습니다.
2. 판정 비교에서 바뀐 공고는 10건이고, 그중 9건은 공고가 「한국지역난방공사 일반용역 적격심사 세부기준」을 명시한 대상 공고입니다. 나머지 1건(`R26BK01809261`)은 공고 명시와 기관 규칙이 충돌하는 사례로, 2026-11-15 코디네이터 결정(C)에 따라 변경을 허용하고 이 문서 3.2절에 적었습니다.
3. 같은 세 지사의 기술용역 7건과 건설폐기물 3건은 판정이 바뀌지 않았습니다.
4. 원인을 확정하지 못했던 지역난방공사 일반용역 4건(`D325109` 3건·`D325115` 1건)의 미선택 원인을 확정했습니다. 조달청 대행 배제가 아니라, 공고일이 2026-01-01 이전이라 현행 규칙이 후보에서 빠지고 2023-07-19 시행판에는 시설분야·수리점검 규칙이 없기 때문입니다. 해당 4건의 코드는 고치지 않았습니다.

---

## 1. 추가한 지사·사업소 코드

`src/app/services/evaluation_rules_institution.py:150` 의 `_KDHC_BRANCH_CODES` 에 세 코드를 더했습니다. 목록은 대역 접두가 아니라 읽기 전용 DB 조회로 확인한 명시 코드만 담습니다.

| 코드 | 기관명 | 상위 기관 | 확인 방법 |
| --- | --- | --- | --- |
| `D325100` | 한국지역난방공사 용인지사 | `B550373` 한국지역난방공사 | `g2b_demand_institutions` 코드 조회, 공고 `raw_data.dminsttCd`·`dminsttNm` 대조 |
| `D325101` | 한국지역난방공사 파주지사 | `B550373` 한국지역난방공사 | 같음 |
| `D325111` | 한국지역난방공사 고양사업소 | `B550373` 한국지역난방공사 | 같음 |

- 조회 질의는 `scripts/db_readonly_query.py` 로 `dminstt_cd IN (...)` 키 조건만 썼고 테이블 전체 스캔이나 `LIKE` 검색은 쓰지 않았습니다.
- 코드 추가 근거는 `docs/analysis/appstd_vs_pps_default_20261115.md` 3.6절과 4절 3행입니다.
- 정확 코드 목록은 판본별 규칙 ID(`SERVC_INST_KDHC_*`)에 모두 붙으므로, 2026-01-01판·2026-08-18판·2023-07-19판 규칙이 같은 코드를 봅니다.

---

## 2. 판정 비교

### 2.1 방법

```text
uv run python scripts/judge_snapshot_diff.py dump --as-of 2026-11-15 --output .orca/tmp/judge_before.tsv
uv run python scripts/judge_snapshot_diff.py dump --as-of 2026-11-15 --output .orca/tmp/judge_after.tsv
uv run python scripts/judge_snapshot_diff.py diff .orca/tmp/judge_before.tsv .orca/tmp/judge_after.tsv \
  --expect .orca/capsules/task_kdhc_branch_codes_20261115/expect9.txt
```

- 변경 전·후 모두 27,638행입니다.
- 바뀐 공고는 10건(판정 변경 10건, 한쪽에만 있는 공고 0건)이고, `--expect` 집합과 정확히 일치해 종료 코드 0 입니다.

### 2.2 바뀐 공고 10건

| 공고 | 지사·사업소 | 낙찰방법명 | 공고일 | 변경 전 `rule_id` | 변경 후 `rule_id` |
| --- | --- | --- | --- | --- | --- |
| `R26BK01259230` | 파주지사 `D325101` | 시설분야용역 | 2026-01-05 | `SERVC_QUAL_PRE_20250901_ATTACH_01` | `SERVC_INST_KDHC_20260101_FACILITY` |
| `R26BK01272934` | 고양사업소 `D325111` | 수리·점검용역 | 2026-01-14 | `SERVC_QUAL_PRE_20250901_ATTACH_15` | `SERVC_INST_KDHC_20260101_REPAIR` |
| `R26BK01303924` | 파주지사 `D325101` | 시설분야용역 | 2026-01-29 | `SERVC_QUAL_PRE_20250901_ATTACH_01` | `SERVC_INST_KDHC_20260101_FACILITY` |
| `R26BK01371793` | 파주지사 `D325101` | 시설분야용역 | 2026-03-05 | `SERVC_QUAL_PRE_20250901_ATTACH_01` | `SERVC_INST_KDHC_20260101_FACILITY` |
| `R26BK01396735` | 용인지사 `D325100` | 시설분야용역 | 2026-03-16 | `SERVC_QUAL_PRE_20250901_ATTACH_01` | `SERVC_INST_KDHC_20260101_FACILITY` |
| `R26BK01461622` | 파주지사 `D325101` | 폐기물처리용역 | 2026-04-13 | `SERVC_QUAL_PRE_20250901_ATTACH_08` | `SERVC_INST_KDHC_20260101_WASTE` |
| `R26BK01466720` | 용인지사 `D325100` | 시설분야용역 | 2026-04-15 | `SERVC_QUAL_PRE_20250901_ATTACH_01` | `SERVC_INST_KDHC_20260101_FACILITY` |
| `R26BK01486262` | 파주지사 `D325101` | 폐기물처리용역 | 2026-04-23 | `SERVC_QUAL_PRE_20250901_ATTACH_08` | `SERVC_INST_KDHC_20260101_WASTE` |
| `R26BK01734726` | 파주지사 `D325101` | 수리·점검용역 | 2026-09-17 | `SERVC_QUAL_POST_20260526_ATTACH_15` | `SERVC_INST_KDHC_20260818_REPAIR` |
| `R26BK01809261` | 용인지사 `D325100` | 수리·점검용역 | 2026-11-04 | `SERVC_QUAL_POST_20260526_ATTACH_15` | `SERVC_INST_KDHC_20260818_REPAIR` |

- 앞 9건은 모두 공고 `sucsfbidMthdAppStd` 가 `한국지역난방공사 일반용역 적격심사 세부기준`이고 `srvceDivNm` 가 `일반용역`입니다. 기대한 대로 `PPS_DEFAULT` 에서 `INSTITUTION` 으로 바뀌었습니다.
- 폐기물처리용역 2건은 공고문이 환경부고시를 인용한 건설폐기물이 아니어서 공사 별표 4 규칙이 선택됐습니다. 같은 세 지사의 건설폐기물 3건(`R26BK01622145`·`R26BK01632151`·`R26BK01654279`)은 변경 전과 같이 `SERVC_QUAL_MOE_CDW_*` 로 남았습니다.
- 기술용역 7건(`R26BK01472025`·`R26BK01516874`·`R26BK01607232`·`R26BK01619856`·`R26BK01628050`·`R26BK01671454`·`R26BK01678323`)은 변경 전과 같이 `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT*` 로 남았습니다.

### 2.3 공고 명시와 기관 규칙 충돌 1건

`R26BK01809261`(용인지사, 2026-11-04, 수리·점검용역)은 `sucsfbidMthdAppStd` 가 `조달청 일반용역 적격심사 세부기준` 인데도 기관 코드 우선 설계에 따라 `SERVC_INST_KDHC_20260818_REPAIR` 로 바뀌었습니다.

- 현재 `_select_institution_rule`(`src/app/services/evaluation_rules.py:2632-2691`)은 공고 명시 기준을 보지 않고 수요기관 코드·납찰방법명으로 기관 규칙을 고릅니다.
- 2026-11-15 코디네이터 결정(C)으로 이 1건의 변경을 허용했습니다. 공고 명시 기준과 기관 규칙이 충돌하는 경우의 처리 방침은 별도 사용자 결정 대기 항목입니다.
- `evaluation_rules.py` 는 이번 작업에서 고치지 않았습니다.

---

## 3. 원인 미확정 4건 조사

### 3.1 대상 공고

변경 전 스냅샷에서 `dminsttCd` 가 `D325109`·`D325115` 이고 일반용역이면서 조달청 규칙으로 계산된 4건입니다. 4건 모두 12개월 창 안에 있습니다.

| 공고 | 코드 | 지사 | 공고일 | 낙찰방법명 | 변경 전 `rule_id` |
| --- | --- | --- | --- | --- | --- |
| `R25BK01167705` | `D325109` | 서울중앙지사 | 2025-11-20 | 수리·점검용역 고시금액 미만 | `SERVC_QUAL_PRE_20250901_ATTACH_15` |
| `R25BK01193316` | `D325115` | 삼송지사 | 2025-12-01 | 수리·점검용역 고시금액 미만 | `SERVC_QUAL_PRE_20250901_ATTACH_15` |
| `R25BK01229478` | `D325109` | 서울중앙지사 | 2025-12-15 | 수리·점검용역 고시금액 미만 | `SERVC_QUAL_PRE_20250901_ATTACH_15` |
| `R25BK01231018` | `D325109` | 서울중앙지사 | 2025-12-15 | 시설분야용역 5억원 미만 | `SERVC_QUAL_PRE_20250901_ATTACH_01` |

### 3.2 조달청 대행 배제는 원인이 아니다

4건의 `raw_data.ntceInsttCd`·`ntceInsttNm` 을 키 조회로 확인한 결과 모두 수요기관과 같은 `D325109`·`D325115` 였습니다.

| 공고 | `dminsttCd` | `ntceInsttCd` | `ntceInsttNm` |
| --- | --- | --- | --- |
| `R25BK01167705` | `D325109` | `D325109` | 한국지역난방공사 서울중앙지사 |
| `R25BK01193316` | `D325115` | `D325115` | 한국지역난방공사 삼송지사 |
| `R25BK01229478` | `D325109` | `D325109` | 한국지역난방공사 서울중앙지사 |
| `R25BK01231018` | `D325109` | `D325109` | 한국지역난방공사 서울중앙지사 |

`_is_pps_proxy_announcement`(`evaluation_rules.py:2602-2609`)는 기관명에 `조달청` 이 있거나 코드가 `1230` 으로 시작할 때만 참입니다. 네 공고는 모두 거짓이므로 `EXCLUDE_INSTITUTION_RULES_FOR_PPS_PROXY` 게이트(`evaluation_rules.py:2683-2691`)는 작동하지 않았습니다.

### 3.3 확정한 원인: 공고일 이전 판본에 시설분야·수리점검 규칙이 없다

4건의 공고일은 2025-11-20부터 2025-12-15까지로 모두 2026-01-01 이전입니다. `_select_institution_rule` 의 판본 필터가 다음 순서로 후보를 지웁니다.

1. `evaluation_rules.py:2665-2679` 는 `institution_code` 가 규칙의 본청 코드(`B550373`)와 다르고 규칙 ID 가 `INSTITUTION_RULE_EXACT_CODES` 에 있으면서 시행일이 공고일보다 늦으면 후보에서 뺍니다. 네 공고는 지사 코드로만 걸리므로 2026-01-01판·2026-08-18판 규칙이 모두 여기서 빠집니다.
2. 남는 후보는 2023-07-19 시행판뿐입니다. 등록된 판본은 폐기물처리용역(`evaluation_rules_institution.py:2432-2441`), 기타용역(`4056-4085`), 여객 육상운송용역(`4097-4116`) 세 가지이고, `PREDECESSOR_INSTITUTION_RULES`(`4124-4127`)에도 기타·여객만 들어 있습니다.
3. 따라서 시설분야용역과 수리·점검용역은 2023-07-19판 규칙이 없습니다. 남은 후보의 패턴(`폐기물처리`, `기타`, `여객육상운송`)은 네 공고의 납찰방법명(`수리ㆍ점검용역`, `시설분야용역`)과 맞지 않아 `_institution_match_score` 가 0 이 되고, `evaluation_rules.py:2711-2715` 에서 후보 없음으로 끝납니다.

결과적으로 기관 규칙 후보가 비어 종전 조달청 경로로 내려갔습니다. 이 4건을 공사 규칙으로 계산하려면 2023-07-19 시행판 원문에서 시설분야·수리점검 별표의 B·k·기준비율·통과점수·낙찰하한율을 확인해 판본 규칙으로 등록해야 합니다. 이번 작업 범위가 아니므로 코드는 고치지 않았습니다.

---

## 4. 검증

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_kdhc_branch_codes_20261115.py -q` | 8 passed |
| `uv run pytest tests/ -q -m 'not data_assets'` | 11,006 passed, 41 skipped, 3 deselected, 2 xfailed (323.25s) |
| `uv run mypy src` | Success: no issues found in 152 source files |
| `python3 scripts/validate_agent_rules.py --quiet` | 22/22 통과, 종료 코드 0 |
| `judge_snapshot_diff.py diff --expect expect9.txt` | 10건 일치, 종료 코드 0 |

- 회귀 시험 `tests/test_kdhc_branch_codes_20261115.py` 는 세 지사의 일반용역 대표 `raw_data`(시설분야·수리점검·폐기물)가 공사 규칙을 고르는지, 기술용역 대표 `raw_data` 가 종전 기술용역 규칙을 유지하는지, 그리고 3.2절 충돌 사례 1건의 현재 동작을 검사합니다. 실제 DB·Redis 에는 연결하지 않습니다.
- DB 조회는 모두 `scripts/db_readonly_query.py` 의 `SELECT` 였고 스키마·데이터를 변경하지 않았습니다.

---

## 5. 남은 결정

1. **공고 명시와 기관 규칙 충돌**: `R26BK01809261` 처럼 공고가 조달청 기준을 명시해도 기관 코드가 맞으면 기관 규칙을 쓰는 설계를 유지할지, 공고 명시 기준을 우선할지 결정이 필요합니다. 이번 작업에서는 2026-11-15 결정(C)에 따라 현 설계를 유지했습니다.
2. **2025년 시설분야·수리점검 공고 4건**: 2023-07-19 시행판 원문에서 해당 별표 값을 확인해 판본 규칙을 등록해야 공사 규칙으로 계산할 수 있습니다. 원문 확인 전에는 값을 추정하지 않습니다.
