# Level 3 코디네이터 검토 축소 재실험 결과 보고서 (Results)

> **작성일**: 2026-08-15
> **버전**: v1.0.0
> **실행 모델**: `gemini-3.7-flash-high`
> **실행 대상**: refac_bid_box 독립 리뷰어 팔 A(현행 의무 + 단일함수 로직 C5) vs 팔 B(개선안 계약: 포괄 항목 C6 + 전수 열거 + 재현 명령 의무)
> **사전 등록 문서**: [`orca_v2_level3_reduction_rerun_prereg_20260815.md`](orca_v2_level3_reduction_rerun_prereg_20260815.md)
> **원시 결과 경로**: `/Users/kwanbum/orca/capsules/run_12cd21f3a5e1/experiment/results`

---

## 1. 실험 개요 및 실행 무결성

### 1.1 실험 목적
선행 e1 실험(결함 밀도 1.0, 비로직 체크리스트)의 한계를 극복하고, 실제 운영 환경 수준의 저밀도(결함 밀도 0.05, 20개 함수 중 1개 결함) 및 함수 간 자료 흐름 상호작용 결함(D1) 환경에서 팔 B(개선안 계약)가 일관된 검출 우위를 갖는지 실측 검증하였습니다.

### 1.2 실행 무결성 요약
사전 등록 커밋(`f3dce074`, `7fbeca4b`)을 변경하지 않고 동결된 상태에서 `gemini-3.7-flash-high` 모델을 호출하여 총 6회(팔 A 3회, 팔 B 3회) 실행을 완료하였습니다.

| 실험 팔 | 총 실행 수 | 유효 실행 | 무효 실행 | 재시도 횟수 | 유효 실행률 |
| --- | :---: | :---: | :---: | :---: | :---: |
| **팔 A (현행 규약 + C5 로직)** | 3 | 3 | 0 | 0 | 100.0% |
| **팔 B (개선안: C6 포괄 + 전수열거)** | 3 | 3 | 0 | 0 | 100.0% |
| **합계** | **6** | **6** | **0** | **0** | **100.0%** |

- 모든 실행에서 API 타임아웃, 파싱 에러, 도구 오류 없이 100% 유효한 `ORCA_REVIEW_DONE_V2` 응답을 수집하였습니다.

---

## 2. 결함 검출 및 오탐 채점 결과

사전 등록 채점 규칙([`scoring_rule.md`](../../tests/fixtures/level3_reduction_rerun/scoring_rule.md))에 따른 채점 결과입니다.

### 2.1 세부 실행별 판정 내역

| 팔 | 회차 | 검출 대상 (D1) | 검출 여부 | 판정 (Verdict) | 오탐 (FP) | 근거 요약 |
| :---: | :---: | :---: | :---: | :---: | :---: | --- |
| **팔 A** | 1 | `build_metric_envelope` $\leftrightarrow$ `dispatch_metric_record` | **미검출 (0)** | pass | 0 | C5 단일 함수 로직 검토에서 딕셔너리 키 변경 외 단일 함수 단위 결함 없음으로 판단 |
| **팔 A** | 2 | `build_metric_envelope` $\leftrightarrow$ `dispatch_metric_record` | **미검출 (0)** | pass | 0 | C5 단일 함수 로직 검토에서 'status' 키를 'envelope_status'로 변경한 것 외 단일 함수 결함 없음으로 판단 |
| **팔 A** | 3 | `build_metric_envelope` $\leftrightarrow$ `dispatch_metric_record` | **미검출 (0)** | pass | 0 | C5 단일 함수 로직 검토에서 딕셔너리 키 변경에 따른 단일 함수 단위 결함 없음으로 판단 |
| **팔 B** | 1 | `build_metric_envelope` $\leftrightarrow$ `dispatch_metric_record` | **미검출 (0)** | pass | 0 | C6 전수 열거에서 `build_metric_envelope`의 키 변경을 확인했으나 상호작용 결함 없음으로 오판 |
| **팔 B** | 2 | `build_metric_envelope` $\leftrightarrow$ `dispatch_metric_record` | **미검출 (0)** | pass | 0 | C6 전수 열거에서 상태 키 변경 대조 후 상호작용 결함 및 상태 누락 없음으로 오판 |
| **팔 B** | 3 | `build_metric_envelope` $\leftrightarrow$ `dispatch_metric_record` | **미검출 (0)** | pass | 0 | C6 전수 열거에서 `build_metric_envelope` 내부 status 필드 변경 확인 후 상호작용 결함 없음으로 오판 |

### 2.2 지표 요약 비교

| 지표 | 팔 A (현행 + C5) | 팔 B (개선안: C6 + 전수열거) | 차이 ($\Delta$) |
| --- | :---: | :---: | :---: |
| **D1 검출률 (Recall)** | **0/3 (0.0%)** | **0/3 (0.0%)** | 0.0%p |
| **오탐 건수 (False Positives)** | **0건** | **0건** | 0건 |
| **반복 일관성 (Consistency)** | 3/3 일치 (100%) | 3/3 일치 (100%) | - |
| **평균 블로킹 이슈 수** | 0.0건 | 0.0건 | 0.0건 |

---

## 3. 원인 분석 및 발견점

