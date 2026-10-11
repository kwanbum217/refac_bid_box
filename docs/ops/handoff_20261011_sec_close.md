# 핸드오프 인수인계 — 재발주 조회 인덱스, 충남 별표 2·3·4, 회원정보 수정, 보안 검토 후속

> **작성일**: 2026-10-11
> **작성**: Claude 코디네이터 (Orca Run `run_38d15a53246a`)
> **기준 커밋**: `fe6126c7` (이 문서가 들어가는 작업 브랜치의 부모)
> **직전 인수인계**: [handoff_20261009_mypage_detail_latency_close.md](handoff_20261009_mypage_detail_latency_close.md)

---

## 0. 다음 세션이 가장 먼저 할 일

| 우선 | 과제 | 선행 |
| --- | --- | --- |
| 1 | 마지막 병합(T3) 커밋의 CI 가 원격 `main` 에서 녹색인지 확인. 새 gitleaks 이력 스캔 단계가 처음 도는 실행이다 | 없음 |
| 2 | 로그인 상태로 마이페이지, 정보 수정(`/accounts/mypage/edit/`), 공고 상세, 챗봇 답변 렌더링을 브라우저에서 확인 | 스택 기동, 계정 비밀번호(사용자) |
| 3 | 4절 보안 검토 잔여 항목(CSP, M4, M7, L14, 품질 2·3)의 처리 여부를 사용자에게 받기 | 사용자 결정 |

---

## 1. 이 세션에서 병합한 것

빌더는 모두 cmd `deepseek/deepseek-v4.1-flash`(effort high), 리뷰어는 모두 opencode `muse-spark-1.3-contributor-free` 이다. 아홉 건 모두 `--no-ff` 병합과 원격 반영을 확인했다.

| Task | 병합 | 내용 | 검증 |
| --- | --- | --- | --- |
| N1 재발주 이력 커버링 인덱스 | `9e543d6e` | `bid_results` `ix_bid_results_repeat_hist (dminstt_nm, category, rl_openg_dt, sucsf_bid_rate, bid_ntce_nm)`, 마이그레이션 `a6b7c8d9e0f1`, G1 기준선 갱신 | 리뷰 pass, 전량 6,825. 운영 DB 적용(사용자 승인, 20초) |
| N2 충남 별표 2·3·4 | `a8c3504c` | `SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_02`(SW)·`03`(WASTE)·`04`(LAND_TRANSPORT) 3구간 | 리뷰 pass, 전량 6,856. 사용자 등록 승인 |
| N3 회원정보 수정 | `19992761` | `GET/POST /accounts/mypage/edit/`, 닉네임·이메일·회사·정량 원자료(아이디·비밀번호 제외) | 리뷰 pass(반례 5종), 전량 6,832 |
| S3 설정·헬스·검색·CI | `724eb9ca` | staging 검증 강화, `.env` 프로젝트 루트, 헬스 예외 원문 제거, LIKE autoescape, CI 최상위 `permissions` | 리뷰 pass(반례 4종), 전량 6,891 |
| S2 XSS·인증 경계 | `5c592bf8` | marked renderer 정화(새 의존성 없음), 대시보드·상세 이스케이프, escapejs·to_json, CSRF 쿠키 Secure, next 경로, 더미 해시 | 리뷰 pass(node 반례), 전량 6,932 |
| S1 채팅 자동화 staff 전용 | `fe6126c7` | 채팅 action·확인 토큰·실행 문구 staff 전용, REST confirm·cancel staff, 로그인 사용자 쿼터 120회/60초 | 리뷰 pass(반례 7종), 전량 6,885 |
| T2 API 출처 검사 | `0034b9e4` | 세션 쿠키가 있는 `/api/v1` 상태 변경 요청의 Origin/Referer 검사(L4), 콜백 토큰 우선 검증(L10) | 리뷰 pass(반례 12종, Host 위조 불가 확인), 전량 6,971 |
| T1 인증·세션 | `7873de70` | 로그인 재해시·salt 22자·비밀번호 상한 4096(L2), 세션 유휴 만료 7일(L11, 사용자 결정) | 리뷰 pass(반례 30건), 전량 6,967 |
| T3 스크립트·CI·XML | 이 문서와 같은 병합 | 백업 tar 경로·DB URL(L7·L8), defusedxml 0.7.1(L9, 사용자 승인), CI gitleaks 전체 이력 스캔(L12), README 고정 안내(L16) | 리뷰 pass(반례 9건), 로컬 gitleaks 2,259커밋 통과 |

병합 후 `main`(`fe6126c7`) 전량은 6,951 통과, 31 skip, mypy 오류 없음이다(주 저장소라 데이터 자산 시험이 더 돈다).

---

## 2. 실측과 판정

### 2.1 predict-price 지연

원인은 `src/ml/repeat_history.py` `lookup_repeat_history` 였다. 기관+업무구분으로 최대 5,000행을 읽고 `bid_ntce_nm` 을 행마다 본문에서 읽었다. 모델 추론은 4~11ms 였다.

