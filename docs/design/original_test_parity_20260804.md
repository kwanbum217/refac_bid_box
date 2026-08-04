# 원본 테스트 재현 현황과 제외 근거

> **작성일**: 2026-08-04
> **버전**: v1.0
> **상태**: 확정

---

## 1. 목적

이식본이 원본(`bid_box`)의 동작을 얼마나 재현하는지를 주관적 인상이 아니라
**원본 테스트 이름 기준 커버리지**로 측정합니다. 화면이 비슷해 보이는 것과
같은 계약을 지키는 것은 다른 문제이며, 후자만 측정 가능합니다.

측정 방법은 단순합니다. 원본 `apps/*/tests.py` 에 정의된 테스트 이름이
이식본 `tests/` 안 어딘가에 나타나는지 봅니다. 이름이 달라진 경우에는 이식본
테스트의 docstring 또는 모듈 상단 대응표에 원본 이름을 명시해 매핑을 남깁니다.

```bash
python - <<'PY'
import re, pathlib
orig = {}
for p in pathlib.Path("../bid_box/apps").rglob("tests.py"):
    for m in re.finditer(r"def (test_\w+)", p.read_text(encoding="utf-8")):
        orig[m.group(1)] = str(p).split("/")[-2]
ported = {n for n in orig for p in pathlib.Path("tests").rglob("*.py")
          if n in p.read_text(encoding="utf-8")}
print(f"{len(ported)}/{len(orig)} = {len(ported)/len(orig)*100:.1f}%")
PY
```

---

## 2. 현황

| 구분 | 건수 |
| --- | --- |
| 원본 테스트 전체 | 131 |
| 이식 완료 | 122 |
| 구조적 제외 | 9 |
| **커버리지** | **93.1%** |

제외 9건을 뺀 이식 가능 범위 기준으로는 122/122 로 전량 이식된 상태입니다.

---

## 3. 제외 대상과 근거

제외는 "하기 어려워서"가 아니라 **이식본에 대응 개념이 존재하지 않아서**
입니다. 대응 개념 없이 이름만 맞추면 아무것도 검증하지 않는 테스트가 남습니다.

### 3.1 소셜 로그인 (3건)

| 원본 테스트 |
| --- |
| `test_login_page_renders_allauth_social_provider_links` |
| `test_signup_page_only_renders_configured_social_provider` |
| `test_kakao_social_login_does_not_require_client_secret` |

원본은 `django-allauth` 로 구글·카카오·네이버 로그인을 붙였습니다. 이식본은
allauth 를 도입하지 않았고 자체 세션 인증만 씁니다. 신규 라이브러리 추가는
사전 합의 사항이므로 임의로 넣지 않았습니다.

도입한다면 이 3건이 그대로 되살아납니다.

### 3.2 Harness 전용 도구 (3건)

| 원본 테스트 | 검증 대상 |
| --- | --- |
| `test_runtime_yaml_contains_all_variables` | Harness 파이프라인 변수 정의 YAML |
| `test_runtime_yaml_preserves_empty_variable_values_as_strings` | 같은 YAML 의 빈 값 직렬화 |
| `test_kb_only_rag_self_seeds_empty_runtime_database` | `harness/scripts/ci_pipeline_run.sh` 셸 스크립트 본문 |

원본은 Harness 클라우드 CI 에 파이프라인 실행을 위임했고, 위 세 건은 그
런타임 정의 파일과 셸 스크립트의 내용을 문자열로 검사합니다. 이식본은
Arq 워커가 같은 일을 파이썬으로 수행하므로 검사 대상 파일 자체가 없습니다.

대응하는 이식본 검증은 다음이 담당합니다.

| 원본이 보던 것 | 이식본에서 같은 것을 보는 테스트 |
| --- | --- |
| 실행 모드별 스텝 구성 | `tests/test_run_mode_matrix.py` |
| 스텝 실행 순서와 중단 지점 | `tests/test_automation_bundle_parity.py` |
| 워커 결과 보고 경로 | `tests/test_callback_delivery.py` |

### 3.3 Harness 실행 이력 재사용 (1건)

`test_confirm_reuses_recent_harness_summary_without_new_run`

원본은 재사용 소스가 둘이었습니다.

1. DB 의 최근 성공한 스테이징 실행 이력
2. Harness 클라우드 API 에서 가져온 최근 실행 요약

이식본에는 2번 소스가 없습니다. 1번은 `_try_reuse_recent_execution` 으로
그대로 살아 있고 `tests/test_automation_status_api.py` 의
`test_confirm_reuses_recent_success_without_new_run` 이 검증합니다.

### 3.4 validate_model 관리 명령 (2건)

| 원본 테스트 |
| --- |
| `test_validate_model_command_rejects_low_r2_summary` |
| `test_validate_model_command_skip_summary_emits_success_result` |

원본은 `champion_summary.json` 파일과 `--min-r2` 인자를 받아 기준 미달이면
`CommandError` 를 던지는 Django 관리 명령이었습니다.

이식본은 승격 게이트를 `src/ml/validate_model.py` 의
`compare_champion_vs_challenger` 로 재설계했습니다. 파일 하나의 집계값을 보고
통과 여부를 정하는 대신, 현행 챔피언과 도전자를 같은 데이터로 비교해 압도할
때만 승격합니다. 요약 파일 기준 검사는 이 설계에서 되살릴 자리가 없습니다.

재학습 게이트 검증은 `tests/test_retrain_pipeline_e2e.py` 와
`tests/test_mlops_pipeline.py` 가 담당합니다.

---

## 4. 이번 작업에서 발견한 실제 결함

재현 테스트를 채우는 과정에서 나온 것으로, 테스트만 늘린 것이 아닙니다.

| 위치 | 증상 | 원인 |
| --- | --- | --- |
| `src/app/templates/bids/result_detail.html` | 낙찰률 자리에 bound method 객체가 출력됨 | 낙찰률이 공고 기준금액 재조회를 필요로 해 property 에서 `db` 인자를 받는 메서드로 바뀌었는데, 템플릿이 인자 없는 속성 접근을 유지. Jinja2 는 속성 접근으로 메서드를 호출하지 않음 |

`src/app/services/bid_queries.py:get_result_detail` 에서 값을 확정해
`resolved_winning_rate` 로 넘기도록 고쳤습니다.

`run_automation_pipeline` 은 그동안 다른 테스트에서 모킹 대상이기만 했고
스텝 실행 순서를 직접 확인하는 테스트가 없었습니다. 결함은 없었지만
방어가 비어 있던 자리입니다.

---

## 5. 관련 문서

- [`docs/design/FRONTEND_DECISION.md`](FRONTEND_DECISION.md) — 화면 재현 결정과 의도적 차이
- [`docs/design/prediction_without_amount_20260804.md`](prediction_without_amount_20260804.md) — 금액 미공개 공고 예측 차단 결정
