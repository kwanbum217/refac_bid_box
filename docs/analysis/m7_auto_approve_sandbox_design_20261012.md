# M7 자동 승인 감시기 샌드박스 격리 설계

> **작성일**: 2026-10-12
> **기준 커밋**: `47e97dfb` (main). 작업 브랜치 `kwanbum217/r2-m7-sandbox-design`
> **대상 위험**: `scripts/orca_auto_approve.py` 가 승인한 워커 명령이 호스트 사용자 권한으로 실행되는 위험(M7)
> **산출물 성격**: 설계 보고서. 이번 작업에서 코드는 변경하지 않는다. 구현은 사용자 결정 뒤 별도 Task 로 진행한다.
> **표기 규칙**: `(사실)` 은 저장소 코드나 벤더 공식 문서로 확인한 내용이고, `(추정)` 은 설계 제안이거나 아직 실측하지 않은 판단이다.

---

## 1. 요약

현재 방어선은 승인 감시기의 명령 화이트리스트(`scripts/orca_auto_approve.py`)와 작업 트리 밖 경로 차단(Z3, `8097cd95`)이다. 이 방어선은 승인 대화창이 뜨는 경로에서 명령 **문자열**을 판정할 뿐이고, 승인된 명령은 다시 사용자 계정 권한으로 호스트에서 실행된다. 더구나 cmd 빌더는 `--auto` 로 기동해 승인 대화창 자체가 없으므로(`scripts/orca_cmd_launch.py:97`) 감시기가 개입할 지점이 없다.

따라서 승인 목록을 더 정교하게 만드는 방향으로는 M7 을 닫을 수 없다. 권장안은 워커 실행 자체를 호스트에서 떼어내는 **2단 격리**다. 1단계에서 CLI 자체 권한 모드 하드닝과 비밀값 분리를 즉시 넣고, 2단계에서 워커 CLI 를 컨테이너 안에서 실행하며 워크트리만 마운트한다.

---

## 2. 위협 모델

워커가 의도치 않게 또는 프롬프트 주입으로 할 수 있는 피해를 자산별로 정리한다. "현재 방어"는 승인 대화창이 뜨는 경로를 기준으로 하고, `--auto`(cmd 의 `--trust --yolo`, opencode 의 `--auto`) 경로는 별도로 표기한다.

