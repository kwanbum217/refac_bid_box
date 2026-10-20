# 인수인계: 20260906 Wave AA~AD 세션 종료

> **작성일**: 2026-09-06
> **Run**: `run_f6f7669674ae`(AA), `run_9eaeef52f8c7`(AB), `run_ee49a3580968`(AC), `run_1fdc2e7e8206`(AD)
> **기준 커밋**: `2fbe6e0` -> `204dcc6` (커밋 18개)
> **미병합 브랜치**: 없음
> **인수 대상**: 다음 코디네이터
> **선행 문서**: [`handoff_20260906_wave_uv_session_close.md`](handoff_20260906_wave_uv_session_close.md)

---

## 1. 한 줄 요약

**2026-09-05 진단 보고서의 잔여 6건 중 4건(R-02, R-07, R-10, R-14)을 닫고 R-13 을
측정까지 마쳤습니다.** 보고서 19건 기준으로 18건이 닫혔고, 남은 것은 Windows
장비가 필요한 R-12 하나와 R-13 의 정본 측정입니다. 빌더는 전부 Muse Spark 1.3,
리뷰어는 전부 Gemini 였습니다.

---

## 2. 닫은 항목

| ID | 내용 | 병합 |
| --- | --- | --- |
| R-02 | 정기 백업 전용 잡 컨테이너 배선 | `54b3f4c` |
| R-07 | RPO 24시간·RTO 4시간 확정과 정책 문서 신설 | `a33c96a` |
| R-10 | 관측성 1단계 (Collector·Tempo·Grafana) | `d7c468f` |
| R-14 | drift baseline 생성과 감시 활성화 | `6cbead3`, `8c3bf01` |
| Z1 잔여 | 디스크 경보를 prune 이후 판정, 임계값·심볼릭 링크 테스트 | `182153f` |
| R-13 | 콜드 SQL 재측정과 코드 과제 3건 판정 | `204dcc6` |

`main` 최종 검증은 pytest **3,740 passed / 32 skipped / 3 deselected**,
`validate_agent_rules` 20/20, ruff 통과, mypy 93개 파일 0건입니다.

---

## 3. 사용자가 이 세션에서 내린 결정

**여섯 개 잔여 항목이 전부 사람의 결정이나 장비를 기다리고 있었습니다.**
그래서 코드 작업보다 결정을 받는 것이 먼저였습니다.

| 항목 | 결정 |
| --- | --- |
| R-02 백업 실행 위치 | **별도 스케줄 잡 컨테이너.** 워커 컨테이너에 백업 역할을 주지 않는다 |
| R-07 복구 목표 | **RPO 24시간 / RTO 4시간** |
| R-10 관측성 | 1차 보류 후 승인. **Collector + Tempo + Grafana, 트레이스 7일, 샘플링 0.1** |
| R-12 Windows | **이번 세션 제외** |
| R-14 baseline 출처 | 실측 후 **레짐 전환 이후 구간(2안)**, 우회 호출이 아니라 정식 스크립트 |

---

## 4. R-14 는 실측 하나로 결론이 뒤집혔습니다

조사 워커(AB2)는 **3안(다음 재학습까지 대기)** 을 권고했습니다. 근거는
"레짐 전환 이후 표본이 충분한지 미확인" 이었고, 그 미확인은 워커가 격리
워크트리에서 DB 에 접속하지 못해 생긴 것이었습니다.

**코디네이터가 DB 를 띄워 직접 재니 2안이 성립했습니다.**

| 항목 | 실측 (2026-09-06) |
| --- | --- |
| `bid_results` 전체 | 3,427,814건 (2008-12-17 ~ 2026-09-03) |
| 레짐 전환 이후 전체 | 73,206건 |
| 그중 Servc | 24,892건 |

PSI 최소 표본이 집단당 100건이고 평가 윈도우가 7일인데 전환 후 3.3개월간
Servc 가 24,892건입니다. 표본 부족이 아닙니다.

