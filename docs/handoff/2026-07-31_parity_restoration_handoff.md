# 원본 재현율 복원 작업 인수인계

> **작성일**: 2026-07-31
> **브랜치**: `refactor/restore-original-parity` (커밋 7개)
> **상태**: 기능 계층 이식 완료, 테스트 스위트 및 템플릿 미이식

---

## 1. 작업 배경

기존 리팩토링본이 원본 `bid_box`와 크게 달랐습니다. 착수 시점 실측은 다음과 같았습니다.

| 영역 | 원본 | 착수 시점 | 현재 |
| --- | --- | --- | --- |
| 앱 코드 | 약 12,000 라인 | 2,476 라인 | 약 9,000 라인 |
| HTTP 엔드포인트 | 20개 | 5개 | 32개 |
| DB 데이터 | 469만 행 | **0행 (유실)** | 463만 행 복구 |

---

## 2. 데이터 유실과 복구 (가장 중요)

### 유실 경위

원본 MariaDB(`localhost:3307`, datadir `/opt/homebrew/var/mariadb_data`)가 2026-07-31에 새로
생성되면서 `bid_announcements` 1,698,014행 / `bid_results` 2,996,476행이 사라졌습니다.
유실 전 규모는 `bid_box/.django_cache/*.djcache`(zlib+pickle)를 디코딩해 확인했습니다.

| 항목 | 유실 전 (2026-06-07 스냅샷) |
| --- | --- |
| `bid_announcements` | 1,698,014행 |
| `bid_results` | 2,996,476행 |
| 낙찰 총액 | 713.16조원 |
| 평균 낙찰률 | 89.11% |

### 복구 결과

`bid_box/data/exports/*.parquet` 8개(460MB)가 DB와 동일한 컬럼 스키마여서 재적재했습니다.

| 항목 | 복구 후 | 기준선 대비 |
| --- | --- | --- |
| `bid_announcements` | 1,660,792행 | 97.8% |
| `bid_results` | 2,973,072행 | 99.2% |
| 평균 낙찰률 | **89.12%** | 사실상 일치 |

복구 스크립트: `scripts/restore_from_parquet.py` (원본 `id` 보존, 유니크 제약 기반 중복 무시,
G2B 원시 컬럼을 `raw_data` JSON 으로 복원)

### 진행 중인 백필

`cnstwk`/`servc` parquet 이 정확히 100,000행에서 잘려 있어 그 두 카테고리는 부분 복원입니다.
`scripts/backfill_from_g2b.py` 로 카테고리별 공백을 G2B API 에서 재수집 중이며, 완주에
약 8시간이 걸립니다. 중단되었다면 같은 명령을 다시 실행하면 최신 적재일 이후부터 이어서 받습니다.

```bash
python scripts/backfill_from_g2b.py            # 전체 공백 백필
python scripts/backfill_from_g2b.py --dry-run  # 구간만 확인
```

---

## 3. 발견한 조작 및 결함

다음 항목은 실제로 사실과 다르거나 검증을 무력화하고 있던 것들입니다. 재발하지 않도록 주의하십시오.

| # | 위치 | 내용 |
| --- | --- | --- |
| 1 | `src/app/api/v1/bids.py` | 가짜 공고 5건(`MOCK_BIDS`)을 하드코딩하고 DB 조회 실패를 `except: pass` 로 은폐 |
| 2 | `frontend/src/App.tsx` | 지표 카드 4종(1,420,891건 / MAPE 1.42% / P95 0.95ms / 19 컬렉션)이 전부 하드코딩 |
| 3 | `frontend/src/App.tsx` | 헬스체크 실패 시 `catch` 에서 가짜 정상 상태를 생성 |
| 4 | `scripts/verify_migration.py` | DB 검증 함수가 테이블 누락·연결 실패에도 무조건 `True` 반환 |
| 5 | `scripts/verify_migration.py` | ChromaDB 컬렉션 수를 디렉토리 개수로 계산 (실제 1개인데 19개로 보고) |
| 6 | `src/app/models/accounts.py` | 원본 `accounts_customuser` 대신 존재하지도 않는 `user_account` 테이블 정의 |
| 7 | `pyproject.toml` | `scikit-learn>=1.6.0` 상한 미지정으로 1.7+ 에서 모델 1종 역직렬화 실패 |

