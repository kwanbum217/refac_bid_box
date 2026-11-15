# 광주광역시 별표 1-2 소프트웨어용역 적격심사 규칙 등록 (2026-11-15)

> **작성일**: 2026-11-15
> **작업**: Orca Task `task_2c3be8d0f85a` (builder, `run_87d6d4d819d1`). 광주광역시 구판 별표 1-2 를 지역 규칙으로 등록하고 시험과 판정 비교를 마쳤습니다.
> **정본 사양**: `.orca/capsules/task_gwangju_sw_rule_20261115/capsule.yaml` (`ORCA_TASK_CAPSULE_V2`)
> **원문 사본**: `.orca/capsules/task_gwangju_sw_rule_20261115/source/` 의 `elis_hist007.html`, `att_001.bin`, `att_001_flat.txt`, `rows.txt`
> **판정 기준 덤프**: `.orca/capsules/task_gwangju_sw_rule_20261115/judge_main_25bbc03e.tsv` (main `25bbc03e`, 27,638행)

---

## 1. 요약

광주광역시 일반용역 적격심사 세부기준(예규 제377호, 시행 2022-11-15, 2026-07-16 폐지) 제6조 2호가 지정하는 별표 1-2 소프트웨어용역 별표를 지역 규칙으로 등록했습니다. 입찰가격 배점한도는 별표 1-2 가, 평점산식과 낙찰하한율은 그 별표가 인용하는 별표 6 소프트웨어 행이 정합니다.

| 항목 | 값 |
| --- | --- |
| 규칙 식별자 (자치구) | `SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_2` |
| 규칙 식별자 (본청·소속기관) | `SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_2_METRO_SW` |
| 지역 | `29` 광주광역시 |
| 세부유형 | `SW` 단일 |
| 시행 / 폐지 | 2022-11-15 / 2026-07-16 |
| 통과점수 | 95 단일 |

전체 판정 비교에서 바뀐 공고는 광주 소프트웨어 2건뿐이고, 두 건 모두 `BLOCKED`(`LOCAL_RULE_NOT_FOUND`)에서 `REGION` 이 되었습니다. 다른 공고의 `scope`, `rule_id`, `block_code`, `region` 은 바뀌지 않았습니다.

---

## 2. 원문 근거

### 2.1 적용 판본과 별표 지정

| 근거 | 내용 | 위치 |
| --- | --- | --- |
| 본문 표제 | `광주광역시 일반용역 적격심사 세부 기준`, `[시행 2022.11.15]`, `예규 제 377호` | `elis_hist007.html:1217` |
| 제6조 2호 | `소프트웨어용역 평가기준 : 별표 1-2` | `elis_hist007.html:1217` |
| 제11조 ① | `종합평점이 95점이상인 최저가 입찰자를 낙찰자로 결정` | `elis_hist007.html:1217` |
| 폐지 부칙 | `(폐지) 2026-07-01 예규 제 3호 전남광주통합특별시 일반용역 적격심사 세부지침`, `2026년 7월 16일부터 시행` | `elis_hist008.html:1217` |
| 별표 1-2 표제 | `[별표 1-2] 소프트웨어용역 적격심사 항목 및 배점한도` | `att_001_flat.txt` 1,613자 부근 |
| 별표 6 표제 | `[별표 6] 입찰가격 평가방법` | `att_001_flat.txt` 19,989자 부근 |

### 2.2 입찰가격 배점한도 (별표 1-2)

| 구간 | 배점한도 | 근거 |
| --- | ---: | --- |
| 추정가격 5억원 이상 | 50 | `rows.txt:34` |
| 5억원 미만 2억원 이상 | 70 | `rows.txt:34` |
| 2억원 미만 | 90 | `rows.txt:34` |
| 합계 | 100 | `rows.txt:36` |
| 인용 조항 | `입찰가격은 [별표6]에 따라 평가한다.` | `rows.txt:37` |

### 2.3 평점산식·낙찰하한율 (별표 6 소프트웨어 행)

| 구간 | 평점산식 | 투찰율 상한 평점 | 낙찰하한율 | 근거 |
| --- | --- | --- | ---: | --- |
| 5억원 이상 | `50 - 2 x (88 - 입찰가격/예정가격 x 100)` | 90.5% 이상 45점 | 85.495 | `rows.txt:170`, `rows.txt:290` |
| 5억원 미만 2억원 이상 | `70 - 4 x (88 - 입찰가격/예정가격 x 100)` | 89.25% 이상 65점 | 86.745 | `rows.txt:171`, `rows.txt:290` |
| 2억원 미만 | `90 - 20 x (88 - 입찰가격/예정가격 x 100)` | 88.25% 이상 85점 | 87.745 | `rows.txt:172`, `rows.txt:290` |

