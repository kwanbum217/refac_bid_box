# 세션 TODO (2026-08-01 기준)

> **작성일**: 2026-08-01
> **최종 갱신**: 2026-08-01 (세션 종료 시점)
> **상태**: Phase 0~6 완료, Phase 7 검증 잔존
> **기준 커밋**: `9a1a7c0` (main, origin 까지 push 완료)
> **테스트**: 196 passed / 1 skipped, `python scripts/validate_agent_rules.py` 6/6 PASS

---

## 재개 방법

작업 트리는 clean 이고 브랜치는 `main` 단독입니다. 미커밋 작업물이나 띄워둔 서버는 없습니다.

```bash
cd ~/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box
git pull

# 서버가 필요한 작업일 때만
redis-server --port 6379 --daemonize yes
.venv/bin/python -m uvicorn src.app.main:app --host 127.0.0.1 --port 8000
# 워커까지 필요하면
.venv/bin/arq src.tasks.worker.WorkerSettings
```

화면은 `http://127.0.0.1:8000/` 입니다. Ollama 는 담당자 앱(`Ollama.app`)이 상시 구동하므로 별도 기동이 필요 없습니다.

Redis 스냅파일(`dump.rdb`)은 `.gitignore` 처리가 끝나 더 이상 커밋에 잡히지 않습니다.

---

## 다음에 할 일

### 즉시 진행 가능 (서버 없이)

1. ~~**ChatAutomationApiTests 이식**~~ — **완료**. 상세는 아래 "ChatAutomationApiTests 이식 결과" 참조.
2. ~~**정기 실행 스케줄 추가**~~ — **완료**. 아래 "정기 실행 스케줄 이식" 참조
3. ~~**Alembic 마이그레이션 도입**~~ — **완료**. 아래 "Alembic 도입 결과" 참조
8. ~~**모델-스키마 차이 정리**~~ — **완료**. 아래 "모델 선언 정정 결과" 참조
7. ~~**`dump.rdb` Git 추적 해제**~~ — **완료**. `git rm --cached` 후 `.gitignore` 에 `*.rdb`/`appendonly.aof` 등록

### 서버 필요 (Ollama + Redis)

4. ~~**성능 벤치마크**~~ — **측정 완료**. 목표 2건 미달, 원인 규명. [`docs/ops/latency_benchmark.md`](../ops/latency_benchmark.md)
9. **레이턴시 개선** — SQL 사전 집계 **완료** (전체 P95 목표 달성). SSE 진짜 스트리밍은 잔존. 아래 참조
5. ~~**재학습 E2E 검증**~~ — **완료**. 결함 6건 발견·수정. [`docs/ops/retrain_pipeline_e2e.md`](../ops/retrain_pipeline_e2e.md)
10. **재학습 모델 설계** — `inst_hist_rate` 실제 기관 이력 계산 완료. 잔여: 승격 임계값, 특징 확장, K-Fold/LightGBM/CatBoost, 시계열 분할
6. **크로스 플랫폼 검증** — Windows 환경에서 Docker + Makefile 실행 확인

### 실기동 확인 (2026-08-02 완료)

Redis + MySQL + uvicorn + Arq 워커 + Ollama 를 모두 띄우고 실제 HTTP 로 확인했습니다. 상세는 아래 "실기동 확인 결과" 참조.

---

## 최근 세션 작업 요약 (2026-08-01)

| 커밋 | 내용 |
| --- | --- |
| `b6486ca` | 자동화 통합 테스트를 챗봇 경로 기준으로 재작성, `new_chat_session` URL 오타 수정 |
| `eabb9c1` | 원본 ChatAutomationApiTests 23개 이식, 누락 기능 5건 복원 |
| `8012ef1` | Arq 작업 중지(abort) 연결, 최근 실행 재사용 구현, 테스트 3개 추가 이식 |
| `9a1a7c0` | 콜백 도달성 판정을 Arq 기준으로 설계·구현 |

원본 재현율: ChatAutomationApiTests **26/28 이식** (제외 2건은 Arq 로 바꾼 이상 개념이 성립하지 않음).

---

## ChatAutomationApiTests 이식 결과

원본 클래스는 **28개**입니다 (`apps/chatbot/tests.py:784-1798`). **26개 이식 완료**, 2개는 Arq 로 바꾼 이상 대응 개념이 성립하지 않아 제외했습니다.

