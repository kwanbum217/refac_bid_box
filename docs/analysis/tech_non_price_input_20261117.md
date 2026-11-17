# 기술용역 비가격 점수 공고별 입력 경로 (2026-11-17)

> **작성일**: 2026-11-17
> **범위**: 조달청 기술용역 적격심사 공고(`SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT`, `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526`)에 비가격 점수(사업수행능력평가 등) 입력 경로를 열고, 입력이 없을 때 `PRICE_BOUNDS_UNRESOLVED` 대신 `TECH_NON_PRICE_REQUIRED` 로 안내
> **데이터**: 운영 DB 읽기 전용 조회. DB 접근은 전부 `scripts/db_readonly_query.py` 를 거쳤다.

---

## 1. 결론

- 두 기술용역 규칙에 새 정량 근거 `QUANT_BASIS_TECH_USER_INPUT` 을 선언하고, `_resolve_evaluation_inputs` 가 요청의 `manual_non_price_score` 를 그 공고의 비가격 점수로 쓴다.
- 입력이 없으면 `TECH_NON_PRICE_REQUIRED` 로 막고 "기술용역은 사업수행능력평가 등 비가격 점수를 공고마다 입력해야 통과 금액을 계산합니다." 를 안내한다. 기존 `PRICE_BOUNDS_UNRESOLVED` 는 입력 뒤에도 통과 구간을 만들 수 없을 때만 남는다.
- 회원 프로필의 `non_price_quant_score`(일반용역 정량점수)는 기술용역 비가격 점수로 대체하지 않는다. 지방 시·도 경로의 회원 저장값 대체와 `LOCAL_QUANT_REQUIRED` 는 바꾸지 않았다.
- 2026-06-01 이후 기술용역 적격심사 공고 4,177건 재생 결과, 입력이 없을 때 `TECH_NON_PRICE_REQUIRED` **3,720건**, 비가격 만점의 90%를 넣으면 **3,717건이 계산 가능(`OK`)** 이다. 같은 3,720건을 비가격 0점으로 계산하면 전부 `PRICE_BOUNDS_UNRESOLVED` 이므로, 새 차단 코드는 막다른 길이 아니라 입력 경로를 안내하는 코드다.
- 판정 스냅샷 비교에서 규칙 선택 변경은 **0건**이다.

---

## 2. 변경 내용

### 2.1 새 정량 근거

`src/app/services/evaluation_rules.py` 에 다음 상수를 두고 두 기술용역 규칙에 선언했다.

```python
QUANT_BASIS_TECH_USER_INPUT = "TECH_USER_INPUT"
```

- `REGISTRY`: 규칙이 선언한 정량 배점표를 쓴다.
- `AGENCY_DOCUMENT_NOT_LOADED`: 지방 시·도처럼 기관 원문 미반영이라 사용자가 정량점수를 직접 입력한다(기존).
- `TECH_USER_INPUT`: 기술용역처럼 비가격 점수를 공고마다 평가해, 요청의 `manual_non_price_score` 만 그 공고의 비가격 점수로 쓴다(신규).

`quant_score_table_for_rule` 은 `REGISTRY` 가 아닌 근거에 표를 붙이지 않으므로, 기술용역은 종전처럼 조달청 일반용역 정량 배점표를 잘못 적용하지 않는다.

### 2.2 입력 확정 순서

`src/app/api/v1/evaluations.py::_resolve_evaluation_inputs` 의 정량 분기에 기술용역 분기를 추가했다.

| 순서 | 조건 | 결과 |
| ---: | --- | --- |
| 1 | `quant_basis == AGENCY_DOCUMENT_NOT_LOADED` | 기존 지방 경로. 값이 없으면 `LOCAL_QUANT_REQUIRED` |
| 2 | `quant_basis == TECH_USER_INPUT` | 요청 `manual_non_price_score` 를 비가격 점수로 사용. 없으면 `TECH_NON_PRICE_REQUIRED` |
| 3 | `quant_table is None` | 정량 항목 입력이 있으면 `QUANT_ITEM_NOT_IN_TABLE` |
| 4 | 그 밖 | 레지스트리 배점표 검증 |

