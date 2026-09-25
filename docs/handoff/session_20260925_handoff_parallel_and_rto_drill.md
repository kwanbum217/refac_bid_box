# 세션 인수인계: 2026-09-25 인수인계 잔여 과업 병렬 처리와 restore drill 재측정

> **작성일**: 2026-09-25
> **작성자**: Claude Opus 5.5 (Orca 코디네이터)
> **기준 커밋**: `main` `ef93ad2b`
> **Orca Run**: `run_073ce2b70842` (워커 터미널 전부 회수)
> **이어받은 문서**: [`session_20260923c_qualification_badge_and_filter.md`](session_20260923c_qualification_badge_and_filter.md)

---

## 1. 한 줄 요약

직전 인수인계의 잔여 과업 셋을 처리했습니다. 런북 키 로드 한 줄(T1)과 코디네이터 직접 작성 브랜치용 최소 Capsule 명령(T2)은 빌더 두 대가 병렬로 구현해 병합했고, restore drill 과 재색인(T3)은 코디네이터가 저장소를 동결한 채 연속 측정했습니다. RTO 는 재색인 포함 약 2,444초(약 41분)로 모든 단계가 자기 예산 안입니다.

---

## 2. 병합 결과

| 과업 | 병합 | 내용 | 검증 |
| --- | --- | --- | --- |
| T1 런북 `MEILI_MASTER_KEY` 로드 | `28d3b292` | 런북 4.3.1 의 curl 확인 명령 앞에 `.env` 에서 키를 읽는 한 줄(`grep '^MEILI_MASTER_KEY=' .env \| cut -d= -f2-`)을 더했다 | 빌더 `846e787d`(cmd DeepSeek V4.1 Flash), 리뷰 pass(`task_1bccf516ad74`, OpenCode Muse Spark, `=` 가 든 값과 접두 겹침 재현), strict 게이트 11/11, 전량 5,382, CI 성공 |
| T2 `coordinator-capsule` | `3e3bf9be` | `scripts/orca_taskctl.py coordinator-capsule --slug --objective --scope [--out] [--json]` 이 Orca Task 없이 최소 Capsule 을 만든다. 조율 스킬 4.2 절 세 미러와 control plane 문서 3.1 표에 절차를 적었다. 게이트 코드는 바꾸지 않았다(게이트 2 의 Capsule 미지정 건너뜀은 이미 `--strict` 에서 실패한다) | 빌더 `ab2c7cdb`, 리뷰 pass(`task_7c23e4e9c67d`, 경로 가드 6종 직접 실행, src·scripts·frontend 능력 대조), strict 게이트 11/11(`--verify "uv run mypy src"`), 전량 5,390, CI 성공 |
| T4 `coordinator-capsule` 보고 선언 제거 | `c4da1c32` | T2 도구가 만든 Capsule 에 워커용 `report_path` 가 들어가 게이트 6 이 fail, 문서의 `--strict` 절차가 어느 코디네이터 브랜치에서도 통과하지 못했다. 생성 결과에서 `report_path`, `return_contract`, 보고 파일 항목 세 줄만 지운다. `expand` 경로와 게이트 코드는 그대로다 | 빌더 `3c19f822`, 리뷰 pass(`task_e6d9116889cc`, main 과 expand 출력 동일 확인), strict 게이트 11/11, 전량 5,392. 코디네이터가 이 문서 브랜치로 종단 실행해 strict 종료 코드 0 확인 |

사용자 결정(2026-09-25): 게이트 2 문제는 "최소 Capsule 의무화" 안, restore drill 은 이번 세션 실행.

---

## 3. restore drill 과 재색인 측정

측정 동안 커밋·병합을 멈췄고, 재색인은 drill 종료를 기다리는 배경 스크립트로 이어 붙였다. 두 측정은 같은 MySQL 컨테이너를 쓰므로 겹치지 않게 했다.

### 3.1 drill (`data/backups/restore_drill_report_20260925.json`)

