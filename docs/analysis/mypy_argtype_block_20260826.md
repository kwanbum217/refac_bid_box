# mypy arg-type 블록 1 해소 (2026-08-26)

> **작성일**: 2026-08-26
> **관련 Task**: task_2e60da21b7db

---

## 변경 전

`pyproject.toml` 첫 arg-type override 블록에 16모듈이 등재되어 있었습니다.

## 변경 후

해당 블록 전체를 제거했습니다. 16모듈 모두 override 없이 `uv run mypy` 를 통과합니다.

## 상세

`docs/analysis/task_2e60da21b7db.md` 를 참조하십시오.