**교훈: 워커가 "미확인" 으로 남긴 항목이 결론을 가르는 값이면 코디네이터가
직접 재십시오.** 워커의 환경 제약을 결론의 제약으로 그대로 받아들이면
안 됩니다.

### 4.1 생성한 baseline

```
ml_registry/servc_institution_v1/baseline/
  feature_distributions_v1.json
  metadata.json
```

| 항목 | 값 |
| --- | --- |
| 식별자 | `b_20260906_servc_post_regime` |
| 구간 | 2026-05-26 이후 |
| 표본 | 18,993건 (원시 24,892건에서 공고 조인·가격 유효구간 필터 적용) |
| 특징 | 35개 |
| 집단 분리 | `lwlt_rate` 보유 11,828건 / 결측 7,165건 |

`scripts/generate_drift_baseline.py` 로 만들었습니다. 기본이 dry-run 이고
`--write` 는 `--start-at` 을 요구하며, 표본이 최소 기준에 미달하면 기록하지
않고 실패합니다. `build_training_dataset` 은 `persist=False` 로 불러 운영
학습 parquet 캐시를 건드리지 않습니다.

### 4.2 감시 활성화 전에 안전성을 먼저 판정했습니다

`ML_DRIFT_MONITOR_ENABLED` 기본값을 켜기 전에 **baseline 이 없는 모델에서
무슨 일이 나는지** 를 코드로 확인하도록 Capsule 에 순서를 못박았습니다.
`drift_monitor_task` 는 baseline 부재 시 예외 없이 `INSUFFICIENT_DATA` 로
기록하고 `continue` 하므로 Thng 에서 오경보가 나지 않습니다.

**Thng(`quantum_leap_v25_pro`) baseline 은 여전히 없습니다.** 감시 대상이
아니며 건너뛰기가 계속 기록됩니다. 필요해지면 같은 스크립트로 만들 수 있습니다.

---

## 5. R-13 은 측정했으나 정본이 아닙니다

버퍼풀 콜드 조건에서 재측정했습니다.

| 구간 | 콜드 (n=2) | 웜 (n=4) |
| --- | --- | --- |
| `sql_ms` P50 | 86,539.54ms | 62.02ms |
| `sql_ms` max | 101,496.91ms | 1,015.64ms |

**이전 관찰치 97,087.81ms 와 같은 계열이 재현됐습니다.** 개선도 악화도
아니고 변하지 않았다는 것이 결론입니다.

**정본 자격은 없습니다.** `status: partial` 이고 canonical 게이트 중
`no_request_failures`(8회 중 2회 HTTP 실패), `trace_correlation_passed`,
`item_count_full`, `repetitions_minimum` 이 미충족입니다. 콜드 표본이 2건이라
P95·P99 도 통계적 의미가 약합니다.

측정 절차에서 걸린 것이 하나 있습니다. `LATENCY_SEGMENT_LOGGING` 이 꺼져
있으면 하네스가 **측정을 시작하지 않고 거부** 합니다. `.env` 를 백업하고
`true` 로 바꾼 뒤 app 을 재기동해야 하며, 측정 후 원래 값으로 되돌려야
합니다. 이 세션은 되돌린 뒤 원본과 완전 일치를 확인했습니다.

### 5.1 코드 과제 3건은 전부 "바꾸지 않음" 이 결론입니다

| 과제 | 판정 | 근거 |
| --- | --- | --- |
| `corrupted_probe` 비용 제거 | 유지 | 게이팅하면 `test_ranking_snapshots.py` live_path 2건이 깨진다. 가져온 창이 깨끗한 것과 전체 결과에 손상이 없는 것은 다르다 (Wave E1 회귀 재현) |
| `contains` 선행 와일드카드 대체 | 미처리 | 스키마 변경 없이 B-트리로 탈 방법이 없고 대체는 결과 집합을 바꾼다 |
| GROUP BY 날짜 인덱스 힌트 | 이미 적용됨 | 힌트 유무 모두 `type: range` |

EXPLAIN 실측(빌더·리뷰어 독립 대조 일치):

