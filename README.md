# refac_bid_box

공공조달 입찰 데이터 수집·분석 + 하이브리드 RAG 챗봇 + AI 낙찰가 예측 플랫폼의
리팩토링 저장소입니다. 협상에의한계약 공고는 가격점수를 계산하지 않고 평가비율과 낙찰률 참고 분포를 제공합니다.

> 기존 프로젝트(`bid_box`, Django 5.1.6 모놀리식)를 레이턴시·정합성·크로스 플랫폼
> 호환성(macOS / Windows)·데이터 무손실 마이그레이션 관점에서 재설계합니다.

## 상태

**Phase 7 컷오버 검증 중** — G1 데이터 무손실은 통과했고, G2 Windows 실기
검증이 남았습니다. G3 는 일괄 판정하지 않으며 항목별 현재 상태는
[`docs/context/CURRENT_STATE.md`](docs/context/CURRENT_STATE.md) 1장이 정본입니다.

| Phase | 상태 | 비고 |
| --- | --- | --- |
| Phase 0 | 완료 | uv, Docker, Makefile, 스킬 시스템 |
| Phase 1~3 | 완료 | 데이터 자산 보존, ORM/API 이식 |
| Phase 4~6 | 완료 | 추론·RAG·재학습·스트리밍 경로 구축 |
| Phase 7 | 부분 완료 | G1 통과, G2 Windows 실기 검증 잔여, G3 항목별 판정([`CURRENT_STATE.md`](docs/context/CURRENT_STATE.md) 1장) |

### Phase 7 검증 세부 현황

| 목표 | 세부 항목 | 현재 실측 | 목표치 | 판정 | 근거 |
| --- | --- | ---: | ---: | --- | --- |
| G1 | DB 스키마·행 수·가중치 보존 | 100% 무손실 | 100% | 통과 | `scripts/verify_migration.py` |
| G2 | 크로스 플랫폼 (macOS / Windows) | macOS 완료 | 양대 OS | 보류 | Windows Docker Desktop 실기 검증 잔여 |
| G3 | 성능 지표 (예측 API, SSE) | 항목별 실측 | 항목별 기준 | **항목별 판정** | [`docs/context/CURRENT_STATE.md`](docs/context/CURRENT_STATE.md) 2장 |

> **G3 실측값은 이 표에 두지 않습니다.** 레이턴시 지표는 측정마다 바뀌므로 정본은
> [`docs/context/CURRENT_STATE.md`](docs/context/CURRENT_STATE.md) 이며, 측정 조건은
> [`docs/ops/latency_gate_protocol.md`](docs/ops/latency_gate_protocol.md) 규약을 따릅니다.
> README 에 수치를 복사해 두면 실측이 갱신될 때마다 뒤처져 워커에게 틀린 사실을
> 주입합니다. **수치뿐 아니라 통과·미달 같은 판정 문구도 두지 않습니다.**
> 2026-08-15 에 수치 3행을 포인터로 대체했으나 판정 문구가 남아, 정본이 예측 API
> 통과로 바뀐 뒤에도 README 는 2026-08-16 까지 미달로 표시했습니다.
> **G3 는 일괄 통과로 선언하지 않고 항목별로 판정합니다.**

자세한 내용은 [`docs/design/REFACTORING_DESIGN.md`](docs/design/REFACTORING_DESIGN.md)와 [`docs/archive/handoff/2026-08/2026-08-14_gpt_analysis_verification.md`](docs/archive/handoff/2026-08/2026-08-14_gpt_analysis_verification.md)를 참고하세요.

## 주요 목표

- **데이터 무손실 마이그레이션**: 기존 DB 스키마·저장 데이터·ML 모델 가중치 보존
- **크로스 플랫폼 호환**: macOS / Windows 동일 환경에서 개발·실행 가능
- **기술 스택 최적화**: 레이턴시·정합성 관점에서 효율적인 스택 적용

## 기술 스택 (확정)

| 영역 | 기술 | 비고 |
| --- | --- | --- |
| 백엔드 | FastAPI (ASGI) | 비동기 I/O, Pydantic v2, Swagger 자동화 |
| DB | MySQL 8 (Docker) | 이중화(SQLite fallback) 제거, 스키마 100% 보존 |
| 캐시/브로커 | Redis | 파일/locmem 캐시 대체 |
| 검색 엔진 | Meilisearch | Compose 필수 서비스. `MEILI_ENABLED`로 제어, 공고·낙찰 목록 읽기 모델 전용 |
| 태스크 큐 | Arq (asyncio + Redis) | 경량 비동기 태스크 큐 |
| ML | LightGBM, CatBoost, scikit-learn | 기존 스택 유지 |
| 벡터DB | ChromaDB (유지) | 원본 `bidding_kb` 1개 컬렉션 스냅샷 보존 최우선 (G1) |
| LLM | Ollama gemma4:e2b (기본), Google Gemini (대체/선택) | 의도 분류, 요약, RAG |
| 패키지 관리 | uv + pyproject.toml | pip 대체 |
| 컨테이너 | Docker + docker-compose | 크로스 플랫폼 표준 (G2) |

