# GPT 코디네이션 세션 인수인계

> **작성일**: 2026-08-13
> **기능 기준 커밋**: `main` `d82a638`
> **정본 백로그**: [`2026-08-13_future_work_backlog.md`](2026-08-13_future_work_backlog.md)
> **상태**: 실행 가능한 인수인계. 다음 세션은 본 문서와 정본 백로그를 순서대로 읽습니다

---

## 1. 세션 종료 상태

| 항목 | 상태 |
| --- | --- |
| Git | 기능 작업 종료 기준 `main = origin/main = d82a638`. 본 인수인계는 이 기준점 뒤의 문서 전용 병합으로 반영 |
| 작업 트리 | `refac_bid_box` 주 작업 트리 1개만 존재. 섹션 작업 트리 없음 |
| Orca Run | `run_a739f50fb02a`: 완료 15건, 대체·폐기 실패 5건, `ready`·`dispatched` 0건 |
| Docker | `app`, `db`, `redis`, `meilisearch` healthy. `app`은 `--workers 1` |
| 완료 섹션 | 워커 터미널·작업 트리·병합 원격 브랜치 반납 완료 |
| 남은 로컬 브랜치 | `feat/codex-task-routing`, `integrate/arq-worker-cutover`. 감사·처분 전 삭제 금지 |

다음 세션은 기존 Run을 재사용하지 않고 새 Orca Run을 만듭니다. 이전 Run에
남아 있던 `ready` 4건은 후속 검증으로 대체된 lifecycle 오류 기록이어서
`failed/superseded`로 종결했습니다.

컴퓨터를 종료했다가 재개한다면 Docker 상태부터 다시 확인합니다. 종료 전
컨테이너를 내리려면 `docker compose down`, 다음 세션에 다시 올리려면
`docker compose up -d db redis meilisearch app`을 사용합니다. 볼륨 삭제 옵션은
데이터 보존 범위이므로 사용하지 않습니다.

---

## 2. 이번 세션에 확정한 결과

### 2.1 P0 수집 공백 복구

- `20260804`~`20260813` 공고·결과 전 범주 **20,602건** 백필 완료
- `resolve_collection_window`와 `MAX_CATCHUP_DAYS=7` 도입
- 요청 범주별 `MIN(MAX per category)` 체크포인트, 없는 범주 fallback,
  `INSERT IGNORE` 멱등성 계약 검증
- 최종 병합: `f5ca094`
- 관련 테스트 19개와 P0 관련 회귀 128개 통과, 규칙 검증 6/6

남은 것은 코드 구현이 아니라 정기 실행의 연속 성공 관찰입니다. 한 번의 백필을
수집 안정화 완료로 바꾸지 않습니다.

### 2.2 P1 예측 계측과 실제 Docker 실측

`/predict`와 `/predict-price`에 다음 기계 파싱 가능 로그를 추가했습니다.

```text
endpoint=..., wall_ms=..., thread_cpu_ms=..., model_wall_ms=..., model_thread_cpu_ms=...
```

계측·원시 증빙 최종 병합은 `bdea9e7`입니다. 실제 Docker 단일 워커 warm
`/predict`를 각 동시성에서 100회 측정한 결과는 다음과 같습니다.

| 동시성 | P95 | 오류 |
| ---: | ---: | ---: |
| 1 | 16.1358ms | 0 |
| 2 | 31.2996ms | 0 |
| 4 | 58.4468ms | 0 |
| 10 | **199.1758ms** | 0 |

원시는 `data/benchmarks/phase7_predict_instrumented_c{1,2,4,10}_20260813.json`에
보존했습니다.

### 2.3 Uvicorn 다중 워커 후보 기각

로컬 사전 실험과 달리 실제 Docker에서는 다중 워커가 c10 P95 100ms 목표를
충족하지 못했습니다.

| 워커 | 기동 | 메모리 | c1 | c2 | c4 | c10 | 반복 c10 | 오류 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| 3 | 12초 | 1.259GiB | 15.75ms | 18.97ms | 40.96ms | **127.32ms** | 151.82 / 135.33ms | 0 |
| 4 | 11초 | 1.603GiB | 15.61ms | 19.43ms | 41.23ms | **165.92ms** | - | 0 |

판정은 다음과 같습니다.

- 3·4워커를 운영 기본값으로 채택하지 않습니다.
- `WEB_CONCURRENCY` 조정 기능은 수동 실험을 위해 유지합니다.
- Compose 안전 기본값은 `1`입니다.
- 실제 앱을 `--workers 1`로 재기동해 8초 안에 healthy, 436.5MiB를 확인했습니다.
- 대상 Compose 테스트 10개와 규칙 검증 6/6 통과
- 최종 병합·원격 반영: `d82a638`

세부 근거는
[`../ops/uvicorn_worker_scaling_candidate_20260813.md`](../ops/uvicorn_worker_scaling_candidate_20260813.md)를
따릅니다. 이 후보는 다시 기본값으로 올리지 않습니다.

### 2.4 P4 MySQL 8 UUID 교정

MySQL 8에 존재하지 않는 native `UUID` DDL 대신 `VARCHAR(36)`을 사용하도록
기준선 마이그레이션과 모델 방언 변형을 교정했습니다. MariaDB UUID는 레거시
호환 경로로 유지합니다. 최종 병합은 `5f52ba1`입니다.

---

## 3. 다음 세션 권장 순서

### 3.1 Task A — P0 수집 안정화 관찰 계약과 첫 판정

**목표:** 정기 개발 수집이 실제로 누락일을 회복하고 공고일·개찰일·유효 라벨이
전진하는지 확인합니다.