- `quant_source` 는 `USER_INPUT_UNVERIFIED`, `quant_notice` 는 "기술용역 비가격 점수는 공고별 사업수행능력평가 등으로 평가됩니다. 입력한 점수는 서버가 검증하지 않습니다." 다.
- 새 차단 코드는 `BLOCK_CODE_TECH_NON_PRICE_REQUIRED = "TECH_NON_PRICE_REQUIRED"` 이며, `/analyze` 와 `/recommend` 가 같은 공통 입력 확정 함수를 쓰므로 두 끝단이 같은 코드를 낸다. `/analyze` 의 차단 응답 분기에도 `tech_non_price` 단계를 추가했다.

### 2.3 회원 프로필 대체 금지

`_build_recommend_inputs` 는 요청 수정값이 없을 때 회원 프로필의 `non_price_quant_score` 로 `manual_non_price_score` 를 채웠다. 이 대체는 일반용역 정량점수이므로 기술용역에는 쓰지 않는다.

- `_is_tech_qualification_bid` 가 공고의 `srvceDivNm=기술용역` 과 낙찰방법명(코드가 `공고서참조` 일 때는 코드 계열명)의 `적격심사` 로 기술용역 여부를 판별한다.
- 판별 함수는 `evaluation_rules.is_servc_tech_qualification` 하나를 두고 규칙 판별 본문과 추천 입력 계층이 함께 쓴다.
- 지방 시·도 규칙(`AGENCY_DOCUMENT_NOT_LOADED`)은 종전대로 회원 저장값을 대체한다.

### 2.4 화면

`src/app/templates/bids/detail.html` 에 새 코드를 `LOCAL_QUANT_REQUIRED` 와 같은 "입력하면 계산 가능" 계열로 매핑했다.

| 위치 | 변경 |
| --- | --- |
| `getBlockedReasonText` | `TECH_NON_PRICE_REQUIRED` 사유 문구 |
| `getBlockedGuidanceText` | 입력 위치·미검증 고지 안내 |
| `localInputCodes` | 입력란 노출 코드에 추가 |
| `renderLocalInputs` | 제목 "기술용역 비가격 점수 입력", 힌트, 비가격 점수 입력란 노출 |
| 비가격 점수 라벨 | 기술용역이면 "비가격 점수(사업수행능력 등, 0~100)", 그 밖은 기존 "비가격 정량점수 (0~100)" |
| `scopeBadgeInputCodes` | "입력하면 계산 가능 · 비가격 점수 입력"(주황 배지) |

입력란은 기존 지방 경로와 같은 `#input-manual-non-price-score` 를 쓰고, 페이로드 필드명도 `manual_non_price_score` 그대로다. 새 Tailwind 클래스를 추가하지 않아 `npm run build:css` 후 `tailwind.css` 차이는 0이다.

---

## 3. 입력 범위와 배점 초과

- `manual_non_price_score` 는 스키마상 0~100 이다.
- 기술용역의 비가격 만점은 `100 - B`(구간별 70/50/30/10)지만, 초과 값을 막지 않는다. 기존 지방 경로도 `manual_non_price_score` 를 수행능력 점수로 그대로 넣고 배점한도와 대조하지 않으며, `quant_notice` 로 미검증을 알린다. 같은 방식을 따랐다.
- 초과 값을 넣으면 필요 가격점수가 낮아져 통과 구간이 넓어진다. 서버가 값을 검증하지 않는다는 사실은 응답의 `quant_notice` 와 화면 안내에 남는다.

---

## 4. 효과 측정

`docs/analysis/score_table_coverage_20261117.md` 2.2절의 5단계 재생과 같은 순서로 2026-06-01 이후 기술용역 적격심사 공고를 돌렸다. 여기에 6단계로 `compute_price_bounds` 를 붙여 실제 통과 금액 계산 가능 여부까지 셌다.

- 모집단: `Servc`, `sucsfbidMthdCd=낙030001`, `srvceDivNm=기술용역`, 2026-06-01 00:00 ~ 2026-11-18 00:00, 공고번호별 최신 차수, 취소공고 제외
- 재생 순서: (1) 규칙 판별 (2) 유효 낙찰하한율 (3) 예정가격 (4) 정량 배점표·구간 (5) B·k·T 확정 (6) 사정률 이론 범위의 최저가·최상가
- 비가격 입력: (1) 없음 (2) 구간별 비가격 만점의 90%(70→63, 50→45, 30→27, 10→9)
- DB: `scripts/db_readonly_query.py` 로만 읽음. 스크립트는 `/tmp` 일회성이며 저장소에 커밋하지 않았다.

| 구분 | 건수 |
| --- | ---: |
| 조회 행 | 6,013 |
| 취소공고 제외 | 693 |
| 재생 공고 | 4,177 |

