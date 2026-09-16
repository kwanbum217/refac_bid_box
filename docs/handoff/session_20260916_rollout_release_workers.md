# 세션 인수인계: 2026-09-16 인수인계 잔여 과업 병렬 처리

> **작성일**: 2026-09-16
> **작성자**: Claude Opus 5 (Orca 코디네이터)
> **기준 커밋**: `main` `854f3153`
> **이어받은 문서**: [`docs/handoff/session_20260915_grok_audit_review_and_waves.md`](session_20260915_grok_audit_review_and_waves.md)

---

## 1. 한 줄 요약

2026-09-15 인수인계 6장의 잔여 과업 중 즉시 착수 가능한 네 건을 Orca 워커로 병렬 처리해 모두 병합했고, 그 과정에서 매일 모든 병합을 막는 스냅샷 결함과 릴리스 노트 범위 결함을 찾아 고쳤으며, 첫 사전 릴리스 `v0.1.0-rc.1` 을 draft 로 끝까지 통과시켰습니다.

---

## 2. 병합 내역 (Run `run_62606b0b7a2c`)

| 작업 | 병합 | 내용 | 검증 |
| --- | --- | --- | --- |
| 스냅샷 롤링 날짜 | `7bdf921b` | 정본 스냅샷이 "최근" 질의 창을 절대 날짜로 굳혀 기록 다음 날부터 매일 실패. `relative_to_today` 오프셋으로 오늘 기준 재계산 | 전량 5,055. 계획기 창을 6일에서 7일로 바꾸는 반례에서 테스트가 실패함을 확인 |
| ar4 Thng baseline | `8a156081` | `drift_job` 정본 갱신. 세 카테고리 baseline 이 컨테이너에서 모두 적재됨 | 컨테이너 실측 Servc 925,054 · Thng 18,069 · Cnstwk 1,363,701 건 |
| ar2 신선도 가드 | `11045069` | `scripts/retrain_servc_from_parquet.py` 에 `--max-parquet-age-days`(기본 14)·`--allow-stale-parquet`, `docs/ops/weekly_retrain_verification.md` | 게이트 통과, 전량 5,050, 문서의 `retrain_logs` 조회 명령 실제 실행 확인 |
| ar3 사전 릴리스 | `421f9506` | PEP 440 사전 릴리스를 `v0.1.0-rc.1` 로 정규화, 사전 릴리스일 때만 `--prerelease`. 리뷰어 지적으로 직전 태그 정렬 수정 | 전량 5,055, 리뷰 fail 후 코디네이터 수정 |
| ar1 운영 체크리스트 | `44a47864` | `docs/ops/production_rollout_checklist_20260916.md` 다섯 항목. `backup_least_privilege.md` 의 잘못된 명령 2곳 정정 | 리뷰 3회(fail 7건, fail 3건, pass) |
| 사전 릴리스 버전 | `854f3153` | `pyproject.toml` 0.1.0 -> 0.1.0rc1, 버전 형식 테스트가 사전 릴리스 허용 | 전량 5,064, CI 성공 |

모든 병합의 CI 가 성공했습니다.

---

## 3. 이번 세션에서 드러난 결함

| 결함 | 발견 경로 | 조치 |
| --- | --- | --- |
| 스냅샷 불변 테스트가 2026-09-16 부터 매일 실패 | ar2·ar3 워커가 둘 다 실패 1건을 "범위 밖" 으로 보고. 코디네이터가 `main` 에서 재현 | `7bdf921b`. 워커는 둘 다 원인을 정확히 짚고도 차단 결함임을 알리지 않았음 |
| `_previous_release_tag` 가 사전 릴리스를 정식보다 높게 정렬 | ar3 리뷰어. 코디네이터가 임시 저장소로 재현 | `versionsort.suffix=-`, 회귀 테스트는 수정 전 코드에서 실패함을 확인. `release_process.md` 6.3 의 반대 서술 정정 |
| `test_version_consistency.py` 가 순수 SemVer 만 허용 | 사전 릴리스 버전 상향 후 전량 테스트 | ar3 Capsule 에서 이 테스트를 범위에 넣지 못한 누락. PEP 440 사전 릴리스 허용으로 확장 |
| 운영 체크리스트 차단 결함 10건 | ar1 리뷰어 1·2차 | 존재하지 않는 스크립트, 운영 네트워크에서 불가능한 호스트 DB 접속, 실행하면 기동이 실패하는 되돌리기 3건 등. 1차는 워커 재작업, 2차는 코디네이터 수정 |
| `backup_least_privilege.md` 의 명령 오류 | ar1 리뷰어 | 서브커맨드 누락(`backup --execute`)과 호스트 `mysql` 접속. 체크리스트가 이 문서를 그대로 옮겨 오류가 전파됐음 |
| 워커 감시기 오탐 | `orca_worker_watch.py` 가 기동 직후 세 워커를 "reportPath 누락 실패 정체" 로 표시 | 터미널을 직접 읽어 정상 작업 확인. preamble 의 계약 문구를 화면에서 읽은 것 |
| `check --wait` 가 계속 빈 결과 | 대기 중 `worker_done` 이 이미 도착해 있었음 | **Orca 결함이 아님.** 코디네이터가 `timeout 900 orca ...` 로 감쌌는데 macOS 에 `timeout` 이 없어 `command not found`(exit 127)로 즉시 끝났고, 파서가 `{` 없는 오류 문자열을 "빈 결과" 로 삼켰음. 같은 날 후속 세션에서 래퍼 없이 재현해 배달 도착 16초 만에 반환됨을 확인 |

