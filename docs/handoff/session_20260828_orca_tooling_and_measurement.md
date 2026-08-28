# 인수인계: 2026-08-28 조율 도구 결함 정리와 RAG 정본 재측정

> **작성일**: 2026-08-28
> **Run**: `run_973af8e258f4` (1차 3건), `run_58423ec599bf` (2차 4건)
> **코디네이터**: Claude Opus 5
> **워커**: Antigravity `gemini-3.7-flash-high` 2대, cursor `composer-2.5` 3대, kimi `or-free/minimax-m3` 2대
> **시작 HEAD**: `e5db8a9` / **종료 HEAD**: `412f5c1`
> **결과**: Task 7건 전부 병합, CI green(run `33167341679`). 전량 2600 passed.
> RAG 정본 재측정은 두 번 시도해 두 번 다 실패했습니다(5장)

---

## 1. 이번 세션이 닫은 것

조율 도구 결함 7건을 병렬로 처리했습니다. 이 중 5건은 **이번 세션 자체에서
코디네이터가 실제로 겪은 문제**였고, 겪은 자리에서 Task 로 등록했습니다.

| Task | 내용 | 워커 | 커밋 |
| --- | --- | --- | --- |
| `task_d90da80dacf3` | CPU utilization 관측 시간 분리 | kimi | `a148f31` |
| `task_7bd2943e69b5` | 워커 감시 정체 신호 분류 | cursor | `9d787e3` |
| `task_95b03278c33b` | 파일 편집 승인 모드 자동 전환 | Antigravity | `821e48f` |
| `task_0efb961554ff` | Antigravity 워커 런처 신규 | kimi | `a4ac9ba` |
| `task_dc563d276c5a` | 감시 터미널 선택 | cursor | `666398c` |
| `task_109829469d92` | worker-start 진단 명령 일치 | Antigravity | `412f5c1` |
| `task_6c4678a375c2` | kimi 런처 창 유지 | cursor | `412f5c1` |

---

## 2. 워커 보고를 믿고 병합했다면 들어갔을 결함 5건

**7건 중 5건에서 워커가 "검증 전량 통과" 를 보고했고 실제로는 결함이 있었습니다.**
모두 모킹 테스트를 통과한 상태였고, 실물 실행 실증에서만 드러났습니다.

| Task | 워커 보고 | 실제 결함 | 발견 방법 |
| --- | --- | --- | --- |
| 감시 정체 신호 | 2540 passed | `429`·`502` 단독 숫자가 pytest 출력을 오탐. `2537 passed in 429.31s` 가 rate limit 으로 판정 | 실제 출력 문자열 4개로 직접 호출 |
| 편집 승인 모드 | 2535 passed | CLI 구분 없이 전송. cursor 에서 shift+tab 은 Plan Mode(편집 금지) 전환이라 정반대 효과 | `cursor-agent --help` 와 기동 화면 확인 |
| 편집 승인 모드 2차 | 테스트 통과 | 판정이 실제 화면에서 전부 False. `terminal show` preview 에 CLI 상태줄이 없음 | 살아 있는 워커 3대 화면으로 판정 함수 호출 |
| 감시 터미널 선택 | 2570 passed | `title` 이 None 인 빈 셸을 워커 후보로 취급. 핸들 정렬 우연으로만 맞고 있었음 | 인위적 후보 조합 6종 실증 |
| worker-start 진단 | 2567 passed | 도달 불가 fallback 이 남아 테스트가 실제와 다른 3 튜플 계약을 검증 | fallback 제거 시도 시 17건 실패 |

**교훈**: `uv run pytest` 통과는 이 저장소의 조율 도구에 대해 품질 보증이 되지
못합니다. 이 도구들은 터미널 화면, 프로세스 수명, CLI 별 키 의미처럼 모킹으로
재현되지 않는 것을 다룹니다. **병합 전에 실물로 한 번 돌려 보십시오.**

---

## 3. 코디네이터가 직접 고친 2건

왕복 비용이 수정 규모를 넘어서면 코디네이터가 직접 고치는 편이 낫습니다.