**선행 조건:** `db`, `redis`, Arq `worker`가 healthy/running이고
`AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED=true`여야 합니다.

**처리 원칙:**

1. 다음 Task에서 관찰 횟수와 기간을 먼저 고정합니다. 권장값은 3회 연속 일일 실행입니다.
2. 각 실행의 `PipelineExecution` 상태, 범주별 수집 건수와 오류, 최신 공고일·개찰일,
   Servc 유효 라벨 수를 전후 비교합니다.
3. 실패하면 같은 날짜 창을 재실행해 멱등성과 부분 실패 회복을 확인합니다.
4. 7일 초과 공백만 `scripts/backfill_from_g2b.py`로 수동 회수합니다.

**완료 기준:** 고정한 연속 실행 횟수 전부 성공, 날짜·라벨 전진, 중복·스키마 변경
없음, 실패 알림과 수동 재실행 절차 문서화. 관찰 기간이 지나기 전에는 완료로
선언하지 않습니다.

### 3.2 Task B — `/predict` c10 병목 프로파일링과 단일 후보 구현

**목표:** 단일 워커 warm c10 P95 199.18ms를 100ms 이하로 낮출 수 있는 코드
경로 후보를 실측으로 고릅니다.

**공유 자원:** 주 저장소의 모델 아티팩트와 Docker 앱. 다른 Docker 벤치마크,
ML 학습, Ollama 코딩 에이전트를 동시에 실행하지 않습니다.

**순서:**

1. 현재 `uvicorn.error` 로그에서 wall 대비 thread CPU와 model 구간 비중을 c1/c10으로 비교
2. `src/ml/predictor.py` 내부 모델별 호출과 실행기 큐 대기 구간을 최소 계측
3. 프로세스 증설은 기각 목록으로 고정하고, 요청 배칭·모델 호출 벡터화·용량 제한 중
   측정 근거가 가장 강한 후보 하나만 구현
4. 동일 payload, 동시성 1/2/4/10, 각 100회 이상으로 재측정

**완료 기준:** c10 P95 100ms 이하, 오류 0, c1/c2/c4 역행 없음,
Thng·Servc·fallback 예측 동등성 보존, 원시 JSON과 판정 문서 저장. 목표 실패 시
구현을 유지할 별도 정합성 이득이 없으면 후보를 기각합니다.

### 3.3 Task C — `/predict-price` Servc 운영 경로 기준선

**목표:** `/predict` 결과를 대신 쓰지 않고 실제 Servc 공고의 cold 및 warm
c1/c2/c4/c10 기준선을 만듭니다.

공고 PK 조회, 기관 이력, 재발주 이력, 특징 생성, 점 추정과 분위 모델을 구간별로
분리합니다. 첫 요청에서만 분위 모델 로드가 지배적일 때만 프리로드 후보를
검토합니다. 반복 이력 인덱스는 DDL이므로 사용자 승인과 데이터 보존 검증 전에는
만들지 않습니다.

### 3.4 외부 조건이 필요한 후속

| 작업 | 시작 조건 |
| --- | --- |
| Windows 전체 스택 | 실제 Windows Docker Desktop 호스트 확보 |
| 운영 CORS·쿠키 | 운영 도메인과 프런트/API 토폴로지 확정 |
| Servc OOS 판정 | 학습 필터 통과 신 제도 표본 3,098건 축적 |
| 주간 재학습 | P0 안정화와 현 Champion OOS 판정 완료 |
| Cnstwk·Thng 연구 | P0~P2 완료 또는 사용자 우선순위 변경 |

---

## 4. 다음 세션 시작 명령

```bash
git status --short --branch
git rev-parse HEAD
git rev-parse origin/main
orca status --json
orca worktree list --json
docker compose ps
uv run python scripts/validate_agent_rules.py
```

기대 상태는 clean `main`, `main == origin/main`, 섹션 작업 트리 없음입니다.
Docker가 내려가 있으면 다음 순서로 시작합니다.

```bash
docker compose up -d db redis meilisearch app worker
docker compose ps
```

DB가 healthy가 되기 전에 전체 pytest를 실행하면 연결 실패를 코드 회귀로
오판할 수 있습니다. Docker·DB·벤치마크를 사용하는 Task는 새 Orca Run에 공유
자원 소유권과 의존성을 등록하고, `worker_done` 뒤에도 코디네이터가 diff와 테스트를
직접 확인합니다.

---

## 5. 다시 하지 않을 것

- `WEB_CONCURRENCY=3` 또는 `4`를 운영 기본값으로 승격
- 단순 Uvicorn 워커 증설로 c10 100ms 목표를 해결했다고 선언
- `/predict` 수치를 `/predict-price` Servc 운영 경로 수치로 대체
- 사용자 승인과 무손실 검증 없이 반복 이력 인덱스 DDL 적용
- OOS 3,098건 이전 재학습·Champion 승격
- 감사 전 `feat/codex-task-routing`, `integrate/arq-worker-cutover` 삭제 또는 전체 병합
- Windows Docker Desktop 실측 없이 G2 컷오버 통과 선언
- c10 P95 100ms 미달 상태에서 Phase 7 전체 통과 선언

---

## 6. 종료 전 확인 결과

- 기능 작업 종료 시 `main`과 `origin/main` SHA `d82a638` 일치
- 작업 트리 clean
- P1 Compose 대상 테스트 10개 통과
- `scripts/validate_agent_rules.py` 6/6 통과
- 앱 `--workers 1`, healthcheck 통과
- Orca `ready` Task 0건
- P1 워커 터미널·작업 트리·원격 브랜치 제거 완료
