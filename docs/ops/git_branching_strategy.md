# Git 브랜치 전략

> **작성일**: 2026-07-31
> **상태**: 설계

---

## 1. 브랜치 모델

| 브랜치 | 용도 | 보호 |
| --- | --- | --- |
| `main` | 운영 반영 가능 안정 버전 | 직접 push 금지, PR만 |
| `dev` | 통합 개발 브랜치 | PR 기반 병합 |
| `feature/*` | 개별 기능 개발 | `dev`에서 분기 |
| `phase/*` | Phase 단위 작업 | `dev`에서 분기 |
| `fix/*` | 버그 수정 | `dev` 또는 `main`에서 분기 |

---

## 2. 브랜치 명명 규칙

```
feature/retraining-trainer
phase5/retraining-pipeline
fix/db-connection-timeout
docs/migration-runbook
```

---

## 3. 커밋 메시지 규칙

형식: `type: subject`

| type | 용도 |
| --- | --- |
| `feat` | 새 기능 |
| `fix` | 버그 수정 |
| `docs` | 문서 |
| `refactor` | 리팩토링 (기능 변경 없음) |
| `chore` | 빌드, 설정, 의존성 |
| `test` | 테스트 추가/수정 |
| `ci` | CI 구성 |

예:
```
feat: add retraining trainer with LightGBM
fix: remove hardcoded DEFAULT_INST_RATE in features
docs: add phase5 retraining design
```

- 이모지 사용 금지.
- subject는 간결하게, 영어 또는 한국어 가능 (코드는 영어 권장).

---

## 4. PR 프로세스

1. `dev`에서 브랜치 분기.
2. 작업 완료 후 `dev`로 PR.
3. CI(lint + test) 통과 필수.
4. 데이터 무손실 영향 시 [`migration/`](../migration/) 검증 결과를 PR에 명시.
5. 리뷰 후 병합.
6. `dev` → `main`은 릴리스 시점에 병합.

---

## 5. 작업 완료 시

- [`changelogs/[이니셜].md`](../changelogs/TEMPLATE.md)에 엔트리 추가.
- 관련 문서 갱신 여부 확인.
