# 핸드오프 인수인계 — 2026-10-11 인수인계 잔여와 Grok 검토 잔여 항목

> **작성일**: 2026-10-12
> **작성**: Claude 코디네이터 (Orca Run `run_75c43ef48072`)
> **기준 커밋**: `aba87269` (이 문서가 들어가는 최종 병합의 부모)
> **직전 인수인계**: [handoff_20261011_sec_close.md](handoff_20261011_sec_close.md)

---

## 0. 다음 세션이 가장 먼저 할 일

| 우선 | 과제 | 선행 |
| --- | --- | --- |
| 1 | 이 문서가 들어간 최종 병합 커밋의 CI 가 원격 `main` 에서 녹색인지 확인 | 없음 |
| 2 | 직전 인수인계 0절의 사용자 조치 항목(GitHub 비공개 취약점 제보 활성화, 로그인 화면 브라우저 확인)은 그대로 남아 있다 | 사용자 |
| 3 | 5절의 manifest 서명, 세대 번호 영속화, M7 감시기, 등급확인서 실측은 같은 날 Z 차수(Z1~Z4)로 착수했다(사용자 결정 2026-10-12). Run `run_75c43ef48072` 의 Z Task 상태를 먼저 확인 | 없음 |

---

## 1. 운영 주의 사항

### 1.1 `uv.lock` 을 바꾸면 `constraints.txt` 도 재생성 (Y2)

- 루트 `constraints.txt` 는 uv 없이 `pip install -c constraints.txt .` 로 설치하는 경로용 버전 고정 파일이다.
- `tests/test_constraints_sync.py` 가 `uv export` 결과와 대조한다. **의존성을 추가·변경해 `uv.lock` 이 바뀌면 이 시험이 실패한다.** 다음으로 재생성한다.

  ```bash
  uv export --frozen --format requirements.txt --no-emit-project --no-dev --no-hashes -o constraints.txt
  ```

- uv 가 없는 환경에서는 이 시험이 skip 된다.

### 1.2 경로 설정 정규화 (Y1)

- `CHROMA_DB_PATH`, `MODEL_FILES_DIR`, `MODEL_BACKUPS_DIR`, `MODEL_METRICS_DIR`, `MODEL_REGISTRY_DIR`, `FEATURE_STORE_DIR` 는 상대 값이면 실행 위치(CWD)가 아니라 프로젝트 루트 기준으로 해석된다(`src/app/core/config.py` 의 `normalize_project_paths`). 절대 값은 그대로다.
- 재학습·드리프트 경로의 `ml_registry`, `data/feature_store` 하드코딩 기본값은 설정값을 따른다. 명시 인자는 그대로 존중한다.
- compose 는 `/app` 아래 절대 경로를 넘기고 컨테이너의 프로젝트 루트도 `/app` 이라 동작 변화가 없다.

### 1.3 모델 들여오기 경로가 manifest 를 다시 쓴다 (X1)

- `scripts/import_data_assets.py` 와 `scripts/sync_model_files.py import` 가 배치 직후 서빙 모델 무결성 manifest(`artifact_manifest.json`)를 다시 쓴다. 직전 인수인계 1.1 의 "확인하지 않은 것" 이 해소됐다. 번들에 원본 머신의 manifest 가 들어 있어도 배치된 파일 기준으로 덮어쓴다.
- 손으로 모델 파일을 교체했다면 여전히 `uv run python scripts/write_model_manifests.py` 가 필요하다.

### 1.4 Caddy Permissions-Policy (Y2)

- `deploy/Caddyfile` 에 `Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), usb=()"` 를 추가했다. 운영 Caddy 는 설정을 다시 읽어야 적용된다.
- CSP 는 앱이 요청마다 nonce 로 붙이므로(`src/app/core/csp.py`) Caddy 에는 넣지 않는다. `tests/test_caddyfile_security_headers.py` 가 CSP 부재를 단언한다.

### 1.5 예외 원문 마스킹 (X2)

- 재학습 실패 알림과 스케줄 따라잡기 실패 원장에 예외 원문 대신 `src/tasks/error_payload.py` 의 `summarize_error` 요약(첫 줄, 자격 증명·경로 마스킹, 200자)이 들어간다. 원문 전체는 `logger.exception` 로그에만 있다.

### 1.6 nosec 정책 (Y4)

- 저장소 정책은 그대로 줄 단위 `# nosec BXXX - 사유` 다(사용자 결정 2026-10-12, 경로 단위 예외 전환 안 함).
- bandit 의 `nosec encountered (BXXX), but no failed test` 경고는 여러 줄 문장의 중복 경고다. 리뷰어가 표본 10건에서 마커를 지우면 해당 규칙이 다시 검출됨을 확인했다. 이 경고 수를 낡은 nosec 의 근거로 쓰지 않는다.
- 점검 결과는 `docs/analysis/nosec_audit_20261012.md` 에 있다.

---

## 2. 이 세션에서 병합한 것

빌더는 cmd `deepseek/deepseek-v4.1-flash`(위험도 medium 은 effort high, low 는 default)다. 리뷰어는 X 차수가 opencode `muse-spark-1.3-contributor-free`, Y 차수가 Antigravity `gemini-3.8-flash-medium` 이다(4절). 전부 `--no-ff` 병합, 원격 반영, strict 게이트 증거와 병합 전 전량 시험 증거를 거쳤다.

