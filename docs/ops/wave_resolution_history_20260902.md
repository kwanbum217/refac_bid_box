# 웨이브별 해소 이력 (2026-09-02 까지)

> **작성일**: 2026-09-02
> **성격**: 이력 문서입니다. 현재 운영 상태 정본은 [`../context/CURRENT_STATE.md`](../context/CURRENT_STATE.md) 입니다.
> **분리 사유**: `CURRENT_STATE.md` 가 자체 컨텍스트 예산(8,000자)의 네 배를 넘어, 매 세션 자동 주입되는 정본에서 완료된 웨이브 이력을 이 문서로 옮겼습니다.
> **읽는 시점**: 특정 웨이브에서 무엇을 어떤 커밋으로 닫았는지 근거가 필요할 때만 조회하십시오. 부트스트랩에서는 읽지 않습니다.

본 문서의 링크는 `docs/ops/` 기준 상대 경로로 조정되어 있습니다.

---

## 1.5 보안 P0 해소 (2026-09-02)

2026-09-02 보완점 분석 보고서의 출시 차단 3건을 Orca Run `run_971584ddb4a0` 으로
해소하고 병합했습니다. 익명 세션 키 격차는 후속 Task 로 함께 닫았습니다.

| 항목 | 조치 | 병합 |
| --- | --- | --- |
| 대화 상태 교차 사용자 접근(IDOR) | `_get_state_by_key` 소유자 대조, `user:` 접두사 키 거부, fail-closed | `0438db5` |
| 익명 세션 키 공유 | 익명 요청은 HMAC 서명된 서버 발급 키만 수용. 인증 요청은 레거시 평문 키 복원 유지 | `5a0ffb0` |
| 자동화 RBAC 부재 | run 계열 5개 엔드포인트에 `require_staff_user` 적용 | `b08e58f` |
| 확인 토큰 빈 값 우회 | 토큰 필수화 및 일회성 소비. 콜백 경로는 불변 | `b08e58f` |
| 기각 모델 승격 가능 | `paired_verdict.json` 기계 게이트. `rejected` 는 `force` 로도 차단. staging 원자적 교체 | `98f8291` |

검증은 Level 1 기계 게이트, 빌더와 다른 계열의 Level 2 리뷰어(4건 전부 `pass`),
코디네이터 자체 재현 세 층으로 수행했습니다.

### 1.5.1 P1 Wave A 해소 (2026-09-02)

보고서 P1 중 세 건을 Orca Run `run_971584ddb4a0` Wave A 로 해소했습니다.

| 항목 | 조치 |
| --- | --- |
| 3.4 Session 스레드 간 재사용 | 자동화 파이프라인 예외 경로가 rollback 후 실패를 기록하도록 고쳤습니다. 종전에는 세션이 pending-rollback 이면 실패 기록 자체가 다시 실패했습니다 |
| 3.5 서비스 키 로그 노출 | `mask_credentials` 를 수집 경로와 사용자 노출 실패 요약에 적용했습니다 |
| 3.5 비활성 계정 | `get_current_user` 가 `is_active` 를 확인합니다. `require_current_user` 는 원래부터 확인하고 있었으므로 격차는 선택적 인증 경로에 국한됐습니다 |
| 3.5 로그인 시도 제한 | Redis 기반 IP 및 계정 축 제한. 새 의존성 없음. Redis 장애 시 로그인을 막지 않고 제한만 건너뜁니다 |
| 3.5 본문 크기 상한 | ASGI 미들웨어로 `receive` 만 감싸 SSE 응답 경로에 영향이 없습니다 |
| 3.5 GET 로그아웃 | 라우트를 제거하고 UI 링크를 POST form 으로 바꿨습니다 |
| 3.8 RAG single-flight | 참조 계수 기반 키별 잠금. 마지막 대기자가 빠질 때 항목을 제거해 동적 SQL 리터럴 키가 누적되지 않습니다 |
| 3.8 readiness | warmup 완료와 LLM 상태를 반영하되 기본값에서는 degraded 입니다. 게이트 승격은 `READINESS_REQUIRE_WARMUP` 과 `READINESS_REQUIRE_LLM` 으로 선택합니다 |

### 1.5.2 P1 Wave B 해소 (2026-09-02)

