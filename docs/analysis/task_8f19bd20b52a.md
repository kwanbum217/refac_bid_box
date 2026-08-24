# Task 보고서: 감사 문서-코드 정합성 4건 정정

> **작성일**: 2026-08-24
> **Task ID**: task_8f19bd20b52a
> **작성자**: builder 워커
> **브랜치**: `audit-doc-reconcile`
> **범위**: 문서 정정 4건 (코드 수정 없음)

---

## 1. 수행 내용

외부 감사 P1 지적 중 코드 수정 없이 문서만으로 닫히는 4건을 정정했습니다.

1. **Arq provenance 기술 정정** — `docs/analysis/gpt_audit_reverification_20260824.md` 감사 9번의 "두 하네스가 동일한 `build_provenance_dict` 를 import" 서술을 실제 구현(각 파일 별도 정의)과 일치하도록 정정하고, 보고서 내부 모순(110행 대 112행)을 해소.
2. **보고서 현재성 메타데이터** — 같은 문서 머리에 `observed_commit`/`status`/`resolved_at_commit`/`superseded_by` 추가, `status=historical` 표기.
3. **CURRENT_STATE CI evidence 통일** — `docs/context/CURRENT_STATE.md` G2 근거를 main 병합 검증 run `32703990405`(`a203286`)로 통일하고 `32703096829`(`bd6212c`)는 feature 사전 검증 이력으로 구분.
4. **LLM 비교 문서 모순 정정** — `docs/analysis/llm_model_comparison_e4b_e2b_20260824.md` 컨텍스트 부족 문항 수를 4(1·3·4·5)로 통일하고, "사실 오류 0건"이 지면 대조 한정이며 ground truth 대조가 없음을 명시.

정정 근거와 상세 내역은 `docs/analysis/audit_doc_reconcile_20260824.md` 에 기록했습니다.

## 2. 읽은 파일

- `.orca/capsules/task_8f19bd20b52a/capsule.yaml`
- `docs/context/CURRENT_STATE.md`
- `docs/analysis/gpt_audit_reverification_20260824.md`
- `docs/analysis/llm_model_comparison_e4b_e2b_20260824.md`
- `scripts/benchmark_arq_container.py`
- `scripts/benchmark_arq_throughput.py`
- `scripts/benchmark_provenance.py`

## 3. 변경한 파일

- `docs/context/CURRENT_STATE.md`
- `docs/analysis/gpt_audit_reverification_20260824.md`
- `docs/analysis/llm_model_comparison_e4b_e2b_20260824.md`
- `docs/analysis/audit_doc_reconcile_20260824.md` (신규)
- `docs/analysis/task_8f19bd20b52a.md` (신규, 본 문서)

## 4. 검증

- `python3 scripts/validate_agent_rules.py --quiet` 통과.
- CURRENT_STATE.md 8,000자 이내 유지, 이모지 미사용.
- 코드(scripts/*)는 수정하지 않아 범위 외 변경 없음.

## 5. 인수인계 / 남은 사항

- 문서 정정으로 닫히지 않는 감사 P1 2건(provenance 공통화, Redis 결박)과 캘리브레이션 산식은 다른 Task 가 병렬 처리하며, 본 Task 는 해당 코드를 건드리지 않았습니다.