| 차수 | Task | 병합 | 내용 | 검증 |
| --- | --- | --- | --- | --- |
| X | X3 tailwind vendor 삭제 | `6789f60f` | 미사용 `vendor/tailwindcss/3.4.16` 삭제, 무결성 시험 목록 정리 | 리뷰 pass, 전량 7,138 통과 |
| X | X1 manifest 재봉인 | `a6bc5395` | 모델 들여오기 두 경로의 manifest 재작성 | 리뷰 pass(틀린 번들 manifest 반례), 전량 7,145 통과 |
| X | X2 예외 마스킹 | `2e54a09f` | 재학습 알림·따라잡기 원장 `summarize_error` | 리뷰 pass, 전량 7,140 통과 |
| Y | Y2 배포 보강 | `81bcf037` | README Windows 대체 명령, `constraints.txt` 와 동기 시험, Caddy Permissions-Policy | 리뷰 pass, 전량 7,148 통과 |
| Y | Y1 경로 정규화 | `aba87269` | 경로 설정 프로젝트 루트 기준 정규화, 하드코딩 기본값 통일 | 리뷰 pass, 전량 7,151 통과 |
| Y | Y4 nosec 재점검 | 이 문서와 같은 병합 | 낡은 nosec 8건·불필요 B607 9건 삭제, 사유 보강 102건, 코드 변경 0 | 리뷰 pass(표본 10건 실측), bandit 0건, 전량 7,147 통과 |

### 2.1 Grok 검토 보고서(`dc843e89` 기준) 대비 상태

High 2, Medium 7, Low 16, 크로스 플랫폼 3, 품질 9 가운데 이 세션 종료 시점 미처리는 5절의 항목뿐이다. 이 세션에서 처리한 것은 크로스 플랫폼의 상대 경로(Y1)와 README make 의존(Y2), 품질 3(예외 원문, X2), 4(nosec, Y4), 7(Caddy 헤더, Y2), 9(constraints, Y2)다. 품질 6(에이전트 설정 미러)은 현행 유지로 결정했다(5절).

---

## 3. 실측과 판정

- 세 차례 병렬 웨이브에서 빌더 6대 모두 1회에 계약을 충족했다(게이트 위반 0, 재작업 0).
- 코디네이터 Level 3 확인: Y4 diff 에서 주석을 뗀 코드 줄 차이 0건, X1·X2·Y1 diff 는 계약 범위 안.

---

## 4. 이 세션의 절차 함정

| 함정 | 처리 |
| --- | --- |
| opencode `muse-spark-1.3-contributor-free` 리뷰어 두 대가 `Free usage exceeded ... retrying in 2h 24m` 로 정지 | 창을 닫고 `task-update --status ready` 후 Antigravity `gemini-3.8-flash-medium` 런처로 재Dispatch(`--launcher scripts/orca_agy_launch.py --agent antigravity`) |
| Antigravity 를 처음 띄운 워크트리는 `Do you trust the contents of this project?` 에서 정지 | Dispatch 직후 터미널 끝부분을 읽고 Enter 로 기본값 Yes |
| Task 블록의 Capsule 경로는 Intent 이름 디렉터리(`.orca/capsules/task_<intent 이름>/`)다. 실제 ID 디렉터리만 복사하면 agy 가 `find ~`·`find /` 로 홈 전체를 뒤진다 | 워크트리에 두 디렉터리를 모두 복사 |
| 리뷰어가 완료한 직후 다른 Dispatch 를 시도하면 `settled_session_lingering` 으로 거부 | 수신함을 먼저 처리해 회수한 뒤 Dispatch |
| 감시기가 이미 회수한 빌더의 worker_done 페이로드 `reportPath` 누락을 `[차단:실패 정체]` 로 계속 표시 | 오탐. 대기 루프에서 그 사유만 제외 |
| 스킬 미러를 링크로 바꾸자는 제안 | `scripts/sync_skill_mirrors.py` 설명문에 G2 로 기각된 이력이 있다. 사용자가 현행 유지 결정 |

---

## 5. 하지 않은 것과 사용자 결정 대기

| 항목 | 상태 |
| --- | --- |
| 에이전트 설정 미러 정리(Grok 품질 6) | 현행 유지(사용자 결정 2026-10-12). 복제는 `sync_skill_mirrors.py`, 어긋남은 `validate_agent_rules.py` 검사 5 가 막는다. `.cursor/rules` 는 미러가 아니라 형식이 다른 `.mdc` 12개 |
| M7 자동 승인 감시기 샌드박스 | 미착수(개발 도구) |
| manifest 서명 | 미착수. 서명 키 보관 방식 결정 필요 |
| 세대 번호 영속화(모든 기기 로그아웃) | 미착수. Redis 데이터 소실 시 무효 세션 부활 가능 |
| chromadb 0.6.3 CVE allowlist(Grok L15) | 만료 2026-12-31. 수정 버전 없이 업그레이드 재제안 금지 |
| Chroma 백업 tar 의 git 이력 제거, docs 의 로컬 절대 경로 | 하지 않음(직전 세션 사용자 결정) |
| 스캔본 등급확인서 OCR, 재무제표 PDF 자동 입력, 실제 확인서 적중률 | 직전 인수인계 6절 그대로 |

---

## 6. 종료 시 자원

| 자원 | 상태 |
| --- | --- |
| Orca Run `run_75c43ef48072` | 빌더 6, 리뷰 6(opencode 실패 2건은 같은 Task 를 agy 로 재Dispatch) 전부 `completed`, 워커 창 전부 닫음 |
| 워크트리 | 병합한 워크트리·브랜치 전부 정리 |
| 다른 코디네이터 세션 창 | `term_a814...`(Cursor CLI 코디네이터)는 이 Run 소속이 아니라 건드리지 않음 |