| 항목 | 조치 |
| --- | --- |
| 3.3 재학습 category | `None` 과 빈 문자열을 거부하고 주간 재학습을 등록 카테고리별 독립 실행으로 fan-out 합니다. 한 카테고리 실패가 나머지를 막지 않습니다. 학습 아티팩트는 staging 후 이동이라 부분 아티팩트가 `latest_version` 이 되지 않습니다 |
| 3.1 G1 검증 | 전 테이블 스키마 서명(컬럼, 타입, nullable, 기본키, 외래키, 인덱스)을 기준선과 비교하고 날짜와 HEAD 가 담긴 보고서를 남깁니다. 스크립트는 읽기 전용이며 기존 4단계 통과 조건은 그대로입니다 |
| 3.7 운영 Compose | `docker-compose.prod.yml` 신설. 전용 DB 계정, db 와 redis 와 meilisearch 포트 미노출, Redis `requirepass`, non-root, worker healthcheck, 자원 제한, 로그 회전. 개발용 `docker-compose.yml` 은 변경하지 않았습니다 |
| 3.10 Servc 취약 집단 | 운영 정책안을 문서로 남겼습니다. 구현은 후속 과업이며 기각된 세 접근은 제안하지 않았습니다 |

### 1.5.3 P1 Wave C 해소 (2026-09-02)

| 항목 | 조치 |
| --- | --- |
| 3.2 백업 복구 | `scripts/backup_recovery.py` 와 런북 신설. DB, ChromaDB, 모델 레지스트리를 하나의 복구 단위로 묶고 매니페스트를 남깁니다. dry-run 이 기본값이고 실제 실행은 `--execute`, 복원은 `--confirm` 을 요구하며 비대화형에서는 거부합니다. 복원 검증은 `verify_migration.py` 를 재사용합니다 |
| 3.9 PSI 드리프트 | 학습 성공 시 baseline 분포를 원자적으로 저장하고 크론 job 이 판정을 `retrain_logs` 에 기록하고 알림을 보냅니다. `ML_DRIFT_MONITOR_ENABLED` 기본값 False 로 꺼져 있습니다 |
| 3.10 Servc 서빙 | 결측 공고의 불확실성 경고를 예측 응답과 상세 화면에 싣습니다. 결측 판정은 `features.py` 특징을 그대로 씁니다. 예측 하드 차단은 넣지 않았습니다 |
| 4.2 CI 사각지대 | 커버리지 게이트 하한 80% 도입(실측 85.23%), push 트리거를 전체 브랜치로 확대, `docs/ops/ci_contract.md` 신설 |

### 1.5.4 P2 Wave D 해소 (2026-09-02)

| 항목 | 조치 |
| --- | --- |
| 4.3 공급망 | Python 과 npm 의존성 취약점 스캔, Trivy 컨테이너 스캔, SPDX SBOM 생성과 업로드를 CI 에 추가했습니다. 초기에는 보고 전용이며 게이트 승격 조건은 [`../ops/supply_chain.md`](./supply_chain.md) 에 있습니다. python, node, mysql, redis, meilisearch 다섯 이미지를 digest 로 고정했습니다 |
| 4.4 버전 정본 | `pyproject.toml` 하나가 정본입니다. 앱이 하드코딩 대신 그 값을 읽고, 패키지 미설치 환경에서는 `pyproject.toml` 을 직접 읽습니다. 버전 값 0.1.0 은 바꾸지 않았습니다 |
| 3.10 드리프트 연계 | baseline 과 평가를 `lwlt_rate_missing` 값별로 분리하고 with_lwlt 0.2, missing_lwlt 0.25 차등 임계를 적용합니다. 옛 baseline 과 해당 특징이 없는 모델은 기존 방식으로 동작합니다 |

### 1.5.5 Wave E 해소 (2026-09-02)

| 항목 | 조치 |
| --- | --- |
| 3.2 정기 스케줄 | 백업 태스크를 arq cron 에 등록했습니다. `BACKUP_SCHEDULE_ENABLED` 기본값 False 이며 보존은 개수 기준이고 삭제와 복원 리허설은 명시 지정을 요구합니다 |
| 2.3 served-version | health 라우터에 읽기 전용 조회를 두어 인메모리 버전과 디스크 버전 불일치를 드러냅니다. 자동 리로드는 넣지 않았고 readiness 에도 결합하지 않았습니다 |
| 4.3 관측성 조사 | 선택지 세 가지를 비교한 조사 보고서를 남겼습니다. 스택은 확정하지 않았고 SLO 값도 정하지 않았습니다 |