| 이식본 파일 | 테스트 수 | 범위 |
| --- | ---: | --- |
| `tests/test_chatbot_integration.py` | 15 | 세션 전환, 자동화 요청, 텍스트 승인, 진행 상황, 챗봇 화면 |
| `tests/test_chatbot_prediction.py` | 6 | 투찰가 예측, 답변 모드 계약, 대화 상태 영속 |
| `tests/test_automation_status_api.py` | 12 | 콜백 인증, 상태 조회, 실행 중지, 최근 실행 재사용, 확인 실행 |

제외한 2개와 사유입니다.

| 원본 테스트 | 제외 사유 |
| --- | --- |
| `test_chat_api_falls_back_to_polling_for_loopback_callback_base_url` | 전제가 반전됩니다. 원본은 외부 SaaS 인 Harness 가 사설망으로 들어올 수 없어 loopback/private 주소를 거부했습니다. Arq 워커는 같은 Docker 네트워크 안에 있어 사설 주소가 오히려 정상 설정이므로, 규칙을 그대로 옮기면 정상 배포에서 콜백이 영구히 꺼집니다. 판정 자체는 Arq 기준으로 새로 설계해 구현했습니다 (아래 참조) |
| `test_confirm_reuses_recent_harness_summary_without_new_run` | 원격 Harness API 이력을 끌어와 로컬에 적재하는 흐름입니다. Arq 는 외부 실행 레지스트리가 없고 `pipeline_executions` 가 이미 유일한 진실 원천이라 로컬 재사용 테스트와 같은 것이 됩니다 |

### 이식 과정에서 복원한 누락 기능

테스트가 통과하지 않아 드러난 실제 이식 누락분입니다. 테스트를 고치지 않고 구현을 채웠습니다.

| 대상 | 누락 내용 |
| --- | --- |
| `src/app/api/v1/chatbot.py` | 텍스트 승인("승인 후 실행해줘")과 `confirmation_token` 처리 자체가 없었습니다 |
| `src/app/api/v1/chatbot.py` | 답변 모드가 `suggestions`/`advisory_signals` 를 전혀 싣지 않았습니다 |
| `src/app/schemas/chatbot.py` | 세션 전환 응답에 `last_query`/`history` 가 없어 `chat.html:1734` 의 대화 복원이 동작하지 않았습니다 |
| `src/app/services/conversation_state.py` | 사용자 고정 메모리(`user:{id}`)가 통째로 빠져 세션 간 필터가 이어지지 않았습니다 |
| `src/app/services/automation_orchestrator.py` | `_step_status_lines` 가 "Step 진행 상황" 머리글, 단계 순서, 요약 표기를 누락했습니다 |
| `src/app/services/automation_orchestrator.py` | 실행 중지가 DB 레코드만 바꾸고 워커 작업은 방치했습니다. Arq 작업 ID 를 남기지 않아 붙잡을 핸들조차 없었습니다 |
| `src/app/services/automation_orchestrator.py` | 고비용 작업의 최근 성공 실행 재사용이 없어 승인할 때마다 무조건 새로 실행했습니다 |

### 실행 중지 (Arq abort) 구현 메모

`abort_arq_job` 은 arq 의 `Job.abort()` 를 쓰지 않습니다. `Job.abort()` 는 중단 신호를 넣은 뒤 워커의 확인 결과까지 기다리므로, 중지 버튼이 워커 응답만큼(기본 무한, 지정 시 timeout 만큼) 멈춥니다. 신호 전달까지만 수행해 응답을 즉시 돌려주고, `worker_abort_requested` 플래그도 "실제 중단됨"이 아니라 "중단 신호를 전달함"을 뜻합니다.

워커 쪽 `allow_abort_jobs = True`(`src/tasks/worker.py`)가 켜져 있어야 동작합니다. 실제 워커를 띄워 10초 태스크를 중간에 죽이는 것까지 확인했습니다.

### 재사용 정책

`full_validation` 만 대상이며(`REUSABLE_ACTIONS`), 신선도 창은 72시간(`REUSE_MAX_AGE_HOURS`)입니다. `AUTOMATION_REUSE_RECENT=false` 로 끌 수 있습니다.

### 작성 규칙

자동화 관련 테스트는 반드시 `/api/v1/chatbot/chat` 을 거쳐 작성합니다. 자동화 엔드포인트를 직접 호출하면 원본이 검증하려던 계획 수립 경로를 건너뛰고 `tests/test_automation_api.py` 와 중복됩니다.

