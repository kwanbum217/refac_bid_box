# refac_bid_box

공공조달 입찰 데이터 수집·분석 + 하이브리드 RAG 챗봇 + AI 낙찰가 예측 플랫폼의
리팩토링 저장소입니다.

> 기존 프로젝트(`bid_box`, Django 5.1.6 모놀리식)를 레이턴시·정합성·크로스 플랫폼
> 호환성(macOS / Windows)·데이터 무손실 마이그레이션 관점에서 재설계합니다.

## 상태

**Phase 7 컷오버 검증 중** — G1 데이터 무손실은 통과했고, G2 Windows 실기
검증과 G3 SSE 첫 토큰 목표 결정이 남았습니다.

| Phase | 상태 | 비고 |
| --- | --- | --- |
| Phase 0 | 완료 | uv, Docker, Makefile, 스킬 시스템 |
| Phase 1~3 | 완료 | 데이터 자산 보존, ORM/API 이식 |
| Phase 4~6 | 완료 | 추론·RAG·재학습·스트리밍 경로 구축 |
| Phase 7 | 부분 완료 | G1 통과, G2 Windows 실기 검증과 SSE 목표 결정 필요 |

자세한 내용은 [`docs/design/REFACTORING_DESIGN.md`](docs/design/REFACTORING_DESIGN.md)를 참고하세요.

## 주요 목표

- **데이터 무손실 마이그레이션**: 기존 DB 스키마·저장 데이터·ML 모델 가중치 보존
- **크로스 플랫폼 호환**: macOS / Windows 동일 환경에서 개발·실행 가능
- **기술 스택 최적화**: 레이턴시·정합성 관점에서 효율적인 스택 적용

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

# 스택 시동
make dev
```

## 문서

- [문서 인덱스](docs/README.md)
- [리팩토링 설계서](docs/design/REFACTORING_DESIGN.md)
- [프론트엔드 결정](docs/design/FRONTEND_DECISION.md)
- [SKILLS.md](SKILLS.md) / [AGENTS.md](AGENTS.md)

---

_리포지토리: https://github.com/kwanbum217/refac_bid_box_
