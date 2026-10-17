# 개정 후 공고의 임대차·수리ㆍ점검·수요기관 지정형 적격심사 표기 매칭

> **작성일**: 2026-10-17
> **작업**: `task_726ec2471804` (Orca builder, run_5614217efbdd)
> **브랜치**: `kwanbum217/orca-post-rev-old-annex`
> **정본 사양**: [.orca/capsules/task_post_rev_old_annex_20261017/capsule.yaml](../../.orca/capsules/task_post_rev_old_annex_20261017/capsule.yaml)
> **선행 조사**: `docs/analysis/rule_not_found_rest_20261017.md` (RULE_NOT_FOUND 536건 중 375건이 개정 전 벌 전용 별표 표기)

---

## 1. 결론

조달청 일반용역 적격심사 세부기준 **제2026-260호(시행 2026-05-26)** 와 **제2026-390호(시행 2026-07-27)** 개정 전문에 [별표 7] 수리ㆍ점검용역, [별표 8] 임대차, [별표 9] 수요기관 지정형 적격심사가 **실재**합니다. 폐지되거나 다른 별표로 통합되지 않았습니다. 두 판의 배점한도·기준값·계수·통과점수·낙찰하한율이 모두 같습니다.

따라서 코드를 고쳤습니다. 개정 후 두 벌(`POST_20260526_RULES`, `POST_20260727_RULES`)에 원문 값으로 규칙 6종(별표마다 고시금액 미만·이상 2종)을 추가해, 개정 후 공고가 쓰는 세 표기가 `RULE_NOT_FOUND` 로 막히지 않고 그 별표로 계산됩니다. 2026-05-26 이전 공고의 판정과 값은 바뀌지 않았습니다.

---

## 2. 원문 출처 (조회일 2026-10-17)

내려받은 원문은 커밋하지 않고 `.cache/` 에만 두었습니다.

| 버전 | 문서 | 출처 | URL |
| --- | --- | --- | --- |
| 제2026-260호 | 개정 전문 PDF | 국가법령정보센터 | `https://www.law.go.kr/LSW/flDownload.do?flSeq=164496633` |
| 제2026-260호 | 개정 전문 HWPX | 조달청 누리집 고시 | `https://www.pps.go.kr/common/fileDown.do?key=202605220020&sn=3` |
| 제2026-260호 | 분야별 낙찰하한율 안내_260526(수정) HWPX | 조달청 누리집 고시 | `https://www.pps.go.kr/common/fileDown.do?key=202605220020&sn=4` |
| 제2026-260호 | 고시 화면(첨부 목록) | 조달청 누리집 | `https://www.pps.go.kr/kor/bbs/view.do?key=00030&bbsSn=2605220029` |
| 제2026-390호 | 개정 전문 HWPX | 조달청 누리집 고시 | `https://www.pps.go.kr/common/fileDown.do?key=202607240030&sn=3` |
| 제2026-390호 | 분야별 낙찰하한율 안내_260727 HWPX | 조달청 누리집 고시 | `https://www.pps.go.kr/common/fileDown.do?key=202607240030&sn=2` |
| 제2026-390호 | 고시 화면(첨부 목록) | 조달청 누리집 | `https://www.pps.go.kr/kor/bbs/view.do?key=00030&bbsSn=2607240033` |
| 연혁 | 제2026-390호 시행 확인 | 국가법령정보센터 | `https://www.law.go.kr/admRulLsInfoP.do?admRulId=33121&efYd=0` |

제2026-260호 PDF 는 별표 계산식이 심볼 폰트의 사용자 정의 영역(U+E0xx)으로 실려 있어, 글리프를 대응시켜 읽었습니다. `0.375`(별표 6 보험 계수)와 `-5`(별표 2 시설 계수)로 숫자 대응을 고정한 뒤 별표 7~9 의 기준값 글리프가 `90`, 계수 글리프가 `2`/`4` 임을 확인했습니다. 제2026-390호 HWPX 는 `hp:equation` 스크립트 18개가 그대로 실려 있어 같은 값을 이중 확인했습니다.