---

## 콜백 도달성 판정 (Arq 기준 신규 설계)

`_callback_metadata` 가 읽던 `callback_mode`/`callback_configured` 를 아무도 채우지 않아 모든 작업이 기본값 `polling` 으로 보고되던 문제를 해결했습니다. 검증은 `tests/test_callback_delivery.py` (21건).

### 원본과 무엇이 다른가

원본의 질문은 "외부 SaaS 가 우리 망으로 들어올 수 있는가" 였고, 그래서 사설 대역 전체를 거부했습니다. Arq 의 질문은 "워커의 단계별 보고가 요청 레코드까지 돌아올 수 있는가" 이고, 워커는 이미 같은 네트워크 안에 있습니다. 따라서 판정 축이 바뀝니다.

| 축 | 원본 (Harness) | 이식본 (Arq) |
| --- | --- | --- |
| 호출자 위치 | 외부 클라우드 | 같은 네트워크 |
| 사설 주소 | 거부 | **허용** (`http://app:8000` 이 정상) |
| 루프백 | 거부 | 거부 (사유가 다름: 워커 자기 자신을 가리킴) |
| 경로 종류 | callback / polling | **direct** / callback / polling |

`direct` 는 원본에 없던 모드입니다. 번들 워커는 앱과 같은 DB 를 보므로 HTTP 를 거치지 않고 `apply_callback_payload` 로 바로 기록합니다. 이게 기본 구성이자 가장 확실한 경로인데, 기존 코드는 이 경우를 `polling` 이라 잘못 안내하고 있었습니다.

### 판정 규칙

`resolve_callback_delivery(job_id)` (`automation_orchestrator.py`)

| `AUTOMATION_CALLBACK_BASE_URL` | `AUTOMATION_WORKER_SHARES_DB` | 모드 |
| --- | --- | --- |
| 없음 | `true` | `direct` |
| 없음 | `false` | `polling` |
| 정상 주소 | 무관 | `callback` |
| 루프백 / 형식 오류 | `true` | `direct` (안내 문구 첨부) |
| 루프백 / 형식 오류 | `false` | `polling` (안내 문구 첨부) |

판정 결과는 요청 생성 시점에 `AutomationRequest.payload` 에 기록되어 `job` 응답 계약과 답변 문구에 그대로 실립니다.

### 워커 보고 경로

`_report`(`src/tasks/automation_tasks.py`)는 `callback_url` 이 있으면 HTTP 로 보내고, 없거나 전송이 실패하면 같은 페이로드를 DB 에 기록합니다. 전송 실패로 단계 보고가 유실되지 않습니다. 실제 uvicorn 을 띄워 워커 → API → 요청 레코드 왕복까지 확인했습니다.

`callback_url`/`callback_token` 은 `callback` 모드일 때만 워커에 전달합니다. `direct` 모드에서는 빈 값을 넘겨 불필요한 HTTP 왕복과 토큰 노출을 만들지 않습니다.
---

## 정기 실행 스케줄 이식 (2026-08-02)

원본은 스케줄이 **두 군데로 나뉘어** 있었습니다. 야간 번들은 Harness 트리거, 주간 재학습은 Airflow DAG 였습니다. 이식본은 둘 다 Arq 크론(`src/tasks/worker.py` `cron_jobs`)으로 모았습니다. 검증은 `tests/test_scheduled_tasks.py` (10건).

| 원본 | 정의 위치 | 주기 | 이식 태스크 |
| --- | --- | --- | --- |
| `BIDBOX_Personal_Nightly_Schedule` | `harness/bidbox_personal_triggers.yaml` (`0 2 * * *`) | 매일 02:00 | `nightly_schedule_task` |
| `narabid_weekly_retrain` | `apps/pipelines/dags/retrain_dag.py` (`0 3 * * 1`) | 매주 월요일 03:00 | `weekly_retrain_task` |

시각은 원본과 동일하게 유지했고, 테스트는 값 비교가 아니라 `next_cron` 으로 다음 실행 시각을 계산해 검증합니다.

### 설계 메모

