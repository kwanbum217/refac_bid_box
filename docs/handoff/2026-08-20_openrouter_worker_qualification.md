# OpenRouter 무료 워커 자격 검증 및 모델 재고 대조 인수인계

> **작성일**: 2026-08-20
> **Run**: `run_a32b6b614996` (Task 6건 전부 completed)
> **관련 문서**: [`../ops/agent_worker_launch_reference.md`](../ops/agent_worker_launch_reference.md) 1.5 절, [`../context/CURRENT_STATE.md`](../context/CURRENT_STATE.md)

---

## 1. 인계 경위

Codex 코디네이터가 소유권을 Claude Opus 세션에 넘긴 뒤 창만 남기고 종료했고,
이 세션이 그 Run 을 이어받았습니다. 인계 시점에 probe 4건은 끝나 있었고
문서 반영 Task 는 `ready` 로 대기 중이었습니다.

**워커 보고와 실제 상태가 어긋나 있었습니다.** `worker_done` 은 probe Task
4건이 전부 `completed` 라고 적었으나 실제로는 2건이 `ready` 였습니다. Dispatch
와 메시지 이력을 직접 확인해 증적이 온전함을 보고 `completed` 로 정정했습니다.
Laguna XS 는 첫 `worker_done` 의 `--from` 에 코디네이터 핸들을 넣어 거부됐다가
오류 문구를 보고 스스로 고쳤습니다.

---

## 2. 모델별 실측 결과

### 2.1 전달 경로

4종 모두 `dispatch --return-preamble` -> `kimi -p` 경로로 tool loop 와
`worker_done` 까지 완주했습니다. `dispatch --inject` 는 Kimi TUI 를 종료시킵니다.

### 2.2 능력 실측

`scripts/orca_level1_gate.py`(1,111줄) 감사 6문항을 **4종 동시 실행**했습니다.
정답은 해당 모듈을 직접 실행해 확정했으므로 채점에 주관이 들어가지 않았습니다.

| 모델 | 정답 | 소요 | 형식 |
| --- | :---: | ---: | --- |
| `or-free/laguna-xs` | 6/6 | 15s | 준수 |
| `or-free/laguna-s` | 6/6 | 26s | 준수 |
| `or-free/nemotron-ultra` | 6/6 | 57s | 준수 |
| `or-free/north-mini` | 6/6 | 86s | 출력 자리표시자를 그대로 남김 |

**정확도로는 변별되지 않았습니다.** 변별 지점으로 넣은 두 문항도 전부 맞혔습니다.
현재 `FREE_POOL_ORDER` 순서는 문맥 크기와 응답 시간 근거이며 **잠정**입니다.
순서를 능력 근거로 바꾸려면 더 어려운 과제로 재측정해야 합니다.

---

## 3. 이 세션에서 드러난 결함

### 3.1 등록된 무료 풀 1순위를 호출할 수 없었습니다

`opencode/deepseek-v4-flash-free` 가 계정 모델 목록에서 빠지고 호출이
`Model not found` 로 거부되는데 라우터는 그대로 1순위로 들고 있었습니다.

**원인은 삭제가 아니라 opt-in 미승인입니다.** 최신판이 중국 호스팅이라
워크스페이스 Go 설정에서 명시적 opt in 이 필요하고, 미승인 계정에서는 무료
variant 가 목록에서 사라집니다. 유료 variant 를 호출하면
`requires explicit opt in` 으로 원인을 명시합니다. **처음에 이 구분을 놓쳐
삭제로 잘못 판정했고, 사용자 지적으로 바로잡았습니다.**

재발을 막기 위해 [`../../scripts/audit_model_inventory.py`](../../scripts/audit_model_inventory.py)
를 추가했습니다. 배정 대상만 검사하고, **조회 실패를 소멸로 승격하지 않습니다.**

### 3.2 문서 정본의 낡은 기록

| 대상 | 상태 |
| --- | --- |
| OpenCode 무료 풀 목록 | `laguna-s-2.1-free` 도 목록에서 빠짐(원인 미확인), `muse-spark-1.2-contributor-free` 신규 |
| Codex 모델 ID | `gpt-5.6-sol-wm` 이 `models_cache.json` 에서 사라짐 |
| 예시 명령 | `opencode -m opencode/deepseek-v4-flash-free` 는 실행하면 실패 |
| 반복 금지 11장 | deepseek 을 "주력 사용 가능" 으로 판정 중이었음 |
| 3 장 절 번호 | 3.5·3.4·3.5 중복 |

### 3.3 근거 없이 옮겨 적은 CLI 주장

인계받은 Capsule 의 `ground_truth` 에 "`-p` 와 `-y`/`--auto` 병용 불가" 가
있었으나 `--help` 에는 그 제약이 없습니다. 직접 실행해 확인했습니다.

    error: Cannot combine --prompt with --yolo.   (종료 코드 1)
    error: Cannot combine --prompt with --auto.   (종료 코드 1)

주장은 사실이었고, 근거를 사양 인용에서 실측으로 바꿨습니다.

---

## 4. 병합 이력

| 커밋 | 내용 |
| --- | --- |
| `9f88ded` | Kimi 워커 경로 1.5 절 신설, 3 장 절 번호 교정 |
| `4a43374` | CURRENT_STATE 신선도 갱신 |
| `8661412` | OpenRouter 4종 등록, 소멸한 deepseek 제외, 테스트 13건 갱신 |
| `f1bdc32` | 등록 모델 실재 전수 대조 |
| `bb66ec5` | kimi 플래그 제약 실측 근거화 |
| `f10b04d` | 모델 소멸 자동 점검 도구 |

검증은 전체 테스트 1,555 passed / 2 skipped, `validate_agent_rules.py` 12/12,
ruff check·format 통과입니다.

---

## 5. 다음 세션이 이어받을 것

1. **원격 미반영**: 위 커밋 전부 로컬에만 있습니다. 푸시가 필요합니다.
2. **순서 재측정**: 무료 4종이 천장에 붙어 변별되지 않았습니다. 더 어려운
   과제가 필요하며, 그전까지 `FREE_POOL_ORDER` 순서는 능력 근거가 아닙니다.
3. **쓰기 적합성 미검증**: 4종 모두 읽기 전용 범위에서만 검증했습니다.
   `builder` 를 부여하려면 별도 실측이 필요합니다.
4. **deepseek opt in 이 가장 싼 복구입니다**: 워크스페이스 Go 설정에서 opt in
   한 뒤 `uv run python scripts/audit_model_inventory.py` 와 probe 로 확인하고
   `suitable_for` 와 `FREE_POOL_ORDER` 를 되돌리면 됩니다. 그전까지는
   `cursor-auto` 가 유일한 무료 builder 후보입니다.
5. **`cursor-auto` 재현 시험**: 2026-08-20 3회 시행에서 3회 모두 `OK` 를
   8~9초에 반환했습니다. 08-18 의 5회 중 3회 빈 출력은 재현되지 않았으나
   3회는 판정에 부족하므로 기존 주의는 유지합니다.
5. **터미널 정리**: GPT 의 Codex 창(`term_29ed7781`)이 코디네이터 탭과 같은
   `tabId` 라 닫지 않았습니다. 사용자가 직접 닫아야 합니다.