| 단계 | 2026-09-25 | 2026-09-22 |
| --- | ---: | ---: |
| 스냅샷 검증 | 2.1초 | 2.0초 |
| 아카이브 해제 | 16.6초 | 15.5초 |
| G1 파일 검증 | 20.8초 | 3.2초 |
| DB import | 1,429.2초 | 1,391.6초 |
| G1 DB 검증 | 3.6초 | 7.9초 |
| 정리 | 4.9초 | 3.6초 |
| 총계 | 1,477.4초, G1 PASS | 1,423.9초, G1 PASS |

같은 스냅샷(`snapshot_20260921_061612`)이다. 호스트 mysql 26.7 은 인증 플러그인이 없어 `MYSQL_CLIENT_CONTAINER=refac_bid_box-db-1` 로 실행했다.

**DB import 1.7배 판정 (N3 로 정정).** 처음에는 같은 날 같은 스냅샷의 차이 2.7% 만 보고 "전부 스냅샷 차이" 라고 적었으나 틀렸다. N3 에서 2026-09-11 스냅샷을 같은 날 다시 돌리니 그날 823.9초가 1,151.4초였다(같은 데이터에서 1.40배, 환경 요인). 같은 날 두 스냅샷끼리는 1,151.4초 대 1,429.2초(1.24배, 스냅샷 요인)이고 1.40 × 1.24 = 1.74 다. 스냅샷 요인 약 278초 중 약 260초가 커버링 인덱스가 추가된 두 테이블(`bid_announcements` +208초·+22%, `bid_results` +52초·+31%, 데이터 크기는 +0.3~0.7%)에 있어 인덱스 유지 비용으로 판정했다. 환경 요인의 정체는 특정하지 못했다. 보고서는 `data/backups/restore_drill_report_20260925_snap0911.json`(G1 PASS, 총 1,182.8초).

### 3.2 재색인

| 항목 | 2026-09-25 | 2026-09-22 |
| --- | ---: | ---: |
| 클라이언트 적재 | 687.9초 | 581.9초 |
| 서버 색인 완료 대기 | 263.2초 | 257.4초 |
| 전체 | **951.2초** | 839.3초 |
| 문서 / 실패 작업 | 8,318,760 / 0 | 8,318,760 / 0 |
| 색인 크기 / 클라이언트 최대 RSS | 23.3GB / 약 188MB | 21.8GB / 약 185MB |

빈 임시 Meilisearch v1.14(127.0.0.1:7701, 전용 볼륨, 일회용 키), `MEILI_TIMEOUT_SECONDS=30`. 늘어난 몫은 클라이언트 적재에 있고, 그 사이 공고 문서마다 `qualification_analyzable` 판정이 더해졌다. 예산 42분 안이다. 임시 컨테이너와 볼륨은 측정 뒤 삭제했다.

`docs/ops/rpo_rto_policy.md` 3장 단계표와 근거 문단, 런북 4.3.1 의 인용 수치를 갱신했다.

---

## 4. 이번 세션에서 드러난 사실

| 사실 | 조치 |
| --- | --- |
| `orca worktree rm` 은 워크트리와 함께 병합된 로컬 브랜치까지 지운다 | 뒤이은 `git branch -d` 가 "not found" 를 낸다. 제거 전에 `git log main..<branch>` 가 비었는지 확인하는 순서를 유지한다 |
| `dispatch-show` 결과에는 워커 터미널 핸들이 없다 | 회수 시 핸들은 `worker_done` 뒤 `orca terminal list` 나 Dispatch 영수증에서 가져온다 |
| G1 파일 검증이 같은 스냅샷에서 3.2초에서 20.8초로 늘었다 | N4 조사: 단계 본체는 `verify_migration.py` 의 모델·chroma 원본 SHA256 순차 해시라 페이지 캐시에 민감하고, 코드·매니페스트는 구간 내 불변이다. 환경 요인 유력(추정). N3 drill 에서는 3.9초였다. 확정하려면 하위 구간 타이머를 넣고 웜·콜드 재측정 |
| 게이트·훅을 새로 만드는 과업은 첫 병합이 곧 첫 실사용이다 | N1 병합 때 증거 없이 병합을 시도해 훅이 거부함을 확인했고, 증거 기록 뒤 같은 병합을 커밋해 통과시켰다. 거부 직후 `git merge --abort` 가 훅이 건드린 파일 시각 때문에 "not uptodate" 로 실패했으나 내용 차이는 없어 병합 상태를 유지한 채 마무리했다 |
| T2 의 인수 조건에 '생성 Capsule 로 strict 게이트 종단 실행' 이 없어 빌더·리뷰어 모두 게이트 6 결함을 놓쳤다. 첫 실사용(이 문서 브랜치)에서 드러났다 | T4 로 고쳤고, 게이트·훅을 만드는 과업의 인수 조건에는 실제 입력으로 끝까지 돌리는 종단 검증을 넣는다 |