### 3.1 CLI 판정 마커가 대화 내용에 오염됩니다

Antigravity 워커 화면에 cursor 마커(`cursor-agent`, `composer`, `run everything`)가
**전부 매칭**됐습니다. 코디네이터가 반려 지시문에 그 단어들을 써서 화면에 남았기
때문입니다. 워커가 넣은 `● bash(`, `thought for ` 같은 범용 마커는 여러 CLI 가
공유하는 출력 형식이라, cursor 화면에 그 문자열이 남으면 Antigravity 로 오판합니다.

판정 근거를 **CLI 가 상태줄에 스스로 그리는 문자열**과 기동 명령줄로만 좁혔습니다.

    ACCEPT_EDITS_CLI_MARKERS = ("accept-edits", "auto-approve file edits",
                                "shift+tab to auto-approve", "antigravity cli", "agy --model")

**터미널 화면 기반 판정을 설계할 때는 그 화면에 코디네이터의 지시문도 남는다는
점을 계산에 넣으십시오.**

### 3.2 제목 없는 터미널은 워커가 아닙니다

`is_shell_default_title` 이 `None` 과 빈 문자열을 False(워커 후보)로 봤습니다.
실제로 제목 없는 셸이 워커와 같은 워크트리에 있었고, 선택이 핸들 정렬 우연에
좌우됐습니다.

---

## 4. 워커 운용에서 새로 확인한 것

| 사실 | 조치 |
| --- | --- |
| **cursor 워커가 3번 중 2번 커밋 없이 완료 선언** | Capsule 에 커밋 요구가 있어도 지키지 않습니다. 터미널로 커밋을 직접 지시해야 했습니다 |
| `worker_done` 접수 후 코디네이터 반려가 오면 보고 경로가 영구히 막힘 | `dispatch_capability_invalid` 로 거부됩니다. 워커가 고쳐도 알릴 방법이 없어 **터미널을 직접 읽어야만** 압니다 |
| kimi 워커는 작업이 끝나면 창이 사라짐 | `-p` 단발 모드 + `os.execvpe` 구조. 이번에 `task_6c4678a375c2` 로 해소 |
| cursor `worker-start` 가 매번 `codex-trust-workspace` 로 실패 | 워크트리마다 신뢰 대화창이 새로 뜹니다. `terminal send --text 'a'` 후 Task 를 `ready` 로 되돌려 재 Dispatch |
| `minimax-m3` 는 OpenRouter 무료 풀에 있음 | 핸드오프에 "유료 전용, 세션 쿠키 미설정" 으로 적혀 있었으나 `minimax/minimax-m3:free` 가 존재합니다. kimi 프로필에 `or-free/minimax-m3` 별칭 추가 |

### 4.0 측정 하네스의 기본 fixture 는 정본이 아닙니다

`scripts/measure_llm_quality.py` 의 `--fixture` 기본값은
`data/eval/llm_quality_fixture_v1.json` **24문항**입니다. 정본 비교 기준은
`llm_quality_fixture_v2.json` **32문항**입니다.

이번 세션에서 코디네이터가 `--fixture` 를 지정하지 않아 v1 으로 15분을 측정했고,
정본과 비교할 수 없어 버렸습니다. **측정 명령에 `--fixture` 를 항상 명시하십시오.**
결과 JSON 의 `item_count` 와 `fixture_path` 로 사후 확인할 수 있습니다.

### 4.1 런처 경로 워커는 편집 승인 자동화의 혜택을 받지 못합니다

`task_95b03278c33b` 이 `taskctl dispatch --terminal` 경로에 편집 승인 모드 전환을
넣었지만, **런처 방식(`dispatch --return-preamble` + preamble 파일)으로 띄운 워커는
그 경로를 타지 않습니다.** 이번 세션에서 N2 워커가 이 구멍으로 첫 편집에서 멈췄고
코디네이터가 수동으로 shift+tab 을 보냈습니다.

런처는 `exec` 로 CLI 를 대체하므로 기동 후 자기 터미널에 키를 보낼 수 없습니다.
구조적 제약이라 코디네이터 절차로 남습니다. **런처 경로로 Antigravity 를 띄웠으면
Dispatch 직후 shift+tab 을 직접 보내십시오.**

