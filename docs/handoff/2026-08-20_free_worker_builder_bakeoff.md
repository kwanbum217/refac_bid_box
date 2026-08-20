# 무료 워커 builder 적합성 경합 인수인계

> **작성일**: 2026-08-20
> **Run**: `run_d2fd971f7daa`
> **관련 문서**: [`../ops/agent_worker_launch_reference.md`](../ops/agent_worker_launch_reference.md) 1.4~1.5 절, [`../ops/orca_do_not_repeat.md`](../ops/orca_do_not_repeat.md) 17 장

---

## 1. 무엇을 쟀는가

무료 모델 10종에 **동일 Capsule 로 같은 쓰기 과제**를 주고 각자 격리 워크트리에서
수행시켰다. 과제는 `scripts/audit_model_inventory.py` 의 반복 확인 로직으로,
이전 인수인계의 잔여 과업이자 실제로 필요한 코드였다.

변별 지점은 하나다. **조회 실패(`unknown`)가 연속 이탈 카운터를 올려서도
초기화해서도 안 된다.** 2026-08-20 오전의 오판이 정확히 이 구분을 놓쳐서
생겼다.

동시 쓰기 워커 상한 3 을 지켜 순차 투입했고, 슬롯이 비는 대로 대기열을
소화하는 러너로 자동화했다.

---

## 2. 결과

| 순위 | 모델 | CLI | 소요 | 중립 채점 | 테스트 |
| ---: | --- | --- | ---: | :---: | ---: |
| 1 | `opencode/nemotron-3-ultra-free` | OpenCode | 9분01초 | 8/8 | 9 |
| 2 | `or-free/laguna-xs` | Kimi | 11분03초 | 8/8 | 11 |
| 3 | `opencode/deepseek-v4-flash-free` | OpenCode | 11분31초 | 8/8 | 8 |
| 4 | `or-free/nemotron-ultra` | Kimi | 12분32초 | 8/8 | 10 |
| 5 | `opencode/mimo-v2.5-free` | OpenCode | 13분58초 | 8/8 | 9 |

실격 5종이다.

| 모델 | 사유 |
| --- | --- |
| `or-free/laguna-s` | 32분간 379KB 출력에 도구 호출 0건. 결정 불능 |
| `or-free/north-mini` | 31분50초에 테스트 미착수. 실격선 28분 초과 |
| `opencode/nemotron-3.5-lightning-free` | 4.8KB 지시문에 무의미 출력 |
| `opencode/hy3-free` | 읽기만 하고 종료 코드 0 |
| `opencode/muse-spark-1.2-contributor-free` | 지역 차단 |

### 2.1 채점 방법

각 모델은 자기 테스트를 통과했으므로 그것으로는 우열이 갈리지 않는다.
코디네이터가 **구현 내부(함수명, 상태 파일 스키마)에 의존하지 않고 `main()` 의
종료 코드와 stdout 만 보는** 행동 시나리오 8문항을 따로 만들어 5종에 동일하게
적용했다. 통과 5종은 전부 8/8 이라 정확도로는 갈리지 않았고, 순서는 소요
시간이다.

---

## 3. 반영한 것

| 대상 | 변경 |
| --- | --- |
| `main` `887b19f` | 승자(laguna-xs) 산출물 병합. 반복 확인 로직 도입 |
| `scripts/orca_model_router.py` | 신규 2종 등록, `builder` 2종 부여, 실격 3종 `suitable_for` 비움, `FREE_POOL_ORDER` 재정렬 |
| `tests/test_orca_model_router.py` | 기대값 13건 갱신. 역할 적합성 불변식 테스트를 하드코딩에서 `MODEL_POOL` 유도로 변경 |
| 기동 정본 1.4 절 | OpenCode 무료 6종 판정표 신설 |
| 기동 정본 1.5 절 | Kimi 쓰기 경로 신설, "쓰기 Task 금지" 조항 개정 |
| 반복 금지 17 장 | 이번 세션 교훈 7건 |

**저위험 Python builder 과제를 완주하는 무료 워커 스택을 처음으로 실측
선별했다.** 이전 순서는 문맥 크기와 probe 응답 시간으로 매긴 잠정치였다.

다만 **아래 순서는 능력 순위가 아니다.** 스택당 1회 실행이라 무료 엔드포인트의
편차를 분리하지 못했다. 다섯은 동등 합격군이다. 상세는 7 장.

### 3.1 Kimi 쓰기 경로

`-p` 는 `-y`/`--auto` 와 병용할 수 없지만 쓰기가 불가능한 것은 아니다. 승인
정책은 `config.toml` 의 `default_permission_mode` 가 정하고 `-p` 도 그 값을
따른다. 기본 프로필(`~/.kimi-openrouter-free`)은 `manual` 이라 막힌다.