| 자산 | 워커가 낼 수 있는 피해 | 현재 방어 | 근거(파일:행) |
| --- | --- | --- | --- |
| `.env` 비밀값 (G2B 키, `SECRET_KEY`, DB 비번, Meili 키, manifest 서명 키) | 파일을 읽어 로그·보고서·커밋에 노출하거나 원격으로 전송 | 부분 방어. 승인 경로에서는 `.env` 등 비밀 경로를 담은 명령을 보류한다. 그러나 워커는 `.env` 사본을 워크트리에서 이미 쥐고 있으며, 감시기는 "읽기"만 막고 "존재"는 막지 않는다. `--auto`(yolo) 경로에서는 대화창이 없어 이 판정이 아예 적용되지 않는다. | `scripts/orca_auto_approve.py:75`(SECRET_PATH), `:1305`(비밀 파일 접근 보류), `:990-991`(히어독 쓰기 대상 보류), `scripts/orca_cmd_launch.py:97`(`--trust --yolo`) |
| 운영 MySQL (호스트 `127.0.0.1:3306`) | 스키마·데이터 변경, 대량 조회로 운영 영향 | 부분 방어. 승인 경로에서는 승인 목록의 읽기 전용 실행기(`scripts/db_readonly_query.py` 등)만 허용하고 임의 `mysql`·`docker exec` 는 보류한다. DANGEROUS 2차 방어선이 `DROP/DELETE/UPDATE/INSERT/TRUNCATE` 를 잡는다. yolo 경로는 무방어. 운영 DB 포트가 호스트에 열려 있다. | `scripts/orca_auto_approve.py:1444-1453`(uv run 허용 스크립트), `:1577-1640`(docker exec 계열 보류), `:106`(DANGEROUS), `docker-compose.yml:216`(`127.0.0.1:3306:3306`) |
| Docker 데몬·소켓 | 컨테이너·볼륨 생성/삭제, 호스트 경로 마운트로 임의 파일 접근 | 부분 방어. 승인 경로에서는 `docker run/exec/rm/rmi/prune/down` 을 보류하고 `build` 의 호스트 내보내기 플래그도 막는다. 다만 워커는 호스트 셸에서 사용자 권한으로 `docker` CLI 를 직접 부를 수 있고, yolo 경로는 무방어다. compose 는 앱·워커 컨테이너에 Docker 소켓을 마운트하지 않는다(그 컨테이너들과 지금의 워커 프로세스는 별개다). | `scripts/orca_auto_approve.py:1577-1640`(docker 판정), `:1535-1537`·`:1627-1632`(빌드 내보내기 보류), `:106`(docker compose down/restart/up), `docker-compose.yml:104-110`, `docker-compose.yml:179-183` |
| 홈 디렉터리 자격증명 (`~/.ssh`, `~/.aws`, `~/.gitconfig`, OS keychain) | 키·토큰 탈취, 원격 자원 접근 | 부분 방어. Z3 가 작업 트리 밖 경로(`~`, 절대 경로, `..`, 링크 우회, 경로 인자의 셸 변수 확장)를 쓰는 명령을 보류한다. yolo 경로는 무방어. Z3 이전에는 `cat $HOME/.netrc` 가 승인된 회귀가 있었다. | `scripts/orca_auto_approve.py:896`(check_path_argument), `:72`(REDIRECT_DENY), `:832`(SHELL_VARIABLE_EXPANSION), `:1246`(경로 봉쇄 검사) |
| 원격 push·배포 | 저장소 이력 오염, 원격 반영 | 부분 방어. `git push` 는 DANGEROUS 패턴이고 `git` 하위 명령 허용 목록에 없다. 원격 반영/배포 확인 프롬프트 패턴도 있다. yolo 경로는 무방어이며, 자격증명이 있으면 `ssh`·`curl` 로 우회할 수 있다. | `scripts/orca_auto_approve.py:106`(git push), `:138-150`(허용 git 하위 명령), `:1411`(그 밖 git 보류), `:475-479`(원격 반영 프롬프트) |

### 2.1 현재 방어선의 구조적 한계

1. **승인 경로와 yolo 경로의 비대칭(사실).** 감시기는 승인 대화창의 명령 문자열을 읽어 판정한다(`scripts/orca_auto_approve.py:1901-1916`, `:1861`). cmd 빌더는 `--auto` 로 `--trust --yolo` 를 붙여 기동하므로(`scripts/orca_cmd_launch.py:97`) 대화창이 없고, 감시기가 판정할 대상이 없다. 승인받은 명령과 yolo 명령은 모두 사용자 계정 권한으로 호스트에서 실행된다(코디네이터 확인 사실).
2. **자산 단위가 아니라 명령 문자열 단위 판정(사실).** 화이트리스트는 "이 명령이 안전한가"를 묻지 "이 명령이 어떤 자산에 닿는가"를 묻지 않는다. 허용 목록의 읽기 전용 도구도 인자로 전달된 셸 명령 문자열의 절대 경로는 별도 규칙이 없으면 판정 밖이다.
3. **감시기 자신이 호스트 권한으로 동작(사실).** 감시기는 `sys.executable` 로 기동되며(`scripts/orca_taskctl.py:1970`) 승인 시 키를 보낼 뿐(`:1908`), 격리 경계를 만들지 않는다.

---

## 3. 후보 방식 비교

후보는 최소 3개를 요구하므로 4개를 비교한다.