---

## 5. RAG 정본 재측정 — 두 번 시도해 두 번 다 실패했습니다

**정본은 갱신되지 않았습니다.** 이전 정본(`d9a0536` 32문항 x 3회)이 그대로
유효하며, **T7 conditional vector bypass 의 품질 회귀 판정은 여전히 미결**입니다.
T7 을 완료로 선언하지 마십시오.

### 5.1 1차 시도 — 잘못된 fixture (4.0 절)

`--fixture` 를 지정하지 않아 v1 24문항으로 15분을 측정했습니다. 정본 비교
기준은 v2 32문항이므로 버렸습니다. 결과는
`data/benchmarks/blind_fixture_full_20260828_final.json` 에 남아 있으나
**정본 대조에 쓰지 마십시오.** 요청 실패 0건, provenance 는 통과였습니다.

### 5.2 2차 시도 — 측정 중 Docker 데몬 다운

v2 32문항으로 다시 돌렸으나 **q19 시점에 Docker 데몬이 죽었습니다.**
96건 중 54건만 성공하고 42건이 실패했습니다.

| 항목 | 값 |
| --- | --- |
| `canonical` | **false** |
| `serving_model_start` | `gemma4:e2b` |
| `serving_model_end` | `''` (컨테이너 소멸로 확인 불가) |
| 저장 | 디버그 출력만 생성. **무효 데이터라 커밋하지 않았습니다** |

**provenance 게이트가 올바르게 작동했습니다.** 종료 시점 모델을 확인할 수
없으니 fail-closed 로 무효 처리했습니다. 반쪽 데이터가 정본에 들어가는 것을
막았습니다.

Docker 가 죽은 원인은 확인하지 못했습니다. 측정 중 `db` 컨테이너가 175% CPU 를
쓰고 있었고, 6장의 상세 페이지 쿼리 결함이 그 부하의 정체입니다. 리소스 압박이
원인일 가능성이 있으나 **단정할 근거는 없습니다.** 다음 측정 전에 Docker Desktop
의 메모리 할당을 확인하는 편이 낫습니다.

### 5.3 다음 측정 시 지킬 것

```bash
uv run python scripts/measure_llm_quality.py \
  --fixture data/eval/llm_quality_fixture_v2.json \
  --model-label e2b --expected-model gemma4:e2b \
  --repetitions 3 --timeout-sec 200 \
  --output data/benchmarks/<경로>
```

`--fixture` 를 반드시 명시하고, 결과 JSON 의 `item_count` 가 32, `canonical` 이
true 인지 확인한 뒤에만 정본으로 씁니다.

### 5.4 1차 시도에서 관측한 레이턴시 (참고용, 정본 아님)

v1 24문항에서 **첫 회차만 느리고 2·3회차는 2초대**였습니다.

| 문항 | r1 | r2 | r3 |
| --- | ---: | ---: | ---: |
| q21 | 163,601ms | 2,725ms | 2,539ms |
| q24 | 48,086ms | 1,900ms | 1,881ms |
| q20 | 44,951ms | 1,995ms | 1,945ms |

"긴 정확 공고명 질의가 항상 느리다" 는 이전 진단과 다른 양상입니다. **콜드 캐시
성격이 강합니다.** v2 전량 측정에서 이 패턴이 재현되는지 확인하십시오.

---

## 6. 공고 상세 페이지 로딩 지연 (다음 세션 최우선)

사용자가 공고 목록에서 상세로 들어갈 때 로딩이 오래 걸린다고 보고했습니다.
코드로 원인을 특정했고 **실측은 하지 못했습니다** (측정 중이라 DB 부하를 줄 수
없었고, 이후 Docker 가 죽었습니다).

### 6.1 원인: 전체 테이블에 window function

[`src/app/services/bid_queries.py:176`](../../src/app/services/bid_queries.py) 의
`latest_announcement_filter` 가 만드는 서브쿼리에 **WHERE 절이 없습니다.**

