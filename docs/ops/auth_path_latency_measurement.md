# 인증 경로 레이턴시 측정 절차서

> **작성일**: 2026-09-19
> **버전**: v1.0.0
> **상태**: 측정 하니스 및 정본 절차 확정 (측정 실행은 코디네이터가 수행)
> **관련 스크립트**: `scripts/benchmark_auth_paths.py`
> **단위 테스트**: `tests/test_benchmark_auth_paths.py`
> **측정 조건**: `docs/analysis/read_path_concurrency_20260918.md` 조건 준용 (단일 웜: 워밍업 3회 + 본 측정 30회 / 동시성: c10, 100회)

---

## 1. 목적 및 배경

2026-09-18 읽기 경로 실측(`docs/analysis/read_path_concurrency_20260918.md`)에서는 비인증 경로(공고 목록, 낙찰 목록, 홈 컨텍스트, 대시보드 통계)만을 대상으로 P95 레이턴시를 측정했습니다. 세션 쿠키를 발급받아 재사용하는 표준 절차가 문서화되지 않아 인증이 필요한 화면 및 API 경로가 측정에서 제외되었습니다.

`AGENTS.md` 는 G3 스택 최적화를 일회성 과업이 아닌 상시 과제로 규정하며, 측정되지 않은 경로는 최적화 대상이 될 수 없습니다. 본 문서는 사용자 인증이 필요한 엔드포인트의 단일 웜 및 동시성(c10) 레이턴시를 안전하고 일관되게 측정하기 위한 세션 쿠키 발급 절차, 측정 계정 준비 가이드, 대상 및 제외 엔드포인트 판별 기준, 하니스 실행 절차를 확정합니다.

---

## 2. 세션 쿠키 발급 아키텍처 및 제약 사항

### 2.1 세션 쿠키 사양

| 항목 | 내용 | 근거 코드 |
| --- | --- | --- |
| 쿠키 이름 | `bidbox_session` | `src/app/core/security.py:38` (`SESSION_COOKIE_NAME`) |
| 세션 유효 기간 (TTL) | 14일 (`1,209,600`초) | `src/app/core/security.py:37` (`SESSION_TTL_SECONDS`) |
| 쿠키 발급 지점 | `_issue_session` | `src/app/api/v1/accounts.py:147` |
| 로그인 엔드포인트 | `POST /api/v1/accounts/login` | `src/app/api/v1/accounts.py:216` |
| 인증 판정 의존성 | `get_current_user` / `require_current_user` | `src/app/api/v1/accounts.py:110, 127` |

세션 유효 기간이 14일이므로 측정 세션 동안 쿠키가 만료되지 않으며, 한 번 발급받은 쿠키를 전체 측정 회차에 걸쳐 재사용할 수 있습니다.

### 2.2 로그인 시도 제한(Rate Limiter) 주의

`src/app/api/v1/accounts.py:229`에는 `login_rate_limiter.check_rate_limit(ip, payload.username)` 가 적용되어 있습니다. 짧은 시간 동안 반복적인 로그인을 시도할 경우 429 (Too Many Requests) 차단이 발생합니다.

따라서 동시성(c10, 100회) 측정 과정에서 매 요청마다 로그인을 시도하면 정상적인 서비스 응답 지연이 아니라 로그인 차단 응답 시간을 측정하게 됩니다. **스크립트는 측정 회차 시작 시 단 1회만 로그인하여 `Set-Cookie` 에서 `bidbox_session` 값을 추출하고, 이후 모든 단일 웜 및 동시성 요청에 해당 쿠키를 재사용해야 합니다.**

---

## 3. 측정 계정 준비 절차

### 3.1 계정 하드코딩 금지 원칙

- 코드(`scripts/benchmark_auth_paths.py`) 및 본 문서에 실제 사용자명과 비밀번호를 절대 하드코딩하거나 커밋하지 않습니다.
- 자격 증명은 CLI 옵션(`--username`, `--password`) 또는 환경변수(`BENCHMARK_USERNAME`, `BENCHMARK_PASSWORD`)를 통해서만 주입받습니다.
- 자격 증명이 주어지지 않으면 스크립트는 즉시 실행을 거부하고 명확한 오류(종료 코드 2)로 종료합니다.

### 3.2 코디네이터 사전 점검 명령

측정 실행 전, 코디네이터는 읽기 전용 질의 도구를 통해 측정에 사용할 수 있는 활성 계정의 존재 여부를 확인합니다. (새로운 계정을 `signup` 엔드포인트로 등록하거나 DB에 직접 쓰지 않습니다.)

