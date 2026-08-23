# BIDBOX 리팩토링 설계서

> 원본: `bid_box` (Django 5.1.6 모놀리식)
> 대상: `refac_bid_box` (https://github.com/kwanbum217/refac_bid_box)
> 작성일: 2026-07-31
> 상태: Baseline Design (설계 기준선)
> 운영 상태 정본: [`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md)

> [!NOTE]
> **설계 기준선(Baseline Design) 안내**
> 본 문서는 프로젝트 초기(2026-07-31)에 작성된 리팩토링 청사진 및 설계 기준선입니다.
> 본 문서의 초기 목표치 및 계획 수치는 설계 당시의 기준선이며, 현재 시스템의 구현 상태, 실측 레이턴시 및 운영 판정의 단일 진실 원천(SSOT)은 [`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md) 및 최신 프로토콜 문서([`docs/ops/latency_gate_protocol.md`](../ops/latency_gate_protocol.md))입니다.

---

## 0. 문서 개요

본 설계서는 기존 `bid_box` 프로젝트를 **데이터 무손실**, **크로스 플랫폼 호환(macOS/Windows)**, **기술 스택 최적화(레이턴시·정합성)** 세 가지 목표로 리팩토링하기 위한 설계 기준선(청사진)이다. 각 장은 현재 상태 분석 → 문제점 → 목표 → 설계 → 이행 절차 순으로 구성된다.

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
| 벡터DB/RAG | ChromaDB 0.6.3 (`chroma_db/`, 활성 컬렉션 `bidding_kb` 1개) |
| LLM | Google Gemini (`google-genai`) |
| MLOps | Harness Cloud (YAML 파이프라인 + `hc.exe` CLI 바이너리) |
| 캐시 | 파일기반(`.django_cache`) / locmem / dummy — env 스위치 |

### 1.2 데이터 자산 (보존 대상)

| 자산 | 위치 | 규모 | 비고 |
|------|------|------|------|
| DB 데이터 | MySQL `procurement` | 다수 테이블 (9개 모델) | **핵심 보존 대상** |
| ML 가중치 | `apps/predictions/model_files/` (4종) | ~41MB | v25, quantum_leap_v25_pro, ssh_hist_premium, v13_hybrid |
| 벡터DB | `chroma_db/` | 원본 3.4MB, 활성 컬렉션 1개 / 임베딩 10건 | RAG 임베딩 |
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
| 임베딩 재계산 | 불명확 | 원본 스냅샷 보존 후 운영 컬렉션 재구축 허용 | 원본 1개 컬렉션 무결성 보존 (G1) |

### 3.7 프론트엔드 (선택적, 우선순위 낮음)

| 항목 | AS-IS | TO-BE (권장) | 근거 |
|------|-------|--------------|------|
| 렌더링 | Django Templates (SSR) | **SSR 유지 + 점진적 하이브리드(HTMX)** | 챗봇 스트리밍 응답 등 인터랙션 필요 시에만 도입. 풀 SPA(React/Vue)는 오버킬 |
| 채팅 UI | 폴링/동기 | **SSE/WebSocket 스트리밍** | LLM 토큰 스트리밍 → 체감 레이턴시 ↓ (G3) |

### 3.8 MLOps 실행·CI: 외부 SaaS 종속 → **Arq + GitHub Actions**

| 항목 | AS-IS | TO-BE | 근거 |
|------|-------|-------|------|
| 실행 백엔드 | Harness Cloud 파이프라인 | **Arq + Redis 워커** | 로컬·컨테이너 재현성 및 비동기 실행 |
| CI | Harness YAML 파이프라인 | **GitHub Actions** (`.github/workflows/ci.yml`) | 저장소 표준 CI와 크로스 플랫폼 검증 |
| 스케줄러 | `.ps1`(Windows 작업스케줄러) | **Arq cron** | OS 종속성 제거 (G2) |

### 3.9 패키지 관리: pip → **uv + pyproject.toml**

| 항목 | AS-IS | TO-BE | 근거 |
|------|-------|-------|------|
| 도구 | `requirements.txt`(76개, pip) | **uv + pyproject.toml** (의존성 그룹화) | 10~100x 빠른 설치,_lockfile 재현성, dev/prod 그룹 분리, 크로스 플랫폼 동일 (G2) |
| 파이썬 | 불명확 | **Python 3.11+ 고정** (pyproject에 명시) | 버전 표준화 (G2) |

### 3.10 컨테이너화: 없음 → **Docker + docker-compose**

| 항목 | TO-BE | 근거 |
|------|-------|------|
| Dockerfile (앱) | 파이썬 슬림 이미지 | macOS/Windows/Linux 동일 런타임 (G2) |
| docker-compose | app + Arq worker + MySQL + Redis | `make up` 단일 명령으로 전체 스택 실행 (G2) |

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
                       │   - CI artifacts (GitHub Actions)        │
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
| ChromaDB `bidding_kb` 컬렉션(원본 10건) | **中** | 원본 스냅샷 체크섬 + 운영 컬렉션 구조 검증 |
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
[1] 원본 chroma_db/ 를 data/backups/chroma_source/ 에 별도 보존
[2] 원본 bidding_kb 1개 컬렉션 / 임베딩 10건과 파일 체크섬 확인
[3] 운영 chroma_db/ 는 bidding_kb 1개 컬렉션이 비어 있지 않은지 별도 확인
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
	docker compose up -d db redis

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
  db:       # MySQL 8 — macOS/Windows 동일
  redis:    # 캐시 + 브로커
  app:      # FastAPI/Django (uvicorn)
  worker:   # Arq 워커
```
→ 개발자는 `docker compose up` 한 번으로 운영과 동일한 서비스 토폴로지를 로컬에 재현.

---

## 7. 재학습(Training) 파이프라인 신규 설계 ★ 핵심 추가

> 기존 시스템은 수집·RAG·검증(ops) 파이프라인만 갖추고 있으며, **ML 모델 학습/재학습 단계가 전무**하다. 본 장에서는 학습 사이드 전체를 새로 설계한다.

### 7.1 현재 상태 (AS-IS) — 재학습 갭 분석

조사 결과, "재학습"은 요구사항 정의서·발표 자료에는 명시되어 있으나 **실행 가능한 구현체가 없다**. 구체적 증거:

| 항목 | 현황 | 증거 |
|------|------|------|
| `retrain_dag.py` | **순수 stub** | 3개 태스크 중 2개는 `echo`만, 1개는 **존재하지 않는 명령** `retrain_model_v13` 호출 |
| `retrain_model_v13` 명령 | **미구현** | 전체 grep 결과 0건 |
| `run_mode_matrix.py` 단계 공간 | `retrain` 단계 **정의 없음** | 가능 단계는 collect/rag/predict/inspect 4개뿐 |
| `local_automation.py` STEP_COMMANDS | 재학습 매핑 **없음** | 4개 명령만 |
| Harness 5단계 파이프라인 | retrain 단계 **0회** | `ci_pipeline_run.sh`에 `retrain` 키워드 0회 |
| 4개 모델 빌드 스크립트 | **2개만 존재** | `quantum_leap_v25_pro`는 실제 학습 아님(분위수 통계+하드코딩값 블렌딩); `v25`/`v13_hybrid`는 외부 노트북 산출물(model.bin)만 |

**가장 심각한 문제 — Train/Serve Skew (학습-서빙 특징 불일치):**

`predictor.py`의 추론 특징(52차원)에는 `inst_hist_rate`, `ppi`, `ex_rate`, `sem_0~31` 임베딩 등이 정의되어 있으나, **이들을 raw 데이터에서 계산하는 로직이 레포 전체에 없다.** 그 결과 실서비스 추론 시:
- `views.py`가 predictor에 넘기는 features_dict에는 원시 필드만 있고,
- `inst_hist_rate`/`ppi`/`ex_rate`/`sem_*`는 **하드코딩된 상수**(`DEFAULT_INST_RATE=0.925`, `DEFAULT_PPI=100.0`, `DEFAULT_EXCHANGE_RATE=1300.0`)로 들어간다.

즉, **학습 시점(외부 노트북)에 사용한 특징 분포와 서빙 특징 분포가 다르다.** 이는 모델 정확도의 근본 원인이며, 재학습 파이프라인 설계의 출발점이 된다.

**DB → 학습 데이터셋 변환 로직 부재:** `BidAnnouncement` + `BidResult`를 join하여 feature matrix를 만드는 코드가 없다 (수집→DB 적재는 완성되어 있으나, DB→학습 데이터는 비어있음).

**`validate_model.py` 한계:** 학습 후 RMSE/MAPE/R²를 실측하는 것이 아니라, 외부에서 미리 계산해 둔 `champion_summary.json`의 `avg_r2 >= 0.75` 임계값만 체크하는 게이트다.

### 7.2 재학습 설계 목표

| # | 목표 | 지표 |
|---|------|------|
| T1 | **재현 가능한 학습 파이프라인** | 동일 입력 → 동일 가중치(시드 고정), 학습 단계 전부 코드화 |
| T2 | **Train/Serve Skew 제거** | 학습·추론이 **동일 특징 생성 함수** 사용 (단일 진실 공급원) |
| T3 | **자동화된 재학습 트리거** | 정기(주간) + 데이터 드리프트 감지 + 수동 |
| T4 | **모델 버저닝·레지스트리** | 가중치·메타데이터·평가지표 추적, 롤백 가능 |
| T5 | **Champion/Challenger 배포** | 신규 모델이 현역(champion)을 성능으로 압도 시에만 승격 |
| T6 | **모니터링** | 데이터 드리프트·예측 분포 변화 감지 |

### 7.3 타겟 학습 파이프라인 (전체 흐름)

```
┌─────────────────────────────────────────────────────────────────────┐
│  1. DATA INGESTION (기존 수집 파이프라인 재사용)                       │
│     G2B API ─▶ DB (BidAnnouncement + BidResult)                       │
└───────────────────────────┬─────────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  2. TRAINING DATASET BUILD  ★ 핵심 신규 (현재 부재)                    │
│     - DB 쿼리: BidAnnouncement ⟕ BidResult (공고번호 join)            │
│     - 카테고리 분할: Thng / Servc / Cnstwk                             │
│     - 레이블 생성: sucsf_bid_rate (낙찰률) 또는 premium                │
│     - 특징 저장(Feature Store): 재사용 가능 형태로 캐싱                 │
└───────────────────────────┬─────────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  3. FEATURE ENGINEERING  ★ 핵심 신규 — Train/Serve 공유                │
│     단일 transform_features(df) 함수 (학습·추론 모두 호출)             │
│     - 기본: log_price, month/weekday + sin/cos                        │
│     - 기관 히스토리: inst_hist_rate (과거 낙찰률 집계 — 현재 상수값!)  │
│     - 시장 지표: PPI, 환율 (외부 데이터 소스 join)                     │
│     - 텍스트 임베딩: sem_0~31 (공고명 → 임베딩)                        │
│     - interaction 특징                                                │
└───────────────────────────┬─────────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  4. TRAIN                                                           │
│     - 시계열 분할(train:과거 / test:최근, 랜덤분할 지양)               │
│     - 모델: LightGBM / CatBoost (기존 스택 유지)                       │
│     - 시드 고정(재현성), 하이퍼파라미터 기록                           │
└───────────────────────────┬─────────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  5. EVALUATE  ★ validate_model.py 실측화                              │
│     - RMSE / MAPE / R² 실시간 산출 (summary JSON 의존 탈피)           │
│     - 카테고리별·기간별 성능 분해                                      │
│     - 기존 champion 대비 성능 비교 (Challenger 평가)                   │
└───────────────────────────┬─────────────────────────────────────────┘
                            ▼
        ┌─────────────────┴─────────────────┐
        ▼                                   ▼
  [성능 임계값                                  [미달]
   충족]                                    → 아카이브만,
        ▼                                       미배포
┌──────────────────────────────────────────┐
│  6. REGISTER & DEPLOY                    │
│     - 모델 레지스트리에 버전 등록           │
│       (가중치 + 메타데이터 + 평가지표)      │
│     - Champion 교체 (카나리/블루그린)       │
│     - 추론 서비스 핫스왑 (재시작 없이)      │
└───────────────────────────┬──────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  7. MONITOR (운영 중)                                                │
│     - 데이터 드리프트: 입력 특징 분포 변화 (PSI/KL)                    │
│     - 예측 드리프트: 예측값 분포 변화                                  │
│     - 임계 초과 시 → 재학습 트리거 자동 발화 (3단계로 루프)            │
└─────────────────────────────────────────────────────────────────────┘
```

### 7.4 핵심 설계 결정

#### (A) 단일 특징 공급원 (Single Source of Truth for Features) ★ T2 핵심

기존의 **train/serve skew**를 근본적으로 해결하기 위해, 특징 생성을 한 곳에 둔다.

```
src/ml/features.py
├── build_feature_frame(raw_df) → DataFrame   # 학습용 (DB 데이터프레임 입력)
└── build_feature_dict(request) → dict        # 추론용 (API 요청 입력)
    # 두 함수 모두 동일한 내부 _compute_features() 호출
    # → 학습·서빙 특징 정의가 영원히 일치
```

- **기관 히스토리 낙찰률**(`inst_hist_rate`): 더 이상 상수 `0.925`가 아닌, **DB 집계 쿼리**(기관별 과거 낙찰률 평균)로 계산. 집계 결과는 Redis에 캐싱하여 추론 시에도 실시간 계산 가능.
- **PPI/환율**: 외부 통계 API 또는 사전 적재된 참조 테이블에서 as-of join (시점 기준값).
- **텍스트 임베딩**(`sem_0~31`): 공고명 → 임베딩 모델. 학습 시 사전 계산하여 Feature Store에 저장, 추론 시 온디맨드 계산(캐싱).

#### (B) 학습 데이터셋 빌더 (현재 부재) ★ 신규

```
src/ml/dataset.py
└── build_training_dataset(category, since=None) → DataFrame
    - DB에서 BidAnnouncement ⟕ BidResult join (공고번호)
    - 결측치/이상치 처리 (ssh/final_cleaned_filtered.csv 정제 로직 승격)
    - 카테고리(Thng/Servc/Cnstwk) 분할
    - Feature Store(materialized parquet)에 캐싱 → 반복 학습 시 DB 부하 회피
```

기존 `ssh/final_cleaned_filtered.csv`의 정제 로직(결측치 필터링 등)을 일회성 스크립트에서 **재사용 가능한 모듈로 승격**.

#### (C) 재학습 트리거 (3가지)

| 트리거 | 조건 | 스케줄 |
|--------|------|--------|
| 정기 | 고정 주기 | 주 1회 (월요일 03:00, 기존 `retrain_dag.py` 의도) |
| 데이터 드리프트 | 입력 특징 분포 PSI > 임계값 | 비정기 (모니터링이 발화) |
| 수동 | 운영자 판단 | 온디맨드 (API/CLI) |

모두 **동일한 학습 파이프라인 코드**를 실행하며, 트리거 원인만 `PipelineExecution.source`에 기록.

#### (D) 모델 레지스트리 & 버저닝

기존의 느슨한 폴더 구조(`model_files/[model_id]/`)를 **레지스트리 패턴**으로 발전:

```
ml_registry/
└── {model_name}/
    └── {version}/            # 타임스탬프 + git SHA
        ├── model.bin         # 가중치 (joblib)
        ├── metadata.json     # 학습 설정 (하이퍼파라미터, 시드, 데이터 범위)
        ├── metrics.json      # RMSE/MAPE/R² (실측, champion_summary 대체)
        ├── feature_schema.json  # 특징 목록 (스키마 검증용)
        └── status            # challenger | champion | archived
```

- **Champion**: 현재 서빙 중인 모델
- **Challenger**: 평가 중인 신규 모델 (성능 압도 시 champion 승격, 기존은 archived)
- 롤백: 이전 champion 버전으로 즉시 복귀 가능

기존 메타데이터 스펙(`metadata.json` + `champion_summary.json`, `MODEL_INTEGRATION_GUIDE.md`에 문서화됨)을 **흡수·확장**. 기존 4개 모델은 초기 champion으로 레지스트리에 등록(바이너리 복사, 메타데이터 마이그레이션).

#### (E) 평가 실측화 (validate_model.py 개선)

```
기존: champion_summary.json의 avg_r2 >= 0.75 게이트만
개선: holdout/test 세트에 대해 RMSE, MAPE, R² 실시간 산출
      + 카테고리별·기간별 분해
      + champion vs challenger 비교 리포트 자동 생성
```

#### (F) 모니터링 (드리프트 감지)

- **데이터 드리프트**: 최근 N일 입력 특징 분포 vs 학습 시 분포를 PSI(Population Stability Index)로 비교. PSI > 0.2 시 경고·재학습 트리거.
- **예측 드리프트**: 예측값 분포 변화 추적.
- 결과는 `PipelineExecution`의 후속 모델(예: `ModelMonitoringLog`)에 누적.

### 7.5 학습 오케스트레이션 — 태스크 큐 연동

재학습은 장시간(수십 분~수 시간) 실행되므로 **비동기 태스크**(3.4절 Celery/Arq)로 구현. 기존 `run_mode_matrix`에 `retrain` 단계를 **정식 추가**:

```
run_mode_matrix (개정):
  refresh_data : (collect, rag, inspect)
  retrain_only : (retrain,)                    ★ 신규
  nightly_full : (collect, rag, retrain, predict, inspect)  ★ retrain 추가
```

→ 챗봇 자동화 오케스트레이터(`automation_orchestrator.py`)에서도 "재학습 실행"을 트리거 가능.

### 7.6 기존 코드 재사용 매핑

| 기존 자산 | 재사용 방식 |
|-----------|-------------|
| `build_ssh_hist_premium_model.py`(유일한 실제 학습 스크립트, KFold) | 학습 로직 **템플릿으로 승격** — 일반화된 `trainer.py`의 기반 |
| `ssh/final_cleaned_filtered.csv` 정제 로직 | `dataset.py`의 결측치 처리 모듈로 이식 |
| predictor.py 특징 정의(52차원) | `features.py`의 추출 기준 (학습용으로 보강) |
| 메타데이터 스펙(`metadata.json`/`champion_summary.json`) | 레지스트리 메타데이터 포맷으로 흡수 |
| 기존 4개 모델 가중치 | 레지스트리 초기 champion으로 등록 (G1 보존) |

### 7.7 트레이드오프 / 범위 한계

- **딥러닝 도입 여부**: 현재 스택(LightGBM/CatBoost)이 테이블 데이터에 효율적이므로 유지. TF/Keras는 레거시 import만 남기고 기본 비활성.
- **온라인 학습**: 범위 외. 배치 재학습(주간)으로 충분.
- **분산 학습**: 단일 워커 머신으로 시작. 데이터 규모(~140만 행)는 단일 머신으로 처리 가능.

---

## 8. 이행 로드맵 (단계별)

> 원칙: 각 단계가 **독립적으로 검증 가능**하고 **롤백 가능**해야 한다.

### Phase 0 — 기반 정비 (1~2일)
- [x] 신규 저장소 초기화 (완료)
- [x] `pyproject.toml`(uv) + 의존성 그룹 정의
- [x] `Makefile` / `Taskfile` 진입점
- [x] `.env.example` 보강 (완료 기본)
- [x] `Dockerfile` + `docker-compose.yml`(`app`, `worker`, `db`, `redis`)
- [x] 린터/포매터(ruff, black), pre-commit 설정
- [x] CI(GitHub Actions): lint + test 파이프라인

### Phase 1 — 데이터 보존 선행 (2~3일) ★ G1
- [x] 기존 MySQL 풀 덤프 + 행 수 기준선 문서화 (parquet 복원으로 대체)
- [x] ML 가중치 체크섬 기록 (`data_assets_checksums.json`)
- [x] ChromaDB 백업
- [x] 자동화된 검증 스크립트 작성 (`scripts/verify_migration.py`)
- [x] **검증 통과 후에만 다음 단계 진행** (행 수 100%+ 달성)

### Phase 2 — DB/캐시/태스크 인프라 (3~5일)
- [x] ORM 모델 이식 (기존 9개, 테이블명·컬럼 100% 유지)
- [x] 마이그레이션 히스토리 — Alembic 도입 완료(리비전 8개). 원본 Django 이력은 `django_migrations` 54행으로 DB 에 그대로 보존. 스키마 일치는 `scripts/check_schema_drift.py` 로 검증(2026-08-06 실질 차이 0건)
- [x] Redis 캐시 레이어 적용
- [x] Celery/Arq 워커 + 태스크 이식 (G2B 수집, KB 업데이트)
- [x] 기존 DB 연결 후 데이터 무결성 재검증

### Phase 3 — 애플리케이션 이식 (5~10일)
- [x] 백엔드 전환 결정(FastAPI vs Django ASGI)에 따라 라우터/서비스 이식
- [x] 거대 파일 분할:
      - `chatbot/views.py`(801줄) → 라우터 + 서비스 + 스키마 분리
      - `automation_orchestrator.py`/`rag_engine.py`/`planner.py` → 도메인별 모듈
      - `predictor.py`(758줄) → ML 도메인 + 싱글톤 로드
- [x] 비동기화: 챗봇 API, G2B 수집, 모델 추론
- [x] 보안 강화: 검증기 활성화, SECRET_KEY/DEBUG 환경 강제, 시크릿 관리

### Phase 4 — ML 추론/RAG 최적화 (3~5일)
- [x] 모델 싱글톤 로드 + 통합 전처리 레지스트리
- [x] 가중치 저장·배포 경로 정비 (2026-08-06) — 아래 전제 정정 참조
- [x] RAG 검색 비동기화 + 결과 캐싱
- [x] Harness 바이너리 Git 제거 + 플랫폼 중립화

#### 가중치 외부화 전제 정정 (2026-08-06)

이 절과 3.4 절은 AS-IS 를 "Git 내 `model_files/` (41MB)" 로 적고 목표를 저장소 경량화로 두었습니다. **2026-08-06 실사 결과 그 전제는 이미 해소된 상태였습니다.**

| 항목 | 실측 |
| --- | --- |
| `data/model_files/` 전체 | 71MB (모델 5종) |
| Git 추적 파일 | 10개 — `metadata.json`, `preprocess.py`, `champion_summary.json` |
| 바이너리 추적 | 없음 (`.gitignore` 의 `*.bin`, `*.joblib` 로 제외) |

경량화 대신 실제로 비어 있던 것은 **배포 경로**였습니다. 저장소만 클론한 장비에는 `metadata.json` 만 오고 `model.bin` 은 오지 않아 예측 API 가 뜨지 않습니다. `import_data_assets.py` 는 원본 `bid_box` 저장소가 옆에 있어야 동작하므로 새 장비에서는 쓸 수 없습니다.

Git LFS 와 오브젝트 스토리지는 검토 후 채택하지 않았습니다. LFS 는 GitHub 무료 한도가 저장 1GB·월 대역폭 1GB 인데 승격마다 71MB 가 누적돼 소진이 빠르고, 되돌리기도 어렵습니다. MinIO 는 `boto3` 의존성과 컨테이너 증설을 요구해 1인 운영·71MB 규모에 비용이 큽니다.

채택한 것은 **로컬 보관 유지 + 번들 배포 경로 확립**입니다.

| 조치 | 내용 |
| --- | --- |
| 경로 설정 단일화 | `MODEL_FILES_DIR`, `MODEL_BACKUPS_DIR`, `MODEL_METRICS_DIR`. 외부 볼륨 이전 시 코드 수정 불필요 |
| 배포 스크립트 | `scripts/sync_model_files.py` 의 `export` / `import` / `verify` |
| 무결성 | 파일별 SHA256 인벤토리 + 번들 사이드카. 검증 실패 시 배치하지 않음 |
| 매니페스트 | `data_assets_checksums.json` 은 갱신하지 않습니다. 원본 4종의 G1 기준선이며, 서빙본으로 다시 만들면 승격 모델이 기준선을 덮습니다 |

번들에는 `model_backups/` 를 반드시 포함합니다. 승격된 모델은 서빙본이 원본과 달라지므로 `verify_migration.py` 가 원본 기준선을 백업 쪽에서 대조합니다. 백업을 뺀 상태로 실측한 결과 G1 검증이 체크섬 불일치로 실패했습니다.

### Phase 5 — 재학습 파이프라인 구축 (5~8일) ★ 신규 — 7장 참조
- [x] **단일 특징 공급원** `features.py` 구현 (train/serve skew 제거)
- [x] **학습 데이터셋 빌더** `dataset.py` (DB join → feature matrix, 현재 부재)
- [x] **일반화 학습기** `trainer.py` (`build_ssh_hist_premium_model.py` 승격)
- [x] **평가 실측화**: validate_model 개선 (RMSE/MAPE/R² 실시간 산출)
- [x] **모델 레지스트리** — 다만 champion 등록은 `quantum_leap_v25_pro` 1개뿐입니다. `ssh_hist_premium`, `v13_hybrid`, `v25` 는 서빙 슬롯(`data/model_files/`)에만 있고 레지스트리에 없어 승격·롤백 경로 밖입니다. 서빙 지표는 실측 사이드카로 채웁니다(`scripts/measure_serving_model.py`)
- [x] **재학습 태스크** (Celery/Arq) + `run_mode_matrix`에 `retrain` 단계 추가
- [x] **재학습 트리거**: 주간 스케줄 + 수동 API — 둘 다 구현됨. 크론은 `src/tasks/worker.py:43` (월요일 03:00), 야간 수집은 매일 02:00
- [x] **모니터링**: 데이터/예측 드리프트 감지 (PSI)

### Phase 6 — 프론트엔드/스트리밍 (선택, 3~5일)
- [x] 챗봇 SSE/WebSocket 스트리밍 (stream 엔드포인트 + CONFIG.streamUrl)
- [ ] HTMX 도입(필요 시) — 현재 jQuery, 필요시 전환

### Phase 7 — 검증 및 컷오버 (2~3일)

> [!WARNING]
> **HISTORICAL SNAPSHOT — 현재 상태 판정에 사용 금지.** 아래 Phase 7 서술은 설계
> 기준선 작성 시점의 계획과 당시 관측입니다. 현재 게이트 판정은
> [`docs/context/CURRENT_STATE.md`](../context/CURRENT_STATE.md)와
> [`docs/ops/latency_gate_protocol.md`](../ops/latency_gate_protocol.md)만 근거로 삼습니다.
- [x] 원본 동작 재현·통합 테스트 — 원본 테스트 이름 기준 122/131(구조적 제외 9건), 2026-08-05 격리 환경 전량 632 passed / 2 skipped
- [x] 성능 벤치마크 (Before/After 레이턴시 비교) — 2026-08-06 실측: 예측 API P95 19.1ms(기동 직후), SSE 첫 토큰 P95 2.66초, SSE 전체 P95 6.39초. 모두 목표 충족
  > **P95 목표 재설정 (2026-08-01)**: LLM 을 Gemini → Ollama `gemma4:e4b` 로 전환하여
  > 절대 응답 시간이 1~3초 → 11~16초로 증가. SSE 토큰 스트리밍으로 체감 레이턴시를 개선.
  > **새 목표: 스트리밍 첫 토큰 P95 3초 이내, 전체 응답 P95 20초 이내.** 2026-08-06 기준 첫 토큰 P95 2.66초, 전체 P95 6.39초로 **둘 다 충족**했습니다. 목표 재설정도 하드웨어 투자도 필요하지 않았습니다. 원인은 프리필이 아니라 `gemma4` 의 사고 단계였습니다(`docs/design/sse_first_token_20260805.md`).
- [x] 재학습 end-to-end 검증 (데이터→학습→평가→배포 전 주기) — 용역 917,629행 학습, Champion 승격, API 비교, 백업 롤백까지 검증
- [ ] 크로스 플랫폼 실행 검증 (macOS 완료 / Windows CI 3개 작업 통과 / Windows Docker Desktop 실기 검증 대기)
- [ ] 컷오버 + 사후 모니터링

### 2026-08-06 로드맵 실사

표시와 실제가 어긋난 항목이 있어 코드·DB 를 직접 확인하고 정정했습니다. 정정 내역은 위 각 항목의 주석에 있습니다.

| 확인 항목 | 방법 | 결과 |
| --- | --- | --- |
| Alembic 도입 | `alembic current` | 리비전 8개, head 단일 |
| 원본 마이그레이션 이력 | `django_migrations` 조회 | 54행 보존 |
| 스키마 정합성 | `scripts/check_schema_drift.py` | 실질 차이 0건 |
| 주간 재학습 크론 | `src/tasks/worker.py` | 월 03:00 배선됨 |
| 레지스트리 champion | `ml_registry` 탐색 | 1개만 등록 (4개 아님) |

**컷오버를 막는 조건은 Windows 호스트 Docker Compose 실기 검증 하나만 남았습니다.** 나머지 성능·무손실·재현 조건은 모두 충족했습니다.

#### 운영 DB 에 남은 분석 잔여물

관리 밖 테이블 18개를 확인했습니다. 16개는 Django 잔존 테이블(`auth_*`, `django_*`, `account_*`, `socialaccount_*`)이고 G1 원칙상 보존 대상입니다. `alembic_version` 은 정상입니다.

나머지 하나였던 `servc_inst_verify` 는 **2026-08-06 담당자 승인으로 삭제했습니다.**

| 테이블 | 행 수 | 크기 | 출처 | 조치 |
| --- | ---: | ---: | --- | --- |
| `servc_inst_verify` | 1,033,106 | 553.1 MB (데이터 509.0 + 인덱스 44.1) | `scripts/verify_servc_institution.py` 의 작업 테이블 | 2026-08-06 `DROP TABLE` |

일회성 분석 스크립트가 만든 중간 산출물이며 업무 데이터가 아닙니다. ORM·백업 매니페스트·`verify_migration.py` 검증 대상 어디에도 없어 G1 영향이 없습니다. 삭제 후 `verify_migration.py` 4/4 통과를 확인했습니다.

재생성이 필요하면 `scripts/verify_servc_institution.py` 를 다시 실행하십시오. 스크립트가 `DROP TABLE IF EXISTS` 후 테이블과 인덱스 2종(`ix_v_dt`, `ix_v_lwlt`)을 스스로 만듭니다.

---

## 9. 위험 관리

| 위험 | 확률 | 영향 | 완화 |
|------|------|------|------|
| 마이그레이션 중 데이터 손실 | 중 | **치명적** | 풀 덤프 + 자동 검증 + 롤백 계획 (G1 최우선) |
| ORM 전환 시 스키마 불일치 | 중 | 높음 | 테이블/컬럼명 100% 유지, 타입 변경 금지 |
| FastAPI 전환 공수 과대 | 중 | 중 | 점진적 이행, 필요 시 Django ASGI 대안 |
| ML 가중치 비호환 | 낮 | 중 | 체크섬 + 회귀 테스트 |
| 크로스플랫폼 의존성 누락 | 중 | 중 | Docker 표준화 + CI에서 Windows/macOS 매트릭스 테스트 |
| 성능 개선 미달 | 낮 | 중 | Phase 7 벤치마크로 조기 검증 |
| **재학습 후 성능 저하** | **중** | **높음** | **Champion/Challenger 게이트, 새 모델이 기존 압도 시에만 승격, 즉시 롤백** |
| **Train/Serve 특징 불일치 잔존** | **중** | **높음** | **단일 특징 함수 + 스키마 검증 + 학습/추론 패리티 테스트** |
| **재학습 모델 배포로 예측 정합성 붕괴** | 낮 | **높음** | **카나리 배포 + 메타데이터 검증 + E2E 회귀** |

---

## 10. 확정된 아키텍처 결정 사항 (Signed-Off)

본 프로젝트의 기술 스택 및 MLOps 운영 방침은 다음 7가지 아키텍처 결정으로 최종 확정되었다 (2026-07-31 확정):

1. **백엔드 프레임워크**: **FastAPI (ASGI)** — I/O 비동기화, Pydantic v2, Swagger 자동화
2. **로컬/운영 DB**: **Docker MySQL 8** — DB 이중화 제거, 스키마/데이터 100% 통일 (G1, G2)
3. **태스크 큐**: **Arq (asyncio + Redis)** — 초경량 FastAPI 친화적 비동기 태스크 큐
4. **벡터 DB**: **ChromaDB 유지** — 원본 `bidding_kb` 1개 컬렉션 스냅샷 무결성 및 데이터 보존 최우선 (G1)
5. **ML 가중치 저장**: **외부 스토리지 / 독립 볼륨** — Git LFS 대신 저장소 경량화 및 핫스왑 지원
6. **재학습 주기**: **PSI 드리프트 감지 동적 주기** — 입력 분포(PSI > 0.2) 검출 시 자동 발화
7. **Champion 전환**: **하이브리드 게이트** — 자동 평가지표 검증 후 1-Click 승인/승격

---

_본 설계서는 확정된 아키텍처 결정을 바탕으로 구현을 진행합니다._