```python
ranked_ids = select(
    BidAnnouncement.id,
    func.row_number().over(
        partition_by=(bid_ntce_no, category),
        order_by=(bid_ntce_ord.desc(), bid_ntce_dt.desc(), collected_at.desc(), id.desc()),
    ),
).subquery("latest_ann")
return stmt.join(ranked_ids, ...).where(ranked_ids.c.latest_rank == 1)
```

공고 테이블 **전체 행**에 대해 파티션 정렬을 수행한 뒤 조인합니다. 10년치
데이터에서는 매 요청마다 수십만~수백만 행을 정렬하는 셈입니다.

### 6.2 상세 페이지가 특히 나쁜 이유

`get_announcement_detail`(458행)의 similar_bids 는 **최종적으로 5건만 필요한데,
그 5건을 고르기 전에 전체 테이블 랭킹을 계산합니다.**

```python
similar_stmt = latest_announcement_filter(
    select(BidAnnouncement).where(category == ..., dminstt_nm == ...)
).where(BidAnnouncement.id != bid.id)
similar_bids = db.execute(similar_stmt.limit(5)).scalars().all()
```

`category` 와 `dminstt_nm` 조건이 **바깥에만 있어 서브쿼리를 좁히지 못합니다.**

### 6.3 수정 방향

1. **필터 조건을 서브쿼리 안으로 밀어넣습니다.** `category` 와 `dminstt_nm` 으로
   먼저 좁힌 뒤 랭킹하면 대상이 수백 행 수준으로 줄어듭니다.
2. `past_results` 의 `dminstt_nm` 필터 + `rl_openg_dt` 정렬에 복합 인덱스가
   있는지 확인합니다. 이번에 Docker API 오류로 확인하지 못했습니다.
3. `EXPLAIN` 으로 실제 실행 계획을 먼저 확인하고, 개선 전후를 실측합니다.

**주의**: `latest_announcement_filter` 는 목록·검색·상세 여러 경로가 공유합니다.
회귀 위험이 크므로 호출부를 전부 확인하고 결과 동일성을 검증한 뒤 바꾸십시오.

---

## 7. 다음 착수 순위

| 순위 | 작업 | 비고 |
| --- | --- | --- |
| 1 | 공고 상세 페이지 쿼리 개선 | 6장. 사용자가 직접 겪는 체감 문제이며 원인이 특정돼 있습니다 |
| 2 | RAG v2 32문항 x 3회 정본 재측정 | 5장. **T7 품질 회귀 판정이 걸려 있습니다** |
| 3 | 구간 계측으로 느린 문항 지연 분해 | REST 노출까지 열려 있습니다 |
| 4 | `benchmark_rag_segments.py` 규약 레이턴시 재측정 | G3 판정 정본 |
| 5 | Servc 3,589 OOS 현 Champion 고정 평가 | 재학습 게이트 3,098 을 491 초과 |
| 6 | Windows Docker Desktop 실기 | 장비 확보 시. G2 완전 PASS 조건 |

1 번과 2 번은 순서가 있습니다. 상세 페이지 쿼리가 DB 를 175% CPU 로 밀어붙이는
상태에서 측정하면 그 부하가 RAG 수치에 섞입니다.

---

## 8. 세션 중 기동했던 것과 종료 절차

RAG 측정을 위해 Docker 스택 5개 컨테이너(`app`/`db`/`redis`/`meilisearch`/`worker`)를
띄웠습니다. 측정 중 Docker 데몬이 죽어 컨테이너는 이미 사라진 상태였고, 세션 종료
시점에 데몬을 다시 올려 정식 절차로 내렸습니다.

```bash
docker compose exec redis redis-cli SHUTDOWN NOSAVE   # dump.rdb 재생성 방지
docker compose down
```

**Redis 를 그냥 내리면 `dump.rdb` 가 다시 생깁니다.** 반드시 `SHUTDOWN NOSAVE` 를
먼저 보내십시오.

워커·터미널·워크트리·브랜치는 전부 반납했습니다. 남은 워크트리는 주 저장소
하나입니다.
