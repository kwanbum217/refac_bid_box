# 공고 명시 기준 라우팅 두 경로 (2026-11-18)

> 작성일: 2026-11-18
> 브랜치: kwanbum217/orca-stated-route
> 정본: .orca/capsules/task_stated_basis_routing_20261118/capsule.yaml

---

## 1. 변경 요약

공고의 낙찰방법 적용 기준(`raw_data.sucsfbidMthdAppStd`)을 시·도 분기보다 먼저 보는
두 경로를 `src/app/services/evaluation_rules.py` 에 추가했습니다. 기존 시·도 분기가
먼저 차단하던 공고만 대상이며 새 rule id 나 규칙 값은 만들지 않았습니다.

| 경로 | 조건 | 결과 |
| --- | --- | --- |
| 환경부고시 | `MOE_CDW_STATED_MARKER` + 낙찰방법명이 고시 띠 표기 6종 일치 + 차단 코드 `LOCAL_SERVICE_TYPE_UNRESOLVED` | 환경부고시 [별표] 해당 호, `MOE_CDW_STATED_WARNING` |
| 조달청 | `_PPS_STATED_MARKER` + 차단 코드 `LOCAL_RULE_NOT_FOUND` + 조달청 매칭 결과 비차단 + 공고일이 그 규칙 시효 구간 | 조달청 매칭 규칙, `JNGJ_STATED_PPS_WARNING` |

`_is_moe_cdw_fallback_target` 에 명시 표지·띠 표기 조건을 인자로 받는 분기를 더했고,
시·도 규칙 미발견 분기 뒤에 지역을 가리지 않는 조달청 명시 분기를 추가했습니다.

---

## 2. 경계

- 환경부고시 경로는 표지와 띠 표기가 모두 맞을 때만 열립니다. 시·도 규칙이 정상 선택된
  공고와 띠 표기가 다른 공고는 종전 판정을 유지합니다.
- 조달청 경로는 `LOCAL_RULE_NOT_FOUND` 이고 조달청 매칭 결과가 있으며 그 규칙의 시효
  구간에 공고일이 들 때만 열립니다. 명시가 없거나 지역 기준(예규 제1075호 등)을 명시한
  공고, 조달청 매칭이 없는 공고, 건설폐기물 띠 표기, 시효 이전 공고는 종전 차단입니다.
- 통합특별시·대구·충남 분기는 그대로 앞에서 처리되어 결과가 바뀌지 않습니다. 부산
  인력공급 자동 매핑 공고(R25BK01244020)도 종전 `LOCAL_SERVICE_TYPE_UNRESOLVED` 입니다.

---

## 3. 판정 비교

기준 스냅숏 `.orca/judge_base_20261118.tsv`(51,303건)와 같은 옵션으로 뜬 최종 덤프를
공고 키 교집합으로 맞춰 비교했습니다. 원시 덤프는 51,357건이었고, 기준 이후 새로 수집된
26건과 오늘 취소 재공고로 최신 차수가 바뀐 2건(R26BK01838981·R26BK01839161)은 규칙
변경과 무관해 비교 코호트에서 제외했습니다.

```sh
uv run python scripts/judge_snapshot_diff.py dump --months 24 --as-of 2026-11-18 --output "$TMP/after.tsv"
uv run python scripts/judge_snapshot_diff.py diff "$TMP/before_cohort.tsv" "$TMP/after_cohort.tsv" --expect "$TMP/expect.txt"
```

```
공고 before 51301건, after 51301건
바뀐 공고 12건(판정 변경 12건, before 만 0건, after 만 0건)
  [판정 변경] R25BK00729411 001  BLOCKED -> PPS_DEFAULT  SERVC_QUAL_PRE_20230501_ATTACH_03
  [판정 변경] R25BK00760557 000  BLOCKED -> PPS_DEFAULT  SERVC_QUAL_PRE_20230501_ATTACH_15
  [판정 변경] R25BK00775634 000  BLOCKED -> PPS_DEFAULT  SERVC_QUAL_PRE_20230501_ATTACH_16
  [판정 변경] R25BK00778916 000  BLOCKED -> PPS_DEFAULT  SERVC_QUAL_PRE_20230501_ATTACH_15
  [판정 변경] R25BK00864238 000  BLOCKED -> PPS_DEFAULT  SERVC_QUAL_PRE_20230501_ATTACH_06
  [판정 변경] R25BK00876620 000  BLOCKED -> PPS_DEFAULT  SERVC_QUAL_PRE_20230501_ATTACH_06
  [판정 변경] R25BK00883763 000  BLOCKED -> PPS_DEFAULT  SERVC_QUAL_MOE_CDW_ATTACH_04
  [판정 변경] R25BK00925563 000  BLOCKED -> PPS_DEFAULT  SERVC_QUAL_PRE_20230501_ATTACH_02
  [판정 변경] R26BK01531664 000  BLOCKED -> PPS_DEFAULT  SERVC_QUAL_PRE_20250901_ATTACH_06
  [판정 변경] R26BK01589681 000  BLOCKED -> PPS_DEFAULT  SERVC_QUAL_POST_20260526_ATTACH_02
  [판정 변경] R26BK01653130 000  BLOCKED -> PPS_DEFAULT  SERVC_QUAL_POST_20260526_ATTACH_18
  [판정 변경] R26BK01817736 000  BLOCKED -> PPS_DEFAULT  SERVC_QUAL_MOE_CDW_ATTACH_04
[expect] 일치: 12건
```

