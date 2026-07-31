# refac_bid_box 문서 인덱스

> **작성일**: 2026-07-31
> **버전**: v0.1.0
> **상태**: 리팩토링 설계 단계
> **적용 범위**: 기존 `bid_box` (Django 5.1.6) → `refac_bid_box` 전환 전체

---

## 문서 목록

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| **리팩토링 설계서** | [`design/REFACTORING_DESIGN.md`](design/REFACTORING_DESIGN.md) | 전체 리팩토링 청사진. 데이터 무손실·크로스플랫폼·스택 최적화 + 재학습 파이프라인 |

---

## 폴더 구조

```
docs/
├── README.md              # 본 파일 (마스터 인덱스)
├── design/                # 핵심 시스템 설계서 (아키텍처, 리팩토링 설계)
├── phase-guides/          # 이행 단계별(Phase 0~7) 상세 설계서
├── migration/             # 데이터 무손실 마이그레이션 절차서
├── research/              # 기술 조사, 스택 비교, 타당성 검토
├── ops/                   # 운영/환경/배포/테스트 가이드
├── security/              # 보안 기준 및 시크릿 관리
├── dev-guides/            # 코딩 표준, 협업 워크플로
├── changelogs/            # 작업 이력 (이니셜별 누적)
└── handoff/               # 세션 인수인계서
```

---

## 1. design/ — 핵심 시스템 설계서

> 시스템 전체 구조와 리팩토링 방향성을 정의하는 최상위 설계 문서입니다.

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| **리팩토링 설계서** | [`REFACTORING_DESIGN.md`](design/REFACTORING_DESIGN.md) | AS-IS 분석, TO-BE 스택, 타겟 아키텍처, 재학습 파이프라인, 이행 로드맵 |

## 2. phase-guides/ — 이행 단계별 상세 설계서

> 리팩토링 설계서 8장의 Phase 0~7 단계를 각각 개별 문서로 전개합니다. 각 문서는 범위·파일목록·검증기준을 명시합니다.

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| Phase 0 — 기반 정비 | [`phase0_foundation_design.md`](phase-guides/phase0_foundation_design.md) | uv, Makefile, Dockerfile, CI |
| Phase 1 — 데이터 보존 | [`phase1_data_preservation_design.md`](phase-guides/phase1_data_preservation_design.md) | DB 덤프, 가중치 검증, ChromaDB 백업 |
| Phase 2 — 인프라 | [`phase2_infrastructure_design.md`](phase-guides/phase2_infrastructure_design.md) | ORM 이식, Redis, 태스크 큐 |
| Phase 3 — 애플리케이션 | [`phase3_application_design.md`](phase-guides/phase3_application_design.md) | 백엔드 이식, 파일 분할, 비동기화 |
| Phase 4 — ML 추론/RAG | [`phase4_inference_rag_design.md`](phase-guides/phase4_inference_rag_design.md) | 싱글톤 로드, 가중치 외부화 |
| **Phase 5 — 재학습** | [`phase5_retraining_design.md`](phase-guides/phase5_retraining_design.md) | 특징 함수, 데이터셋 빌더, 학습기, 레지스트리 |
| Phase 6 — 프론트엔드 | [`phase6_frontend_design.md`](phase-guides/phase6_frontend_design.md) | 스트리밍, HTMX (선택) |
| Phase 7 — 검증/컷오버 | [`phase7_validation_cutover_design.md`](phase-guides/phase7_validation_cutover_design.md) | E2E, 벤치마크, 크로스플랫폼 검증 |

## 3. migration/ — 데이터 무손실 마이그레이션 절차서

> 기존 DB·가중치·벡터DB의 무손실 이행을 위한 실행 가능한 절차서입니다. (설계서 5장 참조)

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| DB 마이그레이션 런북 | [`db_migration_runbook.md`](migration/db_migration_runbook.md) | MySQL 덤프→복원→검증→롤백 |
| ML 가중치 검증 | [`ml_weights_verification.md`](migration/ml_weights_verification.md) | 4개 모델 체크섬·회귀 테스트 |
| ChromaDB 백업/검증 | [`chromadb_backup.md`](migration/chromadb_backup.md) | 19개 컬렉션 무결성 검증 |

## 4. research/ — 기술 조사

> 스택 결정을 위한 비교·타당성 검토 문서입니다. (설계서 3장·10장과 연동)

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| 백엔드 프레임워크 비교 | [`backend_framework_comparison.md`](research/backend_framework_comparison.md) | FastAPI vs Django ASGI |
| 태스크 큐 비교 | [`task_queue_comparison.md`](research/task_queue_comparison.md) | Celery vs Arq |
| 벡터DB 비교 | [`vector_db_comparison.md`](research/vector_db_comparison.md) | ChromaDB vs Qdrant |
| Train/Serve Skew 분석 | [`train_serve_skew_analysis.md`](research/train_serve_skew_analysis.md) | 하드코딩 상수 문제와 해결 |

