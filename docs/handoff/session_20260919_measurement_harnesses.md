# 세션 인수인계: 2026-09-19 측정 하니스 병렬 작업

> **작성일**: 2026-09-19
> **작성자**: Claude Opus 5 (Orca 코디네이터)
> **기준 커밋**: `main` `ec882eee`
> **Orca Run**: `run_1dbced5f03c6`
> **이어받은 문서**: [`session_20260918_night_opus_parallel.md`](session_20260918_night_opus_parallel.md)

---

## 1. 한 줄 요약

전 세션 인수인계 7장에서 지금 착수 가능한 것이 측정 계열 두 건뿐이어서, 워커 2대로 측정 하니스를 병렬 제작해 병합한 뒤 코디네이터가 실측했습니다. 낙찰 목록 N+1 제거의 순개선을 -62.7% 로 확정했고, 사용자가 측정 계정을 만들어 준 뒤 인증 경로 P95 까지 실측을 마쳤습니다.

---

## 2. 이번 세션 병합

| 커밋 | 내용 | 검증 |
| --- | --- | --- |
| `f83bbdad` | 인증 경로 레이턴시 하니스 + 절차서 (w2) | Level 1 pass, 리뷰 pass, 전량 5,108 |
| `8d3409b8` | 읽기 경로 선채움 A/B 하니스 + 측정 전용 플래그 (w1) | Level 1 pass, 리뷰 pass(재작업본), 전량 5,102, mypy 108파일 무결함 |
| `7502c7aa` | `source_commit` 을 `8d3409b8` 로 갱신 | 전량 5,131. CI success |
| `2ab8caa4` | A/B 하니스 재시작 명령 수정 | 전량 5,133. CI success |
| `ec882eee` | 준비 대기 수정 + A/B 실측 확정 보고서 | 전량 5,134. CI success |

워커 모델: 빌더 `gemini-3.8-flash-medium` 2대, 리뷰어 `opencode/muse-spark-1.3-contributor-free` 2대. 리뷰어는 사용자 지시이며 TIER_POLICY 기본 이탈이므로 `WORKER_MODEL_NOTICE` 입니다. 빌더도 배정표 권장(`muse-spark`)보다 상위라 같은 고지 대상입니다.

Antigravity·OpenCode 계열은 `worker-start --agent` 가 받지 않으므로 **터미널 부착 `--inject` 비감독 경로**로 띄웠습니다. `worker-release` 는 네 건 모두 `no_owned_resource` / `retained` 로 돌아왔고 `orca terminal close` 로 창을 닫았습니다.

Run `run_1dbced5f03c6` 의 Task 4건은 전부 `completed` 이고 잔류 세션·워크트리·작업 브랜치는 없습니다.

---

## 3. 확정된 측정 결과

상세는 [`read_path_ab_confirmation_20260919.md`](../analysis/read_path_ab_confirmation_20260919.md) 입니다.

| 경로 | 선채움 ON | 선채움 OFF | 순개선율 |
| --- | ---: | ---: | ---: |
| 낙찰 목록 1쪽 | 75.28ms | 202.01ms | **-62.7%** |
| 낙찰 목록 50쪽 | 76.13ms | 197.58ms | **-61.5%** |
| 홈 컨텍스트 | 69.09ms | 132.25ms | **-47.8%** |

대조군 다섯 경로의 A/B 차이는 +0.19ms ~ +3.94ms 로 전부 판정 기준(±5% 또는 ±5ms) 안입니다. 3 왕복 전 구간 오류 0건입니다.

**전 세션의 "`-64%` 인용 금지" 는 해제됩니다.** 다만 인용할 값은 전 회차 수치가 아니라 위 표입니다. 이 값은 같은 시각 A 와 B 의 차이이며 절대값 자체를 주장하지 않습니다.

---

## 4. 이번 세션에서 드러난 사실

