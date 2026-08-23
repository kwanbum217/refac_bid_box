# Orca 후속 작업 인수인계 (2026-08-23)

> [!NOTE]
> **SNAPSHOT / HISTORICAL** — 작성 시점의 상태 기록입니다. 현재 정본은 [`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md)입니다.


> **작성일**: 2026-08-23 (Asia/Seoul)
> **사유**: 현재 코디네이터 5시간 토큰 사용량 92%
> **현재 main**: `d95efd5` (`origin/main`과 일치)
> **Orca Run**: `run_a70e06fe0719`
> **현재 상태**: P1 provenance 후보 구현·Level 1 통과, main 병합 대기

---

## 1. 이번 세션에서 수행한 작업

핸드오프 [`2026-08-22_post_1a45ad5_audit.md`](2026-08-22_post_1a45ad5_audit.md)의 최우선 P1인 benchmark provenance 결박을 구현했습니다.

| 항목 | 결과 |
| --- | --- |
| `base_url`과 Docker container 포트 결박 | loopback/container IP/포트 불일치 strict 거부 |
| target container 지정 | `--target-container` 지원 및 container/image 식별자 분리 |
| SSE provenance | 존재하지 않는 `backend` 조회 제거, `app` 정책 공유 |
| 원격 host false-pass | 동일 포트만 일치하는 원격 host를 strict 거부 |
| strict JSON 중복 | benchmark 경로를 `_strict_json.py`로 통일 |
| 저장소 Ruff 오류 | 전체 `ruff check .` 통과하도록 기존 오류 7건 정리 |
| 상태 문서 | feature branch에서 `source_commit`을 `28a06b2`로 동기화 |

커밋은 feature branch `kwanbum217/p1-provenance-binding`에만 존재합니다.

```text
0d0aead fix: bind benchmark provenance to target container
28a06b2 fix: reject unproven remote benchmark targets
313aac4 docs: sync current state source commit
dfdd172 fix: clear repository lint gate findings
```

---

## 2. 검증 상태

- 대상 benchmark 테스트: `29 passed`
- 관련 strict JSON/trust/Arq 테스트: `63 passed`
- feature branch 전체 테스트: `1782 passed, 2 failed, 6 skipped`
- 전체 테스트의 2건 실패는 격리 worktree에 Git 무시 자산(`data/model_files`, `chroma_db`)이 없는 알려진 예외입니다.
- 저장소 전체 Ruff: 통과
- 변경 스크립트 Bandit: 통과
- `python3 scripts/validate_agent_rules.py --quiet`: `12/12 passed`
- `orca_level1_gate.py --strict`: `pass`, 6개 게이트 중 5개 통과, 리뷰 보고 게이트 1개는 optional skip

Level 1 결과는 다음 조건으로 실행했습니다.

```bash
python3 scripts/orca_level1_gate.py \
  --base main \
  --branch kwanbum217/p1-provenance-binding \
  --repo /Users/kwanbum/orca/workspaces/refac_bid_box/p1-provenance-binding \
  --tests 'tests/test_benchmark_latency.py tests/test_benchmark_sse_gate.py' \
  --capsule /Users/kwanbum/orca/workspaces/refac_bid_box/p1-provenance-binding/docs/orca/capsules/p1_provenance_binding_20260823/capsule.yaml \
  --strict --json
```

---

## 3. 병합 상태와 차단 사유

아직 `main`에는 병합하지 않았습니다.

- Level 1은 통과했습니다.
- Level 2 독립 reviewer 보고서는 아직 없습니다.
- strict finalize 증거와 reviewer PASS가 없으므로 `merge_verified_branch.py` 우회 금지입니다.
- feature worktree는 병합 전까지 삭제하지 않습니다.

병합 전 필요한 절차입니다.

1. 독립 reviewer가 실제 diff를 검토하고 `ORCA_REVIEW_DONE_V2` 보고서를 생성합니다.
2. worker 완료 보고, Capsule, reviewer 보고를 `orca_taskctl finalize`로 검증합니다.
3. `target_commit`이 현재 main과 일치하는지 다시 확인합니다.
4. strict finalize PASS 후에만 `git merge --no-ff`를 수행합니다.
5. 병합 후 `CURRENT_STATE.md`의 semantic state와 `source_commit`을 같은 작업 단위로 갱신합니다.

---

## 4. Orca 워커 상태

### 4.1 현재 Run `run_a70e06fe0719`

| Task | 상태 | 비고 |
| --- | --- | --- |
| P1 provenance 설계 조사 | completed | Kimi 보고서 존재 |
| P1 provenance 구현 | completed (coordinator recovery) | Gemini Dispatch capability 폐기 후 코디네이터가 diff 보완·커밋 |
| P1 diff commit-review | failed | Kimi OpenRouter `provider.api_error: 404` |

### 4.2 주의할 살아 있는 세션

main worktree의 `term_b7d51144-c0e4-4715-b2b5-632ad2ec15e5`는 `worker-list`에 등록된 Dispatch가 아니지만, 화면상 Kimi Nemotron 프로세스가 실행 중이며 P1 worktree의 start/end provenance를 수정 중이라고 표시되었습니다.

- 이 세션은 완료 세션으로 간주하거나 회수하지 않습니다.
- 먼저 `orca terminal read --terminal term_b7d51144-c0e4-4715-b2b5-632ad2ec15e5 --screen --json`으로 현재 상태를 확인합니다.
- 실제 변경 파일과 프로세스 소유권을 확인하기 전에는 종료·재기동·동일 worktree 수정 금지입니다.
- 현재 확인된 `reclaimable` 워커는 0개입니다.

---

## 5. 다음 작업 순서

핸드오프 정본의 순서를 유지합니다.

1. P1 feature branch의 독립 Level 2 reviewer 확보 및 strict finalize
2. P1 branch를 `main`에 `--no-ff` 병합
3. 병합 후 전체 테스트와 규칙 검증 재실행
4. start/end provenance 기록 및 측정 중 container/image 교체 무효화
5. trust lock `read -> stat -> unlink` TOCTOU 보완 및 경쟁 테스트
6. `c2_disposition_20260822.md`의 c2 단독 표본 수를 6,000으로 명확화
7. `CURRENT_STATE.md`의 완료/미완료 semantic state 갱신
8. Arq threshold 도출식과 host/Redis/Arq/Docker provenance 문서화
9. 실제 Docker `worker` 업무 큐 측정
10. Ollama c4와 Windows Docker Desktop G2 검증 후 G3 전체 판정

---

## 6. 재개 명령

```bash
git status --short --branch
git rev-parse HEAD origin/main
git -C /Users/kwanbum/orca/workspaces/refac_bid_box/p1-provenance-binding status --short --branch
git -C /Users/kwanbum/orca/workspaces/refac_bid_box/p1-provenance-binding log --oneline main..HEAD
/Users/kwanbum/.local/bin/orca status --json
/Users/kwanbum/.local/bin/orca orchestration task-list --run run_a70e06fe0719 --brief --json
/Users/kwanbum/.local/bin/orca orchestration worker-list --json
```

재개 시 반드시 먼저 읽을 문서입니다.

- `AGENTS.md`
- `docs/context/CURRENT_STATE.md`
- `docs/handoff/2026-08-22_post_1a45ad5_audit.md`
- 본 문서

기존 raw benchmark JSON, Docker volume/image, `.env` 실제 값은 변경하거나 문서에 기록하지 않습니다.
