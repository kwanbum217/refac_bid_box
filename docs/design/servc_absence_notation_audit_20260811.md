# 학습 사용 13개 필드의 부재 표기 접힘 전수 점검

> **작성일**: 2026-08-11
> **상태**: 읽기 전용 진단. 일부 미완(아래 명시)
> **결론**: 13개 필드 모두 현재 코드에서 train/serve 불일치(즉시조치)는 검출되지 않았습니다. 다만 결측 지시자가 있는 필드는 `lwlt_rate` 하나뿐이라, 나머지 숫자형 4개는 "결측"과 "진짜 0"이 구분되지 않는 정보 손실이 있습니다(표기 변경에 대한 스큐는 아님).
> **선행**: [`servc_lwlt_missing_remechanism_20260811.md`](servc_lwlt_missing_remechanism_20260811.md) 4.4 — `lwlt_rate` 는 접힘이 확인된 유일한 사례였습니다.
> **주의**: 이 문서 작성 중 선행 문서 4.1(비예가 라벨 관련 서술)과 제 실측이 모순되는 것을 발견해 별도 escalation 으로 보고했습니다. 4.1 의 결측 분해 수치가 정정되면 이 문서의 결론 자체(안전 등급)는 영향받지 않지만, `prearng_mthd` 값 구성에 대한 배경 서술은 재확인이 필요합니다.

---

## 1. 방법

`scripts/survey_servc_fields.py` 의 `IN_USE` 13개 필드(= `src/ml/dataset.py` 의 `INSTITUTION_FIELDS`)를 대상으로 합니다.

1. `src/ml/features.py`, `src/ml/dataset.py` 를 읽고 각 필드가 어떤 함수를 거치는지 코드로 확인
2. `bid_announcements.raw_data` (category='Servc', `bid_ntce_dt >= 2025-01-01`, 표본 20,000행)에서 실제 값 분포를 뽑아 부재 표기 후보(빈 문자열, `'0'`, `'N'`, 자유텍스트 placeholder)가 있는지 확인
3. 부재 표기가 학습 경로(`dataset.py`)와 서빙 경로(`features.py` `announcement_feature_payload`/`build_default_feature_map`)에서 같은 규칙으로 접히는지 코드 대조

표본은 20,000행(2025-01 이후)입니다. 전수가 아니며, 특히 희귀 placeholder 문자열은 표본에 없을 수 있습니다.

---

## 2. 등급 정의

| 등급 | 뜻 |
| --- | --- |
| **접힘(안전)** | 부재를 뜻하는 값이 학습·서빙 양쪽에서 같은 규칙으로 결측/기본값으로 접힙니다 |
| **범주로 남음(취약)** | 부재로 보이는 값이 접히지 않고 하나의 문자 그대로 범주가 됩니다. 원천이 그 표기를 바꾸면 모델이 조용히 다른 신호를 학습합니다 |
| **train-serve 불일치(즉시조치)** | 같은 원시값을 학습 경로와 서빙 경로가 다르게 처리합니다. 비협상 원칙 위반입니다 |

---

## 3. 코드 경로 요약

| 경로 | 처리 |
| --- | --- |
| `dataset.py:_institution_columns` (학습, SQL) | `JSON_UNQUOTE(JSON_EXTRACT(...))` 후 `NULLIF(값, '')` — 빈 문자열만 NULL로 접음 |
| `dataset.py:announcement_feature_payload` (서빙) | `None if value in ("", None) else value` — 빈 문자열/None 만 접음. **SQL 쪽과 동일 규칙** |
| `dataset.py:231-234` (학습, pandas) | `lwlt_rate`, `tech_ablt_evl_rt`, `bid_prce_evl_rt`, `tot_prdprc_num`, `drwt_prdprc_num` 에 `pd.to_numeric(errors="coerce")` — 숫자로 안 읽히면 전부 NaN |
| `features.py:_coerce_category` | `_is_missing(value) or value == ""` 만 `MISSING_CATEGORY`("미상")로 접음. 그 외 문자열은 그대로 범주 |
| `features.py:_coerce_float` | `None` 또는 `float()` 변환 실패(`ValueError`/`TypeError`) 또는 비유한값이면 `default`(보통 0.0). **NaN 도 `math.isfinite` 에서 걸려 default 로 접힙니다** |