| 사실 | 근거 | 조치 |
| --- | --- | --- |
| 병합된 측정 도구가 실행조차 되지 않는 상태였다 | `docker compose up` 에 `-e` 옵션이 없고, compose 의 `app` 환경 목록에 변수도 없었다 | compose 전달 추가 + 셸 환경변수 주입으로 교체 (`2ab8caa4`) |
| 변체 전환 뒤 5초 고정 대기로는 부족하다 | 컨테이너 재생성에 30초 안팎. 첫 실행에서 A 1왕복을 뺀 전 구간이 요청 100/100 실패 | `health/ready` 200 폴링으로 교체 (`6289e15c`) |
| 측정 실패가 결과표에서 정상처럼 보였다 | 빈 값을 `-` 로 채워 표를 그대로 출력했다 | 표본 0건이면 즉시 예외로 중단하도록 고쳤다 |
| **Level 1 게이트와 독립 리뷰가 위 셋을 모두 통과시켰다** | 세 검증 모두 명령의 실재 여부와 실제 실행 결과를 검사하지 않는다 | **측정·운영 도구는 병합 뒤 코디네이터가 한 번 실제로 돌려 본 뒤에 신뢰한다** |
| 코디네이터가 승인한 범위 확장은 Capsule 에 반영해야 한다 | `.env.example` 승인을 회신으로만 주어 게이트 2가 범위 초과로 실패했다 | Capsule 의 `allowed_write_files` 를 갱신한 뒤 게이트를 재실행했다 |
| `orca_taskctl.py rework` 가 만든 Task 는 Orca 에 등록되지 않는다 | 리뷰어의 1차 `worker_done` 이 `unknown task task_4946d8699d9b_rework` 로 거절됐다 | 보고서 파일은 정상 생성되며 계약 검증도 가능하다. Task 참조 없이 보낸 두 번째 통보가 접수됐다 |
| `orca orchestration check --wait` 가 즉시 빈 결과로 돌아온다 | `--timeout-ms 1800000` 을 줘도 곧바로 반환. 6회 반복해도 같다 | 커밋 발생과 배달함 소진을 조건으로 하는 배경 루프로 대체했다 |
| heartbeat 배치를 ack 하지 않으면 뒤의 질문이 묻힌다 | w1 의 `.env.example` 질문이 FIFO 뒤에 있어 늦게 드러났다 | 대기 루프가 heartbeat 도 ack 하도록 고쳤다 |
| 워커 컨테이너 로그 시각은 로컬, DB 시각은 UTC 다 | 워커 기동 로그 `11:53`(KST)과 `pipeline_executions.started_at` `02:53`(UTC)이 같은 사건이다 | 크론 시각 판단은 컨테이너 로컬 기준으로 한다 |

---

## 5. 스택 및 데이터 상태

| 대상 | 상태 |
| --- | --- |
| 수집 | `pipeline_executions` id=22 `success` (2026-09-19 02:53:10~03:02:33 UTC). 스택 기동 시 따라잡기 |
| 드리프트 | `retrain_logs` 최신은 여전히 id=9 (2026-09-18). 크론은 워커 컨테이너 로컬 04:00 이라 오늘치는 아직 도래 전 |
| Docker | app/db/redis/meilisearch/worker 기동. ready 200. app 은 A/B 측정 중 여섯 번 재생성했고 마지막 상태는 **선채움 OFF 변체일 수 있음** |
| CI | `ec882eee` 까지 전 건 success |

> **주의**: A/B 측정 마지막 구간이 B(선채움 OFF)였습니다. 다음 세션은 다른 측정을 하기 전에 `docker compose up -d --no-deps --force-recreate app` 으로 기본값(선채움 ON)으로 되돌리십시오. 환경변수를 주지 않으면 compose 기본값 `true` 가 적용됩니다.

---

## 6. 사용자 결정 (유지)

전 세션에서 이어받은 결정이며 이번 세션에서 바뀐 것은 없습니다.

