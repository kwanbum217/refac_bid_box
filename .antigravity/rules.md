# refac_bid_box Antigravity 핵심 규칙 (요약본)

> **작성일**: 2026-07-31
> **버전**: v0.1.0
> 본 파일은 AGENTS.md 정본의 핵심 행동 규칙을 압축한 요약본입니다 (12,000자 이내).
> 충돌 시 AGENTS.md 정본이 우선합니다.

---

## 1. 비협상 원칙

- **데이터 무손실**: 기존 DB 테이블/컬럼명·타입 변경 금지.
- **Train/Serve 특징 단일화**: 특징 생성은 `src/ml/features.py` 단일 함수만 사용.
- **크로스 플랫폼**: macOS/Windows Docker + Makefile 동일 환경.
- **시크릿 비기록**: `.env` 실제 값은 문서/코드에 노출 금지.

---

## 2. 코딩 규칙

- 대화 응답과 아티팩트는 한국어(존댓말). 코드/변수명/환경변수명은 영어.
- 문서, 코드 주석, 커밋 메시지에 이모지 사용 금지.
- 프로젝트 루트 기준 상대 경로 사용.

---

## 3. 금지 행위

1. 코드 주석, 커밋 메시지, 문서 내 이모지 사용
2. 영어로 대화 응답이나 아티팩트 작성 (코드/변수명 제외)
3. 사전 허가 없이 새로운 Python 라이브러리 추가
4. `.env` 파일의 실제 값을 코드나 문서에 노출
5. 기존 DB 테이블/컬럼명·타입 변경 (데이터 무손실 원칙 위반)
6. 학습·추론 특징 생성 로직을 분리하여 작성 (train/serve skew 유발)
7. `main` 브랜치에 직접 push
8. 마이그레이션 검증 없이 다음 Phase 진행

---

## 4. Git 전략 및 브랜치 규칙

- `main` 브랜치에 직접 push 금지. 항상 브랜치 → PR.
- 커밋 메시지: `type: subject` 형식 (`feat`, `fix`, `docs`, `refactor`, `chore`, `test`, `ci`).

---

## 5. 스킬 인덱스

| 스킬명 | Phase | 경로 | 주요 기능 |
| --- | --- | --- | --- |
| `foundation-setup` | Phase 0 | `.agents/skills/foundation-setup/` | uv, Makefile, Docker, CI, 린터 설정 |
| `data-preservation` | Phase 1 | `.agents/skills/data-preservation/` | DB 덤프, 가중치 체크섬, ChromaDB 백업 |
| `infrastructure-setup` | Phase 2 | `.agents/skills/infrastructure-setup/` | DB ORM 이식, Redis 캐시, 비동기 태스크 큐 |
| `application-migration` | Phase 3 | `.agents/skills/application-migration/` | 백엔드 API 이식, 거대 모듈 분할, async/await |
| `inference-rag-opt` | Phase 4 | `.agents/skills/inference-rag-opt/` | 싱글톤 로드, 가중치 외부화, RAG 캐싱 |
| `retraining-pipeline` | Phase 5 | `.agents/skills/retraining-pipeline/` | 단일 특징 features.py, trainer, ml_registry, PSI 모니터링 |
| `frontend-streaming` | Phase 6 | `.agents/skills/frontend-streaming/` | SSE/WebSocket 스트리밍, HTMX 동적 UI |
| `validation-cutover` | Phase 7 | `.agents/skills/validation-cutover/` | E2E, P95 레이턴시 벤치마크, 크로스플랫폼 컷오버 |
| `git-workflow` | 공통 | `.agents/skills/git-workflow/` | 브랜치 전략, 커밋 컨벤션, PR 템플릿 |

---

## 6. 재학습 (핵심 MLOps)

- train/serve skew 해소: 단일 `features.py` 사용 (`DEFAULT_INST_RATE` 하드코딩 제거).
- Champion/Challenger 게이트: 신규 모델이 기존 모델을 성능(RMSE/MAPE/R²)으로 압도할 때만 승격.
- `ml_registry/` 버저닝 및 PSI 기반 드리프트 모니터링.

---

## 7. 문서화 표준

- 마크다운 위계(`#`/`##`/`###`), 구분선(`---`), 표 우선, Mermaid 다이어그램, 메타데이터 블록(`>`) 준수.
