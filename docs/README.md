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
├── migration/             # 데이터 무손실 마이그레이션 절차서
├── ops/                   # 운영/환경/배포/테스트 + 다중 에이전트 셋업
├── handoff/               # 세션 인수인계서
└── changelogs/            # 통합 작업 일지 (work_log.md)
```

> 1인 리팩토링 프로젝트 실제 규모에 맞춰 간결화했습니다. 각 폴더는 실제 문서를 보유한 폴더만 유지합니다.

---

## 1. design/ — 핵심 시스템 설계서

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| **리팩토링 설계서** | [`REFACTORING_DESIGN.md`](design/REFACTORING_DESIGN.md) | AS-IS 분석, TO-BE 스택, 타겟 아키텍처, 재학습 파이프라인(7장), 이행 로드맵(8장) |

## 2. migration/ — 데이터 무손실 마이그레이션 절차서

> 기존 DB·가중치·벡터DB의 무손실 이행 절차서입니다. (설계서 5장 참조)

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| DB 마이그레이션 런북 | [`db_migration_runbook.md`](migration/db_migration_runbook.md) | MySQL 덤프→복원→검증→롤백 |
| ML 가중치·ChromaDB 검증 | [`ml_weights_verification.md`](migration/ml_weights_verification.md) | 4개 모델 체크섬·회귀 테스트, ChromaDB 19개 컬렉션 검증 |

## 3. ops/ — 운영/환경/배포

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| 환경변수 명세 | [`environment_variables.md`](ops/environment_variables.md) | 전체 환경변수 단일 명세 |
| 크로스플랫폼 가이드 | [`cross_platform_guide.md`](ops/cross_platform_guide.md) | macOS/Windows 호환 (Docker + Makefile) |
| Git 브랜치 전략 | [`git_branching_strategy.md`](ops/git_branching_strategy.md) | 브랜치/커밋 규칙 |
| 다중 에이전트 셋업 | [`multi_agent_setup.md`](ops/multi_agent_setup.md) | 5개 CLI(opencode/cursor/codex/Claude/Antigravity) 규칙 파일 매핑 |

## 4. handoff/ — 세션 인수인계서

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| 스킬 시스템 구축 인계 | [`2026-07-31_skill_system_handoff.md`](handoff/2026-07-31_skill_system_handoff.md) | 다중 에이전트 스킬 시스템 8개 구축 완료 (Phase 0~7) |

## 5. changelogs/ — 작업 일지

| 문서 | 파일 | 설명 |
| --- | --- | --- |
| 작업 변경 기록 가이드 | [`changelogs/README.md`](changelogs/README.md) | 1인 및 AI 에이전트 협업 단일 로그 작성 지침 |
| 통합 작업 일지 | [`changelogs/work_log.md`](changelogs/work_log.md) | 관범 님의 리팩토링 날짜 및 Phase별 누적 작업 일지 |


---

## 권장 독해 순서

신규 참여자(또는 AI 에이전트)는 아래 순서로 문서를 읽습니다.

1. [`README.md`](../README.md) (프로젝트 루트)
2. [`AGENTS.md`](../AGENTS.md) → [`SKILLS.md`](../SKILLS.md) (에이전트 작업 규칙)
3. [`design/REFACTORING_DESIGN.md`](design/REFACTORING_DESIGN.md) (전체 설계)
4. [`migration/db_migration_runbook.md`](migration/db_migration_runbook.md) (데이터 보존)
5. [`ops/multi_agent_setup.md`](ops/multi_agent_setup.md) (다중 에이전트)

---

## 현재 문서 기준선 (비협상 원칙)

1. **데이터 무손실 최우선**: 모든 변경은 기존 DB 행 수·스키마 100% 보존을 전제로 한다.
2. **Train/Serve 특징 단일화**: 학습·추론 특징 생성은 단일 함수(`features.py`)를 사용한다.
3. **크로스 플랫폼**: macOS/Windows 모두 Docker + Makefile 단일 명령으로 실행 가능해야 한다.
4. **시크릿 비기록**: `.env` 실제 값은 어떤 문서에도 기록하지 않는다.
5. **규칙 단일 진실 원천**: 에이전트 규칙은 `AGENTS.md`에서만 편집한다.

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
