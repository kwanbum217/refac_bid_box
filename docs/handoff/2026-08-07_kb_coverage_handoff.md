# KB 커버리지 확대 인수인계

> **작성일**: 2026-08-07
> **버전**: v0.1.0
> **상태**: 50만 건 확대 진행 중(15:35 기준 약 30만 건). 중단분 재개가 다음 단계입니다.
> **선행 문서**: [`2026-08-06_refactoring_handoff.md`](2026-08-06_refactoring_handoff.md) 4.1.1 절

---

## 1. 이번 세션에서 끝낸 것

### 1.1 테스트가 운영 Slack 으로 경고를 실제 발신하던 문제 (해결, 병합 완료)

2026-08-06 21시대에 온 경고 6건은 **재학습 실패가 아닙니다.** 테스트 스위트가
운영 채널로 직접 보낸 것입니다.

| 확인 항목 | 결과 |
| --- | --- |
| 컨테이너 DB 행 수 | 호스트와 동일 (공고 5,461,079 / 결과 3,405,928) |
| Servc 공고 조인율 | 932,624 / 933,808 = 99.9% |
| `build_training_dataset('Servc')` | 호스트·컨테이너 모두 917,629행 정상 |
| `retrain_logs` 최신 기록 | 양쪽 DB 모두 2026-08-02. 8/6 21시대 기록 없음 |
| 문구 `"학습 데이터 부족"` 출처 | 운영 코드에 없음. `tests/test_scheduled_tasks.py` 의 가짜 예외 문자열 |

`retrain_logs` 에 기록이 없는데 알림만 온 것이 결정적 근거입니다. 실제 파이프라인이
돌았다면 `_record` 가 먼저 커밋됩니다.

원인은 `src/tasks/notifier.py` 의 발신 조건이 **URL 이 비었는지 하나뿐**이라는
점입니다. `.env` 에 실제 Slack URL 을 넣는 순간부터 테스트가 실제로 나갔습니다.
`tests/conftest.py` 에서 `MLOPS_WEBHOOK_URL` 을 빈 값으로 **대입**해 차단했고
(셸 export 도 막아야 하므로 `setdefault` 가 아닙니다), 회귀 테스트를 더했습니다.

병합 완료: `aabba03`. 전량 748 통과, `validate_agent_rules` 6/6.

> **어제(8/6) 세션의 "컨테이너가 빈 DB 를 본다" 진단은 오진이었습니다.** compose
> `db` 는 명명 볼륨 `refac_bid_box_mysql_data`(36.2G) 를 쓰므로 컨테이너를 새로
> 만들어도 데이터가 남습니다. 같은 추론을 반복하지 마십시오.

### 1.2 부수 조치

`896d4ad` 가 `.agents/skills/servc-model-tuning/SKILL.md` 만 갱신해
`validate_agent_rules` 가 실패하고 있었습니다. `.claude`, `.opencode` 에 그대로
반영했습니다(`7ca7c22`). 해당 스킬은 다른 세션 영역이므로 내용은 건드리지
않았습니다.

---

## 2. 진행 중이던 것: KB 커버리지 확대

### 2.1 실행한 명령

```bash
KB_MAX_DOCUMENTS=100000 uv run python - <<'PY'
from src.app.core.db import SessionLocal
from src.app.services.kb_builder import rebuild_knowledge_base
rebuild_knowledge_base(SessionLocal(), pipeline_run_id="kb_scale_100k")
PY
```

증분 색인이라 기존 500건은 본문 해시가 같아 재임베딩되지 않고, 신규분만
임베딩됩니다.

### 2.2 실측값

| 항목 | 값 |
| --- | --- |
| 색인 결과 | 100,000건 (신규 99,500 / 유지 500 / 삭제 0) |
| 소요 | 2,412.9초 = **40.2분** (설계서 추정 36분) |
| `chroma_db/` 크기 | **700MB** (추정 0.70GB 와 일치) |

