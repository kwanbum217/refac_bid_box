# 핸드오프 인수인계 — R 차수(설계·조사 3건), M7 1단계(CLI 권한 하드닝·워커 .env 최소화), 모바일 반응형 수정

> **작성일**: 2026-10-13
> **작성**: Claude 코디네이터 (Orca Run `run_ec5dfe0b8e2d`)
> **기준 커밋**: `d6311664` (이 문서가 들어가는 최종 병합의 부모)
> **직전 인수인계**: [handoff_20261012_z_q_waves_close.md](handoff_20261012_z_q_waves_close.md)

---

## 0. 다음 세션이 가장 먼저 할 일

| 우선 | 과제 | 선행 |
| --- | --- | --- |
| 1 | 이 문서가 들어간 최종 병합 커밋의 CI 가 원격 `main` 에서 녹색인지 확인(RSP1 `0b7cb0a2`, M7A `d6311664` 의 CI 결과는 6절) | 없음 |
| 2 | Docker 는 정지 상태다. 다음 시동은 Docker Desktop 실행 후 `docker compose up -d`. RSP1 이 템플릿·정적 파일을 바꿨으므로 앱은 새로 띄우면 반영된다 | 없음 |
| 3 | **M7A 이후 cmd 워커는 승인 대화창에서 멈출 수 있다(1.1 마지막 항목, 이번 세션 실측 약 3시간 반 정체).** 첫 Dispatch 를 직접 지켜보고, `orca_auto_approve.py` 가 cmd 대화창의 파이프·`echo` 결합 명령을 승인하지 못하는 문제를 먼저 고친다(감시기 화이트리스트 확장 또는 cmd 정책 allow 목록). 고치기 전에는 Intent 에 '검증 명령을 파이프·`;` 로 잇지 말 것' 을 적는다 | 워커 Dispatch |
| 4 | M7 1단계 운영 관찰 기록을 시작한다(약 일주일, 4절 결정 2) | 없음 |
| 5 | 직전 인수인계 0절의 사용자 조치(운영 서버 Z1 서명 키·Z2 마이그레이션, 비공개 취약점 제보 활성화)는 그대로 남아 있다 | 사용자 |

---

## 1. 운영 주의 사항

### 1.1 워커 권한 모드가 바뀌었다 (M7A, `d6311664`)

- `scripts/orca_cmd_launch.py --auto` 는 이제 `--trust` 만 붙인다. `--trust` 는 작업 공간 신뢰 대화창만 넘기고(`cmd --help`: "Auto-trust project (skip initial permission prompt)") 도구 승인 대화창은 그대로 뜬다. 판정은 `scripts/orca_auto_approve.py` 감시기가 한다. `--yolo` 는 어떤 인자 조합에서도 붙지 않는다.
- cmd 런처는 워커 워크트리(주 저장소가 아닌 연결 워크트리)에서만 `scripts/orca_policies/commandcode_worker_settings.json` 을 `<워크트리>/.commandcode/settings.json` 으로 배치한다. deny: `git push`, `.git` 편집, `.env*`·홈 자격증명·`/etc` 읽기, `disableBypass`. 주 저장소의 개인 `.commandcode/settings.json` 은 건드리지 않는다.
- opencode 런처는 `--auto` 를 넘기지 않는다. `opencode.json` 에 `permission` 블록(`external_directory` deny, `.env` 읽기 deny·`.env.example` 허용, 위험 bash deny)이 들어갔다. 감시기에 opencode 승인 대화창 탐지가 추가됐다.
- agy 런처는 `--sandbox` 로 띄운다. 홈 설정(`~/.gemini/antigravity-cli/settings.json` 의 `enableTerminalSandbox`, `toolPermission`)은 작업 트리 밖이라 손대지 않았다. 필요하면 사람이 넣는다.
- **실측된 정체(2026-10-13)**: M7A 워크트리 런처로 뜬 보고 재작업 cmd 워커가 `uv run pytest ... 2>&1 | tail -20; echo "EXIT=$?"` 승인 대화창에서 약 3시간 반 멈췄다. 자동 승인 감시기는 붙어 있었으나 리다이렉션·파이프·`;` 결합 명령은 화이트리스트 밖이라 승인하지 않았고, `orca_worker_watch.py` 는 이를 차단으로 보고하지 않았다. 코디네이터가 터미널 끝을 읽고 수동 승인해 풀었다. M7 1단계 관찰 기록의 첫 항목이다.
- **리뷰·조사 Intent 의 임시 경로는 `/tmp` 대신 워크트리 안 `.orca/tmp_<태그>/` 로 적는다.** opencode 의 `external_directory` deny 가 `/tmp` 쓰기를 막을 수 있다.

