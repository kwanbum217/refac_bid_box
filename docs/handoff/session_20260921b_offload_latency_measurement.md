# 세션 인수인계: 2026-09-21 오프로드 레이턴시 실측과 D8 회귀 발견

> **작성일**: 2026-09-21
> **작성자**: Claude Opus 5 (Orca 코디네이터)
> **기준 커밋**: `main` `29a8202e`
> **Orca Run**: `run_0601d2861203`
> **이어받은 문서**: [`session_20260921_d7d9_review_merge.md`](session_20260921_d7d9_review_merge.md)

---

## 1. 한 줄 요약

병합된 오프로드들의 효과를 처음으로 실측했습니다. **D1(요약 재집계)은 워커 이벤트 루프를 최대 29.6초 막던 것을 11ms 로 줄인 확실한 성과**이고, D2·D7·D9 는 정상 상태에서 차이가 측정 해상도 이하입니다. **D8(홈 최근 공고 선별)은 개선이 아니라 회귀**로 드러나 사용자 승인에 따라 점진 확대 방식으로 다시 썼으나, **그 수정(L4)과 실측 보고서(L3)는 아직 병합되지 않았습니다.**

---

## 2. 이번 세션 병합

| 병합 커밋 | 내용 | 검증 |
| --- | --- | --- |
| `0aca1363` | D8 실측 하니스 `scripts/benchmark_home_recent_selection.py` + `source_commit` 을 `772082ba` 로 갱신 | 리뷰 pass, Level 1 11/11, 전량 5,222 |
| `29a8202e` | loop lag 실측 하니스 `scripts/benchmark_offload_loop_lag.py` | 리뷰 pass, Level 1 11/11, 병합 트리 전량 5,245 |

워커 모델: 빌더 Command Code `deepseek/deepseek-v4.1-flash`(하니스 `high`, D8 재작성 `max`), 리뷰어 OpenCode `opencode/muse-spark-1.3-contributor-free`. 전부 터미널 부착 비감독 경로이며 회수는 `release-worker` 후 `orca terminal close` 로 했습니다.

---

## 3. 병합 대기 브랜치 (다음 세션이 먼저 할 일)

| 브랜치 | 커밋 | 내용 | 리뷰 | Level 1 | 남은 조치 |
| --- | --- | --- | :---: | :---: | --- |
| `kwanbum217/orca-l3` | `3f610441` | 실측 보고서 `docs/analysis/offload_latency_20260921.md` + 원시 결과 JSON 2개 | **pass** | **게이트 6 실패** | 보고서만 재작업 후 병합 |
| `kwanbum217/orca-l4` | `907f877b` | D8 점진 확대 재작성 | **미실시** | 미실시 | 리뷰 -> 게이트 -> 병합 -> 재측정 |

워크트리는 `/Users/kwanbum/orca/workspaces/refac_bid_box/orca-l3`, `orca-l4` 에 그대로 있습니다. **병합 전에 지우지 마십시오.** 유일본입니다.

### 3.1 L3 게이트 6 실패의 원인과 처리

원인은 보고서 **내용이 아니라 `worker_done.json` 형식** 하나입니다. `verification[3].command` 가 852자로 상한 600자를 넘어 계약 비대 위반이 되고, 그 결과 실효 verdict 가 `blocked` 입니다. 보고서 수치는 리뷰어가 부록 명령과 독립 명령으로 전수 대조했고 코디네이터도 핵심 수치 16개를 원시 JSON 과 대조해 일치를 확인했습니다. 원시 JSON 의 sha256 앞 12자리는 `loop_lag.json` `fd25a383d65d`, `home_recent.json` `b97de85f8e68` 이며 코디네이터가 넘긴 원본과 같습니다.

처리는 `python3 scripts/orca_taskctl.py rework` 로 재작업 Task 를 발급하고 `--effort default` 로 보고서만 다시 쓰게 하는 것입니다. 긴 재계산 명령은 verification 이 아니라 보고서 부록에만 두고, verification 에는 `python3 scripts/validate_agent_rules.py --quiet` 처럼 짧은 명령만 적게 하십시오. **코디네이터가 워커 보고를 직접 고쳐 게이트를 통과시키지 마십시오.**

L4 가 병합된 뒤에는 이 보고서에 D8 재측정 결과를 덧붙여야 합니다(5장). 보고서의 D8 처분 표에는 점진 확대 선택지가 없습니다. 사용자 결정이 보고서 작성 뒤에 나왔기 때문입니다.

