# 협상에 의한 계약 입찰가격 평점 입력 조사

> 작성일: 2026-09-10
> 대상: `category='Servc'`, `bid_ntce_dt >= '2026-05-26'`, `sucsfbidMthdNm`가 `협상에의한계약`으로 시작하는 공고
> 결론: 협상계약 전용 가격평점 산식은 저장소 근거만으로 확정할 수 없습니다.

## 1. 결론 요약

협상 공고 20,077건에서 `techAbltEvlRt`와 `bidPrceEvlRt`는 모두 채워져 있지만, 이는 기술능력과 입찰가격의 배점 비율이지 가격평점 계산식 자체가 아닙니다. `sucsfbidMthdAppStd`는 20,077건 전부 빈 문자열이므로 DB 원본에서 세부 가격평점식을 확인할 수 없습니다.

가격평점 계산에 경쟁 투찰가 목록 또는 최저 투찰가가 필요한지 여부는 공고별 평가기준 확인 없이는 확정할 수 없습니다. 다만 `bid_results`에는 낙찰자 1명의 낙찰금액만 있고 경쟁자별 투찰금액·개찰 목록이 없으므로, 경쟁 투찰가를 요구하는 산식이라면 투찰 전 계산과 사후 재현 모두 불가능합니다.

`bid_announcements`의 기초금액(`base_amount`, 원본 `asignBdgtAmt`)과 공고 메타데이터는 일부 확보되어 있으나, 예정가격·A값·가격평점의 기준비율·배점한도·계수·통과점수는 협상계약 가격평점용으로 확정된 DB 필드가 아닙니다. 따라서 공고문에서 읽은 값을 사용자 입력으로 받아야 하며, 값을 받더라도 경쟁자별 투찰가가 필요한 산식의 결과인 순위·낙찰 여부는 계산할 수 없습니다.

## 2. 조사 범위와 데이터 현황

### 2.1 대상 공고

| 구분 | 건수 |
| --- | ---: |
| 협상계약 전체 | 20,077 |
| 협상에 의한 낙찰자 결정 | 16,197 |
| 협상에 의한 낙찰자 결정(SW사업) | 3,383 |
| 협상에 의한 낙찰자 결정(엔지니어링) | 341 |
| 협상에 의한 낙찰자 결정(건설엔지니어링) | 156 |

모집단은 `bid_announcements`에서 날짜와 업무구분을 제한하고 `raw_data.sucsfbidMthdNm LIKE '협상에의한계약%'`로 골랐습니다.

### 2.2 가격·배점 후보 필드 채움 현황

| 필드 | 의미 후보 | 채움 | 빈 값 |
| --- | --- | ---: | ---: |
| `techAbltEvlRt` | 기술능력 평가비율 | 20,077 | 0 |
| `bidPrceEvlRt` | 입찰가격 평가비율 | 20,077 | 0 |
| `sucsfbidMthdNm` | 낙찰방법 | 20,077 | 0 |
| `sucsfbidMthdAppStd` | 낙찰방법 적용기준 | 0 | 20,077 |
| `asignBdgtAmt` | 배정예산금액·기초금액 후보 | 20,077 | 0 |
| `presmptPrce` | 추정가격·참고금액 후보 | 20,077 | 0 |
| `prearngPrceDcsnMthdNm` | 예정가격 결정방법 | 20,077 | 0 |
| `totPrdprcNum` | 복수예비가격 총수 | 2,377 | 17,700 |
| `drwtPrdprcNum` | 추첨 예비가격 수 | 2,377 | 17,700 |
| `sucsfbidLwltRate` | 낙찰하한율 | 0 | 20,077 |

`base_amount`와 원본 `asignBdgtAmt`는 대상 20,077건 모두 값이 있습니다. 그러나 이 값은 기초금액 후보이며, 협상계약 가격평점에 쓰는 분모가 공고별로 무엇인지까지 확정하지 않습니다.

### 2.3 원본 JSON 최상위 키 전체 목록

키 스캔 결과는 다음과 같습니다.

