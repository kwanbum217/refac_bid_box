# 첨부 판별기 1.2.0 재판별 회귀 결과

> **작성일**: 2026-11-06
> **작업**: Orca Task `task_130296b8bb9c` (builder), Run `run_8734173629f4`, Dispatch `ctx_eb496b6ad270`
> **정본 사양**: `.orca/capsules/task_130296b8bb9c/capsule.yaml` (`ORCA_TASK_CAPSULE_V2`)
> **대상**: `bid_announcement_regime` 의 `CLASSIFIED`·`NO_ATTACHMENT` 전 행 100건
> **판정**: `candidate`. 기대 목록 14건만 바뀌었고 목록 밖 변경은 0건입니다.
> **역할 경계**: 코드·규칙·시험·이 문서만 바꿨습니다. 운영 DB 쓰기·푸시·병합은 하지 않았습니다.

---

## 1. 요약

### 1.1 결과

| 항목 | 값 |
| --- | ---: |
| 재판별 대상 | 100 |
| 라벨 변경 | 14 |
| 라벨 유지 | 86 |
| 기대 목록 밖 변경 | 0 |
| 첨부 | 294 |
| 최초 캐시 적재 외부 호출 | 294 (상한 400) |
| 최종 측정 외부 호출 | 0 (캐시 재사용) |

기대 목록은 미확정 13건 중 10건(후보 C1 9건 → `MOIS_ACADEMIC`, 후보 C2 1건 → `PPS`)과
`MOIS_OTHER` 7건 중 4건(대구 2건 → `MOIS_ACADEMIC`, 광주북구·광명 2건 → `MOIS_TECH`)입니다.
측정 결과가 이 14건과 정확히 일치했습니다.

### 1.2 라벨 분포

| regime | 변경 전 | 변경 후 | 증감 |
| --- | ---: | ---: | ---: |
| `MOIS_ACADEMIC` | 65 | 76 | +11 |
| `MOIS_TECH` | 0 | 2 | +2 |
| `MOIS_OTHER` | 7 | 3 | -4 |
| `PPS` | 2 | 3 | +1 |
| `LOCAL` | 2 | 2 | 0 |
| `NO_ATTACH` | 11 | 11 | 0 |
| `UNSPECIFIED` | 2 | 1 | -1 |
| `UNSPECIFIED_SUBTABLE` | 11 | 2 | -9 |
| 합계 | 100 | 100 | 0 |

---

## 2. 판별기·규칙 변경

### 2.1 후보 C1: R15 학술연구 확정

- 정규식은 조사 문서 3.1절과 같습니다:
  `(?<!기술[·ㆍ.,․])학술(?:[·ㆍ.]?\s*연구)?\s*용역\s*적격심사\s*(?:세부\s*)?기준`
- 확정 조건은 같은 결정 창 ±160자 안에 `행정안전부|행안부|지방자치단체 입찰시 낙찰자 결정 기준`이
  있고 `87.745|별표 2|P.Q|기술용역`이 없을 때입니다.
- R15 가중치는 0 이라 1단 갈래 점수를 흔들지 않고, `_resolve_mois_branch` 에서만 씁니다.
  확정에 쓰이지 않은 R15 매치는 `matched_rules` 에도 넣지 않습니다.

### 2.2 후보 C2: 참고 문구 하드 드롭에서 R6·R7 예외

- `_accepted_matches` 의 `_NOISE` 하드 드롭을 R6·R7 에만 적용하지 않습니다.
- R2·R3·R5·R8·R9·R10·R12 의 드롭은 그대로라 물품 장 참고 문장 오탐은 재발하지 않습니다.

### 2.3 MOIS 갈래 세분과 학술 우선

- 새 상수 `MOIS_TECH = "MOIS_TECH"` 를 추가했습니다.
- `_resolve_mois_branch` 순서:
  1. 공고문 본문의 학술연구 직접 표지(R2·R4·R14)가 `87.745` 가 처음 나오는 텍스트보다
     앞서면 `MOIS_ACADEMIC`. 대구 2건이 여기에 해당합니다.
  2. `87.745` 와 `낙찰하한율(87.745%)` 표기가 있고 기술용역 표지
     (`P.Q … 하지 않는 기술용역`, `P.Q 비대상 기술용역`, `제2장의2 … 기술용역 적격심사`)가
     있으면 `MOIS_TECH`.
  3. 그 밖의 `87.745` 는 `MOIS_OTHER`.
  4. `87.745` 가 없으면 기존 학술 세부표 확인, R15 확정, 기술용역 문구(R12), 미지정 순서입니다.
- 예규 전문을 통째로 첨부한 원주 1건은 예규 안에 학술 표지와 `87.745`, 기술용역 표지가 모두
  있지만 공고문에 `낙찰하한율(87.745%)` 표기가 없어 `MOIS_OTHER` 로 남습니다.