핵심 관찰: **숫자형 4개 필드는 학습의 `pd.to_numeric(errors="coerce")` 가 만드는 NaN 과, 서빙의 `_coerce_float` 가 직접 만나는 비숫자 문자열이 결국 같은 `_coerce_float` 를 거쳐 같은 `default` 로 수렴합니다.** 즉 원천이 부재를 빈 문자열로 적든, `'0'` 으로 적든, `'미정'` 같은 임의 텍스트로 적든 두 경로가 항상 같은 값에 도달합니다. `lwlt_rate` 가 접힌 것은 우연이 아니라 이 숫자 변환 함수 조합의 일반적 성질입니다.

---

## 4. 필드별 등급

| 필드 | raw_data 키 | 부재 표기 관측 | 처리 | 등급 |
| --- | --- | --- | --- | --- |
| `lwlt_rate` | `sucsfbidLwltRate` | 빈 문자열(27.0%), 키 없음(23.8%), `'0'`(2025-01 이전 다수) | `dataset.py:238` 이 0 을 NA 로, `features.py:259` 가 결측 지시자 별도 생성 | **접힘(안전)** — 이미 확인됨(4.4) |
| `tech_ablt_evl_rt` | `techAbltEvlRt` | 빈 문자열(37.7%), 키 없음(28.9%). 값은 `'90'`/`'90.0'` 등 정수·소수 표기 혼재 | `pd.to_numeric` + `_coerce_float` → 결측·비숫자 텍스트 전부 0.0 | **접힘(안전)**. 단 결측 지시자 없음(6장) |
| `bid_prce_evl_rt` | `bidPrceEvlRt` | 위와 동일(협상계약 아니면 미기재) | 위와 동일 | **접힘(안전)**. 결측 지시자 없음 |
| `tot_prdprc_num` | `totPrdprcNum` | 빈 문자열(15.9%), 키 없음(15.3%), `'15'`/`'15.0'` 혼재 | 위와 동일 | **접힘(안전)**. 결측 지시자 없음 |
| `drwt_prdprc_num` | `drwtPrdprcNum` | 빈 문자열(15.9%), 키 없음(15.3%), `'4'`/`'4.0'`, `'0'`/`'0.0'` 혼재 | 위와 동일 | **접힘(안전)**. 결측 지시자 없음 |
| `prearng_mthd` | `prearngPrceDcsnMthdNm` | 빈 문자열·키 없음 합쳐 0.03% 수준 | `_coerce_category` → 미상 | **접힘(안전)** |
| `sucsfbid_mthd_nm` | `sucsfbidMthdNm` | 표본 20,000행 중 결측 0건, 104종 범주 | `_coerce_category` | **접힘(안전)**(관측 범위 내 결측 자체가 없음) |
| `srvce_div_nm` | `srvceDivNm` | 표본 20,000행 중 결측 0건, 3종 범주 | `_coerce_category` | **접힘(안전)** |
| `lrg_clsfc_nm` | `pubPrcrmntLrgClsfcNm` | 빈 문자열 0.45%, 키 없음 0.01% | `_coerce_category` → 미상 | **접힘(안전)** |
| `mid_clsfc_nm` | `pubPrcrmntMidClsfcNm` | 위와 동일(같은 조인 원본) | `_coerce_category` | **접힘(안전)** |
| `clsfc_nm` | `pubPrcrmntClsfcNm` | 위와 동일 | `_coerce_category` | **접힘(안전)** |
| `intrbid_yn` | `intrbidYn` | `N` 98.5%, `Y` 0.8%, 빈 문자열 0.5%, 키 없음 0.2% | `_coerce_category` → 빈 문자열/키없음만 미상. `N` 은 실제 값(국내입찰) | **접힘(안전)** — `N` 은 placeholder 가 아니라 도메인 값 |
| `ppsw_gnrl_srvce_yn` | `ppswGnrlSrvceYn` | `N` 89.5%, `Y` 10.5%, 결측 0건(표본 내) | `_coerce_category` | **접힘(안전)** |

**13개 전부 안전 등급이며, 이번 점검에서 범주로 남음(취약)이나 train-serve 불일치(즉시조치)는 나오지 않았습니다.**

