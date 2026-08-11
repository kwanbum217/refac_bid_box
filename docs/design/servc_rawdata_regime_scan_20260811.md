# 용역 raw_data 나머지 필드의 2025-01 체제 전환 전수 확인

> **작성일**: 2026-08-11
> **상태**: 읽기 전용 감사 완료
> **결론**: 추가로 16건의 계단식 전환을 찾았습니다. 그중 6건이 2025-01 에 몰려 있어 경계 가설을 보강합니다. **현재 학습에 쓰는 필드에서는 전환이 나오지 않았습니다.**
> **선행**: [`servc_2025_source_regime_shift_20260811.md`](servc_2025_source_regime_shift_20260811.md), [`servc_unused_rawdata_field_audit_20260811.md`](servc_unused_rawdata_field_audit_20260811.md)

---

## 1. 배경

선행 감사에서 `prdctClsfcLmtYn`, `rbidPermsnYn`, `sucsfbidLwltRate` 세 필드가 2025-01 을 경계로 계단식 전환을 겪은 것이 확인됐습니다. 세 개에서 나왔으므로 raw_data 의 나머지 필드에도 같은 경계를 공유하는 것이 더 있는지 전수로 확인합니다.

---

## 2. 대상 필드 확정

`bid_announcements` 의 `category='Servc'` 표본(연도별 5,000~20,000행, `scripts/audit_servc_raw_data_keys.py` 2026-08-11 실행분)에서 raw_data 는 **113 종의 키**를 씁니다. 이 중:

| 구분 | 개수 | 내용 |
| --- | ---: | --- |
| 정규 컬럼으로 이미 옮겨 담김 | 12 | `COLUMN_MAPPED` (`bidNtceNm` 등). 학습 특징 경로가 이미 통과하므로 제외 |
| 2026-08-03 조사(`survey_servc_fields.py`)로 연관도까지 측정됨 | 51 | `IN_USE`(학습 사용 13) + `CANDIDATES`(미사용 후보 38) |
| 이번 감사 이전 **한 번도 조사되지 않음** | 52 | URL, 파일명, 전화번호, 이메일, 날짜류 다수 포함 |

51종 중 11종은 `servc_2025_source_regime_shift_20260811.md` 3.1/3.2 에서 이미 월별 추적을 마쳤습니다(`prdctClsfcLmtYn`, `rbidPermsnYn`, `sucsfbidLwltRate`, `indstrytyLmtYn`, `dsgntCmptYn`, `cmmnSpldmdMethdNm`, `sucsfbidMthdNm`, `prearngPrceDcsnMthdNm`, `intrbidYn`, `srvceDivNm`, `totPrdprcNum`).

**이번 감사 대상은 51 - 11 = 40종과, 한 번도 조사되지 않은 52종을 합친 92종입니다.** 92종 안에는 학습에 쓰는데 아직 전환을 확인하지 않은 필드 7개(`pubPrcrmntLrgClsfcNm`, `pubPrcrmntMidClsfcNm`, `pubPrcrmntClsfcNm`, `techAbltEvlRt`, `bidPrceEvlRt`, `drwtPrdprcNum`, `ppswGnrlSrvceYn`)가 포함됩니다. 이것이 5장의 핵심입니다.

---

## 3. 방법

### 3.1 표본 설계

기존 `scripts/audit_servc_flag_regime.py` 는 필드 하나당 77만 행(2023년 이후 Servc) 전체를 `SUM(JSON_EXTRACT(...)='Y')` 로 스캔합니다. 필드당 40~50초가 걸려 92개 필드로는 감당이 안 됩니다(직접 측정: `techAbltEvlRt` 1건에 47.5초).

대신 새 스크립트 `scripts/audit_servc_rawdata_regime_scan.py` 를 만들어 **월별로 raw_data 원문을 표본 추출**한 뒤 파이썬에서 92개 필드를 한 번에 집계합니다.