전부 수정 완료했습니다. 특히 4번은 "무손실 검증 통과" 보고가 나온 직접적 원인입니다.

### 원본 자체의 문제 (수정 시 판단 필요)

| 위치 | 내용 |
| --- | --- |
| `update_hybrid_kb.py:38` | `MAX_DOCUMENTS = 10` 하드코딩으로 KB 가 10건에 머물러 RAG 벡터 검색이 무력화됨 |
| `update_hybrid_kb.py` | `GEMINI_API_KEY` 를 요구하지만 임베딩에 쓰지 않음 (`_ = client`) |

전자는 `KB_MAX_DOCUMENTS` 환경변수로 조정 가능하게 하고 기본값은 원본과 동일하게 두었습니다.
후자는 Ollama 전환 후 KB 갱신이 막히지 않도록 키 요구를 제거했습니다.

---

## 4. 스택 변경 사항

| 영역 | 원본 | 현재 | 비고 |
| --- | --- | --- | --- |
| 생성 LLM | Google Gemini | **Ollama `gemma4:e4b`** | `LLM_PROVIDER=gemini` 로 원복 가능 |
| 임베딩 | ChromaDB 기본 all-MiniLM-L6-v2 | **동일 (교체 금지)** | 기존 컬렉션 정합성 |
| 자동화 실행 | Harness 파이프라인 | **Arq + Redis** | 상태 전이·응답 계약은 원본 유지 |
| 확인/콜백 토큰 | `django.core.signing` | HMAC-SHA256 | 표준 라이브러리만 사용 |
| 비밀번호 해시 | Django pbkdf2_sha256 | **동일 포맷** | 기존 계정 로그인 보장 |

Ollama 는 호스트(`localhost:11434`)에서 구동하며 컨테이너는 `host.docker.internal` 로 접근합니다.
macOS 컨테이너가 GPU(Metal)에 접근하지 못하기 때문입니다.

**응답 지연**: Gemini 1~3초 대비 Ollama 11~16초입니다. Phase 7 P95 목표 재설정이 필요합니다.

---

## 5. 실행 방법

```bash
# 의존성 (scikit-learn 은 1.6.1 고정 필수)
uv sync   # 또는 pip install -e .

# 인프라
redis-server --port 6379 --daemonize yes
ollama serve   # gemma4:e4b 필요

# 백엔드 / 워커 / 프론트
python -m uvicorn src.app.main:app --host 127.0.0.1 --port 8000
python -m arq src.tasks.worker.WorkerSettings
cd frontend && VITE_API_URL=http://127.0.0.1:8000 npm run dev

# 검증
python scripts/verify_migration.py   # 행 수 기준선 대조 포함
```

---

## 6. 남은 작업

| 우선순위 | 항목 | 원본 규모 | 비고 |
| --- | --- | --- | --- |
| 1 | 원본 테스트 스위트 이식 | 약 3,000줄 | 회귀 방지에 가장 효과적. `bid_box/apps/*/tests.py` |
| 2 | `final_inspect` 상세 점검 | 295줄 | 현재 inspect 스텝은 핵심 지표만 산출 |
| 3 | Jinja2 템플릿 12종 | — | 담당자와 후순위 합의됨 |
| 4 | G2B 백필 완주 확인 | — | 진행 중, 재실행 가능 |

`load_big_data`, `migrate_legacy_data`, `update_rag_kb` 는 각각 parquet 복원 스크립트와
`update_hybrid_kb` 이식으로 대체되어 별도 이식이 불필요합니다.

---

## 7. 커밋 이력

| 커밋 | 내용 |
| --- | --- |
| `d38321d` | 입찰 도메인 로직 복원, 가짜 목업 제거 |
| `79fdbe2` | parquet 데이터 복구, 플래너 이식 |
| `e35c684` | 챗봇 두뇌 이식, Ollama 전환 |
| `337a8b5` | 프론트 실집계 연결, 가짜 지표 제거 |
| `706672b` | 자동화 생명주기, 인증, 검증 스크립트 교정 |
| `7a16d67` | G2B 수집기, KB 구축 |
| `5b662bf` | advisory 엔진, 자동화 상태 도구 |
