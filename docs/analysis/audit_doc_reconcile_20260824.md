# 감사 문서-코드 정합성 4건 정정 보고서 (2026-08-24)

> **작성일**: 2026-08-24
> **작성자**: task_8f19bd20b52a (builder)
> **대상 브랜치**: `audit-doc-reconcile`
> **목적**: 외부 감사 P1 지적 중 코드 수정 없이 문서만으로 닫히는 4건을 정정

---

## 1. 개요

외부 감사에서 지적된 문서-코드 정합성 오류 4건을 바로잡았습니다. 코드는 수정하지 않고, 감사 보고서와 현재 운영 상태 정본, LLM 비교 문서의 서술만 정정했습니다. 각 항목의 정정 내용과 근거는 아래와 같습니다.

---

## 2. 정정 항목별 내역

### 2.1 Arq provenance 구현 기술 정정 (`gpt_audit_reverification_20260824.md` 감사 9번)

**지적**: 감사 보고서 112행이 "두 하네스 모두 동일한 `build_provenance_dict` 함수를 import하여 사용"이라 기술했으나 이는 사실이 아님.

**실제 구현 확인 (코드 대조)**:
- `build_provenance_dict` 는 `scripts/benchmark_arq_container.py:209` 와 `scripts/benchmark_arq_throughput.py:192` 에 **각각 별도로 정의**되어 있으며, 공통 모듈에서 import 하지 않음.
- `scripts/benchmark_provenance.py` 에서 import 하는 것은 `BuildProvenanceError`, `_parse_source_mount`, `is_source_dirty`, `single_host_load_sample` 등 일부이며 `build_provenance_dict` 는 포함되지 않음.
- `get_host_memory`(container:90, throughput:73)와 `get_git_status`(container:144, throughput:127)도 양쪽에 각각 중복 정의.
- 두 함수의 스키마 동등성은 공통 구현이 아니라 `tests/test_benchmark_arq_container.py` 의 키 집합 비교로 결박.

**정정**: 112행의 import 서술을 실제 구현과 일치하도록 정정. 보고서 내부 모순(110행 "다른 파일" 대 112행 "공통 import")도 해소.

### 2.2 보고서 현재성 메타데이터 추가 (`gpt_audit_reverification_20260824.md` 머리)

**지적**: 과거 분석 문서에 현재성 표기가 없음.

**정정**: 문서 머리에 `observed_commit`, `status`, `resolved_at_commit`, `superseded_by` 필드를 추가하고 `status` 를 `historical` 로 표기. 값은 확인할 수 없어 `미정` 으로 적되 필드는 유지.

### 2.3 CURRENT_STATE CI evidence 불일치 정정 (`CURRENT_STATE.md`)

**지적**: G2 근거가 feature 브랜치 사전 검증 run `32703096829`(`bd6212c`)이었으나, main 병합 후 검증 run 이 별도 존재.

**정정**:
- G2 판정 근거를 **main 병합 검증 run `32703990405`(`a203286`)** 으로 통일.
- `32703096829`(`bd6212c`)는 feature 브랜치 사전 검증 이력으로 구분해 보존.
- 4장 운영 검증 항목도 동일 run 으로 통일.

### 2.4 LLM 비교 문서 컨텍스트 판정 모순 정정 (`llm_model_comparison_e4b_e2b_20260824.md`)

**지적 1 (문항 수 모순)**: 92행은 "컨텍스트가 부족한 3문항(1·3·5)"이라 적고, 112행·130행은 "5문항 중 컨텍스트가 충분한 것이 2번 하나뿐(즉 4문항 부족)"이라 적어 문서 내부 판정이 어긋남.

**문항별 대조로 확정**: 표에서 DB 집계 근거(충분한 컨텍스트)를 가진 것은 2번 하나뿐이며, 1·3·4·5번이 컨텍스트 부족. 이 중 3·5번은 거절, 1·4번은 답변은 했으나 불충분 컨텍스트. → **컨텍스트 부족 문항 수 = 4 (1·3·4·5)** 로 통일. 92행을 3→4 로 정정하고 130행의 "4문항 거절" 서술을 "4문항 컨텍스트 부족"으로 정리.

**지적 2 (사실 오류 0건 평가)**: 문서가 "사실 오류·환각 0건"이라 평가했으나 4번 문항에서 e4b 가 "통계 데이터가 없다"고 말한 뒤 비교를 수행하는 자기모순을 함께 보고.

**정정**: "사실 오류 0건"이 **지면 대조 한정** 판정임을 명시하고, ground truth(정답 참조) 대조는 수행하지 않았음을 명확히 함. 4번의 e4b 자기모순을 "사실 오류 0건" 판정이 포착하지 못한 논리 결함으로 재기술.

---

## 3. 검증 결과

| 검증 | 결과 |
| --- | --- |
| 감사 보고서 내 "공통 함수 import" 서술 잔존 여부 | 없음 (2.1 정정으로 제거) |
| CURRENT_STATE G2 근거 run 통일 | main 병합 검증 run `32703990405` 단일, 이전 run 은 이력 구분 |
| LLM 비교 문서 컨텍스트 부족 문항 수 | 4 (1·3·4·5) 단일 값으로 일관 |
| `python3 scripts/validate_agent_rules.py --quiet` | 통과 |
| 이모지 사용 | 없음 |
| CURRENT_STATE.md 문자 수 | 8,000자 이내 유지 |

---

## 4. 남은 사항

- 문서 정정으로 닫히지 않는 감사 P1 2건(provenance 공통화, Redis 결박)과 캘리브레이션 산식은 다른 Task 에서 병렬 처리합니다. 본 Task 는 해당 파일(코드)을 건드리지 않았습니다.
