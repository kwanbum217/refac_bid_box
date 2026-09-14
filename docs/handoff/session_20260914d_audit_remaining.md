# 세션 인수인계: 2026-09-14 (넷째) 외부 감사 잔여 과업 병렬 처리

> **작성일**: 2026-09-14
> **작성자**: Claude Opus 5 (Orca 코디네이터)
> **기준 커밋**: `c9272410` (`main`), 이 문서는 ad4 병합에 함께 들어갑니다
> **이어받은 문서**: [`docs/handoff/session_20260914c_audit_fixes_and_restriction_ui.md`](session_20260914c_audit_fixes_and_restriction_ui.md)

---

## 1. 한 줄 요약

외부 감사에서 사실로 확인된 잔여 과업 다섯 건을 Orca 워커 4대(빌더)와 리뷰어 4대, 코디네이터 직접 구현 1건으로 병렬 처리해
전부 병합했습니다. backup 최소권한은 arq 큐 공유 때문에 되돌리고 선행 조건을 문서화했습니다.

---

## 2. 병합 내역 (Run `run_6ef8b7336870`)

| Task | 병합 | 내용 | 검증 |
| --- | --- | --- | --- |
| ad5 (코디네이터) | `5e65d645` | 판정 사실 원장 `updated_at` 이 최신 `decision_date` 보다 이르면 규칙 검증 실패, 원장 날짜 09-14 로 갱신 | 전량 4,758 passed, CI 성공 |
| ad3 `task_11e1b5ac7612` | `06475a02` | 릴리스 워크플로가 태그 전에 이미지 빌드, trivy 차단 판정, SPDX SBOM·이미지 ID 를 릴리스 자산으로 첨부(레지스트리 푸시 없음) | 게이트 9/9, 리뷰 결함 0, 전량 4,752 passed, CI 성공 |
| ad2 `task_7e3d526ea70d` | `f08002ec` | `rag_llm_ttft_ms`, `rag_llm_generation_ms`, `rag_llm_tokens`, `rag_llm_requests` 지표. 토큰은 백엔드가 줄 때만, 계측 예외는 삼킴 | 게이트 9/9, 리뷰 결함 0, 전량 4,756 passed, CI 성공 |
| ad1 `task_19e732e36709` | `c9272410` | 운영 `READINESS_REQUIRE_LLM=false`, app 헬스체크가 `degraded` 허용. backup 권한 축소는 되돌림 | 게이트 3 의 운영 compose 검증만 필수 환경변수 부재로 실패(가짜 값으로 별도 통과), 리뷰 결함 0, 전량 4,751 passed |
| ad4 `task_410ca46c9657` | 이 병합 | 프롬프트 인젝션 결정론적 테스트 5종, 적대적 fixture 35건(7범주 × 5), 평가 계획서. `src/` 무변경 | 게이트 9/9, 리뷰 결함 0, 전량 4,760 passed |

---

## 3. 코디네이터 판단과 정정

| 항목 | 내용 |
| --- | --- |
| ad1 계약 2 정정 | Capsule 이 LLM 실패 시 `ready` 를 요구했으나 기존 `degraded`(HTTP 200) 설계가 맞았습니다. 워커 질문으로 드러나 답변으로 정정했습니다. 실제 문제는 운영 헬스체크가 `ready` 만 받는 것이었습니다 |
| ad1 backup 권한 되돌림 | backup 은 worker 와 같은 arq `WorkerSettings`·기본 큐를 소비해 수집(외부 API)·재학습(`ml_registry` 쓰기)·크론이 떨어질 수 있습니다. egress 제거와 `:ro` 는 무작위 실패를 만들어 되돌렸고, `test_backup_keeps_worker_privileges_while_sharing_arq_queue` 가 큐 분리 전 축소를 막습니다. 선행 조건은 `docs/ops/backup_least_privilege.md` |
| ad4 범위 | `SYSTEM_PROMPT` 는 바꾸지 않았습니다. 바꾸면 blind_fixture_v2 96요청 canonical 재측정이 필요합니다. 보강 문안은 평가 계획서의 권고입니다 |
| 게이트 병렬화 | 사용자 지적으로 스킬 4.3 대로 게이트·리뷰어를 완료 즉시 병렬 실행했습니다. 겹쳐 돌린 게이트에서 오탐 0건. 직렬은 `main` 병합과 premerge 증거 기록뿐입니다 |

---

## 4. 남은 과업

| 순서 | 작업 | 선행 조건 |
| :---: | --- | --- |
| 1 | backup 전용 arq 큐 분리 후 권한 축소, 백업 전용 DB 계정 | 큐 분리 구현, DB 계정은 사용자 결정 |
| 2 | 적대적 fixture 35건 LLM 실측과 `SYSTEM_PROMPT` 보강 여부 결정 | 로컬 Ollama, 보강 시 blind_fixture_v2 재측정 |
| 3 | 릴리스 워크플로 첫 실행에서 SBOM 업로드·자산 첨부 실동작 확인 | 수동 릴리스 1회 |
| 4 | LLM 지표 운영 대시보드·알람 반영 | 운영 배포 |
| 5 | 이전 과업: 첫 야간 수집 확인, Windows 실기(G2), chromadb 재확인(2026-12-31) | - |

---

## 5. 자원 상태

| 대상 | 상태 |
| --- | --- |
| Docker | 전 서비스 실행 중. ad1·ad2 코드 반영은 `app`·`worker` 재시작 필요 |
| 워크트리 | ad1·ad2·ad3 제거 완료. ad4 는 이 병합 후 제거 |
| Orca | 빌더 4, 리뷰어 4 전원 회수. 회수 대기 0 |
