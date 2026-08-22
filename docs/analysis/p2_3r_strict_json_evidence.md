# P2-3R Strict JSON Evidence 표준화 분석 및 결과 보고서

> **문서 상태**: 완료 (Final)  
> **작성 일자**: 2026-08-23  
> **관련 Task**: `task_8ffc08d03dea` (`p2_3r_strict_json_evidence`)  
> **목적**: `dump_strict_json` / `sanitize_nan_to_none` / `load_strict_json` 단일 진실 공급원(`scripts/_strict_json.py`) 신설 및 전 evidence 스크립트 표준 직렬화 통일

---

## 1. 개요 및 배경

기존 `scripts/benchmark_latency.py`에만 국소적으로 적용되어 있던 strict JSON 직렬화(`dump_strict_json`, `sanitize_nan_to_none`)를 공용 모듈 `scripts/_strict_json.py`로 추출하였습니다.

이를 통해 다른 evidence 스크립트들(`benchmark_predict_tail.py`, `benchmark_sse_gate.py`, `benchmark_arq_throughput.py`, `orca_metrics_ledger.py`, `orca_level1_gate.py`, `orca_model_router.py`)이 비표준 부동소수점(`NaN`, `Infinity`, `-Infinity`)을 그대로 직렬화하여 게이트 및 다운스트림 파서에서 오류가 발생하는 문제를 원천 차단하였습니다.

---

## 2. 주요 변경 사항

### 2.1 단일 진실 공급원 모듈 신설 (`scripts/_strict_json.py`)

- `sanitize_nan_to_none(obj)`: 재귀 탐색을 통해 부동소수점 `NaN`, `Inf`, `-Inf`를 `None`(`null`)으로 정규화.
- `dump_strict_json(data, **kwargs)`: `sanitize_nan_to_none` 선행 처리 후 `allow_nan=False` 옵션을 강제하여 RFC-8259 준수 JSON 문자열 직렬화.
- `load_strict_json(source, **kwargs)`: `parse_constant` 훅을 통해 비표준 상수(`NaN`, `Infinity`, `-Infinity`)가 포함된 입력을 명시적으로 거부(`ValueError` 발생). 파일 객체, `Path`, `str`, `bytes` 모두 지원.
- `dumps_strict_json`, `loads_strict_json` 별칭 제공.

### 2.2 Evidence 및 게이트 스크립트 표준 직렬화 적용

| 스크립트 | 변경 내용 |
| --- | --- |
| `scripts/benchmark_predict_tail.py` | `dump_strict_json`을 적용하여 tail 레이턴시 및 요약 직렬화 |
| `scripts/benchmark_sse_gate.py` | `dump_strict_json`을 적용하여 원시 측정치 저장 직렬화 |
| `scripts/benchmark_arq_throughput.py` | `dump_strict_json`을 적용하여 처리량 벤치마크 결과 저장 직렬화 |
| `scripts/orca_metrics_ledger.py` | 원장 파일 저장(`indent=None`) 및 CLI JSON 출력에 `dump_strict_json`, 행 로드에 `load_strict_json` 적용 |
| `scripts/orca_level1_gate.py` | Level 1 게이트 결과 JSON 반환 시 `dump_strict_json` 적용 |
| `scripts/orca_model_router.py` | 모델 라우팅/신뢰도 이력 저장 및 CLI JSON 출력에 `dump_strict_json` 적용 |

### 2.3 회귀 및 단위 테스트 추가 (`tests/test_strict_json_serialiation.py`)

- 스칼라 및 중첩 자료구조(dict, list, tuple)에서의 `NaN`/`Inf` `None` 정규화 검증.
- `allow_nan=False` 직렬화 성공 및 `null` 복원 검증.
- `load_strict_json`의 비표준 부동소수점(`NaN`, `Infinity`, `-Infinity`) 및 구문 오류(트레일링 콤마 등) 거부 검증.
- 다양한 소스 타입(`str`, `bytes`, `bytearray`, `StringIO`, `Path`) 지원 검증.
- 벤치마크 evidence 데이터 왕복(roundtrip) 정합성 검증.

---

## 3. 데이터 무손실(G1) 및 호환성 원칙 준수

- 기존 raw benchmark 파일(`data/benchmarks/*.json` 등) 및 기존 리포트는 일체 수정하지 않았습니다.
- `scripts/benchmark_latency.py`의 기존 동작 및 인터페이스는 100% 보존되었습니다.
