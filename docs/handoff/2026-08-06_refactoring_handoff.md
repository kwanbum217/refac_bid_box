# 리팩토링 세션 인수인계 (2026-08-06)

> **작성일**: 2026-08-06
> **작성 세션**: Claude Opus 5 (리팩토링·성능 담당)
> **병행 세션**: 별도 세션이 용역·물품 모델 성능을 담당했으며 그쪽 작업도 함께 병합됨
> **다음 담당자**: 이 문서만 읽고 이어받을 수 있도록 작성했습니다

---

## 0. 먼저 알아야 할 것

### 0.1 병렬 세션이 동작합니다

| 절대 하지 말 것 | 이유 |
| --- | --- |
| `git add -A` / `git add .` | 다른 세션의 미완성 파일이 딸려 들어갑니다 |
| `git stash` | 다른 세션의 작업 트리를 흔듭니다 |
| `main` 에서 직접 커밋 | 금지 사항입니다 (AGENTS.md 6장 7항). 이 세션도 한 번 위반해 되돌렸습니다 |
| 컨테이너·브랜치 임의 정리 | 다른 세션이 쓰고 있을 수 있습니다 |

병합은 항상 작업 브랜치에서 `git merge --no-ff` 로 합니다. Pull Request 는 만들지 않습니다.

### 0.2 착수 전에 기각 목록을 읽으십시오

용역 모델을 만질 계획이라면 [`.agents/skills/servc-model-tuning/SKILL.md`](../../.agents/skills/servc-model-tuning/SKILL.md) 를 **먼저** 읽으십시오. 실측으로 기각된 접근 9건이 근거와 함께 정리돼 있습니다.

이 세션도 그 문서가 없던 시점에 이미 기각된 접근(낙찰하한율 결측 복원)을 다시 시도했다가 실측으로 되돌렸습니다. 스킬은 그 낭비를 막으려고 만든 것입니다.

---

## 1. 지금 상태

### 1.1 Phase 7 컷오버 조건

| 목표 | 상태 | 근거 |
| --- | --- | --- |
| G1 데이터 무손실 | **통과** | `verify_migration.py` 4/4 |
| G3 예측 API P95 100ms | **통과** | 기동 직후 19.1ms |
| G3 SSE 첫 토큰 P95 3초 | **통과** | 2.66초 |
| G3 SSE 전체 P95 20초 | **통과** | 6.39초 |
| G2 Windows CI | **통과** | 3개 작업 전량 성공 |
| G2 Windows Docker Compose 실기 | **미수행** | Windows 장비 필요 |

**컷오버를 막는 것은 마지막 한 줄뿐입니다.** 절차는 `scripts/validate_windows.ps1` 한 번 실행이며 [`docs/ops/cross_platform_guide.md`](../ops/cross_platform_guide.md) 에 있습니다.

### 1.2 실행 중인 것

이 세션이 띄운 프로세스입니다. 필요 없으면 내리셔도 됩니다.

| 대상 | 상태 | 비고 |
| --- | --- | --- |
| uvicorn | 127.0.0.1:8000 | 벤치마크용으로 기동 |
| arq 워커 | 실행 중 | 크론 2건(매일 02:00 수집, 월 03:00 재학습) |
| Redis 컨테이너 | `refac_bid_box-redis-1` | 내릴 때 `SHUTDOWN NOSAVE` 를 쓰십시오 |
| MySQL | 127.0.0.1:3307 | 컨테이너가 아니라 별도 구동 중 |

---

## 2. 이 세션이 고친 것

### 2.1 SSE 첫 토큰: 11.06초 → 2.66초

Phase 7 인수인계서는 원인을 로컬 LLM 프리필로 지목하며 "애플리케이션 최적화로는 도달 불가" 라고 적었습니다. **그 진단이 틀렸습니다.**

실제 원인은 `gemma4` 의 **사고(thinking) 단계**였습니다. 사고 토큰은 0.57초에 나오지만 우리가 읽는 `message.content` 는 사고가 끝난 뒤에야 시작됩니다. `think: false` 와 모델 상주(`keep_alive`)로 해결했고, 하드웨어 투자도 목표 재설정도 필요하지 않았습니다.

이후 상위 N 실시간 경로에 TTL 캐시를 붙여 반복 질의 정형 조회를 1,967ms 에서 5ms 로 줄였습니다.

