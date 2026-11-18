# 핸드오프 인수인계 - 2026-11-18 행안부 학술 띠 구판 등록

> **작성일**: 2026-11-18
> **작성**: 코디네이터(Claude Opus 5.5). Orca Run `run_b68a3b16b660`
> **기준 커밋**: 이 문서 병합 직전 `main` 은 `ee0a8536` 이다.
> **이전 문서**: [`handoff_20261118e_band_lnf.md`](handoff_20261118e_band_lnf.md) 의 0절은 이 문서 0절로 대체합니다.

---

## 0. 다음 세션이 바로 할 일

| 우선 | 과업 | 방법 |
| --- | --- | --- |
| 1 | 이 병합 커밋의 CI 확인 | 규칙 변경이 들어갔다 |
| 2 | 부산 `R25BK01244020` 단순노무 기록 | 사용자 승인. 공고 단건 선택 저장 경로가 코드에 없어 설계 필요 |
| 3 | 2024-07-01 이전 행안부 학술 띠 공고 | 제283호 이전 판본이 필요하면 같은 방식으로 원문 조사 |
| 4 | 그 밖의 구판본(경기·부산·경북 40, 기관 19) | 사용자 결정 '구판본 등록 후 계산' 의 나머지 묶음 |
| 5 | cmd 크레딧 | 소진. 대체는 Antigravity Gemini·Claude, Cursor CLI. Gemini Flash 는 2026-11-18 서버 용량 부족(503)이 잦았다 |
| 6 | `R26BK01727058` 자동 회수 확인, 재학습 판정(11-23), 노출 지연 2차 측정(11-25) | 이전 문서 그대로 |

---

## 1. 이 병합에 들어간 것

| 브랜치 | 내용 | 검증 |
| --- | --- | --- |
| `orca-mois-old` | `docs/analysis/mois_academic_band_old_versions_20261118.md`. 행안부 예규 제283호(시행 2024-07-01~2025-06-30) [별표 4] 학술연구용역 세 열 값이 현행 제325호와 같음을 원문으로 확정, 70건 매핑 | 빌더 Antigravity Claude, Cursor 리뷰 pass(law.go.kr 원문 재현) |
| `orca-mois-apply` | 구판 규칙 `SERVC_LOCAL_MOIS_ACADEMIC_20240701_*` 3종 등록, 학술 제외 시·도의 학술 공고 GENERAL 폴백을 행안부 학술 띠로 정정 | 빌더 Antigravity Claude, Cursor 리뷰 pass, L1 pass, 판정 비교 코디네이터 재현(내용 변경 53 건) |

---

## 2. 운영 메모

| 항목 | 내용 |
| --- | --- |
| 리뷰어 Cursor | 라우터 키 `cursor-auto` 의 id `cursor-agent/auto` 는 CLI 가 모른다. `worker-start --agent cursor --model auto` 로 띄운다. taskctl dispatch 는 `path:` 워크트리에 `--repo` 를 붙여 거부되므로 worker-start 를 직접 부른다 |
| Antigravity 승인 대화창 | 허용 목록 밖 명령(mktemp, curl 등)은 감시기가 넘기지 않는다. 코디네이터가 위험 명령·외부 도메인·임시 경로 밖 쓰기를 거르는 판정기로 승인했다 |
| 코디네이터 토큰 | 사용자 주간 한도 2% 남음 알림 뒤 남은 단계를 배경 스크립트 하나로 묶어 진행했다 |