- 야간 실행은 `run_mode="nightly_schedule"` 로 원본 스텝 구성(`collect, rag, predict, inspect`)을 그대로 씁니다.
- 실행 이력은 챗봇 실행과 같은 `pipeline_executions` 에 남기되 `source="local_scheduler"` 로 구분합니다. 원본 `run_local_automation_bundle` 의 기본 라벨과 같은 값입니다.
- 큐를 한 번 더 거치지 않고 크론 작업 안에서 파이프라인을 직접 실행합니다. 워커 안에서 다시 Redis 로 넣을 이유가 없습니다.
- 두 크론 모두 `timeout=10800` 입니다. 기본 `job_timeout` 30분으로는 전체 번들이 끝나지 않습니다.
- `run_at_startup=False` 입니다. 워커를 재기동할 때마다 수집이 도는 사고를 막습니다.
- `weekly_retrain_task` 는 예외를 삼키고 실패 결과를 반환합니다. 크론 안에서 예외가 새면 이후 스케줄까지 함께 멈춥니다.
- 개발 장비용 차단 스위치: `AUTOMATION_NIGHTLY_SCHEDULE_ENABLED`, `ML_WEEKLY_RETRAIN_ENABLED`.

### 확인한 것과 남은 것

워커를 실제로 띄워 `cron:nightly_schedule_task`, `cron:weekly_retrain_task` 가 등록되는 것까지 확인했습니다. 스케줄이 실제 시각에 발화해 번들을 끝까지 도는 것은 아직 관측하지 못했습니다.

---

## Alembic 도입 결과 (2026-08-02)

기준선 리비전 `migrations/versions/0001_django_baseline.py` 를 만들고 운영 DB 에 `stamp` 까지 완료했습니다. 검증은 `tests/test_alembic_setup.py` (34건).

핵심 설계 판단은 **기준선을 모델이 아니라 운영 DB 반영(reflect)으로 만들었다**는 점입니다. 모델에서 뽑으면 "19개 마이그레이션을 적용한 상태"와 다른 것을 기준선이라 부르게 되고, `stamp` 가 거짓말이 됩니다.

| 항목 | 내용 |
| --- | --- |
| 기준선 리비전 | `0001_django_baseline` (down_revision 없음) |
| 생성 방식 | 운영 DB 11개 테이블 reflect |
| 검증 | 빈 스키마에 적용 후 운영 DB 와 비교 → 차이 0건 |
| 운영 DB 적용 | `stamp` 만 실행 (DDL 미실행), 27→28 테이블, 데이터 변동 없음 |
| 신규 환경 | `make migrate-up` |
| 기존 환경 | `make migrate-stamp` |
| 드리프트 점검 | `make migrate-check` (읽기 전용) |

`migrations/env.py` 의 `include_object`/`include_name` 이 모델에 있는 11개 테이블만 추적합니다. 이 필터가 없으면 `autogenerate` 가 운영 DB 에 남은 Django 인프라 테이블 16개(`django_migrations`, `auth_*`, `socialaccount_*`, `account_*`)를 전부 DROP 대상으로 잡습니다. G1 직결 사안이라 테스트로 고정했습니다.

원본 19개 마이그레이션의 목록과 내용은 `docs/migration/django_migration_history.md` 에 기록했습니다. `bids` 0006~0008 이 기초금액 산출 기준을 세 번 뒤집는 관계라 리비전으로 재현하지 않고 최종 상태만 기준선에 담았습니다.

### 부수적으로 드러난 것: 모델-스키마 차이 (2026-08-02 해소 완료)

`make migrate-check` 결과입니다. 주석 67건과 인덱스 명명 차이 58건은 무해하지만, **33건은 SQLAlchemy 모델이 원본 Django 스키마를 그대로 재현하지 못한 지점**입니다.

| 유형 | 건수 | 내용 |
| --- | ---: | --- |
| `nullable` 완화 | 20 | DB 는 `NOT NULL` 인데 모델은 nullable. 모델이 원본보다 느슨합니다 |
| `LONGTEXT` -> `TEXT` | 10 | 모델이 `Text()` 로 선언. MySQL `TEXT` 는 64KB 라 4GB 인 `LONGTEXT` 보다 좁습니다 |
| `UUID` -> `VARCHAR(36)` | 1 | `automation_requests.request_id` |
| unique 제약 추가 | 2 | `uq_bid_ann_no_ord_cat`, `uq_bid_results_no_ord_cat` (원본은 인덱스로 동일 제약) |

