# BIDBOX 리팩토링 설계서

> 원본: `bid_box` (Django 5.1.6 모놀리식)
> 대상: `refac_bid_box` (https://github.com/kwanbum217/refac_bid_box)
> 작성일: 2026-07-31

---

## 0. 문서 개요

본 설계서는 기존 `bid_box` 프로젝트를 **데이터 무손실**, **크로스 플랫폼 호환(macOS/Windows)**, **기술 스택 최적화(레이턴시·정합성)** 세 가지 목표로 리팩토링하기 위한 청사진이다. 각 장은 현재 상태 분석 → 문제점 → 목표 → 설계 → 이행 절차 순으로 구성된다.

---

## 1. 현재 시스템 분석 (AS-IS)

### 1.1 시스템 개요

공공조달(G2B/나라장터) 입찰 데이터를 수집·분석하고, 하이브리드 RAG 챗봇·AI 낙찰가 예측·Harness Cloud MLOps를 통합한 Django 모놀리식 플랫폼.

| 영역 | 기술 |
|------|------|
| 웹 프레임워크 | Django 5.1.6 (동기 WSGI, 서버사이드 렌더링) |
| 프론트엔드 | Django Templates + Chart.js + DaisyUI 4.x + Mermaid |
| DB | MariaDB/MySQL 3307 (운영), SQLite (스테이징 fallback) — env 스위치 |
| ORM/마이그레이션 | Django ORM + Django migrations (5개 앱, 19개 마이그레이션) |
| 인증 | django-allauth (Google/Kakao/Naver OAuth) + CustomUser |
| ML | scikit-learn, LightGBM, CatBoost, category-encoders (joblib 직렬화 가중치) |
| 벡터DB/RAG | ChromaDB 0.6.3 (`chroma_db/`, 19개 컬렉션) |
| LLM | Google Gemini (`google-genai`) |
| MLOps | Harness Cloud (YAML 파이프라인 + `hc.exe` CLI 바이너리) |
| 캐시 | 파일기반(`.django_cache`) / locmem / dummy — env 스위치 |

### 1.2 데이터 자산 (보존 대상)

| 자산 | 위치 | 규모 | 비고 |
|------|------|------|------|
| DB 데이터 | MySQL `procurement` | 다수 테이블 (9개 모델) | **핵심 보존 대상** |
| ML 가중치 | `apps/predictions/model_files/` (4종) | ~41MB | v25, quantum_leap_v25_pro, ssh_hist_premium, v13_hybrid |
| 벡터DB | `chroma_db/` | 3.4MB, 19개 컬렉션 | RAG 임베딩 |
| parquet 스냅샷 | `data/exports/` | 438MB | 입찰 데이터 스냅샷 |
| 학습 데이터 | `ssh/`, `sde/` | ~36MB CSV | 정제/원천 데이터 |
| RAG KB | `rag_kb.csv` | 768KB | 지식베이스 원문 |

### 1.3 핵심 문제점 (리팩토링 동기)

1. **동기식 WSGI 병목**: 챗봇(LLM/벡터검색), G2B API 수집, 모델 추론 등 I/O 집약 작업이 동기 블로킹 → 동시 요청 시 레이턴시 급증
2. **DB 이중화 리스크**: 운영 MySQL과 스테이징 SQLite를 env 스위치로 운영 → 스키마 불일치, 데이터 정합성 위험. `PyMySQL.install_as_MySQLdb()` 트릭 사용
3. **거대 파일/책임 집중**: `chatbot/views.py`(801줄), `automation_orchestrator.py`(44KB), `rag_engine.py`(35KB), `planner.py`(32KB), `predictor.py`(758줄)
4. **크로스 플랫폼 미대응**: Harness `hc.exe`(Windows 바이너리)·`.ps1` 스케줄러에 종속, macOS에서 `mysqlclient` 빌드 의존성 문제
5. **대용량 바이너리 in repo**: `hc.exe`(46MB), `hc.tar.gz`(15MB)가 Git에 포함 → 클론 비대
6. **보안**: `.env`에 실제 키 평문, `AUTH_PASSWORD_VALIDATORS` 전체 주석, SECRET_KEY 기본값 하드코딩, DEBUG 기본 True
7. **모델 동적 로드**: `importlib`로 `preprocess.py` 런타임 로드 → 모델별 전처리 로직 분산·추적 곤란
8. **캐시 전략 부재**: 효율적 인메모리 캐시(Redis 등) 없이 파일/locmem에 의존

---

## 2. 리팩토링 원칙 및 목표 (TO-BE)

### 2.1 3대 핵심 목표

| # | 목표 | 정량/정성 지표 |
|---|------|----------------|
| G1 | **데이터 무손실 마이그레이션** | DB 행 수·스키마 100% 보존, 모델 가중치/벡터DB 무결성 검증 통과 |
| G2 | **크로스 플랫폼 호환** | macOS·Windows에서 `make dev`/`make test` 단일 명령 실행 가능, 플랫폼 의존 바이너리 제거 |
| G3 | **기술 스택 최적화** | 챗봇 P95 레이턴시 50%↓, DB 정합성(트랜잭션·제약조건) 강화, 동시 처리량 향상 |

### 2.2 원칙

- **점진적 이행**: 빅뱅 교체 지양. 스키마 호환성을 유지하며 단계별 전환( strangler fig 패턴)
- **데이터가 우선**: 코드보다 데이터 보존·검증을 먼저 확보
- **외부화**: 바이너리·가중치·대용량 데이터는 Git이 아닌 외부 저장소(LFS/오브젝트 스토리지)로 분리
- **재현성**: 모든 환경이 `make`/`docker` 단일 명령으로 재현 가능
- **보안 기본값**: 시크릿 주입·검증기 활성화·DEBUG=False 기본

---

## 3. 제안 기술 스택 (TO-BE) 및 근거

### 3.1 백엔드 프레임워크 전환: Django → **FastAPI (권장)**

| 항목 | AS-IS (Django WSGI) | TO-BE (FastAPI ASGI) | 근거 |
|------|---------------------|----------------------|------|
| I/O 동시성 | 동기 블로킹 | **비동기(async/await)** | 챗봇(LLM 호출·벡터검색), G2B API 수집, 모델 추론이 모두 I/O 바운드 → 비동기로 레이턴시·처리량 대폭 개선 (G3) |
| 레이턴시 | 동시 요청 시 직렬 대기 | 이벤트 루프 병행 | P95 레이턴시 50%↓ 목표 달성 가능 |
| 타입/스키마 | Django Form/Serializer | **Pydantic v2** (이미 의존 중) | 요청/응답 검증 자동·직관, 기존 `pydantic 2.10` 활용 |
| API 문서 | 수동 | **자동 OpenAPI/Swagger** | `api_specification.md`(19KB) 수동 유지보수 부담 제거 |
| ML 통합 | 동기 로드 | 백그라운드 태스크(Celery/Arq) | 무거운 추론·수집 작업 비동기 오프로드 |

> **대안 검토 — Django ASGI (uvicorn + django-async-views)**: ORM·인증·admin을 그대로 쓸 수 있어 이행 비용이 가장 낮다. 단, Django ORM의 동기 제약(비동기 컨텍스트에서 `database_sync_to_async` 래핑 필요)과 Async 세컨드클래스 시민 이슈가 남는다.
>
> **결정 기준**:
> - **이행 비용 최소·안정성 우선** → **Django ASGI 유지 + 점진적 API 분리**
> - **성능·타입 안전성·API-퍼스트 우선** → **FastAPI 전환**
> - 두 안 모두 아래의 DB/캐시/태스크/ML 변경안은 동일하게 적용된다.

### 3.2 데이터베이스: MySQL/MariaDB **유지 + 이중화 제거**

| 항목 | AS-IS | TO-BE | 근거 |
|------|-------|-------|------|
| 엔진 | MySQL + SQLite env 스위치 | **MySQL 단일 통일** (모든 환경) | 스키마 불일치·정합성 리스크 제거 (G3). 단, 로컬 개발 편의를 위해 **Docker MySQL**로 macOS/Windows 동일 환경 제공 (G2) |
| 드라이버 | `mysqlclient`(빌드 의존) + `PyMySQL.install_as_MySQLdb()` 트릭 | **PyMySQL 순수 파이썬** 또는 **mysqlclient in Docker** | macOS에서 `mysqlclient` 빌드 실패 이슈 → Docker로 표준화 (G2). 순수 파이썬 드라이버는 빌드 의존성 제거 |
| 마이그레이션 도구 | Django migrations (19개) | **Alembic** (FastAPI) / Django migrations 유지 | 스키마 호환 유지하며 점진 전환. **기존 migration 히스토리 전체 보존** (G1) |
| 정합성 | 제약조건 약함 | **트랜잭션·FK·유니크 제약 강화** | 데이터 무결성 확보 (G3) |

**로컬 개발 DB 전략 (크로스 플랫폼)**:
```
docker-compose.yml → MySQL 8 서비스 (macOS/Windows/Linux 동일 버전)
개발자는 `make db-up` 한 번으로 동일 DB 환경 확보
```

### 3.3 캐시: 파일/locmem → **Redis**

| 항목 | AS-IS | TO-BE | 근거 |
|------|-------|-------|------|
| 백엔드 | 파일기반(`.django_cache`)/locmem | **Redis** (Docker) | 인메모리 → 조회 레이턴시 마이크로초, 프로세스 간 공유, TTL/LRU 지원 |
| 용도 | Django 템플릿 프래그먼트 | 대시보드 집계, G2B 응답, 모델 추론 결과, 세션 | 핫 쿼리(대시보드 통계) 반복 계산 회피 → 레이턴시 ↓ (G3) |

### 3.4 백그라운드 태스크: 동기 → **Celery + Redis (또는 Arq)**

| 작업 | AS-IS | TO-BE | 근거 |
|------|-------|-------|------|
| G2B 데이터 수집 | 동기 뷰/커맨드 | **비동기 태스크 큐** | 장시간 실행(수십 분) 작업을 워커로 분리 → API 블로킹 제거, 재시도/스케줄링 |
| 모델 재학습/추론 배치 | Harness 원격 | **로컬 워커 + (선택) Harness** | macOS/Windows 로컬 실행 보장 (G2), 실패 시 재시도·추적 |
| RAG KB 업데이트 | 커맨드 | **스케줄 태스크(crontab/beat)** | 야간 자동 갱신 |

> **Arq vs Celery**: Arq(Redis 기반, async 네이티브)는 FastAPI와 궁합이 좋고 경량. Celery는 성숙도·모니터링(Flower) 우세. 팀 규모·운영 복잡도에 따라 선택.

### 3.5 ML 추론 서비스

| 항목 | AS-IS | TO-BE | 근거 |
|------|-------|-------|------|
| 모델 로드 | 요청마다/동적 `importlib` | **앱 시작 시 싱글톤 로드** (메모리 상주) | 매 로드 오버헤드 제거 → 추론 레이턴시 ↓ (G3) |
| 가중치 저장 | Git 내 `model_files/` (41MB) | **Git LFS 또는 오브젝트 스토리지** | repo 경량화, 버전 관리 명확화 (G2 클론 속도) |
| 전처리 | 모델별 분산 `preprocess.py` | **통합 전처리 레지스트리** | 추적·테스트 용이, 동적 로드 제거 |
| 추론 API | 동기 뷰 | **비동기 엔드포인트 + 결과 캐싱** | 동시 추론 병렬화 |

### 3.6 벡터DB/RAG: ChromaDB → **유지(단일 인스턴스) 또는 Qdrant**

| 항목 | AS-IS | TO-BE | 근거 |
|------|-------|-------|------|
| 엔진 | ChromaDB (임베디드) | **ChromaDB 유지(로컬)** 또는 **Qdrant(Docker)** | 데이터 보존 우선 시 ChromaDB 유지(G1). 성능·필터링 강화 시 Qdrant 고려 |
| 검색 | 동기 | **비동기 검색** | RAG 파이프라인 병렬화 |
| 임베딩 재계산 | 불명확 | 기존 컬렉션 **그대로 마이그레이션** | 19개 컬렉션 무결성 보존 (G1) |

### 3.7 프론트엔드 (선택적, 우선순위 낮음)

| 항목 | AS-IS | TO-BE (권장) | 근거 |
|------|-------|--------------|------|
| 렌더링 | Django Templates (SSR) | **SSR 유지 + 점진적 하이브리드(HTMX)** | 챗봇 스트리밍 응답 등 인터랙션 필요 시에만 도입. 풀 SPA(React/Vue)는 오버킬 |
| 채팅 UI | 폴링/동기 | **SSE/WebSocket 스트리밍** | LLM 토큰 스트리밍 → 체감 레이턴시 ↓ (G3) |

### 3.8 MLOps/Harness: 바이너리 종속 → **외부화 + 플랫폼 중립**

| 항목 | AS-IS | TO-BE | 근거 |
|------|-------|-------|------|
| CLI | `hc.exe`(Windows)/`hc.tar.gz`(46+15MB) in Git | **Git에서 제거**, CI에서 다운로드 또는 REST API만 사용 | repo 경량화 + 크로스 플랫폼 (G2) |
| 스케줄러 | `.ps1`(Windows 작업스케줄러) | **Celery Beat / cron(크로스플랫폼)** | OS 종속성 제거 (G2) |

### 3.9 패키지 관리: pip → **uv + pyproject.toml**

| 항목 | AS-IS | TO-BE | 근거 |
|------|-------|-------|------|
| 도구 | `requirements.txt`(76개, pip) | **uv + pyproject.toml** (의존성 그룹화) | 10~100x 빠른 설치,_lockfile 재현성, dev/prod 그룹 분리, 크로스 플랫폼 동일 (G2) |
| 파이썬 | 불명확 | **Python 3.11+ 고정** (pyproject에 명시) | 버전 표준화 (G2) |

### 3.10 컨테이너화: 없음 → **Docker + docker-compose**

| 항목 | TO-BE | 근거 |
|------|-------|------|
| Dockerfile (앱) | 파이썬 슬림 이미지 | macOS/Windows/Linux 동일 런타임 (G2) |
| docker-compose | app + MySQL + Redis (+ worker) | `make up` 단일 명령으로 전체 스택 실행 (G2) |

---

## 4. 타겟 아키텍처 (TO-BE)

```
                        ┌──────────────────────────────────────────┐
                        │              Client (Browser)             │
                        │   Django Templates/HTMX + Chart.js        │
                        │   (SSE/WebSocket for chat streaming)      │
                        └──────────────────┬───────────────────────┘
                                           │ HTTPS
                        ┌──────────────────▼───────────────────────┐
                        │            Reverse Proxy (Nginx)          │
                        └──────────────────┬───────────────────────┘
                                           │
                        ┌──────────────────▼───────────────────────┐
                        │      FastAPI / Django ASGI (uvicorn)      │
                        │  ┌──────────┐ ┌──────────┐ ┌──────────┐  │
                        │  │ bids API │ │ chatbot  │ │predict   │  │
                        │  │          │ │ (async)  │ │ API      │  │
                        │  └────┬─────┘ └────┬─────┘ └────┬─────┘  │
                        └───────┼────────────┼────────────┼────────┘
                                │            │            │
              ┌─────────────────┼────────────┼────────────┼──────────────┐
              │                 │            │            │              │
   ┌──────────▼─────┐  ┌────────▼───┐  ┌─────▼────┐  ┌───▼────────┐  ┌──▼────────┐
   │  MySQL 8 (DB)  │  │   Redis    │  │ ChromaDB │  │ ML In-Memory│  │  Gemini   │
   │  (Docker)      │  │ (cache+    │  │ /Qdrant  │  │  (singleton)│  │  (LLM)    │
   │                │  │  broker)   │  │ (vector) │  │  weights    │  │           │
   └────────────────┘  └────────────┘  └──────────┘  └─────────────┘  └───────────┘
                                           ▲
                       ┌───────────────────┼─────────────────────┐
                       │   Celery / Arq Worker (async tasks)     │
                       │   - G2B data collection                 │
                       │   - model retrain/batch inference       │
                       │   - RAG KB update (scheduled)           │
                       └─────────────────────────────────────────┘
                                           ▲
                       ┌───────────────────┼─────────────────────┐
                       │   External Stores (outside Git)         │
                       │   - Model weights (Git LFS / S3)        │
                       │   - parquet snapshots (S3/NAS)          │
                       │   - Harness CLI (CI download)           │
                       └─────────────────────────────────────────┘
```

### 4.1 타겟 디렉토리 구조 (FastAPI 기준; Django 유지 시 기존 구조 개선)

```
refac_bid_box/
├── pyproject.toml              # uv 의존성 (dev/prod 그룹)
├── docker-compose.yml          # app + mysql + redis + worker
├── Dockerfile
├── Makefile                    # make dev/test/migrate/up (크로스플랫폼 진입점)
├── .env.example
├── alembic.ini                 # (FastAPI) / Django migrations 유지
├── src/
│   ├── app/                    # FastAPI 앱
│   │   ├── main.py             # 진입점 (uvicorn)
│   │   ├── core/               # config, security, db 세션
│   │   ├── api/v1/             # 라우터 (bids, chatbot, predictions, accounts)
│   │   ├── models/             # ORM 모델 (기존 9개 보존)
│   │   ├── schemas/            # Pydantic 스키마
│   │   └── services/           # 비즈니스 로직 (예측, RAG, 수집)
│   ├── ml/                     # ML 도메인 (싱글톤 로드, 통합 전처리)
│   │   ├── predictor.py
│   │   ├── registry.py         # 모델별 전처리 레지스트리
│   │   └── weights/            # (gitignore, LFS/외부에서 주입)
│   ├── tasks/                  # Celery/Arq 비동기 태스크
│   └── rag/                    # RAG 엔진 (ChromaDB/Qdrant 클라이언트)
├── migrations/                 # Alembic (FastAPI) 또는 apps/*/migrations (Django)
├── templates/                  # (Django/HTMX 시)
├── static/
├── data/                       # 로컬 데이터 (gitignore 대상, 외부 주입)
├── tests/
├── scripts/                    # 데이터 마이그레이션·검증 스크립트
└── docs/
    ├── REFACTORING_DESIGN.md   # 본 문서
    ├── MIGRATION_RUNBOOK.md    # 데이터 이행 절차서
    └── ...
```

---

## 5. 데이터 무손실 마이그레이션 설계 (G1 핵심)

### 5.1 보존 대상 및 위험도

| 자산 | 위험도 | 전략 |
|------|--------|------|
| MySQL 행 데이터 | **高** | 풀 덤프 + 검증 |
| DB 스키마/제약조건 | **高** | 기존 마이그레이션 히스토리 100% 보존 |
| ML 가중치(4종) | **中** | 바이너리 복사 + 로드 검증 |
| ChromaDB 컬렉션(19개) | **中** | 디렉토리 복사 + 쿼리 검증 |
| parquet/CSV 데이터 | **低** | 외부 저장소 이동 (변경 없음) |

### 5.2 DB 마이그레이션 절차

```
[1] 사전 스냅샷          mysqldump --single-transaction --routines --triggers \
                         procurement > snapshot_pre.sql
                         + 행 수 카운트 SQL 결과 저장 (검증 기준선)

[2] 스키마 호환성 확보    새 ORM 모델 = 기존 Django 모델과 동일 테이블명·컬럼명·타입
                         (BidResult → bid_results 등 매핑 유지)
                         ※ 컬럼 타입 변경 금지 (데이터 손실 위험)

[3] 이행                 기존 DB 그대로 신규 앱이 바라보도록 연결만 변경
                         (데이터 복사 아님 — 다운타임 최소화)
                         또는 복제 이행 시: dump → 신규 DB restore

[4] 검증 (자동화)        행 수 비교 (원본 vs 이행 후) — 100% 일치 확인
                         체크섬/샘플 행 diff
                         FK 무결성, 유니크 제약, 인덱스 점검
                         마이그레이션 status 일치 (django_migrations 테이블)

[5] 롤백 계획            snapshot_pre.sql 보관 → 이상 시 즉시 복원
                         컷오버 전 트래픽 중단(유지보수 창) 권장
```

### 5.3 마이그레이션 히스토리 보존

- **기존**: 5개 앱의 `migrations/` (총 19개 버전) → 신규 저장소로 **통째로 복사**
- 이유: Django/Alembic이 스키마 상태를 추적하는 단일 정보원. 히스토리 단절 시 향후 마이그레이션 충돌
- `django_migrations` 테이블의 기록도 DB와 함께 보존됨

### 5.4 ML 가중치 검증

```
각 모델 디렉토리(v25, quantum_leap_v25_pro, ssh_hist_premium, v13_hybrid):
  [1] 파일 체크섬(sha256) 기록 → 복사 후 일치 확인
  [2] 신규 predictor 로드 → 샘플 입력에 대한 예측값이 기존과 동일한지 회귀 테스트
  [3] 메타데이터(metadata.json) 스펙 호환성 확인
```

### 5.5 ChromaDB 검증

```
[1] chroma_db/ 디렉토리 복사 후 19개 컬렉션 존재 확인
[2] 각 컬렉션 문서 수 비교 (원본 vs 복사본)
[3] 샘플 쿼리 10건 → 동일 top-k 결과 반환 확인
```

---

## 6. 크로스 플랫폼 호환 설계 (G2)

### 6.1 핵심 과제와 해결

| 과제 | 해결 |
|------|------|
| `mysqlclient` macOS 빌드 실패 | Docker MySQL + PyMySQL(순수 파이썬) 드라이버 |
| `hc.exe` Windows 바이너리 종속 | Git 제거 → CI 다운로드 or REST API |
| `.ps1` Windows 스케줄러 | Celery Beat(크로스플랫폼)로 대체 |
| 환경 차이로 인한 재현 불가 | Docker + Makefile 표준화 |
| 경로 구분자/인코딩 | `pathlib.Path` 전면 사용, UTF-8 강제 |

### 6.2 Makefile 진입점 (macOS/Windows/Git Bash 공용)

```makefile
# Windows에서는 Make for Windows 또는 Git Bash 필요. 대안: Taskfile.yml.
.PHONY: setup dev test migrate db-up up down lint

setup:        ## 의존성 설치 (uv)
	uv sync

db-up:        ## MySQL + Redis 컨테이너 기동
	docker compose up -d mysql redis

dev:          ## 개발 서버 실행
	uvicorn src.app.main:app --reload --port 8000

migrate:      ## 마이그레이션 적용
	alembic upgrade head     # 또는 python manage.py migrate

test:         ## 테스트 실행
	pytest -q

up:           ## 전체 스택 기동 (app+db+redis+worker)
	docker compose up -d

down:         ## 전체 스택 중지
	docker compose down
```

> Windows 네이티브 `make` 부재 시 **Taskfile.yml + go-task** 또는 **just**를 대안으로 권장 (단일 바이너리, 크로스플랫폼).

### 6.3 인코딩 가드 (기존 프로젝트 교훈 반영)

- 모든 파일 입출력 시 `encoding="utf-8"` 명시
- CSV/parquet 로드 시 인코딩·구분자 자동 감지 로직 유지
- DB 연결 charset `utf8mb4` 고정

### 6.4 Docker Compose (전체 스택)

```yaml
# docker-compose.yml (개념)
services:
  mysql:    # MySQL 8 — macOS/Windows 동일
  redis:    # 캐시 + 브로커
  app:      # FastAPI/Django (uvicorn)
  worker:   # Celery/Arq 워커
```
→ 개발자는 `docker compose up` 한 번으로 운영과 동일한 스택을 로컬에 재현.

---

## 7. 이행 로드맵 (단계별)

> 원칙: 각 단계가 **독립적으로 검증 가능**하고 **롤백 가능**해야 한다.

### Phase 0 — 기반 정비 (1~2일)
- [x] 신규 저장소 초기화 (완료)
- [ ] `pyproject.toml`(uv) + 의존성 그룹 정의
- [ ] `Makefile` / `Taskfile` 진입점
- [ ] `.env.example` 보강 (완료 기본)
- [ ] `Dockerfile` + `docker-compose.yml`(mysql, redis)
- [ ] 린터/포매터(ruff, black), pre-commit 설정
- [ ] CI(GitHub Actions): lint + test 파이프라인

### Phase 1 — 데이터 보존 선행 (2~3일) ★ G1
- [ ] 기존 MySQL 풀 덤프 + 행 수 기준선 문서화
- [ ] ML 가중치 체크섬 기록
- [ ] ChromaDB 백업
- [ ] 자동화된 검증 스크립트 작성 (`scripts/verify_migration.py`)
- [ ] **검증 통과 후에만 다음 단계 진행**

### Phase 2 — DB/캐시/태스크 인프라 (3~5일)
- [ ] ORM 모델 이식 (기존 9개, 테이블명·컬럼 100% 유지)
- [ ] 마이그레이션 히스토리 복사 (19개 버전)
- [ ] Redis 캐시 레이어 적용
- [ ] Celery/Arq 워커 + 태스크 이식 (G2B 수집, KB 업데이트)
- [ ] 기존 DB 연결 후 데이터 무결성 재검증

### Phase 3 — 애플리케이션 이식 (5~10일)
- [ ] 백엔드 전환 결정(FastAPI vs Django ASGI)에 따라 라우터/서비스 이식
- [ ] 거대 파일 분할:
      - `chatbot/views.py`(801줄) → 라우터 + 서비스 + 스키마 분리
      - `automation_orchestrator.py`/`rag_engine.py`/`planner.py` → 도메인별 모듈
      - `predictor.py`(758줄) → ML 도메인 + 싱글톤 로드
- [ ] 비동기화: 챗봇 API, G2B 수집, 모델 추론
- [ ] 보안 강화: 검증기 활성화, SECRET_KEY/DEBUG 환경 강제, 시크릿 관리

### Phase 4 — ML/RAG 최적화 (3~5일)
- [ ] 모델 싱글톤 로드 + 통합 전처리 레지스트리
- [ ] 가중치 Git LFS / 외부 저장소 이동
- [ ] RAG 검색 비동기화 + 결과 캐싱
- [ ] Harness 바이너리 Git 제거 + 플랫폼 중립화

### Phase 5 — 프론트엔드/스트리밍 (선택, 3~5일)
- [ ] 챗봇 SSE/WebSocket 스트리밍
- [ ] HTMX 도입(필요 시)

### Phase 6 — 검증 및 컷오버 (2~3일)
- [ ] E2E 테스트 (`tests/chatbot_e2e/` 이식)
- [ ] 성능 벤치마크 (Before/After 레이턴시 비교)
- [ ] 크로스 플랫폼 실행 검증 (macOS + Windows)
- [ ] 컷오버 + 사후 모니터링

---

## 8. 위험 관리

| 위험 | 확률 | 영향 | 완화 |
|------|------|------|------|
| 마이그레이션 중 데이터 손실 | 중 | **치명적** | 풀 덤프 + 자동 검증 + 롤백 계획 (G1 최우선) |
| ORM 전환 시 스키마 불일치 | 중 | 높음 | 테이블/컬럼명 100% 유지, 타입 변경 금지 |
| FastAPI 전환 공수 과대 | 중 | 중 | 점진적 이행, 필요 시 Django ASGI 대안 |
| ML 가중치 비호환 | 낮 | 중 | 체크섬 + 회귀 테스트 |
| 크로스플랫폼 의존성 누락 | 중 | 중 | Docker 표준화 + CI에서 Windows/macOS 매트릭스 테스트 |
| 성능 개선 미달 | 낮 | 중 | Phase 6 벤치마크로 조기 검증 |

---

## 9. 결정 보류 사항 (사용자 확인 필요)

아래 사항은 트레이드오프가 명확하여 구현 착수 전 사용자 결정이 필요하다.

1. **백엔드 프레임워크**: FastAPI 전환 vs Django ASGI 유지
2. **로컬 DB**: Docker MySQL(통일) vs SQLite(개발 편의, 운영과 분리)
3. **태스크 큐**: Celery(성숙) vs Arq(경량·async)
4. **벡터DB**: ChromaDB 유지(보존 우선) vs Qdrant 전환(성능)
5. **ML 가중치 저장**: Git LFS vs 외부 오브젝트 스토리지(S3 등)

---

_본 설계서는 살아있는 문서입니다. 이행 과정에서 발견되는 사항은 지속 갱신됩니다._
