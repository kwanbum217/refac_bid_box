# task_x2_residual_cleanup — R-15 잔여 및 취소 계측 정리

> **날짜**: 2026-09-05
> **Task**: `task_b6cef03e3887`
> **브랜치**: `kwanbum217/wave-x-x2-cleanup`

V3 가 GitHub Actions 를 SHA 로 고정한 뒤 Dockerfile 의 uv 이미지가 태그 참조로 남았고, 취소 계측에 동작이 없는 코드가 두 곳 있었다. 이 문서는 그 두 잔여를 정리한 근거와 검증이다.

## 1. Dockerfile uv 이미지 다이제스트 고정 (R-15)

### 1.1 실측

명령:

```bash
docker buildx imagetools inspect ghcr.io/astral-sh/uv:0.12.5
```

결과의 최상위 필드:

| 필드 | 값 |
| --- | --- |
| Name | `ghcr.io/astral-sh/uv:0.12.5` |
| MediaType | `application/vnd.oci.image.index.v1+json` |
| Digest | `sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1` |

플랫폼별 매니페스트(`linux/amd64`, `linux/arm64`)는 인덱스 아래 항목이다. 핀은 인덱스를 쓴다. 태그를 지우지 않고 `tag@sha256:<64자>` 형식을 유지한다.

### 1.2 Dockerfile 변경

```dockerfile
COPY --from=ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 /uv /bin/uv
```

정책 목록은 [`docs/ops/supply_chain_policy.md`](../ops/supply_chain_policy.md) 10.2절 3항에 같은 참조를 넣었고, 10.3절에 이미지 다이제스트 갱신 절차를 추가했다. 문서 버전은 1.4.0 에서 1.4.1 이다.

## 2. 취소 계측에서 실효 없는 코드 제거

### 2.1 `except asyncio.CancelledError: raise`

`traced_worker_task` 의 `async_wrapper` 와 `sync_wrapper` 는 `trace_worker_task` 가 이미 취소를 기록한 뒤 같은 예외를 다시 던진다. 바깥에서 잡아 그대로 재발생시키는 절은 없을 때와 동작이 같다. 두 wrapper 에서 제거했다. 취소 기록과 재전파는 `trace_worker_task` 한 곳에 남는다.

### 2.2 `_resolve_cancel_reason` 의 `exc.args` 검사

`asyncio.CancelledError` 는 운영 경로에서 인자를 갖지 않는다. 실제 구분은 `src/tasks/worker.py` 가 ctx 에 넣는 값이다.

| ctx 키 | 실제 위치 | 분류 |
| --- | --- | --- |
| `is_background_catchup` | `src/tasks/worker.py:173` | `worker_shutdown` |
| `worker_shutting_down` | `src/tasks/worker.py:196` | `worker_shutdown` |

Capsule 의 121행·144행은 현재 HEAD 와 어긋난다. 키 이름과 역할은 맞고, 줄 번호만 밀려 있다. `worker.py` 는 이 Task 쓰기 범위가 아니므로 수정하지 않았다.

예외 인자 분기를 제거했고, 사용되지 않는 `exc` 매개변수까지 없앴다. ctx 검사와 취소 시 span 상태를 `UNSET` 으로 두는 동작은 그대로다.

근거: 인자가 실리는 운영 경로가 없다. 테스트가 `CancelledError("worker_shutdown")` 를 쓰던 것은 인자를 흉내 낸 것이고, 같은 테스트의 ctx 에 이미 `worker_shutting_down=True` 가 있다. 인자를 비운 뒤에도 ctx 만으로 분류가 유지된다.

## 3. 테스트

- 셧다운 시나리오는 인자 없는 `CancelledError()` 로 바꿨다.
- `test_cancel_reason_ignores_exception_args_and_uses_ctx` 를 추가했다. 메시지에 `worker_shutdown` 이 있어도 ctx 가 없으면 `aborted` 이고, 인자가 없어도 `is_background_catchup` 이면 `worker_shutdown` 이다.

## 4. 검증

| 명령 | 결과 |
| --- | --- |
| `uv run pytest tests/test_observability.py -q` | 21 passed in 0.90s |
| `docker build -t refac-bid-box-root:orca-gate .` | 종료 코드 0 |
| `uv run mypy src` | no issues found in 93 source files |
| `python3 scripts/validate_agent_rules.py --quiet` | 20/20 |

상세는 [`task_b6cef03e3887.md`](task_b6cef03e3887.md) 이다.