| 후보 | 막는 위협 | macOS 동작 | Windows 동작 | 기존 런처·감시기 변경량 | 워커 속도·편의 비용 | 새 의존성 |
| --- | --- | --- | --- | --- | --- | --- |
| A. 워커 CLI 컨테이너 격리 (워크트리만 마운트) | 5개 자산 전부. 홈 자격증명·운영 DB·Docker 소켓·호스트 파일시스템이 컨테이너 밖이 된다. `.env` 도 워크트리에 넣지 않으면 차단된다. | Docker Desktop 필요. Linux 컨테이너로 동일하게 동작한다. | Docker Desktop 필요. WSL2 백엔드로 동일하게 동작한다(G2 표준과 일치). | 큼. 런처 래퍼 신설 + `.commandcode`/opencode/agy 설정 분리. 감시기는 컨테이너 경로에서 불필요해질 수 있다. | 중간. 이미지 빌드·기동 지연, 컨테이너 안 도구·인증을 갖춰야 함. | Docker(이미 G2 표준). 워커 이미지 정의 추가. |
| B. OS 수준 샌드박스 직접 래핑 (우리가 `sandbox-exec` 등으로 감쌈) | 5개 자산 대부분. 파일시스템·네트워크 경계를 OS 가 강제한다. | `sandbox-exec`(Seatbelt, SBPL) 가능. | 대응 기법이 OS·버전마다 다르고 우리가 직접 구현할 안정 경로가 없다(추정). | 큼. 프로파일 작성·유지, CLI 별 인자 호환. | 중간. 기동 지연은 작지만 프로파일 유지비가 크다. | 없음(OS 내장). |
| C. CLI 자체 샌드박스·권한 모드 | 자산별로 다름. agy·codex 는 OS 경계를 만들고, cmd·opencode 는 정책 게이트라 yolo/auto 를 끄는 전제에서만 유효하다. | agy 는 `sandbox-exec`, codex 는 Seatbelt 로 동작한다. | agy 는 preview(구 권한 체계), codex 는 native Windows sandbox·WSL2 로 동작한다. cmd·opencode 는 자체 OS 샌드박스가 문서에 없다. | 작음. 런처 인자와 설정 파일 값 변경이 중심이다. | 낮음. 대화창/거부가 늘어 워커가 멈출 수 있어 감시기·설정 관리가 필요하다. | 없음. |
| D. 비밀값 분리 (`.env` 미복사 + 최소 주입) | `.env` 비밀값 노출만. DB·Docker 소켓·홈 자격증명은 그대로 남는다. | 공통. | 공통. | 작음. 워크트리 준비 절차와 런처 env 주입. | 낮음. 다만 워커가 DB 조회 등에 필요한 값을 잃으면 작업이 막힌다. | 없음(환경변수 주입). |

### 3.1 CLI 자체 기능 확인 결과 (사실)

각 CLI 의 자체 샌드박스·권한 기능을 공식 문서로 확인한 결과다. 확인하지 못한 항목은 미확인으로 적는다.

| CLI | 자체 샌드박스·권한 기능 | 확인 여부 | 출처 |
| --- | --- | --- | --- |
| cmd (Command Code) | 권한 엔진. 모드 `default`·`accept-edits`·`plan`·`yolo`·`dont-ask`, `deny`/`ask`/`allow` 규칙, 외부 디렉터리 게이트, `disableBypass`, 루트/홈 삭제 회로 차단기. `dont-ask` 는 프롬프트 없이 허용된 것만 실행하고 나머지를 거부하는 fail-closed 모드다. OS 수준 샌드박스는 문서에서 확인하지 못했다. | 확인 | commandcode.ai/docs/permissions |
| opencode | `permission` 설정의 `allow`/`ask`/`deny`, `external_directory`, 기본 deny 되는 `.env`. `--auto` 는 명시 deny 가 아닌 요청을 자동 승인한다. OS 수준 샌드박스는 문서에서 확인하지 못했다(공식 Docker 샌드박스 가이드는 별도). | 확인 | opencode.ai/docs/permissions |
| agy (Antigravity CLI) | 터미널 샌드박스. macOS 는 `sandbox-exec`(Seatbelt SBPL), Linux 는 커널 namespaces. `enableTerminalSandbox`(기본 false), `toolPermission` 프리셋(`request-review`/`proceed-in-sandbox`/`always-proceed`/`strict`), `allow`/`ask`/`deny` 규칙, `unsandboxed` 이스케이프, `--sandbox` 플래그. Windows 는 preview 이며 구 권한 체계를 쓴다. | 확인 | antigravity.google/docs/sandbox, antigravity.google/docs/permissions |
| codex | `sandbox_mode`(`read-only`/`workspace-write`/`danger-full-access`)와 `approval_policy`. macOS Seatbelt, Linux bubblewrap, native Windows sandbox·WSL2 로 플랫폼별 강제. `config.toml` 키 `sandbox_mode`, `approval_policy`, `sandbox_workspace_write.writable_roots`. | 확인 | developers.openai.com/codex/sandboxing |

