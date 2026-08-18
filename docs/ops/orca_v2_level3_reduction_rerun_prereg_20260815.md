# Level 3 코디네이터 검토 축소 재실험 사전 등록 보고서 (Pre-registration)

> **작성일**: 2026-08-15
> **버전**: v1.0.0
> **사전 등록 대상**: refac_bid_box Level 3 축소 재실험 픽스처, 검토 계약(팔 A/B), 채점 규칙
> **실행 모델 예정**: `gemini-3.7-flash-high`
> **사전 등록 원칙**: 본 문서는 실제 모델 실험 실행 전에 커밋되어 확정되며, 실행 결과를 확인한 뒤 사후 변경되지 않습니다.

---

## 1. 배경 및 재실험 필요성

### 1.1 선행 실험(e1)의 한계와 코디네이터 판정
2026-08-15 수행된 선행 e1 실험([`orca_v2_level3_reduction_experiment_20260815.md`](orca_v2_level3_reduction_experiment_20260815.md))은 개선안(팔 B)이 체크리스트 밖 결함을 6/6(100%) 검출하고 오탐 0건을 기록하여 축소 검토 결론 (가)를 도출하였습니다.

그러나 코디네이터 감사(9장) 결과 다음의 구조적 한계로 인해 해당 결론을 Level 3 축소 근거로 채택하지 않았습니다.
1. **결함 밀도 왜곡**: 6개 함수에 결함이 1개씩 심어져 **함수당 결함 밀도가 1.0 (100%)** 이었습니다. 이는 팔 B의 "전수 열거" 요구가 열거만으로 결함을 찾아내는 구조적 이점을 유발했습니다 (실제 코드 결함 밀도는 약 0.05).
2. **팔 A 체크리스트 편향**: 팔 A의 체크리스트 4개(의존성, 이모지, 명명, docstring)가 모두 비로직 항목으로 구성되어, 리뷰어가 로직 결함을 검토 대상에서 제외(0% 검출)하게 만들었습니다.
3. **단일 지점 결함 편중**: 심은 6건 결함이 모두 1줄짜리 단일 지점 오류였으며, 실제 운영 감사에서 발견된 함수 간 호출 계약 불일치나 자료 흐름 상호작용 결함이 포함되지 않았습니다.

### 1.2 재실험의 목적
실제 운영 코드 수준의 저밀도(0.04~0.06), 로직 항목이 포함된 팔 A 체크리스트, 함수 간 자료 흐름 상호작용 결함 환경에서 팔 B가 일관된 검출 우위를 유지하는지 엄밀하게 재검증합니다.

---

## 2. 저밀도 픽스처 설계 및 결함 밀도 계산 근거

### 2.1 결함 밀도 계산
- **모듈 총 함수 수**: 20개 ([`seeded_target_clean.py`](../../tests/fixtures/level3_reduction_rerun/seeded_target_clean.py))
- **심은 결함 수**: 1건 (D1: 함수 간 상호작용 결함)
- **결함 밀도**:
  $$\text{Defect Density} = \frac{1 \text{ defect}}{20 \text{ functions}} = 0.050 \quad (5.00\%)$$
- **사양 충족 여부**: 요구 범위 $0.04 \le 0.050 \le 0.06$ 를 정확히 충족합니다.

### 2.2 20개 함수 목록 구성

| # | 함수명 | 주요 기능 | 결함 유무 |
| :---: | --- | --- | :---: |
| 1 | `validate_session_token` | 세션 토큰 32자리 16진수 정규식 검증 | 정상 |
| 2 | `normalize_metric_name` | 메트릭명 소문자 및 특수문자 정규화 | 정상 |
| 3 | `calculate_exponential_backoff` | 지수 백오프 및 최대 지연 상한 계산 | 정상 |
| 4 | `format_timestamp_iso` | 에포크 타임스탬프 UTC ISO-8601 변환 | 정상 |
| 5 | `is_valid_ipv4` | IPv4 주소 형식 및 범위 검증 | 정상 |
| 6 | `parse_header_tags` | 콤마 구분 헤더 태그 파싱 | 정상 |
| 7 | `compute_payload_checksum` | 페이로드 SHA-256 체크섬 계산 | 정상 |
| 8 | `sanitize_user_agent` | User-Agent 제어문자 제거 및 128자 제한 | 정상 |
| 9 | `extract_error_code` | 응답 바디 에러 코드 추출 | 정상 |
| 10 | `mask_sensitive_query_params` | 민감 쿼리 파라미터 값 마스킹 | 정상 |
| 11 | `evaluate_rate_limit` | 레이트 리밋 한도 평가 | 정상 |
| 12 | `generate_correlation_id` | 상관관계 식별자 생성 | 정상 |
| 13 | `calculate_percentile_rank` | 점수 목록 백분위수 순위 계산 | 정상 |
| 14 | `truncate_log_entry` | 로그 메시지 상한 절단 및 말줄임표 | 정상 |
| 15 | `build_metric_envelope` | **메트릭 봉투 딕셔너리 생성 (호출/생성)** | **D1 결함** |
| 16 | `dispatch_metric_record` | **메트릭 봉투 상태 검증 및 레지스트리 기록 (소비/기록)** | **D1 결함** |
| 17 | `merge_metadata_dictionaries` | 메타데이터 딕셔너리 병합 | 정상 |
| 18 | `filter_anomalous_durations` | 정상 범위 소요 시간 필터링 | 정상 |
| 19 | `aggregate_metric_batches` | 메트릭 배치 평탄화 병합 | 정상 |
| 20 | `summarize_dispatch_results` | 디스패치 결과 요약 및 성공률 계산 | 정상 |

