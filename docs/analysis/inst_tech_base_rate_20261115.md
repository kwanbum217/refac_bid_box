# 수요기관 자체 기술용역 적격심사 세부기준 판본별 기준비율 적용

> **작성일**: 2026-11-15
> **작업**: Orca Task `task_026bfdcb93d2` (builder)
> **정본 사양**: `.orca/capsules/task_inst_tech_base_rate_20261115/capsule.yaml` (`ORCA_TASK_CAPSULE_V2`)
> **작업 브랜치**: `kwanbum217/itbase`
> **선행 보고서**: `docs/analysis/inst_tech_criteria_source_20261115.md`
> **판정**: candidate

---

## 1. 요약

기술용역 규칙 `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT`(조달청 현행판, 기준비율 0.90)로 계산되는 공고 가운데 낙찰방법 적용 기준(`raw_data.sucsfbidMthdAppStd`)이 한국지역난방공사 또는 인천국제공항공사의 자체 기술용역 적격심사 세부기준을 명시한 공고는, 규칙 선택을 바꾸지 않고 공고일이 속한 기관 원문 판본의 기준비율을 `resolution.base_rate` 에 채웁니다.

| 기관 | 공고일 구간 | 원문 기준비율 | 채우는 값 | 바뀐 건수 |
| --- | --- | ---: | ---: | ---: |
| 한국지역난방공사 | 2026-01-01 이상 2026-08-18 미만 | 88/100 | 0.88 | 37 |
| 한국지역난방공사 | 2026-08-18 이상 | 90/100 | 채우지 않음(규칙 값 0.90) | 0 |
| 인천국제공항공사 | 2023-07-24 이상 | 88/100 | 0.88 | 17 |
| 그 밖의 공고 | - | - | 종전과 같음 | 0 |

- 한국지역난방공사 37건과 인천국제공항공사 17건, 합계 54건이 모두 0.90 에서 0.88 로 바뀌었습니다.
- 판정(규칙 선택)이 바뀐 공고는 0건입니다.
- 한국지역난방공사의 2026-01-01 판본은 공고일 2026-05-26 미만 구간에서 이미 구판 규칙(`SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526`, 기준비율 0.88)이 선택되므로, 실제로 값이 달라지는 구간은 2026-05-26 이상 2026-08-17 이하입니다.
- 인천국제공항공사의 2023-07-24 이상 2026-05-25 이하 공고도 구판 규칙이 기준비율 0.88 을 이미 갖고 있어 값은 그대로입니다. 새 분기는 공고일 조건을 원문 부칙 그대로 두고, 규칙이 현행판일 때만 값을 채웁니다.

---

## 2. 구현

### 2.1 변경 위치

| 구분 | 위치 | 내용 |
| --- | --- | --- |
| 상수 | `src/app/services/evaluation_rules.py:1235-1249` | 기관 판정 문자열 2종, 판본 시행일 3종, 경고 문구 |
| 분기 | `src/app/services/evaluation_rules.py:3893-3916` | 현행 기술용역 규칙 결과의 `base_rate` 를 판본별로 채움 |

### 2.2 분기 조건

```text
선택된 규칙 rule_id == SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT
AND app_std == sucsfbidMthdAppStd 에서 공백 제거
AND (
      (app_std == "한국지역난방공사기술용역적격심사세부기준"
       AND 2026-01-01 <= 공고일 < 2026-08-18)
   OR (app_std == "인천국제공항공사기술용역적격심사세부기준"
       AND 2023-07-24 <= 공고일)
)
```

- 공고일은 같은 함수에서 이미 쓰는 `_parse_announcement_date(bid_ntce_dt)` 값을 재사용합니다. 공고일이 없거나 읽을 수 없으면 값을 채우지 않습니다.
- 한국지역난방공사 공고일이 2026-08-18 이상이면 현행 규칙 값 0.90 이 원문 90/100 과 같으므로 아무것도 채우지 않습니다.
- 구판 규칙 `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526` 은 이미 기준비율 0.88 이므로 분기 대상이 아닙니다.
- 규칙 객체는 바꾸지 않고 `dataclasses.replace` 로 결과의 `base_rate` 와 경고만 덧붙입니다. 규칙 선택·차단·범위 축은 종전과 같습니다.
- 경고 문구는 `공고가 수요기관 자체 기술용역 적격심사 세부기준을 명시해 해당 판본의 기준비율 88/100을 적용했습니다.` 입니다.
- 같은 자리의 행안부 예규 분기(`MOIS_BIDDER_DECISION_STANDARD_MARKER`)와는 `elif` 로 갈라, 두 표지가 동시에 나타나도 경고가 중복되지 않습니다.