현재는 운영에 영향이 없습니다. 모델을 DB 에 맞추는 것이 아니라 **DB 를 모델에 맞추는 순간** 문제가 됩니다. 특히 `LONGTEXT` -> `TEXT` 는 64KB 를 넘는 기존 값을 잘라냅니다. 절대 `autogenerate` 결과를 그대로 적용하지 마십시오.

해소 결과는 아래 절에 정리했습니다.

---

## 모델 선언 정정 결과 (2026-08-02)

모델 선언만 고쳤습니다. **DB 는 한 번도 건드리지 않았습니다.** 검증은 `tests/test_model_schema_parity.py` (66건).

최종 상태는 `make migrate-check` 기준 **실질 차이 0건, 인덱스 명명 차이 0건**이며, `alembic revision --autogenerate` 는 리비전 파일 자체를 만들지 않습니다.

### 무엇을 고쳤는가

| 대상 | 건수 | 내용 |
| --- | ---: | --- |
| `nullable` 복원 | 20 | DB 가 `NOT NULL` 인 컬럼에 `nullable=False` 명시 |
| `LONGTEXT` | 10 | `LongText = Text().with_variant(mysql.LONGTEXT, ...)` 도입. SQLite 테스트는 그대로 `TEXT` |
| 네이티브 `uuid` | 1 | 일반 `Uuid` 는 MariaDB 에서 `CHAR(32)` 로 컴파일됩니다. `UUID(as_uuid=False)` 로 교체 |
| `int unsigned` | 1 | `knowledge_base_status.source_bid_count` (원본 `PositiveIntegerField`) |
| 누락 FK | 3 | `automation_requests`, `automation_subscriptions`, `chat_session_states` 의 `accounts_customuser` 참조가 통째로 빠져 있었습니다 |
| 누락 인덱스 | 6 | 원본 `Meta.indexes` 가 이름 붙인 복합 인덱스. `ix_auto_req_user_status` 등 |
| 임의 추가 인덱스 제거 | 3 | `prediction_results` 는 원본에 인덱스가 없습니다 |
| 인덱스명 정정 | 15 | `index=True` 가 만든 `ix_<table>_<column>` 을 원본 실제 이름으로 교체 |

인덱스를 "이름만 다름"으로 분류했던 앞선 판단은 틀렸습니다. 실제로는 **원본이 명시 선언한 복합 인덱스 6개가 빠져 있었고**, 그중 `ix_auto_req_user_status` 는 `_find_pending_confirmation_request` 가 매 요청마다 쓰는 `user_id + status` 조회 경로입니다.

### 코드 쪽 영향

`automation_requests.user_id` 가 `NOT NULL` 이므로 `create_automation_request` / `create_action_request` 의 `user_id` 를 필수 인자로 조였습니다. 두 호출부 모두 이미 로그인 사용자 ID 를 넘기고 있어 동작 변화는 없습니다. 익명 요청은 애초에 DB 가 거부합니다.

### 주석 67건을 남긴 이유

원본 Django 는 컬럼 주석을 DB 에 기록하지 않지만, 이식본 모델의 한국어 주석은 문서로서 가치가 있습니다. 주석을 지우는 대신 `migrations/env.py` 의 `process_revision_directives` 훅이 **주석만 다른 변경을 마이그레이션에서 걸러냅니다.** 진짜 스키마 변경(타입 변경, 컬럼 추가/삭제)은 그대로 감지되는 것까지 확인했습니다.

### 검증 방법

빈 스키마에 `Base.metadata.create_all` 로 스키마를 만든 뒤 운영 DB 와 비교해 주석 외 차이 0건을 확인했습니다. 임시 스키마는 검증 후 삭제했습니다.

---

## 실기동 확인 결과 (2026-08-02)

Redis, MariaDB(운영), uvicorn, Arq 워커, Ollama 를 모두 띄우고 실제 HTTP 요청으로 확인했습니다. 세 항목 모두 통과했으며, 확인 과정에서 화면 버그 하나가 드러났습니다.

### 드러난 버그: 자동화 제어 버튼 3개가 전부 404

`chat.html` 의 URL 템플릿이 원본 Django 경로(`/chatbot/api/automation/job/<id>/...`)로 남아 있었습니다. 이식본 라우트는 `/api/v1/automation/job/{job_id}/...` 이므로 다음이 전부 동작하지 않았습니다.

| 기능 | 증상 |
| --- | --- |
| 요청 중지 버튼 | 404 |
| 확인 실행(고비용 승인) 버튼 | 404 |
| 진행 상황 폴링 | 404 |