### 3.2 L4 가 한 일

`src/app/services/home_context.py` 의 `_recent_unique_announcements` 가 전역 정렬 접두를 표본 50·200·1000 순서로 **필요할 때만** 읽고(`ordered_prefix`), 윈도 표본은 그 접두에서 `collected_at >= window_start` 로 메모리에서 거릅니다. 접두가 요청 크기보다 짧게 돌아오면 테이블이 바닥난 것으로 보고 더 읽지 않습니다. 빌더 보고 기준으로 흔한 형상은 질의 1회·LIMIT 50, 희소 형상은 최대 3회이고 legacy 는 4~12회였습니다. **기존 동일성 테스트 11건이 단언 변경 없이 통과**했고 전량 5,255 passed, mypy 무결, 규칙 21/21 입니다. 코디네이터가 diff 를 읽어 설계 계약(오프셋 미사용, 상수·시그니처 불변)을 확인했으나 **독립 리뷰는 하지 않았습니다.**

리뷰 Capsule 은 Intent `.orca/intents/run_offload_latency_20260921/l4_d8_progressive.yaml` 의 `review_checklist` 여섯 항목을 **한 글자도 바꾸지 말고** 복사하십시오. 리뷰 Intent 에는 `report_path` 를 명시해야 합니다(6장).

---

## 4. 확정된 실측 결과 (main `29a8202e`)

측정 조건: Docker 는 `db`·`redis` 만 기동, 정규화 load average L1 중앙 28.2%·최대 39.1%, L2 중앙 26.3%·최대 28.6%(규약 5.3 기준 안), 버퍼풀 2GB, 공고 5,515,517행. A 는 대상 함수를 이벤트 루프에서 직접 부른 오프로드 전 동작, B 는 `asyncio.to_thread` 로 부른 현재 동작입니다. 값은 세 회차 중 최악값입니다.

| 대상 | A 최대 루프 정지 | B 최대 루프 정지 | 판정 |
| --- | ---: | ---: | --- |
| D1 공고 요약 재집계 | 29,595.26ms | 11.17ms | 효과 확정 |
| D1 낙찰 요약 재집계 | 697.99ms | 1.58ms | 효과 확정 |
| D1 기관명 캐시 갱신 | 396.48ms | 28.31ms | 효과 확정 |
| D7 오늘 공고 COUNT | 2.36ms | 0.60ms | 정상 상태 미미 |
| D2 claim 주기, D9 heartbeat | 0.1~0.2ms | 0.1~0.2ms | 판정 불가(해상도 이하) |
| D9 스케줄 결과 기록 | 1.05ms | 9.05ms | 판정 불가(단발 표본) |
| D2 따라잡기 판정 | - | - | **측정 불성립** |

D8 은 전체 최근 공고 기준 현재 구현 중앙값 34.32~35.26ms, 변경 전 구현 2.05~2.11ms 로 **약 16배 느린 회귀**였습니다. 다섯 시나리오 전부, 세 회차 전부 같은 방향이고 두 구현의 선별 결과는 전부 동일했습니다.

**인용 규칙**: 위 표는 인용해도 됩니다. D1 은 집단·회차당 표본이 1개라 분포 통계가 아니며 방향 판정만 확정입니다.

---

## 5. 다음 세션 순서 (고정)

1. **L4 독립 리뷰**를 Muse Spark 리뷰어로 붙입니다. `builder_provider: cmd`, 리뷰 Intent 에 `report_path` 명시.
2. **L3 보고서 재작업**을 `default` 등급으로 병렬 Dispatch 합니다. 두 작업은 파일이 겹치지 않습니다.
3. L4 리뷰가 pass 면 Level 1 게이트(`--tests` 와 `--verify "uv run mypy src"` 를 한 쌍으로) 후 병합합니다. 병합은 직렬입니다.
4. **D8 을 재측정합니다.** `docker compose up -d db redis` 만 띄우고(`worker` 는 따라잡기 수집 때문에 띄우지 않음) `uv run python scripts/benchmark_home_recent_selection.py --rounds 3 --repeats 30 --warmup 3 --output data/benchmarks/offload_latency_20260921/home_recent_progressive.json` 를 돌립니다. 기대값은 current 가 legacy 와 같은 수준(약 2ms)입니다.
5. 재측정 결과를 L3 보고서에 부록으로 덧붙이고 병합합니다.
6. `source_commit` 은 현재 `772082ba` 입니다. 5커밋을 넘기 전에, **묶음의 첫 병합에** 갱신하십시오.

