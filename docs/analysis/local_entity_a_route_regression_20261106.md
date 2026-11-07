# 지방공기업 라벨 A 기관의 조달청 경로 전환 회귀 (2026-11-06)

> **작성일**: 2026-11-06
> **작업**: Orca Task `task_b49ef852a1ac` (builder, `run_d3fa8d51ba74`)
> **정본 사양**: `.orca/capsules/task_b49ef852a1ac/capsule.yaml` (`ORCA_TASK_CAPSULE_V2`)
> **사용자 결정**: 결정 3 (2026-11-06 22:30). 공고문이 조달청 세부기준을 인용한 지방공기업(라벨 A) 공고를 조달청 기준 경로로 옮긴다. 해석기는 실행 시 공고문을 읽지 않으므로 기관 단위로 옮긴다.
> **근거 문서**: `docs/analysis/local_entity_69_citation_check_20261106.md` 2·3절
> **작업 브랜치**: `kwanbum217/entity-a31`

---

## 1. 요약

라벨 A 기관 14곳을 수요기관 코드 17개로 명시하고, 시·도 매핑이 있어도 시·도 규칙 후보를 만들지 않고 조달청 기본 규칙으로 해석하게 했습니다. 최근 12개월 `Servc`·낙찰방법 코드 `낙030001` 공고 31,325건을 같은 데이터로 수정 전후 비교한 결과, 판정이 바뀐 공고는 **26건**이며 전부 대상 기관의 공고입니다. 문서 2절의 대상 기관 라벨 A 25건과 E 1건을 합한 26건과 일치합니다.

| 항목 | 수정 전 | 수정 후 | 변화 |
| --- | ---: | ---: | ---: |
| 전체 공고 | 31,325 | 31,325 | 0 |
| `PPS_DEFAULT` 조달청 기본 규칙 | 19,659 | 19,685 | +26 |
| `REGION` 시·도 규칙 | 1,832 | 1,813 | -19 |
| `BLOCKED` | 9,735 | 9,728 | -7 |
| `INSTITUTION` 기관 규칙 | 99 | 99 | 0 |
| 판정 변경 공고 | - | - | **26** |

- 변경 26건 중 19건은 `REGION` 에서 `PPS_DEFAULT` 로, 7건은 `LOCAL_RULE_NOT_FOUND` 차단에서 `PPS_DEFAULT` 로 바뀌었습니다.
- 대상 기관 밖에서 판정이 바뀐 공고는 **0건**입니다.
- 대상 기관의 공고 가운데 라벨 B·C·D 인 공고가 바뀐 사례는 **0건**입니다. 변경 26건은 라벨 A 25건과 라벨 E 1건입니다.

---

## 2. 대상 기관 명시 목록

`src/app/services/demand_institutions.py` 의 `PPS_CITED_LOCAL_INSTITUTION_CODES` 입니다. 이름 패턴은 쓰지 않습니다. 한 기관이 여러 코드로 등록된 경우(부산환경공단·제주관광공사)는 코드를 모두 담았습니다.

| 기관 | 수요기관 코드 | 문서 2절 라벨 A | 문서 2절 라벨 E | 이번 변경 |
| --- | --- | ---: | ---: | ---: |
| 구리농수산물공사 | `Z003836` | 4 | 0 | 4 |
| 대전광역시 시설관리공단 | `Z004979` | 1 | 0 | 1 |
| 대전도시공사 | `B552519` | 3 | 0 | 3 |
| 부산환경공단 | `B552625`, `Z003824` | 1 | 0 | 1 |
| 서울시 강남구도시관리공단 | `Z005642` | 2 | 0 | 2 |
| 세종도시교통공사 | `B553733` | 2 | 0 | 2 |
| 아산시시설관리공단 | `Z028316` | 4 | 0 | 4 |
| 양산시시설관리공단 | `B552542` | 1 | 0 | 1 |
| 울주군시설관리공단 | `B552147` | 1 | 0 | 1 |
| 인천광역시 연수구 시설안전관리공단 | `Z033569` | 1 | 0 | 1 |
| 인천교통공사 | `Z003991` | 1 | 0 | 1 |
| 전남광주통합특별시북구시설관리공단 | `B555480` | 2 | 1 | 3 |
| 제주관광공사 | `B552701`, `Z017752`, `Z020113` | 1 | 0 | 1 |
| 제주에너지공사 | `B552915` | 1 | 0 | 1 |
| **합계** | **17개 코드 / 14개 기관** | **25** | **1** | **26** |