---

## 3. 원문 근거

파일 경로는 워크트리 루트 기준 상대 경로이며, 줄 번호는 판독본(`*.lines.txt`) 기준입니다. `data/sources/` 아래 원문 사본은 저장소에 커밋되지 않습니다.

| 기관·판본 | 파일 | 줄 | 인용 | 값 |
| --- | --- | ---: | --- | ---: |
| 한국지역난방공사 2026-01-01 | `data/sources/qualification/files/kdhc/5511b7e2c6e6_기술용역적격심사세부기준(개정전문)(2026.01.01).lines.txt` | 49 | `1. 이 세부기준은 2026년 1월 1일 이후 입찰공고분부터 시행한다.` | 시행일 |
| 같음 | 같음 | 75 | `[EQ]F30- LEFT \| ( {88} over {100} - {입찰가격} over {예정가격} ) TIMES 100 RIGHT` | 88/100 |
| 같음 | 같음 | 107, 139, 192 | `{88} over {100}` (10억원 미만 5억원 이상, 5억원 미만 고시금액 이상, 고시금액 미만 구간) | 88/100 |
| 한국지역난방공사 2026-08-18 | `data/sources/qualification/files/kdhc/715f62aee8ef_기술용역적격심사세부기준(2026.08.18. 시행).lines.txt` | 52 | `1. 이 세부기준은 2026년 8월 18일 이후 입찰공고분부터 시행한다.` | 시행일 |
| 같음 | 같음 | 78, 110, 142, 195 | `{90} over {100}` | 90/100 |
| 인천국제공항공사 재무처-8933호 | `data/sources/qualification/files/iiac/9ae88bc02e11_기술용역적격심사세부기준(재무처-8933).lines.txt` | 7, 38-39 | `【재무처-8933호, 2023.7.20.】`, `부 칙 <2023.7.20.>`, `1. 이 세부기준은 2023년 7월 24일 이후 입찰공고하는 용역부터 적용한다.` | 시행일 |
| 같음 | 같음 | 64 | `88 입찰가격` | 88/100 |
| 같음 | 같음 | 97, 130, 162 | `88 입찰가격` (10억원 미만 5억원 이상, 5억원 미만 고시금액 이상, 고시금액 미만 구간) | 88/100 |

한국지역난방공사 두 판본과 인천국제공항공사 판본의 구간 경계·배점한도·계수·통과점수는 같고 기준비율만 다릅니다. 상세 대조는 선행 보고서 `docs/analysis/inst_tech_criteria_source_20261115.md` 3.2~3.4절에 있습니다.

---

## 4. 검증

### 4.1 판정(규칙 선택) 불변

```sh
uv run python scripts/judge_snapshot_diff.py dump --as-of 2026-11-15 --output .orca/tmp/judge_before.tsv
uv run python scripts/judge_snapshot_diff.py dump --as-of 2026-11-15 --output .orca/tmp/judge_after.tsv
uv run python scripts/judge_snapshot_diff.py diff .orca/tmp/judge_before.tsv .orca/tmp/judge_after.tsv
```

```text
공고 before 27638건, after 27638건
바뀐 공고 0건(판정 변경 0건, before 만 0건, after 만 0건)
```

`scope`, `rule_id`, `block_code`, 수요기관 코드·이름을 공고 키별로 비교했고 바뀐 행이 없습니다. 규칙 선택은 그대로입니다.

### 4.2 기준비율 변화

`scripts/report_rule_coverage.py` 의 `collect_records` 와 같은 조회·판정 경로를 쓰는 임시 스크립트로 공고별 실효 기준비율(`resolution.base_rate` 가 있으면 그 값, 없으면 `rule.base_rate`)을 수정 전후로 덤프했습니다. 덤프와 임시 스크립트는 `.orca/tmp/` 에만 두고 커밋하지 않았습니다.