| 항목 | 결정 | 실행 |
| --- | --- | --- |
| 운영 반영 | 경로 A (운영에서 재학습·승격) | 미실행. 운영 서버 접근 없음 |
| GitHub Release | `v0.1.0` 과 `v0.1.0-rc.1` 둘 다 초안 유지 | 공개·삭제·태그 push 없음 |
| 용역 표본 외 재비교 | 2026-10 중순 이후 | 지금 Dispatch 금지 |
| 20260909 backfill | 2026-09-18 승인·완료 | 추가 수집 금지 |

이번 세션의 새 결정입니다.

| 항목 | 결정 |
| --- | --- |
| 인증 경로 측정 계정 | 사용자가 측정 전용 계정 `sojiroh`(id=16)를 직접 만들어 자격증명을 주입했다. 비밀번호는 저장소에 두지 않으며 코디네이터는 측정 후 주입 파일을 삭제했다 |

---

## 7. 다음 세션이 확인할 과업

| 시점 | 과업 | 확인 방법 |
| --- | --- | --- |
| 완료 | 인증 경로 P95 실측 | 결과는 [`auth_path_latency_20260919.md`](../analysis/auth_path_latency_20260919.md). 최적화 후보 없음 |
| 스택 기동 후 | 수집·드리프트 진행 | 전 인수인계 6.1 절차 |
| 2026-09-21 03:00 이후 | 첫 주간 재학습. 자동 승격 없는지 | [`weekly_retrain_verification.md`](../ops/weekly_retrain_verification.md) |
| 운영 접근 확보 시 | 경로 A. **ml_registry 재생성이 선행** | [`ml_registry_production_bootstrap.md`](../ops/ml_registry_production_bootstrap.md) |
| 2026-10 중순 이후 | 용역 표본 외 재비교 | `compare_servc_models_paired.py --year 2026 --since 2026-09-15` |
| 장비 확보 시 | Windows Docker Desktop 실기 | G2 보류 |
| 2026-12-31 | chromadb CVE 재확인 | 수정 버전 없으면 업그레이드 재제안 금지 |

**인증 경로 측정은 `POST /api/v1/evaluations/analyze` 를 포함하지 않습니다.** 그 경로는 `_save_snapshot_async` 로 스냅샷을 저장하는 부작용이 있어 제외했습니다. 전 인수인계가 이 경로를 측정 대상으로 지목했으나, 동시성 100회를 던지면 스냅샷이 누적됩니다. 측정 대상은 부작용 없는 `GET /accounts/me`, `GET /evaluations/profiles`, `GET /evaluations/snapshots` 세 건입니다.

---

## 8. 하지 말 것

- `docker compose down -v` 로 볼륨을 지우지 마십시오.
- 운영 서버 없이 경로 A 를 로컬에서 실행하지 마십시오.
- chromadb 를 수정 버전 없이 1.x 로 올리지 마십시오.
- Release 초안을 사용자 확인 없이 공개하거나 삭제하지 마십시오.
- `main` 에 직접 커밋하지 마십시오.
- `TRIGGER_RETRAIN` 을 보고 재학습·승격을 자동 실행하지 마십시오.
- 20260909 를 다시 backfill 하지 마십시오.
- 주간 재학습을 09-21 전에 enqueue 하지 마십시오.
- **`READ_PATH_PRELOAD_ANNOUNCEMENTS` 를 운영에서 `false` 로 두지 마십시오.** 측정 전용 스위치이며 끄면 낙찰 목록 P95 가 세 배가 됩니다.
- **측정 계정을 새로 만들거나 자격증명을 문서·커밋에 남기지 마십시오.**
- 저장소가 조용하지 않을 때 A/B 를 재지 마십시오. 대조군이 흔들려 회차가 무효가 됩니다.
- `orca terminal close --tab` 을 쓰지 마십시오. 코디네이터 창까지 닫힙니다.
