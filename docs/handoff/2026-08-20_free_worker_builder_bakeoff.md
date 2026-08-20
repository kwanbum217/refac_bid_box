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

**`FREE_POOL_ORDER` 가 능력 근거로 정렬된 것은 이번이 처음이다.** 이전 순서는
문맥 크기와 probe 응답 시간으로 매긴 잠정치였고 문서에 그렇게 적혀 있었다.

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