- 순천 2건은 `낙찰하한율(87.745%)` 은 있으나 기술용역 표지가 없어 `MOIS_OTHER` 로 남습니다.

### 2.4 행안부 [별표 2] 4. 기술용역 규칙

`src/app/services/evaluation_rules.py` 에 `MOIS_TECH_BAND_RULES` 와
`get_mois_tech_attachment_rule` 을 추가했습니다. 낙찰방법명 매칭에는 쓰지 않고
`attachment_regime == "MOIS_TECH"` 인 차단 공고에만 적용합니다.

| 필드 | 값 |
| --- | --- |
| rule_id | `SERVC_LOCAL_MOIS_TECH_20250701_1E_2E` |
| 근거 | 행안부 예규 제2장의2 [별표 2] 4. P.Q 비대상 기술용역 |
| B (배점한도) | 80 |
| k (평점계수) | 20 |
| 기준비율 | 0.88 |
| 적격통과점수 | 95 |
| 낙찰하한율 | 87.745% |
| 추정가격 띠 | 1억원 이상 2억원 미만 |
| 시행일 | 2025-07-01 (제325호). 제344호·제373호도 같은 값을 인쇄 |
| 근거 문자열 | `_SRC_MOIS_TECH_BAND` (예규 판·별표·산식·통과점수) |

학술연구 규칙(`SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E`)의 값과 적용 조건은 바꾸지 않았습니다.

---

## 3. 회귀 측정

### 3.1 방법

`scripts/regress_band_regime_classifier.py` 를 만들었습니다.

- `bid_announcement_regime` 의 `CLASSIFIED`·`NO_ATTACHMENT` 100행과 조인한 공고 `raw_data` 를
  `SET SESSION TRANSACTION READ ONLY` 트랜잭션에서 읽습니다. DB 쓰기는 없습니다.
- 첨부는 `scripts/classify_band_regime.plan_attachments` 기준으로
  `.cache/band_regress/raw/<공고번호>/` 에 내려받고 이미 있으면 재사용합니다. 요청 사이 1초,
  호출 상한 400회입니다. 최초 적재는 294회였고 이후 측정은 전부 캐시를 썼습니다.
- 텍스트 추출은 `scripts/classify_band_regime.extract_document_texts` 를 그대로 씁니다.
- 출력 표는 공고번호·DB regime·새 regime·변경 여부·`matched_rules` 이고, `--output` 으로
  행별 JSON 을 씁니다(모두 `.cache` 아래, 커밋하지 않음).

재현:

```sh
uv run python scripts/regress_band_regime_classifier.py \
  --output .cache/band_regress/result_v12.json
```

### 3.2 변경 행 14건

| 공고번호(차수) | DB regime | 새 regime | 새 matched_rules | 근거 |
| --- | --- | --- | --- | --- |
| R25BK01150429(000) | `UNSPECIFIED_SUBTABLE` | `MOIS_ACADEMIC` | R3,R5,R15 | 학술연구용역 적격심사 기준 추정가격이 |
| R25BK01217261(001) | `UNSPECIFIED_SUBTABLE` | `MOIS_ACADEMIC` | R3,R5,R15 | 학술연구용역 적격심사 세부기준(행정안전부 예규) |
| R25BK01229566(000) | `UNSPECIFIED_SUBTABLE` | `MOIS_ACADEMIC` | R3,R15 | 학술연구용역 적격심사 세부기준(행정안전부 예규) |
| R25BK01252798(000) | `UNSPECIFIED_SUBTABLE` | `MOIS_ACADEMIC` | R3,R15 | 학술연구용역 적격심사 세부기준(행정안전부 예규) |
| R26BK01271755(000) | `UNSPECIFIED_SUBTABLE` | `MOIS_ACADEMIC` | R3,R15 | 학술용역 적격심사 세부기준(행정안전부 예규) |
| R26BK01297162(000) | `UNSPECIFIED_SUBTABLE` | `MOIS_ACADEMIC` | R3,R15 | 학술용역 적격심사 세부기준(행정안전부 예규) |
| R26BK01379713(000) | `UNSPECIFIED_SUBTABLE` | `MOIS_ACADEMIC` | R3,R15 | 학술용역 적격심사 세부기준(행정안전부 예규) |
| R26BK01379750(000) | `UNSPECIFIED_SUBTABLE` | `MOIS_ACADEMIC` | R3,R15 | 학술용역 적격심사 세부기준(행정안전부 예규) |
| R26BK01736152(000) | `UNSPECIFIED_SUBTABLE` | `MOIS_ACADEMIC` | R3,R5,R15 | 학술연구용역 적격심사 세부기준을 적용 |
| R25BK01255918(000) | `UNSPECIFIED` | `PPS` | R6,R7 | 조달청 일반용역 적격심사 [별표1] 학술연구용역 |
| R25BK01199418(001) | `MOIS_OTHER` | `MOIS_ACADEMIC` | R1,R2,R3,R4,R5,R14 | [별표4] 학술연구용역 평가기준을 적용 |
| R25BK01225789(000) | `MOIS_OTHER` | `MOIS_ACADEMIC` | R1,R2,R3,R4,R5,R14 | [별표4] 학술연구용역 평가기준을 적용 |
| R26BK01506722(002) | `MOIS_OTHER` | `MOIS_TECH` | R1,R3,R12 | 사업수행능력평가(P.Q)를 하지 않는 기술용역 |
| R26BK01705722(000) | `MOIS_OTHER` | `MOIS_TECH` | R1,R5,R12 | 제2장의2 기술 용역적격심사 + 낙찰하한율(87.745%) |

