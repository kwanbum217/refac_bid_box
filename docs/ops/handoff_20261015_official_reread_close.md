# 핸드오프 인수인계 — 2026-10-15 공식 원문 재독 세션 종료

> **작성일**: 2026-10-15
> **작성**: Grok 코디네이터 (Orca Run `run_5631fae373c0`)
> **기준 커밋**: `3e31c60a` (origin/main)
> **source_commit**: `523de82a` (`docs/context/CURRENT_STATE.md`, `updated_at` 2026-10-15)
> **직전 인수인계**: [handoff_20261014_ocr_ledger_close.md](handoff_20261014_ocr_ledger_close.md)
> **이 문서**: 브랜치 `kwanbum217/handoff-20261015-reread-close` 에만 커밋했다. `main` 에는 병합하지 않았다.

---

## 0. 다음 세션이 가장 먼저 할 일

1. Actions `38736352504` 가 커밋 `3e31c60a` 에서 녹색인지 확인한다. 종료 시점에는 `in_progress` 였다. 주소는 `https://github.com/kwanbum217/refac_bid_box/actions/runs/38736352504` 이다.
2. 녹색이 아니면 그 실패만 다룬다. 녹색이면 아래 미결을 사용자에게 다시 묻기 전에 코드를 고치지 않는다.
3. 이 인수인계 브랜치를 `main` 에 넣을지는 사용자 확인 뒤 문서 병합으로 처리한다. 전량 시험 게이트를 이 문서 때문에 다시 돌리지 않았다.

---

## 1. 이번 세션에 `main` 으로 들어간 재독

