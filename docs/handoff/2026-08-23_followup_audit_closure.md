# 후속 감사 항목 처리 인수인계 (2026-08-23 야간)

> **작성일**: 2026-08-23 (Asia/Seoul)
> **작성자**: Orca 코디네이터 (Claude Opus 5)
> **Orca Run**: `run_a70e06fe0719`
> **사유**: 사용자 장비 가용 시각 21:00 마감으로 세션 종료
> **현재 정본**: [`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md)

---

## 1. 이번 세션에서 닫은 것

병렬 5트랙(쓰기 워커 상한 3대 준수, 리뷰어는 읽기 전용이라 미포함)으로 진행했습니다.

| 트랙 | 과업 | 모델 | 결과 |
| --- | --- | --- | --- |
| C | 수집 2·3회차 관찰 | Antigravity `gemini-3.7-flash-medium` | 병합 |
| A | 실제 컨테이너 워커 큐 측정 | Antigravity `gemini-3.7-flash-high` | 병합 |
| D | P1 런타임 소스 provenance | Antigravity `gemini-3.7-flash-high` | 병합 |
| B | HTMX 이행 계획서 | Kimi `or-free/nemotron-ultra` | 아래 3장 참조 |
| E | trust lock 경쟁 + `os.fork()` 제거 | Antigravity `gemini-3.7-flash-high` | 아래 3장 참조 |

### 1.1 P1 런타임 소스 provenance (최우선 항목)

`docker-compose.yml`의 `app`·`worker`가 `./src:/app/src`를 bind mount 하므로 이미지 ID는
실행되는 Python 코드를 증명하지 못했습니다. `reproducibility_metadata`에 다음을 추가했습니다.

| 키 | 의미 |
| --- | --- |
| `target_source_mount` | `docker inspect .Mounts`에서 `/app/src`의 host 경로 |
| `target_source_git_sha` | 그 경로 worktree 의 HEAD |
| `target_source_git_dirty` | 미커밋 변경 유무 |

strict 모드에서 dirty 이거나 판정 불가면 `BuildProvenanceError`로 측정을 거부합니다.
bind mount 가 없는 이미지 전용 컨테이너는 거부하지 않고 `target_source_mount`를 null 로 남깁니다.

### 1.2 실제 컨테이너 워커 큐 측정

운영 `WorkerSettings`와 `docker-compose.yml`을 건드리지 않고, 같은 이미지로 벤치마크 전용
`WorkerSettings`(`scripts/_bench_worker_settings.py`)를 일회성 컨테이너로 띄워 측정했습니다.

| 경로 | 처리량 | P95 | 실패율 |
| --- | ---: | ---: | ---: |
| 컨테이너 워커 (신규) | 1,636 jobs/sec | 352.6ms | 0% |
| in-process (기존) | 1,107 jobs/sec | 519.2ms | 0% |

증거 JSON 에 워커 컨테이너 ID, 이미지 ID, Redis 컨테이너 ID, docker 버전, host load,
`max_jobs`가 기록됩니다.

### 1.3 수집 2·3회차 관찰

코디네이터가 DB 를 직접 조회해 보고서 수치와 일치함을 확인했습니다.
`bid_announcements` 5,475,948행, `bid_results` 3,413,823행, `institution_win_rate_stats`
38,834행, `bid_ranking_snapshots` 152행, `collected_at` 최대 2026-08-14 04:37.

마지막 수집이 9일 전이라 `_step_inspect`의 최신성 경고 기준(`stale_hours > 48`)에 해당합니다.
운영 재개 시 4회차 트리거로 갱신해야 합니다.

### 1.4 문서 계층

`CURRENT_STATE` G2 에 최신 Windows CI FAIL 과 원인(`os.fork()`)을 명시했습니다. SSOT 만
읽고 Windows CI 가 정상이라고 오독하던 문제를 없앴습니다. `REFACTORING_DESIGN`의 Phase 7
절과 2026-08-23 handoff 2건에 섹션 단위 HISTORICAL/SNAPSHOT 배너를 붙였습니다. 청크 단위로
검색하는 에이전트가 상단 배너를 놓치는 경우에 대비한 조치입니다.

---

## 2. 코디네이터가 되돌린 오분류

2026-08-23 낮에 코디네이터가 `CURRENT_STATE` Active Priorities 를 정리하면서
**신뢰 설정 잠금·복구를 종결로 잘못 분류**했습니다. 커밋 목록만 보고 판단했고 소스를
확인하지 않았습니다. `scripts/orca_trust_worktree.py`에 경쟁이 그대로 남아 있어
진행 과업으로 복원했습니다. 종결 판정은 커밋 이력이 아니라 소스로 확인해야 합니다.

---

## 3. 마감 시점 미완 트랙

| 트랙 | 상태 |
| --- | --- |
| B (HTMX 계획서) | 워커가 268줄 계획서를 작성했으나 주 저장소에 썼고 코디네이터가 워크트리로 옮겼습니다. 커밋 여부는 아래 5장 확인 명령으로 판단하십시오 |
| E (trust lock) | `scripts/orca_trust_worktree.py`와 `tests/test_orca_trust_worktree.py` 수정 중이었습니다. 미커밋이면 워크트리에 변경이 남아 있습니다 |

두 워크트리는 병합 전까지 제거하지 마십시오.

---

## 4. 남은 과업 (우선순위 순)

| 순위 | 과업 | 근거 |
| --- | --- | --- |
| 1 | **Windows CI 복구** | `tests/test_orca_trust_worktree.py`의 `os.fork()` 제거. E 트랙이 착수했으므로 잔여분만 확인 |
| 2 | **trust stale 회수 경쟁 제거** | `orca_trust_worktree.py:71`의 `stat()`이 suppress 밖이라 미포착 `FileNotFoundError` 가능. `:75` `unlink()`가 새 소유자 락을 지울 수 있음. POSIX `fcntl.flock` / Windows `msvcrt.locking` 으로 통일 권장 |
| 3 | **Arq raw evidence provenance 이행** | [`arq_threshold_provenance_20260823.md`](../ops/arq_threshold_provenance_20260823.md)는 host/Redis/Arq/Docker 4계층을 요구하나 `benchmark_arq_throughput.py`의 `environment`는 `python`·`platform`·`redis_url` 3개뿐. 컨테이너 하네스(`benchmark_arq_container.py`)의 구현을 이식하면 됨 |
| 4 | **Arq 절대 기준선 도출 근거 명문화** | 900 jps / 600ms 가 어느 frozen baseline 에서 나왔는지 미명시. 근거를 못 세우면 provisional consistency envelope 로 정확히 개명 |
| 5 | **Arq 3회 raw 전부 보존** | 현재 worst 1회분만 커밋됨. 제3자가 저장소만으로 3회 수행을 재구성할 수 없음 |
| 6 | **성능 설정 snapshot 기록** | `WEB_CONCURRENCY`, `PREDICTION_GC_MODE`, `LATENCY_SEGMENT_LOGGING`, LLM provider/model 등 비밀값 제외 설정을 evidence 에 포함. 같은 이미지·소스여도 이 값이 다르면 다른 벤치마크 |
| 7 | **Ollama c4 측정** | 재기동 승인 필요. Docker 배타 자원 |
| 8 | **단발 RAG/LLM 내부 구간 검증** | Docker 배타 자원 |
| 9 | **Windows Docker Desktop 실기** | **장비 부재로 차단.** 사용자 장비 확보 전까지 진행 불가 |
| 10 | **프론트엔드 HTMX 도입 여부 결정** | B 트랙 계획서를 근거로 사용자가 결정. 도입 시 4~6시간 별도 과업 |
| 11 | **G3 전체 컷오버 판정** | 위 항목이 닫힌 뒤. 코디네이터가 직접 판정하며 위임하지 않음 |

---

## 5. 재개 시 첫 명령

```bash
cd /Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box
git branch --show-current                 # main 인지 반드시 확인
git status --short --branch
git worktree list

for w in htmx-plan trust-lock; do
  echo "== $w"
  git -C /Users/kwanbum/orca/workspaces/refac_bid_box/$w log --oneline main..HEAD
  git -C /Users/kwanbum/orca/workspaces/refac_bid_box/$w status --short
done

python3 scripts/validate_agent_rules.py
uv run pytest tests/ -q -m 'not data_assets'
```

---

## 6. 이번 세션에서 배운 운영 함정

1. **워커가 격리 워크트리를 벗어납니다.** Antigravity Sonnet 과 Kimi 둘 다 주 저장소로
   `cd` 했습니다. Sonnet 은 거기서 브랜치까지 만들어 코디네이터의 병합 2건이 엉뚱한
   브랜치에 쌓였고, 그 브랜치를 지우면서 병합이 포인터를 잃었습니다. 커밋 해시로
   복구했습니다. **병합 직전마다 `git branch --show-current`를 확인하고, 브랜치를 지우기
   전에 `git log --oneline main..<branch>` 결과를 반드시 읽으십시오.**
2. **워커가 Capsule scope 밖 파일을 만듭니다.** A 트랙이 같은 문서를 두 경로에 생성했고
   B 트랙도 분석서를 추가로 만들려 했습니다. 병합 전 `git diff --name-only`로 scope 대조가
   필요합니다.
3. **리뷰어 답변 극성이 자주 뒤집힙니다.** `defect_when: "yes"` 항목에 근거는 맞게 쓰고
   답변만 반대로 적는 사례가 반복됐습니다. 근거 문장을 읽어야 합니다.
4. **리뷰어 PASS 를 그대로 믿지 마십시오.** Gemini 리뷰어가 `pass` 를 준 브랜치에서
   코디네이터가 `provenance_consistent` 상수 기록 결함을 찾았습니다.
5. **`agent_prompt_stalled` 는 오탐입니다.** 화면을 직접 읽어 도달을 확인하십시오. 다만
   터미널 생성 직후 곧바로 dispatch 하면 스플래시에 입력이 먹힙니다. 기동 후 10초 이상
   두고 주입하거나 재주입하십시오.