---

## 3. 별표별 원문 근거

### 3.1 제2026-260호 (시행 2026-05-26)

| 항목 | [별표 7] 수리ㆍ점검용역 | [별표 8] 임대차 | [별표 9] 수요기관 지정형 |
| --- | --- | --- | --- |
| 원문 위치 | 개정 전문 p.38 | 개정 전문 p.41 | 개정 전문 p.43 |
| 입찰가격 배점한도 | 5억원 이상 60 / 미만 70 | 70 단일 | 60점 이상 70점 이하 (수요기관 선택) |
| 입찰가격 계산식 | `배점한도 − 2 × abs(90/100 − 입찰가격/예정가격) × 100` (고시금액 이상)<br>`배점한도 − 4 × abs(90/100 − ...) × 100` (고시금액 미만) | 좌동 | 좌동 |
| 기준값 | **90** | **90** | **90** |
| 계수 | **2 / 4** | **2 / 4** | **2 / 4** |
| 예외 상한 | 예정가격의 97.5% / 93.75% 이상이면 그 지점 점수로 평가 | 좌동 | 좌동 |
| 통과점수 (제10조) | **85점** | **85점** | **85점** |
| 낙찰하한율 (분야별 안내) | 고시금액 미만 **86.245%** / 이상 **82.495%** | 좌동 | 좌동 |
| 해당용역 수행능력 계 | 40 (5억원 이상) / 30 (미만) | 30 | 100 − 입찰가격 |
| 경영상태·기술능력·신인도 | 신용평가 10/20, 기술신용 10/0, 신인도 +4.25~-5.0 | 신용평가 20, 사후관리(A/S) 10, 신인도 +4.25~-5.0 | 경영상태 10~30, 이행실적 ≤30, 기술능력 ≤20, 사후관리(A/S) ≤10, 기타 수행능력 ≤5 |

제10조 본문은 "종합평점이 85점(다만, 소프트웨어용역의 중소기업자간 경쟁제품, 여객 육상운송용역은 88점)이상이면 낙찰자로 결정한다" 이므로, 세 별표의 통과점수는 기타 분야 85점입니다. 분야별 낙찰하한율 안내는 "[별표7] 수리·점검용역, [별표8] 임대차, [별표9] 수요기관 지정형" 을 별표 1·3·4·5의2 와 한 묶음으로 두고 "고시금액 미만 85점 86.245% / 고시금액 이상 82.495%" 를 인쇄합니다.

### 3.2 제2026-390호 (시행 2026-07-27) — 세 별표가 그대로 남아 있는지

| 확인 항목 | 결과 | 근거 |
| --- | --- | --- |
| [별표 7]·[별표 8]·[별표 9] 실재 | **실재.** 개정 전문에 `[별표 7] (제5조제1항제7호 관련) 수리ㆍ점검용역 적격심사`, `[별표 8] (제5조제1항제8호 관련) 임대차 적격심사`, `[별표 9] (제5조제1항제9호 관련) 수요기관 지정형 적격심사` | 개정 전문 HWPX 조문 |
| 제5조 제1항 목록 | `7. 수리ㆍ점검용역 평가기준 : 별표 7`, `8. 임대차 평가기준 : 별표 8`, `9. 수요기관 지정형 평가기준 : 별표 9` | 개정 전문 HWPX |
| 입찰가격 배점한도 | 별표 7 = 60/70, 별표 8 = 70, 별표 9 = 60점 이상 70점 이하 (260호와 같음) | 개정 전문 HWPX 표 |
| 기준값·계수 | `hp:equation` 18개 중 별표 7~9 에 해당하는 6개가 모두 기준값 `90`, 계수 `2`/`4` (260호와 같음) | 개정 전문 HWPX 수식 스크립트 |
| 통과점수·낙찰하한율 | "고시금액 미만 85점 86.245% / 고시금액 이상 82.495%" 에 별표 7·8·9 포함 | 분야별 낙찰하한율 안내_260727 |