## 주요 기능

| 기능 | 설명 | API |
| --- | --- | --- |
| 낙찰가 예측 | 공고 기반 낙찰가 예측과 예측 구간 | `POST /api/v1/predictions/predict-price` |
| 적격심사 정량평가 | 규칙 판별·가격점수 산출·통과 가능 낙찰가 구간 역산 | `POST /api/v1/evaluations/analyze` |
| 신용평가등급확인서 자동 입력 | 등급확인서 PDF 에서 등급·평가일을 뽑아 입력란을 미리 채웁니다 | `POST /api/v1/documents/extract` |
| 스캔본 OCR | 텍스트로 등급을 못 찾은 이미지 PDF 를 로컬 OCR 로 한 번 더 읽습니다 | 같은 API (OCR 토글) |
| 수기심사 직접 입력 | 수기심사 공고와 기준 미확보 공고는 B·k·기준비율·통과점수를 직접 넣어 계산합니다 | `POST /api/v1/evaluations/analyze` |

### 적격심사 규칙 범위

`src/app/services/evaluation_rules.py` 는 적격심사 산식 규칙을 규칙 ID 기준 206종으로
담고 있습니다. 표의 건수는 규칙 항목 수이고, 상수 사이에 같은 규칙 ID 가 겹쳐 252개
항목이 206종이 됩니다.

| 구분 | 규칙 상수 | 항목 수 |
| --- | --- | ---: |
| 조달청 일반용역 현행 | `POST_20260727_RULES` | 20 |
| 조달청 일반용역 개정 | `POST_20260526_RULES` | 20 |
| 조달청 일반용역 구판 | `PRE_20260526_RULES` / `PRE_20250901_RULES` / `PRE_20230501_RULES` | 56 |
| 시·도 자체 별표 | `LOCAL_RULES` | 70 |
| 기관 배점표와 구판 | `INSTITUTION_RULES` | 78 |
| 환경부 건설폐기물처리용역 | `MOE_CDW_RULES` | 6 |
| 행안부 학술연구 띠 | `MOIS_ACADEMIC_BAND_RULES` | 2 |

최근 12개월 Servc 적격심사 공고 31,305건 기준(2026-10-19 판정) 지역 규칙 1,872건,
조달청·전국 기준 19,459건, 기관 규칙 63건에 적용됐고 9,911건은 계산이 차단됩니다.
차단된 공고 가운데 지자체 기준 미확보(`LOCAL_RULE_NOT_FOUND`)와 수기심사 공고는
B·k·기준비율·통과점수를 직접 입력해 계산합니다. 근거는
[`docs/handoff/handoff_20261019_close.md`](docs/handoff/handoff_20261019_close.md) 7절입니다.

### 기능 활성화 설정

기능은 기본값이 꺼져 있습니다. 켜려면 환경 변수를 설정합니다. 전체 목록은
[`docs/ops/environment_variables.md`](docs/ops/environment_variables.md) 를 봅니다.

| 환경 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `DOCUMENT_EXTRACTION_ENABLED` | `false` | 신용평가등급확인서 PDF 추출 API 를 엽니다. 꺼져 있으면 `POST /api/v1/documents/extract` 가 404 입니다 |
| `DOCUMENT_OCR_ENABLED` | `false` | 텍스트 추출로 등급을 못 찾은 스캔본 PDF 를 로컬 OCR 로 한 번 더 읽습니다 |
| `DOCUMENT_OCR_MODEL_DIR` | `data/ocr_models` | OCR 인식 모델 파일 위치입니다. 상대 경로는 프로젝트 루트 기준입니다 |

OCR 인식 모델은 실행 중에 내려받지 않습니다. Docker 이미지는 빌드 단계에서 모델을
넣지만, 로컬 개발은 미리 받아 두십시오.

```bash
uv run python scripts/fetch_ocr_models.py
uv run python scripts/fetch_ocr_models.py --dest data/ocr_models
```

