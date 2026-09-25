# 세션 인수인계: 2026-09-25 인수인계 잔여 과업 병렬 처리와 restore drill 재측정

> **작성일**: 2026-09-25
> **작성자**: Claude Opus 5.5 (Orca 코디네이터)
> **기준 커밋**: `main` `3e3bf9be`
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

**DB import 1.7배 판정.** 같은 스냅샷의 실행 간 차이가 2.7% 이므로 2026-09-11 대비 1.7배는 스냅샷 차이에서 온다. 처음 기록한 `database_import_breakdown` 에서 `bid_announcements` 데이터 구간이 1,163.7초(81.7%)이고 이 테이블에 2026-09-11 이후 커버링 인덱스 `ix_bid_ann_inst_cat_ntce` 가 추가됐다. 인덱스 유지 비용 가설과 맞지만 인덱스 비용이 데이터 구간에 섞여 있어 확정하지 않았다.

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
| G1 파일 검증이 같은 스냅샷에서 3.2초에서 20.8초로 늘었다 | 합계 영향은 작다. 같은 호스트의 다른 프로젝트 작업과 겹쳤다. 다음 drill 에서 반복되면 조사한다 |
| 이 문서 브랜치는 코디네이터 직접 작성이다 | T2 의 `coordinator-capsule` 로 최소 Capsule 을 만들어 strict 게이트를 돌렸다(첫 실사용) |

---

## 5. 다음 세션 할 일

| 순서 | 할 일 | 근거와 주의 |
| --- | --- | --- |
| 1 | 이 문서 병합의 CI 확인 | |
| 2 | (선택) 2026-09-11 스냅샷으로 drill 을 돌려 `bid_announcements` 구간을 비교해 1.7배 원인 확정 | 약 25분, Docker·DB 독점. 저장소 동결 필요 |
| 3 | OP-3 주간 재학습 | worker 는 A안대로 정지 유지. 변동 없음 |
| 4 | `test_benchmark_offload_loop_lag` 의 CI 흔들림이 반복되면 기준값이나 러너 조건을 재검토 | 이번 세션 CI 3건은 모두 처음부터 성공 |

---

## 6. 자원 상태

| 대상 | 상태 |
| --- | --- |
| Git | `main` 은 이 문서 병합 후 clean, 원격 반영. 워커 워크트리 0건, 작업 브랜치는 이 문서 브랜치뿐이며 병합 후 삭제 |
| Orca | Run `run_073ce2b70842` Task 4건 completed, 워커 터미널 전부 닫음, 배달 큐 비움. 터미널 목록의 narani_homepage 창들은 다른 프로젝트라 건드리지 않았다 |
| Docker | db 컨테이너만 실행 중. 임시 Meilisearch 는 삭제. 컴퓨터를 끄기 전에 `docker compose stop` 으로 내린다 |
| 배경 프로세스 | 상시 워커 감시기는 워커 회수와 함께 중지 |
