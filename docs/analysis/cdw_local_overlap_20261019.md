# 건설폐기물 고시 띠 표기 공고와 시·도 규칙의 겹침 조사

> **작성일**: 2026-10-19
> **조사 대상**: `.cache/cdw_band_notices.json` 의 낙찰방법명이 환경부고시 「건설폐기물처리용역 적격업체 평가기준」 띠 표기와 맞는 공고 3,042건.
> **정본 사양**: `.orca/capsules/task_cdw_local_overlap_20261019/capsule.yaml`
> **범위**: 조사 문서 한 건. 코드·규칙·원장은 변경하지 않았다. 판정 변경·권고는 쓰지 않는다.

## 1. 목적과 범위

낙찰방법명만으로는 건설폐기물 공고를 특정할 수 없어(띠 표기는 일반 용역 공고에도 쓰임), 공고명 문자열 포함 여부로 세 갈래를 나눴다. 각 갈래를 rule_id·시·도별로 집계하고, 시·도 규칙으로 계산되는 건설폐기물 공고가 있는 시·도마다 그 시·도 세부기준 원문의 폐기물처리용역 정의를 인용해 건설폐기물 제외 여부를 라벨했다. DB·docker·mysql 은 사용하지 않았다. 텍스트 추출은 `scripts/extract_score_params.py` 의 `extract_document_text` 를 사용했다.

## 2. 세 갈래 기준

- CDW: 공고명에 `건설폐기물` 포함.
- WASTE_OTHER: 공고명에 `폐기물` 은 있으나 `건설폐기물` 은 없음.
- NO_WASTE: 공고명에 `폐기물` 없음.

## 3. 3,042건의 세 갈래 × rule_id 집계

| rule_id | CDW | WASTE_OTHER | NO_WASTE | 합계 |
| --- | ---: | ---: | ---: | ---: |
| SERVC_QUAL_MOE_CDW_ATTACH_04 | 429 | 393 | 16 | 838 |
| SERVC_LOCAL_SEOUL_20240812_ATTACH_01 | 264 | 43 | 34 | 341 |
| SERVC_QUAL_MOE_CDW_ATTACH_03 | 215 | 107 | 2 | 324 |
| SERVC_LOCAL_GG_20250808_ATTACH_1_3 | 77 | 158 | 7 | 242 |
| SERVC_LOCAL_GN_20230105_ATTACH_01 | 70 | 115 | 1 | 186 |
| SERVC_LOCAL_JEONNAM_20230302_ATTACH_4_1_4 | 62 | 86 | 9 | 157 |
| SERVC_QUAL_MOE_CDW_ATTACH_02 | 92 | 22 | 1 | 115 |
| SERVC_LOCAL_GB_20260108_ATTACH_03 | 61 | 49 | 1 | 111 |
| SERVC_LOCAL_CB_20231020_ATTACH_01 | 28 | 77 | 1 | 106 |
| SERVC_LOCAL_CHUNGNAM_20200201_ATTACH_03 | 39 | 66 | 0 | 105 |
| SERVC_LOCAL_JEONBUK_20240118_ATTACH_01 | 65 | 34 | 3 | 102 |
| SERVC_LOCAL_GANGWON_20230611_ATTACH_01 | 26 | 58 | 0 | 84 |
| SERVC_LOCAL_JNGJ_20260716_ATTACH_03 | 30 | 21 | 2 | 53 |
| SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_03 | 21 | 22 | 0 | 43 |
| SERVC_LOCAL_GB_20241212_ATTACH_05 | 7 | 30 | 2 | 39 |
| SERVC_LOCAL_BUSAN_20250626_ATTACH_01 | 20 | 15 | 2 | 37 |
| SERVC_LOCAL_ULSAN_20220810_ATTACH_02 | 22 | 7 | 3 | 32 |
| SERVC_LOCAL_INCHEON_20251224_ATTACH_01 | 17 | 12 | 0 | 29 |
| SERVC_LOCAL_JEJU_20240101_ATTACH_01 | 9 | 17 | 0 | 26 |
| SERVC_QUAL_MOE_CDW_ATTACH_04A | 15 | 0 | 3 | 18 |
| SERVC_LOCAL_INCHEON_20241204_ATTACH_01 | 9 | 8 | 0 | 17 |
| SERVC_LOCAL_DAEJEON_20260101_ATTACH_01 | 8 | 3 | 0 | 11 |
| SERVC_LOCAL_SEJONG_20251201_ATTACH_04 | 3 | 4 | 0 | 7 |
| SERVC_LOCAL_DAEJEON_20240120_ATTACH_01 | 3 | 1 | 2 | 6 |
| SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_3_METRO_350 | 3 | 2 | 0 | 5 |
| None (LOCAL_SERVICE_TYPE_UNRESOLVED) | 0 | 0 | 3 | 3 |
| SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_3 | 2 | 1 | 0 | 3 |
| SERVC_LOCAL_GG_20250808_ATTACH_1_6 | 0 | 0 | 1 | 1 |
| SERVC_INST_KDHC_20260101_WASTE | 1 | 0 | 0 | 1 |
| **합계** | **1598** | **1351** | **93** | **3042** |

