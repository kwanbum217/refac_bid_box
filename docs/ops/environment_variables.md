# 환경변수 명세

> **작성일**: 2026-07-31
> **갱신일**: 2026-08-11
> **상태**: 운영 계약
> **관련**: [`.env.example`](../../.env.example)

---

## 1. 목적

refac_bid_box에서 사용하는 모든 환경변수의 **단일 명세**입니다. 실제 값은 `.env`에만 저장하며, 본 문서에는 키명과 용도만 기록합니다.

---

## 2. 환경변수 매트릭스

### 2.1 Application

| 변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `ENVIRONMENT` | 아니오 | `development` | 실행 환경 (`development` / `staging` / `production`) |
| `SECRET_KEY` | **예** | - | 32자 이상의 애플리케이션 시크릿 키 (랜덤값) |
| `DEBUG` | 아니오 | `false` | 디버그 모드 (운영은 `false` 강제) |

현재 FastAPI 설정 모델이 읽는 애플리케이션 키는 위 세 가지입니다. `APP_ENV`,
`APP_SECRET_KEY`, `APP_DEBUG`, `APP_ALLOWED_HOSTS`는 이전 Django 설계의 명칭이므로
이 프로젝트의 `.env`에 사용하지 않습니다. 허용 호스트 목록은 현재 설정 모델에
구현되어 있지 않아 별도 환경변수로 추가하지 않습니다.

`ENVIRONMENT`는 표의 세 값만 허용합니다. 오타나 임의 값은 개발 환경으로 강등하지
않고 시동을 거부합니다. `SECRET_KEY`가 없거나 32자보다 짧아도 애플리케이션은
시작하지 않습니다. 또한 `ENVIRONMENT=production`에서는 예제 시크릿,
`DEBUG=true`, 기본 DB 비밀번호를 거부합니다. Docker Compose도 `.env`에
`SECRET_KEY`가 없으면 구성 단계에서 실패하도록 동일한 계약을 사용합니다.

### 2.2 Database

| 변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `DATABASE_URL` | 아니오 | `mysql+pymysql://root:rootpassword@localhost:3306/procurement` | 애플리케이션이 실제 연결에 사용하는 SQLAlchemy URL |
| `DB_HOST` | 아니오 | `localhost` | DB 호스트 보조 설정 |
| `DB_PORT` | 아니오 | `3306` | DB 포트 (기존 3307에서 표준 3306으로 표준화) |
| `DB_NAME` | 아니오 | `procurement` | DB 이름 (기존 유지) |
| `DB_USER` | 아니오 | `root` | DB 사용자 보조 설정 |
| `DB_PASSWORD` | 아니오 | `rootpassword` | DB 비밀번호 보조 설정과 운영 보안 검증 입력 |
| `MYSQL_ROOT_PASSWORD` | 아니오 | `rootpassword` | Docker Compose 개발용 MySQL root 비밀번호 (운영에서는 교체 필수) |

> 이중화 제거: 기존 `BIDBOX_DB_BACKEND=sqlite` fallback을 폐지하고 모든 환경에서 MySQL 통일.

현재 애플리케이션 연결의 정본은 `DATABASE_URL`입니다. Docker Compose는
`MYSQL_ROOT_PASSWORD`로 `DATABASE_URL`을 구성하고 같은 값을 `DB_PASSWORD`에도
전달하므로 Compose에서는 `MYSQL_ROOT_PASSWORD`만 실제 운영값으로 교체하면 두
설정이 함께 바뀝니다. Compose 밖에서 직접 배포할 때는 `DATABASE_URL`과
`DB_PASSWORD`를 일치시켜야 하며, 둘 중 하나라도 기본 비밀번호가 남으면
애플리케이션이 시동을 거부합니다.

### 2.3 LLM (로컬 Ollama / Google Gemini)

| 변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `LLM_PROVIDER` | 아니오 | `ollama` | 생성 LLM 백엔드. `gemini` 로 원본 경로 복원 |
| `OLLAMA_MODEL` | 아니오 | `gemma4:e4b` | 로컬 생성 모델 |
| `OLLAMA_KEEP_ALIVE` | 아니오 | `-1` | 모델을 메모리에 붙잡아 두는 시간. `-1` 무기한, `30m` 30분 |
| `LLM_WARMUP_ON_STARTUP` | 아니오 | `true` | 기동 시 모델을 미리 올립니다 |
| `LLM_THINKING` | 아니오 | `false` | 사고(thinking) 단계 사용 여부 |
| `GEMINI_API_KEY` | 아니오 | - | Gemini API 키. `LLM_PROVIDER=gemini` 일 때만 필요 |