### 4.1 비가격 입력 없음

| 판정 | 건수 |
| --- | ---: |
| `TECH_NON_PRICE_REQUIRED` | **3,720** |
| `MANUAL_EVALUATION` | 408 |
| `NON_PRED_PRICE` | 49 |
| 계산 가능(`OK`) | 0 |

- 같은 3,720건을 비가격 0점으로 끝까지 계산하면 전부 `PRICE_BOUNDS_UNRESOLVED` 다. 즉 종전에는 "계산 불가"로 보였던 건이 이제 "입력하면 계산 가능"으로 안내된다.
- 408건의 수기심사와 49건의 비예가는 1단계에서 막혀 이번 변경과 무관하다.

### 4.2 비가격 만점의 90% 입력

| 판정 | 건수 |
| --- | ---: |
| 계산 가능(`OK`) | **3,717** |
| `PRICE_BOUNDS_UNRESOLVED` | 3 |
| `MANUAL_EVALUATION` | 408 |
| `NON_PRED_PRICE` | 49 |

- 3,720건 가운데 3,717건(99.92%)이 입력 한 번으로 계산 가능해진다.
- 남은 3건은 공고 낙찰하한율이 100%(또는 `1` 이 비율 1.0 으로 정규화되는 값)로 수집된 이상값이라, 평점 통과 금액 상한이 하한율 금액보다 낮다.

| 공고 | 구간 | B·k·T | 비가격 90% | 공고 하한율 | 사유 |
| --- | --- | --- | ---: | ---: | --- |
| `R26BK01563352` 000 | 고시금액 미만 | 90·20·95 | 9 | 100 | 하한율 금액이 통과 상한보다 큼 |
| `R26BK01767298` 002 | 5억원 미만 고시금액 이상 | 70·4·95 | 27 | 100 | 〃 |
| `R26BK01771676` 001 | 10억원 이상 | 30·1·92 | 63 | 1(→100%) | 〃 |

- 선행 보고서(`docs/analysis/tech_score_table_20261117.md` 5장)의 4,173건과 4건 차이는 측정 시점 이후 수집된 공고다.
- 선행 보고서 7장의 "기술용역과 일반용역이 같은 `PRICE_BOUNDS_UNRESOLVED`" 서술은 이번 변경으로 기술용역에 한해 대체된다.

### 4.3 손검산(10억원 이상, B=30, k=1, T=92, 비가격 70)

- 필요 가격점수 `P = T - Q = 92 - 70 = 22` 로 배점한도 30 이하다.
- 사정률 이론 범위 ±2%: 예정가격 1,176,000,000원(하한)·1,224,000,000원(상한).
- 공고 하한율 87.495%, 비가격 70, 평탄 10억원 이상 구간(비율 0.98·점수 22)을 적용하면
  - 최저가 1,028,941,200원(1,176,000,000 × 0.87495)
  - 최상가 1,224,000,000원(비율 1.0, 평탄 22점 ≥ 필요 22점)
- 시험 `test_over_1b_with_non_price_70_releases_bounds` 가 같은 조건에서 `price_bounds.status=ok`, `min_bid_amount <= max_bid_amount` 를 고정한다.

---

## 5. 판정 비교

`scripts/judge_snapshot_diff.py` 로 main 기준 스냅샷과 변경 스냅샷을 비교했다. 기준일 2026-11-17, 12개월, `Servc`, 낙찰방법 코드 `낙030001` 이다.

| 항목 | 값 |
| --- | ---: |
| 기준 스냅샷 행 | 27,857 |
| 변경 스냅샷 행 | 27,869 |
| 바뀐 공고 | 26 |
| **판정 변경** | **0** |
| before 에만 있음 | 7 |
| after 에만 있음 | 19 |

- 판정 변경 0건은 규칙 선택 부작용이 없다는 회귀 확인이다. 이 스냅샷은 규칙 선택만 기록하므로 차단 해소 효과는 4장 재생으로 쟀다.
- before/after 에만 있는 26건은 기준 스냅샷 생성 이후 수집·소멸된 공고다(신규 19건, 기존 7건 소멸). 같은 공고의 판정이 바뀐 것이 아니다.

---

## 6. 시험

### 6.1 신규 시험 `tests/test_tech_non_price_input_20261117.py`