즉 제2026-390호는 세 별표를 **바꾸지 않았습니다.** 그래서 개정 후 두 벌이 같은 규칙 객체를 재사용하며, 제2026-390호 전용 규칙 ID 를 새로 만들지 않았습니다(제2026-260호 판의 규칙 ID `SERVC_QUAL_POST_20260526_ATTACH_15~20` 을 그대로 씁니다). 이는 값이 바뀐 여객(`ATTACH_03`)·SW 대상(`ATTACH_04`)만 390 전용 ID 를 새로 서는 기존 처리와 같은 규칙입니다.

### 3.3 개정 전후 비교

| 항목 | 개정 전 (제2025-257호·제2026-15호) | 개정 후 (제2026-260호·제2026-390호) | 변화 |
| --- | --- | --- | --- |
| 기준비율 | 0.88 | **0.90** | +2 |
| 낙찰하한율 | 단일 84.245% | **고시금액 미만 86.245% / 이상 82.495%** | 두 구간으로 분리 |
| 계수 | 2 / 4 | 2 / 4 | 변동 없음 |
| 통과점수 | 85 | 85 | 변동 없음 |
| 입찰가격 배점한도 | 별표 7 = 60/70, 별표 8 = 70, 별표 9 = 60~70 | 같음 | 변동 없음 |
| 규칙 벌 | 별표마다 한 규칙 (`ATTACH_15`·`16`·`17`) | 고시금액 구간마다 한 규칙 (`ATTACH_15`~`20`) | 하한율이 갈려 분리 |

별표 7~9 의 개정 후 기준비율은 별표 1·3·4·5의2 와 같은 0.90 이고, 하한율도 같은 두 구간입니다. 별표 2·3의2·5·6 만 기준비율이 따로 갑니다(0.93 / 0.91 / 0.91 / 0.88).

---

## 4. 구현

`src/app/services/evaluation_rules.py` 한 파일입니다.

| 변경 | 내용 |
| --- | --- |
| 규칙 6종 추가 | `SERVC_QUAL_POST_20260526_ATTACH_15`~`_20`. 별표 7~9 각각 고시금액 미만·이상 두 규칙입니다. `POST_20260727_RULES` 는 `POST_20260526_RULES[4:]` 를 그대로 이어받아 두 벌에 함께 들어갑니다 |
| 배점표 선언 | `_SCORE_TABLE_DECLARATIONS` 에 여섯 항목. 별표 7 은 B 조건부(70/60), 별표 8 은 B=70 단일, 별표 9 는 B 미확정(공고문 값), 셋 다 k 조건부(4/2)·T=85 |
| 조건부 축 | `_has_conditional_axis` 의 개정 후 B 집합에 15·16, k 집합에 15~20 을 넣었습니다 |
| 주석 정정 | 규칙 벌 크기를 적은 두 주석을 실제 값(규칙 20종)으로 고쳤습니다 |

선언한 값은 전부 원문에서 온 것이며 개정 전 규칙에서 옮기지 않았습니다. 근거는 `score_table_source` 에 남아 있고, 개정 전 값(0.88·84.245)과 다르다는 사실을 `tests/test_post_rev_old_annex.py` 가 고정합니다.

매칭 `patterns` 는 DB 의 실제 낙찰방법명 표기를 그대로 옮겼습니다.

| 규칙 | patterns |
| --- | --- |
| `ATTACH_15` | `수리ㆍ점검용역 적격심사 고시금액 미만`, `수리ㆍ점검용역 적격심사 추정가격 고시금액 미만` |
| `ATTACH_16` | `수리ㆍ점검용역 적격심사 5억원 미만 고시금액 이상`, `수리ㆍ점검용역 적격심사 5억원 이상` |
| `ATTACH_17`·`_18` | `임대차 적격심사 추정가격 고시금액 미만` / `…이상` |
| `ATTACH_19`·`_20` | `수요기관 지정형 적격심사  추정가격 고시금액 미만` / `…이상` (두 칸 공백이 DB 표기), 한 칸 표기 병기 |

