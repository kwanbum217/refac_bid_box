# refac_bid_box Antigravity 핵심 규칙 (요약본)

> **작성일**: 2026-07-31
> **버전**: v0.1.0
> 본 파일은 AGENTS.md 정본의 핵심 행동 규칙을 압축한 요약본입니다 (12,000자 이내).
> 충돌 시 AGENTS.md 정본이 우선합니다.

---

## 1. 비협상 원칙 및 확정 스택

- **데이터 무손실**: 기존 DB 테이블/컬럼명·타입 변경 금지, ChromaDB 유지.
- **Train/Serve 특징 단일화**: 특징 생성은 `src/ml/features.py` 단일 함수만 사용.
- **크로스 플랫폼**: macOS/Windows Docker + Makefile 동일 환경 (FastAPI + Arq + MySQL 8 + Redis).
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
7. `main` 브랜치에서 직접 작업·커밋 (병합은 작업 브랜치를 거칠 것)
8. Pull Request 생성 (1인 작업이므로 불필요)
9. 마이그레이션 검증 없이 다음 Phase 진행

---

## 4. Git 전략 및 브랜치 규칙

본 저장소는 1인 작업입니다. Pull Request 절차를 두지 않습니다.

- **Pull Request 를 만들지 않습니다.** 작업 브랜치에서 커밋·푸시 후 담당자 확인을 거쳐 `main` 에 직접 병합합니다.
- `main` 에서 직접 작업하지 않습니다. 변경은 항상 작업 브랜치에서 시작합니다.
- 병합은 `git merge --no-ff` 로 수행합니다.
- 커밋 메시지: `type: subject` 형식 (`feat`, `fix`, `docs`, `refactor`, `chore`, `test`, `ci`).

---

## 5. Orca 다중 섹션 조율

- 다른 섹션과 같은 파일·브랜치·작업 트리를 다루거나, 병합 대기, 검증 의존성, Docker/DB/대량 색인/ML 학습 공유 자원이 있으면 `.agents/skills/orca-section-coordination/SKILL.md`를 먼저 읽습니다. 겹치는 것이 없는 독립 작업은 대상이 아닙니다.
- Orca Run과 Task에 작업·의존성·자원 소유자를 등록하고, `worker_done` 및 검증 결과 전에는 후속 섹션을 시작하지 않습니다.
- 배정은 코디네이터 토큰을 기준으로 정합니다. 큰 분석·감사·측정 보고서는 위임하고, 긴 측정 실행과 짧은 판정 문서는 직접 합니다. 검증·병합 판정·게이트 기준 제정은 위임하지 않습니다. 주력 워커는 Antigravity Gemini Flash 입니다.
- Dispatch 직후 `orca terminal read`로 워커가 지시를 실제로 받았는지 확인합니다. `dispatch --inject`의 `ok: true`, Task의 `dispatched` 상태, 프로세스 생존은 진척의 근거가 아닙니다.
- 터미널 출력이나 구두 보고만으로 완료·병합·시작 가능을 선언하지 않습니다. 같은 브랜치·작업 트리·공유 자원에 동시 쓰기를 배정하지 않습니다.

---

## 6. 스킬 인덱스

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
| `servc-model-tuning` | 상시 | `.agents/skills/servc-model-tuning/` | 용역 모델 성능 개선. 기각 목록, 쌍대 검정 기준, 측정 함정 |
| `project-orchestrator` | 운영 | `.agents/skills/project-orchestrator/` | 컨테이너 시동, 헬스체크, 무손실 검증, 레이턴시 벤치마크 자동화 |
| `git-workflow` | 공통 | `.agents/skills/git-workflow/` | 브랜치 전략, 커밋 컨벤션, 1인 main 병합 (PR 없음) |
| `orca-section-coordination` | 공통 | `.agents/skills/orca-section-coordination/` | Orca Run·Task·Dispatch 기반 섹션 의존성 및 완료 검증 |

---

## 7. 재학습 (핵심 MLOps)

- train/serve skew 해소: 단일 `features.py` 사용 (`DEFAULT_INST_RATE` 하드코딩 제거).
- Champion/Challenger 게이트: 신규 모델이 기존 모델을 성능(RMSE/MAPE/R²)으로 압도할 때만 승격.
- `ml_registry/` 버저닝 및 PSI 기반 드리프트 모니터링.

---

## 8. 문서화 표준

- 마크다운 위계(`#`/`##`/`###`), 구분선(`---`), 표 우선, Mermaid 다이어그램, 메타데이터 블록(`>`) 준수.