- `Z003824`(부산환경공단), `Z017752`·`Z020113`(제주관광공사)은 이번 측정 창에 대상 판정(`REGION`·`LOCAL_RULE_NOT_FOUND`) 공고가 없어 변경 건수에 잡히지 않았습니다. 같은 기관명의 등록 코드라 기관 단위 원칙에 따라 목록에 함께 넣었습니다.
- 라벨이 섞인 아래 3개 기관은 목록에서 제외했습니다. 이번 변경으로 이 기관들의 판정은 하나도 바뀌지 않았습니다.

| 제외 기관 | 수요기관 코드 | 문서 라벨 구성 | 이번 변경 |
| --- | --- | --- | ---: |
| 제주특별자치도개발공사 | `B551939`, `Z013671`, `Z013672`, `Z032807` | A 2, D 2 | 0 |
| 거제해양관광개발공사 | `B552833` | A 1, B 1 | 0 |
| 대구공공시설관리공단 | `B554808`, `Z004900` | A 3, B 2 | 0 |

---

## 3. 판정 변경 26건

### 3.1 전이 유형

| 수정 전 | 수정 후 | 건수 |
| --- | --- | ---: |
| `REGION` 시·도 규칙 | `PPS_DEFAULT` 조달청 기본 규칙 | 19 |
| `BLOCKED` `LOCAL_RULE_NOT_FOUND` | `PPS_DEFAULT` 조달청 기본 규칙 | 7 |
| **합계** | | **26** |

### 3.2 적용된 조달청 규칙

| 조달청 규칙 | 건수 |
| --- | ---: |
| `SERVC_QUAL_PRE_20250901_ATTACH_01` | 8 |
| `SERVC_QUAL_PRE_20250901_ATTACH_02` | 8 |
| `SERVC_QUAL_POST_20260526_ATTACH_08` | 3 |
| `SERVC_QUAL_POST_20260526_ATTACH_02` | 2 |
| `SERVC_QUAL_POST_20260526_ATTACH_01` | 1 |
| `SERVC_QUAL_PRE_20250901_ATTACH_04` | 1 |
| `SERVC_QUAL_PRE_20250901_ATTACH_05` | 1 |
| `SERVC_QUAL_PRE_20250901_ATTACH_09` | 1 |
| `SERVC_QUAL_PRE_20250901_ATTACH_10` | 1 |
| **합계** | **26** |

### 3.3 공고별 내역

