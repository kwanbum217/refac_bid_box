---
name: project-orchestrator
description: refac_bid_box 프로젝트의 멀티 스택 도커 컨테이너(FastAPI, MySQL 8, Redis 7, React 19) 자동 시동, 헬스체크, 무손실 검증, 레이턴시 벤치마크 및 전체 품질 검사를 단일 스킬로 자동 실행할 때 호출됩니다.
---

# project-orchestrator 스킬 지침

본 스킬은 에이전트가 `refac_bid_box` 구현 및 운영 환경에서 전체 인프라를 자동으로 구동하고 검증할 수 있도록 돕는 전용 오케스트레이션 지침입니다.

## 1. 실행 명령어 순서

사용자가 "프로젝트 실행해줘", "도커 올리고 검증해줘", "구현 환경 셋업해줘" 등의 요청을 했을 때 아래 절차를 자동으로 순차 실행합니다:

```bash
# 1. 전체 컨테이너 배경 시동 (FastAPI + MySQL 8 + Redis 7 + React 19)
make up

# 2. 데이터 무손실 및 레지스트리 무결성 실측 검증
make migrate-verify

# 3. P95 레이턴시 벤치마크 실측 검증
make benchmark

# 4. 전체 단위/통합/E2E 테스트 및 다중 에이전트 규칙 검증
make test
make check-rules
```

## 2. 서비스 포트 및 접근 URL

- **FastAPI 백엔드 API**: `http://localhost:8000/docs`
- **React 19 프론트엔드 UI**: `http://localhost:5173`
- **MySQL 8 DB**: `localhost:3306` (user: `root`, db: `bid_box`)
- **Redis 7 캐시**: `localhost:6379`

## 3. 예외 및 복구 지침

- 컨테이너 포트 충돌 발생 시: `make down` 실행 후 `make up` 재시도.
- DB 연결 지연 시: 5초 대기 후 `make migrate-verify` 재실행.
