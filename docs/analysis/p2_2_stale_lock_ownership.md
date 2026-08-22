# P2-2 분석 — Stale Lock Ownership 보강

> **tag**: p2_2_stale_lock_ownership
> **branch**: `kwanbum217/orca-p2-2`
> **base**: main `4fe939d merge: sync CURRENT_STATE source_commit after P1-1/P1-2 merge`

---

## 1. 동기

`docs/handoff/2026-08-22_post_1a45ad5_audit.md` P2-2: 기존 `_settings_lock`은 lock 파일에 보유 PID만 기록하고 finally 블록에서 소유권 확인 없이 같은 경로를 unlink 한다. 동시 trust 워커가 돌면 silent 로서 다른 프로세스의 lock을 지울 가능성이 남아 있으며, `finally` 블록의 무조건 unlink는 경쟁 시 정상 종료 후 lock 이 사라지지 않는 회귀를 만든다.

## 2. 변경 요약

| 파일 | 변경 |
| --- | --- |
| `scripts/orca_trust_worktree.py` | `_settings_lock`이 lock 파일에 `uuid:pid` 형태의 토큰을 기록하고, 동시 acquire 시점에는 PID 생존 검사를 더해 stale 회수 조건을 강화했다. finally 블록은 lock 파일 토큰을 다시 읽어 자기 토큰일 때만 unlink 하도록 변경. |
| `tests/test_orca_trust_worktree.py` | 회귀 테스트 4종 추가. |

## 3. 회귀 검증

```
uv run pytest tests/test_orca_trust_worktree.py -q
9 passed
python3 scripts/validate_agent_rules.py --quiet
검증 통과: 12/12 건
```

추가된 회귀 테스트:

| ID | 검증 |
| --- | --- |
| `test_settings_lock_other_token_is_not_recovered` | 같은 신선한 mtime + 살아있는 self PID lock 은 회수하지 않는다 |
| `test_settings_lock_release_only_owns_token` | finally 블록은 lock 토큰이 자기 token과 일치할 때만 unlink |
| `test_settings_lock_concurrent_acquire_serializes` | 다른 프로세스의 lock 으로 인해 두 번째 acquire는 timeout 내 실패 (실제 unlink 없음) |
| `test_settings_lock_stale_recovery` (보강) | 자식 fork + 즉시 종료한 PID로 stale lock 자동 회수 경로 검증 |

기존 `test_settings_lock_timeout`도 token 형식을 보장하도록 보강했다.

## 4. 격리 보장

- 모든 새 테스트는 `tmp_path`/`monkeypatch` 안에서 동작
- 모듈 상수 `LOCK_FILE`, `CLI_SETTINGS`, `TRUSTED_FOLDERS`는 monkeypatch 로 격리
- `~/.gemini` 사용자의 실제 설정은 손대지 않음

## 5. 잔여 리스크

- macOS PID 정책은 32bit 부호 정수까지 허용하지만, 검사 오버플로를 막기 위해 `pid > 2**22`은 살아있다고 보수 판정한다. 일부 워커 시스템에서 PID 가 큰 값일 경우 stale 회수가 보수적으로 동작해 사용자가 직접 lock 을 청소해야 하는 케이스가 있다. 운영 영향은 매우 작으나, 추후 `2**31 - 1`까지 완화하거나 OS 종속 PID 한계를 동적으로 검사하도록 확장할 여지가 있다.
- `_is_owner_process_dead` 의 `os.kill(pid, 0)`은 권한 거부 시 살았다고 보수 판정하기 때문에, 권한 부족 환경에서는 stale 회수가 의도보다 보수적으로 동작할 수 있다. 본 환경에서는 단일 사용자 권한으로 동작하므로 실효 영향은 없다.