Docker 로 실행할 때 컨테이너는 `.env` 를 읽지 않으므로, `docker-compose.yml` 이 넘기는
`DOCUMENT_EXTRACTION_ENABLED` 와 `DOCUMENT_OCR_ENABLED` 로 켭니다.

## 빠른 시작

```bash
# 환경 구성
make setup

# 데이터 자산 이전 (최초 1회, bid_box 경로 필요)
make import-assets

# 코드 테스트 (외부 데이터 자산 불필요)
make test
# 무손실·모델 호환성 검증 (데이터 자산 이전 후)
make migrate-verify
make model-verify
make test-data-assets

# 전체 Docker 스택 시동 (앱·Arq·MySQL·Redis·Meilisearch)
make up

# 로컬 코드만 FastAPI로 실행할 때
make dev

# 코드 품질·정합성 일괄 검사 (lint, security, typecheck, 규칙, 워크플로)
make check-all

# 레이턴시 벤치마크
make benchmark
```

`make` 가 없는 환경(예: Windows PowerShell)에서는 같은 동작을 `uv` 명령으로 직접
실행합니다. 아래 명령은 PowerShell 에서도 그대로 실행할 수 있습니다.

| make 타깃 | uv run 대체 명령 |
| --- | --- |
| `make setup` | `uv sync --all-groups` |
| `make import-assets` | `uv run python scripts/import_data_assets.py` |
| `make test` | `uv run python -m pytest tests/ -m "not data_assets" --cov=src --cov-report=term-missing` |
| `make migrate-verify` | `uv run python scripts/verify_migration.py` |
| `make model-verify` | `uv run python scripts/verify_model_compatibility.py` |

### 의존성 버전 고정

의존성은 `uv.lock` 에 해시까지 고정됩니다. 재현 가능한 설치에는 `uv sync --frozen`
을 쓰십시오. 이 명령은 `uv.lock` 과 `pyproject.toml` 이 어긋나면 실패하므로, 고정이
깨진 상태를 조용히 넘기지 않습니다. `uv.lock` 없이 `pip install .` 로 설치하면
`pyproject.toml` 의 범위 표기(`>=`)만 적용되어 버전이 고정되지 않습니다. 이 경로에서는
`uv.lock` 에서 생성한 `constraints.txt` 로 버전을 고정합니다: `pip install -c constraints.txt .`

`make` 가 없는 Windows 환경에서의 대체 명령은 위 `빠른 시작` 의 `uv run` 표를
참조하십시오.

### 스키마 마이그레이션

`make migrate-current` 로 현재 리비전을 확인하고, `make migrate-check` 로 모델과
스키마가 어긋나지 않았는지 봅니다.

> **`make migrate-up` 은 스키마를 실제로 변경합니다.** 이 저장소의 최우선 목표는
> 데이터 무손실(G1)이며 기존 테이블·컬럼·타입은 변경 금지입니다. 실행 전
> `make migrate-verify` 로 행 수와 스키마 보존을 확인하고, 되돌릴 수 있는
> 백업이 있는지 먼저 점검하십시오. 확인 없이 운영 DB에 적용하지 마십시오.

```bash
make migrate-current   # 현재 리비전
make migrate-check     # 모델 대 스키마 정합성
make migrate-up        # 스키마 변경 (위 경고 확인 후)
```

Docker 앱·워커 이미지는 소스와 의존성만 포함합니다. 데이터셋, 모델 레지스트리,
ChromaDB 색인은 `docker-compose.yml`의 호스트 볼륨으로 제공하므로 첫 이미지 빌드에
포함되지 않습니다.

기본 Compose 워커는 매일 02:00 KST에 개발 DB 수집·KB·집계 최신화를 실행합니다.
KB는 최근 24시간 적재분만 멱등 upsert하므로 50만 건 전체를 재색인하지 않습니다.
예측 검증과 재학습은 운영 전용 스케줄로 분리되어 기본값에서 실행하지 않습니다.

## 라이선스 및 보안

- [LICENSE](LICENSE): 오픈소스 라이선스가 아니며, 사전 서면 허락 없이 복제·수정·배포·상업적 이용을 허락하지 않습니다.
- [SECURITY.md](SECURITY.md): 취약점은 공개 이슈 대신 저장소 Security 탭의 비공개 제보로 알려 주십시오.

---

## 문서

- [문서 인덱스](docs/README.md)
- [리팩토링 설계서](docs/design/REFACTORING_DESIGN.md)
- [프론트엔드 결정](docs/design/FRONTEND_DECISION.md)
- [SKILLS.md](SKILLS.md) / [AGENTS.md](AGENTS.md)

---

_리포지토리: https://github.com/kwanbum217/refac_bid_box_