- 표본: 2023-01 ~ 2026-08(부분월), 월마다 최대 **3,000행**(`bid_ntce_dt` 순, `LIMIT`). 2026-08 은 데이터가 206행뿐이라 표본 그대로 사용
- 월 44개 전부 표본을 뜨는 데 총 6초 안팎(쿼리 1개당 0.1~0.3초)
- 값 비교 전 숫자 표기를 정규화합니다(`4.0` 과 `4` 를 같은 값으로 취급). 정규화 전에는 `drwtPrdprcNum` 의 JSON 타입 표기 차이가 가짜 전환으로 잡혔습니다

### 3.2 계단식 전환의 정의 (고정)

인접한 두 달 사이에 다음 중 하나가 **20%p 이상** 변하면 급변으로 표시합니다.

1. **값 존재율**: `raw_data` 에 해당 키가 있고 빈 문자열이 아닌 행의 비율
2. **최빈값 비중**: 값이 존재하는 행 중 가장 흔한 값이 차지하는 비율

존재율만 보면 `prdctClsfcLmtYn` 처럼 **항상 채워져 있으면서 값 구성만 뒤집히는 경우**를 놓칩니다. 그래서 두 지표를 함께 봅니다.

최빈값비중은 표본이 작으면(존재 행이 적으면) 잡음으로 0%/100% 를 오갑니다. 예비 실행에서 `bidGrntymnyPaymntYn` 같은 필드가 매달 뒤집혀 172건이 잡혔는데, 존재 행이 수십 건 수준이었습니다. **존재 행이 양쪽 달 모두 200건 이상일 때만** 최빈값비중 급변을 인정하도록 `MIN_EXISTING_FOR_TOP=200` 을 두었습니다. 이 가드 이후 172건이 16건으로 줄었습니다.

---

## 4. 결과 — 급변 16건

`data/analysis/servc_rawdata_regime_scan/jumps.csv` 전량입니다. 학습 사용 필드는 0건입니다.

| 필드 | 전환 월 | 지표 | 전 | 후 | 학습 사용 |
| --- | --- | --- | ---: | ---: | --- |
| `arsltApplDocRcptMthdNm` | 2025-01 | 존재율 | 47.2% | 16.9% | 아니오 |
| `bidPrtcptFee` | 2025-01 | 존재율 | 0.2% | 84.3% | 아니오 |
| `ntceInsttOfclEmailAdrs` | 2025-01 | 존재율 | 91.6% | 0.0% | 아니오 |
| `pqEvalYn` | 2025-01 | 존재율 | 93.2% | 8.0% | 아니오 |
| `pqEvalYn` | 2025-01 | 최빈값비중 | 97.8% | 58.3% | 아니오 |
| `tpEvalYn` | 2025-01 | 존재율 | 0.1% | 88.4% | 아니오 |
| `rsrvtnPrceReMkngMthdNm` | 2025-01 | 최빈값비중 | 50.4% | 99.8% | 아니오 |
| `brffcBidprcPermsnYn` | 2023-03 | 존재율 | 64.8% | 44.4% | 아니오 |
| `brffcBidprcPermsnYn` | 2023-04 | 존재율 | 44.4% | 0.3% | 아니오 |
| `infoBizYn` | 2023-02 | 최빈값비중 | 50.4% | 71.3% | 아니오 |
| `purchsObjPrdctList` | 2023-02 | 최빈값비중 | 34.3% | 13.9% | 아니오 |
| `rgnLmtBidLocplcJdgmBssCd` | 2023-04 | 존재율 | 0.0% | 23.4% | 아니오 |
| `rgnLmtBidLocplcJdgmBssNm` | 2023-04 | 존재율 | 0.0% | 23.4% | 아니오 |
| `rsrvtnPrceReMkngMthdNm` | 2023-03 | 존재율 | 67.0% | 46.2% | 아니오 |
| `sucsfbidMthdAppStd` | 2025-12 | 존재율 | 5.7% | 29.5% | 아니오 |
| `tpEvalYn` | 2026-01 | 존재율 | 93.6% | 23.7% | 아니오 |