뒤의 세 변수는 **첫 토큰 지연을 직접 좌우합니다.** 2026-08-05 실측입니다.

| 조건 | 첫 토큰 |
| --- | ---: |
| 사고 켜짐 (모델 기본값) | 9.73초 |
| 사고 끔 (`LLM_THINKING=false`) | **0.41초** |
| 모델이 내려가 있을 때 추가 비용 | +11.78초 |

`gemma4` 는 사고를 끝낸 뒤에야 답변 본문을 내보내므로, 사고를 켜면 그동안 화면에 아무것도 뜨지 않습니다. 품질이 중요한 용도라면 켜되 첫 토큰이 10초 가까이 걸린다는 점을 감수해야 합니다. 상세는 [`docs/design/sse_first_token_20260805.md`](../design/sse_first_token_20260805.md).

### 2.4 G2B / 공공데이터 API

| 변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `G2B_SERVICE_KEY` | **예** | - | 나라장터 공공데이터 serviceKey. 기존 `serviceKey`도 하위 호환으로 읽습니다 |

### 2.5 Vector DB / RAG

| 변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `CHROMA_DB_PATH` | 아니오 | `chroma_db` | ChromaDB 저장 경로 |

### 2.6 Cache / Broker

| 변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `REDIS_URL` | **예** | `redis://localhost:6379/0` | Redis 연결 (캐시 + 브로커) |

### 2.7 Social Login

| 변수 | 필수 | 설명 |
| --- | --- | --- |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | 아니오 | Google OAuth |
| `KAKAO_CLIENT_ID` / `KAKAO_CLIENT_SECRET` | 아니오 | Kakao OAuth |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | 아니오 | Naver OAuth |

### 2.8 Search / Meilisearch

| 변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `MEILI_ENABLED` | 아니오 | `false` | 공고·낙찰 목록 조회를 Meilisearch 읽기 모델로 전환합니다 |
| `MEILI_URL` | 전환 시 예 | `http://localhost:7700` | Meilisearch API 주소. Compose 내부에서는 `http://meilisearch:7700`입니다 |
| `MEILI_MASTER_KEY` | 전환 시 예 | - | Meilisearch 관리자 키. `.env`와 배포 시크릿에만 저장합니다 |

Meilisearch는 원본 MySQL 테이블의 검색 인덱스를 바꾸지 않습니다. 초기 전체 색인은
`uv run python scripts/sync_search_index.py`, 일일 증분 반영은 수집 직후 Arq의
`search` 단계가 수행합니다. 활성화 후에는 빈 검색어 목록도 Meilisearch가 담당하며,
검색 엔진 장애 시 API와 SSR 목록은 빈 결과나 느린 `LIKE` 폴백 대신 HTTP 503을 반환합니다.

### 2.9 MLOps / Automation (Arq)

원본의 Harness 관련 변수(`HARNESS_ACCOUNT_ID`, `HARNESS_API_KEY`, `HARNESS_PIPELINE_ID`)는 실행 백엔드를 Arq 로 교체하면서 사용하지 않습니다.

| 변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `AUTOMATION_WORKER_SHARES_DB` | 아니오 | `true` | 워커가 앱과 같은 DB 를 보는지 여부. 기본 docker-compose 구성은 공유합니다 |
| `AUTOMATION_CALLBACK_BASE_URL` | 아니오 | (없음) | 워커를 별도 배포해 DB 를 공유하지 않을 때 결과를 되돌려 보낼 API 주소 |
| `AUTOMATION_REUSE_RECENT` | 아니오 | `true` | 고비용 작업(`full_validation`)의 최근 72시간 성공 이력 재사용 |
| `AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED` | 아니오 | `false` | 매일 02:00 KST 개발 DB 수집·최근 24시간 KB 델타 upsert·집계 최신화. 예측 검증·재학습은 제외 |
| `AUTOMATION_NIGHTLY_SCHEDULE_ENABLED` | 아니오 | `true` | 매일 02:00 야간 번들 크론 사용 여부 |

`AUTOMATION_CALLBACK_BASE_URL` 은 **워커가 도달할 수 있는 주소**여야 합니다. 컨테이너를 분리했다면 `http://app:8000` 처럼 서비스명을 쓰십시오. `http://localhost:8000` 은 워커 컨테이너 자기 자신을 가리키므로 거부됩니다.

결과 수신 경로는 다음과 같이 결정됩니다.

