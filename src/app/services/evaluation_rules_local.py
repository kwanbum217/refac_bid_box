"""
src/app/services/evaluation_rules_local.py

지방계약(LOCAL) 시·도 자체 별표 적격심사 규칙 레지스트리.
수요기관 시·도로 매칭하는 시·도 규칙과 구간별 배점 도우미를 담습니다.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from src.app.services.evaluation_rules_core import (
    QUANT_BASIS_AGENCY_DOCUMENT_NOT_LOADED,
    RULE_SCOPE_REGION,
    EvaluationRule,
    PriceBand,
    ThresholdBand,
)

# =============================================================================
# 지방계약(LOCAL) 시·도 자체 별표 규칙
# =============================================================================
#
# 정본: docs/design/local_regime_rules_design_20261005.md 0절(D8)·6.4절, 4절.
# 수집 원문: docs/analysis/servc_formula_collection_local_20261004.md 4.2~4.12절,
#           docs/analysis/servc_formula_userfiles_local_20261004.md,
#           docs/analysis/servc_formula_resolve_daegu_dapa_gg_20261005.md.
# 시·도 규칙은 낙찰방법명이 아니라 수요기관 시·도로 매칭하며, 조달청 별표를 후보에서 배제합니다.
# 행정안전부 예규 기본 규칙은 만들지 않습니다(0.1 D8). 시·도 규칙이 없으면 LOCAL_RULE_NOT_FOUND 입니다.
#
# B·k 는 price_bands(추정가격 3~4구간), T 는 threshold_bands(경계가 다를 수 있음)로 표현합니다.
# 모든 밴드의 기준비율은 88%(경기 별표 1-1 의 89 는 미확정이라 규칙을 만들지 않음)입니다.
#
# 단순노무 대표 낙찰하한율: 원문 산식이 전 구간 평점계수 20·기준비율 88 이고 통과점수가 95 인
# 지역(인천·제주·강원·서울·부산·대전·전북·울산·충북·경북)은 87.745 입니다. 대구는 원문이
# 87.745% 를 직접 인쇄합니다. 경기 별표 1-1·세종·경남·전남광주·충남 단순노무는 원문 산식이
# 확인되지 않아(미확인) 하한율을 바꾸지 않고 규칙도 만들지 않았습니다.
_LOCAL_COLLECTION = "docs/analysis/servc_formula_collection_local_20261004.md"

_SRC_INCHEON = (
    f"{_LOCAL_COLLECTION}:122-146 (인천광역시 일반용역 적격심사 세부기준, "
    "인천광역시 예규 제488호, 시행 2025-12-24, 별표 1); "
    "EXT/qual_raw/3.txt:170,314,457,600 (별표 1 1~4. 추정가격 구간별 입찰가격 평점산식)"
)
_SRC_INCHEON_20241204 = (
    "자치법규정보시스템(ELIS) https://www.elis.go.kr/allalr/selectAlrBdtOne?alrNo=28000032005015&histNo=007 "
    "(인천광역시 예규 제484호, 일부개정 2024-11-18, 시행 2024-12-04); "
    "인천광역시 계약정보공개시스템 게시글 https://www.incheon.go.kr/contract/CTRT050100/3061306 "
    "(첨부 HWP sha256 ed0ed1ae0a694bc12948a4e1c2895528788ab43a7c923ba7c84b7ab3189b7356); "
    "제5조 ① '종합평점이 추정가격 30억원 이상 용역은 85점 이상, 30억원 미만 10억원 이상인 용역은 "
    "90점 이상, 10억원 미만인 용역은 95점 이상'; 부칙 제1조 시행일 2024-12-04, 제2조 적용례 시행일 "
    "이후 최초 입찰공고; 별표 1 rows 7·38·69·99 (일반용역 4구간 B·k·기준비율 88·가격점수 고정 구간 "
    "상한 투찰률 98/90.5/89.25/88.25). 낙찰하한율은 원문 미인쇄, 계산값: base_rate 88%·통과점수"
    "(10억 미만 95, 10~30억 90)·평점산식으로 역산 (87.745/86.745/85.495/77.995)."
)
_SRC_JEJU = (
    f"{_LOCAL_COLLECTION}:148-173 (제주특별자치도 일반용역 적격심사 세부기준, "
    "제주특별자치도 예규 제82호, 시행 2024-01-01, 별표 1); "
    "EXT/qual_raw/6.txt:18,243,465,687 (별표 1 1~4. 추정가격 구간별 입찰가격 평점산식)"
)
_SRC_GANGWON = (
    f"{_LOCAL_COLLECTION}:175-200 (강원특별자치도 일반용역 적격심사 세부기준, "
    "강원특별자치도 예규 제832호, 시행 2023-06-11, 별표 1); "
    "EXT/qual_raw/1.txt:1996-2032 (참고 입찰가격 평점 산식 낙찰하한율 30억 이상 72.995%"
    "·10억 이상 77.995%), :150,307,463,618 (별표 1 1~4. 구간별 입찰가격 평점산식)"
)
_SRC_SEJONG = (
    f"{_LOCAL_COLLECTION}:225-247 (세종특별자치시 일반용역 적격심사 세부기준, "
    "세종특별자치시 예규 제32호, 시행 2025-12-01, 별표 2~5)"
)
_SRC_GB = (
    f"{_LOCAL_COLLECTION}:249-273 (경상북도 일반용역 등 적격심사 세부기준, "
    "경상북도 예규 제1571호, 시행 2026-01-08, 별표 1~4)"
)
_SRC_GB_20241212 = (
    "자치법규정보시스템 https://www.elis.go.kr/allalr/selectAlrBdtOne?alrNo=47000006006048&histNo=002 "
    "(경상북도 예규 제1568호, 시행 2024-12-12, 별표 1·5); "
    ".cache/gb_1568/att001 (별표 1-7 HWP) sha256 0f60839f893e3ea8a9b23db825274f2bcdd4c85c5dff22ad5c6aaf53ade55180; "
    "별표 5 폐기물처리(수집·운반, 처리)용역, 별표 1 일반용역 적격심사 세부기준. "
    "낙찰하한율은 원문 미인쇄, 계산값: base_rate 88%·통과점수(10억 미만 95, 10~30억 90, 30억 이상 85)·"
    "평점산식으로 역산 (87.745/86.745/85.495/77.995/72.995)."
)
_SRC_ULSAN = (
    f"{_LOCAL_COLLECTION}:275-306 (울산광역시 일반용역 적격심사 세부기준, "
    "울산광역시 공고 제2022-1100호, 시행 2022-08-10, 별표 1·1-1·2); "
    "EXT/ulsan/ulsan_general_20220810.tbl.txt:671-713 "
    "(참고 입찰가격 평점 산식의 낙찰하한율)"
)
_SRC_CB = (
    f"{_LOCAL_COLLECTION}:308-333 (충청북도 일반용역 적격심사 세부기준, "
    "충청북도 공고 제2023-1428호, 시행 2023-10-20, 별표 1); "
    "EXT/cb/cb_cjuc.txt:1454-1659 (별표 1 3. 입찰가격 평가의 낙찰하한율)"
)
_SRC_JNGJ = (
    f"{_LOCAL_COLLECTION}:335-371 (전남광주통합특별시 일반용역 적격심사 세부지침, "
    "전남광주통합특별시 예규 제3호, 시행 2026-07-16, 별표 1~6); "
    "EXT/jn_gj/jngj_att001.hwp.tbl.txt:47-69, EXT/jn_gj/jngj_att002.hwp.tbl.txt:52-74, "
    "EXT/jn_gj/jngj_att003.hwp.tbl.txt:53-75, EXT/jn_gj/jngj_att004.hwp.tbl.txt:46-60, "
    "EXT/jn_gj/jngj_att005.hwp.tbl.txt:48-70, EXT/jn_gj/jngj_att006.hwp.tbl.txt:9-93 "
    "(별표 1~6 입찰가격 평가의 낙찰하한율)"
)
_SRC_GN = (
    f"{_LOCAL_COLLECTION}:373-394 (경상남도 일반용역 등 적격심사 세부기준, "
    "경상남도 공고 제2023-23호, 시행 2023-01-05, 별표 1); "
    "EXT/qual_raw/5.txt:54,300,548,794 (별표 1 1~4. 추정가격 구간별 입찰가격 평점산식)"
)
_SRC_DAEGU = (
    f"{_LOCAL_COLLECTION}:202-223 (대구광역시 일반용역 적격심사 세부기준, "
    "대구광역시 예규 제238호, 시행 2026-05-11, 별표 1 단순노무); "
    "EXT/daegu/tbl1_daegu.txt:150 (최저 낙찰하한율 87.745%), "
    "EXT/supplement/daegu/R25BK01157938_f1.txt:47 (공고문 낙찰하한율 87.745%)"
)
_SRC_DAEGU_20220930 = (
    "data/sources/qualification/files/daegu/560b82365946_대구광역시 일반용역 적격심사세부기준(대구광역시예규제223호_2022.9.30).pdf "
    "(sha256 560b82365946fb006c5ba282a779198d62fc69ce5ceed80d103653d1bcdd5c47); "
    "ELIS 대구광역시 일반용역 적격심사 세부기준 [시행 2022.09.30] (예규 제223호) 부칙 제1조 시행일 2022-09-30, "
    "제2조 적용례 시행일 이후 입찰공고; "
    "별표 1 단순노무: data/sources/qualification/files/daegu/a15ebda73ce5_byp1.txt:16 (최저 낙찰하한율 87.745%); "
    "별표 4 폐기물: 제238호 ELIS 첨부 HWP(7560ea7a)와 동일 값, 낙찰하한율 원문 미인쇄 계산값 80.495%; "
    "지역제한 금액은 행안부 고시 변수이며 광주·전남 구판 관례대로 5억원으로 등록, 광역 본청·소속기관 3.3억/3.5억 분리는 하지 않음; "
    "원문 정의 조항: '폐기물처리용역 … 이 경우 건설폐기물 처리용역은 제외한다' (856673076d70_elis_daegu_main.txt); "
    "낙찰하한율 계산식: B70: 85-30=55, 70-2x>=55, x<=7.5 / B60: 85-40=45, 60-2x>=45, x<=7.5 → 88-7.5=80.5"
)
_SRC_DAEGU_ATTACH_04 = (
    "data/sources/qualification/files/daegu/7560ea7a13d3_[별표 4] 폐기물처리용역 적격심사 평가기준.hwp "
    "(sha256 7560ea7a13d3ef8e6e13a86b38310c0153348373e670c57646c7befc7ed426e0); "
    "ELIS 대구광역시 일반용역 적격심사 세부기준 [시행 2026.05.11] (예규 제238호) 제4조① 4, 제8조, 제12조④; "
    "별표 4 표: 입찰가격 배점한도 지역제한 금액 이상 60·미만 70, 평점산식 k=2·기준비율 88, "
    "고정 상한 투찰률 95.5%, 통과점수 85; 낙찰하한율 원문 미인쇄, 계산값 80.495; "
    "지역제한 금액은 행안부 고시 변수이며 광주·전남 구판 관례대로 5억원으로 등록, 광역 본청·소속기관 3.3억/3.5억 분리는 하지 않음; "
    "원문 정의 조항: '폐기물처리용역 … 이 경우 건설폐기물 처리용역은 제외한다' (856673076d70_elis_daegu_main.txt); "
    "낙찰하한율 계산식: B70: 85-30=55, 70-2x>=55, x<=7.5 / B60: 85-40=45, 60-2x>=45, x<=7.5 → 88-7.5=80.5"
)
_SRC_GG = (
    f"{_LOCAL_COLLECTION}:396-463 (경기도 일반용역 적격심사 세부기준 지침, "
    "경기도 예규 제748호, 시행 2025-08-08, 별표 1-2~1-6); "
    "EXT/gg/gg_g2b_20251210_coord.txt:337-455 (별표 1-2), "
    "EXT/gg/gg_g2b_20251210_coord.txt:456-572 (별표 1-3), "
    "EXT/gg/gg_g2b_20251210_coord.txt:573-672 (별표 1-4), "
    "EXT/gg/gg_g2b_20251210_coord.txt:733-843 (별표 1-6) "
    "(입찰가격 평점 산식의 낙찰하한율)"
)
# 경기 별표 1-5 보험용역은 원문에 낙찰하한율 열이 없고 평점산식(계수 0.375)만 인쇄됩니다.
# 배점한도는 5억원 미만 70·5억원 이상 60(coord:684-685)이고 제8조 통과점수는 85(:169)라
# 88 - (100 - 85) / 0.375 = 48.0 → 47.995% 로, 조달청 보험용역 INSURANCE 기본값과 값·산식이
# 같습니다. 2026-10-13 원문 산식 역산으로 확인했습니다.
_SRC_GG_INSURANCE = (
    f"{_SRC_GG}; 별표 1-5 보험용역 coord:676-728 "
    "(B 5억원 미만 70·5억원 이상 60, 계수 0.375), 제8조 :169 통과점수 85 "
    "(원문 산식 역산 47.995%)"
)

# 2단계 추가 5곳(서울·부산·대전·충남·전북)의 원문 근거는 별도 재수집 문서와 이 워크트리의
# EXT/ 추출물입니다. 값이 의심스러우면 EXT 원문 행을 직접 대조합니다.
_SRC_RECOVER = "docs/analysis/servc_formula_recover_c_20261005.md"
_SRC_SEOUL = (
    f"{_SRC_RECOVER}:76-103 (서울특별시 일반용역 적격심사 세부기준, 시행 2024-08-12, "
    "별표 1~4); EXT/seoul/seoul_general_2024_08_12.tbl.txt:"
    "32,35-37,369-384,712-727,1055-1070,1308-1323"
)
# 서울 별표 1~4 구간별 하한율은 원문에 열로 인쇄되지 않지만 평점산식과 통과점수에서 닫힙니다.
# 하한율 = 88 - (100 - 통과점수) / 평점계수 이고, 소수 셋째 자리 .995 표기 관행을 따릅니다.
# 통과점수는 30억원 이상 85·10억~30억 90·10억원 미만 95(제7조 :32)이고, 평점계수는 단순노무 외
# 10억원 이상 1(:379)·10억~5억 2(:722)·5억~2억 4(:1065)·2억원 미만 20(:1318), 단순노무 전 구간
# 20(:381,724,1067,1320)입니다. 2026-10-13 역산값이 종전 공고 실측 최빈값과 모두 일치합니다.
_SRC_SEOUL_LWLT_FORMULA = (
    "원문 산식 역산 (하한율 = 88 - (100 - 통과점수) / 평점계수, .995 표기): "
    "제7조 :32 (30억원 이상 85, 10억~30억 90, 10억원 미만 95), "
    "평점산식 :379(k 1), :722(k 2), :1065(k 4), :1318(k 20)"
)
_SRC_BUSAN = (
    f"{_SRC_RECOVER}:105-132 (부산광역시 일반용역 적격심사 세부기준, 공고 제2025-1981호, "
    "시행 2025-06-26, 별표 1); EXT/busan/busan_general_2025_1981.txt:57,82-84,149-150 "
    "(149 입찰가격 평가: 단순노무 외 10억원 이상 30억원 미만 77.995%, 30억원 이상 72.995%; "
    "단순노무 87.745%)"
)
_SRC_DAEJEON = (
    f"{_SRC_RECOVER}:134-168 (대전광역시 일반용역 적격심사 세부기준, 공고 제2025-9528호, "
    "시행 2026-01-01, 별표 6); EXT/daejeon/daejeon_2025_9528.txt:39,68-71,260-265 "
    "(262 입찰가격 평가: 소프트웨어·폐기물·기타 일반용역 10억원 이상 30억원 미만 77.995%, "
    "30억원 이상 72.995%; 청소·시설물경비·시설물관리 87.745%)"
)
_SRC_DAEJEON_20240120 = (
    "대전광역시 공고 제2024-2호, 시행 2024-01-20, 대전광역시 고시공고 게시글 "
    "https://www.daejeon.go.kr/drh/drhGosiView.do?gosigbn=A&sno=45050&menuSeq=1908&pageIndex=1 "
    "첨부 HWP, sha256 05f8bd0b2f03f9515b35a5cba23fee90209cd707082d6da763dd4be1db97423f; "
    "EXT/daejeon/daejeon_2024_2.hwp (별표 6)"
)
_SRC_CHUNGNAM_ATTACH_01 = (
    f"{_SRC_RECOVER}:170-202 (충청남도 일반용역 적격심사 세부기준, 공고 2026-1235호, "
    "시행 2026-07-13, 별표 1 시설분야용역); EXT/chungnam/chungnam_2026_1235.txt:"
    "457-459,481-483,487,551-560; EXT/chungnam/chungnam_tables.txt:2-18"
)
_SRC_CHUNGNAM_ATTACH_2_1 = (
    f"{_SRC_RECOVER}:170-202 (충청남도 일반용역 적격심사 세부기준, 별표 2의1 정보통신 "
    "중소기업자간 경쟁제품 대상); EXT/chungnam/chungnam_2026_1235.txt:"
    "457-459,481-483,1121,1172-1180; EXT/chungnam/chungnam_tables.txt:47-63"
)
_SRC_CHUNGNAM_ATTACH_05 = (
    f"{_SRC_RECOVER}:170-202 (충청남도 일반용역 적격심사 세부기준, 별표 5 해양환경관리 "
    "및 어장관리용역); EXT/chungnam/chungnam_2026_1235.txt:"
    "193,457-459,481-483,2248,2334-2366; EXT/chungnam/chungnam_tables.txt:137-158"
)
# 충남 별표 2·3·4(정보통신·폐기물처리·육상운송)는 배점 B 가 추정가격 5억원 축(미만 70·이상 60)이고
# 계수 k·기준비율·낙찰하한율이 고시금액 축(미만 k4·84.245% / 이상 k2·80.495%)이라 한 행에 결합
# 인쇄되지 않습니다. 2026-10-08 HWPX 원문 격자 검토(3.3·3.4절)와 2026-10-09 재검증(2절 3·14·
# 21행)으로 계층 분리가 확정되어, 두 경계를 합친 3구간으로 등록합니다.
_SRC_CHUNGNAM_HWPX = "docs/analysis/qual_chungnam_2026_1235_hwpx_20261008.md"
_SRC_CHUNGNAM_HWPX_REVIEW = "docs/analysis/qual_chungnam_2026_1235_hwpx_review_20261009.md"
_SRC_CHUNGNAM_ATTACH_02 = (
    f"{_SRC_CHUNGNAM_HWPX}:74-97 (충청남도 일반용역 적격심사 세부기준, 공고 2026-1235호, "
    "시행 2026-07-13, 별표 2 정보통신용역; 3.3 낙찰하한율·평점산식, 3.4 별표별 축 정리: "
    "고시금액 미만 k=4·84.245%, 고시금액 이상 k=2·80.495%, 배점 5억원 미만 70·이상 60); "
    f"{_SRC_CHUNGNAM_HWPX_REVIEW}:53,64,71 (원문 격자 재검증 일치)"
)
_SRC_CHUNGNAM_ATTACH_03 = (
    f"{_SRC_CHUNGNAM_HWPX}:74-97 (충청남도 일반용역 적격심사 세부기준, 공고 2026-1235호, "
    "시행 2026-07-13, 별표 3 폐기물처리용역; 3.3·3.4, 별표 2 와 같은 산식: "
    "고시금액 미만 k=4·84.245%, 고시금액 이상 k=2·80.495%, 배점 5억원 미만 70·이상 60); "
    f"{_SRC_CHUNGNAM_HWPX_REVIEW}:53,64,71 (원문 격자 재검증 일치)"
)
_SRC_CHUNGNAM_ATTACH_04 = (
    f"{_SRC_CHUNGNAM_HWPX}:74-97 (충청남도 일반용역 적격심사 세부기준, 공고 2026-1235호, "
    "시행 2026-07-13, 별표 4 육상운송용역; 3.3·3.4, 별표 2 와 같은 산식: "
    "고시금액 미만 k=4·84.245%, 고시금액 이상 k=2·80.495%, 배점 5억원 미만 70·이상 60); "
    f"{_SRC_CHUNGNAM_HWPX_REVIEW}:53,64,71 (원문 격자 재검증 일치)"
)
_SRC_CHUNGNAM_20200201 = (
    "신·구 대비표 HWPX .cache/chungnam_2019/singu.hwpx (충청남도 일반용역 적격심사 세부기준, "
    "공고 제2019-2047호, 행정안전부 협의 2019. 12. 20., sha256 "
    "11c48edac4f7e4233ab5cc0939d59992691d62ba4ec3c86ead1447e70cae368e, 325333 bytes); "
    "비교표 최상위 셀 colAddr=0 이 구판(공고 2019-2047호) 열, colAddr=1 이 개정(2026-1235호) 열. "
    "부칙(colAddr=0): '행정안전부장관 협의 완료 후 2020년 2월 1일 입찰공고부터 적용한다.' "
    "별표 1 시설(colAddr=0; [별표 1] offset 8478; B '60 70' offset 8501): 추정가격 5억원 미만/이상, "
    "B 70/60, k 5, 기준비율 91%, 통과점수 85, 평탄 상한 94%, 낙찰하한율 원문 미인쇄, 계산값 87.995%. "
    "별표 3 폐기물(colAddr=0; [별표 3] offset 16027; B '60 70' offset 16051; "
    "hp:equation offset 16293·16512): B 5억원 미만/이상 70/60, k 고시금액 미만 4/이상 2, "
    "기준비율 88%, 통과점수 85, 평탄 상한 91.75%/95.5%, 낙찰하한율 원문 미인쇄, 계산값 84.245%/80.495%. "
    "별표 4 육상운송(colAddr=0; [별표 4] offset 19296; B '60 70' offset 19319; "
    "hp:equation offset 19919·19763): 별표 3 과 같은 값. "
    "낙찰하한율은 원문 미인쇄, 계산값: 통과점수와 평점산식으로 역산."
)
_SRC_JEONBUK = (
    f"{_SRC_RECOVER}:204-230 (전북특별자치도 일반용역 적격심사 세부기준, 부칙 제2024-10호, "
    "시행 2024-01-18, 별표 1); EXT/jeonbuk/jb_general_2024_10.tbl.txt:"
    "35-37,44-49,127-145,357-366,583-592,792-799 "
    "(138-145 입찰가격 평가: 단순노무 외 10억원 이상 30억원 미만 77.995%, 30억원 이상 "
    "72.995%; 단순노무 87.745%; 구간 하한율 숫자 행 141, 143, 145, 369, 595, 802)"
)

# 통합특별시 출범 전 옛 전라남도 기준입니다. 통합 지침(예규 제3호) 시행일 2026-07-16 이전 공고에만
# 적용하는 구판 별표이고, 원문은 자치법규정보시스템 전라남도 일반용역 적격심사 세부기준
# 예규 제1075호(시행 2023-03-02)와 그 별표 4·5 첨부(HWP)입니다. 같은 주소의 histNo=001 은
# 2015-10-01 예규 제1050호라 값이 다릅니다(2026-10-17 확인).
_JEONNAM_ELIS_RULE = (
    "자치법규정보시스템 https://www.elis.go.kr/allalr/selectAlrBdtOne"
    "?alrNo=46000007006065&histNo=005 (전라남도 일반용역 적격심사 세부기준, "
    "전라남도 예규 제1075호, 시행 2023-03-02)"
)
_SRC_JEONNAM_ATTACH_4_1_4 = (
    f"{_JEONNAM_ELIS_RULE}; 별표 4 폐기물처리용역 적격심사 "
    "1. 심사항목 및 배점한도 (Ⅱ. 입찰가격 5억원 이상 30·5억원 미만 1억원 이상 80·"
    "1억원 미만 90, 합계 100), 4. 입찰가격 평점산식[별표 4-1-4] "
    "(5억원 이상 평점 = 30 - 1 * |88 - 입찰가격/예정가격 * 100|, 5억원 미만 1억원 이상 "
    "평점 = 80 - 20 * |...|, 1억원 미만 평점 = 90 - 20 * |...|), "
    "주 2) 투찰률 93% 이상 25점·88.25% 이상 75점·88.25% 이상 85점; "
    "본문 제7조 ① 통과점수 (30억원 이상 85·30억원 미만 10억원 이상 90·10억원 미만 95); "
    "낙찰하한율은 원문 미인쇄라 평점산식·통과점수 역산 "
    "(하한율 = 88 - (100 - 통과점수) / 평점계수, .995 표기): 1억원 미만·5억원 미만 1억원 이상 "
    "87.745, 5억원 이상 10억원 미만 82.995, 10억원 이상 30억원 미만 77.995, "
    "30억원 이상 72.995"
)
_SRC_JEONNAM_ATTACH_5_1_4 = (
    f"{_JEONNAM_ELIS_RULE}; 별표 5 육상운송용역 적격심사 "
    "1. 심사항목 및 배점한도 (Ⅱ. 입찰가격 5억원 이상 60·5억원 미만 80, 합계 100), "
    "7. 입찰가격 평점산식[별표 5-1-4] (5억원 이상 평점 = 60 - 2 * |88 - 입찰가격/예정가격 "
    "* 100|, 5억원 미만 평점 = 80 - 2 * |...|), "
    "주 2) 투찰률 90.5% 이상은 90.5%인 경우의 점수로 평가; "
    "본문 제7조 ① 통과점수 (30억원 이상 85·30억원 미만 10억원 이상 90·10억원 미만 95); "
    "낙찰하한율은 원문 미인쇄라 평점산식·통과점수 역산 "
    "(하한율 = 88 - (100 - 통과점수) / 평점계수, .995 표기): 5억원 미만·5억원 이상 10억원 미만 "
    "85.495, 10억원 이상 30억원 미만 82.995, 30억원 이상 80.495"
)
_SRC_JEONNAM_ATTACH_1_1_4 = (
    f"{_JEONNAM_ELIS_RULE}; 별표 1 시설분야용역 적격심사 "
    "1. 심사항목 및 배점한도 (Ⅱ. 입찰가격 5억원 이상 50·5억원 미만 70, 합계 100), "
    "7. 입찰가격 평점산식 (5억원 이상 평점 = 50 - 20 * |88 - 입찰가격/예정가격 * 100|, "
    "5억원 미만 평점 = 70 - 20 * |...|), "
    "주 2) 입찰가격이 예정가격 이하로서 예정가격의 100분의 88.25 이상인 경우 입찰가격이 "
    "예정가격의 100분의 88.25인 경우의 점수로 평가; "
    "본문 제7조 ① 통과점수 (30억원 이상 85·30억원 미만 10억원 이상 90·10억원 미만 95); "
    "낙찰하한율은 원문 미인쇄라 평점산식·통과점수 역산 "
    "(하한율 = 88 - (100 - 통과점수) / 평점계수, .995 표기): 10억원 미만 87.745, "
    "10억원 이상 30억원 미만 87.495, 30억원 이상 87.245"
)

# 광주광역시 구판 (예규 제377호, 시행 2022-11-15) — 통합 지침 이전 공고 전용.
# 통합 지침 시행일(2026-07-16) 이후 공고는 JNGJ 규칙이 쓰이고, 그 이전 공고는 같은
# 세부유형의 이 구판 규칙이 쓰입니다. region_code "29" 로 두고 superseded_date 2026-07-16.
_GWANGJU_ELIS_RULE = (
    "자치법규정보시스템 https://www.elis.go.kr/allalr/selectAlrBdtOne"
    "?alrNo=29000068001145&histNo=007 (광주광역시 일반용역 적격심사 세부 기준, "
    "광주광역시 예규 제377호, 시행 2022-11-15)"
)
_SRC_GWANGJU_ATTACH_1_3 = (
    f"{_GWANGJU_ELIS_RULE}; 별표 1-3 폐기물처리용역 적격심사 "
    "1. 심사항목 및 배점한도 (Ⅱ. 입찰가격 지역제한 금액 이상 30·"
    "지역제한 금액 미만~1억원 이상 80·1억원 미만 90, 합계 100), "
    "별표 6 폐기물 행 (평점 = 30 - 1x|88 - 투찰율| / 80 - 20x|...| / 90 - 20x|...|), "
    "제11조제1항 통과점수 95; "
    "낙찰하한율 원문 병기 82.995·87.745·87.745"
)
_SRC_GWANGJU_ATTACH_1_5 = (
    f"{_GWANGJU_ELIS_RULE}; 별표 1-5 육상운송용역 적격심사 "
    "1. 심사항목 및 배점한도 (Ⅱ. 입찰가격 지역제한 금액 이상 60·"
    "지역제한 금액 미만 70, 합계 100), "
    "별표 6 육상운송 행 (평점 = 60 - 2x|88 - 투찰율| / 70 - 2x|...|), "
    "제11조제1항 통과점수 95; "
    "낙찰하한율 원문 병기 85.495·85.495"
)

# 세종 별표 3(소프트웨어)·별표 5(육상운송)는 같은 별표 안에서 중소기업자간 경쟁제품
# 대상/비대상 여부로 k·낙찰하한율·통과점수가 갈립니다(별표 분리가 아니라 조건 분기).
# 출처는 코디네이터가 확인한 원문 추출 파일의 행 번호입니다.
_SRC_SEJONG_EXT = ".orca/capsules/task_58ea8ddab6fb/external/sejong"
_SRC_SEJONG_SW_NON_TARGET = (
    f"{_SRC_SEJONG}; 원문 {_SRC_SEJONG_EXT}/byp3_sw_2025.txt:16-23 "
    "(가. 중소기업간 경쟁제품 비대상 입찰가격 평점산식 80.495%), "
    f"{_SRC_SEJONG_EXT}/byp3_sw_2025.tbl.txt:10 (B 5억원 이상 60·5억원 미만 70), "
    f":14 (k 2), {_SRC_SEJONG_EXT}/sejong_body_2025.txt:108 (비대상 T 85)"
)
_SRC_SEJONG_SW_TARGET = (
    f"{_SRC_SEJONG}; 원문 {_SRC_SEJONG_EXT}/byp3_sw_2025.txt:24-31 "
    "(나. 중소기업간 경쟁제품 대상 입찰가격 평점산식 84.995%), "
    f"{_SRC_SEJONG_EXT}/byp3_sw_2025.tbl.txt:10 (B 5억원 이상 60·5억원 미만 70), "
    f":17 (k 4), {_SRC_SEJONG_EXT}/sejong_body_2025.txt:108 (대상 T 88)"
)
_SRC_SEJONG_LT_NON_TARGET = (
    f"{_SRC_SEJONG}; 원문 {_SRC_SEJONG_EXT}/byp5_2025.txt:19-26 "
    "(가. 중소기업간 경쟁제품 비대상 입찰가격 평점산식 80.495%), "
    f"{_SRC_SEJONG_EXT}/byp5_2025.tbl.txt:10 (B 5억원 이상 60·5억원 미만 70), "
    f":20 (k 2), {_SRC_SEJONG_EXT}/sejong_body_2025.txt:108 (비대상 T 85)"
)
_SRC_SEJONG_LT_TARGET = (
    f"{_SRC_SEJONG}; 원문 {_SRC_SEJONG_EXT}/byp5_2025.txt:27-34 "
    "(나. 중소기업간 경쟁제품 대상 입찰가격 평점산식 84.995%), "
    f"{_SRC_SEJONG_EXT}/byp5_2025.tbl.txt:10 (B 5억원 이상 60·5억원 미만 70), "
    f":23 (k 4), {_SRC_SEJONG_EXT}/sejong_body_2025.txt:108 (대상 T 88)"
)
# 시설·폐기물·생활폐기물 별표는 전 구간 단일 낙찰하한율을 인쇄합니다.
_SRC_SEJONG_FACILITY = f"{_SRC_SEJONG}; EXT/sejong/byp2_2025.txt:31 (별표 2 시설 전 구간 87.745%)"
_SRC_SEJONG_WASTE = f"{_SRC_SEJONG}; EXT/sejong/byp4_2025.txt:18 (별표 4 폐기물 전 구간 87.745%)"
_SRC_SEJONG_WASTE_HOUSEHOLD = (
    f"{_SRC_SEJONG}; EXT/sejong/byp4_2_2025.txt:11 (별표 4의2 생활폐기물 전 구간 87.745%)"
)

# 경상북도 별표 4(기타 일반용역) 원문. 5억원 기준 두 구간만 인쇄하므로 5억 경계로 값을 가릅니다.
_SRC_GB_ATTACH_04 = (
    f"{_SRC_GB}; EXT/gb/gb_byp004.tbl.txt:9,12 "
    "(별표 4 기타 일반용역 Ⅲ.입찰가격: 5억원 이상 평점 50-4x|88-투찰률| 89.25% 이상 45점, "
    "5억원 미만 평점 70-20x|88-투찰률| 88.25% 이상 65점)"
)
# 2026-10-05 공고 실측: 자치법규 원문이 낙찰하한율을 인쇄하지 않은 규칙의 10억원 미만 구간
# 최빈값입니다. 자치법규 원문이 인쇄한 값이 아니므로 원문 확인값으로 표기하지 않습니다.
# 2026-10-06 부로 이 실측 헬퍼는 서울특별시 GENERAL(10억원 이상 30억원 분할) 전용입니다.
_SRC_LWLT_MEASURED = (
    "docs/analysis/local_lwlt_announcement_measure_20261005.md:225-235 "
    "6.1 공고 실측 최빈값, 자치법규 원문 미확인"
)
# 구간 순서는 (2억원 미만, 5억원 미만, 10억원 미만, 10억원 이상)입니다. 10억원 이상은
# 값을 비워 두어 규칙 대표값(EvaluationRule.lwlt_rate)을 쓰게 합니다.
_MEASURED_LWLT_UNDER_1B: tuple[str | None, str | None, str | None, str | None] = (
    "87.745",
    "86.745",
    "85.495",
    None,
)

_LOCAL_NOT_FOUND_MESSAGE = (
    "해당 지자체의 일반용역 적격심사 기준이 아직 확보되지 않았습니다. "
    "가격배점한도(B)·평점계수(k)·기준비율·통과점수를 직접 입력하면 가격점수를 계산합니다."
)

# 시·도별 기본 낙찰하한율은 그 별표에 대응하는 조달청 관행 하한율을 기본값으로 둡니다.
# 공고에 sucsfbidLwltRate 가 있으면 공고값이 우선합니다(현행과 동일).
_LOCAL_LWLT_BY_SERVICE: dict[str, str] = {
    "FACILITY": "87.995",
    "INSURANCE": "47.995",
    "LAND_TRANSPORT": "87.995",
    "LAND_TRANSPORT_SME": "84.995",
    "SW": "87.995",
    "SW_SME": "84.995",
    "WASTE": "84.245",
    "WASTE_HOUSEHOLD": "84.245",
    "REPAIR_INSPECTION": "84.245",
    "LEASE": "84.245",
    "GENERAL": "87.995",
    "SIMPLE_LABOR": "87.995",
    "FISHERY_CLEANUP": "87.995",
}


def _local_price_band(
    upper: str | None,
    b: str,
    k: str,
    label: str,
    source: str,
    base_rate: str = "0.88",
    lwlt_rate: str | None = None,
) -> PriceBand:
    return PriceBand(
        upper_bound=Decimal(upper) if upper is not None else None,
        max_price_score=Decimal(b),
        multiplier=Decimal(k),
        base_rate=Decimal(base_rate),
        label=label,
        source=source,
        lwlt_rate=Decimal(lwlt_rate) if lwlt_rate is not None else None,
    )


def _local_threshold_band(upper: str | None, t: str, label: str, source: str) -> ThresholdBand:
    return ThresholdBand(
        upper_bound=Decimal(upper) if upper is not None else None,
        pass_threshold=Decimal(t),
        label=label,
        source=source,
    )


def _four_band_price(
    source: str,
    *,
    simple_labor: bool = False,
    lwlt_rates: tuple[str | None, str | None, str | None, str | None] | None = None,
) -> tuple[PriceBand, ...]:
    """10억/5억/2억 4구간 B·k. 단순노무 행은 k 가 전 구간 20 입니다.

    lwlt_rates 를 주면 구간 순서(2억 미만, 5억 미만, 10억 미만, 10억 이상)대로 인쇄된
    낙찰하한율을 덧붙입니다. 원문이 구간 하나에 값을 확정하지 못하는 자리는 None 으로
    두어 규칙 대표값을 쓰게 합니다.
    """
    k_top = "20" if simple_labor else "1"
    k_10 = "20" if simple_labor else "2"
    k_5 = "20" if simple_labor else "4"
    bands = (
        _local_price_band("200000000", "90", "20", "추정가격 2억원 미만", source),
        _local_price_band("500000000", "70", k_5, "5억원 미만 2억원 이상", source),
        _local_price_band("1000000000", "50", k_10, "10억원 미만 5억원 이상", source),
        _local_price_band(None, "30", k_top, "추정가격 10억원 이상", source),
    )
    if lwlt_rates is None:
        return bands
    return tuple(
        replace(band, lwlt_rate=Decimal(rate) if rate is not None else None)
        for band, rate in zip(bands, lwlt_rates, strict=True)
    )


def _measured_lwlt_four_band_price(source: str) -> tuple[PriceBand, ...]:
    """10억원 미만 3개 구간에 공고 실측 하한율을 붙인 10억/5억/2억 4구간.

    2026-10-06 부로 서울특별시 GENERAL(10억원 이상 30억원 분할) 전용입니다. 구간 하한율을
    붙인 구간의 source 는 자치법규 원문이 아니라 공고 실측임을 함께 밝히고, 10억원 이상 구간은
    값을 비워 규칙 대표값(EvaluationRule.lwlt_rate)을 그대로 쓰게 합니다. 이 헬퍼를 쓰지 않는
    다른 규칙의 구간은 종전과 같습니다.
    """
    bands = _four_band_price(source, lwlt_rates=_MEASURED_LWLT_UNDER_1B)
    return tuple(
        replace(band, source=f"{source}; {_SRC_LWLT_MEASURED}")
        if band.lwlt_rate is not None
        else band
        for band in bands
    )


# 서울 GENERAL 전용 30억원 분할. 별표 1~4 평점산식과 제7조 통과점수를 역산하면 10억원 이상
# 구간이 30억원 경계로 77.995/72.995 로 갈려 서울은 원문 산식 역산으로 5구간을 만듭니다.
# 구간 라벨은 원문 구간 표기를 따르고, B·k·기준비율은 분할 전 10억원 이상 구간 값
# (B 30·k 1·0.88) 그대로입니다. (인천·제주·강원·경남은 같은 30억 분할을 _five_band_price 로
# 원문 산식 역산값으로 씁니다.)
_SEOUL_TOP_LWLT_RATES: tuple[str, str] = ("77.995", "72.995")


def _seoul_five_band_price(source: str) -> tuple[PriceBand, ...]:
    """서울 GENERAL 전용 5구간. 10억원 이상을 30억원 경계로 나눠 역산 하한율을 붙입니다.

    10억원 미만 3구간은 _four_band_price 가 정한 B·k 를 그대로 쓰고 값만 채우며, 10억원 이상은
    분할 전 값(B 30·k 1·기준비율 0.88)을 유지한 채 두 구간으로 나눕니다. 구간 하한율은 원문에
    열로 인쇄되지 않고 별표 1~4 평점산식·제7조 통과점수 역산값이며, 모든 구간의 source 에 그
    근거를 함께 밝힙니다. 공유 헬퍼(_four_band_price·_measured_lwlt_four_band_price)는 그대로
    두고 구간 구조만 재사용합니다.
    """
    band_source = f"{source}; {_SRC_SEOUL_LWLT_FORMULA}"
    bands = tuple(
        replace(band, source=band_source) for band in _measured_lwlt_four_band_price(source)
    )
    under_30 = replace(
        bands[-1],
        upper_bound=Decimal("3000000000"),
        label="30억원 미만 10억원 이상",
        lwlt_rate=Decimal(_SEOUL_TOP_LWLT_RATES[0]),
    )
    over_30 = _local_price_band(
        None,
        "30",
        "1",
        "추정가격 30억원 이상",
        band_source,
        lwlt_rate=_SEOUL_TOP_LWLT_RATES[1],
    )
    return (*bands[:-1], under_30, over_30)


def _five_band_price(
    source: str,
    *,
    lwlt_rates: tuple[str | None, str | None, str | None, str | None, str | None] | None = None,
) -> tuple[PriceBand, ...]:
    """10억원 이상을 30억원 경계로 나눈 5구간 B·k.

    부산·대전·전북·울산·충북 일반 띠와 전남광주 어장정화 띠가 씁니다.
    원문은 10억원 이상 행을 30억원 미만 77.995%, 30억원 이상 72.995% 로 나눠 인쇄합니다.
    B·k·기준비율은 나눈 두 구간 모두 10억원 이상 값(B 30·k 1·0.88)입니다. 서울 등 나머지
    시·도는 이 분할이 없어 기존 _four_band_price 를 그대로 씁니다.
    lwlt_rates 순서는 (2억원 미만, 5억원 미만, 10억원 미만, 30억원 미만, 30억원 이상)입니다.
    """
    bands = (
        _local_price_band("200000000", "90", "20", "추정가격 2억원 미만", source),
        _local_price_band("500000000", "70", "4", "5억원 미만 2억원 이상", source),
        _local_price_band("1000000000", "50", "2", "10억원 미만 5억원 이상", source),
        _local_price_band("3000000000", "30", "1", "30억원 미만 10억원 이상", source),
        _local_price_band(None, "30", "1", "추정가격 30억원 이상", source),
    )
    if lwlt_rates is None:
        return bands
    return tuple(
        replace(band, lwlt_rate=Decimal(rate) if rate is not None else None)
        for band, rate in zip(bands, lwlt_rates, strict=True)
    )


def _chungnam_notice_band_price(source: str) -> tuple[PriceBand, ...]:
    """충남 별표 2·3·4 의 두 축 결합 3구간 B·k·기준비율·하한율.

    배점 B 는 추정가격 5억원 축(미만 70·이상 60)이고 계수 k·기준비율·낙찰하한율은 고시금액
    축(미만 k4·84.245% / 이상 k2·80.495%)이라 한 행에 결합 인쇄되지 않습니다. 두 경계를
    합치면 상한 230000000(고시금액 2026 값)·500000000·없음 세 구간이 됩니다.
    """
    return (
        _local_price_band(
            "230000000", "70", "4", "추정가격 고시금액 미만", source, lwlt_rate="84.245"
        ),
        _local_price_band(
            "500000000", "70", "2", "5억원 미만 고시금액 이상", source, lwlt_rate="80.495"
        ),
        _local_price_band(None, "60", "2", "추정가격 5억원 이상", source, lwlt_rate="80.495"),
    )


def _threshold_30_10(source: str) -> tuple[ThresholdBand, ...]:
    """30억/10억 경계 T: 30억↑85, 10억~30억90, ~10억95."""
    return (
        _local_threshold_band("1000000000", "95", "추정가격 10억원 미만", source),
        _local_threshold_band("3000000000", "90", "30억원 미만 10억원 이상", source),
        _local_threshold_band(None, "85", "추정가격 30억원 이상", source),
    )


def _single_threshold(value: str, label: str, source: str) -> tuple[ThresholdBand, ...]:
    return (_local_threshold_band(None, value, label, source),)


def _local_rule(
    rule_id: str,
    *,
    sido_code: str,
    sido_name: str,
    service_type: str,
    effective_date: str,
    source: str,
    price_bands: tuple[PriceBand, ...],
    threshold_bands: tuple[ThresholdBand, ...],
    description: str,
    lwlt_rate: str | None = None,
    base_rate: str = "0.88",
    superseded_date: str | None = None,
    bounded_price_top: bool = False,
    cdw_exclusion: str | None = None,
) -> EvaluationRule:
    return EvaluationRule(
        rule_id=rule_id,
        service_type=service_type,
        table_name=f"{sido_name} 일반용역 적격심사 ({service_type})",
        description=description,
        effective_date=effective_date,
        superseded_date=superseded_date,
        bounded_price_top=bounded_price_top,
        cdw_exclusion=cdw_exclusion,
        source=source,
        patterns=(),
        lwlt_rate=Decimal(lwlt_rate or _LOCAL_LWLT_BY_SERVICE[service_type]),
        base_rate=Decimal(base_rate),
        price_bands=price_bands,
        threshold_bands=threshold_bands,
        quant_basis=QUANT_BASIS_AGENCY_DOCUMENT_NOT_LOADED,
        score_table_source=source,
        contract_regime="LOCAL",
        institution_scope=RULE_SCOPE_REGION,
        region_code=sido_code,
        region_name=sido_name,
    )


LOCAL_RULES: tuple[EvaluationRule, ...] = (
    # 인천광역시 구판 (예규 제484호, 시행 2024-12-04) — 현행 규칙 시행일 이전 공고 전용.
    _local_rule(
        "SERVC_LOCAL_INCHEON_20241204_ATTACH_01",
        sido_code="28",
        sido_name="인천광역시",
        service_type="GENERAL",
        effective_date="2024-12-04",
        superseded_date="2025-12-24",
        source=_SRC_INCHEON_20241204,
        cdw_exclusion="named",  # 원문: "3. 폐기물처리용역(건설폐기물 및 음식물류 폐기물은 제외한다) 적격심사 세부기준: 별표 2, 별표 3 및 별표 5" (ELIS https://www.elis.go.kr/allalr/selectAlrBdtOne?alrNo=28000032005015&histNo=007, sha256 a44aa6b09defdd28d19665525640e112bfc4ed99cba659179a2fae62e2987c54)
        description="인천광역시 일반용역 적격심사 (단순노무 외, 구판)",
        price_bands=(
            _local_price_band(
                "200000000",
                "90",
                "20",
                "추정가격 2억원 미만",
                _SRC_INCHEON_20241204,
                lwlt_rate="87.745",
            ),
            _local_price_band(
                "500000000",
                "70",
                "4",
                "5억원 미만 2억원 이상",
                _SRC_INCHEON_20241204,
                lwlt_rate="86.745",
            ),
            _local_price_band(
                "1000000000",
                "50",
                "2",
                "10억원 미만 5억원 이상",
                _SRC_INCHEON_20241204,
                lwlt_rate="85.495",
            ),
            _local_price_band(
                "3000000000",
                "30",
                "1",
                "30억원 미만 10억원 이상",
                _SRC_INCHEON_20241204,
                lwlt_rate="77.995",
            ),
        ),
        threshold_bands=_threshold_30_10(_SRC_INCHEON_20241204),
        base_rate="0.88",
        bounded_price_top=True,
    ),
    # 인천광역시 (예규 제488호, 시행 2025-12-24)
    _local_rule(
        "SERVC_LOCAL_INCHEON_20251224_ATTACH_01",
        sido_code="28",
        sido_name="인천광역시",
        service_type="GENERAL",
        effective_date="2025-12-24",
        source=_SRC_INCHEON,
        cdw_exclusion="named",  # 원문: "3. 폐기물처리용역(건설폐기물 및 음식물류 폐기물은 제외한다) 적격심사 세부기준: 별표 2, 별표 3 및 별표 5" (ELIS https://www.elis.go.kr/allalr/selectAlrBdtOne?alrNo=28000032005015&histNo=007, sha256 a44aa6b09defdd28d19665525640e112bfc4ed99cba659179a2fae62e2987c54)
        description="인천광역시 일반용역 적격심사 (단순노무 외)",
        # 별표 1 1~4 는 구간별 입찰가격 평점산식을 인쇄합니다. 10억원 이상은 30억원 경계로
        # 30억원 미만 77.995%, 30억원 이상 72.995% 로 갈립니다.
        price_bands=_five_band_price(
            _SRC_INCHEON,
            lwlt_rates=("87.745", "86.745", "85.495", "77.995", "72.995"),
        ),
        threshold_bands=_threshold_30_10(_SRC_INCHEON),
    ),
    _local_rule(
        "SERVC_LOCAL_INCHEON_20251224_SIMPLE_LABOR",
        sido_code="28",
        sido_name="인천광역시",
        service_type="SIMPLE_LABOR",
        effective_date="2025-12-24",
        source=_SRC_INCHEON,
        description="인천광역시 일반용역 적격심사 (단순노무)",
        # 단순노무 행의 낙찰하한율은 구간 구분 없이 87.745% 입니다(별표 1 단순노무 평점산식).
        price_bands=_four_band_price(_SRC_INCHEON, simple_labor=True),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_INCHEON),
        lwlt_rate="87.745",
    ),
    # 제주특별자치도 (예규 제82호, 시행 2024-01-01) — 인천과 동일 구조
    _local_rule(
        "SERVC_LOCAL_JEJU_20240101_ATTACH_01",
        sido_code="50",
        sido_name="제주특별자치도",
        service_type="GENERAL",
        effective_date="2024-01-01",
        source=_SRC_JEJU,
        description="제주특별자치도 일반용역 적격심사 (단순노무 외)",
        # 별표 1 1~4 는 구간별 입찰가격 평점산식을 인쇄합니다. 10억원 이상은 30억원 경계로
        # 30억원 미만 77.995%, 30억원 이상 72.995% 로 갈립니다.
        price_bands=_five_band_price(
            _SRC_JEJU,
            lwlt_rates=("87.745", "86.745", "85.495", "77.995", "72.995"),
        ),
        threshold_bands=_threshold_30_10(_SRC_JEJU),
    ),
    _local_rule(
        "SERVC_LOCAL_JEJU_20240101_SIMPLE_LABOR",
        sido_code="50",
        sido_name="제주특별자치도",
        service_type="SIMPLE_LABOR",
        effective_date="2024-01-01",
        source=_SRC_JEJU,
        description="제주특별자치도 일반용역 적격심사 (단순노무)",
        # 단순노무 행의 낙찰하한율은 구간 구분 없이 87.745% 입니다(별표 1 단순노무 평점산식).
        price_bands=_four_band_price(_SRC_JEJU, simple_labor=True),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_JEJU),
        lwlt_rate="87.745",
    ),
    # 강원특별자치도 (예규 제832호, 시행 2023-06-11) — 인천과 동일 구조
    _local_rule(
        "SERVC_LOCAL_GANGWON_20230611_ATTACH_01",
        sido_code="51",
        sido_name="강원특별자치도",
        service_type="GENERAL",
        effective_date="2023-06-11",
        source=_SRC_GANGWON,
        cdw_exclusion="named",  # 원문: "3. '폐기물처리용역'이란 ... 단, 생활폐기물 수집·운반 대행용역 및 건설폐기물 처리용역은 제외한다." (.cache/local_src/gwd/0ab5d0ce1041_elis_gwd_main.txt, sha256 0ab5d0ce10418097bb3f3ae6cb6bc1b30b73cf0e24560debea807ca4452892c0)
        description="강원특별자치도 일반용역 적격심사 (단순노무 외)",
        # 별표 1 1~4 는 구간별 입찰가격 평점산식과 낙찰하한율을 인쇄합니다(원문 :1996-2032).
        # 10억원 이상은 30억원 경계로 30억원 미만 77.995%, 30억원 이상 72.995% 로 갈립니다.
        price_bands=_five_band_price(
            _SRC_GANGWON,
            lwlt_rates=("87.745", "86.745", "85.495", "77.995", "72.995"),
        ),
        threshold_bands=_threshold_30_10(_SRC_GANGWON),
    ),
    _local_rule(
        "SERVC_LOCAL_GANGWON_20230611_SIMPLE_LABOR",
        sido_code="51",
        sido_name="강원특별자치도",
        service_type="SIMPLE_LABOR",
        effective_date="2023-06-11",
        source=_SRC_GANGWON,
        description="강원특별자치도 일반용역 적격심사 (단순노무)",
        # 단순노무 행의 낙찰하한율은 구간 구분 없이 87.745% 입니다(원문 :2006-2011).
        price_bands=_four_band_price(_SRC_GANGWON, simple_labor=True),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_GANGWON),
        lwlt_rate="87.745",
    ),
    # 세종특별자치시 (예규 제32호, 시행 2025-12-01)
    _local_rule(
        "SERVC_LOCAL_SEJONG_20251201_ATTACH_02",
        sido_code="36",
        sido_name="세종특별자치시",
        service_type="FACILITY",
        effective_date="2025-12-01",
        source=_SRC_SEJONG_FACILITY,
        description="세종특별자치시 시설분야용역 적격심사 (별표 2)",
        price_bands=(
            _local_price_band("500000000", "70", "60", "추정가격 5억원 미만", _SRC_SEJONG_FACILITY),
            _local_price_band(None, "60", "60", "추정가격 5억원 이상", _SRC_SEJONG_FACILITY),
        ),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_SEJONG_FACILITY),
        lwlt_rate="87.745",
    ),
    _local_rule(
        "SERVC_LOCAL_SEJONG_20251201_ATTACH_03",
        sido_code="36",
        sido_name="세종특별자치시",
        service_type="SW",
        effective_date="2025-12-01",
        source=_SRC_SEJONG_SW_NON_TARGET,
        description="세종특별자치시 소프트웨어용역(중소기업간 경쟁제품 비대상) 적격심사 (별표 3)",
        price_bands=(
            _local_price_band(
                "500000000", "70", "2", "추정가격 5억원 미만", _SRC_SEJONG_SW_NON_TARGET
            ),
            _local_price_band(None, "60", "2", "추정가격 5억원 이상", _SRC_SEJONG_SW_NON_TARGET),
        ),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_SEJONG_SW_NON_TARGET),
        lwlt_rate="80.495",
    ),
    _local_rule(
        "SERVC_LOCAL_SEJONG_20251201_ATTACH_03_SME",
        sido_code="36",
        sido_name="세종특별자치시",
        service_type="SW_SME",
        effective_date="2025-12-01",
        source=_SRC_SEJONG_SW_TARGET,
        description="세종특별자치시 소프트웨어용역(중소기업간 경쟁제품 대상) 적격심사 (별표 3)",
        price_bands=(
            _local_price_band("500000000", "70", "4", "추정가격 5억원 미만", _SRC_SEJONG_SW_TARGET),
            _local_price_band(None, "60", "4", "추정가격 5억원 이상", _SRC_SEJONG_SW_TARGET),
        ),
        threshold_bands=_single_threshold("88", "전 구간 88", _SRC_SEJONG_SW_TARGET),
        lwlt_rate="84.995",
    ),
    _local_rule(
        "SERVC_LOCAL_SEJONG_20251201_ATTACH_04",
        sido_code="36",
        sido_name="세종특별자치시",
        service_type="WASTE",
        effective_date="2025-12-01",
        source=_SRC_SEJONG_WASTE,
        cdw_exclusion="named",  # 원문: "5. '폐기물처리용역'이란 ... 다만, 생활폐기물처리용역 및 건설폐기물처리용역은 제외한다." (.cache/local_src/sejong/d9b290e93e43_sejong_body_2025.txt, sha256 d9b290e93e43fc979f73bb58ffb1bd2f7c9cd448bb27f954f9c4844c4b76e533)
        description="세종특별자치시 폐기물처리용역 적격심사 (별표 4)",
        price_bands=(
            _local_price_band("500000000", "70", "60", "추정가격 5억원 미만", _SRC_SEJONG_WASTE),
            _local_price_band(None, "60", "60", "추정가격 5억원 이상", _SRC_SEJONG_WASTE),
        ),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_SEJONG_WASTE),
        lwlt_rate="87.745",
    ),
    _local_rule(
        "SERVC_LOCAL_SEJONG_20251201_ATTACH_4_2",
        sido_code="36",
        sido_name="세종특별자치시",
        service_type="WASTE_HOUSEHOLD",
        effective_date="2025-12-01",
        source=_SRC_SEJONG_WASTE_HOUSEHOLD,
        description="세종특별자치시 생활폐기물처리용역 적격심사 (별표 4의2)",
        price_bands=(
            _local_price_band(
                "500000000", "70", "60", "추정가격 5억원 미만", _SRC_SEJONG_WASTE_HOUSEHOLD
            ),
            _local_price_band(None, "60", "60", "추정가격 5억원 이상", _SRC_SEJONG_WASTE_HOUSEHOLD),
        ),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_SEJONG_WASTE_HOUSEHOLD),
        lwlt_rate="87.745",
    ),
    _local_rule(
        "SERVC_LOCAL_SEJONG_20251201_ATTACH_05",
        sido_code="36",
        sido_name="세종특별자치시",
        service_type="LAND_TRANSPORT",
        effective_date="2025-12-01",
        source=_SRC_SEJONG_LT_NON_TARGET,
        description="세종특별자치시 육상운송용역(중소기업간 경쟁제품 비대상) 적격심사 (별표 5)",
        price_bands=(
            _local_price_band(
                "500000000", "70", "2", "추정가격 5억원 미만", _SRC_SEJONG_LT_NON_TARGET
            ),
            _local_price_band(None, "60", "2", "추정가격 5억원 이상", _SRC_SEJONG_LT_NON_TARGET),
        ),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_SEJONG_LT_NON_TARGET),
        lwlt_rate="80.495",
    ),
    _local_rule(
        "SERVC_LOCAL_SEJONG_20251201_ATTACH_05_SME",
        sido_code="36",
        sido_name="세종특별자치시",
        service_type="LAND_TRANSPORT_SME",
        effective_date="2025-12-01",
        source=_SRC_SEJONG_LT_TARGET,
        description="세종특별자치시 육상운송용역(중소기업간 경쟁제품 대상) 적격심사 (별표 5)",
        price_bands=(
            _local_price_band("500000000", "70", "4", "추정가격 5억원 미만", _SRC_SEJONG_LT_TARGET),
            _local_price_band(None, "60", "4", "추정가격 5억원 이상", _SRC_SEJONG_LT_TARGET),
        ),
        threshold_bands=_single_threshold("88", "전 구간 88", _SRC_SEJONG_LT_TARGET),
        lwlt_rate="84.995",
    ),
    # 경상북도 구판 (예규 제1568호, 시행 2024-12-12) — 현행 규칙 시행일 이전 공고 전용.
    _local_rule(
        "SERVC_LOCAL_GB_20241212_ATTACH_01",
        sido_code="47",
        sido_name="경상북도",
        service_type="GENERAL",
        effective_date="2024-12-12",
        superseded_date="2026-01-08",
        source=_SRC_GB_20241212,
        description="경상북도 기타 일반용역 적격심사 (별표 1, 구판)",
        price_bands=_five_band_price(
            _SRC_GB_20241212,
            lwlt_rates=("87.745", "86.745", "85.495", "77.995", "72.995"),
        ),
        threshold_bands=_threshold_30_10(_SRC_GB_20241212),
        lwlt_rate="87.745",
    ),
    _local_rule(
        "SERVC_LOCAL_GB_20241212_ATTACH_05",
        sido_code="47",
        sido_name="경상북도",
        service_type="WASTE",
        effective_date="2024-12-12",
        superseded_date="2026-01-08",
        source=_SRC_GB_20241212,
        cdw_exclusion="named",  # 원문: "5. '폐기물처리용역'이란 ... (단 건설폐기물의 재활용 촉진에 관한 법률에 따른 '건설폐기물'은 제외한다.)" (.cache/local_src/gb/ab55faa1b1a3_gb_body.txt, sha256 ab55faa1b1a30752252aad8fc530fcd21d9f7141f3236e9df1fcd436b063e121)
        description="경상북도 폐기물처리용역 적격심사 (별표 5, 구판)",
        price_bands=_five_band_price(
            _SRC_GB_20241212,
            lwlt_rates=("87.745", "86.745", "85.495", "77.995", "72.995"),
        ),
        threshold_bands=_threshold_30_10(_SRC_GB_20241212),
        lwlt_rate="87.745",
    ),
    # 경상북도 (예규 제1571호, 시행 2026-01-08)
    _local_rule(
        "SERVC_LOCAL_GB_20260108_ATTACH_01",
        sido_code="47",
        sido_name="경상북도",
        service_type="SIMPLE_LABOR",
        effective_date="2026-01-08",
        source=_SRC_GB,
        description="경상북도 단순노무용역 적격심사 (별표 1)",
        # 별표 1 단순노무 행은 전 구간 평점계수 20·기준비율 88 이고 통과점수가 95 라 인천·제주·
        # 강원 단순노무와 같은 산식입니다. 5억원 미만은 70-20x|88-투찰률|=65, 5억원 이상은
        # 50-20x|88-투찰률|=45 이므로 두 구간 모두 투찰률 87.75% → 87.745% 입니다(원문 _SRC_GB).
        lwlt_rate="87.745",
        price_bands=(
            _local_price_band("500000000", "70", "20", "추정가격 5억원 미만", _SRC_GB),
            _local_price_band(None, "50", "20", "추정가격 5억원 이상", _SRC_GB),
        ),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_GB),
    ),
    _local_rule(
        "SERVC_LOCAL_GB_20260108_ATTACH_02",
        sido_code="47",
        sido_name="경상북도",
        service_type="SW",
        effective_date="2026-01-08",
        source=_SRC_GB,
        description="경상북도 소프트웨어용역 적격심사 (별표 2)",
        price_bands=(
            _local_price_band("500000000", "80", "4", "추정가격 5억원 미만", _SRC_GB),
            _local_price_band(None, "60", "4", "추정가격 5억원 이상", _SRC_GB),
        ),
        threshold_bands=_single_threshold("88", "전 구간 88", _SRC_GB),
    ),
    _local_rule(
        "SERVC_LOCAL_GB_20260108_ATTACH_03",
        sido_code="47",
        sido_name="경상북도",
        service_type="WASTE",
        effective_date="2026-01-08",
        source=_SRC_GB,
        cdw_exclusion="named",  # 원문: "5. '폐기물처리용역'이란 ... (단 건설폐기물의 재활용 촉진에 관한 법률에 따른 '건설폐기물'은 제외한다.)" (.cache/local_src/gb/ab55faa1b1a3_gb_body.txt, sha256 ab55faa1b1a30752252aad8fc530fcd21d9f7141f3236e9df1fcd436b063e121)
        description="경상북도 폐기물처리용역 적격심사 (별표 3)",
        price_bands=(
            _local_price_band("500000000", "70", "20", "추정가격 5억원 미만", _SRC_GB),
            _local_price_band(None, "50", "4", "추정가격 5억원 이상", _SRC_GB),
        ),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_GB),
    ),
    _local_rule(
        "SERVC_LOCAL_GB_20260108_ATTACH_04",
        sido_code="47",
        sido_name="경상북도",
        service_type="GENERAL",
        effective_date="2026-01-08",
        source=_SRC_GB,
        description="경상북도 기타 일반용역 적격심사 (별표 4)",
        # 별표 4 원문은 5억원 미만 / 5억원 이상 두 행(B70·k20 / B50·k4)만 인쇄합니다. 구간별
        # 하한율은 원문 산식과 통과점수 95로 역산합니다. 5억원 미만 행(70-20x|88-투찰률|)은
        # 비가격 만점 30, 필요 65 → 투찰률 87.75% → 87.745% 이고, 5억원 이상 행
        # (50-4x|88-투찰률|)은 비가격 만점 50, 필요 45 → 투찰률 86.75% → 86.745% 입니다.
        price_bands=(
            _local_price_band(
                "200000000",
                "70",
                "20",
                "추정가격 2억원 미만",
                _SRC_GB_ATTACH_04,
                lwlt_rate="87.745",
            ),
            _local_price_band(
                "500000000",
                "70",
                "20",
                "5억원 미만 2억원 이상",
                _SRC_GB_ATTACH_04,
                lwlt_rate="87.745",
            ),
            _local_price_band(
                "1000000000",
                "50",
                "4",
                "10억원 미만 5억원 이상",
                _SRC_GB_ATTACH_04,
                lwlt_rate="86.745",
            ),
            _local_price_band(
                None, "50", "4", "추정가격 10억원 이상", _SRC_GB_ATTACH_04, lwlt_rate="86.745"
            ),
        ),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_GB_ATTACH_04),
        lwlt_rate="87.995",
    ),
    # 울산광역시 (공고 제2022-1100호, 시행 2022-08-10)
    _local_rule(
        "SERVC_LOCAL_ULSAN_20220810_ATTACH_01",
        sido_code="31",
        sido_name="울산광역시",
        service_type="GENERAL",
        effective_date="2022-08-10",
        source=_SRC_ULSAN,
        description="울산광역시 일반용역 적격심사 (별표 1, 단순노무 외)",
        # 별표 1 참고 입찰가격 평점 산식은 구간마다 낙찰하한율을 인쇄합니다(원문 :671-713).
        # 10억원 이상은 30억원 경계로 30억원 미만 77.995%, 30억원 이상 72.995% 로 갈립니다.
        price_bands=_five_band_price(
            _SRC_ULSAN,
            lwlt_rates=("87.745", "86.745", "85.495", "77.995", "72.995"),
        ),
        threshold_bands=_threshold_30_10(_SRC_ULSAN),
    ),
    _local_rule(
        "SERVC_LOCAL_ULSAN_20220810_SIMPLE_LABOR",
        sido_code="31",
        sido_name="울산광역시",
        service_type="SIMPLE_LABOR",
        effective_date="2022-08-10",
        source=_SRC_ULSAN,
        description="울산광역시 일반용역 적격심사 (별표 1, 단순노무)",
        # 단순노무 행의 낙찰하한율은 구간 구분 없이 87.745% 입니다(원문 :677,689,701,713).
        price_bands=_four_band_price(_SRC_ULSAN, simple_labor=True),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_ULSAN),
        lwlt_rate="87.745",
    ),
    _local_rule(
        "SERVC_LOCAL_ULSAN_20220810_ATTACH_1_1",
        sido_code="31",
        sido_name="울산광역시",
        service_type="WASTE_HOUSEHOLD",
        effective_date="2022-08-10",
        source=_SRC_ULSAN,
        description="울산광역시 생활폐기물 수집·운반 대행용역 적격심사 (별표 1-1)",
        price_bands=(
            _local_price_band("1000000000", "70", "20", "추정가격 10억원 미만", _SRC_ULSAN),
            _local_price_band("3000000000", "50", "20", "30억원 미만 10억원 이상", _SRC_ULSAN),
            _local_price_band(None, "30", "40", "추정가격 30억원 이상", _SRC_ULSAN),
        ),
        threshold_bands=_threshold_30_10(_SRC_ULSAN),
        # 생활폐기물수집·운반대행용역 행의 낙찰하한율은 구간 구분 없이 87.745% 입니다
        # (원문 :680,692,704).
        lwlt_rate="87.745",
    ),
    _local_rule(
        "SERVC_LOCAL_ULSAN_20220810_ATTACH_02",
        sido_code="31",
        sido_name="울산광역시",
        service_type="WASTE",
        effective_date="2022-08-10",
        source=_SRC_ULSAN,
        cdw_exclusion="named_except_haul",  # 원문: "3. 폐기물처리용역이란 ... 단, 생활폐기물 수집·운반 대행용역 및 건설폐기물 처리용역은 제외하나 건설폐기물 중 중간처리를 포함하지 않는 수집·운반용역은 포함한다." (.cache/local_src/ulsan/c6a460417140_ulsan.txt, sha256 c6a460417140c9e849521fbc1489b53391d09ff21b2b885063ca30185382f829)
        description="울산광역시 폐기물처리용역 적격심사 (별표 2)",
        # 폐기물용역 행도 별표 1 참고 산식과 같은 구간별 낙찰하한율을 인쇄합니다.
        price_bands=_five_band_price(
            _SRC_ULSAN,
            lwlt_rates=("87.745", "86.745", "85.495", "77.995", "72.995"),
        ),
        threshold_bands=_threshold_30_10(_SRC_ULSAN),
    ),
    # 충청북도 (공고 제2023-1428호, 시행 2023-10-20)
    _local_rule(
        "SERVC_LOCAL_CB_20231020_ATTACH_01",
        sido_code="43",
        sido_name="충청북도",
        service_type="GENERAL",
        effective_date="2023-10-20",
        source=_SRC_CB,
        cdw_exclusion="named",  # 원문: "② 건설폐기물처리용역 적격심사는 이 세부기준 시행과 동시에 환경부고시 제2007-37호 '건설폐기물처리용역 적격업체 평가기준'을 적용한다." (.cache/local_src/cb/cb8c86236f3b_cb.txt, sha256 cb8c86236f3b688c7499718d50d05e378800e4860ee0df3622ea1118ba82c69e)
        description="충청북도 일반용역 적격심사 (별표 1, 단순노무 외)",
        # 별표 1 3. 입찰가격 평가는 구간마다 낙찰하한율을 인쇄합니다(원문 :1513-1659).
        # 10억원 이상은 30억원 경계로 30억원 미만 77.995%, 30억원 이상 72.995% 로 갈립니다.
        price_bands=_five_band_price(
            _SRC_CB,
            lwlt_rates=("87.745", "86.745", "85.495", "77.995", "72.995"),
        ),
        threshold_bands=_threshold_30_10(_SRC_CB),
    ),
    _local_rule(
        "SERVC_LOCAL_CB_20231020_SIMPLE_LABOR",
        sido_code="43",
        sido_name="충청북도",
        service_type="SIMPLE_LABOR",
        effective_date="2023-10-20",
        source=_SRC_CB,
        description="충청북도 일반용역 적격심사 (별표 1, 단순노무)",
        # 단순노무 행의 낙찰하한율은 구간 구분 없이 87.745% 입니다(원문 :1535-1537 등).
        price_bands=_four_band_price(_SRC_CB, simple_labor=True),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_CB),
        lwlt_rate="87.745",
    ),
    # 전라남도 구판 (예규 제1075호, 시행 2023-03-02) — 통합 지침 이전 공고 전용.
    # 통합 지침 시행일(2026-07-16) 이후 공고는 아래 현행 규칙이 쓰이고, 그 이전 공고는 같은
    # 세부유형의 이 구판 규칙이 쓰입니다. 광주광역시 계열은 별도 구판 규칙
    # (SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_3/1_5) 이 아래에 등록되어 있습니다.
    _local_rule(
        "SERVC_LOCAL_JEONNAM_20230302_ATTACH_4_1_4",
        sido_code="46",
        sido_name="전라남도",
        service_type="WASTE",
        effective_date="2023-03-02",
        superseded_date="2026-07-16",
        source=_SRC_JEONNAM_ATTACH_4_1_4,
        description="전라남도 폐기물처리용역 적격심사 (별표 4-1-4, 통합 지침 이전)",
        # 별표 4 는 추정가격 5억원 이상(B 30·k 1)·5억원 미만 1억원 이상(B 80·k 20)·
        # 1억원 미만(B 90·k 20) 세 구간입니다. 5억원 이상 행은 통과점수 구간(10억·30억)마다
        # 낙찰하한율이 갈려 같은 B·k 로 세 구간으로 나눠 등록합니다(현행 별표 3 과 같은 구조).
        lwlt_rate="87.745",
        price_bands=(
            _local_price_band(
                "100000000",
                "90",
                "20",
                "추정가격 1억원 미만",
                _SRC_JEONNAM_ATTACH_4_1_4,
                lwlt_rate="87.745",
            ),
            _local_price_band(
                "500000000",
                "80",
                "20",
                "5억원 미만 1억원 이상",
                _SRC_JEONNAM_ATTACH_4_1_4,
                lwlt_rate="87.745",
            ),
            _local_price_band(
                "1000000000",
                "30",
                "1",
                "10억원 미만 5억원 이상",
                _SRC_JEONNAM_ATTACH_4_1_4,
                lwlt_rate="82.995",
            ),
            _local_price_band(
                "3000000000",
                "30",
                "1",
                "30억원 미만 10억원 이상",
                _SRC_JEONNAM_ATTACH_4_1_4,
                lwlt_rate="77.995",
            ),
            _local_price_band(
                None,
                "30",
                "1",
                "추정가격 30억원 이상",
                _SRC_JEONNAM_ATTACH_4_1_4,
                lwlt_rate="72.995",
            ),
        ),
        threshold_bands=_threshold_30_10(_SRC_JEONNAM_ATTACH_4_1_4),
    ),
    _local_rule(
        "SERVC_LOCAL_JEONNAM_20230302_ATTACH_5_1_4",
        sido_code="46",
        sido_name="전라남도",
        service_type="LAND_TRANSPORT",
        effective_date="2023-03-02",
        superseded_date="2026-07-16",
        source=_SRC_JEONNAM_ATTACH_5_1_4,
        description="전라남도 육상운송용역 적격심사 (별표 5-1-4, 통합 지침 이전)",
        # 별표 5 는 추정가격 5억원 이상(B 60·k 2)·5억원 미만(B 80·k 2) 두 구간이고,
        # 5억원 이상 행은 통과점수 구간(10억·30억)마다 낙찰하한율이 갈립니다.
        lwlt_rate="85.495",
        price_bands=(
            _local_price_band(
                "500000000",
                "80",
                "2",
                "추정가격 5억원 미만",
                _SRC_JEONNAM_ATTACH_5_1_4,
                lwlt_rate="85.495",
            ),
            _local_price_band(
                "1000000000",
                "60",
                "2",
                "10억원 미만 5억원 이상",
                _SRC_JEONNAM_ATTACH_5_1_4,
                lwlt_rate="85.495",
            ),
            _local_price_band(
                "3000000000",
                "60",
                "2",
                "30억원 미만 10억원 이상",
                _SRC_JEONNAM_ATTACH_5_1_4,
                lwlt_rate="82.995",
            ),
            _local_price_band(
                None,
                "60",
                "2",
                "추정가격 30억원 이상",
                _SRC_JEONNAM_ATTACH_5_1_4,
                lwlt_rate="80.495",
            ),
        ),
        threshold_bands=_threshold_30_10(_SRC_JEONNAM_ATTACH_5_1_4),
    ),
    _local_rule(
        "SERVC_LOCAL_JEONNAM_20230302_ATTACH_1_1_4",
        sido_code="46",
        sido_name="전라남도",
        service_type="FACILITY",
        effective_date="2023-03-02",
        superseded_date="2026-07-16",
        source=_SRC_JEONNAM_ATTACH_1_1_4,
        description="전라남도 시설분야용역 적격심사 (별표 1, 통합 지침 이전)",
        # 별표 1 은 추정가격 5억원 이상(B 50·k 20)·5억원 미만(B 70·k 20) 두 구간이고,
        # 5억원 이상 행은 통과점수 구간(10억·30억)마다 낙찰하한율이 갈립니다.
        lwlt_rate="87.745",
        price_bands=(
            _local_price_band(
                "500000000",
                "70",
                "20",
                "추정가격 5억원 미만",
                _SRC_JEONNAM_ATTACH_1_1_4,
                lwlt_rate="87.745",
            ),
            _local_price_band(
                "1000000000",
                "50",
                "20",
                "10억원 미만 5억원 이상",
                _SRC_JEONNAM_ATTACH_1_1_4,
                lwlt_rate="87.745",
            ),
            _local_price_band(
                "3000000000",
                "50",
                "20",
                "30억원 미만 10억원 이상",
                _SRC_JEONNAM_ATTACH_1_1_4,
                lwlt_rate="87.495",
            ),
            _local_price_band(
                None,
                "50",
                "20",
                "추정가격 30억원 이상",
                _SRC_JEONNAM_ATTACH_1_1_4,
                lwlt_rate="87.245",
            ),
        ),
        threshold_bands=_threshold_30_10(_SRC_JEONNAM_ATTACH_1_1_4),
    ),
    # 광주광역시 구판 (예규 제377호, 시행 2022-11-15) — 통합 지침 이전 공고 전용.
    # region_code "29" 로 두고 superseded_date 2026-07-16. 통과점수는 95 단일(제11조 ①).
    _local_rule(
        "SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_3",
        sido_code="29",
        sido_name="광주광역시",
        service_type="WASTE",
        effective_date="2022-11-15",
        superseded_date="2026-07-16",
        source=_SRC_GWANGJU_ATTACH_1_3,
        description="광주광역시 폐기물처리용역 적격심사 (별표 1-3, 통합 지침 이전)",
        lwlt_rate="82.995",
        price_bands=(
            _local_price_band(
                "100000000",
                "90",
                "20",
                "추정가격 1억원 미만",
                _SRC_GWANGJU_ATTACH_1_3,
                lwlt_rate="87.745",
            ),
            _local_price_band(
                "500000000",
                "80",
                "20",
                "지역제한 금액 미만 1억원 이상",
                _SRC_GWANGJU_ATTACH_1_3,
                lwlt_rate="87.745",
            ),
            _local_price_band(
                None,
                "30",
                "1",
                "지역제한 금액 이상",
                _SRC_GWANGJU_ATTACH_1_3,
                lwlt_rate="82.995",
            ),
        ),
        threshold_bands=_single_threshold(
            "95", "폐기물처리용역 추정가격 무관 95", _SRC_GWANGJU_ATTACH_1_3
        ),
    ),
    _local_rule(
        "SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_5",
        sido_code="29",
        sido_name="광주광역시",
        service_type="LAND_TRANSPORT",
        effective_date="2022-11-15",
        superseded_date="2026-07-16",
        source=_SRC_GWANGJU_ATTACH_1_5,
        description="광주광역시 육상운송용역 적격심사 (별표 1-5, 통합 지침 이전)",
        lwlt_rate="85.495",
        price_bands=(
            _local_price_band(
                "500000000",
                "70",
                "2",
                "지역제한 금액 미만",
                _SRC_GWANGJU_ATTACH_1_5,
                lwlt_rate="85.495",
            ),
            _local_price_band(
                None,
                "60",
                "2",
                "지역제한 금액 이상",
                _SRC_GWANGJU_ATTACH_1_5,
                lwlt_rate="85.495",
            ),
        ),
        threshold_bands=_single_threshold(
            "95", "육상운송용역 추정가격 무관 95", _SRC_GWANGJU_ATTACH_1_5
        ),
    ),
    # 광주광역시(광역) 본청·소속기관 전용 구판 규칙 (국제입찰 고시 금액 경계).
    # 자치구 등 그 밖의 공고는 위 5억원 경계 규칙을 그대로 쓰고, 본청·소속기관 공고만
    # 이 규칙(3.3억/3.5억 경계)을 씁니다. _select_local_rule 이 수요기관명으로 가릅니다.
    _local_rule(
        "SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_3_METRO_330",
        sido_code="29",
        sido_name="광주광역시",
        service_type="WASTE",
        effective_date="2022-11-15",
        superseded_date="2025-01-01",
        source=_SRC_GWANGJU_ATTACH_1_3,
        description="광주광역시(광역) 폐기물처리용역 적격심사 (별표 1-3, 지역제한 3.3억, 통합 지침 이전)",
        lwlt_rate="82.995",
        price_bands=(
            _local_price_band(
                "100000000",
                "90",
                "20",
                "추정가격 1억원 미만",
                _SRC_GWANGJU_ATTACH_1_3,
                lwlt_rate="87.745",
            ),
            _local_price_band(
                "330000000",
                "80",
                "20",
                "지역제한 금액 미만 1억원 이상",
                _SRC_GWANGJU_ATTACH_1_3,
                lwlt_rate="87.745",
            ),
            _local_price_band(
                None,
                "30",
                "1",
                "지역제한 금액 이상",
                _SRC_GWANGJU_ATTACH_1_3,
                lwlt_rate="82.995",
            ),
        ),
        threshold_bands=_single_threshold(
            "95", "폐기물처리용역 추정가격 무관 95", _SRC_GWANGJU_ATTACH_1_3
        ),
    ),
    _local_rule(
        "SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_3_METRO_350",
        sido_code="29",
        sido_name="광주광역시",
        service_type="WASTE",
        effective_date="2025-01-01",
        superseded_date="2026-07-16",
        source=_SRC_GWANGJU_ATTACH_1_3,
        description="광주광역시(광역) 폐기물처리용역 적격심사 (별표 1-3, 지역제한 3.5억, 통합 지침 이전)",
        lwlt_rate="82.995",
        price_bands=(
            _local_price_band(
                "100000000",
                "90",
                "20",
                "추정가격 1억원 미만",
                _SRC_GWANGJU_ATTACH_1_3,
                lwlt_rate="87.745",
            ),
            _local_price_band(
                "350000000",
                "80",
                "20",
                "지역제한 금액 미만 1억원 이상",
                _SRC_GWANGJU_ATTACH_1_3,
                lwlt_rate="87.745",
            ),
            _local_price_band(
                None,
                "30",
                "1",
                "지역제한 금액 이상",
                _SRC_GWANGJU_ATTACH_1_3,
                lwlt_rate="82.995",
            ),
        ),
        threshold_bands=_single_threshold(
            "95", "폐기물처리용역 추정가격 무관 95", _SRC_GWANGJU_ATTACH_1_3
        ),
    ),
    _local_rule(
        "SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_5_METRO_330",
        sido_code="29",
        sido_name="광주광역시",
        service_type="LAND_TRANSPORT",
        effective_date="2022-11-15",
        superseded_date="2025-01-01",
        source=_SRC_GWANGJU_ATTACH_1_5,
        description="광주광역시(광역) 육상운송용역 적격심사 (별표 1-5, 지역제한 3.3억, 통합 지침 이전)",
        lwlt_rate="85.495",
        price_bands=(
            _local_price_band(
                "330000000",
                "70",
                "2",
                "지역제한 금액 미만",
                _SRC_GWANGJU_ATTACH_1_5,
                lwlt_rate="85.495",
            ),
            _local_price_band(
                None,
                "60",
                "2",
                "지역제한 금액 이상",
                _SRC_GWANGJU_ATTACH_1_5,
                lwlt_rate="85.495",
            ),
        ),
        threshold_bands=_single_threshold(
            "95", "육상운송용역 추정가격 무관 95", _SRC_GWANGJU_ATTACH_1_5
        ),
    ),
    _local_rule(
        "SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_5_METRO_350",
        sido_code="29",
        sido_name="광주광역시",
        service_type="LAND_TRANSPORT",
        effective_date="2025-01-01",
        superseded_date="2026-07-16",
        source=_SRC_GWANGJU_ATTACH_1_5,
        description="광주광역시(광역) 육상운송용역 적격심사 (별표 1-5, 지역제한 3.5억, 통합 지침 이전)",
        lwlt_rate="85.495",
        price_bands=(
            _local_price_band(
                "350000000",
                "70",
                "2",
                "지역제한 금액 미만",
                _SRC_GWANGJU_ATTACH_1_5,
                lwlt_rate="85.495",
            ),
            _local_price_band(
                None,
                "60",
                "2",
                "지역제한 금액 이상",
                _SRC_GWANGJU_ATTACH_1_5,
                lwlt_rate="85.495",
            ),
        ),
        threshold_bands=_single_threshold(
            "95", "육상운송용역 추정가격 무관 95", _SRC_GWANGJU_ATTACH_1_5
        ),
    ),
    # 전남광주통합특별시 (예규 제3호, 시행 2026-07-16)
    _local_rule(
        "SERVC_LOCAL_JNGJ_20260716_ATTACH_01",
        sido_code="12",
        sido_name="전남광주통합특별시",
        service_type="FACILITY",
        effective_date="2026-07-16",
        source=_SRC_JNGJ,
        description="전남광주통합특별시 시설분야용역 적격심사 (별표 1)",
        # 별표 1 입찰가격 평가의 낙찰하한율은 3구간 모두 87.745% 입니다(원문 att001:53,61,69).
        price_bands=(
            _local_price_band("200000000", "90", "20", "추정가격 2억원 미만", _SRC_JNGJ),
            _local_price_band("500000000", "70", "20", "5억원 미만 2억원 이상", _SRC_JNGJ),
            _local_price_band(None, "50", "20", "추정가격 5억원 이상", _SRC_JNGJ),
        ),
        threshold_bands=_single_threshold("95", "시설분야 추정가격 무관 95", _SRC_JNGJ),
        lwlt_rate="87.745",
    ),
    _local_rule(
        "SERVC_LOCAL_JNGJ_20260716_ATTACH_02",
        sido_code="12",
        sido_name="전남광주통합특별시",
        service_type="SW",
        effective_date="2026-07-16",
        source=_SRC_JNGJ,
        description="전남광주통합특별시 소프트웨어용역 적격심사 (별표 2)",
        # 별표 2 는 5억원 이상 행을 10억·30억 경계로 나눠 인쇄합니다(원문 att002:58).
        # B·k(50·2)는 나눈 세 구간 모두 같습니다.
        price_bands=(
            _local_price_band(
                "200000000", "80", "20", "추정가격 2억원 미만", _SRC_JNGJ, lwlt_rate="87.745"
            ),
            _local_price_band(
                "500000000", "70", "4", "5억원 미만 2억원 이상", _SRC_JNGJ, lwlt_rate="86.745"
            ),
            _local_price_band(
                "1000000000", "50", "2", "10억원 미만 5억원 이상", _SRC_JNGJ, lwlt_rate="85.495"
            ),
            _local_price_band(
                "3000000000", "50", "2", "30억원 미만 10억원 이상", _SRC_JNGJ, lwlt_rate="82.995"
            ),
            _local_price_band(
                None, "50", "2", "추정가격 30억원 이상", _SRC_JNGJ, lwlt_rate="80.495"
            ),
        ),
        threshold_bands=_threshold_30_10(_SRC_JNGJ),
    ),
    _local_rule(
        "SERVC_LOCAL_JNGJ_20260716_ATTACH_03",
        sido_code="12",
        sido_name="전남광주통합특별시",
        service_type="WASTE",
        effective_date="2026-07-16",
        source=_SRC_JNGJ,
        description="전남광주통합특별시 폐기물처리용역 적격심사 (별표 3)",
        # 별표 3 의 5억원 이상 행도 10억·30억 경계로 나뉩니다(원문 att003:59).
        price_bands=(
            _local_price_band(
                "200000000", "90", "20", "추정가격 2억원 미만", _SRC_JNGJ, lwlt_rate="87.745"
            ),
            _local_price_band(
                "500000000", "80", "20", "5억원 미만 2억원 이상", _SRC_JNGJ, lwlt_rate="87.745"
            ),
            _local_price_band(
                "1000000000", "30", "1", "10억원 미만 5억원 이상", _SRC_JNGJ, lwlt_rate="82.995"
            ),
            _local_price_band(
                "3000000000", "30", "1", "30억원 미만 10억원 이상", _SRC_JNGJ, lwlt_rate="77.995"
            ),
            _local_price_band(
                None, "30", "1", "추정가격 30억원 이상", _SRC_JNGJ, lwlt_rate="72.995"
            ),
        ),
        threshold_bands=_threshold_30_10(_SRC_JNGJ),
    ),
    _local_rule(
        "SERVC_LOCAL_JNGJ_20260716_ATTACH_04",
        sido_code="12",
        sido_name="전남광주통합특별시",
        service_type="WASTE_HOUSEHOLD",
        effective_date="2026-07-16",
        source=_SRC_JNGJ,
        description="전남광주통합특별시 생활폐기물처리용역 적격심사 (별표 4)",
        # 별표 4 입찰가격 평가의 낙찰하한율은 3구간 모두 87.745% 입니다(원문 att004:46-60).
        price_bands=(
            _local_price_band("1000000000", "70", "20", "추정가격 10억원 미만", _SRC_JNGJ),
            _local_price_band("3000000000", "50", "40", "30억원 미만 10억원 이상", _SRC_JNGJ),
            _local_price_band(None, "30", "60", "추정가격 30억원 이상", _SRC_JNGJ),
        ),
        threshold_bands=_threshold_30_10(_SRC_JNGJ),
        lwlt_rate="87.745",
    ),
    _local_rule(
        "SERVC_LOCAL_JNGJ_20260716_ATTACH_05",
        sido_code="12",
        sido_name="전남광주통합특별시",
        service_type="LAND_TRANSPORT",
        effective_date="2026-07-16",
        source=_SRC_JNGJ,
        description="전남광주통합특별시 육상운송용역 적격심사 (별표 5)",
        lwlt_rate="84.245",
        # 별표 5 의 5억원 이상 행도 10억·30억 경계로 나뉩니다(원문 att005:54).
        price_bands=(
            _local_price_band(
                "200000000", "80", "2", "추정가격 2억원 미만", _SRC_JNGJ, lwlt_rate="85.495"
            ),
            _local_price_band(
                "500000000", "70", "2", "5억원 미만 2억원 이상", _SRC_JNGJ, lwlt_rate="85.495"
            ),
            _local_price_band(
                "1000000000", "60", "2", "10억원 미만 5억원 이상", _SRC_JNGJ, lwlt_rate="85.495"
            ),
            _local_price_band(
                "3000000000", "60", "2", "30억원 미만 10억원 이상", _SRC_JNGJ, lwlt_rate="82.995"
            ),
            _local_price_band(
                None, "60", "2", "추정가격 30억원 이상", _SRC_JNGJ, lwlt_rate="80.495"
            ),
        ),
        threshold_bands=_threshold_30_10(_SRC_JNGJ),
    ),
    _local_rule(
        "SERVC_LOCAL_JNGJ_20260716_ATTACH_06",
        sido_code="12",
        sido_name="전남광주통합특별시",
        service_type="FISHERY_CLEANUP",
        effective_date="2026-07-16",
        source=_SRC_JNGJ,
        description="전남광주통합특별시 어장정화·정비용역 적격심사 (별표 6)",
        # 별표 6 은 구간마다 낙찰하한율을 인쇄합니다(원문 att006:9,37,65,93).
        # 10억원 이상은 30억원 경계로 30억원 미만 77.995%, 30억원 이상 72.995% 로 갈립니다.
        price_bands=_five_band_price(
            _SRC_JNGJ,
            lwlt_rates=("87.745", "86.745", "85.495", "77.995", "72.995"),
        ),
        threshold_bands=_threshold_30_10(_SRC_JNGJ),
    ),
    # 경상남도 (공고 제2023-23호, 시행 2023-01-05)
    _local_rule(
        "SERVC_LOCAL_GN_20230105_ATTACH_01",
        sido_code="48",
        sido_name="경상남도",
        service_type="GENERAL",
        effective_date="2023-01-05",
        source=_SRC_GN,
        description="경상남도 일반용역 적격심사 (별표 1)",
        # 별표 1 1~4 는 구간별 입찰가격 평점산식을 인쇄합니다. 10억원 이상은 30억원 경계로
        # 30억원 미만 77.995%, 30억원 이상 72.995% 로 갈립니다.
        price_bands=_five_band_price(
            _SRC_GN,
            lwlt_rates=("87.745", "86.745", "85.495", "77.995", "72.995"),
        ),
        threshold_bands=_threshold_30_10(_SRC_GN),
    ),
    # 대구광역시 (예규 제238호, 시행 2026-05-11) — 단순노무만 확정, 일반 별표는 삭제됨
    _local_rule(
        "SERVC_LOCAL_DAEGU_20260511_ATTACH_01",
        sido_code="27",
        sido_name="대구광역시",
        service_type="SIMPLE_LABOR",
        effective_date="2026-05-11",
        source=_SRC_DAEGU,
        description="대구광역시 단순노무 일반용역 적격심사 (별표 1)",
        price_bands=(
            _local_price_band("200000000", "70", "60", "추정가격 2억원 미만", _SRC_DAEGU),
            _local_price_band(None, "60", "60", "추정가격 2억원 이상", _SRC_DAEGU),
        ),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_DAEGU),
        # 별표 1 은 최저 낙찰하한율을 87.745% 이상으로 인쇄합니다(원문 tbl1_daegu.txt:150).
        lwlt_rate="87.745",
    ),
    # 대구광역시 구판 (예규 제223호, 시행 2022-09-30) — 별표 4 폐기물처리용역
    _local_rule(
        "SERVC_LOCAL_DAEGU_20220930_ATTACH_04",
        sido_code="27",
        sido_name="대구광역시",
        service_type="WASTE",
        effective_date="2022-09-30",
        superseded_date="2026-05-11",
        source=_SRC_DAEGU_20220930,
        description="대구광역시 폐기물처리용역 적격심사 (별표 4, 구판)",
        price_bands=(
            _local_price_band(
                "500000000",
                "70",
                "2",
                "지역제한 금액 미만",
                _SRC_DAEGU_20220930,
                lwlt_rate="80.495",
            ),
            _local_price_band(
                None, "60", "2", "지역제한 금액 이상", _SRC_DAEGU_20220930, lwlt_rate="80.495"
            ),
        ),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_DAEGU_20220930),
        lwlt_rate="80.495",
        bounded_price_top=False,
        cdw_exclusion="band",
    ),
    # 대구광역시 구판 (예규 제223호, 시행 2022-09-30) — 별표 1 단순노무
    _local_rule(
        "SERVC_LOCAL_DAEGU_20220930_ATTACH_01",
        sido_code="27",
        sido_name="대구광역시",
        service_type="SIMPLE_LABOR",
        effective_date="2022-09-30",
        superseded_date="2026-05-11",
        source=_SRC_DAEGU_20220930,
        description="대구광역시 단순노무 일반용역 적격심사 (별표 1, 구판)",
        price_bands=(
            _local_price_band("200000000", "70", "60", "추정가격 2억원 미만", _SRC_DAEGU_20220930),
            _local_price_band(None, "60", "60", "추정가격 2억원 이상", _SRC_DAEGU_20220930),
        ),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_DAEGU_20220930),
        lwlt_rate="87.745",
    ),
    # 경기도 (예규 제748호, 시행 2025-08-08) — 별표 1-1(단순노무)은 원문 산식 미확인
    # (기준비율 0.25 불일치)이라 87.745% 를 적용하지 않고 규칙을 만들지 않습니다.
    _local_rule(
        "SERVC_LOCAL_GG_20250808_ATTACH_1_2",
        sido_code="41",
        sido_name="경기도",
        service_type="SW",
        effective_date="2025-08-08",
        source=_SRC_GG,
        description="경기도 소프트웨어용역 적격심사 (별표 1-2)",
        # 별표 1-2 입찰가격 평점 산식은 구간마다 낙찰하한율을 인쇄합니다(원문 coord:419-452).
        price_bands=(
            _local_price_band(
                "200000000", "90", "20", "추정가격 2억원 미만", _SRC_GG, lwlt_rate="87.745"
            ),
            _local_price_band(
                "500000000", "50", "4", "5억원 미만 2억원 이상", _SRC_GG, lwlt_rate="86.745"
            ),
            _local_price_band(
                "1000000000", "50", "2", "10억원 미만 5억원 이상", _SRC_GG, lwlt_rate="85.495"
            ),
            _local_price_band(None, "30", "1", "추정가격 10억원 이상", _SRC_GG, lwlt_rate="77.995"),
        ),
        threshold_bands=(
            _local_threshold_band("1000000000", "95", "추정가격 10억원 미만", _SRC_GG),
            _local_threshold_band(None, "90", "추정가격 10억원 이상", _SRC_GG),
        ),
    ),
    _local_rule(
        "SERVC_LOCAL_GG_20250808_ATTACH_1_3",
        sido_code="41",
        sido_name="경기도",
        service_type="WASTE",
        effective_date="2025-08-08",
        source=_SRC_GG,
        cdw_exclusion="named",  # 원문: "3. 폐기물처리용역: ... 처리하는 영업을 말하며 ... 4. ... 건설폐기물 처리용역은 '건설폐기물처리용역 적격업체 평가기준'에 따른다." (.cache/local_src/gg/c231f0609a39_gg_g2b_20251210_coord.txt, sha256 c231f0609a398c298fd8dd45f1d0834dfbbfe94d35a58e631ad2ed492fa2fba9)
        description="경기도 폐기물처리용역 적격심사 (별표 1-3)",
        # 별표 1-3 도 구간마다 낙찰하한율을 인쇄합니다(원문 coord:537-569).
        price_bands=(
            _local_price_band(
                "200000000", "70", "20", "추정가격 2억원 미만", _SRC_GG, lwlt_rate="87.745"
            ),
            _local_price_band(
                "500000000", "60", "4", "5억원 미만 2억원 이상", _SRC_GG, lwlt_rate="86.745"
            ),
            _local_price_band(
                "1000000000", "50", "2", "10억원 미만 5억원 이상", _SRC_GG, lwlt_rate="85.495"
            ),
            _local_price_band(None, "30", "1", "추정가격 10억원 이상", _SRC_GG, lwlt_rate="77.995"),
        ),
        threshold_bands=(
            _local_threshold_band("1000000000", "95", "추정가격 10억원 미만", _SRC_GG),
            _local_threshold_band(None, "90", "추정가격 10억원 이상", _SRC_GG),
        ),
    ),
    _local_rule(
        "SERVC_LOCAL_GG_20250808_ATTACH_1_4",
        sido_code="41",
        sido_name="경기도",
        service_type="LAND_TRANSPORT",
        effective_date="2025-08-08",
        source=_SRC_GG,
        description="경기도 육상운송용역 적격심사 (별표 1-4)",
        lwlt_rate="87.995",
        # 별표 1-4 의 구간별 낙찰하한율은 85.495/86.745/87.745/87.745% 입니다(원문 coord:641-669).
        price_bands=(
            _local_price_band(
                "200000000", "90", "20", "추정가격 2억원 미만", _SRC_GG, lwlt_rate="87.745"
            ),
            _local_price_band(
                "500000000", "70", "20", "5억원 미만 2억원 이상", _SRC_GG, lwlt_rate="87.745"
            ),
            _local_price_band(
                "1000000000", "50", "4", "10억원 미만 5억원 이상", _SRC_GG, lwlt_rate="86.745"
            ),
            _local_price_band(None, "30", "4", "추정가격 10억원 이상", _SRC_GG, lwlt_rate="85.495"),
        ),
        threshold_bands=(
            _local_threshold_band("1000000000", "95", "추정가격 10억원 미만", _SRC_GG),
            _local_threshold_band(None, "90", "추정가격 10억원 이상", _SRC_GG),
        ),
    ),
    _local_rule(
        "SERVC_LOCAL_GG_20250808_ATTACH_1_5",
        sido_code="41",
        sido_name="경기도",
        service_type="INSURANCE",
        effective_date="2025-08-08",
        source=_SRC_GG_INSURANCE,
        description="경기도 보험용역 적격심사 (별표 1-5)",
        # 별표 1-5 는 낙찰하한율 열 없이 평점산식(계수 0.375)만 인쇄합니다. B 는 5억원 미만
        # 70·5억원 이상 60 이고 제8조 통과점수는 85 라, 원문 산식 역산값
        # 88 - (100 - 85) / 0.375 = 48.0 → 47.995% 가 INSURANCE 기본값과 같습니다.
        price_bands=(
            _local_price_band("500000000", "70", "0.375", "추정가격 5억원 미만", _SRC_GG_INSURANCE),
            _local_price_band(None, "60", "0.375", "추정가격 5억원 이상", _SRC_GG_INSURANCE),
        ),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_GG_INSURANCE),
    ),
    _local_rule(
        "SERVC_LOCAL_GG_20250808_ATTACH_1_6",
        sido_code="41",
        sido_name="경기도",
        service_type="GENERAL",
        effective_date="2025-08-08",
        source=_SRC_GG,
        description="경기도 기타 일반용역 적격심사 (별표 1-6)",
        # 별표 1-6 도 구간마다 낙찰하한율을 인쇄합니다(원문 coord:805-835).
        price_bands=_four_band_price(_SRC_GG, lwlt_rates=("87.745", "86.745", "85.495", "77.995")),
        threshold_bands=(
            _local_threshold_band("1000000000", "95", "추정가격 10억원 미만", _SRC_GG),
            _local_threshold_band(None, "90", "추정가격 10억원 이상", _SRC_GG),
        ),
    ),
    # 서울특별시 (시행 2024-08-12) — 일반 띠 단순노무 외/단순노무가 갈려 두 규칙으로 둡니다.
    # 원문에 낙찰하한율 열은 없지만 별표 1~4 평점산식과 제7조 통과점수를 역산하면 구간값이
    # 모두 닫히고, 10억원 이상은 30억원 경계(30억원 미만 77.995%, 30억원 이상 72.995%)로
    # 갈립니다. 2026-10-13 역산값이 종전 공고 실측 최빈값과 일치함을 확인했습니다.
    _local_rule(
        "SERVC_LOCAL_SEOUL_20240812_ATTACH_01",
        sido_code="11",
        sido_name="서울특별시",
        service_type="GENERAL",
        effective_date="2024-08-12",
        source=_SRC_SEOUL,
        description="서울특별시 일반용역 적격심사 (별표 1~4, 단순노무 외)",
        price_bands=_seoul_five_band_price(_SRC_SEOUL),
        threshold_bands=_threshold_30_10(_SRC_SEOUL),
    ),
    _local_rule(
        "SERVC_LOCAL_SEOUL_20240812_SIMPLE_LABOR",
        sido_code="11",
        sido_name="서울특별시",
        service_type="SIMPLE_LABOR",
        effective_date="2024-08-12",
        source=_SRC_SEOUL,
        description="서울특별시 일반용역 적격심사 (별표 1~4, 단순노무)",
        # 별표 1~4 단순노무 행은 전 구간 평점계수 20·기준비율 88 이고 통과점수가 95 라
        # 인천·제주·강원 단순노무와 같은 산식입니다. 구간별로 90-20x|88-투찰률|, 70-20x|88-투찰률|,
        # 50-20x|88-투찰률|, 30-20x|88-투찰률| 이 통과점수 95 의 필요 점수와 만나 모두 투찰률
        # 87.75% → 87.745% 가 됩니다(원문 _SRC_SEOUL).
        price_bands=_four_band_price(_SRC_SEOUL, simple_labor=True),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_SEOUL),
        lwlt_rate="87.745",
    ),
    # 부산광역시 (공고 제2025-1981호, 시행 2025-06-26) — 서울과 동일 구조
    _local_rule(
        "SERVC_LOCAL_BUSAN_20250626_ATTACH_01",
        sido_code="26",
        sido_name="부산광역시",
        service_type="GENERAL",
        effective_date="2025-06-26",
        source=_SRC_BUSAN,
        description="부산광역시 일반용역 적격심사 (별표 1, 단순노무 외)",
        # 별표 1 입찰가격 평가는 구간마다 낙찰하한율을 인쇄합니다(원문 :149). 10억원 이상은
        # 30억원 경계로 30억원 미만 77.995%, 30억원 이상 72.995% 로 갈립니다.
        price_bands=_five_band_price(
            _SRC_BUSAN,
            lwlt_rates=("87.745", "86.745", "85.495", "77.995", "72.995"),
        ),
        threshold_bands=_threshold_30_10(_SRC_BUSAN),
    ),
    _local_rule(
        "SERVC_LOCAL_BUSAN_20250626_SIMPLE_LABOR",
        sido_code="26",
        sido_name="부산광역시",
        service_type="SIMPLE_LABOR",
        effective_date="2025-06-26",
        source=_SRC_BUSAN,
        description="부산광역시 일반용역 적격심사 (별표 1, 단순노무)",
        # 단순노무 행의 낙찰하한율은 구간 구분 없이 87.745% 입니다(원문 :149).
        price_bands=_four_band_price(_SRC_BUSAN, simple_labor=True),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_BUSAN),
        lwlt_rate="87.745",
    ),
    # 대전광역시 구판 (공고 제2024-2호, 시행 2024-01-20) — 현행 규칙(공고 제2025-9528호,
    # 시행 2026-01-01) 시행일 이전 공고 전용. 같은 세부유형의 현행 규칙이 함께 등록되어
    # 공고일로 하나를 가립니다. 값 구조는 현행과 같습니다.
    _local_rule(
        "SERVC_LOCAL_DAEJEON_20240120_ATTACH_01",
        sido_code="30",
        sido_name="대전광역시",
        service_type="GENERAL",
        effective_date="2024-01-20",
        superseded_date="2026-01-01",
        source=_SRC_DAEJEON_20240120,
        cdw_exclusion="named",  # 원문: "⑥ '폐기물처리용역'이란 ... 다만 건설폐기물 처리용역은 제외한다." (.cache/local_src/daejeon/6cfe2e0ddf33_daejeon_2025_9528.txt, sha256 6cfe2e0ddf338fe1e5406dabc1f51c634980e447c713b3dbf0d681c922815077)
        description="대전광역시 일반용역 적격심사 (소프트웨어·폐기물처리·기타 일반용역, 구판)",
        # 별표 6 소프트웨어·폐기물처리·기타 일반용역 행은 구간마다 낙찰하한율을
        # 인쇄합니다. 10억원 이상은 30억원 경계로 30억원 미만 77.995%,
        # 30억원 이상 72.995% 로 갈립니다.
        price_bands=_five_band_price(
            _SRC_DAEJEON_20240120,
            lwlt_rates=("87.745", "86.745", "85.495", "77.995", "72.995"),
        ),
        threshold_bands=_threshold_30_10(_SRC_DAEJEON_20240120),
    ),
    _local_rule(
        "SERVC_LOCAL_DAEJEON_20240120_SIMPLE_LABOR",
        sido_code="30",
        sido_name="대전광역시",
        service_type="SIMPLE_LABOR",
        effective_date="2024-01-20",
        superseded_date="2026-01-01",
        source=_SRC_DAEJEON_20240120,
        description="대전광역시 일반용역 적격심사 (청소·시설물경비·시설물관리용역, 구판)",
        # 청소·시설물경비·시설물관리 행의 낙찰하한율은 구간 구분 없이 87.745% 입니다.
        price_bands=_four_band_price(_SRC_DAEJEON_20240120, simple_labor=True),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_DAEJEON_20240120),
        lwlt_rate="87.745",
    ),
    # 대전광역시 (공고 제2025-9528호, 시행 2026-01-01) — 별표 6 이 두 행 묶음으로 인쇄됩니다.
    _local_rule(
        "SERVC_LOCAL_DAEJEON_20260101_ATTACH_01",
        sido_code="30",
        sido_name="대전광역시",
        service_type="GENERAL",
        effective_date="2026-01-01",
        source=_SRC_DAEJEON,
        cdw_exclusion="named",  # 원문: "⑥ '폐기물처리용역'이란 ... 다만 건설폐기물 처리용역은 제외한다." (.cache/local_src/daejeon/6cfe2e0ddf33_daejeon_2025_9528.txt, sha256 6cfe2e0ddf338fe1e5406dabc1f51c634980e447c713b3dbf0d681c922815077)
        description="대전광역시 일반용역 적격심사 (소프트웨어·폐기물처리·기타 일반용역)",
        # 별표 6 소프트웨어·폐기물처리·기타 일반용역 행은 구간마다 낙찰하한율을
        # 인쇄합니다(원문 :262). 10억원 이상은 30억원 경계로 30억원 미만 77.995%,
        # 30억원 이상 72.995% 로 갈립니다.
        price_bands=_five_band_price(
            _SRC_DAEJEON,
            lwlt_rates=("87.745", "86.745", "85.495", "77.995", "72.995"),
        ),
        threshold_bands=_threshold_30_10(_SRC_DAEJEON),
    ),
    _local_rule(
        "SERVC_LOCAL_DAEJEON_20260101_SIMPLE_LABOR",
        sido_code="30",
        sido_name="대전광역시",
        service_type="SIMPLE_LABOR",
        effective_date="2026-01-01",
        source=_SRC_DAEJEON,
        description="대전광역시 일반용역 적격심사 (청소·시설물경비·시설물관리용역)",
        # 청소·시설물경비·시설물관리 행의 낙찰하한율은 구간 구분 없이 87.745% 입니다(원문 :262).
        price_bands=_four_band_price(_SRC_DAEJEON, simple_labor=True),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_DAEJEON),
        lwlt_rate="87.745",
    ),
    # 충청남도 구판 (공고 제2019-2047호, 시행 2020-02-01) — 현행 규칙 시행일 이전 공고 전용.
    _local_rule(
        "SERVC_LOCAL_CHUNGNAM_20200201_ATTACH_01",
        sido_code="44",
        sido_name="충청남도",
        service_type="FACILITY",
        effective_date="2020-02-01",
        superseded_date="2026-07-13",
        source=_SRC_CHUNGNAM_20200201,
        description="충청남도 시설분야용역 적격심사 (별표 1, 구판)",
        price_bands=(
            _local_price_band(
                "500000000",
                "70",
                "5",
                "추정가격 5억원 미만",
                _SRC_CHUNGNAM_20200201,
                base_rate="0.91",
            ),
            _local_price_band(
                None, "60", "5", "추정가격 5억원 이상", _SRC_CHUNGNAM_20200201, base_rate="0.91"
            ),
        ),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_CHUNGNAM_20200201),
        base_rate="0.91",
        lwlt_rate="87.995",
    ),
    _local_rule(
        "SERVC_LOCAL_CHUNGNAM_20200201_ATTACH_03",
        sido_code="44",
        sido_name="충청남도",
        service_type="WASTE",
        effective_date="2020-02-01",
        superseded_date="2026-07-13",
        source=_SRC_CHUNGNAM_20200201,
        description="충청남도 폐기물처리용역 적격심사 (별표 3, 구판)",
        lwlt_rate="84.245",
        price_bands=_chungnam_notice_band_price(_SRC_CHUNGNAM_20200201),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_CHUNGNAM_20200201),
    ),
    _local_rule(
        "SERVC_LOCAL_CHUNGNAM_20200201_ATTACH_04",
        sido_code="44",
        sido_name="충청남도",
        service_type="LAND_TRANSPORT",
        effective_date="2020-02-01",
        superseded_date="2026-07-13",
        source=_SRC_CHUNGNAM_20200201,
        description="충청남도 육상운송용역 적격심사 (별표 4, 구판)",
        lwlt_rate="84.245",
        price_bands=_chungnam_notice_band_price(_SRC_CHUNGNAM_20200201),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_CHUNGNAM_20200201),
    ),
    # 충청남도 (공고 2026-1235호, 시행 2026-07-13) — 별표 1·2·2의1·3·4·5 를 등록합니다.
    # 별표 2·3·4 는 배점 B 가 추정가격 5억원 축(미만 70·이상 60)이고 계수 k·기준비율·낙찰하한율이
    # 고시금액 축(미만 k4·84.245% / 이상 k2·80.495%)이라, 두 경계를 합친 3구간 price_bands 로
    # 표현합니다(2026-10-08 HWPX 원문 격자 검토·2026-10-09 재검증으로 계층 분리 확정).
    _local_rule(
        "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_01",
        sido_code="44",
        sido_name="충청남도",
        service_type="FACILITY",
        effective_date="2026-07-13",
        source=_SRC_CHUNGNAM_ATTACH_01,
        description="충청남도 시설분야용역 적격심사 (별표 1)",
        price_bands=(
            _local_price_band(
                "500000000",
                "70",
                "5",
                "추정가격 5억원 미만",
                _SRC_CHUNGNAM_ATTACH_01,
                base_rate="0.91",
            ),
            _local_price_band(
                None,
                "60",
                "5",
                "추정가격 5억원 이상",
                _SRC_CHUNGNAM_ATTACH_01,
                base_rate="0.91",
            ),
        ),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_CHUNGNAM_ATTACH_01),
        base_rate="0.91",
    ),
    _local_rule(
        "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_2_1",
        sido_code="44",
        sido_name="충청남도",
        service_type="SW_SME",
        effective_date="2026-07-13",
        source=_SRC_CHUNGNAM_ATTACH_2_1,
        description="충청남도 정보통신용역(중소기업자간 경쟁제품 대상) 적격심사 (별표 2의1)",
        lwlt_rate="87.995",
        price_bands=(
            _local_price_band(
                "500000000",
                "70",
                "4",
                "추정가격 5억원 미만",
                _SRC_CHUNGNAM_ATTACH_2_1,
                base_rate="0.91",
            ),
            _local_price_band(
                None,
                "60",
                "4",
                "추정가격 5억원 이상",
                _SRC_CHUNGNAM_ATTACH_2_1,
                base_rate="0.91",
            ),
        ),
        threshold_bands=_single_threshold("88", "전 구간 88", _SRC_CHUNGNAM_ATTACH_2_1),
        base_rate="0.91",
    ),
    _local_rule(
        "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_05",
        sido_code="44",
        sido_name="충청남도",
        service_type="FISHERY_CLEANUP",
        effective_date="2026-07-13",
        source=_SRC_CHUNGNAM_ATTACH_05,
        description="충청남도 해양환경관리 및 어장관리용역 적격심사 (별표 5)",
        # 별표 5 입찰가격 평점산식은 추정가격 5억원 미만 87.995%, 5억원 이상 80.495%
        # 낙찰하한율을 인쇄합니다(원문 :2334-2366). 공고 하한율이 없으면 이 구간값을 씁니다.
        price_bands=(
            _local_price_band(
                "500000000",
                "70",
                "5",
                "추정가격 5억원 미만",
                _SRC_CHUNGNAM_ATTACH_05,
                base_rate="0.91",
                lwlt_rate="87.995",
            ),
            _local_price_band(
                None,
                "60",
                "2",
                "추정가격 5억원 이상",
                _SRC_CHUNGNAM_ATTACH_05,
                base_rate="0.88",
                lwlt_rate="80.495",
            ),
        ),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_CHUNGNAM_ATTACH_05),
        base_rate="0.91",
    ),
    _local_rule(
        "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_02",
        sido_code="44",
        sido_name="충청남도",
        service_type="SW",
        effective_date="2026-07-13",
        source=_SRC_CHUNGNAM_ATTACH_02,
        description="충청남도 정보통신용역 적격심사 (별표 2)",
        # 고시금액 미만 k4·84.245% / 고시금액 이상 5억원 미만 k2·80.495% / 5억원 이상 B60·k2·
        # 80.495%. 규칙 대표값은 첫 구간(고시금액 미만) 인쇄값을 씁니다.
        lwlt_rate="84.245",
        price_bands=_chungnam_notice_band_price(_SRC_CHUNGNAM_ATTACH_02),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_CHUNGNAM_ATTACH_02),
    ),
    _local_rule(
        "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_03",
        sido_code="44",
        sido_name="충청남도",
        service_type="WASTE",
        effective_date="2026-07-13",
        source=_SRC_CHUNGNAM_ATTACH_03,
        description="충청남도 폐기물처리용역 적격심사 (별표 3)",
        # 별표 2 와 같은 3구간·같은 값입니다(고시금액 미만 k4·84.245% / 이상 k2·80.495%).
        lwlt_rate="84.245",
        price_bands=_chungnam_notice_band_price(_SRC_CHUNGNAM_ATTACH_03),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_CHUNGNAM_ATTACH_03),
    ),
    _local_rule(
        "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_04",
        sido_code="44",
        sido_name="충청남도",
        service_type="LAND_TRANSPORT",
        effective_date="2026-07-13",
        source=_SRC_CHUNGNAM_ATTACH_04,
        description="충청남도 육상운송용역 적격심사 (별표 4)",
        # 별표 2·3 과 같은 3구간·같은 값입니다(원문 3.4절 "별표 2 와 동일").
        lwlt_rate="84.245",
        price_bands=_chungnam_notice_band_price(_SRC_CHUNGNAM_ATTACH_04),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_CHUNGNAM_ATTACH_04),
    ),
    # 전북특별자치도 (부칙 제2024-10호, 시행 2024-01-18) — 서울과 동일 구조
    _local_rule(
        "SERVC_LOCAL_JEONBUK_20240118_ATTACH_01",
        sido_code="52",
        sido_name="전북특별자치도",
        service_type="GENERAL",
        effective_date="2024-01-18",
        source=_SRC_JEONBUK,
        cdw_exclusion="named",  # 원문: "③ '폐기물처리용역'이란 ... 단, 건설폐기물 및 음식물류 폐기물처리용역은 제외한다." (.cache/local_src/jeonbuk/2d58643f0a49_jb_general_2024_10.hwp5txt.txt, sha256 2d58643f0a498654f9d01460ab4e89a1e667b25da3d7c6cc8eb43062605b592a)
        description="전북특별자치도 일반용역 적격심사 (별표 1, 단순노무 외)",
        # 별표 1 단순노무 외 행은 구간마다 낙찰하한율을 인쇄합니다(원문 :127-145,
        # :357-366, :583-592, :792-799). 10억원 이상은 30억원 경계로 30억원 미만
        # 77.995%, 30억원 이상 72.995% 로 갈립니다.
        price_bands=_five_band_price(
            _SRC_JEONBUK,
            lwlt_rates=("87.745", "86.745", "85.495", "77.995", "72.995"),
        ),
        threshold_bands=_threshold_30_10(_SRC_JEONBUK),
    ),
    _local_rule(
        "SERVC_LOCAL_JEONBUK_20240118_SIMPLE_LABOR",
        sido_code="52",
        sido_name="전북특별자치도",
        service_type="SIMPLE_LABOR",
        effective_date="2024-01-18",
        source=_SRC_JEONBUK,
        description="전북특별자치도 일반용역 적격심사 (별표 1, 단순노무)",
        # 단순노무 행의 낙찰하한율은 구간 구분 없이 87.745% 입니다(원문 :140-143).
        price_bands=_four_band_price(_SRC_JEONBUK, simple_labor=True),
        threshold_bands=_single_threshold("95", "전 구간 95", _SRC_JEONBUK),
        lwlt_rate="87.745",
    ),
    # 대구광역시 (예규 제238호, 시행 2026-05-11) — 별표 4 폐기물처리용역
    _local_rule(
        "SERVC_LOCAL_DAEGU_20260511_ATTACH_04",
        sido_code="27",
        sido_name="대구광역시",
        service_type="WASTE",
        effective_date="2026-05-11",
        source=_SRC_DAEGU_ATTACH_04,
        description="대구광역시 폐기물처리용역 적격심사 (별표 4)",
        price_bands=(
            _local_price_band(
                "500000000",
                "70",
                "2",
                "지역제한 금액 미만",
                _SRC_DAEGU_ATTACH_04,
                lwlt_rate="80.495",
            ),
            _local_price_band(
                None, "60", "2", "지역제한 금액 이상", _SRC_DAEGU_ATTACH_04, lwlt_rate="80.495"
            ),
        ),
        threshold_bands=_single_threshold("85", "전 구간 85", _SRC_DAEGU_ATTACH_04),
        lwlt_rate="80.495",
        cdw_exclusion="band",
    ),
)
