# Uvicorn 다중 워커 운영 구성 후보 (P1)

> **작성일**: 2026-08-13
> **기준 커밋(실측)**: `main` `e3d705c`
> **구현 커밋(본 작업)**: origin/main `bdea9e7` 기반 새 작업 트리
> **상태**: 구성 후보 구현 완료, 실제 Compose 재기동·재실측은 코디네이터 단계로 보류

---

## 1. 배경

[`docs/ops/phase7_latency_recheck_20260813.md`](phase7_latency_recheck_20260813.md)와
[`docs/handoff/2026-08-13_p1_predict_instrumentation.md`](../handoff/2026-08-13_p1_predict_instrumentation.md)에서
`/predict` 동시성 10 조건의 P95가 단일 Uvicorn 워커 기준 199.18ms로 목표(100ms)를
충족하지 못했습니다. 코디네이터가 같은 `main e3d705c` 환경에서 워커 프로세스 수만
바꿔 c10 P95를 재측정한 결과는 다음과 같습니다.

| 워커 수 | c10 P95 | c1/c2/c4 |
| ---: | ---: | --- |
| 1 (기준) | 199.18ms | 역행 없음 |
| 2 | 101.98ms | 역행 없음 |
| 3 | 60.56ms | 역행 없음 |

3워커에서 목표(100ms)를 충족하고 저동시성(c1/c2/c4) 구간에서도 역행이 없어, 3워커를
운영 구성 **후보**로 확정했습니다. 본 문서는 그 구성을 Docker Compose에 반영하고
비용·게이트·롤백을 기록합니다.

---

## 2. 구성 변경 요약

`docker-compose.yml`의 `app` 서비스에 `command`를 추가해 `WEB_CONCURRENCY`
환경변수로 Uvicorn 워커 프로세스 수를 조정할 수 있게 했습니다. 기본값은 3입니다.

```yaml
command:
  - python3
  - -m
  - uvicorn
  - src.app.main:app
  - --host
  - "0.0.0.0"
  - --port
  - "8000"
  - --workers
  - "${WEB_CONCURRENCY:-3}"
```

**적용 범위와 계약:**

| 항목 | 내용 |
| --- | --- |
| 적용 서비스 | `app`만. `worker`(Arq) 서비스는 그대로이며 `WEB_CONCURRENCY`를 읽지 않습니다 |
| 기본값 | `WEB_CONCURRENCY` 미설정 시 `3` (3워커 후보) |
| 롤백 | `.env`에 `WEB_CONCURRENCY=1` 설정 후 `docker compose up -d app` 재기동. 코드 변경 불필요 |
| 개발/테스트 직접 실행 | `Dockerfile`의 `CMD`(단일 워커, `--workers` 없음)와 `make run`(`uvicorn --reload`)은 이번 변경과 무관하게 그대로 유지 |

### 2.1 안전한 exec와 셸 확장 검증

- `command`가 YAML 배열(exec 형태)이므로 컨테이너 진입점은 `/bin/sh -c`를 거치지
  않습니다. 즉 `WEB_CONCURRENCY` 값이 세미콜론·파이프·백틱 등을 포함해도 셸
  메타문자로 해석되지 않고, `--workers` 뒤의 인자 하나로만 `exec()`에 전달됩니다.
- `${WEB_CONCURRENCY:-3}` 치환은 Docker Compose 자체의 파서가 컴포즈 파일을
  렌더링하는 시점에 수행하며, 컨테이너 내부 셸이 관여하지 않습니다.
- Uvicorn은 `--workers`에 정수가 아닌 값이 오면 기동 자체를 거부하므로(예외 후
  프로세스 종료), 값 오타는 명령 주입이 아니라 즉시 실패로 이어집니다.
- `Dockerfile`의 기존 `CMD`도 이미 exec 배열 형태였고 이번 변경으로 건드리지
  않았습니다.

---

## 3. 메모리 비용

3워커는 각 프로세스가 ML 모델(LightGBM/CatBoost 등, [`src/ml/predictor.py`](../../src/ml/predictor.py)의
싱글톤 프리로딩)을 **독립적으로** 메모리에 올립니다. 프로세스 간 공유 메모리가
아니므로 워커 수에 비례해 총 메모리가 늘어납니다.

| 항목 | 값 | 근거 |
| --- | --- | --- |
| 프로세스당 RSS | 약 300MB | 코디네이터 실측 (모델 로드 완료 후 유휴 상태) |
| 3워커 총 비용 | 약 0.9GB | 300MB × 3 (단순 합산, 코드/라이브러리 page cache 공유분 미차감 보수적 추정) |
| 1워커 대비 증분 | 약 0.6GB | 3워커 총합에서 1워커분(약 0.3GB)을 뺀 값 |

이 수치는 애플리케이션 코드·의존성 로드분을 제외한 **모델 가중치 상주분**을
포함한 프로세스 전체 RSS 기준입니다. 컨테이너 `mem_limit`은 현재
`docker-compose.yml`에 설정되어 있지 않으므로, 호스트 가용 메모리가 3워커
합계(약 0.9GB) + DB/Redis/Meilisearch/Ollama 등 나머지 스택을 함께 수용할 수
있는지 배포 전 확인이 필요합니다.

---

## 4. 승격 게이트

3워커 후보를 실제 운영 기본값으로 확정(컷오버)하기 전에 코디네이터가 실제
Compose 스택에서 아래 두 게이트를 재확인해야 합니다. 본 작업에서는 공유
Docker/DB를 점유하지 않기 위해 실제 재기동·재실측을 수행하지 않았습니다.

| 게이트 | 기준 | 확인 방법 |
| --- | --- | --- |
| 기동 시간 | 3워커 전체가 healthcheck를 통과하는 시각이 기존 `start_period: 180s`(app healthcheck, `docker-compose.yml`) 이내 | `docker compose up -d`부터 `docker inspect --format='{{.State.Health.Status}}' <app 컨테이너>`가 `healthy`가 될 때까지 시간 측정. 초과 시 `start_period` 상향 후 재확인 |
| 메모리 | 3워커 합산 RSS(약 0.9GB 추정치)가 실측으로 확인되고, 호스트 여유 메모리 내에 있음 | `docker stats --no-stream <app 컨테이너>` 또는 컨테이너 내 각 uvicorn 프로세스에 대해 `ps -o rss -p <pid>` 합산 |
| c10 P95 유지 | 3워커 구성에서도 c10 P95가 100ms 목표를 계속 충족 | `scripts/benchmark_latency.py --predict-concurrency 10` 재실행 |
| c1/c2/c4 역행 없음 | 저동시성 구간 P95가 1워커 대비 악화되지 않음 | 위와 동일 스크립트로 동시성 1/2/4 함께 측정 |

네 게이트를 모두 통과해야 3워커를 운영 기본값으로 확정합니다. 하나라도
실패하면 [2절 롤백](#2-구성-변경-요약) 절차로 `WEB_CONCURRENCY=1`로 되돌립니다.

---

## 5. 남은 작업 (코디네이터 단계)

1. 실제 Compose 스택(`docker compose up -d`)에서 `WEB_CONCURRENCY=3`(기본값) 재기동
2. 4절의 기동 시간·메모리 게이트 실측
3. `scripts/benchmark_latency.py`로 c1/c2/c4/c10 P95 재검증(이번 구성 변경 반영본 기준)
4. 네 게이트 모두 통과 시 이 브랜치를 `main`에 병합해 3워커를 기본 운영 구성으로 확정