```text
arsltApplDocRcptMthdNm, arsltCmptYn, arsltReqstdocRcptDt, asignBdgtAmt,
befBidBbancNo, bfSpecRgstNo, bidBeginDt, bidClseDt, bidGrntymnyPaymntYn,
bidMethdNm, bidNtceDt, bidNtceDtlUrl, bidNtceNm, bidNtceNo, bidNtceOrd,
bidNtceUrl, bidPrceEvlRt, bidPrtcptFee, bidPrtcptFeePaymntYn, bidPrtcptLmtYn,
bidQlfctRgstDt, brffcBidprcPermsnYn, chgDt, chgNtceRsn,
cmmnSpldmdAgrmntClseDt, cmmnSpldmdAgrmntRcptdocMethd, cmmnSpldmdCorpRgnLmtYn,
cmmnSpldmdMethdCd, cmmnSpldmdMethdNm, cntrctCnclsMthdNm, crdtrNm, dcmtgOprtnDt,
dcmtgOprtnPlce, dminsttCd, dminsttNm, dminsttOfclEmailAdrs, drwtPrdprcNum,
dsgntCmptYn, dtlsBidYn, exctvNm, indstrytyLmtYn, indutyVAT, infoBizYn,
intrbidYn, jntcontrctDutyRgnNm1, jntcontrctDutyRgnNm2, jntcontrctDutyRgnNm3,
mnfctYn, ntceDscrptYn, ntceInsttCd, ntceInsttOfclEmailAdrs, ntceInsttOfclNm,
ntceInsttOfclTelNo, ntceKindNm, ntceSpecDocUrl1, ntceSpecDocUrl10,
ntceSpecDocUrl2, ntceSpecDocUrl3, ntceSpecDocUrl4, ntceSpecDocUrl5,
ntceSpecDocUrl6, ntceSpecDocUrl7, ntceSpecDocUrl8, ntceSpecDocUrl9,
ntceSpecFileNm1, ntceSpecFileNm10, ntceSpecFileNm2, ntceSpecFileNm3,
ntceSpecFileNm4, ntceSpecFileNm5, ntceSpecFileNm6, ntceSpecFileNm7,
ntceSpecFileNm8, ntceSpecFileNm9, opengDt, opengPlce, orderPlanUntyNo,
ppswGnrlSrvceYn, pqApplDocRcptDt, pqApplDocRcptMthdNm, pqEvalYn,
prdctClsfcLmtYn, prearngPrceDcsnMthdNm, presmptPrce, pubPrcrmntClsfcNm,
pubPrcrmntClsfcNo, pubPrcrmntLrgClsfcNm, pubPrcrmntMidClsfcNm,
purchsObjPrdctList, rbidOpengDt, rbidPermsnYn, refNo, reNtceYn,
rgnDutyJntcontrctRt, rgnLmtBidLocplcJdgmBssCd, rgnLmtBidLocplcJdgmBssNm,
rsrvtnPrceReMkngMthdNm, rgstDt, rgstTyNm, srvceDivNm, stdNtceDocUrl,
sucsfbidLwltRate, sucsfbidMthdAppStd, sucsfbidMthdCd, sucsfbidMthdNm,
techAbltEvlRt, totPrdprcNum, tpEvalApplClseDt, tpEvalApplMthdNm, tpEvalYn,
untyNtceNo, VAT
```

위 목록에서 가격평점·배점·기준금액·평가방식과 직접 관련될 수 있는 키는 위 표에 별도로 정리했습니다. `sucsfbidMthdAppStd`가 전부 빈 값인 점 때문에 이 키만으로는 산식을 복원할 수 없습니다.

## 3. 낙찰률 참고 분포

### 3.1 조인과 품질 제한

`bid_announcements`와 `bid_results`를 다음 세 키 모두로 조인했습니다.

| 조인 키 | 설명 |
| --- | --- |
| `bid_ntce_no` | 공고번호 |
| `category` | 업무구분 |
| `LPAD(bid_ntce_ord, 3, '0')` | 차수 3자리 정규화 |

이 조건으로 성립한 조인 행은 5,014건입니다. 전체 협상 공고 20,077건 중 조인 성립분은 24.98%로 약 25%이며, 낙찰 결과가 수집된 공고만 `bid_results`와 조인되기 때문입니다. 이는 AQ2 조사에서 확인한 협상 연결률 25.38%와 같은 범위의 결과입니다.

기초금액과 낙찰금액으로 `낙찰금액 / 기초금액 * 100`을 계산하고, 다음과 같이 15건을 제외했습니다.

| 제외 사유 | 건수 |
| --- | ---: |
| 계산 불가(기초금액 0 또는 NULL) | 7 |
| 0 이하 | 2 |
| 0 초과 50% 미만 | 5 |
| 110% 초과 | 1 |
| 제외 합계 | 15 |

따라서 유효 표본은 `5,014 - 15 = 4,999`건이며, 3.2 절의 분포는 50% 이상 110% 이하로 제한한 값입니다. 110% 초과 1건은 낙찰금액 250,000,000원·기초금액 1원인 데이터 품질 이상치이므로 필터 없이 평균을 내면 분포를 왜곡합니다.

### 3.2 네 변종별 실측