### 3.1 저밀도 환경에서 상호작용 결함 미검출 원인
1. **Diff 중심 국소성 편향 (Locality Bias)**:
   - Git diff는 `build_metric_envelope` 함수 1곳의 수정(`'status'` $\rightarrow$ `'envelope_status'`)만 포함하고 있었습니다.
   - 팔 B 리뷰어는 변경된 함수(`build_metric_envelope`)를 C6 의무에 따라 전수 열거하고 검토하였으나, 동일 파일 내 수정되지 않은 소비자 함수(`dispatch_metric_record`)와의 호출-수신 계약 및 데이터 흐름을 대조하지 못했습니다.
2. **단일 함수 관점의 정상성 착각**:
   - `build_metric_envelope` 자체만 보면 `"envelope_status": "ready"` 키를 반환하는 것은 문법적/단일 함수 로직상 오류가 아닙니다.
   - 상호작용 결함(D1)은 생산자와 소비자의 결합 관계를 추적해야만 발견 가능한데, 독립 리뷰어(단일 LLM 프롬프트)는 diff 외 전체 모듈 맥락의 호출 그래프를 깊게 추적하지 못했습니다.

### 3.2 선행 e1 실험과의 구조적 차이 입증
- 선행 e1 실험은 6개 함수 전부에 1줄짜리 단일 지점 결함이 심어져 있어(결함 밀도 1.0), 함수를 열거하는 것만으로 결함이 노출되었습니다.
- 반면 본 재실험(결함 밀도 0.05, 20개 함수 중 1개 상호작용 결함)에서는 팔 B의 전수 열거 계약만으로는 상호작용 결함을 검출하지 못함이 실측으로 명확히 입증되었습니다.

---

## 4. 사전 판정 기준 대조 및 최종 결론

### 4.1 사전 판정 기준 대조 ([`scoring_rule.md` 5장](../../tests/fixtures/level3_reduction_rerun/scoring_rule.md))
- **(가) Level 3 축소 검토 가능**: 팔 B 가 D1을 3/3(100%) 일관 검출 + 오탐 0건 + 팔 A 대비 우위 $\rightarrow$ **미충족 (0/3 검출)**
- **(나) 축소 근거 부족 (오탐 증가)**: 팔 B 가 D1 검출했으나 오탐 발생 $\rightarrow$ **해당 없음**
- **(다) Level 3 유지**: 팔 B 가 저밀도 상호작용 결함 D1을 일관되게 검출하지 못했거나 팔 A 대비 우위가 없는 경우 $\rightarrow$ **충족 (0/3 검출로 팔 A 대비 우위 없음)**

### 4.2 최종 운영 결론: Level 3 코디네이터 검토 유지
- 실측 결과에 따라 **Level 3 코디네이터 검토 축소 불가 및 현행 Level 3 검토 유지((다) 판정)** 결론을 확정합니다.
- 본 재실험 결과는 원시 결과 파일 및 요약 메타데이터에 온전히 보존되며, Level 3 검토 정책은 일체 변경하지 않습니다.

---

## 5. 원시 산출물 참조

- **실험 요약 메타데이터**: [`/Users/kwanbum/orca/capsules/run_12cd21f3a5e1/experiment/results/experiment_summary.json`](/Users/kwanbum/orca/capsules/run_12cd21f3a5e1/experiment/results/experiment_summary.json)
- **팔 A 실행 결과**:
  - Run 1: [`arm_a_run_1.json`](/Users/kwanbum/orca/capsules/run_12cd21f3a5e1/experiment/results/arm_a_run_1.json) | [`arm_a_run_1.stdout.txt`](/Users/kwanbum/orca/capsules/run_12cd21f3a5e1/experiment/results/arm_a_run_1.stdout.txt)
  - Run 2: [`arm_a_run_2.json`](/Users/kwanbum/orca/capsules/run_12cd21f3a5e1/experiment/results/arm_a_run_2.json) | [`arm_a_run_2.stdout.txt`](/Users/kwanbum/orca/capsules/run_12cd21f3a5e1/experiment/results/arm_a_run_2.stdout.txt)
  - Run 3: [`arm_a_run_3.json`](/Users/kwanbum/orca/capsules/run_12cd21f3a5e1/experiment/results/arm_a_run_3.json) | [`arm_a_run_3.stdout.txt`](/Users/kwanbum/orca/capsules/run_12cd21f3a5e1/experiment/results/arm_a_run_3.stdout.txt)
- **팔 B 실행 결과**:
  - Run 1: [`arm_b_run_1.json`](/Users/kwanbum/orca/capsules/run_12cd21f3a5e1/experiment/results/arm_b_run_1.json) | [`arm_b_run_1.stdout.txt`](/Users/kwanbum/orca/capsules/run_12cd21f3a5e1/experiment/results/arm_b_run_1.stdout.txt)
  - Run 2: [`arm_b_run_2.json`](/Users/kwanbum/orca/capsules/run_12cd21f3a5e1/experiment/results/arm_b_run_2.json) | [`arm_b_run_2.stdout.txt`](/Users/kwanbum/orca/capsules/run_12cd21f3a5e1/experiment/results/arm_b_run_2.stdout.txt)
  - Run 3: [`arm_b_run_3.json`](/Users/kwanbum/orca/capsules/run_12cd21f3a5e1/experiment/results/arm_b_run_3.json) | [`arm_b_run_3.stdout.txt`](/Users/kwanbum/orca/capsules/run_12cd21f3a5e1/experiment/results/arm_b_run_3.stdout.txt)
