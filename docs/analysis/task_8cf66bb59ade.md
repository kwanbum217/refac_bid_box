# 익명 API 정책 및 쿼터 작업 기록

> 작업일: 2026-09-02

`POST /api/v1/chatbot/chat`, `POST /api/v1/chatbot/chat/stream`,
`POST /api/v1/chatbot/session/new`의 기존 익명 접근은 유지하면서 IP별 Redis
쿼터를 진입 시점에 적용했습니다. 인증 사용자는 쿼터에서 제외하고, Redis 장애
시에는 로그인 시도 제한과 같은 fail-open 원칙을 적용했습니다. 정책과 운영
설정은 [API 접근 정책](../ops/api_access_policy.md)에 기록했습니다.

설정 필드는 기존 `config.py`의 범위를 변경하지 않기 위해 `settings`의 선택
속성으로 읽으며, 미설정 시 60초당 30회가 적용됩니다.