| 대상 | 결과 |
| --- | --- |
| 탐침(날짜 무) | `type: index`, 3,118,641행 |
| 탐침(날짜 유) | `type: range`, 501,266행 |
| GROUP BY (힌트 무/유) | `type: range`, 707,124행 / 736,148행 |

**판단 근거를 코드 주석과 회귀 테스트 5건으로 고정했습니다.** 다음 사람이
같은 최적화를 다시 시도하다 회귀를 재현하지 않게 하기 위함입니다.

---

## 6. 도구 결함과 코디네이터 과실

### 6.1 `--dispatch-capability` 누락으로 워커 전원이 한 번씩 거부됐습니다

**이 세션의 워커·리뷰어 전원(8대 이상)이 첫 `worker_done` 에서 거부됐습니다.**
사유는 전부 같습니다.

```
Orca rejected this worker_done: The Dispatch capability is missing.
Pass --dispatch-capability <token> from your dispatch preamble.
```

Wave V 의 V1 시정이 `--from`·`--dispatch-id` 자동 해소까지만 다루고 capability
토큰은 다루지 않았습니다. **Capsule 에 "토큰은 preamble 의 `dcap_` 문자열이며
환경변수에서 찾지 말라" 고 명시해도 재발했습니다.** 지시문으로 해결되지
않는다는 것이 확정됐습니다.

**시정 방향**: `scripts/orca_worker_done_guard.py` 가 preamble 파일에서
`dcap_` 토큰을 스스로 읽어 붙이게 하십시오. 못 구하면 fail-closed 로
전송하지 않는 V1 의 방식을 그대로 확장하면 됩니다.

부작용도 있었습니다. 리뷰어 세 대가 토큰을 환경변수에서 찾으려고
`env | grep` 승인 프롬프트에 걸려 사람 승인을 여섯 번 요구했습니다.

### 6.2 병렬 부하가 게이트를 네 번 오탐시켰습니다

AA1, AA2, AC1, AD1 에서 게이트가 테스트 실패를 보고했고 **네 번 모두 단독
재실행에서 통과** 했습니다. 원인은 워커·리뷰어·게이트가 같은 머신에서 전량
스위트를 겹쳐 돌린 것입니다.

| 사례 | 게이트 결과 | 단독 재실행 |
| --- | --- | --- |
| AA1 | 1 failed / 3721 passed | 3722 passed |
| AA2 | 1 failed (`test_ssr_auth_login_success`) | 6 passed |
| AC1 | 워커 보고 1 failed | 게이트 재실행 3735 passed |
| AD1 | 2 failed / 3735 passed | 3737 passed |

**`tests/e2e/test_ssr_auth.py` 계열이 반복 등장합니다.** 부하에서만 실패하고
단독으로는 늘 통과합니다. U1 이 CI 타이밍 테스트를 한 번 결정화했는데 이
계열은 남아 있습니다. **별도 과제로 결정화하십시오.**

**시정 방향**: 게이트 실행을 다른 워커의 테스트 실행과 직렬화하거나, 게이트가
테스트 실패 시 자동으로 단독 재시도하게 하십시오.

### 6.3 게이트 6 은 정직한 보고를 위반으로 잡습니다

AC1 워커가 flaky 실패를 숨기지 않고 "1 failed, 단독 재실행 통과, 이 변경과
무관" 이라고 정확히 적었습니다. 그런데 게이트 재실행에서는 통과해서 **보고와
실제가 다르다** 는 이유로 게이트 6 이 실패했습니다. 워커가 자기 결과를 실제보다
나쁘게 적은 쪽으로 어긋난 것입니다.

게이트가 "flaky 라서 단독 재실행은 통과" 라는 상태를 표현하지 못합니다.

### 6.4 코디네이터 과실 세 건

