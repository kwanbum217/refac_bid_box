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

### 2.8 MLOps / Automation (Harness)

| 변수 | 필수 | 설명 |
| --- | --- | --- |
| `HARNESS_ACCOUNT_ID` | 아니오 | Harness 계정 |
| `HARNESS_API_KEY` | 아니오 | Harness API 키 |
| `HARNESS_PIPELINE_ID` | 아니오 | Harness 파이프라인 ID |

### 2.9 ML / Retraining

| 변수 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `MODEL_REGISTRY_PATH` | 아니오 | `ml_registry` | 모델 레지스트리 경로 |
| `RETRAIN_SCHEDULE` | 아니오 | `0 3 * * 1` | 재학습 주간 스케줄 (월요일 03:00) |
| `DRIFT_PSI_THRESHOLD` | 아니오 | `0.2` | 데이터 드리프트 PSI 임계값 |

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