## 4. 시·도 규칙으로 계산되는 건설폐기물 공고 규모

CDW 갈래 중 rule_id 가 `SERVC_LOCAL_*` 인 공고 846건. 시·도별:

| 시·도 | 건수 | 주요 rule_id |
| --- | ---: | --- |
| 서울특별시 | 264 | SERVC_LOCAL_SEOUL_20240812_ATTACH_01 |
| 경기도 | 77 | SERVC_LOCAL_GG_20250808_ATTACH_1_3 |
| 경상남도 | 70 | SERVC_LOCAL_GN_20230105_ATTACH_01 |
| 경상북도 | 68 | SERVC_LOCAL_GB_20260108_ATTACH_03 (61), SERVC_LOCAL_GB_20241212_ATTACH_05 (7) |
| 전북특별자치도 | 65 | SERVC_LOCAL_JEONBUK_20240118_ATTACH_01 |
| 전남광주통합특별시 | 65 | SERVC_LOCAL_JEONNAM_20230302_ATTACH_4_1_4 (42), SERVC_LOCAL_JNGJ_20260716_ATTACH_03 (19), SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_3_METRO_350 (2), SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_3 (2) |
| 충청남도 | 60 | SERVC_LOCAL_CHUNGNAM_20200201_ATTACH_03 (39), SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_03 (21) |
| 전라남도 | 31 | SERVC_LOCAL_JEONNAM_20230302_ATTACH_4_1_4 (20), SERVC_LOCAL_JNGJ_20260716_ATTACH_03 (11) |
| 충청북도 | 28 | SERVC_LOCAL_CB_20231020_ATTACH_01 |
| 인천광역시 | 26 | SERVC_LOCAL_INCHEON_20251224_ATTACH_01 (17), SERVC_LOCAL_INCHEON_20241204_ATTACH_01 (9) |
| 강원특별자치도 | 26 | SERVC_LOCAL_GANGWON_20230611_ATTACH_01 |
| 울산광역시 | 22 | SERVC_LOCAL_ULSAN_20220810_ATTACH_02 |
| 부산광역시 | 20 | SERVC_LOCAL_BUSAN_20250626_ATTACH_01 |
| 대전광역시 | 11 | SERVC_LOCAL_DAEJEON_20260101_ATTACH_01 (8), SERVC_LOCAL_DAEJEON_20240120_ATTACH_01 (3) |
| 제주특별자치도 | 9 | SERVC_LOCAL_JEJU_20240101_ATTACH_01 |
| 세종특별자치시 | 3 | SERVC_LOCAL_SEJONG_20251201_ATTACH_04 |
| 광주광역시 | 1 | SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_3_METRO_350 |

CDW 갈래 중 환경부고시 규칙(SERVC_QUAL_MOE_CDW_*) 은 751건, 한국지역난방공사 기관 규칙(SERVC_INST_KDHC_20260101_WASTE) 은 1건이다.

## 5. 시·도 세부기준 원문의 폐기물처리용역 정의

라벨: `제외 있음` = 정의 또는 별도 조항에 건설폐기물 제외 문구가 있음. `제외 없음` = 정의가 있으나 건설폐기물 제외 문구가 없음. `미확보` = 수집된 원문에 폐기물처리용역 정의가 없음.