참고로 저장소 코드상 codex 는 코디네이터 전용 풀이고 워커 사용이 거부된다(`docs/ops/orca_control_plane_tools.md` 4.3). Capsule 의 "워커 CLI 네 종" 서술과 이 사실이 어긋난다. 이 불일치는 5절 질문으로 남긴다.

---

## 4. 권장안과 단계별 구현 계획

권장안은 **워커 실행을 호스트에서 떼어내는 2단 격리**다. 최종 목표는 후보 A(컨테이너 격리)이며, 그 전에 후보 C(CLI 권한 모드 하드닝)와 후보 D(비밀값 분리)를 즉시 넣는다. 이유는 후보 A 가 운영 DB·Docker 소켓·홈 자격증명까지 한 번에 닫는 유일한 안이고 G2 의 Docker 표준과 맞으며, 후보 C·D 는 A 의 선행 조건이자 A 도입 전 공백을 메우는 저비용 조치이기 때문이다.

### 4.1 1단계: 즉시 적용 (런처·설정 하드닝 + 비밀값 분리)

1. **cmd 런처의 yolo 제거.** `scripts/orca_cmd_launch.py` 의 `--auto` 분기에서 `--trust --yolo`(`:97`)를 제거하고, 프롬프트가 없는 경로가 필요하면 `--permission-mode dont-ask` 로 대체한다(`:172` 인자 정의도 함께 정리). `.commandcode/settings.json` 에 `permissions.deny`(예: `Shell(git push:*)`, `Edit(.git/**)`, `Read(//etc/**)`)와 `disableBypass: "disable"` 를 둔다.
2. **opencode 런처의 `--auto` 제거.** `scripts/orca_opencode_launch.py:74`, `:83` 에서 `--auto` 를 빼고, 프로젝트 opencode 설정에 `permission` deny(`external_directory` deny, `bash` 위험 패턴 deny, `.env` deny 유지)를 둔다.
3. **agy 런처에 샌드박스 켜기.** `scripts/orca_agy_launch.py:55` 의 `build_command` 에 `--sandbox` 를 추가하고, `~/.gemini/antigravity-cli/settings.json` 에 `enableTerminalSandbox: true`, `toolPermission: "proceed-in-sandbox"` 를 둔다. `unsandboxed` 허용은 최소로 유지한다.
4. **비밀값 분리.** `.env` 를 워크트리에 복사하지 않고, 워커가 실제로 쓰는 최소 키만 런처가 주입한다. 현재 `.env` 복사 주체는 코디네이터 워크트리 준비 절차로 보이며(추정), 파일 경로는 5절 질문으로 확인한다.
5. **감시기는 유지.** `scripts/orca_auto_approve.py` 의 화이트리스트와 작업 트리 봉쇄는 2차 방어선으로 남긴다. 봉쇄 회귀(`cat $HOME/.netrc` 류)를 다시 열지 않도록 기존 시험을 유지한다.

### 4.2 2단계: 컨테이너 격리 (목표)