근거: [`docs/design/sse_first_token_20260805.md`](../design/sse_first_token_20260805.md)

### 2.2 5일간 조용했던 지식베이스 장애

ChromaDB 설정이 깨져 챗봇이 근거 없이 답하고 있었는데, 검색 실패가 **오류 문구를 문서처럼 돌려주는** 방식이라 아무도 몰랐습니다. `verify_migration.py` 도 sqlite 행만 세어 그 기간 내내 통과했습니다.

검색 실패 시 빈 목록을 돌려주도록 고쳤고, 검증에 **실제 질의 프로브**를 추가했습니다.

### 2.3 승격 게이트가 엉뚱한 것과 비교하고 있었습니다

재학습이 레지스트리의 "지표를 가진 가장 최근 버전" 을 champion 으로 골랐습니다. `quantum_leap_v25_pro` 는 서빙본이 25.1 인데 비교 대상이 **표본 2개짜리 R2 -35999** 버전이었고, `improved_r2 = challenger.r2 >= -35999 + 최소개선` 이라 어떤 챌린저든 통과했습니다.

champion 을 **서빙 슬롯**에서 읽도록 고쳤습니다. cold start 값(`rmse=inf`)도 함께 고쳤습니다 — 주석은 "무조건 승격되지 않도록" 이라 적혀 있었으나 동작은 정반대였습니다.

근거: [`docs/ops/model_promotion_runbook.md`](../ops/model_promotion_runbook.md) 4.1 절

### 2.4 CI 가 계속 빨간불이었습니다

`collect_checksums` 가 매니페스트 키를 `str(Path)` 로 만들어 Windows 에서 역슬래시가 섞였습니다. **한 플랫폼에서 만든 체크섬을 다른 플랫폼에서 대조할 수 없는 상태**로, G2 가 잡으라고 있는 바로 그 결함입니다. `as_posix()` 로 고정했습니다.

Bandit 17건도 함께 해소했고, `.gitattributes` 가 아예 없어 Windows 체크아웃에서 Makefile 이 CRLF 가 되는 위험도 막았습니다(데이터 자산은 `-text` 로 변환 제외 — 체크섬이 깨집니다).

### 2.5 야간 배치 506초 → 135.8초

`bid_ntce_nm` 한 차원이 야간 재집계 비용의 대부분을 썼습니다(`varchar(500)` 무인덱스, 6.6M 행 전표 스캔). 전 기간 누적 순위라 하루 만에 뒤집히지 않으므로 **주간 주기로 내렸습니다.**

요일이 아니라 **스냅샷 나이**로 판정합니다. 요일 판정은 크론이 도는 시각의 시간대에 따라 건너뛰거나 두 번 도는 날이 생깁니다.

### 2.6 그 밖

| 항목 | 내용 |
| --- | --- |
| 예측 API 기동 예열 | 기동 직후 P95 164.1ms → 19.1ms |
| alembic head 병합 | 분기 둘 → 단일 head |
| MLOps 알림 | 웹훅 발신 구현·배선 완료. `MLOPS_WEBHOOK_URL` 미설정이라 **미발신** |
| 승격·롤백 CLI | `scripts/promote_model.py` |
| 서빙 지표 실측 | `scripts/measure_serving_model.py` |
| `servc-model-tuning` 스킬 | 기각 목록 9건, 판정 기준, 측정 함정 4종 |

---

## 3. 기각한 것 (다시 하지 마십시오)

근거 없이 재시도하면 같은 결론에 같은 비용을 씁니다.

| 접근 | 기각 근거 |
| --- | --- |
| 낙찰하한율 결측 복원 | 결측은 누락이 아니라 **제도적 부재**. 수의시담·규격가격동시입찰은 하한율이 존재하지 않는 방식입니다. 실제 결측 행 적용률 0.0%p |
| 2026-05-26 레짐 보정·재학습 | 구제도만 학습해 신제도 예측 시 편향 +0.0615%p, 대조군 +0.0595%p. 차이가 없습니다 |
| 스냅샷 날짜 축 확장 | 정형 창 7개 추가 시 105조합 약 59분. 매일 02:00 에 한 시간은 불가 |
| 스냅샷 SQL 손상값 필터 제거 | 첫 측정 3.6배는 **버퍼 풀 오측**. 순서를 뒤집으니 4~22% |