| 시·도 | 라벨 | 원문 인용(핵심 구절) | 근거 파일·URL | sha256 |
| --- | --- | --- | --- | --- |
| 대구광역시 | 제외 있음 | "5. '폐기물처리용역'이란 ... 이 경우 건설폐기물 처리용역은 제외한다." | .cache/local_src/daegu/856673076d70_elis_daegu_main.txt | 856673076d70e1e506aa03bfcb3bc87bb3e63da6edfe62b7c8a453fe338917c9 |
| 대전광역시 | 제외 있음 | "⑥ '폐기물처리용역'이란 ... 다만 건설폐기물 처리용역은 제외한다." | .cache/local_src/daejeon/6cfe2e0ddf33_daejeon_2025_9528.txt | 6cfe2e0ddf338fe1e5406dabc1f51c634980e447c713b3dbf0d681c922815077 |
| 경상북도 | 제외 있음 | "5. '폐기물처리용역'이란 ... (단 건설폐기물의 재활용 촉진에 관한 법률에 따른 '건설폐기물'은 제외한다.)" | .cache/local_src/gb/ab55faa1b1a3_gb_body.txt | ab55faa1b1a30752252aad8fc530fcd21d9f7141f3236e9df1fcd436b063e121 |
| 경기도 | 제외 있음 (별도 조항) | "3. 폐기물처리용역: ... 처리하는 영업을 말하며 ... 4. ... 건설폐기물 처리용역은 '건설폐기물처리용역 적격업체 평가기준'에 따른다." | .cache/local_src/gg/c231f0609a39_gg_g2b_20251210_coord.txt | c231f0609a398c298fd8dd45f1d0834dfbbfe94d35a58e631ad2ed492fa2fba9 |
| 강원특별자치도 | 제외 있음 | "3. '폐기물처리용역'이란 ... 단, 생활폐기물 수집·운반 대행용역 및 건설폐기물 처리용역은 제외한다." | .cache/local_src/gwd/0ab5d0ce1041_elis_gwd_main.txt | 0ab5d0ce10418097bb3f3ae6cb6bc1b30b73cf0e24560debea807ca4452892c0 |
| 전북특별자치도 | 제외 있음 | "③ '폐기물처리용역'이란 ... 단, 건설폐기물 및 음식물류 폐기물처리용역은 제외한다." | .cache/local_src/jeonbuk/2d58643f0a49_jb_general_2024_10.hwp5txt.txt | 2d58643f0a498654f9d01460ab4e89a1e667b25da3d7c6cc8eb43062605b592a |
| 세종특별자치시 | 제외 있음 | "5. '폐기물처리용역'이란 ... 다만, 생활폐기물처리용역 및 건설폐기물처리용역은 제외한다." | .cache/local_src/sejong/d9b290e93e43_sejong_body_2025.txt | d9b290e93e43fc979f73bb58ffb1bd2f7c9cd448bb27f954f9c4844c4b76e533 |
| 울산광역시 | 제외 있음 (부분) | "3. 폐기물처리용역이란 ... 단, 생활폐기물 수집·운반 대행용역 및 건설폐기물 처리용역은 제외하나 건설폐기물 중 중간처리를 포함하지 않는 수집·운반용역은 포함한다." | .cache/local_src/ulsan/c6a460417140_ulsan.txt | c6a460417140c9e849521fbc1489b53391d09ff21b2b885063ca30185382f829 |
| 인천광역시 | 제외 있음 | "3. 폐기물처리용역(건설폐기물 및 음식물류 폐기물은 제외한다) 적격심사 세부기준: 별표 2, 별표 3 및 별표 5" | ELIS https://www.elis.go.kr/allalr/selectAlrBdtOne?alrNo=28000032005015&histNo=007 | a44aa6b09defdd28d19665525640e112bfc4ed99cba659179a2fae62e2987c54 |
| 충청북도 | 제외 있음 (별도 조항) | "② 건설폐기물처리용역 적격심사는 이 세부기준 시행과 동시에 환경부고시 제2007-37호 '건설폐기물처리용역 적격업체 평가기준'을 적용한다." | .cache/local_src/cb/cb8c86236f3b_cb.txt | cb8c86236f3b688c7499718d50d05e378800e4860ee0df3622ea1118ba82c69e |
| 전남광주통합특별시 | 제외 없음 | "4. '폐기물처리용역'이란 ... 처리하는 영업을 말한다." (건설폐기물 문구 없음) | .cache/local_src/jn_gj/c5f948f52dce_jngj_jeongan.txt | c5f948f52dce4bf47e3702735ac7d254b6812a05937ad571d091a41319fd6b8c |
| 충청남도 | 제외 없음 | "라. '폐기물처리용역'이라 함은 ... 로 처리하는 영업을 말한다." (건설폐기물 문구 없음) | .cache/local_src/chungnam/d123ad901f6f_chungnam_2026_1235.txt | d123ad901f6f225a3d07f16e93c16f2c5c43bb764a598ac56cd8cffc67bc5e64 |
| 전라남도 | 제외 없음 | "5. '폐기물처리용역'이란 ... 처리하는 영업을 말한다." (건설폐기물 문구 없음) | ELIS https://www.elis.go.kr/allalr/selectAlrBdtOne?alrNo=46000007006065&histNo=005 | a57023e03b87639b7797e1b623db9c0770a5dc54850198638b659a4a5786826e |
| 광주광역시 | 제외 없음 | "5. '폐기물처리용역'이란 ... 처리하는 영업을 말한다." (건설폐기물 문구 없음) | ELIS https://www.elis.go.kr/allalr/selectAlrBdtOne?alrNo=29000068001145&histNo=007 | 5cd1433f04e4509b0d750a8b67d803d094c1e2520126df13f6c3e1c2d82be569 |
| 서울특별시 | 미확보 | 수집된 세부기준 원문(seoul_general_2024_08_12)에 폐기물처리용역 정의 없음 | .cache/local_src/seoul/8cf449ed49f4_seoul_general_2024_08_12.hwp | 8cf449ed49f4933a44e9b2f8aa6a5866897bf0022eb56b169158fcb055721dec |
| 부산광역시 | 미확보 | 수집된 세부기준 원문에 폐기물처리용역 정의 없음 | .cache/local_src/busan/242b87586a42_busan_general_2025_1981.txt | 242b87586a4284bc3db49bc75e028d7132efe3236895e5419d10d2d564cab126 |
| 경상남도 | 미확보 | 수집된 세부기준 원문에 폐기물처리용역 정의 없음 | .cache/local_src/gn/cea6c57cc30d_gn.txt | cea6c57cc30d7d77c38af9445064b56b8390e851754ec53cbee644bd02380048 |
| 제주특별자치도 | 미확보 | 수집된 세부기준 원문에 폐기물처리용역 정의 없음 | .cache/local_src/jeju/79a8f851701b_elis_jeju_main.txt | 79a8f851701b97949c3cfa94511879790c183551803011be151b167b5ecb6843 |

