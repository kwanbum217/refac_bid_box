# refac_bid_box

공공조달 입찰 데이터 수집·분석 + 하이브리드 RAG 챗봇 + AI 낙찰가 예측 플랫폼의
리팩토링 저장소입니다.

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
| G2 | 크로스 플랫폼 (macOS / Windows) | macOS 완료 | 양대 OS | 부분 완료 | Windows Docker Desktop 실기 검증 잔여 |
| G3 | 성능 지표 (예측 API, SSE) | 항목별 실측 | 항목별 기준 | **항목별 판정** | [`docs/context/CURRENT_STATE.md`](docs/context/CURRENT_STATE.md) 2장 |

> **G3 실측값은 이 표에 두지 않습니다.** 레이턴시 지표는 측정마다 바뀌므로 정본은
> [`docs/context/CURRENT_STATE.md`](docs/context/CURRENT_STATE.md) 이며, 측정 조건은
> [`docs/ops/latency_gate_protocol.md`](docs/ops/latency_gate_protocol.md) 규약을 따릅니다.
> README 에 수치를 복사해 두면 실측이 갱신될 때마다 뒤처져 워커에게 틀린 사실을
> 주입합니다. **수치뿐 아니라 통과·미달 같은 판정 문구도 두지 않습니다.**
> 2026-08-15 에 수치 3행을 포인터로 대체했으나 판정 문구가 남아, 정본이 예측 API
> 통과로 바뀐 뒤에도 README 는 2026-08-16 까지 미달로 표시했습니다.
> **G3 는 일괄 통과로 선언하지 않고 항목별로 판정합니다.**

자세한 내용은 [`docs/design/REFACTORING_DESIGN.md`](docs/design/REFACTORING_DESIGN.md)와 [`docs/handoff/2026-08-14_gpt_analysis_verification.md`](docs/handoff/2026-08-14_gpt_analysis_verification.md)를 참고하세요.

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

# 전체 Docker 스택 시동 (앱·Arq·MySQL·Redis)
make up

# 로컬 코드만 FastAPI로 실행할 때
make dev
```

Docker 앱·워커 이미지는 소스와 의존성만 포함합니다. 데이터셋, 모델 레지스트리,
ChromaDB 색인은 `docker-compose.yml`의 호스트 볼륨으로 제공하므로 첫 이미지 빌드에
포함되지 않습니다.

기본 Compose 워커는 매일 02:00 KST에 개발 DB 수집·KB·집계 최신화를 실행합니다.
KB는 최근 24시간 적재분만 멱등 upsert하므로 50만 건 전체를 재색인하지 않습니다.
예측 검증과 재학습은 운영 전용 스케줄로 분리되어 기본값에서 실행하지 않습니다.

## 문서

- [문서 인덱스](docs/README.md)
- [리팩토링 설계서](docs/design/REFACTORING_DESIGN.md)
- [프론트엔드 결정](docs/design/FRONTEND_DECISION.md)
- [SKILLS.md](SKILLS.md) / [AGENTS.md](AGENTS.md)

---

_리포지토리: https://github.com/kwanbum217/refac_bid_box_
