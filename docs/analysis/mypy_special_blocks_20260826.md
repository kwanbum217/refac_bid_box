# mypy special override 현황 (2026-08-26)

> **갱신**: task_8a0cca3400f6 완료 후

---

## task_8a0cca3400f6 소유 블록 (완료)

11블록 13모듈 전부 제거. 상세는 [`task_8a0cca3400f6.md`](task_8a0cca3400f6.md) 참조.

---

## 잔여 override (본 Task 비소유)

`pyproject.toml` 에 남은 블록은 선행 Task 범위입니다.

| 블록 | 모듈 수 | disable_error_code |
| --- | --- | --- |
| ML/앱 arg-type | 14 | `arg-type` |
| model_registry | 1 | `assignment` |
| 혼합 arg/assignment | 4 | `arg-type`, `assignment` |
| audit_model_inventory | 1 | `operator`, `return-value` |
| benchmark_arq_container | 1 | `arg-type`, `call-overload`, `misc`, `unused-ignore` |
| benchmark_provenance | 1 | `arg-type`, `dict-item`, `operator` |

---

## 정책

- `type: ignore` 추가·`Any` 확산·`disable_error_code` 확대 금지
- 스텁 한계는 구체적 근거와 함께 override 존치 가능 (본 Task 소유분은 0건)