후보 C1 9건, 후보 C2 1건, 대구 2건, MOIS_TECH 2건으로 기대 목록과 일치합니다.

### 3.3 기대대로 유지된 행

| 공고번호 | DB = 새 regime | 유지 이유 |
| --- | --- | --- |
| R25BK01166585(완주) | `UNSPECIFIED_SUBTABLE` | 발행기관 표기가 없어 R15 확정 조건 불충족 |
| R26BK01402983(대전) | `UNSPECIFIED_SUBTABLE` | `기술·학술연구 용역 적격심사` 부분 문자열을 부정 lookbehind 로 배제 |
| R26BK01345876(가평) | `UNSPECIFIED` | 취소 공고 1건뿐이라 적용 기준 문장 없음 |
| R25BK01139979(원주) | `MOIS_OTHER` | 공고문은 85점만 적고 예규 전문에만 87.745·기술용역 표지가 있음 |
| R26BK01560778(순천) | `MOIS_OTHER` | 일반용역 평가기준만 지목, 기술용역 표지 없음 |
| R26BK01577453(순천) | `MOIS_OTHER` | 위와 같음 |

### 3.4 변경 목록 밖 행

기대 목록 밖에서 라벨이 바뀐 행은 0건입니다. 나머지 86행은 DB 라벨과 같습니다.
변경 행이 아닌 100행 전체 표와 JSON 은 실행 산출물(`.cache/band_regress/result_v12.json`)에
있으며 커밋하지 않았습니다.

### 3.5 추출 실패

37행에서 첨부 1개 이상의 텍스트 추출이 실패했습니다(XLSX 5종·일부 PDF `PdfminerException`).
판독 가능한 첨부가 하나라도 있으면 그 텍스트로 판별했고, 전부 실패한 행은 없었습니다.
최종 100행 모두 새 regime 이 산출됐습니다.

---

## 4. 검증

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_band_regime_classifier_v12.py tests/test_band_regime_lookup.py tests/test_band_regime_resolve.py tests/test_classify_band_regime.py -q` | 49 passed |
| `uv run pytest tests/ -q -m 'not data_assets' -k 'regime or evaluation_rules or band'` | 1125 passed, 9323 deselected |
| `uv run mypy src` | Success: no issues found in 145 source files |
| `uv run pytest tests/ -q -m 'not data_assets'` | 10402 passed, 41 skipped, 3 deselected, 2 xfailed |
| `python3 scripts/validate_agent_rules.py --quiet` | 22/22 통과 |

`tests/test_band_regime_classifier_v12.py` 는 조사 문서 인용 문구로 만든 짧은 픽스처로
C1 확정·대전 부정 lookbehind·완주 발행기관 없음·C2 PPS·대구 학술 우선·광주북구 MOIS_TECH·
순천·원주 MOIS_OTHER 유지를 단언합니다. 해석기 시험은 MOIS_TECH 판별 행에만
`SERVC_LOCAL_MOIS_TECH_20250701_1E_2E` 가 적용되고, 판별 행이 없거나 다른 갈래면 종전
차단이 유지되는지 확인합니다.

---

## 5. 한계와 남은 일

| 항목 | 내용 |
| --- | --- |
| 운영 DB 재판별 | 이 작업은 측정만 했습니다. `bid_announcement_regime` 갱신은 코디네이터가 합니다 |
| 첨부 캐시 | `.cache/band_regress/` 는 커밋하지 않았습니다. 재현하려면 294회를 다시 내려받습니다 |
| 외부 호출 | 최초 적재 294회로 상한 400회 안입니다 |
| 추출 실패 | XLSX·일부 PDF 는 판별 입력에서 빠졌습니다. 해당 첨부만으로 라벨이 갈리는 공고는 확인하지 못했습니다 |
| 파일명 신호 | 보령 2건의 파일명 `[학술(2억미만 1억이상)용역]` 은 원문 근거가 아니므로 쓰지 않았습니다 |