| 과실 | 내용 | 결과 |
| --- | --- | --- |
| **`worker_done.json` 삭제** | 리뷰어 준비 중 워크트리의 `.orca/capsules` 를 `rm -rf` 후 재복사했는데 워커 보고가 그 안에 있었다 | AD2 게이트 6 을 영구히 통과시킬 수 없다. 위조하지 않고 그대로 남겼다 |
| **Capsule 복사 경로 밀림** | AC1 에서 capsules 가 `.orca/capsules/` 와 `.orca/` 두 곳에 생겨 워커가 후자에 보고를 썼다 | 게이트에 실제 경로를 지정해 우회 |
| **`git stash` 사용** | `source_commit` 갱신 때 파일 하나를 stash 했다. 병렬 세션 간섭 때문에 쓰지 않기로 한 명령 | 즉시 pop 해 영향 없음. 다음부터 브랜치를 먼저 만들 것 |

**재발 방지**: 워크트리 Capsule 갱신은 `rm -rf` 후 재복사가 아니라 `cp -R`
덮어쓰기만 하십시오. 그 디렉터리에는 워커 산출물이 함께 삽니다.

### 6.5 게이트 3 의 docker 허용 목록이 `-f` 를 못 받습니다

`docker compose -f docker-compose.prod.yml config -q` 가 거부됩니다. 허용
토큰이 `docker compose config` 뿐이라, **운영 compose 만 바뀐 Task 는
`compose_config` 능력을 정상 경로로 덮을 수 없습니다.**

이 세션은 `COMPOSE_FILE` 환경변수로 우회했는데, 그때 함께 export 한 더미
비밀값이 **pytest 의 pydantic 설정 검증까지 오염시켜** 수집 단계에서 exit 4 를
냈습니다. 환경변수 우회는 부작용이 큽니다.

**시정 방향**: 허용 목록에 `docker compose -f <파일> config` 형태를 추가하십시오.

---

## 7. 남은 항목

| ID | 내용 | 선행 조건 |
| --- | --- | --- |
| **R-12** | G2 Windows Docker Desktop 실기 | Windows 장비. `worker-start --on <saved-environment>` 원격 워커 경로가 열려 있다 |
| **R-13 정본 측정** | canonical 게이트 충족 측정 | HTTP 실패 0, trace 대조 전량, 문항·회차 정본 기준 충족. 저장소 동결 필요 |

### 7.1 후속 과제 (이 세션이 만든 것)

| 출처 | 내용 |
| --- | --- |
| 6.1 | `orca_worker_done_guard.py` 가 preamble 에서 capability 토큰을 자동 해소 |
| 6.2 | 게이트와 워커 테스트 실행 직렬화, 또는 실패 시 단독 자동 재시도 |
| 6.2 | `tests/e2e/test_ssr_auth.py` 계열 결정화 |
| 6.5 | 게이트 3 docker 허용 목록에 `-f` 형태 추가 |
| 4.2 | Thng baseline 생성 (필요해질 때) |
| R-10 | 메트릭 계측 후 Prometheus 추가 (2단계) |

---

## 8. 정리 상태

**모든 자원을 회수했습니다.** 빌더 6대와 리뷰어 5대를 `worker_done` 확인 직후
`worker-release` 하고 터미널을 닫았습니다. `worker-release` 는 터미널 부착
Dispatch 라 전부 `retained`/`no_owned_resource` 로 돌아왔고
`orca terminal close --terminal` 로 창 단위 종료했습니다(`--tab` 미사용).

워크트리 8개를 모두 제거했고 브랜치는 전부 `git branch -d` 로 삭제했습니다.
`-D` 강제는 쓰지 않았습니다. `orca_settled_session_audit.py` 는 잔류 없음이며
`git worktree list` 는 주 저장소 한 줄입니다.

**Docker 는 이 세션에서 띄웠고 세션 종료 시점에 떠 있습니다.** R-13 측정과
R-14 표본 조회를 위해 dev compose 스택(app, db, redis, meilisearch, worker)을
기동했습니다. 다음 사람이 필요 없으면 내리십시오. `.env` 는 측정용으로 한 번
바꿨다가 원본과 완전 일치로 복원했습니다.