### 1.2 워커 `.env` 는 최소 키만 (M7B, `7eae2bc7`)

- `cp .env <워크트리>/.env` 를 쓰지 않는다. `python3 scripts/orca_prepare_worktree.py` 가 `scripts/orca_worker_env.py` 허용 목록(DB 접속 키 6개)만 옮기고 `SECRET_KEY` 는 워크트리마다 새로 만든다. G2B·Gemini API 키, manifest 서명 키, 웹훅, 관리자 비밀번호 8종은 넘기지 않는다. 기존 워크트리 `.env` 에 금지 키가 남아 있으면 최소 `.env` 로 다시 쓴다.
- 잔여 위험: DB 자격증명은 쓰기도 가능하다. 읽기 전용 DB 계정 분리는 하지 않았다.
- 격리 워크트리에서 서빙 모델을 띄우는 검증(로컬 uvicorn 등)은 `MODEL_FILES_DIR`, `MODEL_REGISTRY_DIR`, `MODEL_METRICS_DIR`, `CHROMA_DB_PATH` 를 주 저장소 경로로 넘겨야 한다. 그러지 않으면 모델 목록이 비어 화면이 달라진다(이번 세션 RSP1 대조에서 실측).

### 1.3 SSR 화면 모바일 반응형 (RSP1, `0b7cb0a2`)

- 768px 미만에서 사이드바는 숨고 헤더 햄버거 버튼(`#mobile-nav-toggle`)이 왼쪽 서랍을 연다(`src/app/static/js/mobile-nav.js`, CSP 때문에 인라인 핸들러 없음). 챗봇은 대화 목록을 토글(`#chat-sessions-toggle`)로 열고 대화창을 전체 폭으로 쓴다.
- **이 화면들은 Bootstrap 5 와 tailwind 를 함께 불러온다. Bootstrap 간격 유틸리티(`px-4`, `gap-2` 등 0~5 단계)는 `!important` 라 tailwind 반응형 변형(`sm:px-8`)을 이긴다.** 모바일 값은 원래 데스크톱 클래스를 두고 `max-sm:`/`max-md:` 변형으로만 준다. `tests/test_responsive_templates.py` 가 새 충돌 조합을 막고, main 에 원래 있던 13개 조합은 예외로 고정했다.
- 푸터의 빈 링크(문서, 지원 센터, API 안내)와 대시보드 "문서 보기" 빈 링크를 제거했다(사용자 결정).

---

## 2. 이 세션에서 병합한 것

빌더는 cmd `deepseek/deepseek-v4.1-flash`, 리뷰어는 opencode `muse-spark-1.3-contributor-free` 로 시작했으나 RSP1 리뷰 도중 `Upstream request failed: Invalid credential` 로 실패해 RSP1·M7A 리뷰는 Antigravity `gemini-3.8-flash-medium` 으로 바꿨다(사용자 지시). 전부 `--no-ff`, strict 게이트 증거와 병합 전 전량 시험 증거를 거쳤다.

