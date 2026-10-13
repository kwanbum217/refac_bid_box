# 기관 하위 조직 적용 후속 (R4 후속)

> **작성일**: 2026-10-13
> **작업**: R4 후속 2건. 메타 scope_note 하위 조직 반영과 옛 환경부 소속기관 코드 대역(1481) 포함
> **정본 사양**: `.orca/capsules/task_b0297f7d0ac6/capsule.yaml` (`ORCA_TASK_CAPSULE_V2`)
> **정본 설계**: [institution_subunit_scope_20261013.md](institution_subunit_scope_20261013.md) 5~6절
> **선행 문서**: [institution_subunit_apply_20261013.md](institution_subunit_apply_20261013.md) (R4)
> **코드 정본**: [src/app/services/evaluation_rules.py](../../src/app/services/evaluation_rules.py), [src/app/api/v1/evaluations.py](../../src/app/api/v1/evaluations.py)
> **기준 브랜치**: `kwanbum217/m1-meta-old-env-code` (기준 `main`)

---

## 1. 요약

R4 후속으로 (1) 메타 API 범위 안내(`SERVC_RULE_META_SCOPE_NOTE`)에 하위 조직 확장 3곳을 사실대로
반영하고, (2) R4 가 환경부 코드 대역을 `1482` 로만 잡아 제외되던 옛 환경부 소속기관 코드
`1481xxx` 를 원문·DB 로 확인해 코드 대역에 포함했습니다. 판정 알고리즘(`_axis_matches`)과 다른
기관 선언은 손대지 않았고, 환경부 규칙의 `subunit_code_prefixes` 만 `("1482", "1481")` 로
넓혔습니다.

| 항목 | 값 |
| --- | --- |
| 변경 1 | `SERVC_RULE_META_SCOPE_NOTE` 에 하위 조직 확장 3곳(국토교통부·환경부·한국석유공사) 문장 추가 |
| 변경 2 | 환경부 규칙 `subunit_code_prefixes` `("1482",)` → `("1482", "1481")` |
| 새 시험 | 옛 환경부 코드(1481) 대역 매칭, 대역 밖 코드 제외, scope_note 하위 조직 문구 |
| DB 스키마·데이터 변경 | 없음 (읽기 전용 조회만) |
| 판정 알고리즘 | 변경 없음 (기존 하위 조직 2차 판정을 그대로 씀) |

---

## 2. 메타 scope_note 하위 조직 반영

`SERVC_RULE_META_SCOPE_NOTE`(`src/app/api/v1/evaluations.py`)는 조달청 별표 14종만 목록에
담고 지방계약·확인 기관 규칙은 목록에서 뺀다는 사실을 밝힙니다. R4 반영 문서 6절이 "하위 조직
문장을 아직 반영하지 않았다"고 남긴 후속을 닫아, 확인 기관 중 국토교통부·환경부·한국석유공사
3곳은 원문 적용 범위 조항이 하위 조직(소속기관·지사·사무소)을 적용 주체로 명시해 그 하위 조직
공고도 기관 규칙으로 판정한다는 문장을 덧붙였습니다. 기존 문구(14종·기관 10곳·목록 제외)는
그대로 유지합니다.

- 문구는 `GET /api/v1/evaluations/rules` 의 `scope_note` 로 그대로 노출됩니다.
- 문구의 사실성은 시험으로 고정합니다. `tests/test_evaluation_rules_meta_api.py` 의
  `test_scope_note_states_local_and_institution_rules_excluded` 가 `INSTITUTION_RULES` 에서
  실제 하위 조직 선언이 있는 기관 집합이 `{국토교통부, 환경부, 한국석유공사}` 인지 확인하고,
  scope_note 에 "하위 조직" 과 그 3개 기관명이 들어 있는지 봅니다.

---

## 3. 옛 환경부 소속기관 코드 1481 대역 포함

### 3.1 기관표 조회 (g2b_demand_institutions)

```sql
SELECT dminstt_cd, dminstt_nm
FROM procurement.g2b_demand_institutions
WHERE dminstt_cd LIKE '148%'
ORDER BY dminstt_cd;
```

- `1480083`~`1480780` 은 옛 표기 `환경부 …`(국립환경연구원·유역환경관리청 등), `1481019`~
  `1481195` 도 옛 표기 `환경부 …`(국가미세먼지정보센터·국립환경과학원 물환경연구부 센터 등),
  `1482000`~`1482309` 는 현행 `기후에너지환경부 …` 입니다.
- `148%` 대역 전체가 `환경부` 또는 `기후에너지환경부` 로 시작해, **환경부 계열이 아닌 다른
  기관은 섞여 있지 않습니다.** 1481 대역 네 코드는 모두 환경부 소속기관입니다.

| 코드 | 수요기관명 |
| --- | --- |
| `1481000` | 환경부 국립환경인재개발원 |
| `1481019` | 환경부 국가미세먼지정보센터 |
| `1481022` | 환경부 물관리위원회지원단 |
| `1481185` | 환경부 국립환경과학원 물환경연구부 한강통합물환경센터 |
| `1481195` | 환경부 국립환경과학원 물환경연구부 금강물환경센터 |

### 3.2 공고 실측 (bid_announcements)

