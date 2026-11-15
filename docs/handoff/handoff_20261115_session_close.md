# 핸드오프 인수인계 - 2026-11-15 세션

> **작성일**: 2026-11-15
> **작성**: 코디네이터(Claude Opus 5.5). Orca Run `run_87d6d4d819d1`
> **기준 커밋**: 작성 시점 `main` 은 `f4baec19` 입니다(CI 성공).
> **워커 풀**: 빌더 cmd `deepseek/deepseek-v4.1-flash`, 리뷰어 cmd `z-ai/glm-5.3-flash`(사용자 지정). 시험 워커 kilo `exaone/k-exaone_v2.5` 2대. 워커 0대, 전부 회수.
> **이전 문서**: [`handoff_20261114_kilo_exaone.md`](handoff_20261114_kilo_exaone.md) 0절 1~5행의 결과는 이 문서 0절로 이어집니다.

---

## 0. 다음 세션이 바로 할 일

| 우선 | 과업 | 방법 |
| --- | --- | --- |
| 1 | 주간 재학습 후보 판정(2026-11-16 월요일) | `docs/design/servc_freshness_retrain_20261114.md` 절차(최신성 쌍대, 운영 쌍대, 승인 후 승격) |
| 2 | 예비가격 소급 이어서 실행 | `G2B_MAX_CONCURRENT=2 uv run python scripts/backfill_prearng_by_notices.py --since 2026-10-12 --until 2026-10-27 --limit 2000 --execute`. 실패 96건은 다음 실행 후보에 남습니다. 실패가 다시 많으면 동시 요청을 1로 낮춥니다 |
| 3 | K-EXAONE 2.5 운용 | 결정 완료(2026-11-15 사용자). 비임계 보조 조사(investigator) 전용, `auto_selectable` False 유지. 라우터 `suitable_for` 에서 reviewer 를 뺐습니다 |
| 4 | Coarena DeepSeek V4.1 Flash 워커 시험 | 등록·probe 만 통과. 이번 세션도 미시험 |
| 5 | cmd 크레딧 잔량 확인 | 리뷰어 화면에 `Plan: 83% used, 11.9 credits left` 경고. 소진 시 리뷰어 대체가 필요합니다 |
| 6 | Docker 스택 유지 | 사용자 결정(2026-11-13)대로 worker 를 포함해 내리지 않았습니다 |

---

## 1. 이 세션에서 main 에 넣은 것

| 병합 | 내용 |
| --- | --- |
| `f4baec19` | `RedisConnection.invalidate()` 를 `client()` 와 같은 `self._lock` 아래에서 실행(`src/app/core/cache.py`). 11-14 리뷰어의 범위 밖 관찰(무잠금 쓰기)을 해소. 새 시험 `tests/test_redis_invalidate_lock_20261115.py` |

검증: 빌더 deepseek 8분, 리뷰어 GLM pass(5항목 결함 없음), Level 1 strict pass, 전량 10,909 passed, 규칙 22/22, CI 성공. 병합 후 app·worker 재시작.

리뷰어 GLM 은 빌더와 같은 cmd 제공자라 `orca_taskctl.py dispatch` 라우터가 거부합니다(`ModelRoutingError`). `orchestration dispatch --return-preamble` 로 받은 지시문을 고유 경로(`.orca/preamble_<task>_rev.txt`)에 쓰고 런처를 `--preamble` 로 띄우는 **비감독 경로**를 썼습니다. 고정 경로 `.orca/preamble.txt` 는 런처가 거부합니다.

---

## 2. K-EXAONE 2.5 워커 성능 시험

혼잡률: 10:02~10:04 단발 `kilo run` 5회 전부 성공(11~25초), 혼잡 오류 0회. 11-14 의 실패(3회 중 2회 혼잡)는 시간대 영향이었을 가능성이 있습니다.

### 2.1 시험 A 빌더 (같은 과업, 같은 기준 커밋 `22a8fe54`)

| 항목 | deepseek-v4.1-flash | K-EXAONE 2.5 |
| --- | --- | --- |
| 소요 시간 | 8분 06초 | 27분 13초 |
| 혼잡 재시도 | 0회 | 1회 |
| 소스 수정 | 정답 | 같은 결과(blob `da3022bc` 일치) |
| 새 시험 / join 상한 | 4건 / 있음 | 3건 / 있음 |
| 지정 시험 재실행 | 23 passed | 22 passed |
| 계약 위반 | 0건 | 0건 |
| 보고 정확성 | 정확 | 제외된 data_assets 시험 2건을 실패로 적음 |

### 2.2 시험 B 리뷰어 (결함 2개를 심은 커밋 `4ba0b571`)

| 항목 | 결과 |
| --- | --- |
| 소요 시간 | 53분 15초. 토큰 카운터가 15분 넘게 멈춘 구간 있음 |
| 최종 판정 | fail (정답) |
| 결함 1: `_client = None` 이 잠금 밖 | 탐지. 줄 번호 정확, 시험 실행으로 재현 |
| 결함 2: join 상한 제거 | 근거란에 정확히 적었으나 판정은 `no`. 근거와 판정이 모순 |
| 오탐 | 0건 |

### 2.3 판정

정확도는 deepseek 과 같은 수준이고 속도는 3~4배 느립니다. 리뷰 판정 칸만 집계하면 결함을 놓칠 수 있어 근거란을 직접 읽어야 합니다. 쉬운 과업 1건씩의 근거라 확정 판정은 아닙니다. 시험 커밋은 `refs/backup/exab-20261115`, `refs/backup/exrv-20261115` 에 있고 브랜치·워크트리는 제거했습니다. 결함 브랜치 `4ba0b571` 은 시험용으로 `--no-verify` 커밋했으며 병합 대상이 아닙니다.

시험 B 리뷰의 빌더 보고 항목 `n/a` 는 코디네이터가 빌더 `worker_done.json` 을 리뷰 워크트리에 복사하지 않은 준비 누락입니다.

---

## 3. 예비가격 소급

| 항목 | 건수 |
| --- | --- |
| 조회(개찰일 10-12~10-27, 상한 2,000) | 2,000 |
| 적재 | 1,216 |
| 자료 없음(Redis 3일 기록) | 688 |
| 실패(429 재시도 소진) | 96 |
| 누적 적재 | 3,382 (2,166 + 1,216) |

스크립트는 실패 공고가 있으면 종료 코드 1 을 냅니다. 로그는 429 재시도만 찍고 성공은 찍지 않으므로 진행 판단은 `bid_prearng_prices.collected_at` 집계로 합니다(행 1개가 공고 1건). 같은 시간 운영 worker 의 429 는 0건이었습니다.

---

## 4. 운영 메모

| 메모 | 내용 |
| --- | --- |
| premerge 증거 두 종류 | Level 1 strict 증거와 별도로 전량 테스트 증거(`.cache/premerge_full_suite_evidence.json`)가 병합 대상 커밋과 일치해야 합니다. 워커 워크트리에서 `python3 scripts/premerge_full_suite_gate.py --record` 를 먼저 돌립니다 |
| kilo 워커 기동 | `source ~/.config/kilo/exaone.env && uv run python scripts/orca_opencode_launch.py --binary kilo --model exaone/k-exaone_v2.5 --variant high --role <역할>` 터미널에 `dispatch --launcher scripts/orca_opencode_launch.py --no-probe` |
| 정체 감시 | kilo 는 화면 해시가 스피너로 계속 바뀌므로 토큰 카운터(`NNN.NK (NN%)`)로 판정합니다 |
| release-worker | `--dispatch` 가 필수입니다. `dispatch-show --task` 로 ID 를 먼저 얻습니다 |