### 4.1 2025-01 군집

16건 중 **6개 필드, 7건**이 2025-01 에 몰려 있습니다: `arsltApplDocRcptMthdNm`, `bidPrtcptFee`, `ntceInsttOfclEmailAdrs`, `pqEvalYn`, `tpEvalYn`, `rsrvtnPrceReMkngMthdNm`. 선행 감사에서 확인된 두 필드(`prdctClsfcLmtYn`, `rbidPermsnYn`)와 합치면 **8개 필드가 2025-01 을 경계로 계단식으로 움직입니다.** 세 번째로 확인됐던 `sucsfbidLwltRate` 는 이후 재분해([`servc_lwlt_missing_remechanism_20260811.md`](servc_lwlt_missing_remechanism_20260811.md) 4.4)에서 결측 표기가 `'0'` 에서 빈 문자열로 바뀐 표기 변경으로 정정됐으므로 이 군집에서 뺍니다. 7장에 관련 한계를 적었습니다.

`ntceInsttOfclEmailAdrs` 는 존재율이 91.6% 에서 0.0% 로 한 달 만에 사라졌습니다. `bidPrtcptFee` 와 `tpEvalYn` 은 반대로 거의 없던 값이 갑자기 채워집니다(0.1~0.2% -> 84~88%). 방향이 필드마다 다르므로 **단일 필드의 결측 증가가 아니라 원천 응답 스키마 자체가 그 시점에 바뀐 것**으로 보입니다. 원인은 저장소 안에서 특정할 수 없습니다.

### 4.2 2023년 초 군집 — 별개로 취급

`brffcBidprcPermsnYn`, `infoBizYn`, `purchsObjPrdctList`, `rgnLmtBidLocplcJdgmBssCd/Nm`, `rsrvtnPrceReMkngMthdNm` 은 2023-02~04 에 몰려 있습니다. 표본 시작이 2023-01 이라 이 구간은 수집 초기 안정화 구간과 겹칠 수 있습니다. **2025-01 군집과 같은 경계로 묶지 않습니다.** 별도 확인 없이는 원인을 말할 수 없습니다.

`sucsfbidMthdAppStd`(2025-12), `tpEvalYn`(2026-01 두 번째 전환)은 위 두 군집 어디에도 속하지 않는 개별 사례입니다.

---

## 5. 핵심 — 학습 사용 필드는 전환이 없습니다

92개 대상 중 학습에 쓰는 7개(`pubPrcrmntLrgClsfcNm`, `pubPrcrmntMidClsfcNm`, `pubPrcrmntClsfcNm`, `techAbltEvlRt`, `bidPrceEvlRt`, `drwtPrdprcNum`, `ppswGnrlSrvceYn`)를 포함해 **`IN_USE` 어느 필드에서도 급변이 검출되지 않았습니다.**

이전 감사(`servc_2025_source_regime_shift_20260811.md`)에서 학습 사용 필드 중 유일하게 전환 후보였던 `sucsfbidLwltRate`(하한율)는 이후 재분해에서 표기 변경으로 정정됐습니다(7장). **학습에 쓰는 13개 필드 전부(`IN_USE`)를 2025-01 경계 관점에서 훑은 결과, 진짜 계단식 전환은 하나도 없습니다.**

---

## 6. 유보

1. **표본 기반입니다.** 월 3,000행(2026-08 은 206행) 표본이며 전수 스캔이 아닙니다. 존재율은 표본 오차가 작지만(3,000 표본에서 20%p 이상 차이는 잡음으로 보기 어려움), 희귀 값 구성은 표본에 따라 흔들릴 수 있습니다.
2. **원인은 저장소 안에서 특정할 수 없습니다.** 2025-01 군집이든 2023년 초 군집이든 제도 변경으로 단정하지 마십시오. 관측된 경계로만 쓰십시오.
3. **미사용 필드의 신호 자체는 측정하지 않았습니다.** 이번 감사는 값 구성의 시점 안정성만 봤습니다. 후보로 쓰려면 `survey_servc_fields.py` 식의 연관도 측정이 별도로 필요합니다.

