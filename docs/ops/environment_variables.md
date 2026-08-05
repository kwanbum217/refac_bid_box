# 환경변수 명세

> **작성일**: 2026-07-31
> **상태**: 설계
> **관련**: [`.env.example`](../../.env.example)

---

## 1. 목적

refac_bid_box에서 사용하는 모든 환경변수의 **단일 명세**입니다. 실제 값은 `.env`에만 저장하며, 본 문서에는 키명과 용도만 기록합니다.

---

## 2. 환경변수 매트릭스

### 2.1 Application

| 변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `APP_ENV` | 아니오 | `development` | 실행 환경 (`development` / `staging` / `production`) |
| `APP_SECRET_KEY` | **예** | - | 애플리케이션 시크릿 키 (랜덤값) |
| `APP_DEBUG` | 아니오 | `true` | 디버그 모드 (운영은 `false` 강제) |
| `APP_ALLOWED_HOSTS` | 아니오 | `localhost,127.0.0.1` | 허용 호스트 |

### 2.2 Database

| 변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `DB_ENGINE` | **예** | `mysql` | DB 엔진 (`mysql`) |
| `DB_HOST` | **예** | `127.0.0.1` | DB 호스트 |
| `DB_PORT` | **예** | `3306` | DB 포트 (기존 3307에서 표준 3306으로 표준화) |
| `DB_NAME` | **예** | `procurement` | DB 이름 (기존 유지) |
| `DB_USER` | **예** | - | DB 사용자 |
| `DB_PASSWORD` | **예** | - | DB 비밀번호 |

> 이중화 제거: 기존 `BIDBOX_DB_BACKEND=sqlite` fallback을 폐지하고 모든 환경에서 MySQL 통일.

### 2.3 LLM (Google Gemini)

| 변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `GEMINI_API_KEY` | **예** | - | Gemini API 키 (의도 분류, 요약) |

### 2.4 G2B / 공공데이터 API

| 변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `G2B_SERVICE_KEY` | **예** | - | 나라장터 공공데이터 serviceKey |

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

### 2.8 MLOps / Automation (Arq)

원본의 Harness 관련 변수(`HARNESS_ACCOUNT_ID`, `HARNESS_API_KEY`, `HARNESS_PIPELINE_ID`)는 실행 백엔드를 Arq 로 교체하면서 사용하지 않습니다.

| 변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `AUTOMATION_WORKER_SHARES_DB` | 아니오 | `true` | 워커가 앱과 같은 DB 를 보는지 여부. 기본 docker-compose 구성은 공유합니다 |
| `AUTOMATION_CALLBACK_BASE_URL` | 아니오 | (없음) | 워커를 별도 배포해 DB 를 공유하지 않을 때 결과를 되돌려 보낼 API 주소 |
| `AUTOMATION_REUSE_RECENT` | 아니오 | `true` | 고비용 작업(`full_validation`)의 최근 72시간 성공 이력 재사용 |
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

### 2.9 ML / Retraining

| 변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `MODEL_REGISTRY_PATH` | 아니오 | `ml_registry` | 모델 레지스트리 경로 |
| `ML_WEEKLY_RETRAIN_ENABLED` | 아니오 | `true` | 매주 월요일 03:00 재학습 크론 사용 여부 |
| `DRIFT_PSI_THRESHOLD` | 아니오 | `0.2` | 데이터 드리프트 PSI 임계값 |
| `MLOPS_WEBHOOK_URL` | 아니오 | (없음) | 재학습 실패·승격 권고를 보낼 웹훅(Slack/Discord) 주소. 비면 알림을 보내지 않습니다 |

`MLOPS_WEBHOOK_URL` 이 비어 있으면 알림 발신이 통째로 생략됩니다. 개발 장비의 기본 동작이며, `ML_WEEKLY_RETRAIN_ENABLED` 와 같은 규약입니다. 알림 발신 실패는 재학습을 되돌리지 않고 로그만 남깁니다. 무엇을 보내고 무엇을 보내지 않는지는 [`docs/design/mlops_notification_20260805.md`](../design/mlops_notification_20260805.md) 4장을 참조하십시오.

재학습 시각 자체는 환경 변수가 아니라 `src/tasks/worker.py` 의 `cron_jobs` 에 고정되어 있습니다. 원본 Airflow DAG 의 `schedule_interval='0 3 * * 1'` 을 그대로 옮긴 값이므로, 바꿀 때는 원본과의 차이를 인지하고 변경하십시오.

---

## 3. 로드 패턴

- `.env` 파일은 `.gitignore`로 제외됩니다.
- 개발 환경: `.env` 파일에서 로드 (`python-dotenv` 또는 `django-environ`).
- 운영 환경: 환경변수 주입 (Docker Compose `environment` 또는 오케스트레이터 시크릿).
- 누락된 필수 변수는 애플리케이션 시작 시 검증하고 명확한 에러를 발생시킵니다.

---

## 4. 보안 주의사항

- 어떤 환경변수의 **실제 값도 문서에 기록하지 않습니다.**
- 시크릿 순환 정책을 운영 환경에 적용합니다.
- 상세는 [`security/README.md`](../security/README.md) 참조.