## 6. 부록: 재계산 스크립트

```python
import json
from collections import Counter, defaultdict
d = json.load(open('.cache/cdw_band_notices.json'))
def group(nm):
    if '건설폐기물' in nm: return 'CDW'
    if '폐기물' in nm: return 'WASTE_OTHER'
    return 'NO_WASTE'
print('total', len(d))
print(Counter(group(x['bid_ntce_nm']) for x in d))
pivot = defaultdict(lambda: defaultdict(int))
for x in d:
    pivot[x['rule_id'] or 'None'][group(x['bid_ntce_nm'])] += 1
for rid in sorted(pivot, key=lambda r: -sum(pivot[r].values())):
    g = pivot[rid]
    print(rid, g['CDW'], g['WASTE_OTHER'], g['NO_WASTE'], sum(g.values()))
# 시·도별 CDW + LOCAL
local_cdw = [x for x in d if '건설폐기물' in x['bid_ntce_nm']
             and (x['rule_id'] or '').startswith('SERVC_LOCAL')]
print('CDW LOCAL total', len(local_cdw))
for r, n in Counter(x['region_name'] for x in local_cdw).most_common():
    print(n, r)
```

## 7. 검증

- `uv run pytest tests/test_validate_doc_links.py -q -m 'not data_assets'`
- `python3 scripts/validate_agent_rules.py --quiet`
- 잔여 토큰 확인: `grep -n '<|' docs/analysis/cdw_local_overlap_20261019.md` (결과 없어야 함).
