# RAG 구간 계측 하네스 Warmup 단계 추가 분석 및 구현 보고서

> **문서 ID**: docs/analysis/task_7ab7d19b1a10.md
> **Task ID**: task_7ab7d19b1a10
> **작성일**: 2026-08-30
> **대상 하네스**: `scripts/benchmark_rag_segments.py`

---

## 1. 개요 및 배경

2026-08-30 정본 측정에서 RAG 구간 계측 하네스의 P99 및 max 지연시간이 프로세스 재기동 직후 첫 요청의 콜드 스타트 비용(ChromaDB 및 임베딩 모델, Ollama 커넥션 초기화)으로 인해 과대 추정(오염)되는 현상이 확인되었습니다.
`docs/ops/latency_gate_protocol.md` 2장의 규약에 따라 정본 레이턴시 계측 시 본 측정 전 Warmup 요청을 실행하고, 해당 요청은 전체·cold·warm·문항별 표본에서 완전히 제외하여 순수 정상 상태 레이턴시만을 측정할 수 있도록 하네스를 개선하였습니다.

---

## 2. 주요 변경 사항

### 2.1 Warmup 기본값 및 근거
- **상수 정의**: `DEFAULT_WARMUP_ROUNDS = 1`
- **근거**: `docs/ops/latency_gate_protocol.md` 2장은 warmup 요청 수를 측정 동시성과 같은 수로 규정합니다. 본 하네스는 직렬(단발) 질의 전송(concurrency=1)이므로 기동 직후 콜드 스타트를 해소하기 위한 최소 직렬 warmup 회수인 1회를 기본값으로 설정하였습니다.

### 2.2 CLI 옵션 확장
- `--warmup-rounds`: 본 측정 전 선행 실행할 Warmup 회수 (기본값: 1, 표본 제외)
- `--no-warmup`: Warmup 단계를 건너뛰고 기존 동작과 동일하게 단독 측정 수행 (`scripts/benchmark_sse_gate.py` 규약 준용)

### 2.3 표본 완전 격리 및 집계 제외
- Warmup 단계에서 발생한 요청의 왕복 시간(roundtrip) 및 응답 trace_id는 `all_roundtrip`, `cold_roundtrip`, `warm_roundtrip`, `trace_metadata` 어디에도 등록되지 않습니다.
- 전체 집계(`summary`, `all`), cold 집계(`summary_cold`), warm 집계(`summary_warm`), 문항별 집계(`summary_by_item`) 전 항목에서 Warmup 요청이 100% 격리·제외됩니다.

### 2.4 Trace 상관 검증(Trace Correlation) 무결성 보존 기전
- Warmup 단계에서 수신된 응답 trace_id 집합(`warmup_traces`)을 별도 메모리에 추적합니다.
- 서버 로그 파싱(`parse_segment_lines`) 후, `warmup_traces`에 해당하는 세그먼트 로그 레코드를 본 측정 세그먼트 레코드(`records`)에서 명시적으로 분리/제외합니다.
- 본 측정 성공 요청 수와 필터링된 본 측정 로그 레코드 수를 1:1로 엄밀히 대조하므로 `verify_trace_correlation` 검증 체계가 훼손 없이 정확하게 성립합니다.

### 2.5 산출물 메타데이터 보강
산출물 JSON payload에 Warmup 실행 내역을 명확히 보존하여 산출물만으로도 Warmup 여부를 검증할 수 있도록 하였습니다.
- `warmup_rounds`: 설정된 Warmup 회수 (정수)
- `warmup_excluded_count`: 실제로 집계에서 제외된 Warmup 요청 수 (정수)
- `config.warmup_rounds`: 설정 값
- `config.no_warmup`: 플래그 지정 여부 (bool)
- `config.warmup`: 실제 Warmup 활성화 여부 (bool)

---

## 3. 단위 테스트 및 검증 결과

### 3.1 추가된 단위 테스트 (5건 고정)
`tests/test_benchmark_rag_segments.py`에 다음 5개 핵심 시나리오를 단위 테스트로 추가하였습니다:
1. `test_warmup_excluded_from_all_summary`: Warmup 요청의 극단치 지연이 전체 집계에 포함되지 않음을 검증
2. `test_warmup_excluded_from_cold_summary`: Warmup 요청이 cold 집계에 포함되지 않고 본 측정 1회차만 정확히 집계됨을 검증
3. `test_no_warmup_flag_skips_warmup`: `--no-warmup` 지정 시 Warmup 요청 없이 본 측정만 수행됨을 검증
4. `test_warmup_metadata_recorded_in_payload`: 산출물 payload에 Warmup 회수, 제외 건수, config 필드가 올바르게 기록됨을 검증
5. `test_warmup_trace_correlation_passes_with_warmup_records`: 로그에 Warmup trace가 있어도 1:1 대조 무결성이 정상 통과함을 검증

### 3.2 검증 명령 실행 결과
- `uv run pytest tests/test_benchmark_rag_segments.py -q`: 61 passed, 1 warning (0.43s)
- `uv run pytest tests/ -q -m 'not data_assets'`: 2753 passed, 6 skipped, 3 deselected, 312 warnings in 258.05s (0:04:18)
- `python3 scripts/validate_agent_rules.py --quiet`: 통과 (12/12 건)