---

## 5. 다음 세션 할 일

### 5.1 같은 세션에서 끝낸 N 웨이브 (사용자 선택 2026-09-25)

| 과업 | 결과 | 검증 |
| --- | --- | --- |
| N1 `task_5ad1df7950b9` main 병합 훅의 Level 1 strict 증거 강제 | 병합 `ef93ad2b`. `orca_level1_gate.py --strict --record-evidence` 가 pass 일 때만 공통 `.cache/level1_strict_evidence.json` 을 쓰고, prepare-commit-msg 훅 `premerge_level1_gate.py` 가 main 병합에서 증거 commit 과 MERGE_HEAD 를 대조한다 | 리뷰 pass(`task_43a06ce5aa60`), strict 11/11, 전량 5,417. 증거 없는 병합 거부와 증거 기록 뒤 통과를 실제 병합으로 확인 |
| N2 `task_c9613bff5f5d` 런북 4.4.2, 조율 스킬 8.1 보강 | 병합 `44391fb9` | 리뷰 pass(`task_674a8853bf50`), strict 11/11, 전량 5,392 |
| N4 `task_342830314b94` G1 파일 검증 시간 조사 | 4장 표. 코드 변경 없음, 보고서는 `.orca/capsules/task_342830314b94/` | 코디네이터가 구간 내 변경 2건이 이 단계 밖임을 git 이력으로 확인 |
| N3 1.7배 원인 확정 drill | 3.1 절. 환경 1.40배 × 스냅샷 1.24배 | 보고서 JSON 커밋 |

**이제 모든 main 병합에 Level 1 strict 증거가 필요하다.** 병합 전 순서는 `orca_level1_gate.py ... --strict --record-evidence`, `premerge_full_suite_gate.py --record`, `git merge --no-ff` 다. 워커 브랜치와 코디네이터 브랜치(`coordinator-capsule`) 모두 같다.

### 5.2 다음 세션

| 순서 | 할 일 | 근거와 주의 |
| --- | --- | --- |
| 1 | 이 문서 병합의 CI 확인 | |
| 2 | (선택) DB import 환경 요인 1.40배의 정체 | 같은 스냅샷이 2026-09-11 823.9초, 2026-09-25 1,151.4초. MySQL 설정·버퍼·Docker 자원 할당 차이부터 본다 |
| 3 | (선택) G1 파일 검증 하위 구간 타이머와 웜·콜드 재측정 | N4 권고. 합계 영향은 작다 |
| 4 | OP-3 주간 재학습, `test_benchmark_offload_loop_lag` 흔들림 | 변동 없음. 이번 세션 CI 는 모두 처음부터 성공 |

---

## 6. 자원 상태

| 대상 | 상태 |
| --- | --- |
| Git | `main` 은 이 문서 병합 후 clean, 원격 반영. 워커 워크트리 0건, 작업 브랜치는 이 문서 브랜치뿐이며 병합 후 삭제 |
| Orca | Run `run_073ce2b70842` Task 11건 completed(T1·T2·T4·N1·N2 와 각 리뷰, N4), 워커 터미널 전부 닫음, 배달 큐 비움. 터미널 목록의 narani_homepage 창들은 다른 프로젝트라 건드리지 않았다 |
| Docker | db 컨테이너만 실행 중. 임시 Meilisearch 는 삭제. 컴퓨터를 끄기 전에 `docker compose stop` 으로 내린다 |
| 배경 프로세스 | 상시 워커 감시기는 워커 회수와 함께 중지 |