쓰기 워커 전용 사본 `~/.kimi-openrouter-bakeoff` 를 만들어 `auto` 로 두었다.
**기본 프로필은 `manual` 그대로다.**

---

## 4. 남은 것

1. **컨텍스트 한도 미확인**: 신규 등록 2종(`nemotron-3-ultra`, `mimo`)의
   `max_tokens` 가 `None` 이다. 라우터가 경고를 내지만 실제 한도는 모른다.
2. **`reviewer` 는 여전히 닫혀 있다**: 병합 판정에 쓰이는 임계 경로라 무료 풀에
   열지 않았다. 이번 경합은 `builder` 만 검증했다.
3. **`cursor-auto` 표본 부족**: 2026-08-18 5회 중 3회 빈 출력, 2026-08-20 3회
   전부 정상. 판정을 뒤집기에 3회는 부족해 기존 주의를 유지했다.
4. **실격 판정의 재확인 주기 없음**: `suitable_for` 를 비운 3종을 언제 다시
   재볼지 정하지 않았다. deepseek 이 하루 만에 복구된 전례가 있다.
5. **경합 워크트리 정리**: 승자 외 9개 브랜치와 워크트리는 이 세션 끝에
   정리한다. 정리 여부는 아래 5 장에 적는다.

---

## 5. 자원 정리

**정리했다.** 경합 워크트리 10개를 전부 제거했고 터미널도 전부 닫았다.

| 대상 | 처리 |
| --- | --- |
| 워크트리 10개 | 제거. 주 저장소만 남음 |
| 터미널 10개 | 닫음. 남은 5개는 이 경합과 무관 |
| `bakeoff-laguna_xs` 등 6개 브랜치 | 삭제. 승자는 `main` 에 병합됐고 나머지는 커밋 0건 |
| `feat/free-pool-builder-qualification` | 삭제 (병합 완료) |

**보존한 브랜치 4개**다. 경합에서 통과했으나 채택되지 않은 대안 구현이며,
`main` 에 병합되지 않았으므로 이 브랜치가 유일본이다.

    kwanbum217/bakeoff-deepseek
    kwanbum217/bakeoff-mimo
    kwanbum217/bakeoff-nemotron_ultra
    kwanbum217/bakeoff-oc_nemotron_ultra

구현을 비교할 일이 없어지면 지워도 된다. `git branch -D` 가 필요하다.

---

## 6. 검증

    uv run pytest tests/ -q              1,564 passed, 2 skipped
    uv run python scripts/validate_agent_rules.py --quiet   12/12
    uv run ruff check scripts/ tests/    All checks passed
    origin/main                          4702c02

`scripts/audit_model_inventory.py` 실동작에서 배정 대상 6종 전부 확인,
배정 제외 3종은 건너뜀으로 나오고 종료 코드 0 이다.


---

## 7. GPT 감사와 교정 (2026-08-20)

1회차 결과를 GPT 가 감사해 6건을 지적했고 전부 사실이었다. 교정한 내용이다.

| 지적 | 교정 |
| --- | --- |
| builder 만 쟀는데 `benchmarker`·`documenter` 까지 부여 | 무료 풀 전체에서 회수. `{investigator, builder}` 불변식을 테스트로 강제 |
| n=1 결과로 1~5위 확정 | 동등 합격군으로 강등. 순서가 능력 근거가 아님을 코드 주석·문서·결과 JSON 에 명시 |
| 실격이 아니라 격리여야 함 | `실격` -> `격리(quarantine)`. 재시험 전까지의 배정 중단임을 명시 |
| 실격선을 결과 보고 설정 | 사후 기준임을 명시. 다음 회차는 시작 전 지정 |
| 채점기를 결과 보고 수정 | 사실을 결과 JSON `limitations` 에 기록. 다음 회차는 실행 전 동결 |
| 측정 장치가 버전 관리 밖 | `benchmarks/free_workers/` 로 이관 |

**지적에 없었으나 함께 고친 것이 하나 있다.** `opencode-deepseek` 과
`cursor-auto` 는 이번 경합 이전부터 근거 없이 네 역할을 갖고 있었다. 내가
기존 관행을 따라 같은 모양으로 맞춘 것이 과대 부여의 원인이었으므로, 그 둘도
함께 회수했다. 특히 `cursor-auto` 는 5회 중 3회 빈 출력 기록을 가진 채
`builder` 를 들고 `FREE_POOL_ORDER` 에 있었다.

### 7.1 남은 것