1. **워커 이미지 신설.** 예: `docker/worker-sandbox/Dockerfile`. 실제 사용하는 CLI(cmd/opencode/agy)와 uv·git 만 넣고 비-root 로 실행한다.
2. **샌드박스 런처 신설.** 예: `scripts/orca_worker_sandbox_launch.py`. `docker run --rm -it -v <워크트리>:/work -w /work <image> <cli>` 형태로 CLI 를 기동하고, Orca terminal 은 이 런처를 `--command` 로 부른다. 네트워크는 기본 차단하고 필요한 호스트(모델 API, Orca 제어 평면)만 연다.
3. **제어 평면 도달 경로 설계.** 워커는 완료 보고를 위해 `orca orchestration send/check` 를 불러야 한다. 컨테이너 안에서 Orca CLI 에 닿는 방법(호스트 네트워크 + orca 바이너리 주입, 또는 제어 평면 소켓 마운트)은 5절 질문 1 로 확정한다.
4. **감시기 역할 정리.** 컨테이너 경로에서는 승인 대화창이 없으므로 `scripts/orca_taskctl.py:1945` 의 `start_auto_approve` 부착은 이 경로에서 건너뛴다.

### 4.3 시험 계획

- **반례(승인 경로).** `cat .env`, `cat ~/.ssh/id_rsa`, `mysql -h 127.0.0.1 -u root`, `docker run --rm -v /:/host alpine`, `git push origin main` 이 1단계 설정에서 보류 또는 거부되는지 확인한다.
- **반례(컨테이너 경로).** 같은 명령이 컨테이너 안에서 실패하거나 호스트 자산에 닿지 못하는지 확인한다.
- **G2.** 위 시나리오를 macOS 와 Windows(PowerShell) 양쪽에서 실행한다.
- **회귀 시험 배치.** 새 시험 파일은 `tests/` 아래에 두고, CI 의 개별 커버리지 목록에도 추가한다(`docs/handoff/handoff_20261012_z_q_waves_close.md` 4절 함정).
- **감시기 단위 시험.** `classify_command` 의 자산별 거부 분기를 기존 시험과 같은 방식으로 고정한다.

---

## 5. 사용자 결정이 필요한 질문

1. 컨테이너 격리에서 워커가 Orca 제어 평면(`orca orchestration send/check`)에 닿는 방식을 무엇으로 할 것인가. (호스트 네트워크 + 이미지 내 orca 바이너리 / 제어 평면 소켓 마운트 / 그 밖)
2. `.env` 를 워크트리에서 완전히 제거할 수 있는가. 워커가 실제로 필요한 값은 무엇이며, 운영 DB 조회는 읽기 전용 실행기(`scripts/db_readonly_query.py`)로 충분한가.
3. 워커에게 네트워크를 허용할 것인가. 허용한다면 어느 호스트(모델 API, Orca 제어 평면)만 열 것인가.
4. Windows 대안의 수용 범위. Windows 에서 agy·codex 는 자체 샌드박스가 있으나 cmd·opencode 는 자체 OS 샌드박스가 문서에 없다. Windows 에서는 컨테이너 격리가 사실상 유일한 대안인가.
5. codex 를 워커로 쓸 것인가. 현재 코드·문서는 codex 를 코디네이터 전용으로 두고 워커 지정을 거부한다.
6. 1단계에서 cmd 를 `--permission-mode dont-ask` 로 바꿀 때, 허용 목록 밖 명령이 프롬프트 대신 즉시 거부되어 워커가 멈추는 빈도가 어느 정도인가. 허용 목록 초기값을 누가 정할 것인가.

---

## 6. 참고 자료

- 저장소 코드: `scripts/orca_auto_approve.py`, `scripts/orca_cmd_launch.py`, `scripts/orca_opencode_launch.py`, `scripts/orca_agy_launch.py`, `scripts/orca_taskctl.py`, `docker-compose.yml`, `Dockerfile`
- 저장소 문서: `docs/ops/orca_control_plane_tools.md`, `docs/handoff/handoff_20261012_z_q_waves_close.md`, `docs/context/CURRENT_STATE.md`
- 벤더 문서: commandcode.ai/docs/permissions, opencode.ai/docs/permissions, antigravity.google/docs/sandbox, antigravity.google/docs/permissions, developers.openai.com/codex/sandboxing