```text
바뀐 공고 54건
수정 전 기준비율: 0.90 54건
수정 후 기준비율: 0.88 54건
바뀐 54건의 rule_id: SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT 54건
expect54.txt 와 공고번호·차수 집합: 일치(54건)
```

| 기관 | 바뀐 건수 | 수정 전 | 수정 후 |
| --- | ---: | ---: | ---: |
| 한국지역난방공사 | 37 | 0.90 | 0.88 |
| 인천국제공항공사 | 17 | 0.90 | 0.88 |
| 합계 | 54 | 0.90 | 0.88 |

나머지 27584건은 실효 기준비율과 규칙 ID 가 모두 종전과 같습니다. 기대 목록 밖에서 바뀐 공고는 없습니다.

### 4.3 시험

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_inst_tech_base_rate_20261115.py -q` | 14 passed |
| `uv run pytest tests/test_inst_tech_base_rate_20261115.py tests/test_base_rate_fix_20261115.py -q` | 20 passed |
| `uv run pytest tests/ -q -m 'not data_assets'` | 전량 통과(아래 5절) |
| `uv run mypy src` | 통과 |
| `python3 scripts/validate_agent_rules.py --quiet` | 통과 |

신규 시험 `tests/test_inst_tech_base_rate_20261115.py` 는 다음을 고정합니다.

- (a) 지역난방공사 기준 명시, 공고일 2026-06-01: 규칙 `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT`, `base_rate=0.88`, 기관 경고 포함
- (b) 지역난방공사 기준 명시, 공고일 2026-09-01: `base_rate` 없음, 규칙 값 0.90 유지
- (c) 인천공항공사 기준 명시, 공고일 2026-07-01: `base_rate=0.88`, 기관 경고 포함
- (d) 조달청 기술용역 기준 명시: `base_rate` 없음, 규칙 값 0.90 유지
- (e) 행안부 기준 명시: 기존 `base_rate=0.88` 과 행안부 경고 유지, 기관 경고 없음
- 판본 경계: 지역난방공사 2026-05-26·2026-08-17 은 0.88, 2026-08-18 은 없음. 인천공항공사 2023-07-23·2023-07-24·2024-06-01 은 구판 규칙(0.88)이라 채우지 않음
- 공백 제거 비교, 공고일 없음, 지역난방공사 2026-05-25(구판 규칙) 무변경

### 4.4 기존 시험 1건 수정 (코디네이터 승인)

`tests/test_base_rate_fix_20261115.py` 의 부정 대조군 `INSTITUTION_APP_STD` 가 정확히 이번 분기가 값을 채우는 `한국지역난방공사 기술용역 적격심사 세부기준` 이어서, `base_rate is None` 을 기대하던 `test_non_mois_stated_tech_announcement_keeps_rule_base_rate[한국지역난방공사 ...]` 가 실패했습니다. 이 파일은 당초 `allowed_write_files` 밖이어서 코디네이터에 승인을 요청했고, 승인 후 다음과 같이 고쳤습니다.

- `INSTITUTION_APP_STD` 를 `한국도로공사 기술용역 적격심사 세부기준` 으로 바꿨습니다. 이번 분기가 다루지 않는 기관 문자열입니다.
- `parametrize` 인자 두 개(조달청, 기관 자체 기준)는 그대로 두었습니다. 다른 단언은 바꾸지 않았습니다.
- 두 인자 모두 `base_rate is None` 과 규칙 값 0.90 유지를 확인하며 통과합니다. 지역난방공사·인천공항공사 케이스는 신규 시험 파일이 담당합니다.

---

## 5. 전량 시험과 정적 검사

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/ -q -m 'not data_assets'` | 11037 passed, 41 skipped, 3 deselected, 2 xfailed (311.10s) |
| `uv run mypy src` | Success: no issues found in 152 source files |
| `python3 scripts/validate_agent_rules.py --quiet` | 검증 통과: 22/22 건 |

`data_assets` 표식 3건은 격리 워크트리에 `data/model_files`·`chroma_db` 가 없어 제외했습니다. 제외 표식이 붙지 않은 다른 시험은 모두 통과했습니다.

---

## 6. 남은 일

- 판정 결과는 candidate 입니다. 리뷰어가 4.1·4.2 절의 비교 방식과 3절 인용을 원문과 대조해야 합니다.
- DB·Redis 쓰기, 스키마 변경, 규칙 선택 변경은 없습니다.