| 낙찰방법 변종 | 유효 건수 | 평균 | 중앙값 | 최소 | 최대 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 협상에 의한 낙찰자 결정 | 3,975 | 94.6172 | 96.8349 | 65.6250 | 100.0000 |
| 협상에 의한 낙찰자 결정(SW사업) | 936 | 93.8110 | 97.2091 | 75.0000 | 100.0000 |
| 협상에 의한 낙찰자 결정(엔지니어링) | 58 | 90.9424 | 94.9996 | 71.9645 | 100.0000 |
| 협상에 의한 낙찰자 결정(건설엔지니어링) | 30 | 93.7441 | 95.1501 | 72.7412 | 100.0000 |

이 분포는 과거 낙찰 결과의 참고값일 뿐 가격평점 산식이나 경쟁자 투찰가를 대체하지 않습니다. 특히 저장소 문서도 협상계약에는 낙찰하한율 제도가 적용되지 않는다고 정리하고 있으므로, 적격심사 별표의 하한율을 협상계약에 전용하면 안 됩니다.

## 4. 산식 의존성 판정

### 4.1 산식 형태

협상계약 전용 산식의 형태는 **확정 불가**입니다. 저장소의 `evaluation_scoring.py`에는 일반용역 적격심사용 가격점수 함수가 있으나, 설계 문서는 협상계약 가격점수를 지원 범위에서 제외하고 있습니다. 따라서 그 일반용역 산식을 협상계약 산식으로 간주하지 않습니다.

공고 데이터에 존재하는 90:10, 80:20 등의 비율은 가격점수의 배점 비중으로 볼 수 있지만, 가격점수를 어떻게 환산하는지, 기준금액이 무엇인지, 하한·최저점·반올림 규칙이 무엇인지는 `sucsfbidMthdAppStd`가 비어 있어 확정할 수 없습니다.

### 4.2 입력 의존성

| 후보 입력 | 판정 | DB 근거 및 제약 |
| --- | --- | --- |
| 본인 투찰금액 | 필요 가능성이 높음 | 가격평점 대상값이지만 협상계약 전용 산식의 확정 근거는 없음. 사용자 입력 대상 |
| 예정가격 또는 공고가 정한 기준금액 | 필요 여부·정의 확정 불가 | 공고에는 기초금액·추정가격 후보가 있으나 가격평점 분모와 동일하다고 확정할 수 없음 |
| 경쟁자 투찰가·최저 투찰가 | 산식에 따라 필요 | `bid_results`에는 낙찰자 1명만 있고 경쟁자별 투찰 목록이 없음. 필요 산식이면 계산 불가 |
| 기술·가격 배점 비율 | 공고별 필요 | `techAbltEvlRt`, `bidPrceEvlRt`는 DB에 있음. 단, 세부 평점식은 아님 |
| 가격 배점한도 B, 계수 k, 기준비율 | 필요 가능성이 높음 | 협상계약 공고 원본의 세부 값·적용기준이 DB에 없음. 공고문 입력 필요 |
| 통과점수 T | 종합평가 시 필요 | 협상계약별 평가기준에 따라 다르며 DB에 확정 필드 없음. 공고문 입력 필요 |
| 비가격 점수 Q 및 구성요소 | 종합점수 시 필요 | 업체별 수행능력·가감점·증빙 결과가 DB에 없음. 사용자 입력 또는 별도 평가 절차 필요 |

따라서 경쟁자 투찰가를 쓰지 않는 산식이라는 사실이 공고문에서 확인되면, 본인 투찰금액·공고가 정한 기준금액·가격 배점 파라미터를 사용자 입력으로 받아 단일 공고의 가격점수만 계산할 수 있습니다. 반대로 경쟁자 투찰가 또는 최저 투찰가를 쓰는 산식이면 해당 계산은 차단해야 합니다.

## 5. 사용자 입력 제안

공고문에서 다음 값을 확인해 입력받을 수 있습니다. 이는 협상계약의 산식을 확정하는 것이 아니라, 공고문에 명시된 값을 계산 입력으로 전달하는 범위입니다.