| Task | 병합 | 내용 | 검증 |
| --- | --- | --- | --- |
| R3 재무제표 PDF 자동입력 설계 | `5114e563` | `docs/analysis/financial_statement_pdf_autofill_design_20261012.md` | 리뷰 pass, 전량 7,256, CI 녹색 |
| R2 M7 샌드박스 설계 | `39972e3c` | `docs/analysis/m7_auto_approve_sandbox_design_20261012.md` | 리뷰 pass, 전량 7,256, CI 녹색 |
| R1 나라장터 첨부 평가표 수집 | `67ddfc99` | `docs/analysis/institution_formula_g2b_attachment_sweep_20261012.md`, 공고 90건·첨부 236건, 확정 0/9 | 리뷰 pass(해시 재대조 3건), 보고 라벨 재작업 1회, CI 녹색 |
| M7B 워커 .env 최소화 | `7eae2bc7` | 1.2 | 리뷰 pass(합성 반례), 전량 7,267, CI 녹색 |
| M7A CLI 권한 하드닝 | `d6311664` | 1.1 | 리뷰 pass, 보고서 검증 명령 재작업 1회, 전량 7,309 |
| RSP1 모바일 반응형 | `0b7cb0a2` | 1.3 | 코디네이터 브라우저 대조(데스크톱 회귀 1건 반려 후 재작업), 리뷰 pass, 보고 재작업 1회, 전량 7,281 |

### 2.1 RSP1 브라우저 검증

- 수정 전: 15개 화면 x 6개 폭(320~1440) 측정. 가로 스크롤·콘솔 오류 0, 데스크톱 정상. 챗봇 375px 입력창이 화면 밖(left 392px)이라 누를 수 없었고, 사이드바 80px 고정, 버튼·표 머리글·푸터 글자 접힘, 작은 터치 영역이 있었다.
- 1차 수정본을 main 과 로컬 서버 두 대(8101 main, 8100 브랜치)로 픽셀·계산 스타일 대조해 Bootstrap 충돌로 헤더 여백이 1440px 에서도 32px -> 24px 로 바뀐 회귀를 찾아 반려했다.
- 재작업본: 1024·1440 헤더 요소 위치가 main 과 동일. 남은 픽셀 차이는 빈 링크 제거, 1024px 공고 상세 표 머리글 접힘 개선(의도), 차트 애니메이션 시점뿐이다. 모바일 접힘은 화면당 4~12건에서 0~2건, 작은 터치 영역은 약 절반 이하로 줄었다. 375px 챗봇 입력·전송 버튼 클릭 가능, 햄버거 서랍 열기·Esc 닫기·`aria-expanded` 갱신을 실측했다.
- 남은 사소한 것: 챗봇 헤더 "활성" 배지와 브레드크럼 두 줄 접힘, 마이페이지 수정 체크박스 16px. 실기(iOS Safari·Android) 확인은 하지 않았다.

---

## 3. 이 세션의 절차 함정

| 함정 | 처리 |
| --- | --- |
| Capsule ground_truth 의 사실 오류 2건(공통 런처 모듈 이름, 스킬 정본 위치) | 워커가 짚어 expand 로 정정·재배치. 스킬 정본은 `.agents/skills`, 미러는 `.claude`·`.opencode` |
| 조사 결과 0건을 빌더가 `verdict: blocked` 로 보고해 게이트 6 실패 | 보고만 다시 쓰는 rework. 0건 가능 조사 Intent 에 라벨 규칙을 적는다 |
| 빌더 보고의 검증 명령에 자리표시자 문구가 들어가 게이트 6 이 재실행 실패 | 보고만 다시 쓰는 rework. Intent 에 "verification 은 실제 실행한 명령 문자 그대로" 를 적는다 |
| 첫 전량 시험에서 1건 간헐 실패, 증거에 이름이 남지 않음 | 재실행 통과. 실패 이름은 `.pytest_cache/v/cache/lastfailed` 를 덮기 전에 읽는다 |
| opencode Muse 무료 리뷰어 인증 실패 | Antigravity 로 교체. 런처가 accept-edits·감시기를 스스로 설정했고 신뢰 대화창은 이번에는 뜨지 않았다 |
| Antigravity 리뷰어가 `review_done.json` 을 쓴 뒤 `worker_done` 전송이 `reportPath` 누락으로 거부되고 이어 크레딧 부족 표시로 멈춤 | 보고 파일 내용(체크리스트 4건 근거)을 코디네이터가 확인하고 `worker-stop`·회수 후 그 파일로 게이트 5 통과 |
| 재작업 빌더가 `changed_files` 에 재작업 커밋 파일만 적어 게이트 6(`main...HEAD` 전체 대조) 실패 | 보고만 다시 쓰는 rework. 재작업 Intent 에 '`changed_files` 는 `main...HEAD` 전체' 를 적는다 |
| 시험용 브라우저 자동화의 로그인 선택자가 헤더 검색 폼 제출 버튼을 눌렀다 | 비밀번호 칸에서 Enter 로 제출 |