| 공고번호 | 차수 | 수요기관(코드) | 수정 전 | 수정 후 |
| --- | :---: | --- | --- | --- |
| `R25BK01155715` | 000 | 서울시 강남구도시관리공단(`Z005642`) | `REGION` `SERVC_LOCAL_SEOUL_20240812_ATTACH_01` | `PPS_DEFAULT` `SERVC_QUAL_PRE_20250901_ATTACH_01` |
| `R25BK01168091` | 000 | 대전광역시 시설관리공단(`Z004979`) | `REGION` `SERVC_LOCAL_DAEJEON_20240120_ATTACH_01` | `PPS_DEFAULT` `SERVC_QUAL_PRE_20250901_ATTACH_09` |
| `R25BK01168200` | 000 | 구리농수산물공사(`Z003836`) | `REGION` `SERVC_LOCAL_GG_20250808_ATTACH_1_6` | `PPS_DEFAULT` `SERVC_QUAL_PRE_20250901_ATTACH_01` |
| `R25BK01179703` | 000 | 구리농수산물공사(`Z003836`) | `REGION` `SERVC_LOCAL_GG_20250808_ATTACH_1_6` | `PPS_DEFAULT` `SERVC_QUAL_PRE_20250901_ATTACH_01` |
| `R25BK01190604` | 000 | 울주군시설관리공단(`B552147`) | `REGION` `SERVC_LOCAL_ULSAN_20220810_ATTACH_01` | `PPS_DEFAULT` `SERVC_QUAL_PRE_20250901_ATTACH_04` |
| `R25BK01197202` | 000 | 서울시 강남구도시관리공단(`Z005642`) | `REGION` `SERVC_LOCAL_SEOUL_20240812_ATTACH_01` | `PPS_DEFAULT` `SERVC_QUAL_PRE_20250901_ATTACH_01` |
| `R25BK01208272` | 000 | 아산시시설관리공단(`Z028316`) | `REGION` `SERVC_LOCAL_CHUNGNAM_20200201_ATTACH_01` | `PPS_DEFAULT` `SERVC_QUAL_PRE_20250901_ATTACH_01` |
| `R25BK01211808` | 000 | 구리농수산물공사(`Z003836`) | `REGION` `SERVC_LOCAL_GG_20250808_ATTACH_1_6` | `PPS_DEFAULT` `SERVC_QUAL_PRE_20250901_ATTACH_01` |
| `R25BK01217544` | 000 | 구리농수산물공사(`Z003836`) | `REGION` `SERVC_LOCAL_GG_20250808_ATTACH_1_6` | `PPS_DEFAULT` `SERVC_QUAL_PRE_20250901_ATTACH_01` |
| `R25BK01234365` | 000 | 아산시시설관리공단(`Z028316`) | `REGION` `SERVC_LOCAL_CHUNGNAM_20200201_ATTACH_01` | `PPS_DEFAULT` `SERVC_QUAL_PRE_20250901_ATTACH_01` |
| `R26BK01256955` | 000 | 제주관광공사(`B552701`) | `REGION` `SERVC_LOCAL_JEJU_20240101_ATTACH_01` | `PPS_DEFAULT` `SERVC_QUAL_PRE_20250901_ATTACH_05` |
| `R26BK01272428` | 000 | 아산시시설관리공단(`Z028316`) | `BLOCKED` `LOCAL_RULE_NOT_FOUND` | `PPS_DEFAULT` `SERVC_QUAL_PRE_20250901_ATTACH_02` |
| `R26BK01284851` | 000 | 전남광주통합특별시북구시설관리공단(`B555480`) | `BLOCKED` `LOCAL_RULE_NOT_FOUND` | `PPS_DEFAULT` `SERVC_QUAL_PRE_20250901_ATTACH_02` |
| `R26BK01309854` | 000 | 아산시시설관리공단(`Z028316`) | `BLOCKED` `LOCAL_RULE_NOT_FOUND` | `PPS_DEFAULT` `SERVC_QUAL_PRE_20250901_ATTACH_02` |
| `R26BK01338617` | 001 | 전남광주통합특별시북구시설관리공단(`B555480`) | `BLOCKED` `LOCAL_RULE_NOT_FOUND` | `PPS_DEFAULT` `SERVC_QUAL_PRE_20250901_ATTACH_02` |
| `R26BK01338805` | 000 | 전남광주통합특별시북구시설관리공단(`B555480`) | `BLOCKED` `LOCAL_RULE_NOT_FOUND` | `PPS_DEFAULT` `SERVC_QUAL_PRE_20250901_ATTACH_02` |
| `R26BK01373914` | 001 | 인천광역시 연수구 시설안전관리공단(`Z033569`) | `REGION` `SERVC_LOCAL_INCHEON_20251224_ATTACH_01` | `PPS_DEFAULT` `SERVC_QUAL_PRE_20250901_ATTACH_02` |
| `R26BK01373956` | 000 | 제주에너지공사(`B552915`) | `REGION` `SERVC_LOCAL_JEJU_20240101_ATTACH_01` | `PPS_DEFAULT` `SERVC_QUAL_PRE_20250901_ATTACH_10` |
| `R26BK01412321` | 000 | 부산환경공단(`B552625`) | `REGION` `SERVC_LOCAL_BUSAN_20250626_ATTACH_01` | `PPS_DEFAULT` `SERVC_QUAL_PRE_20250901_ATTACH_02` |
| `R26BK01448541` | 000 | 인천교통공사(`Z003991`) | `REGION` `SERVC_LOCAL_INCHEON_20251224_ATTACH_01` | `PPS_DEFAULT` `SERVC_QUAL_PRE_20250901_ATTACH_02` |
| `R26BK01569361` | 001 | 양산시시설관리공단(`B552542`) | `REGION` `SERVC_LOCAL_GN_20230105_ATTACH_01` | `PPS_DEFAULT` `SERVC_QUAL_POST_20260526_ATTACH_01` |
| `R26BK01634128` | 000 | 대전도시공사(`B552519`) | `REGION` `SERVC_LOCAL_DAEJEON_20260101_ATTACH_01` | `PPS_DEFAULT` `SERVC_QUAL_POST_20260526_ATTACH_08` |
| `R26BK01644874` | 001 | 대전도시공사(`B552519`) | `REGION` `SERVC_LOCAL_DAEJEON_20260101_ATTACH_01` | `PPS_DEFAULT` `SERVC_QUAL_POST_20260526_ATTACH_08` |
| `R26BK01653443` | 000 | 대전도시공사(`B552519`) | `REGION` `SERVC_LOCAL_DAEJEON_20260101_ATTACH_01` | `PPS_DEFAULT` `SERVC_QUAL_POST_20260526_ATTACH_08` |
| `R26BK01669860` | 000 | 세종도시교통공사(`B553733`) | `BLOCKED` `LOCAL_RULE_NOT_FOUND` | `PPS_DEFAULT` `SERVC_QUAL_POST_20260526_ATTACH_02` |
| `R26BK01683011` | 000 | 세종도시교통공사(`B553733`) | `BLOCKED` `LOCAL_RULE_NOT_FOUND` | `PPS_DEFAULT` `SERVC_QUAL_POST_20260526_ATTACH_02` |