### 1.5.6 Wave F 해소 (2026-09-02)

| 항목 | 조치 |
| --- | --- |
| 4.2 MySQL 통합 | 콜레이션, 정수 나눗셈, `ONLY_FULL_GROUP_BY`, 날짜 함수, JSON 추출 다섯 영역을 통합 테스트로 검증합니다. 기존 SQLite 테스트는 회귀 안전망으로 남겼습니다 |
| 3.5 CSRF | signup, login, logout 세 SSR 폼에 이중 제출 토큰 검증을 겁니다. 토큰이 없으면 403 으로 fail-closed 입니다. JSON API 와 워커 콜백은 제외했습니다 |
| 3.1 G1 대조 | 이행 시점 이전 구간의 행 수를 따로 세어 기준선과 대조합니다. 경계는 `data/backups/data_assets_checksums.json` 의 `generated_at` 에서 왔습니다 |

> **세션 종료 인수인계 (2026-09-02)**: Wave G 잔여를 `565105f` 까지 병합·푸시한 뒤 세션을 닫았습니다. 다음 코디네이터는 [`../ops/handoff_20260902_wave_g_session_close.md`](./handoff_20260902_wave_g_session_close.md) 를 읽으십시오. 이전 인계는 [`../ops/handoff_20260902_grok_coordinator.md`](./handoff_20260902_grok_coordinator.md) 입니다. Grok 운영 절차는 [`../ops/grok_coordinator_operating_prompt.md`](./grok_coordinator_operating_prompt.md) 입니다. Orca Run 은 `run_971584ddb4a0` 을 계속 씁니다.

### 1.5.7 Wave G 부분 해소 (2026-09-02)

| 항목 | 조치 |
| --- | --- |
| 3.4 MySQL 동시성 | 격리 스키마에서 세션 복구, FOR UPDATE 잠금, 데드락, UNIQUE 실패 복구, 동시 INSERT 를 실제 MySQL 로 검증합니다. CI `mysql-ngram-integration` Job 에 합류했습니다 |
| 3.5 익명 API 쿼터 | 익명 챗봇 세 경로에 Redis IP 쿼터. 인증 사용자는 제외, Redis 장애 시 fail-open, SSE 는 진입 시점에만 검사합니다 |
| 3.7 이미지 강화 | `Dockerfile` 을 builder 와 runtime 으로 나눠 빌드 도구를 런타임에서 빼고 `USER 1000:1000` 으로 비 root 실행합니다. 운영 compose 에서 호스트 소스 마운트를 제거하고 `read_only` 루트에 `noexec` `nosuid` 제한 `/tmp` tmpfs 를 붙였습니다 |
| TLS ingress (잔여 3.7) | 운영 compose 에 Caddy 를 두고 443 만 호스트에 엽니다. 앱 8000 은 내부만. 인증서는 저장소에 두지 않습니다 |
| 3.8 Arq heartbeat | Redis 에 워커 식별자·마지막 생존 시각·큐 적체·스케줄 성공 여부를 기록하고 `/api/v1/health/worker` 로 조회합니다. readiness 와 분리했고 Redis 장애는 미상 처리입니다 |

**코디네이터가 직접 확인했습니다.** 이미지 강화는 `docker build` 통과, 컨테이너 `uid=1000(app)`, `which gcc git` 없음. 동시성 테스트는 실제 MySQL 에서 5 passed / 0 skip. TLS 는 호스트 포트 443 만, 인증서 파일 미추적, dummy 환경변수로 prod compose config 통과. 익명 쿼터 단위 테스트 4 passed.

**Codex 워커의 Capsule 배치 경합을 제거했습니다.** `scripts/orca_codex_launch.py` 를 쓰십시오. `worker-start` 는 워크트리 생성과 워커 기동을 한 번에 하므로 기동 뒤에 Capsule 을 복사하면 워커가 그 사이에 정본을 못 찾습니다. 이 경합으로 워커 네 대가 계약 없이 작업했거나 멈췄습니다. 상세는 [`../ops/agent_worker_launch_reference.md`](./agent_worker_launch_reference.md) 1.6 절입니다.