| 공고번호 | 차수 | 지역 | 이전 차단 코드 | 이후 rule id |
| --- | --- | --- | --- | --- |
| R25BK00729411 | 001 | 충청광역연합 | LOCAL_RULE_NOT_FOUND | SERVC_QUAL_PRE_20230501_ATTACH_03 |
| R25BK00760557 | 000 | 경상남도 | LOCAL_RULE_NOT_FOUND | SERVC_QUAL_PRE_20230501_ATTACH_15 |
| R25BK00775634 | 000 | 세종특별자치시 | LOCAL_RULE_NOT_FOUND | SERVC_QUAL_PRE_20230501_ATTACH_16 |
| R25BK00778916 | 000 | 경상남도 | LOCAL_RULE_NOT_FOUND | SERVC_QUAL_PRE_20230501_ATTACH_15 |
| R25BK00864238 | 000 | 전남광주통합특별시 | LOCAL_RULE_NOT_FOUND | SERVC_QUAL_PRE_20230501_ATTACH_06 |
| R25BK00876620 | 000 | 전남광주통합특별시 | LOCAL_RULE_NOT_FOUND | SERVC_QUAL_PRE_20230501_ATTACH_06 |
| R25BK00883763 | 000 | 서울특별시 | LOCAL_SERVICE_TYPE_UNRESOLVED | SERVC_QUAL_MOE_CDW_ATTACH_04 |
| R25BK00925563 | 000 | 전남광주통합특별시 | LOCAL_RULE_NOT_FOUND | SERVC_QUAL_PRE_20230501_ATTACH_02 |
| R26BK01531664 | 000 | 전남광주통합특별시 | LOCAL_RULE_NOT_FOUND | SERVC_QUAL_PRE_20250901_ATTACH_06 |
| R26BK01589681 | 000 | 전남광주통합특별시 | LOCAL_RULE_NOT_FOUND | SERVC_QUAL_POST_20260526_ATTACH_02 |
| R26BK01653130 | 000 | 세종특별자치시 | LOCAL_RULE_NOT_FOUND | SERVC_QUAL_POST_20260526_ATTACH_18 |
| R26BK01817736 | 000 | 서울특별시 | LOCAL_SERVICE_TYPE_UNRESOLVED | SERVC_QUAL_MOE_CDW_ATTACH_04 |

예상 밖 변경은 0건입니다. 대표 사례 두 건은 R26BK01817736 → `SERVC_QUAL_MOE_CDW_ATTACH_04`,
R26BK01531664 → `SERVC_QUAL_PRE_20250901_ATTACH_06` 로 계산됩니다.

---

## 4. 시험

- 신규 `tests/test_stated_basis_routing_20261118.py` 9건: 대표 사례 2건, 환경부고시 띠
  표기 불일치, 조달청 명시 없는 전남 학술, 예규 제1075호 명시, 조달청 매칭 부재,
  통합특별시·대구 기존 분기, 부산 인력공급 불변.
- 기존 3개 시험 파일의 "다른 지역은 차단" 단언을 새 경계로 바꾸고, 파일마다 공고 명시가
  없는 다른 지역은 종전 차단을 유지하는 반례 시험을 남겼습니다.
- `tests/test_jngj_pps_stated_20261115.py`, `tests/test_dgcn_pps_stated_20261115.py`,
  `tests/test_dgcn_revised_pps_stated_20261115.py`

## 5. 검증

| 명령 | 결과 |
| --- | --- |
| `uv run pytest -q -m 'not data_assets and not e2e' tests/test_stated_basis_routing_20261118.py` | 9 passed |
| `uv run pytest -q -m 'not data_assets and not e2e' tests/` | 11,231 passed, 36 skipped, 35 deselected, 2 xfailed |
| `uv run mypy src` | Success: no issues found in 152 source files |
| `python3 scripts/validate_agent_rules.py --quiet` | 22/22 통과 |
