# refac_bid_box

공공조달 입찰 데이터 수집·분석 + 하이브리드 RAG 챗봇 + AI 낙찰가 예측 플랫폼의
리팩토링 저장소입니다.

> 기존 프로젝트(`bid_box`, Django 5.1.6 모놀리식)를 레이턴시·정합성·크로스 플랫폼
> 호환성(macOS / Windows)·데이터 무손실 마이그레이션 관점에서 재설계합니다.

## 상태

**Phase 1~2 진행 중** — Antigravity 스캐폴드 정정 후 원본 로직 이식 단계입니다.

| Phase | 상태 | 비고 |
| --- | --- | --- |
| Phase 0 | 완료 | uv, Docker, Makefile, 스킬 시스템 |
| Phase 1 | 진행 중 | ML 가중치·ChromaDB 이전 완료, DB 덤프 대기 |
| Phase 2~3 | 진행 중 | ORM/API 골격 + predictor/rag/planner 이식 |
| Phase 4~7 | 미착수 | 실측 벤치마크·E2E 컷오버 검증 필요 |

자세한 내용은 [`docs/design/REFACTORING_DESIGN.md`](docs/design/REFACTORING_DESIGN.md)를 참고하세요.

## 주요 목표

- **데이터 무손실 마이그레이션**: 기존 DB 스키마·저장 데이터·ML 모델 가중치 보존
- **크로스 플랫폼 호환**: macOS / Windows 동일 환경에서 개발·실행 가능
- **기술 스택 최적화**: 레이턴시·정합성 관점에서 효율적인 스택 적용

## 빠른 시작

```bash
# 데이터 자산 이전 (최초 1회, bid_box 경로 필요)
python3 scripts/import_data_assets.py

# 무손실 검증
python3 scripts/verify_migration.py

# 스택 시동
make up
```

## 문서

- [문서 인덱스](docs/README.md)
- [리팩토링 설계서](docs/design/REFACTORING_DESIGN.md)
- [프론트엔드 결정](docs/design/FRONTEND_DECISION.md)
- [SKILLS.md](SKILLS.md) / [AGENTS.md](AGENTS.md)

---

_리포지토리: https://github.com/kwanbum217/refac_bid_box_