**그때까지 main 의 D8 은 회귀 상태**입니다. 홈 캐시 예열 1회당 약 150~175ms 가 더 듭니다. 사용자 경로의 응답 지연은 아니며 수집 후 예열 꼬리에서 발생합니다.

---

## 6. 이번 세션에서 드러난 사실

| 사실 | 근거 | 조치 |
| --- | --- | --- |
| **정적 조사의 N+1 판정이 실제 데이터에서 틀렸다** | D8 조사는 이중 순회를 가정했으나 실제로는 변경 전 구현도 첫 표본 50행에서 limit 을 채워 질의 1회로 끝났다 | 질의 축약 과제는 **착수 전에 실데이터로 질의 수를 실측**할 것. 정적 조사 보고서의 "예상 기여" 를 근거로 구현하지 말 것 |
| **리뷰어 보고서가 `worker_done.json` 으로 써지는 원인은 도구 문구다** | `scripts/orca_taskctl.py` 3306행 부근이 Intent 의 `report_path` 를 읽고, 없으면 역할과 무관하게 `worker_done.json` 을 preamble 에 넣는다 | 리뷰 Intent 에 `report_path` 를 명시하면 해소된다. 이번 세션 L1·L3 리뷰어는 명시 후 `review_done.json` 으로 바로 썼다. 도구 수정(역할별 기본값)은 미실시 |
| **런처 경로 Dispatch 는 `--repo` 가 주 저장소여야 한다** | `--repo` 에 워크트리를 주면 `launcher_main_repo_write_forbidden` 로 거부 | `--repo <주 저장소> --worktree <격리 트리>` 로 준다 |
| 새 워크트리에는 `.orca/` 가 없다 | `orca worktree create` 직후 `.orca/capsules` 부재 | `mkdir -p` 후 해당 Task 의 Capsule 디렉터리만 복사 |
| `.env` 복사는 권한 분류기가 막을 수 있다 | L1 워크트리 복사가 거부됨 | DB 에 접속하지 않는 빌더는 `.env` 가 필요 없다. `tests/conftest.py` 가 `SECRET_KEY` 를 채운다 |
| 긴 재계산 명령을 verification 에 넣으면 게이트 6 이 막힌다 | L3 의 852자 명령 | 재계산 명령은 보고서 부록에만 두라고 Capsule 에 못 박을 것 |
| 호스트 설정과 운영 워커 설정이 다르다 | `AUTOMATION_SCHEDULE_CATCHUP_ENABLED` 가 호스트 기본 False, compose 워커 true | D2 따라잡기 판정을 재려면 호스트 환경변수로 켜서 돌려야 한다. 단 실제 따라잡기가 돌지 않게 판정 함수만 부르는지 먼저 확인 |

---

## 7. 자원 상태

| 대상 | 상태 |
| --- | --- |
| Git | 주 저장소 `main`, 원격 반영 완료. **미병합 작업 브랜치 2개**(`orca-l3`, `orca-l4`) |
| 워크트리 | `orca-l3`, `orca-l4` 유지. 병합 전 제거 금지. `orca-l1`, `orca-l2` 는 병합 후 제거 완료 |
| Orca Run | `run_0601d2861203`. 워커 Task 전부 `completed`, 배달 큐 비움, 워커 터미널 전부 회수 |
| 원시 결과 | 주 저장소 `data/benchmarks/offload_latency_20260921/` 에 미추적 파일로 존재. 정본은 `orca-l3` 브랜치의 커밋본이다 |
| Docker | 세션 종료 전 `db`·`redis` 를 `docker compose stop` 으로 정지(볼륨 보존)하고 Docker Desktop 을 종료 |
| 배경 프로세스 | 자동 승인 감시기와 상시 워커 감시기 종료 |

---

## 8. 하지 말 것

- **D2·D7·D9 의 오프로드 효과를 숫자로 인용하지 마십시오.** 정상 상태에서는 측정 해상도 이하입니다.
- **L4 를 리뷰 없이 병합하지 마십시오.** 선별 규칙을 재현해야 하는 변경이라 독립 리뷰가 필수입니다.
- `orca-l3`, `orca-l4` 워크트리와 브랜치를 병합 전에 지우지 마십시오.
- L3 보고서의 게이트 실패를 코디네이터가 워커 보고를 고쳐 통과시키지 마십시오.
- 실측 때 compose 의 `worker` 서비스를 띄우지 마십시오. 따라잡기 수집이 돌 수 있습니다.