**측정 함정을 특히 조심하십시오.** 같은 테이블을 훑는 두 질의를 연달아 비교하면 앞선 질의가 버퍼 풀을 데워 뒤 질의가 유리해집니다. 순서를 뒤집어 각 2회 실행 후 2회차를 채택하십시오.

---

## 4. 남은 일 (우선순위 순)

### 4.1 담당자 결정이 필요한 것

| 항목 | 내용 |
| --- | --- |
| **`servc_inst_verify` 553MB** | 일회성 분석 스크립트(`verify_servc_institution.py`)가 운영 DB 에 남긴 작업 테이블 1,033,106행. 업무 데이터가 아니고 ORM·매니페스트 어디에도 없습니다. 재생성은 스크립트 재실행 한 번. **삭제 여부 확인 필요** |
| 가중치 외부 저장소 이동 | Phase 4 미완. `data/model_files/` 는 체크섬 매니페스트 대상이라 옮길 때 매니페스트 갱신 절차를 함께 정해야 합니다 |
| `MLOPS_WEBHOOK_URL` | 코드·테스트 완료, URL 만 넣으면 동작. 1인 운영에서는 실익이 작아 보류했습니다 |

### 4.2 장비가 필요한 것

**Windows Docker Compose 실기 검증** — 컷오버를 막는 유일한 조건입니다.

### 4.3 이득 대비 비용을 먼저 재야 하는 것

`(category, dminstt_nm)`, `(category, bidwinnr_nm)` 복합 인덱스. 남은 야간 135.8초의 대부분이 카테고리별 그룹핑(19~47초)입니다. 다만 6.6M·3.4M 행 테이블에 인덱스를 추가하는 되돌리기 어려운 변경이고, **야간 배치를 줄여도 사용자 지표는 개선되지 않습니다**(첫 토큰 P95 2.66초는 이미 목표 안).

### 4.4 다른 세션 영역

낙찰방법별 분리 학습이 유망합니다. 수의시담 계열 MAE 2.36 대 적격심사 계열 0.79로 **사실상 다른 문제**입니다. `features.py`·`trainer.py` 를 손대므로 조율이 필요합니다.

물품(Thng) 레거시 모델 `ssh_hist_premium`, `v13_hybrid`, `v25` 는 승격·롤백 경로 밖이나, 담당자 판단으로 **현재 집중 대상이 아닙니다.**

---

## 5. 재현 절차

```bash
# 스택
docker compose up -d redis                 # MySQL 은 3307 에 별도 구동
uv run python -m alembic upgrade head

# 검증
uv run pytest tests -q                     # 718 passed / 2 skipped
uv run python scripts/verify_migration.py  # 4/4 PASS
uv run python scripts/check_schema_drift.py
uv run python scripts/validate_agent_rules.py

# 벤치마크 (서버 기동 필요)
uv run uvicorn src.app.main:app --host 127.0.0.1 --port 8000
uv run python scripts/benchmark_latency.py --sse-rounds 10 --query-rounds 0 --predict-rounds 100

# 모델 현황
uv run python scripts/promote_model.py status
```

---

## 6. 관련 문서

| 문서 | 내용 |
| --- | --- |
| [`sse_first_token_20260805.md`](../design/sse_first_token_20260805.md) | 첫 토큰 진단 정정과 대책, 재측정 |
| [`lwlt_missing_investigation_20260806.md`](../design/lwlt_missing_investigation_20260806.md) | 하한율 결측 복원 기각, 레짐 편향 없음 |
| [`snapshot_rebuild_cost_20260806.md`](../ops/snapshot_rebuild_cost_20260806.md) | 야간 배치 비용 구조, 개선안 2건 기각 |
| [`model_promotion_runbook.md`](../ops/model_promotion_runbook.md) | 승격 게이트, 쌍대 비교, 롤백, 지표 실측 |
| [`cross_platform_guide.md`](../ops/cross_platform_guide.md) | Windows 검증 절차와 정적 감사 결과 |
| [`REFACTORING_DESIGN.md`](../design/REFACTORING_DESIGN.md) | 8장 로드맵. 2026-08-06 실사로 표시 정정 |
| [`2026-08-04_phase7_handoff.md`](2026-08-04_phase7_handoff.md) | 직전 인수인계. 첫 토큰 진단은 이 문서로 정정됨 |