`rows.txt` 는 HWP 표 셀 추출본이라 `氠瑢`, `汤捯` 같은 접두 잡음과 분수 레이아웃이 섞여 있습니다. 같은 표를 `att_001_flat.txt` 로 대조한 결과는 다음과 같습니다.

- `85.495` 는 20,756자 부근, `89.25%` 는 20,897자 부근, `87.745` 는 21,083자 부근에 있습니다.
- `86.745` 와 소프트웨어 행의 `90.5%` 상한 문구는 평문 추출본에서 빠졌습니다. 두 값은 `rows.txt:171` 의 정규화 행과 `rows.txt:290` 의 원본 셀 블록에 모두 남아 있어, 정규화 행과 원본 블록을 서로 대조해 확인했습니다.
- 산식의 `100` 이 분모(예정가격)와 백분율 환산에 각각 쓰이는 것은 기존 광주 별표 1-3·1-5 등록과 같은 표기 방식입니다.

### 2.4 중소기업자간 경쟁제품 구분

원문 별표 1-2 에는 중소기업자간 경쟁제품 대상·비대상에 따라 값을 나누는 문구가 없습니다. 같은 예규의 별표 1-3·1-5 처럼 `SW` 단일 유형으로 등록했고, `SW_SME` 규칙은 만들지 않았습니다. 두 대상 공고의 낙찰방법명에 `중소기업자간 경쟁제품 비대상` 표기가 있어도, 광주 지역에 `SW_SME` 후보가 없으므로 자동 확정 차단 경로(`LOCAL_SERVICE_TYPE_UNRESOLVED`)는 발생하지 않습니다.

---

## 3. 등록한 규칙 값

파일: `src/app/services/evaluation_rules_local.py`

| 필드 | 값 |
| --- | --- |
| `rule_id` | `SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_2` (자치구), `SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_2_METRO_SW` (본청·소속기관) |
| `service_type` | `SW` |
| `sido_code` / `sido_name` | `29` / `광주광역시` |
| `effective_date` / `superseded_date` | `2022-11-15` / `2026-07-16` |
| `lwlt_rate` (대표값) | `85.495` |
| `base_rate` | `0.88` |
| `threshold_bands` | `95` 단일 (`소프트웨어용역 추정가격 무관 95`) |

| 구간 (`upper_bound` 미만) | `max_price_score` (B) | `multiplier` (k) | `lwlt_rate` |
| --- | ---: | ---: | ---: |
| 2억원 미만 (`200000000`) | 90 | 20 | 87.745 |
| 5억원 미만 2억원 이상 (`500000000`) | 70 | 4 | 86.745 |
| 5억원 이상 (상한 없음) | 50 | 2 | 85.495 |

두 규칙의 값은 같습니다. 별표 1-2 는 별표 1-3·1-5 처럼 `지역제한 금액` 경계를 쓰지 않고 추정가격 5억·2억 경계만 쓰므로, 본청·소속기관과 자치구의 값이 갈리지 않습니다. 다만 `src/app/services/evaluation_rules.py:2432-2446` 이 광주광역시(광역) 본청·소속기관 공고에서 `_METRO_` 가 없는 구판 규칙을 후보에서 빼므로, 같은 값을 `_METRO_SW` 로 한 번 더 등록해 두 대상 공고를 모두 계산할 수 있게 했습니다.

---

## 4. 판정 비교

실행 명령은 다음과 같습니다. 결과는 27,638행으로 기준 덤프와 행 수가 같습니다.

```text
uv run python .orca/capsules/task_gwangju_sw_rule_20261115/dump_all.py <출력.tsv>
```

비교한 열은 `scope`, `rule_id`, `block_code`, `region` 입니다.

| 공고번호 | 차수 | 수요기관 | 공고명 | 변경 전 | 변경 후 |
| --- | --- | --- | --- | --- | --- |
| `R25BK01171487` | `000` | 전남광주통합특별시 서구 | 2026년도 행정전산장비 및 네트워크장비 유지보수 용역 | `BLOCKED` / `LOCAL_RULE_NOT_FOUND` | `REGION` / `SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_2` |
| `R26BK01454418` | `000` | 전남광주통합특별시 광주청사 | (긴급)청사 간(광주↔전남) 전용 정보통신서비스 회선사업자 선정 용역 | `BLOCKED` / `LOCAL_RULE_NOT_FOUND` | `REGION` / `SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_2_METRO_SW` |

바뀐 행은 이 2건뿐입니다. 나머지 27,636행은 네 열이 모두 기준 덤프와 같습니다.

---

## 5. 시험