| 사용자 입력 | 필요한 이유 | 공고문 확인 위치 |
| --- | --- | --- |
| 본인 투찰금액 | 가격점수의 대상값 | 입찰가격 제출·평가방법 표 |
| 가격평가 배점 비율 | 공고별 가격평가 비중이 다름 | 제안서 평가항목 및 배점표의 입찰가격 항목 |
| 기술능력 배점 비율 | 종합점수 구성 확인 | 제안서 평가항목 및 배점표의 기술능력 항목 |
| 기준금액의 종류와 금액 | 분모가 기초금액·예정가격·추정가격 중 무엇인지 공고별 확인 필요 | 입찰가격 평가방법, 예정가격·기초금액 안내 |
| 가격 배점한도 B | 가격점수 최대값 | 제안서 평가기준의 입찰가격 배점표 |
| 기준비율·계수 k 또는 공고가 제시한 가격점수 변수 | 세부 산식 재현에 필요 | 입찰가격 평점 산식이 있는 평가기준 표 |
| 통과점수 T | 적격·협상대상 판단에 필요 | 평가방법의 총점·통과기준·협상적격자 기준 |
| 비가격 점수 Q와 세부 점수 | 총점 계산에 필요 | 기술능력 평가결과, 가감점, 결격·증빙 결과 |
| 공고문에 명시된 경쟁 비교 기준 | 경쟁자 투찰가가 산식에 쓰이는지 판별 | 입찰가격 평가방법의 비교대상·최저가·평균가 설명 |

`B`, `k`, `T`는 일반용역 평가 조사에서 공고별 배점표를 사용자 입력으로 돌린 원칙과 같은 취급이 필요합니다. 현재 확인한 설계 문서에는 해당 값을 협상계약용으로 확정한 4.6 절이 없고, 협상계약 가격점수는 명시적으로 제외되어 있으므로, 이 목록은 입력 항목 제안이지 확정된 협상계약 규칙표가 아닙니다.

## 6. 입력을 모두 받아도 계산할 수 없는 결과

다음 결과는 DB 제약 또는 산식 미확정 때문에 계산하지 않습니다.

| 결과 | 판정 | 이유 |
| --- | --- | --- |
| 경쟁자별 가격평점 | 계산 불가 | 경쟁자별 투찰금액·개찰 목록이 없음 |
| 경쟁자와 비교하는 가격평점 | 산식 확인 전 계산 불가 | 비교대상과 비교 규칙이 공고문 확인 전 미확정 |
| 경쟁 순위 | 계산 불가 | 경쟁자 목록과 각 점수가 없음 |
| 낙찰 여부 | 계산 불가 | 순위·협상대상자 선정·발주기관 평가결과가 없음 |
| 종합점수 | 조건부 | 공고 산식, Q 구성요소, 증빙 평가결과를 모두 받아야 하며 현재 DB만으로는 불가 |
| 단일한 협상계약 가격점수 | 조건부 | 공고문에서 경쟁자 비의존 산식과 모든 파라미터를 확인한 경우에만 가능 |

## 7. 근거 문서와 확정 범위

- `docs/design/servc_qualification_evaluation_design_20260909.md`: 일반용역 적격심사 가격점수 산식과 사용자 입력 원칙을 제시하지만, 협상계약 가격점수는 제외 대상으로 명시합니다.
- `docs/design/servc_lwlt_missing_mechanism_20260810.md`: 협상에 의한 계약은 하한선 개념이 없는 방식으로 분류되어 있습니다.
- `docs/analysis/servc_lwlt_missing_20260830.md`: 협상 결측 표본 52건 평균 95.49%, SW사업 7건 평균 94.56%의 과거 실측을 제시하지만, 이는 가격평점 산식이 아니라 낙찰결과 참고값입니다.
- `src/app/services/evaluation_scoring.py`: 일반용역 적격심사 함수가 있으나 협상계약 전용 규칙이라는 근거는 없습니다.

따라서 확정 결론은 다음과 같습니다. 협상계약의 가격평점 산식은 공고문 평가기준 확인 없이 확정할 수 없고, DB에는 배점비율·기초금액 후보·낙찰자 결과만 있으며 세부 산식과 경쟁 투찰가 목록은 없습니다. 구현 시에는 공고문에서 산식 유형을 확인한 뒤 필요한 값만 사용자 입력으로 받고, 산식 유형과 경쟁 데이터가 확인되지 않으면 가격평점·순위·낙찰 여부를 계산하지 않아야 합니다.

## 8. 재현 질의와 결과 원문

모든 질의는 다음 읽기 전용 실행기로 실행했습니다.

```bash
uv run python scripts/db_readonly_query.py --sql "<단일 SELECT 질의>" --limit <N>
```

핵심 질의와 결과 요약은 다음과 같습니다.

```sql
SELECT DISTINCT jt.k AS json_key
FROM bid_announcements a
JOIN JSON_TABLE(JSON_KEYS(a.raw_data), '$[*]' COLUMNS(k VARCHAR(128) PATH '$')) jt
WHERE a.category='Servc' AND a.bid_ntce_dt >= '2026-05-26'
  AND JSON_UNQUOTE(JSON_EXTRACT(a.raw_data,'$.sucsfbidMthdNm')) LIKE '협상에의한계약%'
ORDER BY jt.k
```