**2차 경합이 필요하다.** 합격군 5종을 서로 다른 과제 3종 이상으로 스택당
최소 3회 반복해 median, p95, 성공률, 무응답률로 재야 `FREE_POOL_ORDER` 순서를
능력 근거로 확정할 수 있다. 절차는 `benchmarks/free_workers/README.md` 5 장.

---

## 8. 2차 경합 결과 (builder_02, 같은 날)

소형 과제 1종을 스택당 3회 반복했다. 실격선(720초)과 채점기를 **실행 전에
동결**했고 라운드로빈으로 돌렸다. 성공은 시한 내 종료 AND 커밋 1건 이상 AND
채점 만점이다.

| 스택 | 성공 | median | p95 | 실패 유형 |
| --- | :---: | ---: | ---: | --- |
| `opencode/deepseek-v4-flash-free` | 3/3 | 253s | 279s | - |
| `or-free/laguna-xs` | 3/3 | 458s | 507s | - |
| `opencode/mimo-v2.5-free` | 2/3 | 456s | 506s | 승인 대기로 커밋 0 |
| `or-free/nemotron-ultra` | 2/3 | 586s | 610s | 채점 2/6 |
| `opencode/nemotron-3-ultra-free` | 1/3 | 594s | 594s | 시한 초과 2회 |

**1차 순위가 뒤집혔다.** 1차 1위(`nemotron-3-ultra`, 9분01초)가 최하위가 됐고
1차 3위(`deepseek`)가 1위다. `FREE_POOL_ORDER` 를 이 결과로 재정렬했다.

원인은 설계 판단이다. `nemotron-3-ultra` 는 매 회차 `audit()` 반환값을
3-튜플로 바꿔 기존 테스트 10건을 깨뜨리고 복구하느라 시한을 넘겼다.
`deepseek` 은 기존 시그니처를 건드리지 않았다.

### 8.1 이 값의 한계

- 반복 3회는 median 에는 충분하나 **p95 를 신뢰하기에는 부족하다.**
- 동시 3대 조건에서 측정했다. 같은 백엔드를 쓰는 스택끼리 경합이 있다.
- 과제 1종(소형 builder)만 쟀다. 역할별 적합성은 이 값으로 말할 수 없다.

### 8.2 다음 세션이 이어받을 것

과제 다양성이 아직 없다. `builder_02` 와 같은 방식으로 investigator 감사 과제와
중간 규모 리팩터 과제를 추가해 역할별 leaderboard 를 만들어야 한다. 절차는
`benchmarks/free_workers/README.md` 5 장, 도구는 `aggregate.py` 를 그대로 쓴다.

---

## 9. 다음 세션이 먼저 할 일 (GPT 3차 감사, P0)

**3차 경합을 시작하기 전에 아래 둘을 고쳐야 한다.**

### P0-1. 러너 시한 처리에 프로세스 종료를 넣는다

`benchmarks/free_workers/builder_02/run.sh` 는 시한 초과를 기록만 하고 워커를
죽이지 않는다. 2차에서 실제로 오염이 발생했다(반복 금지 17.17).

    launch 에서 orca terminal create 의 핸들을 보관
    시한 초과 -> 그 핸들만 close -> 프로세스 종료 확인
    -> 산출물 수집 -> 슬롯 반납 -> 다음 회차 허용

`pkill -f` 는 쓰지 않는다. 다른 스택까지 죽는다.

**2차 결과 중 `oc_nemo3ultra` 3회는 폐기하고 재측정한다.** 나머지 4스택
12회는 시한 초과가 없어 영향받지 않는다.

### P0-2. investigator 순서를 builder 와 실제로 분리한다

`FREE_ORDER_BY_ROLE` 의 두 키가 같은 객체를 가리킨다. 별도 목록으로 나누고,
두 순서를 다르게 둔 상태에서 역할별로 다른 모델이 선택되는지 검증하는 테스트를
추가한다(반복 금지 17.18).

### 그다음 (P1)

| 항목 | 내용 |
| --- | --- |
| 러너 preflight | base ref·워크트리·출력 디렉터리 생성, CLI 존재 확인, 채점기 self-test |
| 값 이중화 제거 | `TIMEOUT` 을 상수로 두지 말고 `capsule.yaml` 의 `benchmark.timeout_sec` 에서 읽기 |
| 집계 단위 테스트 | rc 124/1 분류, `p95_all_sec`, 분모 혼재 거부, `no_commit` |
| 분모 일관성 검사 | 한 벤치마크 안에서 채점 분모가 다르면 종료 코드 2 |
| README 재현 절차 | 환경변수와 실행 순서 |