가운뎃점은 DB 와 같은 U+318D(`ㆍ`)입니다. `normalize_pattern_string` 이 공백을 지우므로 이중 공백은 매칭에 영향이 없지만, DB 표기를 그대로 남겨 원문 대조가 되게 했습니다.

---

## 5. DB 실측 — 최근 12개월 해당 표기와 풀리는 상한

`uv run python scripts/db_readonly_query.py --sql "<질의>"` 만 사용했습니다.

```sql
SELECT JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidMthdNm')) AS mthd,
       SUM(bid_ntce_dt >= '2026-07-27') AS post_390,
       SUM(bid_ntce_dt >= '2026-05-26' AND bid_ntce_dt < '2026-07-27') AS post_260,
       SUM(bid_ntce_dt < '2026-05-26') AS pre,
       COUNT(*) AS total_12m
FROM bid_announcements
WHERE category = 'Servc'
  AND bid_ntce_dt >= DATE_SUB(NOW(), INTERVAL 12 MONTH)
  AND (JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidMthdNm')) LIKE '%임대차%'
    OR JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidMthdNm')) LIKE '%수리%'
    OR JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.sucsfbidMthdNm')) LIKE '%수요기관 지정형%')
GROUP BY mthd
ORDER BY total_12m DESC
```

| 표기 | 390 구간 | 260 구간 | 개정 전 | 12개월 합 |
| --- | ---: | ---: | ---: | ---: |
| 적격심사제-수리ㆍ점검용역 적격심사 고시금액 미만 | 59 | 35 | 252 | 346 |
| 적격심사제-임대차 적격심사 추정가격 고시금액 미만 | 67 | 76 | 183 | 326 |
| 적격심사제-수요기관 지정형 적격심사  추정가격 고시금액 미만 | 67 | 38 | 117 | 222 |
| 적격심사제-임대차 적격심사 추정가격 고시금액 이상 | 21 | 22 | 87 | 130 |
| 적격심사제-수리ㆍ점검용역 적격심사 5억원 미만 고시금액 이상 | 5 | 15 | 79 | 99 |
| 적격심사제-수요기관 지정형 적격심사  추정가격 고시금액 이상 | 10 | 11 | 42 | 63 |
| 적격심사제-수리ㆍ점검용역 적격심사 5억원 이상 | 1 | 7 | 12 | 20 |
| 적격심사제-수리ㆍ점검용역 적격심사 추정가격 고시금액 미만 | 4 | 3 | 11 | 18 |

별표별로 묶으면 다음과 같습니다.

| 별표 | 개정 전 | 260 구간 | 390 구간 | 12개월 합 |
| --- | ---: | ---: | ---: | ---: |
| 별표 7 수리ㆍ점검 (고시금액 미만) | 263 | 38 | 63 | 364 |
| 별표 7 수리ㆍ점검 (고시금액 이상) | 91 | 22 | 6 | 119 |
| 별표 8 임대차 (고시금액 미만) | 183 | 76 | 67 | 326 |
| 별표 8 임대차 (고시금액 이상) | 87 | 22 | 21 | 130 |
| 별표 9 수요기관 지정형 (고시금액 미만) | 117 | 38 | 67 | 222 |
| 별표 9 수요기관 지정형 (고시금액 이상) | 42 | 11 | 10 | 63 |
| **합계** | **783** | **207** | **234** | **1,224** |

