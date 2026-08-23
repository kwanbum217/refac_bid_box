# 문서 정합성 감사 및 정비 보고서 (2026-08-23)

> **작성일**: 2026-08-23
> **Task ID**: `docs_consistency_audit_20260823`
> **상태**: 완료
> **단일 진실 원천(SSOT)**: [`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md)
> **적용 범위**: 저장소 전반의 문서 계층 상태 드리프트 해소 및 SSOT 수렴

---

## 1. 감사 개요

2026-08-23 진행된 문서 정합성 감사에서 확인된 10개 핵심 항목을 정비하여, 프로젝트의 현재 사실에 대한 단일 진실 원천(SSOT)이 `docs/context/CURRENT_STATE.md` 하나로 온전히 수렴되도록 문서 계층을 정비했습니다.

---

## 2. 정합성 조치 내역 요약

| 번호 | 점검 항목 | 대상 파일 | 조치 내용 |
| :---: | --- | --- | --- |
| 1 | **독해 순서 및 구조 정비** | `docs/README.md` | 독해 순서를 `AGENTS -> CURRENT_STATE -> 프로토콜/ADR -> 최신 실측 -> 과거 handoff`로 개편, `context/` 및 `analysis/` 폴더 구조 반영 |
| 2 | **구 백로그 정본 해제** | `docs/README.md`, `docs/handoff/2026-08-13_future_work_backlog.md` | `future_work_backlog.md` 상단에 SUPERSEDED 배너 부착 및 `CURRENT_STATE.md` 수렴 안내 |
| 3 | **과거 컷오버 보고서 배너** | `docs/ops/phase7_cutover_report_20260804.md` | 2026-08-14 규약 제정 이전 결과임을 명시하는 HISTORICAL 배너 부착 |
| 4 | **크로스플랫폼 상태 및 큐 정정** | `docs/ops/cross_platform_guide.md` | macOS 실기 PASS, Ubuntu CI PASS, macOS CI PASS, 최신 Windows CI FAIL(SHA d95efd5), Windows Docker 실기 대기 정정 및 Celery -> Arq 통일 |
| 5 | **LLM 스택 표기 정합성** | `AGENTS.md`, `SKILLS.md` | 운영 기본 Ollama `gemma4:e4b`, Gemini 대체/선택 provider로 정정 |
| 6 | **프론트엔드 목표 vs 현 구현 구분** | `docs/design/FRONTEND_DECISION.md` | 목표 아키텍처(확정)와 현재 구현 상태 구분 표기, 실제 템플릿 경로(`src/app/templates/`) 기록 |
| 7 | **설계서 기준선 명시** | `docs/design/REFACTORING_DESIGN.md` | Baseline Design 위치 명시 및 과거 목표치와 현재 운영 상태(SSOT) 구분 배너 부착 |
| 8 | **c2 표본 수 명시** | `docs/analysis/c2_disposition_20260822.md` | c2 단독 표본 6,000건(Baseline 3,000 + Current 3,000) 및 전체 A/B 합계 12,000건 구조 명확화 |
| 9 | **Arq 임계치 규약 문서화** | `docs/ops/arq_threshold_provenance_20260823.md` | `scripts/arq_gate.py` 기준 임계치(-10%, +10%, +1%p) 도출식 및 4대 Provenance(Host/Redis/Arq/Docker) 기록 규약 신규 작성 |
| 10 | **판정 주체 표기 정정** | `docs/ops/latency_gate_protocol.md` | 특정 모델명 표기를 `Orca Coordinator`로 일반화하고 `AGENTS.md` 5장 참조로 정정 |

---

## 3. 검증 결과

- `scripts/validate_agent_rules.py --quiet`: 작업 커밋 직전 기준 **12/12 건 전량 PASS**. 작업 커밋 이후에는 `CURRENT_STATE 필수 필드` 1건이 FAIL 로 바뀌었습니다. `source_commit` 이 HEAD 보다 6 커밋 뒤처져 허용치 5 를 넘었기 때문이며, 본 Task 는 `CURRENT_STATE.md` 수정이 금지되어 있어 코디네이터가 병합 후 갱신했습니다. L2 리뷰가 이 불일치를 차단 사유로 제기했습니다.
- `CURRENT_STATE.md` 및 코드 파일 수정 없음 (무손실 및 계약 엄수)
- 과거 증거 수치는 보존하고 배너/주석으로만 표시 완료

---

## 4. 본 Task 범위 밖이라 코디네이터가 이어서 닫은 항목 (2026-08-23)

감사 지적 10건 중 아래 3건은 `CURRENT_STATE.md` 수정 금지 제약과 실측 확인 필요로 본 Task 에서 처리하지 못했고, 병합 후 코디네이터가 닫았습니다.

| 항목 | 조치 |
| --- | --- |
| CURRENT_STATE split-brain | `source_commit` 을 `e87c60f` 로 갱신하고, 이미 종결된 워커 준비 안전성·ModelRegistry single-flight·병합 재현성·c4 판정을 Active Priorities 에서 4.1 종결 요약으로 옮겼습니다. 잔여 진행 과업은 운영 검증, 프론트엔드 ADR 이행, G3 컷오버 판정 3건입니다 |
| CURRENT_STATE 내부 모순 | 4.1 절의 구 blocking-I/O 수치 `예측 웜 P95 61.9~83.6ms` 를 제거하고 2·3 장 재측정 정본(c1 15.39ms, c4 34.32ms, c10 47.77ms)을 가리키도록 고쳤습니다 |
| 프론트엔드 ADR 대 구현 | 실측 결과 `src/app/templates/` 전체에서 HTMX 로드와 `hx-*` 속성이 0건이고 `base.html:268` 이 jQuery 3.7.1 을 로드합니다. `src/app/static/` 하위는 `css/`, `images/` 뿐입니다. ADR 상태를 `목표 아키텍처 확정 / 구현 미완` 으로 바꾸고, 정적 자산이 CSS·HTMX·Chart.js 를 담고 있다는 기술을 사실로 정정했습니다 (Chart.js 는 CDN 로드) |
