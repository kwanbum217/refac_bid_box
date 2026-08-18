# 금액 미공개 공고의 예측 처리 (ADR)

> **작성일**: 2026-08-04
> **버전**: v1.0.0
> **상태**: 확정. 원본과 **의도적으로 다른 동작**입니다
> **관련**: [`servc_prediction_model_design.md`](servc_prediction_model_design.md)

---

## 결정

기초금액과 예정가격이 모두 없는 공고는 **예측을 거부합니다.** 원본처럼 추천
투찰가 0원을 돌려주지 않습니다.

---

## 증상

챗봇에 "최근 물품 예측해줘" 를 물었을 때 나온 실제 응답입니다.

| 항목 | 값 |
| --- | --- |
| 공고명 | 수질자동분석기(Water Automatic Analyzer) 구매 |
| 분야 | 외자 |
| 기초금액 | **0원** |
| 예상 낙찰률 | **105.0%** |
| 추천 투찰가 | **0원** |

낙찰률 105% 는 모델 출력이 아니라 `DEFAULT_RATIO_MAX` 상한에 걸린 값입니다.
투찰가 0원은 기준 금액 0에 낙찰률을 곱한 결과입니다.

---

## 원인

해당 공고(`R26BK01402966`)의 DB 값입니다.

```
base_amount:  NULL
presmpt_prce: 0
```

`prediction_reference_amount` 는 `resolved_base_amount` 가 없으면 `presmpt_prce`
로 넘어가는데, 그마저 0이라 기준 금액이 0이 됩니다.

```python
reference_amount = float(bid.prediction_reference_amount or 0)  # 0.0
optimal_price = int(reference_amount * predicted_rate)  # 0
```

챗봇 도구의 후보 필터는 `is_not(None)` 이라 **NULL 만 거르고 0은 통과**시켰습니다.

---

## 규모

```sql
SELECT category, COUNT(*) total,
       SUM(CASE WHEN COALESCE(base_amount,0)=0
                 AND COALESCE(presmpt_prce,0)=0 THEN 1 ELSE 0 END) no_amount
FROM bid_announcements GROUP BY category;
```

| 분야 | 전체 | 금액 없음 | 비율 |
| --- | ---: | ---: | ---: |
| 외자 (Frgcpt) | 31,470 | 15,058 | **47.85%** |
| 물품 (Thng) | 1,515,508 | 59,787 | 3.95% |
| 용역 (Servc) | 2,102,766 | 23,014 | 1.09% |
| 공사 (Cnstwk) | 1,811,335 | 10,588 | 0.58% |
| **합계** | 5,461,079 | **108,447** | 1.99% |

외자는 절반 가까이가 예정가격을 공개하지 않습니다.

---

## 원본은 어떻게 하는가

원본 `apps/predictions/views.py` 도 **동일하게 0원을 반환합니다.**

```python
reference_amount = float(bid.prediction_reference_amount or 0)
estimated_price = reference_amount
if predicted_rate < 2.0:
    optimal_price = int(estimated_price * predicted_rate)  # 0
```

`confidence` 계산에서만 `estimated_price > 0` 을 확인해 50을 넣고, 결과 금액은
그대로 0원을 내보냅니다.

**이식 결함이 아니라 원본부터 있던 결함입니다.**

---

## 왜 원본을 따르지 않는가

`SKILLS.md` 의 품질 우선순위 1번은 **정확성 — 잘못된 결과를 내지 않을 것** 입니다.
추천 투찰가 0원은 답이 아니라 오답입니다. 사용자가 그대로 믿으면 입찰에
0원을 써내게 됩니다.

원본 UI 를 재현하는 것과 원본의 오답을 재현하는 것은 다른 문제입니다.

---

## 조치

| 위치 | 변경 |
| --- | --- |
| `src/app/api/v1/predictions.py` | 기준 금액이 0 이하면 **HTTP 422** 와 사유 반환 |
| `src/app/services/tools/bid_prediction_tool.py` | 후보 필터를 `> 0` 으로 강화하고, `prediction_reference_amount` 로 최종 판정 |

후보 필터만으로는 부족합니다. `raw_data` 의 `bdgtAmt` 가 `"0"` 이면 SQL 필터를
통과하고도 기준 금액이 0이 되므로, 파이썬 단계에서 다시 확인합니다. 요청 건수를
채우기 위해 여유분(`CANDIDATE_OVERSAMPLE = 3`)을 더 읽습니다.

### 화면 동작

예측 폼을 **미리 잠급니다.** 눌렀을 때 알리는 것보다 애초에 못 누르게 하는 편이
낫습니다. 외자 공고는 절반 가까이가 이 상태라 알림창이 반복해서 뜹니다.

| 요소 | 금액 있음 | 금액 없음 |
| --- | --- | --- |
| 투찰 금액 입력창 | 정상 | `disabled` |
| 분석 실행 버튼 | 정상 | `disabled` |
| 사유 안내 | 없음 | 폼 아래 노출 |

```
기초금액과 예정가격이 모두 공개되지 않은 공고라 투찰가를 산출할 수 없습니다.
```

판정은 템플릿에서 `bid.prediction_reference_amount` 로 합니다. 서버 계산과 같은
값이라 화면과 API 판단이 어긋나지 않습니다.

API 의 422 는 그대로 둡니다. 화면을 우회한 직접 호출과 다른 클라이언트를 막는
방어선이며, 원본 `detail.html` 의 오류 처리가 `detail` 을 알림창에 띄웁니다.

---

## 회귀 방지

| 테스트 | 파일 |
| --- | --- |
| 금액 전무 공고 거부 | `tests/test_predictions_api.py` |
| `raw_data` 예산 0 거부 | 〃 |
| 챗봇 후보에서 제외 | `tests/test_chatbot_prediction.py` |
| 금액 없는 건이 섞여도 요청 건수 충족 | 〃 |
| 예측 폼 잠금과 사유 노출 | `tests/test_ui_ssr.py` |
| 금액 있으면 폼 정상 노출 | 〃 |

---

## 원본 대비 차이 정리

| 항목 | 원본 | 이식본 |
| --- | --- | --- |
| 금액 없는 공고 예측 | 진행. 추천 투찰가 **0원** 반환 | **거부** (HTTP 422) |
| 예측 폼 | 항상 활성 | 금액 없으면 **잠금 + 사유 표시** |
| 챗봇 예측 대상 선정 | `NULL` 만 제외 | 기준 금액 0 이하 전부 제외 |

디자인과 레이아웃은 그대로입니다. 추가된 것은 `disabled` 속성과 사유 문구
한 줄이며, 금액이 있는 공고에서는 원본과 동일하게 렌더링됩니다.
