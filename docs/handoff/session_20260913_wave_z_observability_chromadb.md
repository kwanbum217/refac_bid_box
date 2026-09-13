# 세션 인수인계: 2026-09-13 Wave Z 관측성 실기동과 ChromaDB 1.x 사전 조사

> **작성일**: 2026-09-13
> **작성자**: Claude Opus 5 (코디네이터)
> **기준 커밋**: `6721981a`
> **이어받은 문서**: [`docs/handoff/session_20260912_backlog_closeout.md`](session_20260912_backlog_closeout.md)

---

## 1. 한 줄 요약

전임 인수인계 7장의 1순위였던 관측성 스택 실기동에서 **운영 compose 와 공유하는 설정 결함 세 건**을
찾아 고쳤고, 기한 걸린 공급망 예외 두 건 중 chromadb 는 사전 조사 보고서를 병합했으며 nanoid 는
이미 해소돼 있었습니다. `main` 은 `6721981a` 이며 원격까지 반영했습니다.

---

## 2. 병합 내역

| 커밋 | 내용 | 검증 |
| --- | --- | --- |
| `f7baa082` | 관측성 추적 경로 수정 (코디네이터 직접) | 전량 4,652건 통과, 실기동 종단 확인 |
| `6721981a` | ChromaDB 1.x 사전 조사 보고서 (Wave Z1) | Level 1 게이트 10종 통과, Muse 리뷰 반영, 전량 4,637건 통과 |

---

## 3. 관측성 스택 실기동 결과

`make observability-up` 첫 실행에서 `otel-collector` 가 재시작 루프에 빠졌습니다. 고친 뒤 추적
한 건을 OTLP HTTP 로 보내 **Grafana 경유 Tempo 검색으로 조회되는 것까지** 확인했습니다. Prometheus 의
`otel-collector` 스크랩 대상은 `up` 이고 Grafana Prometheus 데이터소스 헬스는 OK 입니다.

| 결함 | 증상 | 수정 |
| --- | --- | --- |
| `tail_sampling` probabilistic 정책의 `sampling_ratio` | collector-contrib 0.141.0 이 알 수 없는 키로 거부, 기동 불가 | `sampling_percentage: 100` |
| `otlp/tempo` exporter 가 `http://tempo:4318` | gRPC exporter 가 HTTP 포트로 접속해 export 전량 실패 | `tempo:4317` |
| Grafana Tempo 데이터소스 없음 | 추적을 저장만 하고 조회 불가 | `docker/grafana/provisioning/datasources/tempo.yaml` 신설 |

**세 결함 모두 `docker-compose.prod.yml` 도 같은 파일을 마운트합니다.** 운영에서 관측성을 켰다면
추적이 한 건도 남지 않았을 것입니다. 기존 정적 테스트는 YAML 구조만 보고 키 이름과 포트 의미를
검사하지 않아 통과했습니다. `tests/test_prod_compose_topology.py` 에 회귀 테스트 세 건을 넣었습니다.

**판정 기준을 하나 남깁니다.** 수집기 설정은 정적 테스트가 아니라
`docker run --rm -v <설정>:/c.yaml:ro <collector 이미지> validate --config=/c.yaml` 로 판정하십시오.
수정 전 설정은 종료 코드 1, 수정 후는 0 이었습니다.

Grafana 의 Tempo 데이터소스 `/health` 는 `Method not implemented` 를 돌려줍니다. 연결 확인은
`/api/datasources/proxy/uid/tempo/api/search` 로 하십시오.

검증 후 `make observability-down` 으로 내렸습니다. Docker Desktop 은 켜 둔 상태입니다.

---

## 4. 공급망 예외 두 건

### 4.1 nanoid (만료 2026-10-31): 조치 불필요

`frontend/package.json` 의 `overrides` 로 이미 해소돼 있었습니다. `package-lock.json` 은 3.3.19,
`npm audit` 은 0건, allowlist 의 `npm:` 은 빈 목록입니다. 근거로 삼은
`docs/analysis/task_38b3bb325d8e.md` 7장이 뒤처진 기록이었습니다. 로컬 `node_modules` 에만
3.3.16 이 남아 있으니 필요하면 `npm --prefix frontend ci` 를 실행하십시오.

### 4.2 chromadb (만료 2026-12-31): 업그레이드 보류

[`docs/analysis/chromadb_1x_upgrade_plan.md`](../analysis/chromadb_1x_upgrade_plan.md) 의 권고는
**후보 B, 복사본에서 마이그레이션 후 디렉터리 이름 교체**입니다. 제자리 마이그레이션(후보 A)은
상류 `00005-max-seq-id-int.sqlite.sql` 이 원본 `max_seq_id.seq_id` 컬럼을 `DROP` 하므로 기각했습니다.

**같은 날 사용자가 후보 B 를 승인했으나, 스테이징 실측 전에 UNK-03 을 확인한 결과 보류했습니다.**
GitHub Advisory 와 OSV 기준으로 세 CVE 모두 `<= 1.5.9`(PyPI 최신)까지 영향이고 수정 버전이 없습니다.
1.0.0 이상은 인증 전 코드 주입 CVE-2026-45829(critical)가 추가돼 올리면 예외가 네 건이 됩니다. 네 건 모두
Chroma HTTP 서버 경로이고 이 저장소는 `PersistentClient` 만 씁니다. 사용자 결정으로 업그레이드를 보류하고
allowlist 사유를 "상류 미수정, 서버 경로 미노출" 로 고쳤습니다. 상세는 보고서 0장입니다.