파일: `tests/test_gwangju_sw_rule_20261115.py`. DB·Redis 에 연결하지 않습니다.

| 시험 | 확인 내용 |
| --- | --- |
| `test_target_announcements_select_gwangju_software_rule` | 대상 2건의 대표 `raw_data` 로 새 규칙이 선택되고 `scope_stage` 가 `REGION` 인지 |
| `test_annex_bands_match_original_values` | 두 규칙 모두 2억·5억 구간의 B 90·70·50, k 20·4·2, 기준비율 0.88, 하한율 87.745·86.745·85.495 인지 |
| `test_band_boundaries_belong_to_higher_band` | 정확히 2억원은 `5억원 미만 2억원 이상`, 정확히 5억원은 `5억원 이상` 구간인지 |
| `test_effective_lwlt_rate_follows_price_band` | 추정가격 151,083,655원은 87.745, 324,000,000원은 86.745 를 쓰는지 |
| `test_pass_threshold_is_single_95` | 통과점수가 구간 없이 95 단일인지 |
| `test_announcement_after_abolition_uses_merged_rule` | 공고일 2026-07-16 이후에는 통합특별시 별표 2(`SERVC_LOCAL_JNGJ_20260716_ATTACH_02`)가 선택되는지 |
| `test_announcement_before_effective_date_is_blocked` | 시행일 이전 공고는 `RULE_REGIME_MISMATCH` 로 막히는지 |
| `test_other_region_does_not_select_gwangju_rule` | 전라남도 공고에 광주 규칙이 선택되지 않는지 |

### 5.1 규칙 수·지문을 고정한 시험 갱신

새 규칙 2개를 등록하면 규칙 수·식별자·지문을 고정한 시험 5개가 실패합니다. 코디네이터의 범위 승인(2026-11-15)을 받아, 이번 등록으로 직접 생긴 고정값만 갱신하고 다른 단언은 바꾸지 않았습니다.

| 파일 | 시험 | 변경 | 이유 |
| --- | --- | --- | --- |
| `tests/test_jeonnam_facility_predecessor.py` | `test_gwangju_chungsa_software_stays_blocked` → `test_gwangju_software_uses_gwangju_annex_1_2` | `BLOCKED` 단언을 `NOT BLOCKED`, `rule_id == SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_2`, `scope_stage == REGION` 으로 전환 | 새 규칙 등록으로 광주 소프트웨어 공고가 계산 가능해진 것이 이번 작업의 의도된 결과입니다. 같은 시험의 광산구 표본은 자치구라 `_METRO_` 없는 규칙이 선택됩니다. |
| `tests/test_jngj_predecessor.py` | `test_predecessor_rules_declare_supersede_window` | `superseded` 기대 집합에 신규 2개 ID 추가 | 두 규칙 모두 `superseded_date=2026-07-16` 을 선언합니다. |
| `tests/test_local_regime_rules_wave2.py` | `test_existing_36_local_rules_unchanged` | `PREDECESSOR_RULE_IDS` 에 신규 2개 ID 추가 | 구판 규칙을 기존·신규 순서 단정에서 빼는 목록이라, 추가하지 않으면 규칙 수가 2 늘어납니다. |
| `tests/test_seoul_10eok_lwlt.py` | `test_other_local_rules_unchanged` | `LOCAL_RULES_EXCLUDING_SEOUL_DIGEST` 를 `144100846257408718c55e2ad781010e27864219dac05cd79e424e1adc0f35ed` 로 갱신 | 규칙 2개가 늘어 다이제스트가 바뀌었습니다. |
| `tests/test_evaluation_rules_split_invariance.py` | `test_rule_constant_fingerprints_are_unchanged` | `EXPECTED_FINGERPRINTS["LOCAL_RULES"]` 를 `71684c07cd529398` 로 갱신 | 같은 이유로 `LOCAL_RULES` 지문값이 바뀌었습니다. |

`list_all_rules()` 기본 인자는 조달청 `POST_20260526_RULES` 라 지역 규칙 추가와 무관하며, 해당 지문 시험은 바꾸지 않았습니다.

---

## 6. 남은 확인

- 폐지일 2026-07-16 이후 광주 소프트웨어 공고는 기존 통합특별시 별표 2 규칙이 계속 쓰입니다. 새 규칙은 `superseded_date` 로 그 이후 후보에서 빠지며, 시험으로 확인했습니다.
- 격리 워크트리에는 `data/model_files` 와 `chroma_db` 가 없어 `tests/test_data_preservation.py` 2건(`test_model_bin_files_exist`, `test_chroma_db_exists`)이 실패하는 것이 정상입니다. 이번 변경과 무관합니다.