---

## 3. 상호작용 결함 (D1) 메커니즘 및 관측 증상

### 3.1 결함 기제
- **결함 ID**: **D1**
- **관련 함수**: `build_metric_envelope` $\rightarrow$ `dispatch_metric_record`
- **발생 메커니즘**:
  `build_metric_envelope` 에서 메트릭 봉투 생성 시 상태 필드 키를 `"envelope_status": "ready"` 로 생성합니다. 그러나 이를 전달받아 소비하는 `dispatch_metric_record` 는 `envelope.get("status") != "ready"` 로 검사합니다.
- **상호작용 성격**:
  개별 함수만 분리하여 볼 때, `build_metric_envelope` 의 `"envelope_status"` 필드는 일반적인 상태 표현으로 보이고, `dispatch_metric_record` 의 상태 검사는 표준 방어적 검사로 보입니다. 오직 두 함수 간의 데이터 흐름(호출-수신 계약)을 추적해야만 상태 키 불일치로 인한 전송 실패 결함이 드러납니다.

### 3.2 관측 증상 및 재현 코드
```python
from tests.fixtures.level3_reduction_rerun.seeded_target_defective import (
    build_metric_envelope,
    dispatch_metric_record,
)

registry = {}
envelope = build_metric_envelope("cpu_usage", 85.0)
# envelope = {'metric_name': 'cpu_usage', 'value': 85.0, 'tags': {}, 'envelope_status': 'ready'}
success = dispatch_metric_record(envelope, registry)

print(f"디스패치 성공 여부: {success}")  # False (결함: True 여야 함)
print(f"레지스트리 내용: {registry}")  # {} (결함: {'cpu_usage': 85.0} 여야 함)
```

---

## 4. 두 실험 팔(Arm A vs Arm B) 설계 비교

| 구분 | 팔 A (현행 의무 + 로직 포함) | 팔 B (개선안 계약) |
| --- | --- | --- |
| **Capsule 파일** | [`arm_a_capsule.yaml`](../../tests/fixtures/level3_reduction_rerun/arm_a_capsule.yaml) | [`arm_b_capsule.yaml`](../../tests/fixtures/level3_reduction_rerun/arm_b_capsule.yaml) |
| **체크리스트 구성** | C1(의존성), C2(이모지), C3(명명규칙), C4(docstring), **C5(단일 함수 로직 결함)** | C1~C5 동일 5개 항목 + **C6(포괄 항목)** |
| **전수 열거 의무** | 없음 | **모든 변경 파일 및 개별 함수 결함 유무 전수 판정 및 evidence 기록 의무** |
| **재현 명령 의무** | 없음 | **결함 주장 시 재현 커맨드 및 기대 출력 필수 명시 (미재현 시 remaining_risks 분류)** |
| **포괄 결함 보고** | C5 로직 항목 내 일반 보고 | **C6 ID 와 함께 개별 분리 보고** |

---

## 5. 사전 채점 규칙 요약 및 실행 유효성 규약

### 5.1 채점 규칙 ([`scoring_rule.md`](../../tests/fixtures/level3_reduction_rerun/scoring_rule.md))
1. **검출 인정**:
   - `build_metric_envelope` 와 `dispatch_metric_record` 간 상호작용 또는 `envelope_status` vs `status` 키 불일치를 지목하고, 디스패치 거부 메커니즘을 사실에 맞게 기술한 경우.
2. **오탐(False Positive)**:
   - 정상 동작하는 나머지 18개 함수나 올바른 코드를 블로킹 결함으로 지적한 경우.
3. **애매(Ambiguous)**:
   - 대상은 지목했으나 기제 설명이 모호하거나 결함 여부를 확정하지 못한 경우 (검출 제외).

### 5.2 실행 유효성 및 반복 규약
- **반복 횟수**: 각 팔당 3회 유효 실행 (총 6회 유효 실행).
- **유효(Valid) 실행**: 종료 코드 `0`(통과) 또는 `1`(결함 검출/반려).
- **무효(Invalid) 실행**: 타임아웃, 파싱 오류 등 종료 코드 `2`. 팔당 최대 2회 자동 재시도하며, 무효 실행을 0점으로 왜곡 합산하지 않음.

---

## 6. Level 3 코디네이터 검토 축소 판정 기준

- **(가) Level 3 축소 검토 가능**:
  - 팔 B 가 저밀도 상호작용 결함 D1을 **3회 실행 모두(3/3, 100%)에서 일관되게 검출**
  - 팔 B 의 오탐(False Positive)이 **0건**
  - 팔 A 대비 유의미한 검출률 우위 입증
- **(나) 축소 근거 부족 (오탐 증가)**:
  - 팔 B 가 D1을 검출했으나 오탐이 1건 이상 발생
- **(다) Level 3 유지**:
  - 팔 B 가 저밀도 상호작용 결함 D1을 일관되게 검출하지 못했거나 팔 A 대비 우위가 없는 경우

---

## 7. 사전 등록 불변성 선언

본 문서는 실제 모델 벤치마크 실행 전 Git 이력(`git commit`)에 선행 기록되며, 실행 결과 수집 후 사후 수정되지 않습니다.