```sql
SELECT JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.dminsttCd')) AS cd, dminstt_nm, COUNT(*) AS n
FROM procurement.bid_announcements
WHERE JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.dminsttCd')) LIKE '1481%'
GROUP BY cd, dminstt_nm
ORDER BY cd, n DESC;
```

| 코드 | 수요기관명 | 건수 | 최초 공고 | 최근 공고 |
| --- | --- | ---: | --- | --- |
| `1481000` | 환경부 국립환경인재개발원 | 2 | 2022-01-25 | 2023-11-20 |
| `1481019` | 환경부 국가미세먼지정보센터 | 315 | 2019-12-10 | 2026-09-22 |
| `1481185` | 환경부 국립환경과학원 물환경연구부 한강통합물환경센터 | 185 | 2015-01-12 | 2026-10-08 |
| `1481195` | 환경부 국립환경과학원 물환경연구부 금강물환경센터 | 107 | 2015-03-05 | 2026-10-07 |

- 1481 대역 공고는 2026-10 까지 계속 나오므로, R4 대역(`1482`)만으로는 이 공고들이
  환경부 하위 조직으로 잡히지 않는 실제 공백이었습니다(선행 문서 4.2절의 2025-06-01 이후
  용역 86건 = `1481019` 65 + `1481185` 7 + `1481195` 14 와 일치).
- 공고에 실린 1481 대역 수요기관명은 전부 `환경부 …` 로, 환경부 소속이 아닌 기관은 없습니다.

### 3.3 코드 변경과 오탐 차단

- 환경부 규칙(`SERVC_INST_ME_20251111_TECH`)의 `subunit_code_prefixes` 를
  `("1482",)` → `("1482", "1481")` 로 넓혔습니다. `_axis_matches` 의 하위 조직 2차 판정이
  이 대역을 그대로 읽으므로 판정 알고리즘은 바뀌지 않습니다.
- 정확 일치가 먼저이고(코드 정확 일치 → 이름·별칭 정확 일치), 실패했을 때만 코드 대역을
  봅니다. 환경부 본청(`1482000`)과 기존 `1482` 대역 판정은 그대로입니다.
- 대역 밖 코드는 이름이 `환경부 …` 접두여도 기관 규칙을 받지 않습니다. 코드 대역을 선언한
  규칙은 대역 밖 코드를 이름 접두로 되돌리지 않는 R4 규칙(설계 5.2절 3항)이 그대로 적용되며,
  시험 `test_me_code_out_of_band_is_excluded_even_with_prefix_name` 이 이를 고정합니다.
- `1480xxx` 옛 대역도 환경부 소속기관이지만, 이번 Task 사양이 지목한 옛 대역은 `1481xxx`
  이고 `1480xxx` 공고는 2024-12-10 이후 없습니다. 필요하면 같은 기준(환경부 소속 여부)으로
  별도 검토합니다(5절).

---

## 4. 검증

| 항목 | 값 |
| --- | --- |
| 판정·메타 시험 | `uv run pytest tests/test_institution_rules.py tests/test_evaluation_rules_meta_api.py tests/test_evaluation_rules_scope_axis.py -q` (68 passed) |
| 전량 시험 | `uv run pytest tests/ -q -m 'not data_assets'` |
| 타입 | `uv run mypy src` |
| 규칙 검증 | `python3 scripts/validate_agent_rules.py --quiet` |
| DB 조회 | `uv run python scripts/db_readonly_query.py --sql "<질의>" --format table` (읽기 전용) |
| 변경 파일 | `src/app/api/v1/evaluations.py`, `src/app/services/evaluation_rules.py`, `tests/test_institution_rules.py`, `tests/test_evaluation_rules_meta_api.py`, `docs/analysis/institution_subunit_followup_20261013.md` |

- 신규·갱신 시험은 (사) 절의 옛 환경부 코드 대역 매칭과 대역 밖 코드 제외, 메타 API 의
  하위 조직 scope_note 문구입니다.

---

## 5. 남은 리스크와 후속

| 항목 | 내용 |
| --- | --- |
| `1480xxx` 옛 대역 | 기관표상 환경부 소속기관이지만 2024-12-10 이후 공고가 없어 이번 대역에 넣지 않았습니다. 같은 기준으로 검토할 수 있습니다. |
| 서비스 유형 판정 | 환경부 훈령 적용 유형(기본계획·설계·감리·건설사업관리·정밀안전점검(진단)·지도제작 등)은 낙찰방법명·공고명 표기 매칭에 의존합니다. 표기가 없으면 종전 조달청 경로입니다. |
| 기관 정량 배점표 | 기관 규칙은 아직 정량평가 배점표를 반영하지 않아 정량점수 직접 입력이 필요합니다(R2·R4 동일). |

---

## 6. 참고

- [institution_subunit_apply_20261013.md](institution_subunit_apply_20261013.md) — R4. 하위 조직 확장 반영
- [institution_subunit_scope_20261013.md](institution_subunit_scope_20261013.md) — S1. 하위 조직 적용 범위 조사와 매칭 설계
- [src/app/services/evaluation_rules.py](../../src/app/services/evaluation_rules.py) — 규칙 레지스트리와 판정
- [src/app/api/v1/evaluations.py](../../src/app/api/v1/evaluations.py) — 별표 규칙 메타 API 와 scope_note