---

## 4. 사용자 결정 (2026-10-12)

1. 푸터 빈 링크 제거 — RSP1 에 반영.
2. **재무제표 PDF 자동입력(지시서 B안) 보류.** 현행 용역 적격심사는 경영상태를 신용평가등급으로만 평가해 재무 값 입력처가 없다. 공사 적격심사 계산을 도입할 때 함께 다시 연다.
3. **M7 2단계(워커 CLI 컨테이너 격리)는 착수하지 않는다.** M7A 병합 뒤 약 일주일 워커를 돌려 승인 대화창 정체 횟수와 막힌 명령을 기록한 뒤 착수 여부를 정한다. 미리 정한 방향: 네트워크는 모델 API·Orca 제어 평면만, Windows 는 컨테이너가 유일한 공통 방식, codex 는 워커로 쓰지 않음, 제어 평면 접근 방식은 착수 때 조사 Task 로 먼저 확인. 운영 DB 쓰기 자격증명과 Docker 소켓 위험은 그 기간 감수한다.

---

## 5. 하지 않은 것

| 항목 | 상태 |
| --- | --- |
| 기관 산식 미확정 9행 | R1 로 나라장터 첨부 경로도 소진(확정 0/9). 기관 질의회신이나 기관 전자조달시스템 자료실 접근이 남았다 |
| cmd 정책의 `Read(.env*)` 가 `.env.example` 읽기도 막음 | 리뷰는 설계상 의도로 판정. 비밀값이 없는 파일이라 `Read(.env)` 로 좁히는 후속 과제 |
| Z4 등급확인서 실측 적중률, G2 Windows 실기, 운영 서버 Z1·Z2 적용 | 직전 인수인계와 같다 |

---

## 6. 종료 시 자원

| 자원 | 상태 |
| --- | --- |
| Orca Run `run_ec5dfe0b8e2d` | Task 17개: completed 15, blocked 2. blocked 는 둘 다 중단한 리뷰어다(`task_d84e06238eab` Muse 인증 실패로 결과 없음, `task_940675b2411d` Antigravity 가 `review_done.json` 을 쓴 뒤 `worker_done` 전송 실패 -> 파일을 검토해 수용). 활성 Dispatch 없음 |
| CI | RSP1 병합 `0b7cb0a2`, M7A 병합 `d6311664` 의 원격 CI 는 이 문서 병합 전에 녹색을 확인했다. 이 문서 병합 커밋의 CI 는 0절 1번으로 다음 세션이 확인한다 |
| 워크트리 | 병합한 워크트리·브랜치 전부 정리. 주 저장소만 남김 |
| Docker | 사용자 요청으로 개발 스택 전부 정지(볼륨 유지) |
| 배경 프로세스 | 비교용 로컬 uvicorn 2대, 코디네이터 대기 루프, 워커 감시기·자동 승인 감시기 전부 종료 |