결과 원문은 3.3 절의 전체 키 목록이며, 총 109개 키가 확인되었습니다. 가격 관련 후보별 채움 수는 2.2 절의 표와 같습니다.

```sql
SELECT JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.sucsfbidMthdNm')) AS method, COUNT(*) AS n
FROM bid_announcements
WHERE category='Servc' AND bid_ntce_dt >= '2026-05-26'
  AND JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.sucsfbidMthdNm')) LIKE '협상에의한계약%'
GROUP BY method ORDER BY n DESC
```

```text
협상에의한계약-협상에 의한 낙찰자 결정          16197
협상에의한계약-협상에 의한 낙찰자 결정(SW사업)    3383
협상에의한계약-협상에 의한 낙찰자 결정(엔지니어링)   341
협상에의한계약-협상에 의한 낙찰자 결정(건설엔지니어링) 156
```

```sql
SELECT JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.techAbltEvlRt')) AS tech,
       JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.bidPrceEvlRt')) AS price,
       COUNT(*) AS n
FROM bid_announcements
WHERE category='Servc' AND bid_ntce_dt >= '2026-05-26'
  AND JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.sucsfbidMthdNm')) LIKE '협상에의한계약%'
GROUP BY tech, price ORDER BY n DESC
```

```text
90/10 10984, 80/20 8260, 70/30 545, 100/0 133, 85/15 59,
50/50 29, 10/90 17, 60/40 17, 99/1 12, 95/5 7,
20/80 6, 30/70 3, 40/60 2, 75/25 2, 78/22 1
```

```sql
SELECT COUNT(*) AS joined_rows
FROM bid_announcements a JOIN bid_results r
  ON r.bid_ntce_no=a.bid_ntce_no AND r.category=a.category
 AND LPAD(r.bid_ntce_ord,3,'0')=LPAD(a.bid_ntce_ord,3,'0')
WHERE a.category='Servc' AND a.bid_ntce_dt >= '2026-05-26'
  AND JSON_UNQUOTE(JSON_EXTRACT(a.raw_data,'$.sucsfbidMthdNm')) LIKE '협상에의한계약%'
```

```text
joined_rows = 5014
```

3.1 절의 제외 회계는 다음 질의로 재현할 수 있습니다. `CASE`의 순서는 기초금액 0 또는 NULL인 행을 먼저 계산 불가로 분류한 뒤, 계산된 낙찰률의 범위별로 분류하도록 했습니다.

```sql
WITH joined AS (
  SELECT a.base_amount, r.sucsf_bid_amt,
         r.sucsf_bid_amt / NULLIF(a.base_amount, 0) * 100 AS bid_rate
  FROM bid_announcements a JOIN bid_results r
    ON r.bid_ntce_no=a.bid_ntce_no AND r.category=a.category
   AND LPAD(r.bid_ntce_ord,3,'0')=LPAD(a.bid_ntce_ord,3,'0')
  WHERE a.category='Servc' AND a.bid_ntce_dt >= '2026-05-26'
    AND JSON_UNQUOTE(JSON_EXTRACT(a.raw_data,'$.sucsfbidMthdNm')) LIKE '협상에의한계약%'
), classified AS (
  SELECT CASE
    WHEN base_amount IS NULL OR base_amount = 0 THEN '계산 불가(기초금액 0 또는 NULL)'
    WHEN bid_rate <= 0 THEN '0 이하'
    WHEN bid_rate > 0 AND bid_rate < 50 THEN '0 초과 50% 미만'
    WHEN bid_rate > 110 THEN '110% 초과'
    ELSE '유효(50% 이상 110% 이하)'
  END AS sample_status
  FROM joined
)
SELECT sample_status, COUNT(*) AS n
FROM classified
GROUP BY sample_status
ORDER BY sample_status
```

```text
계산 불가(기초금액 0 또는 NULL) = 7
0 이하 = 2
0 초과 50% 미만 = 5
110% 초과 = 1
유효(50% 이상 110% 이하) = 4999
```

분포 산출 질의는 조인 후 `r.sucsf_bid_amt / NULLIF(a.base_amount,0) * 100`을 계산하고 `BETWEEN 50 AND 110`으로 품질 제한한 뒤 `ROW_NUMBER()`와 `COUNT() OVER()`로 중앙값을 산출했습니다. 이 제한과 제외 건수는 3.1 절에 명시했으며, 원본 낙찰결과를 변경하거나 보정하지 않았습니다.