```bash
# 활성 상태인 사용자 확인 (읽기 전용 질의 도구 사용)
uv run python scripts/db_readonly_query.py --sql "SELECT id, username, is_active, is_staff FROM custom_user WHERE is_active = 1 LIMIT 5;"
```

확인된 계정 정보는 셸 세션의 환경변수로 설정하여 하니스에 주입합니다.

```bash
export BENCHMARK_USERNAME="<계정_사용자명>"
export BENCHMARK_PASSWORD="<계정_비밀번호>"
```

또는 이미 브라우저나 이전 세션에서 발급된 쿠키가 있다면 직접 세션 쿠키를 전달할 수도 있습니다:

```bash
export BENCHMARK_SESSION_COOKIE="<발급받은_bidbox_session_값>"
```

---

## 4. 측정 대상 및 제외 대상 상세

측정 대상은 **부작용(DB 쓰기, 외부 수집, 배치 작업 등록)이 전혀 없는 순수 조회 경로**로만 한정됩니다.

### 4.1 측정 대상 엔드포인트 (3개 경로)

| 식별자 | HTTP 메서드 및 경로 | 설명 | 판단 근거 (부작용 없음) |
| --- | --- | --- | --- |
| `accounts_me` | `GET /api/v1/accounts/me` | 현재 로그인 사용자 정보 조회 | `src/app/api/v1/accounts.py:265`. `require_current_user` 검증 후 `_serialize(user)` 만 반환하며 DB 쓰기 작업이 일절 없음. |
| `evaluations_profiles` | `GET /api/v1/evaluations/profiles` | 내 평가 프로필 목록 조회 | `src/app/api/v1/evaluations.py:741`. 로그인한 사용자의 `BidEvaluationProfile` 레코드만 SELECT 조회하여 반환함. |
| `evaluations_snapshots` | `GET /api/v1/evaluations/snapshots` | 내 분석 스냅샷 목록 조회 | `src/app/api/v1/evaluations.py:906`. 로그인한 사용자의 `BidEvaluationSnapshot` 레코드만 SELECT 조회하여 반환함. |

### 4.2 제외 대상 엔드포인트 및 경로별 판단 근거

| HTTP 메서드 및 경로 | 제외 사유 및 상세 판단 근거 | 근거 위치 |
| --- | --- | --- |
| `POST /api/v1/bids/collect` | 나라장터 OpenAPI 외부 실시간 수집(`collect_bids`)을 트리거하고 DB에 대량 쓰기를 수행하므로 절대 측정 불가. | `src/app/api/v1/bids.py:243` |
| `POST /api/v1/evaluations/analyze` | 적격심사 통합 분석 완료 시 `_save_snapshot_async`가 호출되어 `BidEvaluationSnapshot` 및 `BidEvaluationEvidence`를 DB에 `db.add()` 및 `db.commit()` 하므로 동시성 측정 시 DB 쓰기 누적 부작용이 발생함. | `src/app/api/v1/evaluations.py:569, 686` |
| `POST /api/v1/evaluations/profiles` | 새로운 평가 프로필을 DB에 INSERT 및 `db.commit()` 수행. | `src/app/api/v1/evaluations.py:780` |
| `PUT /api/v1/evaluations/profiles/{profile_id}` | 기존 평가 프로필을 DB에 UPDATE 및 `db.commit()` 수행. | `src/app/api/v1/evaluations.py:843` |
| `DELETE /api/v1/evaluations/profiles/{profile_id}` | 평가 프로필을 DB에서 DELETE 및 `db.commit()` 수행. | `src/app/api/v1/evaluations.py:895` |
| `GET /api/v1/evaluations/profiles/{profile_id}` | 단건 조회를 위해 특정 ID에 의존하며, ID가 존재하지 않으면 404를 반환하므로 범용 하니스 경로로 부적합 (목록 경로로 대체). | `src/app/api/v1/evaluations.py:821` |
| `POST /api/v1/evaluations/snapshots` | 분석 스냅샷을 DB에 직접 INSERT 및 `db.commit()` 수행. | `src/app/api/v1/evaluations.py:950` |
| `GET /api/v1/evaluations/snapshots/{snapshot_id}` | 특정 스냅샷 ID에 의존하며 미존재 시 404를 반환하므로 범용 하니스 경로로 부적합 (목록 경로로 대체). | `src/app/api/v1/evaluations.py:1016` |
| `DELETE /api/v1/evaluations/snapshots/{snapshot_id}` | 스냅샷을 DB에서 DELETE 및 `db.commit()` 수행. | `src/app/api/v1/evaluations.py:1052` |
| `POST /api/v1/automation/run/*` | 수집/KB갱신/예측검증/재학습 등 백그라운드 아르크(Arq) 작업 생성 및 DB 쓰기 발생. | `src/app/api/v1/automation.py:104-147` |
| `POST /api/v1/automation/job/{job_id}/confirm` | 확인 토큰 소비 및 작업 확정 처리 DB 쓰기 발생. | `src/app/api/v1/automation.py:150` |
| `GET /api/v1/automation/job/{job_id}/status` | `sync_automation_status` 호출로 DB 상태 동기화 쓰기가 발생할 수 있으며 동적 ID에 의존함. | `src/app/api/v1/automation.py:173` |
| `POST /api/v1/automation/job/{job_id}/cancel` | 작업 취소 상태 갱신 DB 쓰기 발생. | `src/app/api/v1/automation.py:201` |
| `POST /api/v1/automation/job/{job_id}/callback` | 워커 콜백 데이터 반영 DB 쓰기 발생. | `src/app/api/v1/automation.py:211` |
| `POST /api/v1/accounts/signup` | 신규 사용자 등록 DB 쓰기 발생. | `src/app/api/v1/accounts.py:198` |
| `POST /api/v1/accounts/logout` | Redis 세션 저장소에서 세션을 파기하여 이후 요청의 인증을 무효화하는 부작용 발생. | `src/app/api/v1/accounts.py:250` |

