# refac_bid_box

공공조달 입찰 데이터 수집·분석 + 하이브리드 RAG 챗봇 + AI 낙찰가 예측 플랫폼의
리팩토링 저장소입니다.

> 기존 프로젝트(`bid_box`, Django 5.1.6 모놀리식)를 레이턴시·정합성·크로스 플랫폼
> 호환성(macOS / Windows)·데이터 무손실 마이그레이션 관점에서 재설계합니다.

## 상태

🚧 **리팩토링 설계 중** — 자세한 내용은 `docs/REFACTORING_DESIGN.md`를 참고하세요.

## 주요 목표

- **데이터 무손실 마이그레이션**: 기존 DB 스키마·저장 데이터·ML 모델 가중치 보존
- **크로스 플랫폼 호환**: macOS / Windows 동일 환경에서 개발·실행 가능
- **기술 스택 최적화**: 레이턴시·정합성 관점에서 효율적인 스택 적용

## 문서

- [문서 인덱스](docs/README.md) — 전체 문서 마스터 인덱스
- [리팩토링 설계서](docs/design/REFACTORING_DESIGN.md) — 전체 청사진 (데이터 무손실, 크로스플랫폼, 재학습)
- [SKILLS.md](SKILLS.md) — AI 에이전트 작업 규칙
- [AGENTS.md](AGENTS.md) — 코딩·스택·커뮤니케이션 규칙 정본

---

_리포지토리: https://github.com/kwanbum217/refac_bid_box_