---

## 5. 코디네이터 확인 요청 2 — `'88'` vs `'88.0'` 표기 이중화

숫자형 필드 5개(`lwlt_rate`, `tech_ablt_evl_rt`, `bid_prce_evl_rt`, `tot_prdprc_num`, `drwt_prdprc_num`) **전부**에서 정수·소수 이중 표기가 관측됩니다(예: `tech_ablt_evl_rt` 의 `'90'`/`'90.0'`, `tot_prdprc_num` 의 `'15'`/`'15.0'`, `drwt_prdprc_num` 의 `'4'`/`'4.0'`, `'0'`/`'0.0'`). 8개 범주형 필드는 숫자가 아니므로 이 형태의 이중화가 구조적으로 발생하지 않으며, 표본에서도 관측되지 않았습니다.

이 이중화는 **무해합니다.** 4장에서 확인했듯 다섯 필드 모두 `pd.to_numeric`/`_coerce_float` 를 거쳐 부동소수로 통일되므로 `'88'` 과 `'88.0'` 은 학습·서빙 양쪽에서 항상 같은 수치 88.0 이 됩니다. 범주나 문자열로 다루는 경로가 없어 갈라질 자리가 없습니다.

---

## 6. 한계와 남는 위험

1. **결측 지시자는 `lwlt_rate` 하나뿐입니다.** `tech_ablt_evl_rt`, `bid_prce_evl_rt`, `tot_prdprc_num`, `drwt_prdprc_num` 은 결측과 진짜 0 이 구분되지 않습니다. 이는 표기 변경에 대한 스큐가 아니라(3장 핵심 관찰: 임의 표기가 전부 같은 default 로 수렴), **정보 손실**입니다. `tech_ablt_evl_rt`/`bid_prce_evl_rt` 는 협상계약이 아니면 구조적으로 없는 값이라 결측이 66.6% 로 크고, 모델이 "일반 계약"과 "정확히 0점 배점"을 구분 못 합니다.
2. **범주형 8개는 표본(20,000행, 2025-01 이후)에서 placeholder 텍스트를 못 찾았을 뿐, 없다는 증명은 아닙니다.** `'해당없음'`, `'미정'`, `'공고서참조'` 같은 값이 희귀하게 있고 표본에 안 걸렸을 가능성은 남습니다. 이 값들은 `_coerce_category` 를 거치면 미상으로 접히지 않고 그대로 범주가 되므로, 존재한다면 5장과 다른 결론이 나옵니다.
3. **`apply_categorical_dtypes` 의 안전망은 별도로 확인하지 않았습니다.** 학습 시점에 없던 범주가 서빙에서 들어오면 미상으로 강제 치환되는 코드는 읽었지만(`features.py:71-97`), 실제 재현이나 반대 방향(학습 때만 있던 placeholder 범주가 사라지는 경우)의 영향은 이번 점검 범위 밖입니다.
4. **`sucsfbid_mthd_nm` 의 104종 범주 전부를 개별 검토하지 않았습니다.** 표본에서 결측 0건이었으나 104종 중 소수가 실질적으로 "미정"에 가까운 라벨일 가능성은 배제하지 못합니다.
5. **선행 문서 4.1 의 `prearng_mthd`(비예가) 서술과의 모순은 별도 escalation 으로 보고했습니다.** 답변 대기 중이며, 정정되면 이 문서 4장의 `prearng_mthd` 배경 서술(부재율 수치)을 갱신해야 할 수 있습니다. 단 등급 판정(접힘/안전) 자체는 코드 경로 분석에 근거하므로 영향받지 않습니다.

---

## 7. 검증

| 항목 | 결과 |
| --- | --- |
| DB 읽기 전용 조회 | 완료 (SELECT 만) |
| `src/ml/` 파일 수정 | 없음 |
| parquet, 모델, 원본 변경 | 없음 |
| 학습 실험 | 미수행 |
| `uv run ruff check .` | 통과 |
| `uv run python scripts/validate_agent_rules.py` | 통과 |
| 커버리지 | 학습 사용 13개 필드 전부 코드 경로 확인, 값 분포는 20,000행 표본(2025-01 이후) 기준 |