단위 테스트가 API 를 직접 호출하는 방식이라 아무도 잡지 못했습니다. 세 경로를 `URL_MAP` 에 등록해 다른 항목처럼 `url()` 을 거치도록 고쳤고, `tests/test_template_urls.py` (13건)로 고정했습니다. 이 테스트는 수정 전 코드에서 실제로 실패하는 것을 확인했습니다.

### 확인 1: 요청 중지가 실제 워커 작업을 막는가

화면이 렌더링한 URL 을 그대로 읽어 같은 요청을 보냈습니다.

- 짧은 작업(`predict_only`)은 2초 안에 끝나 중지 대상이 없었고, 이미 끝난 작업의 상태를 바꾸지 않는 것까지 확인했습니다(올바른 동작).
- 워커를 멈춘 상태에서 작업을 넣고 중지한 뒤 워커를 되살렸습니다. 워커 로그에 **`aborted before start`** 가 찍히고 작업을 실행하지 않았습니다. DB 상태는 `canceled` 유지.

중지가 DB 표시만 바꾸는 것이 아니라 Arq abort 신호로 실제 실행을 막는다는 뜻입니다. 실행 중인 작업을 중간에 죽이는 것은 이전 세션에서 10초 태스크로 확인했습니다.

운영 데이터를 건드리지 않으려고 읽기 전용 스텝만 썼습니다. `collect`(G2B 적재)와 `rag`(ChromaDB 재구축)는 돌리지 않았습니다.

### 확인 2: 세션 사이드바 대화 복원

첫 세션에서 2턴 대화 후 새 세션을 만들고, 사이드바 클릭에 해당하는 전환 요청을 보냈습니다.

| 항목 | 결과 |
| --- | --- |
| `mode` | `switch` |
| `history` | 4개 (user/model 2턴) 복원 |
| `last_query` | `"그중 상위 기관은 어디야"` 복원 |
| `answer` | 마지막 답변 전문 복원 |

실제 Ollama 가 응답하고 ChromaDB 검색이 동작하는 상태에서 확인했습니다.

### 확인 3: full_validation 재사용

7/31 11:54 의 `manual_full` 성공 이력이 72시간 창 안에 있어 재사용 조건을 실제로 만족했습니다.

| 항목 | 결과 |
| --- | --- |
| 승인 후 상태 | 즉시 `success` |
| 재사용한 실행 | `manual_full-2a5bdfaffa43` |
| 새 `pipeline_executions` | 0건 |
| Redis 큐 | 비어 있음 |
| `payload.reuse_mode` | `recent_execution` |
| `result_payload.sync_mode` | `reused_recent_execution` |

`reuse_mode` 는 job 응답이 아니라 `AutomationRequest.payload` 에 실립니다. 원본도 같은 위치입니다(`apps/chatbot/tests.py:1418`). 값만 원본의 `recent_staging_execution` / `reused_recent_staging` 에서 `staging` 을 뺀 형태이며, Arq 이식으로 스테이징 환경 구분이 사라졌기 때문입니다. 구조는 원본과 동일합니다.

### 확인에 쓴 계정

`livecheck_*` 형식의 테스트 계정이 운영 DB 에 남아 있습니다. 정리 대상입니다.

---

## 레이턴시 벤치마크 결과 요약 (2026-08-02)

상세는 [`docs/ops/latency_benchmark.md`](../ops/latency_benchmark.md) 입니다.

| 구간 | P50 | P95 | 목표 | 판정 |
| --- | ---: | ---: | ---: | --- |
| SSE 첫 토큰 | 10.35s | 42.83s | 3s | 미달 |
| SSE 전체 응답 | 10.65s | 43.03s | 20s | 미달 |
| 낙찰가 예측 API | 0.7ms | 1.0ms | 100ms | 달성 (100배 여유) |

기존 `scripts/benchmark_latency.py` 는 `TestClient` 로 인프로세스 호출을 재고 있었고 목표치(3초/20초)와 무관한 임계값(100ms/300ms)을 쓰고 있었습니다. 실제 서버에 HTTP 로 붙어 첫 토큰과 전체를 나눠 재도록 다시 썼습니다.

### 미달 원인 1: SSE 가 실제 스트리밍이 아님