**이번 변경으로 규칙이 풀리는 상한은 최근 12개월 441건**(260 구간 207 + 390 구간 234)입니다. 나머지 783건은 개정 전 공고로 기존 `PRE_20250901_RULES` 가 계속 담당하며 판정이 바뀌지 않습니다. 선행 조사의 375건은 그 조사 창에서 `RULE_NOT_FOUND` 로 차단된 부분집합이라 이 수치와 다릅니다.

---

## 6. 검증 결과

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_post_rev_old_annex.py tests/test_evaluation_rules_post.py -q -m 'not data_assets'` | **160 passed** |
| `uv run pytest tests/ -q -m 'not data_assets'` | **15 failed, 7834 passed, 41 skipped, 3 deselected in 248.17s** (커밋 트리에서 측정. 커밋 전 실행도 실패 15건·통과 7834건으로 같았고 시간만 247.56s 였습니다) |
| `uv run mypy src` | **Success: no issues found in 135 source files** |
| `python3 scripts/validate_agent_rules.py --quiet` | **검증 통과: 21/21 건** |
| `uv run ruff check` / `ruff format --check` (변경 3파일) | **All checks passed / 3 files already formatted** |

### 6.1 규칙 수 14 단정 때문에 실패한 시험 (기대 실패)

아래 15건은 모두 **개정 후 규칙 벌이 14종에서 20종으로 늘어난 것**이 원인이며, 다른 결함이 아닙니다. `allowed_write_files` 밖 파일이라 고치지 않았고, 개수 단정과 `scope_note` 문구는 코디네이터가 병합 시 코디네이터 브랜치에서 고칩니다.

| # | 노드 ID | 실패 메시지 | 그 단정 때문인 근거 |
| ---: | --- | --- | --- |
| 1 | `tests/test_evaluation_rules_meta_api.py::test_rules_endpoint_returns_fourteen_rows_without_auth` | `assert 20 == 14` | 응답 별표 행 수와 `len(POST_20260727_RULES)` 를 14로 단정 |
| 2 | `tests/test_evaluation_rules_meta_api.py::test_institution_rules_are_excluded_from_meta_list` | `assert 20 == 14` | `len(payload["rules"]) == 14` 단정 |
| 3 | `tests/test_evaluation_rules_meta_api.py::test_bid_id_returns_institution_matched_rule` | `assert 20 == 14` | 같은 14행 단정 |
| 4 | `tests/test_evaluation_rules_meta_api.py::test_bid_id_returns_matched_rule` | `assert 20 == 14` | 같은 14행 단정 |
| 5 | `tests/test_evaluation_rules_meta_api.py::test_bid_id_without_match_returns_null_and_list_only` | `assert 20 == 14` | 같은 14행 단정 |
| 6 | `tests/test_evaluation_rules_pre.py::TestPost20260727Declaration::test_bundle_has_fourteen_unique_ids` | `assert 20 == 14` | `len(POST_20260727_RULES) == 14` 와 규칙 ID 목록 `range(5, 15)` 단정 |
| 7 | `tests/test_evaluation_rules_pre.py::TestPreRegimeResolution::test_post_period_does_not_gain_pre_only_attachments` | `assert False is True` (`result.is_blocked`) | 2026-06-01 수리ㆍ점검 표기가 `RULE_NOT_FOUND` 로 막힌다는 단정. 이번 과업이 없애려던 바로 그 차단이며, 이제 `ATTACH_15` 로 계산됨 |
| 8 | `tests/test_evaluation_rules_pre.py::TestPostRegimeRegression::test_post_registry_is_untouched` | `assert 20 == 14` | `len(POST_20260526_RULES) == 14` 단정 |
| 9 | `tests/test_evaluation_rules_pre.py::TestExplicitRulesCalls::test_match_rule_by_mthd_nm_default_stays_post_bundle` | `assert EvaluationRule(rule_id='SERVC_QUAL_POST_20260526_ATT…')` | 기본 벌이 수리ㆍ점검 표기를 못 푼다는 단정(`match_rule_by_mthd_nm(...) is None`). 이제 `ATTACH_15` 를 돌려줌 |
| 10 | `tests/test_evaluation_rules_pre.py::TestScoreTableDeclaration::test_all_rules_carry_a_declaration_source` | `assert 48 == 42` | 개정 3세대 규칙 합계를 42로 단정(개정 후만 6종 증가: 14+14+20=48) |
| 11 | `tests/test_evaluation_scoring.py::TestEvaluationRulesRegistry::test_post_20260526_rules_count` | `assert 20 == 14` | `len(list_all_rules()) == 14` 단정 |
| 12 | `tests/test_evaluation_scoring.py::TestEvaluationRulesRegistry::test_all_14_rules_have_correct_rates_and_metadata` | `assert 'SERVC_QUAL_POST_20260526_ATTACH_15' in {…}` | 기대 낙찰하한율 사전이 14종 ID 로 닫혀 있어 새 규칙 ID 가 사전에 없음 |
| 13 | `tests/test_evaluations_realuse_scenarios.py::test_real_star_cases_cover_all_registry_rule_ids` | 집합 불일치, 우변에 `ATTACH_15`~`_20` 추가 | 실공고 표본 14건이 규칙 벌 전체를 덮는다는 단정 |
| 14 | `tests/test_evaluations_realuse_scenarios.py::test_real_registry_contains_fourteen_rules` | `assert 20 == 14` | `len(POST_20260526_RULES) == 14` 단정 |
| 15 | `tests/test_seoul_10eok_lwlt.py::test_national_rules_unchanged` | SHA-256 불일치 `c56ccd81… != 3436d7f5…` | 조달청 개정 전·후 규칙 전체의 서명 다이제스트를 고정한 상수. 규칙 6종이 늘어 다이제스트가 바뀜 |

기대 실패는 위 15건뿐이며 그 밖의 원인으로 실패한 시험은 없습니다. 같은 실행에서 `tests/test_seoul_10eok_lwlt.py::test_other_local_rules_unchanged`(지방계약 규칙)와 `tests/test_evaluation_rules_pre.py::TestPostRegimeRegression::test_all_post_rules_keep_rule_id_lwlt_rate_and_base_rate` 는 통과했으므로, 지방 규칙과 개정 후 기존 14종의 값·되돌이 매칭에는 회귀가 없습니다.

### 6.2 코디네이터가 병합 시 처리할 것

| 대상 | 처리 |
| --- | --- |
| 위 15건의 개수 단정(14 → 20)과 규칙 ID 목록 | 코디네이터 브랜치에서 갱신 |
| `src/app/api/v1/evaluations.py:2609` 의 `scope_note` 문구 "조달청 일반용역 적격심사 별표 14종" | 실재하는 목록 크기로 갱신 |
| `tests/test_seoul_10eok_lwlt.py` 의 `NATIONAL_RULES_DIGEST` | 새 서명으로 재고정 |
| `data/reference/rule_coverage_ledger.yaml` | 새 규칙 6종 등재 |

---

## 7. 남은 선택지

원문에 대응 별표가 없어 코드를 고치지 않는 경우는 발생하지 않았습니다. 별표 7~9 가 두 판에 모두 실재하므로 매칭 규칙을 넣는 쪽이 정본에 맞습니다. 다만 다음은 이번 범위 밖으로 남겨 둡니다.

- **추정가격 띠만 있는 표기**(예: "추정가격 15억원 미만 5억원 이상인 용역")는 정본 사양대로 손대지 않았습니다.
- **수요기관 지정형의 입찰가격 배점한도**는 원문이 "60점 이상 70점 이하"로 수요기관 선택에 맡기므로 값을 만들지 않고 `_SCORE_NOTE_B_MANUAL` 사유만 남겼습니다. 공고문 값 입력 경로가 필요합니다.
- **분야별 낙찰하한율 안내의 나머지 분야**(별표 1·3·4·5의2)는 이미 코드에 같은 값이 있어 그대로 두었습니다.