| `AUTOMATION_CALLBACK_BASE_URL` | `AUTOMATION_WORKER_SHARES_DB` | 모드 | 동작 |
| --- | --- | --- | --- |
| 없음 | `true` | `direct` | 워커가 DB 에 직접 기록 (기본 구성) |
| 없음 | `false` | `polling` | 되돌릴 경로 없음, 화면이 상태를 조회 |
| 정상 주소 | 무관 | `callback` | 워커가 HTTP 로 보고 |
| 루프백/형식 오류 | `true` | `direct` | 안내 문구와 함께 DB 기록으로 강등 |
| 루프백/형식 오류 | `false` | `polling` | 안내 문구와 함께 폴링으로 강등 |

### 2.10 ML / Retraining

| 변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `MODEL_REGISTRY_PATH` | 아니오 | `ml_registry` | 모델 레지스트리 경로 |
| `MODEL_FILES_DIR` | 아니오 | `data/model_files` | 서빙 가중치 위치. 경로 정본이며 `model_registry.py`, `promotion.py`, `verify_migration.py` 가 함께 따릅니다 |
| `MODEL_BACKUPS_DIR` | 아니오 | `data/model_backups` | 승격 시 직전 서빙본 보관 위치. G1 원본 기준선 대조에 쓰이므로 서빙 경로와 함께 옮겨야 합니다 |
| `MODEL_METRICS_DIR` | 아니오 | `data/model_metrics` | 서빙 모델 실측 지표 사이드카. 승격 게이트가 champion 지표를 읽습니다 |
| `ML_WEEKLY_RETRAIN_ENABLED` | 아니오 | `true` | 매주 월요일 03:00 재학습 크론 사용 여부 |
| `DRIFT_PSI_THRESHOLD` | 아니오 | `0.2` | 데이터 드리프트 PSI 임계값 |
| `MLOPS_WEBHOOK_URL` | 아니오 | (없음) | 재학습 실패·승격 권고를 보낼 **Slack Incoming Webhook** 주소. 비면 알림을 보내지 않습니다 |

기본 Docker Compose worker는 개발 DB 최신화를 위해
`AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED=true`로 둡니다. 이 작업은
`collect → rag → inspect`와 순위·기관 집계만 수행합니다. `rag`는 최근 24시간 수집분과
새 낙찰 결과에 연결되는 공고만 upsert하므로 50만 건 KB 전체를 워커 메모리에 올리지
않습니다. 예측 검증이 포함된 운영
야간 번들과 주간 재학습은 `false`로 유지합니다. 두 야간 스케줄을 함께 켜면 개발
최신화 작업이 건너뛰어 중복 수집을 막습니다.

발신 페이로드는 `{"text": ...}` 로 고정돼 있어 **Slack 전용**입니다. Discord 로 바꾸려면 `{"content": ...}` 를 요구하므로 `src/tasks/notifier.py:60` 수정이 함께 필요합니다. 발신 실패는 예외를 삼키고 로그만 남기므로 형식이 틀려도 조용히 실패합니다.

`MLOPS_WEBHOOK_URL` 이 비어 있으면 알림 발신이 통째로 생략됩니다. 개발 장비의 기본 동작이며, `ML_WEEKLY_RETRAIN_ENABLED` 와 같은 규약입니다. 알림 발신 실패는 재학습을 되돌리지 않고 로그만 남깁니다. 무엇을 보내고 무엇을 보내지 않는지는 [`docs/design/mlops_notification_20260805.md`](../design/mlops_notification_20260805.md) 4장을 참조하십시오.

가중치 3종 경로는 **함께 움직여야 합니다.** 서빙 경로만 옮기고 백업을 두고 오면, 승격된 모델의 원본 기준선을 대조할 곳이 없어 `verify_migration.py` 가 체크섬 불일치로 실패합니다(G1). 옮길 때는 `scripts/sync_model_files.py` 로 세 경로를 한 번에 내보내고 들여오십시오.

재학습 시각 자체는 환경 변수가 아니라 `src/tasks/worker.py` 의 `cron_jobs` 에 고정되어 있습니다. 원본 Airflow DAG 의 `schedule_interval='0 3 * * 1'` 을 그대로 옮긴 값이므로, 바꿀 때는 원본과의 차이를 인지하고 변경하십시오.

---

## 3. 로드 패턴

- `.env` 파일은 `.gitignore`로 제외됩니다.
- 개발 환경: Pydantic Settings가 `.env` 파일을 UTF-8로 로드합니다.
- 운영 환경: 환경변수 주입 (Docker Compose `environment` 또는 오케스트레이터 시크릿).
- 누락된 필수 변수는 애플리케이션 시작 시 검증하고 명확한 에러를 발생시킵니다.

---

## 4. 보안 주의사항

- 어떤 환경변수의 **실제 값도 문서에 기록하지 않습니다.**
- 시크릿 순환 정책을 운영 환경에 적용합니다.
- 상세는 [`security/README.md`](../security/README.md) 참조.