증분 색인이 의도대로 동작해 기존 500건은 본문 해시가 같아 재임베딩되지
않았습니다(`index_mode: incremental`, `unchanged_count: 500`).

**ChromaDB 실제 경로는 `chroma_db/` 입니다.** `data/chroma_db/` 가 아닙니다.

전제 조건: 호스트 Ollama 가 떠 있고 `bge-m3:latest` 가 있어야 합니다.

---

### 2.3 적중률 재측정 결과 (완료)

```bash
uv run python scripts/measure_kb_retrieval.py
```

색인된 문서를 시드 42 로 100건 뽑아 `공고명 + 수요기관` 을 그대로 질의하고,
자기 자신이 상위 몇 번째에 오는지 셉니다. 8/6 에 500건으로 잰 방식과 같고
MRR 을 추가로 냅니다.

| 규모 / 임베딩 | top-5 적중률 | 비고 |
| --- | --- | --- |
| 500건 / MiniLM | 4.0% | 한국어에서 동작하지 않았음 |
| 500건 / bge-m3 | 100.0% | 교체 근거 |
| **100,000건 / bge-m3** | **100.0%** | top-1 73.0%, MRR 0.8508, 질의 145.2ms |

**후보를 200배로 늘렸는데 순위 열화가 없습니다.** 우려했던 지점이 해소됐고,
질의 지연 145.2ms 는 첫 토큰 P95 목표(2.66초) 안에서 여유가 큽니다.

---

## 3. 다음에 할 일

### 3.0 재개 진입점 (2026-08-07 15:35 중단)

담당자 장비 종료로 50만 건 색인을 절반에서 멈췄습니다. **이어서 하려면 아래 한
줄이면 됩니다.** 이미 넣은 문서는 본문 해시가 같아 건너뜁니다.

```bash
KB_MAX_DOCUMENTS=500000 uv run python scripts/scale_kb_coverage.py
```

| 항목 | 값 |
| --- | --- |
| 브랜치 | `feat/kb-coverage-500k` (커밋 `b1eb263`, `c52a7ba`. 미병합) |
| 중단 시각 | 15:35 (14:10 재실행 후 1시간 25분) |
| `chroma_db/` | 700MB -> **2.1GB** |
| 색인 규모 추정 | 약 30만 / 50만 건. 신규분 20만 / 40만 건 = 50% |
| 실측 속도 | 시간당 약 14만 건 |
| 남은 소요 | 약 1시간 25분 |

재개 시 `_load_existing_index` 가 30만 건 메타데이터를 먼저 읽으므로 임베딩
시작까지 몇 분 걸립니다. 이번 최초 실행은 1분이었습니다. 진행 확인은
`du -sh chroma_db` 가 늘어나는지로 봅니다. 목표는 약 3.5GB 입니다.

완료 후 반드시 할 일입니다.

1. `uv run python scripts/measure_kb_retrieval.py` 로 적중률·지연 재측정
2. 본 문서 2.3 절 표에 50만 건 행 추가
3. 테스트 전량과 `python scripts/validate_agent_rules.py` 통과 후 main 병합

### 3.0.1 색인이 진행되지 않던 원인 (해결, 커밋 `c52a7ba`)

첫 실행(13:35)은 30분간 `chroma_db/` 가 700MB 에서 움직이지 않았습니다. Python
이 CPU 100% 를 쓰는데 Ollama 는 유휴였습니다. `sample` 로 스택을 뜨니
`set_add_entry` 와 `set_table_resize` 가 전부였습니다.

`_diff_index` 의 `set(ids)` 가 컴프리헨션 **안**에 있어 기존 문서마다 대상
집합을 재구축했습니다. 기존 10만 x 대상 50만 = 5x10^10 연산이라 사실상 끝나지
않습니다. 8/6 에는 기존 색인이 500건이라 2.5x10^8, 수십 초에 지나가 드러나지
않았습니다.