---

## 5. 하니스 실행 순서 및 명령어

측정 스크립트는 `scripts/benchmark_auth_paths.py` 를 통해 실행합니다.

### 5.1 1단계: 드라이런(Dry-run) 검증

실제 서버에 요청을 전송하지 않고, 대상 엔드포인트 목록과 제외 사유, 워밍업 및 측정 회차, 동시성 설정을 검증합니다.

```bash
uv run python scripts/benchmark_auth_paths.py --dry-run
```

### 5.2 2단계: 자격 증명 설정

셸 환경변수에 측정 계정 정보를 주입합니다. (스크립트 명령줄 인자 `--username`, `--password`로 직접 전달할 수도 있습니다.)

```bash
export BENCHMARK_USERNAME="<USERNAME>"
export BENCHMARK_PASSWORD="<PASSWORD>"
```

### 5.3 3단계: 단일 웜(Warm) 측정

사전 워밍업 3회 후 30회 연속 요청을 순차적으로 전송하여 단일 요청 환경의 P50, P95, 최대 레이턴시를 측정합니다.

```bash
uv run python scripts/benchmark_auth_paths.py --mode warm --base-url http://127.0.0.1:8000
```

### 5.4 4단계: 동시성(c10) 측정

동시성 10개 작업자(ThreadPoolExecutor)를 통해 총 100회 요청을 병렬로 던져 동시 부하 상황에서의 P50, P95, 최대 레이턴시를 측정합니다.

```bash
uv run python scripts/benchmark_auth_paths.py --mode concurrency --concurrency 10 --concurrency-rounds 100 --base-url http://127.0.0.1:8000
```

### 5.5 5단계: 통합 측정 및 결과 JSON 저장

단일 웜과 동시성 측정을 연이어 수행하고, 그 결과를 JSON 아티팩트로 저장합니다.

```bash
uv run python scripts/benchmark_auth_paths.py --mode all --base-url http://127.0.0.1:8000 --output docs/analysis/auth_path_concurrency_20260919.json
```

---

## 6. 운영 주의 사항

1. **측정 실행 주체**: 본 측정은 컨테이너 부하 및 백그라운드 태스크가 없는 조용한 상태에서 코디네이터가 수행합니다. 빌더 워커는 실제 측정을 실행하지 않습니다.
2. **컨테이너 불변**: 측정 전후로 도커 컨테이너를 재시작하거나 중단하지 않습니다.
3. **결과 비교 기준**: 2026-09-18 회차(`docs/analysis/read_path_concurrency_20260918.md`)의 비인증 경로(낙찰 목록 c10 P95 79.16ms, 홈 컨텍스트 78.16ms, 공고 목록 61.78ms)와 동일한 머신 환경에서 측정하여 인증 세션 검증 오버헤드(`get_current_user` 의 Redis 세션 조회 및 MySQL 사용자 조회 비용)를 비교 분석합니다.