빌더는 Command Code `deepseek/deepseek-v4.1-flash` (`scripts/orca_cmd_launch.py --effort high --auto --role builder`). 리뷰어는 qwen 경유 OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free` (`scripts/orca_qwen_launch.py --role reviewer --no-commit-notice`). `~/.qwen/settings.json` 의 `reasoningEffort` 는 `max` 이다. 리뷰어는 빌더 `worker_done` 과 계약 파일 확인 뒤에만 띄웠다. 리뷰어는 빌더와 다른 제공자다.

병합은 작업 브랜치 커밋에 대해 Level 1 strict 증거와 전량 시험 증거를 기록하고, 직전 `main` CI 가 녹색인 뒤에 `git merge --no-ff` 로 했다. `source_commit` 은 그 병합 커밋 안에서 병합 직전 `main` HEAD 8자리로 바꿨다. `updated_at` 은 `2026-10-15` 로 유지했다. 워크트리는 병합 후 제거했다. 활성 워커 터미널은 없다.

| 작업 | 병합 | 작업 커밋 | 문서 | 직전 main CI |
| --- | --- | --- | --- | --- |
| 규칙 미발견 식별 불일치 | `a14c97ae` | `96e7a59b` | `docs/analysis/rule_not_found_id_mismatch_20261015.md` | `38715426618` (`b0fb0592`) |
| 기술용역 하한율 공고값 대조 | `0510b8e7` | `e68410bd` | `docs/analysis/pps_tech_lwlt_rate_compare_20261015.md` | `38720744564` (`a14c97ae`) |
| 지역 규칙 부재 시·도별 규모 | `fa44c516` | `d03b8c2d` | `docs/analysis/local_rule_gap_prep_20261015.md` | `38722952677` (`0510b8e7`) |
| 조달청 5억 이상 15억 미만 띠 | `523de82a` | `e4c18749` | `docs/analysis/pps_band_5_15_20261015.md` | `38725353286` (`fa44c516`) |
| 경기 별표 1-1, 충남 별표 2·3·4 | `3e31c60a` | `7d087239` | `docs/analysis/local_annex_reread_20261015.md` | `38733511979` (`523de82a`) |

`3e31c60a` 의 CI 는 종료 시점 실행 `38736352504` 이다. 그 앞의 네 병합 CI 는 녹색을 확인했다.

각 작업 커밋의 전량 시험은 `uv run pytest tests/ -q -m 'not data_assets'` 로 7,649 passed, 41 skipped, 3 deselected 였다. 마크다운만 바꾼 커밋의 Level 1 은 10 passed, 테스트 게이트 1 skipped 였다.

---

## 2. 원문 재독이 닫은 것

조달청 일반용역 적격심사 세부기준 제2026-260호와 제2026-390호 전문에 `15억`, `2억`, `30억` 문자열은 없다. 배점한도 `B` 는 추정가격 5억 원 축이고, 계수 `k` 는 고시금액 축이다. 별표는 용역 종류로만 갈린다. `추정가격 15억원 미만 5억원 이상` 전용 별표와 그 구간 전용 계수는 인쇄되어 있지 않다. 띠 규칙은 넣지 않았다.

경기도 현행은 예규 제751호, 시행 2026-04-15 다. 별표 1-1 파일은 직전 예규 제748호와 MD5 가 같다. 수식 칸은 배점 `30/50/70/90`, 계수 `5`, 기준비율 `89` 이고, 인쇄 점수 `25/45/65/85` 는 인접 칸이다. 대입하면 `0.25` 가 어긋나 확정하지 않았다.

충청남도 공고 2026-1235호 별표 2·3·4 의 배점 열은 추정가격 5억 원 `60/70` 이고, 식의 구간은 고시금액이며 계수는 `2` 또는 `4`, 기준비율은 `88` 이다. 금액 기준이 다른 두 칸을 하나의 계수 짝으로 닫지 않았다. 규칙은 등록하지 않았다.

기술용역 구판은 원문이 이미 `data/reference/pps_tech_lwlt_pre_20260526.yaml` 에 있다. 별표는 `낙찰하한율` 단어를 인쇄하지 않는다. `79.995`, `85.495`, `86.745`, `87.745` 는 역산값이다. 공고일 2026-05-26 이전 9,313건 중 9,177건이 그 값과 같다. 2026-05-26 이후 3,904건 중 3,119건은 직전 판 값을 싣고, 정본은 공고의 `sucsfbidLwltRate` 다. 구판은 코드에 넣지 않았다.

---

## 3. 사용자 결정이 남아 있는 것

코드를 고치지 않는다. 다음 중 사용자가 고른 항목만 별도 Task 로 연다.

| 항목 | 상태 |
| --- | --- |
| 기술용역 구판을 시행일 이전 공고에만 넣을지 | 원문에 등식 문장이 없다. 98.54% 일치는 측정이다. 2026-05-26 이후는 공고 필드를 유지한다 |
| 5억 원 이상 15억 원 미만 띠 규칙 | 두 고시에 전용 별표가 없다. 계수를 만들지 않는다. 같은 낙찰방법명 공고는 389건으로 이미 세었다 |
| 경기·충남 세부유형 등록 | 인쇄 식과 배점이 같은 칸에 있지 않다. 대구 일반 별표는 2022-09-30 삭제라 만들지 않는다. 광주·전남은 전남광주통합특별시 예규 제3호로 이미 등록되어 있다 |
| 시·도 신규 등록 우선순위 | `LOCAL_RULE_NOT_FOUND` 1,184건 중 991건은 시·도 값이 비어 있다. 원문을 더 받아도 이 건수는 줄지 않는다 |
| 발행 원장 재생성 | `data/reference/rule_coverage_ledger.yaml` 은 2026-10-11 스냅샷이다. 발행 총량은 31,485건, 차단 20,973건이다. 다시 생성하지 않는다 |
| 산림청 등록 | 하지 않는다. 확인 기관은 11곳이고 정량표 기관은 10곳이다 |
| 계산 차단 약 67% 의 구현 | 구판 적재, 수동 평가 안내, 지역 규칙 등록, 기본 용역 유형 중 사용자가 고르기 전에는 구현하지 않는다 |

---

## 4. 운영 값

| 항목 | 값 |
| --- | --- |
| Run | `run_5631fae373c0`. 끝난 Run `run_8ca68ee95815`, `run_cfe18fe34fa6` 은 재사용하지 않는다 |
| Orca | 1.4.226. runtimeId `dc23465e-00a1-4a8f-9e24-82920fa71149` |
| 버전 | `pyproject.toml` `0.1.0rc1` |
| 전량 시험 | `uv run pytest tests/ -q -m 'not data_assets'` |
| 증거 파일 | `.cache/level1_strict_evidence.json`, `.cache/premerge_full_suite_evidence.json`. 마지막 기록만 남는다. 종료 시점 기록은 병합된 `7d087239` 이다 |
| DB 조회 | `uv run python scripts/db_readonly_query.py` 만. `docker exec` 와 mysql 클라이언트는 쓰지 않는다. 호스트 MariaDB 3307 은 건드리지 않는다 |
| 워커 | 대화형 Orca 터미널만. 동시 제품 쓰기 3대. `.orca/` 쓰기는 그 상한에 넣지 않는다 |
| 종료 시 도커 | `docker compose down` (볼륨 유지). 앱 `127.0.0.1:8000`, DB `127.0.0.1:3306` 데이터베이스 `procurement`, Redis, Meilisearch, worker 를 내렸다 |

크레딧이 빌더를 멈추기 전에는 모델을 바꾸지 않는다. 멈추면 빌더만 grok-4.7 로 바꾼다. Nvidia 과부하 재시도는 모델 줄이 `NVIDIA: Nemotron 3 Ultra (free) max` 인 동안 실패가 아니다.

---

## 5. 하지 말 것

- `main` 직접 커밋, pull request, `--amend`, 브랜치 강제 삭제.
- `terminal close --tab`. 코디네이터 창까지 닫힌다.
- `check --ack` 에 `deliveryId` 가 아닌 메시지 id 를 넣기.
- 계약 파일 없는 대화 `worker_done` 을 통과로 보기.
- 커버리지 스크립트의 기본 출력으로 발행 원장을 덮어쓰기. 돌릴 때는 `--output` 을 `.cache/` 아래로 준다.
- 해양환경공단 패턴을 `해양폐기물정화` 밖으로 넓히기. 하부기관 접두어를 넣기.
- 산출 하한율을 원문이 인쇄한 낙찰하한율이라고 적기.