집합을 루프 밖에서 한 번만 만들도록 고쳤고, 회귀 테스트
`test_diff_index_scales_to_large_collections` 로 10만 x 5천 규모를 5초 예산에
고정했습니다. 수정 후 재실행은 1분 만에 임베딩에 진입했습니다.

> **교훈**: 색인이 멈춘 것처럼 보이면 프로세스 CPU 와 Ollama 부하를 함께
> 보십시오. Python 만 100% 이고 Ollama 가 놀고 있으면 임베딩 전 단계의 문제입니다.

### 3.1 50만 건(전량) 확대 판단

10만 건에서 적중률·지연 모두 여유가 있으므로 확대를 막는 측정상 근거는
없습니다. 남은 것은 비용입니다.

| 규모 | 소요(실측 기반) | 디스크 |
| --- | ---: | ---: |
| 100,000건 | 40.2분 (실측) | 700MB (실측) |
| 500,000건 | 약 3.4시간 | 약 3.5GB |

증분 색인이 있어 초기 적재만 한 번 비싸고 이후 야간 재색인은 변경분에
비례합니다. 확대 후에는 같은 스크립트로 반드시 다시 재십시오.

실행은 [`scripts/scale_kb_coverage.py`](../../scripts/scale_kb_coverage.py) 로
고정했습니다. 브랜치 `feat/kb-coverage-500k` 에서 진행합니다.

```bash
KB_MAX_DOCUMENTS=500000 uv run python scripts/scale_kb_coverage.py
```

**중단해도 진행분은 남습니다.** `_flush` 가 100건 단위로 `upsert` 하고
`PersistentClient` 라 배치마다 디스크에 씁니다. 재실행하면 `_diff_index` 가
본문 해시로 이미 넣은 문서를 걸러내므로 남은 분량부터 이어갑니다. 목표 집합이
기존 색인의 상위 집합이라 `removed_ids` 도 비어 삭제가 일어나지 않습니다.
최악의 경우 HNSW 가 아직 플러시하지 않은 최근 수천 건만 다시 임베딩됩니다.

컴퓨터를 끄실 때는 `pkill -f scale_kb_coverage` 로 프로세스를 먼저 정리하십시오.

### 3.2 그 뒤

- 원문(HWP/PDF) 수집·청킹·overlap. 현재 KB 문서는 DB 행에서 조립한 정형
  레코드(평균 183자)라 쪼갤 대상이 없습니다. 이것이 먼저가 아닙니다
- Windows Docker Compose 실기 검증 — 컷오버를 막는 유일한 조건, 장비 필요
- ~~Slack 웹훅 재발급~~ — 2026-08-07 담당자가 재발급 완료. 테스트 발신 차단은
  `tests/conftest.py` 가 `MLOPS_WEBHOOK_URL` 을 빈 값으로 대입하는 방식이라 새
  URL 에서도 그대로 유효합니다

---

## 4. 인계 시 주의

### 4.1 병렬 세션과 작업 트리를 공유합니다

`git add -A`, `git add .`, `git stash` 를 쓰지 마십시오. 파일을 하나씩 지정해
담습니다. 브랜치가 다른 세션 것으로 바뀌어 있을 수 있으니 커밋 전에
`git branch --show-current` 를 확인하십시오. 다른 세션 브랜치·컨테이너를 임의로
정리하지 마십시오.

2026-08-07 12시 기준 다른 세션 영역은 용역(Servc) 모델 개선입니다
(`scripts/eval_servc_huber_alpha.py`, `scripts/analyze_servc_error_concentration.py`,
`docs/design/servc_error_concentration_20260807.md`).

### 4.2 Docker

`app`, `db`, `redis` 컨테이너가 떠 있습니다. Docker CLI 가 PATH 에 없어
`/Applications/Docker.app/Contents/Resources/bin/docker` 로 불러야 합니다.

### 4.3 모델·effort

10만 건 적재·측정까지 low 로 마쳤습니다. 50만 건 확대는 실행 자체가 판단이
아니므로 low 로 충분합니다. 원문 청킹 설계에 들어갈 때 medium 을 권합니다.