| 항목 | 시험 |
| --- | --- |
| (a) 입력이 없으면 `TECH_NON_PRICE_REQUIRED` | `test_recommend_requires_tech_non_price_input`, `test_analyze_requires_tech_non_price_input` |
| (b) 10억원 이상·비가격 70 이면 최저가·최상가 | `test_over_1b_with_non_price_70_releases_bounds`, `test_analyze_uses_tech_non_price_input` |
| (c) 통과 불가 값은 `PRICE_BOUNDS_UNRESOLVED` | `test_over_1b_with_non_price_50_blocks_on_price_bounds` |
| (d) 회원 프로필 정량점수를 쓰지 않음 | `test_tech_ignores_member_non_price_quant_score`, `test_tech_request_value_wins_even_with_member_score` |
| (e) 지방 경로 불변 | `test_local_path_still_uses_member_non_price_quant_score`, `test_local_path_still_blocks_without_any_non_price_score` |
| (f) 화면 문구·배지·라벨 | `test_detail_maps_tech_non_price_required_text`, `test_detail_shows_amber_badge_for_tech_non_price_required`, `test_detail_uses_tech_specific_input_label` |

### 6.2 기존 시험 변경

| 파일 | 시험 | 변경 |
| --- | --- | --- |
| `tests/test_tech_score_table_20261117.py` | `test_price_bounds_unresolved_matches_general_service_without_non_price_score` | `test_tech_without_non_price_requires_input_while_general_blocks_on_bounds` 로 이름을 바꾸고, 기술용역은 `TECH_NON_PRICE_REQUIRED`, 일반용역은 `PRICE_BOUNDS_UNRESOLVED` 로 단언을 나눴다 |
| 〃 | `test_tech_analyze_is_not_blocked_by_missing_score_table` | 분석 입력에 `manual_non_price_score=50` 을 넣어 `MISSING_SCORE_TABLE` 부재 확인을 유지했다 |
| 〃 | `test_tech_analyze_applies_flat_zone_to_price_score` | 같은 입력을 넣어 평탄 가격점수 확인을 유지했다 |
| 〃 | `test_tech_recommend_is_not_blocked_by_missing_score_table` | 추천 수정값에 `manual_non_price_score=50` 을 넣어 배점표·최저가·최상가 응답을 유지했다 |

기술용역의 `PRICE_BOUNDS_UNRESOLVED` 를 단언하던 다른 기존 시험은 없었다.

---

## 7. 검증

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_tech_non_price_input_20261117.py tests/test_tech_score_table_20261117.py tests/test_evaluations_api.py tests/test_evaluation_recommend.py tests/test_bid_detail_recommend_ui.py -q` | `131 passed` |
| `uv run pytest tests/ -q -m 'not data_assets'` | 아래 7.1 |
| `uv run mypy src` | `Success: no issues found in 152 source files` |
| `npm run build:css` | 성공, `git diff --exit-code -- src/app/static/css/tailwind.css` 차이 0 |
| `python3 scripts/validate_agent_rules.py --quiet` | 검증 통과: 22/22 건 |
| `uv run python scripts/judge_snapshot_diff.py diff ...` | 판정 변경 0건, exit 0 |

### 7.1 전량 시험

`uv run pytest tests/ -q -m 'not data_assets'` 결과 `11172 passed, 41 skipped, 3 deselected, 2 xfailed` (307.46s)다. 격리 워크트리에서 `data/model_files`·`chroma_db` 부재로 실패하는 데이터 자산 시험 2건은 `data_assets` 마커로 제외했다.

---

## 8. 남은 위험

- 공고 낙찰하한율이 100%(또는 1)로 수집된 3건은 비가격 입력 뒤에도 통과 금액이 없다. 수집 단계의 값 이상이며 이번 변경 범위 밖이다.
- `manual_non_price_score` 는 0~100 만 검증하고 구간별 비가격 만점(`100 - B`) 초과는 막지 않는다. 기존 지방 경로와 같은 동작이며, 초과 값은 통과 구간을 넓힌다.
- 기술용역 화면은 구간별 비가격 만점을 안내하지 않는다. 사용자는 공고문의 사업수행능력평가 배점을 직접 확인해야 한다.
- `/recommend` 는 회원 프로필의 일반용역 정량점수를 더 이상 기술용역에 쓰지 않으므로, 기술용역 공고에서 회원이 아무 값도 입력하지 않으면 항상 `TECH_NON_PRICE_REQUIRED` 가 먼저 보인다. 이는 의도된 동작이다.