`stream_tokens`(`src/rag/engine.py:799`)가 `get_answer` 로 답변을 **전부 받은 뒤** 40자씩 잘라 내보냅니다. LLM 백엔드도 `"stream": False` 입니다. 첫 토큰(10.35s)과 전체(10.65s) 차이가 0.3초뿐인 이유입니다.

### 미달 원인 2: 집계 SQL 이 33초

P95 를 끌어올린 것은 `2025년 물품 낙찰 평균 낙찰률` 류의 질의 하나였습니다. 단계별로 나누면 **SQL 33.00s, LLM 9.59s** 로 LLM 이 아니라 SQL 이 병목입니다.

`retrieve_structured_data` 의 6개 쿼리 중 3개(`GROUP BY bidwinnr_nm / dminstt_nm / bid_ntce_nm`)가 31.4초를 씁니다. `category` 단일 인덱스로 범위만 좁힌 뒤 160~190만 행에 `Using temporary; Using filesort` 를 겁니다. `category` 는 값이 3종뿐이라 거의 걸러지지 않습니다.

### 적용: 상위 N 사전 집계 (2026-08-02 완료)

복합 인덱스 대신 사전 집계를 택했습니다. 원본 테이블의 스키마와 인덱스를 건드리지 않아 재현율이 유지되고, 300만 행 DDL 부담도 없습니다.

| 항목 | 내용 |
| --- | --- |
| 신규 테이블 | `bid_ranking_snapshots` (Alembic 리비전 `23cb59f0e3fe`) |
| 서비스 | `src/app/services/ranking_snapshots.py` |
| 적용 범위 | 필터가 category 뿐인 질의만. 날짜/기관 필터는 실시간 경로 유지 |
| 갱신 | 야간 스케줄 자동, `make rebuild-rankings` 수동 (약 77초) |
| 검증 | `tests/test_ranking_snapshots.py` 19건 |

| 구간 | 개선 전 P95 | 개선 후 P95 | 판정 |
| --- | ---: | ---: | --- |
| SSE 첫 토큰 | 42.83s | 16.02s | 목표 3s 미달 |
| SSE 전체 응답 | 43.03s | **16.56s** | 목표 20s **달성** |
| 느린 질의 SQL 구간 | 33.00s | 1.95s | - |

스냅샷이 없으면 `get_top_rankings` 가 `None` 을 돌려 실시간 집계로 넘어갑니다. 느려질 뿐 답은 항상 나옵니다.

이번 작업으로 Alembic 도입이 실제로 쓰였습니다. 생성된 리비전이 신규 테이블만 담고 기존 11개 테이블은 전혀 건드리지 않는 것을 확인했습니다.

### 잔존: SSE 진짜 스트리밍

첫 토큰 목표(3s)는 여전히 미달입니다. 원인은 SQL 이 아니라 `stream_tokens` 의 가짜 스트리밍입니다. Ollama `/api/chat` 을 `stream: True` 로 호출해야 하며, 답변 후처리(Answer Guard, 카테고리 표기 정규화)가 완성본을 전제로 하므로 교정 처리 설계가 필요합니다.

---

## 인코딩 손상 데이터 (2026-08-02 조사·처리)

상세는 [`docs/migration/encoding_corruption_analysis.md`](../migration/encoding_corruption_analysis.md) 입니다.

`bid_results` 의 **건설(Cnstwk) 카테고리만** 1,244,778행(99.2%)의 문자열이 손상돼 있습니다. 용역(Servc)·물품(Thng)과 `bid_announcements` 전체는 무손상입니다.

### 복구 불가 확정

| 경로 | 결과 |
| --- | --- |
| 원본 프로젝트 DB | 이식본과 **같은 DB**(`127.0.0.1:3307/procurement`). 별도 원본 없음 |
| 로컬 parquet | `bid_results_cnstwk.parquet` 이 이미 손상 |
| 구글 드라이브 백업 | 로컬본과 크기·수정시각 동일. 같은 파일 |
| 바이트 역산 | U+FFFD 로 원본 바이트 소실 |
| `raw_data` | 손상 행 전부 JSON `null` |
| G2B API 재수집 | 유일한 실제 복구 경로. 2008~2025 건설 124만건 재수집 필요 |

### ML 학습 관점

용역(Servc) 예측 모델은 **영향 없습니다**. 889,933행 / 2012-12-18 ~ 2025-04-07(12.3년) / 인코딩 손상 0건으로 10년치 요건을 충족합니다. 유의할 것은 낙찰률 결측 12.4%(110,521건)입니다.