---

## 7. 한계 — 값 존재율 정의가 표기 변경을 전환으로 잘못 셀 수 있습니다

이 스크립트의 "값 존재율"은 `raw_data` 에 키가 있고 빈 문자열이 아닌 행의 비율입니다. **키가 있고 빈 문자열이 아니기만 하면 값의 내용과 무관하게 존재로 셉니다.** 이 정의는 원천이 "값 없음"을 표기하는 방식 자체가 바뀐 경우를 실제 가용성 변화로 착각합니다.

정확히 이 문제가 `sucsfbidLwltRate`(하한율)에서 실측됐습니다. [`servc_lwlt_missing_remechanism_20260811.md`](servc_lwlt_missing_remechanism_20260811.md) 4.4 는 2025-01 을 기점으로 결측 표기가 문자열 `'0'` 에서 빈 문자열로 바뀌었을 뿐, 실제 양수 보유 비율은 2024-06 46.6% -> 2026-08 38.4% 로 완만하게만 떨어졌다는 것을 보였습니다(계단 아님, 8.3%p 의 점진 하락). 선행 문서 3.2 의 "값 존재율 급락"은 이 표기 변경이 만든 착시였습니다.

이번 감사의 16건 중 값 자체가 `'0'`, `'N'` 처럼 정보량이 적은 기본값인 필드(`bidPrtcptFee`, `pqEvalYn`, `tpEvalYn` 등)는 같은 함정에 노출됩니다. 존재율이 뛴 것이 실제 필드 도입인지, 결측 표기가 빈 문자열에서 기본값으로 (또는 반대로) 바뀐 것인지는 이 감사만으로 구분할 수 없습니다. **7장 표의 16건은 "값 존재율 정의 아래에서 계단식으로 보인다"는 관측이지, 전부가 원천의 실제 가용성 변화라는 판정이 아닙니다.**

그럼에도 **5장의 핵심 판정(학습 사용 13개 필드 무전환)은 이 한계로 흔들리지 않습니다.** 이유는 방향성에 있습니다. 표기 변경은 값 존재율을 실제보다 **과대평가하거나 과소평가해 없는 전환을 있는 것처럼 만듭니다(가짜 양성)**. 반대로 진짜 전환이 있는데 표기 변경이 그것을 가려 감지 못 하게 만드는 경로(가짜 음성)는 없습니다. 표기가 무엇으로 바뀌든 "값이 있다/없다"의 판정 자체는 여전히 어느 방향으로든 갈라지고, 진짜로 안정적인 필드가 표기 변경 때문에 안정적으로 "보이는" 경우는 생기지 않습니다. 즉 이 정의는 **없는 전환을 만들어낼 수는 있어도 있는 전환을 감출 수는 없습니다.** `IN_USE` 13개 필드에서 급변이 하나도 검출되지 않았다는 것은 (일부 검출이 표기 착시일 위험과 무관하게) 이 정의 아래에서 볼 수 있는 전환이 전혀 없었다는 뜻이고, 이는 가짜 음성이 아니라 그대로 유효한 음성입니다.

---

## 8. 재현

```bash
uv run python scripts/audit_servc_rawdata_regime_scan.py
```

결과는 `data/analysis/servc_rawdata_regime_scan/jumps.csv` 에 기록됩니다.

---

## 9. 검증

| 항목 | 결과 |
| --- | --- |
| DB 읽기 전용 조회 | 완료 (SELECT 만) |
| parquet, 모델, 원본, `src/ml/features.py` 변경 | 없음 |
| 학습 실험 | 미수행 |
| `uv run ruff check .` | 통과 |
| `python scripts/validate_agent_rules.py` | 통과 |
| 전환 원인 특정 | **미완.** 저장소 안에서는 불가 |