| 측정(처음 여는 공고, 프로세스 내 TestClient) | 적용 전 | 적용 후 |
| --- | --- | --- |
| 재발주 조회 | 0.15~29초 | 0~5ms |
| predict-price 전체 | 0.1~29.5초 | 11~36ms (24건, 중앙값 16ms) |
| EXPLAIN | `ix_bid_results_inst_cat_stats`, rows 5442, filesort | `ix_bid_results_repeat_hist`, Using index, Backward index scan |

적용 후 값은 인덱스 생성 직후라 버퍼풀이 데워진 상태다. 완전한 콜드 값이 아니다.

### 2.2 Grok 보안 검토 보고서 판정

보고서 기준 커밋은 `dc843e89`(세션 시작 `main`)였다. High 2건과 Medium 대부분을 코드로 확인했다. 수치 오차는 두 곳뿐이었다(src `print()` 9곳이 아니라 8곳, escapejs 의 U+2028 은 이미 이스케이프됨).

---

## 3. 이 세션의 절차 함정

| 함정 | 처리 |
| --- | --- |
| 셸 `&` 로 띄운 `check --wait` 를 죽이면 서버에 대기자가 남아 새 `--wait` 가 `waiter_exists` 로 거부된다 | 30초 간격 즉시 조회 루프를 추적되는 배경 작업으로 대체 |
| 즉시 조회 `check` 는 `--types` 를 무시하고 heartbeat 배치도 돌려준다 | 루프에서 heartbeat·status 만 든 배치는 자동 ack |
| `release-worker` 가 성공해도 cmd 런처 창이 남아 다음 Dispatch 가 `settled_session_lingering` 으로 거부됐다 | `terminal show` 로 탭이 코디네이터와 다른지 확인 후 창 단위 `close` 를 매번 같이 실행 |
| 코디네이터 Capsule 의 기본 체크리스트(`scope_expanded`)와 리뷰 보고서 id 가 달라 strict 게이트 5 실패 | 코디네이터 Capsule 의 `review_checklist` 를 그 브랜치 리뷰 Capsule 것으로 교체 |
| 리뷰 Intent 의 `\"` 가 확장 후 `\\"` 가 되어 그 체크리스트를 옮긴 Capsule 이 YAML 오류 | `how` 문구에 큰따옴표를 쓰지 않는다 |
| 병합 다섯 건째에 현황판 `source_commit` 이 6커밋 뒤처져 규칙 검증 실패 | 푸시 전 로컬 병합만 되돌리고 코디네이터 브랜치에 main 반영 후 `source_commit` 갱신, 재게이트 후 재병합 |
| `orca worktree rm` 은 비동기라 직후 `git worktree list` 에 남아 보인다 | 몇 초 뒤 다시 확인. 브랜치도 함께 지운다 |
| 연결 실행(`게이트 && premerge`)을 중복으로 다시 띄워 전량 시험이 두 번 돌았다 | 앞 작업 출력을 끝까지 확인한 뒤 재실행 |

---

## 4. 하지 않은 것과 사용자 결정 대기

| 항목 | 상태 |
| --- | --- |
| CSP 헤더(보고서 H2·품질 7) | 템플릿 인라인 스크립트가 많아 `script-src 'self'` 를 걸면 화면이 깨진다. 인라인 스크립트 정리가 먼저 |
| M4 모델 pickle·`preprocess.py` 무결성 | 서빙 로드 경로 재설계 필요. 운영 Compose 는 `data` 읽기 전용이라 위험이 줄어 있다 |
| M7 자동 승인 감시기 샌드박스 | 개발 도구. 미착수 |
| L16 vendor JS(jQuery·Bootstrap·marked·Font Awesome) 감사 | npm audit 범위 밖. 미착수 |
| L11 전체 기기 로그아웃 | 유휴 만료만 구현. 미착수 |
| L14 공개 저장소의 로컬 경로·Chroma 백업 tar·워커 로그 34건, LICENSE·SECURITY.md 부재 | 저장소 공개 유지 여부와 함께 사용자 결정 |
| 품질 2(print 8곳), 3(`except Exception` 원문 payload) | 미착수 |
| 충남 별표 3 두 번째 표(생활폐기물 참고 예시) | 등록하지 않음 |

---

## 5. 종료 시 자원

| 자원 | 상태 |
| --- | --- |
| Orca Run `run_38d15a53246a` | Task 12건(빌더 6, 리뷰어 6) 모두 `completed`, 워커 창 전부 닫음 |
| 워크트리 | 주 저장소만 남음. 이번 작업 브랜치 전부 삭제(이 인수인계 브랜치 제외) |
| 운영 DB | alembic head `a6b7c8d9e0f1` |
| Docker | 개발 스택 기동 중, app 은 `fe6126c7` 기준으로 재시작함 |