- 라벨 E 1건은 `R26BK01338617`(전남광주통합특별시북구시설관리공단, 첨부 없음)입니다. 기관 단위 전환이라 첨부 유무와 무관하게 함께 옮겨졌습니다.
- 나머지 25건은 문서 2절 라벨 A 공고입니다.

---

## 4. 측정 방법

| 단계 | 방법 |
| --- | --- |
| 모집단 | `scripts/report_rule_coverage.py` 의 `collect_records(months=12, category="Servc", method_code="낙030001")` 를 메모리에서 실행 |
| 측정 시각 | 2026-11-07. 창은 2025-11-07 ~ 2026-11-07 |
| 비교 단위 | 공고번호·업무구분·최신 차수. 31,325건 전부를 키로 맞춰 비교 |
| 판정 정본 | `resolve_evaluation_rule_from_raw_data` (수정 전·후 같은 입력) |
| DB | 읽기 전용 연결(`SET SESSION TRANSACTION READ ONLY`)만 사용. 쓰기 없음 |
| 산출물 | 스크래치패드 JSON 두 벌(`before.json`, `after.json`). 저장소에 커밋하지 않음 |

- 문서 2절의 측정 창은 2025-11-06 ~ 2026-11-06 으로 31,348건이고, 이번 측정은 하루 뒤 창이라 31,325건입니다. 창이 하루 밀린 차이이며, 대상 기관의 A·E 26건은 그대로 재현됐습니다.
- `REGION`·`BLOCKED` 판정만 대상으로 비교했고, `MANUAL_EVALUATION` 등 대상 기관의 비적격심사 공고는 수정 전후 모두 그대로입니다.

---

## 5. 구현

| 파일 | 변경 |
| --- | --- |
| `src/app/services/demand_institutions.py` | `PPS_CITED_LOCAL_INSTITUTION_CODES`(17개 코드)와 `is_pps_cited_local_institution` 추가 |
| `src/app/services/evaluation_rules.py` | `PPS_CITED_LOCAL_INSTITUTION_WARNING`, `_is_pps_cited_local_institution` 추가. `LOCAL` 판정에서 목록 기관이면 시·도 규칙 후보를 만들지 않고 조달청 매칭 결과를 좁혀 확정 |
| `tests/test_local_entity_a_route.py` | 목록 기관 17개 코드의 조달청 기본 규칙 전환, 목록 밖 지방공기업의 시·도 규칙 유지, 제주특별자치도개발공사·거제해양관광개발공사 판정 유지, 혼재 기관 코드 미포함, 이름 패턴 미사용 시험 |

- 기관 규칙(`INSTITUTION`)이 있는 공고는 종전 우선순위(기관 > 시·도 > 조달청)대로 기관 규칙이 먼저입니다. 대상 14개 기관에는 기관 규칙이 없습니다.
- 목록 기관의 조달청 매칭이 실패하면 `LOCAL_RULE_NOT_FOUND` 대신 `RULE_NOT_FOUND` 로 남습니다. 환경부고시·행안부 예규 등 기존 후속 분기는 종전과 같은 순서로 동작합니다.
- 조달청 기준으로 풀린 공고에는 `PPS_CITED_LOCAL_INSTITUTION_WARNING` 을 붙입니다.

---

## 6. 검증

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_local_entity_a_route.py tests/test_local_entity_pps_route.py -q` | 42 passed |
| `uv run pytest tests/ -q -m 'not data_assets' -k 'evaluation_rules or demand_institution or local'` | 1010 passed, 9553 deselected |
| `uv run mypy src` | Success: no issues found in 145 source files |
| `uv run pytest tests/ -q -m 'not data_assets'` | 10517 passed, 41 skipped, 3 deselected, 2 xfailed |
| `python3 scripts/validate_agent_rules.py --quiet` | 22/22 통과 |

- `data_assets` 3건은 격리 워크트리에 `data/model_files`·`chroma_db` 가 없어 제외했습니다. 정본 사양이 정상으로 규정한 조건입니다.
- 기존 시험 단언은 삭제·변경하지 않았습니다.

---

## 7. 한계

1. 이번 회귀는 최근 12개월 `Servc`·`낙030001` 창만 봅니다. 창 밖 과거 공고는 같은 기관 코드 목록으로 판정이 바뀌지만, 별도 전수 비교는 하지 않았습니다.
2. 기관 코드 목록은 2026-11-06 기준 수요기관 기준정보에서 확인한 코드입니다. 기관이 새 코드로 등록되면 목록에 추가해야 합니다. 이름 패턴으로 자동 확장하지 않습니다.
3. 라벨 판정은 선행 조사 문서를 따릅니다. 이번 작업에서 첨부를 다시 내려받아 인용을 재판독하지 않았습니다.