건설 모델은 문자열 특징을 쓸 수 없습니다. 수치 특징은 온전합니다.

### 적용한 처리

복구가 불가능하므로 순위 집계에서 제외하고 그 사실을 답변에 안내합니다. 표본 공고처럼 건너뛸 수 없는 자리는 기존 `CORRUPTED_TEXT_FALLBACKS` 문구로 대체합니다. 대시보드 기관 순위에도 같은 기준을 적용했습니다(업체 순위는 이미 처리돼 있었음). 검증은 `tests/test_ranking_snapshots.py` 25건.

---

## 재학습 E2E 검증 결과 (2026-08-02)

상세는 [`docs/ops/retrain_pipeline_e2e.md`](../ops/retrain_pipeline_e2e.md) 입니다.

**파이프라인은 지금까지 실제 DB 에서 한 번도 동작한 적이 없었습니다.** 첫 단계인 데이터셋 빌더가 존재하지 않는 컬럼(`bid_notice_no` 등)을 참조해 즉시 죽었습니다.

### 발견·수정한 결함 6건

| 위치 | 증상 |
| --- | --- |
| `ml/dataset.py` | 존재하지 않는 컬럼 참조로 AttributeError |
| `ml/dataset.py` | 없는 FK(`announcement_id`)로 조인 |
| `ml/dataset.py` | 데이터가 없으면 더미 1행을 만들어 성공처럼 보임 |
| `tasks/retrain_task.py` | `evaluate_model_performance(y, y)` — 정답을 정답과 비교. 항상 rmse 0 / r2 1 |
| `tasks/retrain_task.py` | 승격 게이트를 아무도 호출하지 않음 |
| `ml/trainer.py` | 초 단위 버전명이라 같은 초 재학습 시 디렉터리 덮어씀 |

부수적으로 `retrain_logs` 가 정의만 있고 미사용이던 것을 연결했고, 테스트가 매 실행마다 운영 `ml_registry/` 에 버전을 쌓던 것(21건 누적)을 임시 디렉터리로 돌렸습니다.

### 조인 실측 — 차수 자리수가 다릅니다

`bid_results` 는 2자리(`00`), `bid_announcements` 는 3자리(`000`) 라 정규화 없이 조인하면 **0건**입니다. 정규화 후 조인율입니다.

| 카테고리 | 조인 성공 / 낙찰 전체 | 비율 |
| --- | ---: | ---: |
| Thng | 857,212 / 858,026 | 99.9% |
| Servc | 46,587 / 889,933 | 5.2% |
| Cnstwk | 65,541 / 1,254,295 | 5.2% |

용역·건설은 공고 수집률이 낮아 조인하면 표본이 급감합니다. `require_announcement=False` 로 낙찰만 쓰면 용역 표본이 41,423 -> 773,045 가 되지만 예정가격을 쓸 수 없습니다.

### 실기동 결과 (용역 773,045건)

```
metrics = {'rmse': 4.5108, 'mape': 3.5131, 'r2': -0.0012}
```

전 주기가 약 30초에 완주합니다. **R² -0.0012 는 평균값 예측보다 못하다는 뜻**입니다. 이전에는 rmse 0 / r2 1 로 가려져 있던 사실입니다.

### 담당자 결정 대기 (TODO 10번)

| 항목 | 현재 상태 |
| --- | --- |
| 승격 임계값 | `r2 >= champion` 이라 **동일 성능도 승격**됩니다. AGENTS.md 의 "압도할 때만" 과 어긋남 |
| 특징 선택 | `features.py` 가 60개 이상 산출하는데 4개만 사용. `inst_hist_rate` 는 상수 0.925 |
| 모델 | Ridge. docstring 이 말하는 K-Fold / LightGBM 미적용 |
| 분할 전략 | 프레임 순서 뒤 20%. 시계열이므로 개찰일 기준 분할 검토 필요 |
| 용역 학습셋 | 표본 19배(773,045) vs 가격 특징. 공고 추가 수집이 근본 해결 |

---

## 참조

- 인수인계: `docs/handoff/2026-07-31_parity_restoration_handoff.md`
- 설계서 체크리스트: `docs/design/REFACTORING_DESIGN.md` Phase 7
- 프론트엔드 결정: `docs/design/FRONTEND_DECISION.md`
- 테스트 현황: 196 passed / 1 skipped (21개 파일)
