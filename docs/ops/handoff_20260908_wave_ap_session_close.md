# 인수인계: 20260908 Wave AP 세션 종료

> **작성일**: 2026-09-08
> **Run**: `run_eac9ca46a942` (선행 `run_1da2d36dee4d`, `run_4c211cc3687f`, `run_a6eec92b5e01`)
> **기준 커밋**: `5da507a` -> (본 커밋)
> **미병합 브랜치**: `kwanbum217/wave-ap1`, `kwanbum217/dashboard-latency`
> **인수 대상**: 다음 코디네이터
> **선행 문서**: [`handoff_20260908_wave_am_an_session_close.md`](handoff_20260908_wave_am_an_session_close.md)

---

## 0. 다음 세션 첫 작업 (최우선)

**AP1 브랜치를 검증하고 판정하십시오. 검증 전 병합 금지입니다.**

| 항목 | 값 |
| --- | --- |
| 브랜치 | `kwanbum217/wave-ap1` @ `9293642` |
| 워크트리 | `/Users/kwanbum/orca/workspaces/refac_bid_box/wave-ap1` (보존됨) |
| Task | `task_b31d76899b47` (상태 `blocked`) |
| Capsule | `.orca/capsules/task_b31d76899b47/capsule.yaml` |
| Intent | `.orca/intents/run_eac9ca46a942/ap1_kb_builder_streaming.yaml` |
| 빌더 | Antigravity `gemini-3.8-flash-medium` (effort 미지정, 기본값) |

**`worker_done` 을 받지 못했습니다.** 사용자 지시로 빌더 완료를 기다리지 않고 세션을
종료했습니다. Dispatch `ctx_d779f936dd3c` 는 `dispatched` 로 남아 있고
`worker-release` 가 `dispatch_inactive` 로 거부됩니다. 워커 창은 닫았습니다.

이어갈 절차입니다.

```bash
# 1. Level 1 게이트 (worker_done 보고가 없으므로 --allow-missing-report 필요)
python3 scripts/orca_level1_gate.py --base main --branch kwanbum217/wave-ap1 \
  --repo /Users/kwanbum/orca/workspaces/refac_bid_box/wave-ap1 \
  --capsule .orca/capsules/task_b31d76899b47/capsule.yaml \
  --allow-missing-report --json

# 2. 통과하면 독립 리뷰어 Dispatch (빌더가 Gemini 이므로 Qwen 또는 Grok)
#    review_checklist 는 build_review_intent.py 로 빌더 Capsule 에서 복사

# 3. 리뷰 통과 시에만 병합
cd /Users/kwanbum/orca/workspaces/refac_bid_box/wave-ap1
git rebase main && python3 scripts/premerge_full_suite_gate.py --record
```

---

## 1. AP1 이 무엇을 고치려 했는가

`rebuild_knowledge_base` 가 최근 1년치 문서를 메모리에 전량 적재해 worker 컨테이너가
**10.5GB** 를 쓰고 소멸하는 결함입니다. 확정 원인과 실측 곡선은
[`../analysis/kb_builder_memory_exhaustion_20260908.md`](../analysis/kb_builder_memory_exhaustion_20260908.md)
에 있습니다. **기각된 가설 다섯을 재조사하지 마십시오.**

---

## 2. 코디네이터가 확인한 것

git 과 diff 로 직접 본 사실만 적습니다.

| 항목 | 확인 결과 |
| --- | --- |
| 커밋 | `9293642` 1건, 미커밋 변경 0건 |
| 변경 파일 | `src/app/services/kb_builder.py`, `tests/test_kb_builder.py` 둘뿐 |
| 규모 | 600 추가 / 132 삭제. 테스트 460줄 신규 |
| 쓰기 범위 | Capsule 의 `allowed_write_files` 안 (초과 0건) |
| `CHUNK_SIZE = 1_000` | 상수로 노출되고 `__all__` 에 추가됨 |
| `chunk_size: int = CHUNK_SIZE` | 인자로 주입 가능 |
| `_sync_stream` | 신설. `for start in range(0, len(items), chunk_size)` 로 청크 순회 |
| 증분 판정 흔적 | `existing_hashes` 기반 `removed_ids` 계산이 남아 있음 |

---

## 3. 코디네이터가 확인하지 않은 것

**아래는 전부 미검증입니다. 워커 주장도 없습니다.**

- Level 1 게이트 **미실행**
- 리뷰어 **미배정**
- `tests/test_kb_builder.py` 460줄이 실제로 통과하는지 미확인
- 전량 테스트 결과 미확인 (빌더가 실행 중이었으나 결과를 받지 못함)
- `uv run mypy src` 미실행
- 메모리 상한 회귀 테스트가 실효적인지 미판정
- 증분 판정 의미가 실제로 보존됐는지 미판정
- 반환 형식과 `metrics` 키 불변 여부 미확인