UNK-01(HNSW 인덱스 제자리 변환)과 UNK-02(`verify_migration.py` 직접 SQL 호환)는 실측하지 않았습니다.
수정 버전이 나오면 그 버전으로 스테이징 복사본에서 재개하십시오. **원본 `chroma_db/` 를 1.x 로
열지 마십시오.** 원본은 이번에도 어떤 버전으로도 열지 않았습니다.

---

## 5. Wave Z1 에서 리뷰가 잡은 결함

Muse Spark 리뷰가 `fail` 을 냈고 두 건 모두 실제 결함이었습니다. 문서 10줄 안팎이라 재작업 위임
대신 코디네이터가 상류 diff 를 직접 대조해 `686cd4e5` 로 반영했습니다.

| 결함 | 실측 |
| --- | --- |
| 제자리 마이그레이션 비가역 단정에 출처 없음 | PR 3765 diff 로 컬럼 삭제는 확인. 0.6.3 역방향 오픈 실패는 **추론**으로 표시 |
| Rust 필터 성능 향상 주장의 출처 불일치 | 인용한 `types.py` 에 해당 내용 없음. 주장 삭제, 미측정 표시 |

리뷰어가 PR 페이지 요약만으로 세부 문자열을 확인하지 못한 항목은 `.diff` URL 을 직접 받아
해소했습니다. **상류 PR 근거는 페이지가 아니라 `<PR URL>.diff` 로 대조하십시오.**

---

## 6. 운영 관찰 (다음 세션 참고)

### 6.1 자동 승인 실동작 (전임 5장 확인 항목)

| 대화창 | 결과 |
| --- | --- |
| CLI 만족도 설문 | 감시기가 자동 해제. 로그에 기록됨 |
| 셸 명령 승인 | 이번 워커가 승인 대상 셸 명령을 부르지 않아 **미확인** |
| Antigravity `Read URL` 접근 승인 | **감시기가 탐지하지 않습니다.** 워커가 도메인마다 멈춤 |

`Read URL` 대화창은 코디네이터가 스크래치 스크립트로 옵션 2("이 대화에서만 허용")를 눌러 넘겼습니다.
상류 문서 조사가 필요한 Capsule 을 Antigravity 에 줄 때는 이 대화창을 전제하십시오. 감시기에
넣을지는 판단이 필요합니다. 읽기 전용이지만 외부 도메인 접근 승인이기 때문입니다.

### 6.2 `orca_taskctl.py` 터미널 부착 Dispatch 인자

이번 세션에서 두 번 틀렸습니다.

| 틀린 형태 | 결과 |
| --- | --- |
| `--repo <워크트리>` | `launcher_main_repo_write_forbidden`. `--repo` 는 주 저장소, `--worktree` 가 워크트리입니다 |
| `create` 없이 `dispatch --terminal` | `Task not found`. 터미널 경로는 `create` 로 Task 를 먼저 만들고 `--task-id` 와 `--capsule` 을 넘깁니다 |

실패한 첫 시도가 워크트리에 `task_z1_...` Capsule 사본을 남겼고 워커가 그 경로에 `worker_done.json`
을 써서 Level 1 게이트 6 이 실패했습니다. 내용은 계약을 지켰으므로 정규 경로로 옮겨 해소했습니다.

### 6.3 병합 전 증거

`premerge_full_suite_gate.py --record` 는 **병합 대상 브랜치 HEAD 에서** 실행해야 합니다. `main`
에서 병합하면 증거 커밋 불일치로 거부됩니다. 워커 워크트리 안에서 기록한 증거도 주 저장소 병합에서
인정됐습니다.

---

## 7. 다음 착수 순서

| 순서 | 작업 | 선행 조건 |
| :---: | --- | --- |
| 1 | 셸 명령 자동 승인 실동작 확인 | 다음 워커 기동 |
| 2 | Windows 실기 검증 | 장비. G2 유일 잔여 조건 |
| 3 | chromadb 상류 수정 버전 재확인, 있으면 UNK-01·02 스테이징 실측 | 2026-12-31 또는 상류 권고 갱신 |

---

## 8. 자원 정리 상태

| 대상 | 상태 |
| --- | --- |
| Orca Run `run_d38c5a224e54` | Task 2건(`task_68678f51a609` 빌더, `task_9a051992ad00` 리뷰) 모두 `completed` |
| 워커 터미널 | 2대 모두 `worker-release` 후 `retained` 로 남아 `terminal close` 로 종료 |
| 워크트리·브랜치 | `orca-wave-z1`, `fix/otel-tail-sampling-key` 병합 후 제거 |
| 관측성 컨테이너 | `make observability-down` 으로 종료 |
| 감시기 | 워커별 자동 승인 감시기는 회수 시 중지. URL 승인 스크래치 스크립트는 종료 |
| 원격 | `origin/main` = `6721981a` |

`kwanbum217/orca-r15-verify` 브랜치는 다른 세션 소유라 건드리지 않았습니다.