게이트 6 이 ar2·ar3 에서 실패했으나, 워커가 보고한 스냅샷 실패 1건이 코디네이터 수정 후 통과로 바뀌어 보고와 재실행이 어긋난 것입니다. 나머지 게이트는 전부 통과했습니다.

---

## 4. 사전 릴리스 실행 결과

| 항목 | 값 |
| --- | --- |
| 실행 | `35071454058`, `draft=true`, 커밋 `854f3153` |
| 결과 | 준비 검사, 이미지 빌드, Trivy, allowlist 대조, SBOM, digest 전 단계 성공 |
| 릴리스 | `v0.1.0-rc.1` Draft, **prerelease 표시 확인**, 자산 `refac-bid-box-sbom.spdx.json`·`image-digest.txt` |
| 원격 태그 | 0 개 (draft 경로라 태그를 푸시하지 않음) |

GitHub 에는 `v0.1.0` Draft(2026-09-15)와 `v0.1.0-rc.1` Draft 두 초안이 있습니다. 공개 여부와 `v0.1.0` 초안 정리는 담당자 결정입니다.

---

## 5. 남은 과업

| 순서 | 작업 | 선행 조건 |
| :---: | --- | --- |
| 1 | 야간 수집(02:00)과 드리프트 감시(04:00) 결과 확인. 세션 종료 시점 개발 DB 의 `drift_monitor` 기록은 **0 건**이었습니다(이전 야간에는 스택이 내려가 있었음). 오늘 04:00 이 첫 기록이며 세 baseline 을 모두 갖춘 상태라 Thng 이 INSUFFICIENT_DATA 가 아니라 실제 PSI 판정으로 남는지 봅니다 | 개발 스택 기동 유지 |
| 2 | 운영 서버 반영. 절차 정본은 `docs/ops/production_rollout_checklist_20260916.md` | 운영 배포 |
| 3 | 첫 주간 재학습(2026-09-21 월 03:00) 확인. 절차는 `docs/ops/weekly_retrain_verification.md` 2장 | 개발 스택 기동 |
| 4 | 표본 외 재비교 `compare_servc_models_paired.py --year 2026 --since 2026-09-15` | 2026-10 중순 개찰 축적 |
| 5 | Release 초안 두 건의 공개 또는 삭제 | 사용자 결정 |
| 6 | 이전 과업: Windows 실기(G2), chromadb 재확인(2026-12-31) | - |

### 5.1 리뷰어가 남긴 개선 제안 (차단 아님)

| 대상 | 제안 |
| --- | --- |
| 운영 체크리스트 경로 B | 로컬에서 실행하는 rsync 와 운영 서버에서 실행하는 명령이 한 코드 블록에 섞여 있음 |
| 운영 체크리스트 항목 5 | 누락된 변수의 되돌리기 서술 보강 |
| `release_tag` 정규식 | `1.0.0rc1.dev2` 같은 사전 릴리스의 dev 판은 정규화하지 않음(거짓 음성). 현재 쓰지 않는 형식 |

---

## 6. 자원 상태 (세션 종료 시점)

| 대상 | 상태 |
| --- | --- |
| 워크트리·브랜치 | 주 저장소 `main` 하나. 워커 워크트리 5개(`orca-ar1`, `orca-ar2`, `orca-ar3`, `orca-ar1-review`, `orca-ar3-review`)를 병합 확인 후 제거했고 브랜치도 함께 삭제됨. `kwanbum217/orca-r15-verify` 는 이 세션 소유가 아니라 건드리지 않음 |
| Orca | 완료 세션 잔류 없음(`orca_settled_session_audit.py`). 워커·리뷰어 터미널 13개 회수 |
| 비감독 경로 | 빌더는 Antigravity 런처(`dispatch --launcher`), 리뷰어는 grok(`dispatch --return-preamble` 뒤 `terminal send`) 경로라 `worker-release` 가 `no_owned_resource` 로 돌아옴. 창은 `terminal close` 로 직접 닫음 |
| 배경 프로세스 | 이 세션이 띄운 상시 감시기(`orca_worker_watch.py --watch --respawn`) 종료 |
| Docker | **기동 유지.** 야간 관찰을 위해 내리지 않음. 앱은 `./src` 마운트여도 코드를 자동 재적재하지 않으므로 측정 전 `docker compose restart app worker` 필요 |
| 워커 모델 | 빌더 gemini-3.8-flash(low·medium), 리뷰어 grok-4.6 |

### 6.1 다음 세션 시작 절차

| 순서 | 명령·확인 |
| :---: | --- |
| 1 | `curl -s localhost:8000/api/v1/health/ready` 200 확인. 스택이 내려가 있으면 `docker compose up -d` |
| 2 | 야간 결과: `uv run python scripts/db_readonly_query.py --sql "SELECT id, champion_version, challenger_version, status, created_at FROM retrain_logs WHERE trigger_source = 'drift_monitor' ORDER BY id DESC LIMIT 6"` 로 세 카테고리 판정 확인. 드리프트 판정은 별도 테이블이 아니라 `retrain_logs` 에 기록됩니다 |
| 3 | `gh run list --branch main --limit 3` 로 이 인수인계 병합의 CI 확인 |
| 4 | `orca skills get orchestration` 재독 후 조율 시작 |
