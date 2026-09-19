# 인증 경로 레이턴시 실측

> **작성일**: 2026-09-19
> **작성자**: Claude Opus 5 (Orca 코디네이터)
> **기준 커밋**: `main` `8f42fa66`
> **Orca Run**: `run_1dbced5f03c6`
> **측정 절차**: [`../ops/auth_path_latency_measurement.md`](../ops/auth_path_latency_measurement.md)
> **선행 문서**: [`read_path_concurrency_20260918.md`](read_path_concurrency_20260918.md)
> **원시 결과**: `artifacts/auth_path_latency_20260919.json`

---

## 1. 한 줄 요약

세션 쿠키 발급 절차가 없어 그동안 측정하지 못했던 인증 경로 세 건을 처음으로 실측했습니다. 단일 웜에서는 전부 P95 5ms 이하, 동시성 c10 에서도 전부 39.2ms 이하로 비인증 읽기 경로보다 빠르며, **최적화 후보가 없습니다.**

---

## 2. 왜 지금 쟀는가

2026-09-18 읽기 경로 실측은 비인증 경로만 다뤘습니다. 로그인 세션을 얻는 표준 절차가 문서에 없어 인증 경로를 통째로 분리해 남겼고, 그 결과 사용자가 실제로 쓰는 평가 화면 계열의 기록이 없었습니다. `AGENTS.md` 는 G3 스택 최적화를 상시 과제로 규정하며, 측정되지 않은 경로는 개선 대상이 되지도 못합니다.

---

## 3. 측정 조건

| 항목 | 값 |
| --- | --- |
| 인증 | 측정 전용 계정으로 로그인 1회, `bidbox_session` 쿠키를 전 회차 재사용 |
| 단일 웜 | 경로마다 워밍업 3회 뒤 30회 순차 |
| 동시성 | 경로마다 c10 으로 100회 |
| 앱 상태 | `READ_PATH_PRELOAD_ANNOUNCEMENTS=true` (운영 기본값) 확인 후 측정 |
| 저장소 상태 | 워커 0대, 워크트리 0개, 배경 테스트 없음 |

전 경로 전 모드에서 오류 0건입니다. 로그인은 회차당 1회뿐이라 `login_rate_limiter` 를 건드리지 않습니다.

---

<!-- METRICS_BEGIN auth_path_latency_20260919 -->

## 4. 결과

| 모드 | 경로 | P50 | P95 | 최대 |
| --- | --- | ---: | ---: | ---: |
| 단일 웜 | `GET /api/v1/accounts/me` | 2.26ms | **2.71ms** | 2.79ms |
| 단일 웜 | `GET /api/v1/evaluations/profiles` | 2.52ms | **2.90ms** | 3.14ms |
| 단일 웜 | `GET /api/v1/evaluations/snapshots` | 3.11ms | **4.36ms** | 4.47ms |
| 동시성 c10 | `GET /api/v1/accounts/me` | 20.66ms | **37.88ms** | 51.45ms |
| 동시성 c10 | `GET /api/v1/evaluations/profiles` | 27.36ms | **39.18ms** | 48.47ms |
| 동시성 c10 | `GET /api/v1/evaluations/snapshots` | 25.16ms | **38.79ms** | 57.68ms |

## 5. 비인증 경로와의 비교

같은 c10 조건에서 2026-09-19 회차의 비인증 경로 값입니다.

| 경로 | c10 P95 | 인증 여부 |
| --- | ---: | --- |
| `GET /api/v1/accounts/me` | 37.88ms | 인증 |
| `GET /api/v1/evaluations/snapshots` | 38.79ms | 인증 |
| `GET /api/v1/evaluations/profiles` | 39.18ms | 인증 |
| 대시보드 통계 | 33.29ms | 비인증 |
| 공고 목록 50쪽 | 55.71ms | 비인증 |
| 공고 목록 1쪽 | 64.62ms | 비인증 |
| 낙찰 목록 1쪽 | 75.28ms | 비인증 |

<!-- METRICS_END -->

인증 경로는 세션 조회(Redis)와 사용자 소유 행 SELECT 만 하므로 목록 직렬화가 없는 대시보드 통계와 비슷한 수준입니다. 세션 검증 자체가 병목이 아니라는 것이 이 표의 요지입니다.

---

## 6. 판정

| 항목 | 판정 |
| --- | --- |
| 인증 경로 P95 | **기록 확보**. 단일 웜 최대 4.36ms, c10 최대 39.18ms |
| 최적화 후보 | **없음**. 정본 레이턴시 게이트의 어떤 기준보다 여유가 크다 |
| 세션 검증 비용 | 유의미하지 않다. 인증 경로가 비인증 목록 경로보다 빠르다 |

---

## 7. 측정하지 않은 것

| 경로 | 이유 |
| --- | --- |
| `POST /api/v1/evaluations/analyze` | `_save_snapshot_async` 로 스냅샷을 저장하는 부작용이 있다. 동시성 100회를 던지면 행이 누적된다 |
| `POST /api/v1/bids/collect` | 외부 수집을 실제로 돌린다 |
| 평가 프로필·스냅샷 생성·수정·삭제 | 전부 DB 쓰기다 |
| 인증 SSR 화면 | 이번 하니스는 API 경로만 다룬다 |

전 세션 인수인계는 `analyze` 를 측정 대상으로 지목했으나, 부작용이 확인되어 제외했습니다. 이 경로의 비용이 필요하면 쓰기를 롤백하는 별도 설계가 선행되어야 합니다. 제외 근거의 경로별 상세는 절차서 4.2 절에 있습니다.

---

## 8. 재현 방법

```bash
BENCHMARK_USERNAME=<사용자명> BENCHMARK_PASSWORD=<비밀번호> \
  uv run python scripts/benchmark_auth_paths.py --mode all \
  --json artifacts/auth_path_latency_<날짜>.json
```

자격증명은 명령 이력에도 남으므로 환경변수 파일을 저장소 밖에 두고 불러 쓰는 편이 안전합니다. 이미 발급된 쿠키가 있으면 `BENCHMARK_SESSION_COOKIE` 로 로그인 단계를 건너뛸 수 있습니다.