## 5. ops/ — 운영/환경/배포

> 개발·운영 환경 구성과 테스트 절차를 정의합니다.

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| 환경변수 명세 | [`environment_variables.md`](ops/environment_variables.md) | 전체 환경변수 단일 명세 |
| 배포 가이드 | [`deployment_guide.md`](ops/deployment_guide.md) | Docker Compose 전체 스택 |
| 크로스플랫폼 가이드 | [`cross_platform_guide.md`](ops/cross_platform_guide.md) | macOS/Windows 호환 |
| Git 브랜치 전략 | [`git_branching_strategy.md`](ops/git_branching_strategy.md) | 브랜치/커밋 규칙 |
| 테스트 명세 | [`test_specification.md`](ops/test_specification.md) | 검증 매트릭스, KPI |

## 6. security/ — 보안 기준

> 시크릿 관리와 보안 강화 방침입니다. 실제 비밀값은 기록하지 않습니다.

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| 보안 문서 인덱스 | [`README.md`](security/README.md) | 보안 원칙, 금지 정보 |
| 보안 강화 가이드 | [`security_hardening_guide.md`](security/security_hardening_guide.md) | 기존 취약점(평문 키, 약한 검증기) 개선 |

## 7. dev-guides/ — 코딩 표준

> 팀 코딩 컨벤션과 협업 워크플로입니다.

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| LLM 협업 워크플로 | [`llm_collaboration_workflow.md`](dev-guides/llm_collaboration_workflow.md) | 담당자 작성 vs LLM 보조 분담 |
| 문서화 규칙 | [`documentation_rules.md`](dev-guides/documentation_rules.md) | Markdown/Mermaid/메타데이터 규칙 |

## 8. changelogs/ — 작업 이력

> 작업 단위로 이니셜 파일에 changelog 엔트리를 하단에 누적합니다.

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| Changelog 안내 | [`README.md`](changelogs/README.md) | 기록 방식 |
| 엔트리 템플릿 | [`TEMPLATE.md`](changelogs/TEMPLATE.md) | 표준 양식 |

## 9. handoff/ — 세션 인수인계서

> 작업 중단/인계 시 `YYYY-MM-DD_주제_handoff.md` 형식으로 작성합니다.

---

## 권장 독해 순서

신규 참여자(또는 AI 에이전트)는 아래 순서로 문서를 읽습니다.

1. [`README.md`](../README.md) (프로젝트 루트)
2. [`SKILLS.md`](../SKILLS.md) (에이전트 작업 규칙)
3. [`design/REFACTORING_DESIGN.md`](design/REFACTORING_DESIGN.md) (전체 설계)
4. [`migration/db_migration_runbook.md`](migration/db_migration_runbook.md) (데이터 보존)
5. [`phase-guides/phase5_retraining_design.md`](phase-guides/phase5_retraining_design.md) (재학습, 핵심 추가)
6. [`ops/environment_variables.md`](ops/environment_variables.md) (환경)
7. [`ops/cross_platform_guide.md`](ops/cross_platform_guide.md) (크로스플랫폼)

---

## 현재 문서 기준선 (비협상 원칙)

1. **데이터 무손실 최우선**: 모든 변경은 기존 DB 행 수·스키마 100% 보존을 전제로 한다.
2. **Train/Serve 특징 단일화**: 학습·추론 특징 생성은 단일 함수(`features.py`)를 사용한다.
3. **크로스 플랫폼**: macOS/Windows 모두 Docker + Makefile 단일 명령으로 실행 가능해야 한다.
4. **시크릿 비기록**: `.env` 실제 값은 어떤 문서에도 기록하지 않는다.
5. **점진적 이행**: 빅뱅 교체 없이 단계별(Phase) 전환한다.

---

## 결정 보류 사항 (구현 착수 전 확인)

> 상세는 [`design/REFACTORING_DESIGN.md`](design/REFACTORING_DESIGN.md) 10장 참조

1. 백엔드 프레임워크: FastAPI vs Django ASGI
2. 로컬 DB: Docker MySQL vs SQLite
3. 태스크 큐: Celery vs Arq
4. 벡터DB: ChromaDB vs Qdrant
5. ML 가중치 저장: Git LFS vs 외부 스토리지
6. 재학습 주기: 주간 고정 vs 드리프트 감지 동적
7. Champion 전환: 자동 승격 vs 수동 승인

---

_본 인덱스는 살아있는 문서입니다. 문서 추가/변경 시 본 표를 갱신합니다._