---

## 4. 코디네이터가 지목한 확인 지점

diff 를 읽다 발견한 것입니다. **리뷰어와 게이트가 반드시 판정해야 합니다.**

```python
target_ids = {make_id(i, it) for i, it in enumerate(items)}
removed_ids = [doc_id for doc_id in existing_hashes if doc_id not in target_ids]
```

청크로 나눠 처리하면서도 이 두 줄은 `items` 전량을 순회해 집합을 만듭니다.
`existing_hashes` 도 536,002건이 상주합니다. **메모리 상한 회귀 테스트가 이 경로까지
덮는지**가 이번 수정의 성패입니다. 덮지 않으면 문서 수가 늘 때 같은 지점에서 다시
깨집니다.

---

## 5. 배정 실수 하나

**`--effort` 를 지정하지 않았습니다.** `risk: high` Task 인데 `--model` 만 주고
effort 는 기본값으로 돌렸습니다. 사용자가 워커의 Read/Edit 반복을 보고 지적해
드러났습니다.

산출물 자체는 계약 항목을 반영했으나, 다음에 `risk: high` 를 배정할 때는
`--effort high` 를 함께 주십시오. `--effort` 는 `--model` 과 함께여야 하고 둘 다
`--terminal` 과는 쓸 수 없으므로, 터미널 부착 경로에서는 런처 인자로 넘겨야 합니다.

**probe 관련 정정**: `orca_model_router.py probe` 가 이 세션 내내 Gemini 에 대해
20초 타임아웃을 냈으나 **런처 경로로는 정상 기동했습니다.** probe 상한이 20초로
고정돼 있고 Antigravity 스플래시가 그보다 느립니다. **probe 실패를 모델 불가용으로
읽지 마십시오.**

---

## 6. 이 세션이 닫은 것

| 내용 | 병합 |
| --- | --- |
| 놓친 02:00 슬롯 판정으로 기동 따라잡기 개선 | `80d7cb0` |
| 코디네이터 교대와 catchup 운영 검증 기록 | `9ef75d1` |
| catchup 색인 실패 진단 정정 (디스크 공간 오진) | `301a164` |
| KB 색인 실패 확정 원인과 실측 곡선 | `5da507a` |

**따라잡기는 운영에서 실제로 동작했습니다.** `bid_announcements` 5,498,959 ->
5,500,771행(+1,812), 최신 `collected_at` 2026-09-07 12:58 -> 2026-09-08 09:05.
색인 단계만 실패했고 그 원인이 AP1 이 고치려는 결함입니다.

---

## 7. 남은 항목

| ID | 내용 | 선행 조건 |
| --- | --- | --- |
| **최우선** | AP1 검증과 판정 (0장) | 없음 |
| 대시보드 금액 집계 실측 | `get_compare_stats_data` 경로로 다시 측정 | AP1 과 무관 |
| `kwanbum217/dashboard-latency` | 리뷰 fail 로 미병합. 보고서 4.2절 수치가 산출물 JSON 에 없음 | 원격 백업됨 |
| **R-12** | G2 Windows Docker Desktop 실기 | Windows 장비 |
| **R-10 2단계** | Prometheus 추가 | 메트릭 계측 선행 |
| 문서 역사층 분리 | `task_*.md` 와 handoff 퇴역, 674 -> 250 이하 | 선행 handoff 12장 |

---

## 8. 환경 변경 기록

| 항목 | 변경 |
| --- | --- |
| Docker Desktop `MemoryMiB` | 14,336 -> **16,384** (백업 `settings-store.json.bak.20260908`) |

**이것은 해법이 아닙니다.** 원인 규명 과정에서 인과를 확인하려고 올린 것이며, 16GiB
에서도 전체 파이프라인은 재현됐습니다. AP1 이 병합되면 되돌려도 무방합니다.

---

## 9. 정리 상태

**워커 창은 모두 닫았습니다.** AP1 워커 터미널과 워크트리 기본 셸 둘 다 종료했고
`orca_settled_session_audit.py` 는 잔류 없음입니다. 자동 승인 감시기도 중지했습니다.

**`worker-release` 는 성립하지 않았습니다.** `worker_done` 미수신으로 Dispatch 가
`dispatched` 상태라 `dispatch_inactive` 로 거부됩니다. Task `task_b31d76899b47` 를
`blocked` 로 기록해 그 사실을 남겼습니다.

**워크트리와 브랜치는 보존했습니다.** `wave-ap1` 은 다음 세션이 검증을 이어가야
하므로 제거하지 않았습니다.

**Docker 스택은 내렸습니다.** Redis 를 `SHUTDOWN NOSAVE` 로 먼저 종료한 뒤
`docker compose down` 했으며 데이터 볼륨 3종(`mysql_data`, `redis_data`,
`meilisearch_data`)은 보존했습니다.
