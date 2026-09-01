# 인수인계: 2026-09-01 컷오버 세션

> **작성일**: 2026-09-01
> **Run**: `run_6872c388bbf2` (K), `run_079be53ebd6e` (M), `run_81f81026d487` (R),
> `run_aae381c7bbc0` (U), `run_3b75cc9989a0` (V), `run_28ccbb883837` (W)
> **기준 HEAD**: `c21fabf` (`main`)
> **이전 인수인계**: [`handoff_20260901_wave_k.md`](handoff_20260901_wave_k.md)
> **이 문서가 우선하는 범위**: 3장 이후. 이전 문서 4장(ngram 순서)은 전부 닫혔습니다

---

## 1. 이 세션이 끝낸 것

| 항목 | 결과 | 근거 |
| --- | --- | --- |
| I-H 경계값 픽스처 | `main` 병합 | `a0ec7e3` |
| J3 리뷰 문서 이식 | `main` 병합 | `32b2426` |
| dispatch 테스트 회귀 27건 | 시정 | `7dac20f` |
| 워커 감시 fail-closed 강제화 | `main` 병합 | `1cdcb51` |
| 운영 ngram FULLTEXT | 생성 후 **기각·제거** | `c733d4d`, `cf9c937` |
| 경계값 7클래스 | **실측 완료** | `edge_07`·`edge_11` 만 누락 |
| 콜드 SQL 총량 | **관찰 지표로 강등** | `7266b45` |
| G3 레이턴시 게이트 | **전 항목 통과** | `f2310c3` |
| **Phase 7 컷오버** | **선언 (조건부)** | `e9934e9` |
| RAG vector 최적화 | 판정 완료 | `d8deba1`. 임베딩 재사용만 병합(`7832292`), wide-fetch 기각 |
| RAG llm 최적화 | 판정 완료 | `04fcb8d`. 후보 넷 전부 닫음, 기동 예열로 콜드 70% 제거 |
| Servc 낙찰하한율 경로 | **재확인·문서 정정** | `6b35a05`. 새 발견 없음. 문서 세 곳 정정, 기각 목록 2건 등록 |
| 자동 승인 읽기 전용 DB 조회 | `main` 병합 | `44b56f3`. docker 통째 보류가 조사 워커를 막던 결함 |
| 읽기 전용 질의 실행기 | `main` 병합 | `831c5ae`, `05984c9`. `db_readonly_query.py` + uv 화이트리스트 |
| **외부 감사 P0/P1 대응** | **7건 중 6건 해소** | Wave U/V/W/X/Y. 상세는 2.8 절 |
| **CI RED 복구** | **워크플로 success** | run `33508869670`. 감사 지적 이후 처음 |
| Wave Z (Windows 테스트 비용, 상태 원장, 스킬 조항) | `main` 병합 | Z1 `beb61e4`, Z2 `b13b6db`·`9db5d58`, Z3 `390ee90` |
| **Windows CI hang 규명** | **해소. 게이트 복귀** | 4.0 절. 원인은 도구의 이식성 결함 두 건. run `33521743699` 8 job 전부 green |
| kimi 워커 대화형 가능성 | **불가로 확정** | 2.9 절. `tui-idle` 대기 후에도 주입 시 종료 |

Z1 은 `-p` 단발 모드라 정체 해제 지시가 도달하지 않아 코디네이터가 직접
마무리했습니다. 산출물 3건 중 `tiny_lgbm_cache` 는 **기각**했습니다. CI 가 매 실행
새 러너라 이득이 0 이고, `tmp_path_factory` 를 버려 작업 트리를 오염시키며, 학습
함수가 바뀌어도 낡은 `model.bin` 을 재사용하는 캐시 무효화 결함이 있습니다.

활성 워커 0, 워크트리는 주 저장소만입니다. **회수했습니다.** 다만 Z1·Z2 의
워크트리·터미널은 감사기가 잡지 못해 한 차례 늦었습니다(2.10 절).

---

## 2. 이 세션이 뒤집은 종전 판단 네 가지

### 2.1 ngram 선행필터는 효과가 없습니다

Wave F3 은 `dminstt_nm` 19.0배 개선을 예측했으나 운영 실측에서 재현되지 않았습니다.
원인은 probe 가 **소규모 스키마의 warm 배율**이었다는 것입니다. 운영 27GB 콜드에서는
`GROUP BY` 의 `Using temporary; Using filesort` 가 남고 1.4GB ngram 인덱스 적재 비용이
스캔 절감분을 상쇄합니다. 인덱스는 제거했고 코드는 기본값 OFF 로 남겼습니다.

### 2.2 콜드 SQL 총량은 게이트가 아닙니다

**같은 코드, 같은 조건에서 333.19초와 432.99초가 나왔습니다.** 원인은
`innodb_buffer_pool_size` 가 기본값 128MB 인 채로 데이터가 27GB 였다는 것입니다.
버퍼풀을 2GB 로 배선하고 측정 규약 5.4 절에 DB 상태 기록을 필수로 넣었습니다.

### 2.3 c2 미달은 코드 결함이 아니었습니다

3개월 가까이 컷오버를 막던 항목입니다. 당시 측정의 호스트 부하가 **42.45%** 로 규약
임계(중앙 30%)를 넘겼고, 규약 안에서 재측정하니 **19.66ms** 로 통과했습니다.

### 2.4 런북이 잘못된 컬럼을 지정하고 있었습니다

`bid_results` 에 `bidwinnr_nm` 인덱스를 만들라고 적었으나 운영 코드가 MATCH 를 거는
컬럼은 `dminstt_nm` 입니다. 이 오기로 첫 실측이 전부 skip 됐습니다.

### 2.5 RAG 병목은 종전 분석이 지목한 곳이 아니었습니다

`vector_segment_optimization_20260830.md` 는 vector 구간의 95% 를 "bge-m3 CPU 순전파"
로 추정했으나(그 문서 스스로 "실측 미수행" 명시), 실측하면 임베딩 45ms, HNSW 3.4ms 이고
**병목은 메타데이터 `where` 절**입니다(`category` 하나로 344배). 그러나 결과 불변 해법이
없어 기각했습니다(fixture 96건 중 6건 불일치).

llm 구간도 후보 넷을 전부 닫았습니다. `SYSTEM_PROMPT` 는 Ollama 가 접두사를 캐시해
46% 를 줄여도 prefill 이 9% 만 줄고, 컨텍스트는 이미 3건 250자로 절제돼 있으며 응답도
평균 248자입니다. 남는 것은 `gemma4:e2b` 의 99 tok/s 입니다.

**실질 문제는 콜드 비용이었습니다.** 기동 예열로 첫 질의 중앙 31,398ms 를 18,784ms 로
낮췄습니다(콜드 초과분의 약 70%). 아울러 컨테이너 루트 로거 때문에 종전 예열 로그가
한 줄도 남지 않던 결함을 고쳤습니다.

상세는 [`../analysis/vector_metadata_prefilter_verdict_20260901.md`](../analysis/vector_metadata_prefilter_verdict_20260901.md)
와 [`../analysis/rag_llm_segment_and_warmup_20260901.md`](../analysis/rag_llm_segment_and_warmup_20260901.md).

### 2.6 Servc 낙찰하한율 개선 경로는 애초에 없었습니다

`CURRENT_STATE` 2.5 절이 개선 경로를 "낙찰하한율 결측 보전" 으로 적고 있어 조사를
시작했으나, **같은 주제가 2026-08-30 에 이미 완결**돼 있었습니다.

| 항목 | 2026-08-30 판정 |
| --- | --- |
| 결측 1,356건의 성격 | **100% 제도적 개념 부재**, 수집 누락 0건 |
| DB 내 보전 | 0건 |
| 외부 API 보전 | 차단 확인 |
| 추정 대입 | 기각(오차 7~12%p 폭증) |

두 집단은 실제 낙찰률 분포가 다른 **별도 모집단**입니다(결측 94.95%/SD 5.19,
보유 88.67%/SD 2.62). 값을 채워서 좁혀질 차이가 아닙니다.

**더 위험했던 것은 그 문서가 대응 경로로 "계약방식별 분리 모델링" 을 권고한 점입니다.**
그 설계는 2026-08-03 에 세 세그먼트 전부 실측 기각(전체 R2 0.6659 대 0.6683)됐고
2026-08-07 문서가 "두 번 실패했다" 로 못 박은 것입니다. 권고를 그대로 따랐다면
세 번째 실패였습니다.

문서 세 곳을 정정하고 기각 목록에 2.11(분리 모델), 2.12(결측 보전)을 등록했습니다.
근거는 [`../analysis/servc_lwlt_path_reconfirmation_20260901.md`](../analysis/servc_lwlt_path_reconfirmation_20260901.md).

**Servc 모델은 사전 순위 축이 전부 닫혔습니다. 남은 것은 새 정보 수집입니다.**

### 2.7 워커가 DB 질의마다 막히던 원인은 정책이었습니다

`orca_auto_approve.py` 가 **docker 명령을 통째로 보류**하고 있었습니다. 감시기는 정상
부착돼 있었고 정책이 막고 있었습니다. K4R 이 강제한 "감시기가 붙는가" 와는 다른 층입니다.

`SELECT`·`SHOW`·`EXPLAIN` 으로만 이루어진 `mysql -e` 질의는 승인하고, `sh -c` 경유·
대화형 세션·쓰기 SQL 은 계속 보류합니다(회귀 테스트 8건).

**다만 이것만으로는 부족합니다.** 워커가 명령 형태를 `sh -c` 로 감싸면 여전히 막힙니다.
조사 Task 를 낼 때는 **허용되는 명령 형태를 Capsule 에 못 박거나, 읽기 전용 질의
스크립트를 만들어 그것만 부르게** 하십시오.

### 2.8 외부 감사 대응 (Wave U/V/W/X/Y)

2026-09-01 외부 감사가 P0/P1 7건을 지적했고 **모든 주장을 직접 검증한 뒤** 작업했습니다.
`main` CI 는 RED 였고(3회 연속) 지적은 사실이었습니다.

| 지적 | 결과 | 근거 |
| --- | --- | --- |
| P1-1 ngram 테스트 계약 모순 | **해소** | safe/unsafe 분리, CI job green 복귀 |
| P1-2 ngram CI 로그 유실 | **해소** | `bash -e` 가 pytest 출력을 삼키던 것 |
| P1-3 `CURRENT_STATE` stale 항목 | **해소** | 6.1 ngram 항목·Wave F 구형 서술 갱신 |
| P1-4 약한 docker 승인 경로 | **해소** | `hold` 로 되돌려 단일 경로로 수렴 |
| P1-5 리뷰어 unknown provider | **해소** | 고위험·쓰기 fail-closed |
| P0-2 G2 문서 재평가 | **해소** | 구형 SHA 근거를 현 CI 사실로 교체 |
| P0-1 Windows CI | **해소(게이트 복귀)** | 4.0 절. 원인은 오케스트레이션 도구의 이식성 결함 두 건이었습니다 |

**감사가 옳았던 지점**: 제가 만든 `classify_docker_execution` 이 `WITH ... UPDATE` 와
`SELECT ... INTO OUTFILE` 을 승인했습니다. 강한 실행기를 만들면서 약한 경로를 지우지
않은 것이 원인이며, 실행으로 확인하고 닫았습니다.

**Windows 는 네 층을 닫았습니다.** 342초 -> 212.90초(30% 감소).

| 층 | 원인 | 효과 |
| --- | --- | --- |
| 1 | 미모킹 dispatch 테스트 4건 x 30초 폴링 | `test_orca_taskctl.py` 126.84초 -> 1.37초 |
| 2 | 단위 테스트의 실제 하위 프로세스 생성 | 대상 5파일 22.25초 -> 3.95초 |
| 3 | **PBKDF2 600,000회** (Windows 2,300ms 대 macOS 45ms) | `call` 4.6초 균일 지연 해소 |
| 4 | fixture setup (LightGBM 재학습, 임포트된 이름) | 18.60->9.09초, 4.30->0.08초 |

3 층은 **같은 코드가 플랫폼에 따라 50배 차이**가 난 사례입니다. macOS 는 OpenSSL
가속으로 45ms 인데 Windows CPython 은 2,300ms 입니다.

4 층에서는 `from ... import make_password` 로 가져간 이름이 **가져간 모듈의
네임스페이스에 따로 존재**해 원본 모듈 패치가 닿지 않았습니다.

**이 네 층은 hang 과 무관했습니다.** 당시 게이트에서 제외하며 적은 "342초 ->
212.90초" 는 완주 시간이 아니라 정지 시점까지의 시간이었고, 매 실행 2090 건에서
끊겨 약 950 건이 실행되지 않았습니다. 속도 개선은 사실이나 그것이 통과를 뜻하지는
않았습니다. 실제 원인과 해소는 4.0 절입니다.

**같은 세션 후반에 원인을 규명해 `continue-on-error` 를 제거했습니다.** Windows 가
게이트에 포함된 상태로 전 job green 입니다(run 33521743699).

### 2.9 kimi 워커는 다른 워커와 같은 방식으로 쓸 수 없습니다

**실측으로 확정했습니다.** kimi CLI 자체는 대화형 TUI 가 정상 동작하지만, Orca 의
프롬프트 주입 경로를 TUI 가 종료로 처리합니다.

| 시도 | 결과 |
| --- | --- |
| `--agent-file` 로 지시 로드 + 대화형 기동 | TUI 는 뜨지만 스스로 시작하지 않음 |
| `sleep` 후 `terminal send --enter` | `Bye!` 종료 |
| `terminal wait --for tui-idle`(`satisfied: true`) 후 `send --enter` | `Bye!` 종료 |
| `--enter` 없이 텍스트만 `send` | `Bye!` 종료 |

**타이밍 문제도, Enter 문제도 아닙니다.** 공식 스킬이 권하는
`orca terminal wait --for tui-idle` 로 준비를 확인한 뒤 보내도 같습니다.
`scripts/orca_kimi_launch.py` 주석의 "주입된 Enter" 설명보다 범위가 넓습니다.

kimi 공식 문서상 대화형 TUI 에 외부에서 프롬프트를 넣는 수단은 **존재하지
않습니다.** 프롬프트 입력은 `-p` 하나뿐이고 stdin·파일 리다이렉션도 없습니다.
유일한 프로그램 제어 경로는 `kimi acp`(JSON-RPC over stdio)이며, 이는 Orca 가
ACP 클라이언트로 붙어야 해서 **Orca 쪽 기능 없이는 쓸 수 없습니다.**

| 결론 | 내용 |
| --- | --- |
| 배정 | `-p` 단발만 가능. **작업 중 개입 불가** |
| 금지 | 임계 경로, 중간 조정이 필요한 작업 |
| 정체 시 | 지시 재전송이 **도달하지 않습니다.** 재기동하거나 코디네이터가 직접 마무리합니다 |

Z1 이 `"Now let me commit:"` 에서 토큰이 끊겼을 때 보낸 해제 지시는 화면에 글자로
찍혔을 뿐 도달하지 않았습니다. **화면 표시를 도달로 판단하지 마십시오.**

### 2.10 완료 세션 감사기에는 사각지대가 있습니다

`scripts/orca_settled_session_audit.py` 는 **Task 가 `completed` 인 세션의 잔류만**
검사합니다. 워커가 `worker_done` 없이 끝나면(토큰 소진, 창 이탈) Task 가
`completed` 가 아니므로 "완료 세션 잔류 없음" 이 나옵니다.

이번 세션에서 Z1·Z2 의 워크트리 2개와 터미널 2개가 그렇게 남았고, 감사기 출력만
믿어 넘어갔다가 사용자가 먼저 발견했습니다. **감사기 출력과 별개로
`git worktree list` 와 `orca_worker_watch.py` 를 함께 보십시오.** 후자는 같은
잔류를 `[진행] commits=0 dirty=0` 으로 보여 줍니다.

---

## 3. 바로 이어서 (승인 없이 가능)

### 3.1 (종결) 낙찰하한율 결측 보전

**착수하지 마십시오. 경로가 없습니다.** 2.6 절과 기각 목록 2.12 를 보십시오.
분리 모델링(기각 목록 2.11)도 대안이 아닙니다.

유효하게 남은 대응은 **결측 집단 전용 예측구간 관리** 하나이며, 현재 피복률이
`missing_lwlt` 92.04% / `with_lwlt` 89.16% 로 목표 90% 에 근접해 시급하지 않습니다.

### 3.2 그 밖

**승인 없이 할 수 있는 잔여 작업이 없습니다.** 컷오버가 선언됐고 RAG·Servc 두 축이
모두 닫혔습니다. 남은 것은 4장의 후속 과업뿐입니다.

---

## 4. 후속 과업

### 4.0 Windows CI hang (해소, 게이트 복귀)

**닫혔습니다.** Windows job 이 처음으로 전량을 완주했고 `continue-on-error` 를
제거해 병합 게이트에 복귀시켰습니다. 근거는
[`windows_ci_soft_fail_20260901.md`](../analysis/windows_ci_soft_fail_20260901.md)
후속 절입니다.

#### 종전 판단이 틀렸던 지점

soft-fail 을 결정할 때 인용한 "342초 -> 212.90초" 는 **완주 시간이 아니라 정지
시점까지의 시간**이었습니다. Windows 는 매 실행 정확히 `2090 passed` 에서
`subprocess.py:1282` 의 KeyboardInterrupt 로 끊겼고 약 950 건이 실행되지
않았습니다. "Windows 도 통과한다" 는 근거는 성립한 적이 없습니다.

위 표에 "남은 원인" 으로 적었던 느린 테스트 넷은 **hang 과 무관했습니다.**
속도는 hang 의 원인이 아니며, 그쪽을 줄여도 정지 지점은 그대로였습니다.

#### 정지 지점 특정 방법

Windows 에만 `-v` 를 켜 마지막 완료 테스트를 남겼습니다(run 33518498545).
`-q` 로는 알 수 없고, `-v` 는 **완료 시** 줄을 찍으므로 마지막 출력의 **다음**
테스트가 정지 지점입니다.

    tests/test_orca_taskctl.py::test_dispatch_suppresses_mode_switch_when_env_disabled PASSED
    !!!!!!!!!!! KeyboardInterrupt !!!!!!!!!!!

정지 지점은 `test_dispatch_handles_mode_switch_failure_and_exception_gracefully`
입니다. 로컬 `--collect-only` 순서에서 2110 번째(2090 passed + 20 skipped)를
계산해도 같은 위치가 나오므로, CI 왕복 전에 후보를 좁힐 수 있습니다.

#### 원인 두 가지 (서비스 코드가 아니라 오케스트레이션 도구의 이식성 결함)

| 원인 | 위치 | 수정 |
| --- | --- | --- |
| 테스트가 실제 배경 감시기를 기동 | `start_worker_watch` 미 mock | autouse 픽스처로 차단 |
| `start_new_session` 이 Windows 에서 무시됨 | `scripts/orca_taskctl.py` | `CREATE_NEW_PROCESS_GROUP \| DETACHED_PROCESS` |
| `signal.SIGKILL` 이 Windows 에 없음 | `scripts/orca_taskctl.py` | `getattr` 로 SIGTERM 폴백 |

dispatch 테스트가 `orca_worker_watch.py --watch` 무한 루프를 러너에 실제로
띄웠고, 분리되지 않아 부모와 같은 콘솔 그룹에서 인터럽트가 전파됐습니다.

#### 결과

| 실행 | Windows |
| --- | --- |
| 33517528907 | 2090 passed 후 hang |
| 33518498545 | 2090 passed 후 hang (정지 지점 특정) |
| 33519652341 | 3024 passed, 1 failed (SIGKILL) |
| 33520619561 | 3025 passed, 0 failed |
| **33521743699** | **3025 passed — 게이트 포함 전 job green** |

**G2 판정의 근거가 처음으로 실제와 일치합니다.** 다만 4.1 의 실기 검증은
그대로 미결입니다.

### 4.1 Windows Docker Desktop 실기 검증 (장비 대기)

| 항목 | 내용 |
| --- | --- |
| 선행 조건 | Windows 장비 확보 |
| 검증 범위 | `docker compose up` 전 서비스 healthy, 예측 API 응답, 마이그레이션 |
| **실패 시** | **G2 를 미통과로 되돌리고 컷오버 선언을 철회합니다** |

### 4.2 콜드 SQL 관찰 (게이트 아님)

버퍼풀 2GB 조건에서 추세만 기록합니다. **통과·미달 판정에 쓰지 마십시오.**
비교는 버퍼풀 크기와 DB 연속 가동 시간이 같은 측정끼리만 합니다.

### 4.3 조사 Task 의 DB 접근 (해소)

`scripts/db_readonly_query.py` 를 추가했습니다. 워커가 `docker exec ... mysql` 을
손으로 조립하면 형태가 바뀔 때마다 승인 대화창에 걸리므로, **전용 실행기만 부르게**
합니다.

> **주의**: `uv run python scripts/...` 가 원래부터 승인 대상인 것은 **아니었습니다.**
> `uv` 는 `uv run pytest` 만 허용하는 분기에 걸려 있어, 실행기를 만들어도 워커가 그대로
> 막혔습니다. 문서 예시를 실제로 실행해 보고서야 드러났습니다. 같은 날
> `UV_RUN_ALLOWED_SCRIPTS` 화이트리스트를 추가해 이 실행기만 승인하도록 열었습니다.
> **다른 스크립트를 그 목록에 넣을 때는 그 스크립트가 스스로 쓰기를 막는지 확인하십시오.**

```bash
uv run python scripts/db_readonly_query.py --sql "SELECT COUNT(*) FROM bid_results"
```

`SELECT`·`SHOW`·`EXPLAIN`·`DESC`·`WITH` 단일 문장만 통과하고, 세미콜론 다중 문장과
`INTO OUTFILE` 우회를 거부하며 `READ ONLY` 트랜잭션으로 드라이버 수준에서도 쓰기를
막습니다. 조율 스킬 2.5 절에 반영했고 회귀 테스트 27건을 붙였습니다.

**Capsule 의 `ground_truth` 에 이 명령 형태를 못 박으십시오.** 형태를 자유롭게 두면
워커는 매번 다른 명령을 만들어 냅니다. 2026-09-01 에 "docker compose exec 형태를
쓰라" 고 적었는데도 워커가 `docker exec -i ... sh -c '...'` 로 감싸 반복해서 막혔습니다.
**허용 형태를 적는 것만으로는 부족하고, 금지 형태와 그 이유를 함께 적어야 합니다.**

Intent 의 `ground_truth` 에 그대로 넣을 문장입니다.

```yaml
ground_truth:
  - "재조사 불필요: DB 조회는 반드시 uv run python scripts/db_readonly_query.py --sql \"<질의>\" 형태만 쓴다. docker exec, docker compose exec, mysql 을 직접 부르지 말라. sh -c 로 감싸지 말라. 그 형태들은 자동 승인 대상이 아니라 질의마다 사람 승인을 기다리게 되어 작업이 멈춘다."
  - "재조사 불필요: 실행기는 SELECT, SHOW, EXPLAIN, DESC, WITH 로 시작하는 단일 문장만 받는다. 세미콜론으로 여러 문장을 이어 붙이면 거부된다. 질의를 나누어 여러 번 실행하라."
  - "재조사 불필요: 결과가 많으면 --limit 로 조절하고 기계 판독이 필요하면 --format json 을 쓴다. 기본 상한은 200행이다."
```

`review_checklist` 에도 한 줄 넣어 두면 리뷰어가 잡습니다.

```yaml
review_checklist:
  - id: raw_db_command
    question: db_readonly_query.py 를 거치지 않고 docker 나 mysql 을 직접 불렀는가
    defect_when: yes
    how: 보고와 터미널 이력에서 docker exec, docker compose exec, mysql 을 검색한다
```

### 4.4 상시 과제

`AGENTS.md` 는 G3 를 상시 과제로 규정합니다. 컷오버는 최적화의 종료가 아닙니다.

**다만 두 축은 이 세션에서 닫혔습니다.**

| 축 | 상태 |
| --- | --- |
| RAG | vector 는 메타데이터 필터가 원인이나 결과 불변 해법 없음. llm 은 후보 넷 소진. 정상 상태는 구조적 하한 |
| Servc | 사전 순위 축 전부 소진. 남은 것은 새 정보 수집 |

**남은 지렛대는 모델·하드웨어 교체이며 둘 다 별도 판단 사항입니다.** 새 최적화를
제안하기 전에 [`orca_do_not_repeat.md`](orca_do_not_repeat.md) 2 장부터 확인하십시오.

---

## 5. 이 세션에서 드러난 반복 금지

| 금지 | 올바른 동작 |
| --- | --- |
| 측정 중 저장소 수정 | `start_clean` 게이트가 `canonical=false` 로 막습니다. 측정 전 커밋하고 동결하십시오 |
| tail 분석 도구를 게이트 도구로 사용 | 게이트는 `benchmark_latency.py`. `benchmark_predict_tail.py` 는 `--trace-log` 필수인 구간 분해용입니다 |
| probe 배율을 운영 개선치로 이전 | 규모와 캐시 상태가 다르면 배율은 이전되지 않습니다 |
| 표본 0건 PASS 를 실측으로 읽기 | `compare_id_sets` 는 공집합끼리도 통과시킵니다. 표본 수를 함께 확인하십시오 |
| 한 번 측정으로 회귀 판정 | 동일 조건 재측정 없이는 변동폭을 모릅니다 |
| 미달을 코드 결함으로 단정 | 그 측정이 규약(부하 임계)을 지켰는지 먼저 확인하십시오 |
| `mysql` 클라이언트 charset 미지정 | `--default-character-set=utf8mb4` 없으면 한글이 깨져 매칭이 0 이 됩니다 |
| 워커가 셸 리다이렉션·heredoc 으로 파일 쓰기 | 자동 승인 화이트리스트 밖입니다. 편집 도구를 쓰라고 지시하십시오 |
| 측정 중 저장소 수정 | `start_clean` 과 `target_source_git_dirty` 가 산출물을 무효로 만듭니다. 이 세션에서 두 번 겪었습니다 |
| **정지한 CI 의 `passed` 수치를 완주로 읽기** | `... in N초` 앞의 `passed` 는 **끊긴 시점까지**의 수입니다. 수집된 전체 건수와 대조하십시오. 이 세션에서 950 건 미실행을 통과로 오독했습니다 |
| **`-q` 로 hang 지점을 찾으려 하기** | `-v` 를 켜면 마지막 완료 테스트가 남고 그 **다음**이 정지 지점입니다. `--collect-only` 순서로 CI 전에 후보를 좁힐 수 있습니다 |
| **테스트가 배경 프로세스를 실제로 띄우게 두기** | 러너에 무한 루프가 남고 Windows 에서는 콘솔 그룹을 공유해 pytest 를 죽입니다. autouse 픽스처로 차단하십시오 |
| **POSIX 전용 API 를 플랫폼 분기 없이 쓰기** | `start_new_session`, `signal.SIGKILL` 은 Windows 에 없거나 무시됩니다. 크로스 플랫폼(G2)은 서비스 코드뿐 아니라 **도구 코드**에도 적용됩니다 |
| **kimi 워커에 지시를 재전송하고 도달했다고 판단** | `-p` 단발이라 입력을 읽지 않습니다. 화면 표시는 도달이 아닙니다. 2.9 절 |
| **완료 세션 감사기 출력만으로 회수 완료를 선언** | `worker_done` 없이 끝난 세션은 잡히지 않습니다. `git worktree list` 와 `orca_worker_watch.py` 를 함께 보십시오. 2.10 절 |
| tail 분석 도구를 게이트 도구로 사용 | 게이트는 `benchmark_latency.py` 입니다 |
| 배경 대기 루프를 회수하지 않기 | 측정을 중단하면 그 결과를 기다리던 루프도 함께 죽이십시오. 이 세션에서 좀비 4건이 남았습니다 |
| 분석 문서의 구간 추정을 근거로 사용 | "실측 미수행" 이라고 적혀 있으면 추정입니다. 직접 재십시오 |
| 표본 몇 건 일치를 결과 동등성으로 읽기 | 96건 대조에서 6건이 깨졌습니다 |
| 강한 경로를 추가하고 약한 경로를 남기기 | `db_readonly_query.py` 를 만들고도 `classify_docker_execution` 이 `WITH ... UPDATE` 를 승인했습니다 |
| 문서에 적은 명령을 실행해 보지 않기 | "`uv run python` 은 자동 승인 대상" 이 사실이 아니었고 예시를 돌려 보고서야 드러났습니다 |
| 워커 모델을 손으로 지정 | 라우터가 배정 정본입니다. 벗어나면 `WORKER_MODEL_NOTICE` 를 남기십시오 |
| `worker_done` ack 후 회수를 미루기 | 검증·병합에 들어가기 전에 회수하십시오. `settled_session_audit` 통과가 회수 완료를 뜻하지 않습니다 |
| 감시 없이 워커를 방치 | `--watch` 는 차단을 만나면 종료합니다. 종료되면 **다시 걸어야** 합니다 |
| 플랫폼 차이를 코드 결함으로 오인 | PBKDF2 가 macOS 45ms, Windows 2,300ms 였습니다. 같은 코드입니다 |
| 착수 전 기존 조사 미확인 | `docs/analysis/` 를 먼저 검색하십시오. 낙찰하한율은 이미 완결된 주제였습니다 |
| 분석 문서의 권고를 기각 목록과 대조 없이 수용 | 작성자가 이력을 확인하지 않았을 수 있습니다. 분리 모델링이 그 사례입니다 |
| `CURRENT_STATE` 요약을 근거로 착수 | 요약은 상세 분석보다 뒤처집니다. 같은 날 문서라도 어긋납니다 |

---

## 6. 세션 종료 점검표

**2026-09-01 세션 종료 시점에 아래 값을 하나씩 실측해 기록했습니다.**

> 최종 갱신: Windows CI 규명과 Wave Z 병합, 자원 회수까지 반영한 값입니다.

### 6.1 저장소

| 항목 | 값 |
| --- | --- |
| 주 저장소 HEAD | `main` `b43cec3` + 이 커밋 |
| 원격 동기 | `origin/main` 과 차이 **0** (푸시 완료) |
| 워크트리 | 주 저장소만 (`git worktree list` 1행) |
| 전체 테스트 | **3,041 passed**, 12 skipped, 실패 0 |
| 미병합 브랜치 | **6개** (6.4 절과 일치) |
| 로컬 실행 시간 | 202초 -> **50초** |
| 규칙 검사 | **17/17** (기계 상태 원장 검사 추가) |
| **CI 워크플로** | **success** (run `33521743699`) |
| CI job | **8개 전부 green.** Windows 포함, `continue-on-error` 제거 후 |

### 6.2 운영 환경

| 항목 | 실측값 |
| --- | --- |
| 컨테이너 | app / db / meilisearch / redis **healthy**, worker 가동 |
| DB 버퍼풀 | **2GB** (`MYSQL_BUFFER_POOL_SIZE` 기본값) |
| FULLTEXT 잔여 인덱스 | **0** (생성 후 기각·제거 완료) |
| `bid_announcements` 행 수 | **5,490,072** (불변) |
| `bid_results` 행 수 | **3,423,008** (불변) |
| `NGRAM_PREFILTER_ENABLED` | `false` |
| `LATENCY_SEGMENT_LOGGING` | `false` (측정 후 원복) |

행 수 두 건은 27GB 테이블을 두 번 재구축(FULLTEXT 생성·제거)한 뒤에도 컷오버 전
정본과 같습니다. **G1 데이터 무손실이 유지됩니다.**

### 6.3 자원 회수

| 대상 | 상태 |
| --- | --- |
| 활성 워커 / 잔류 세션 | **0 / 없음.** 감사기 통과와 별개로 `git worktree list`·`orca_worker_watch.py` 로 재확인했습니다(2.10 절) |
| 워커 터미널 | 코디네이터 1개만 남음 |
| 배경 프로세스 | **0** (측정·감시·승인 감시기 전부 종료). 종료 직전 4건이 남아 있어 다시 회수했습니다 |
| 좀비 대기 루프 | **회수했다** (4건, 조건이 영영 충족되지 않던 것) |
| 고아 워커 감시자 | **회수했다** (2건, 그중 하나는 삭제된 워크트리를 보고 있었음) |
| Wave U/V/W 워커 6대 | **회수했다** (U1·U2·U3·V1·W1 및 워크트리·브랜치) |
| Wave Z 워커 3대 | **회수했다** (Z1·Z2 워크트리·터미널, Z1~Z3 브랜치) |
| 진단·수정 브랜치 5개 | **삭제했다** (state-refresh, win-hang-diag, win-hang-fix, win-signal-fix, win-gate-restore) |
| kimi 실험 자원 | **회수했다** (워크트리 2개, 터미널 2개, 브랜치 2개) |

> **이 세션에서 자원 회수를 네 번 놓쳤습니다.** 좀비 대기 루프 4건, 고아 감시자 2건,
> V1 세션, 그리고 Wave Z 의 워크트리·터미널 2쌍입니다. 넷 중 셋을 사용자가 먼저
> 지적했습니다.
>
> **`orca_settled_session_audit.py` 통과가 회수 완료를 뜻하지 않습니다.** 그 도구는
> Task 가 `completed` 인데 워커 터미널이 열린 경우를 잡습니다. `worker-release` 를
> 하지 않으면, 그리고 **워커가 `worker_done` 없이 끝나 Task 가 `completed` 가 되지
> 못하면** 그 조건에 걸리지 않아 통과합니다. Wave Z 가 후자였습니다. `git worktree
> list`, `orca terminal list`, `orca_worker_watch.py` 로 실물을 직접 보십시오.

**배경 프로세스는 세션 종료 시 반드시 0을 확인하십시오.** 이 세션에서 사용자가
먼저 지적할 때까지 좀비 4건이 남아 있었고, **종료 판정 직전에 다시 4건이
발견됐습니다.** 지속 감시 래퍼 1건과 `orca_worker_watch.py --watch` 3건이며 그중
하나는 이미 삭제된 `orca-z1-win` 워크트리를 보고 있었습니다. 측정을 중단하면 그
결과를 기다리던 루프도 함께 죽여야 하고, **워커를 회수한 뒤에는 그 워커를 보던
감시기도 함께 죽여야 합니다.** 감시기는 대상이 사라져도 스스로 끝나지 않습니다.

확인 명령은 다음 하나입니다. 워크트리·터미널만 보고 0 이라고 판단하지 마십시오.

```bash
ps -eo pid,etime,command | grep -E "orca_worker_watch|orca_auto_approve|persistent_watch" | grep -v grep
```

### 6.4 미병합 보존 브랜치 (6개, 지우지 마십시오)

| 브랜치 | 커밋 | 보존 이유 |
| --- | --- | --- |
| `kwanbum217/orca-i-c` | `9210641` | I-C 반려 보존본 (`citations_wrong`) |
| `kwanbum217/orca-i-f` | `f9184f5` | 재기반본이 `main` 에 병합됨. 구 SHA |
| `kwanbum217/orca-i-h` | `d8aa9a9` | 내용은 `a0ec7e3` 로 병합. SHA 가 달라 `-d` 거부 |
| `kwanbum217/orca-j3` | `4621631` | 문서만 이식하고 코드 커밋이 남음 |
| `kwanbum217/orca-k4-sup` | `cb46fc0` | K4 반려 보존본. K4R 이 대체 |
| `kwanbum217/orca-p1-embed-reuse` | `5fcc712` | **vector wide-fetch 기각본.** 결과 동등성 실패 |

**6개 전부 `origin` 에 올려 두었으며 로컬과 SHA 가 일치합니다.** 로컬만 지워지는
사고가 나도 원본이 남습니다. 마지막 `orca-p1-embed-reuse` 는 후보 수에 무관하게
동일 결과를 보장하는 방법이 생기면 다시 검토할 근거입니다.

### 6.5 다음 세션이 볼 곳

| 순서 | 내용 |
| --- | --- |
| 1 | 이 문서 4 장 (후속 과업). **승인 없이 가능한 잔여 작업은 없습니다** |
| 2 | [`orca_do_not_repeat.md`](orca_do_not_repeat.md) 2 장. 새 최적화 제안 전 필독 |
| 3 | [`../context/CURRENT_STATE.md`](../context/CURRENT_STATE.md) 1~2 장 (게이트·지표 정본) |

**컷오버는 조건부 선언 상태입니다.** Windows Docker Desktop 실기 검증이 실패하면
G2 를 미통과로 되돌리고 선언을 철회합니다(4.1 절).

### 6.6 착수 직후 확인할 것

| 항목 | 명령 | 이유 |
| --- | --- | --- |
| 테스트 기준선 | `uv run pytest tests/ -q` | 인수인계 수치를 믿지 말고 직접 잡습니다 |
| 규칙 정합성 | `python3 scripts/validate_agent_rules.py --quiet` | `source_commit` 신선도가 자주 걸립니다 |
| 자원 잔류 | `git worktree list`, `python3 scripts/orca_worker_watch.py` | 감사기만으로는 부족합니다(2.10 절) |

**`source_commit` 신선도 게이트는 허용 5 커밋입니다.** 이 세션에서 세 번 걸렸고,
갱신 자체가 커밋이라 병합이 잦은 날에는 반복해서 막힙니다. 착수 시 먼저 돌려
현재 지연을 확인하고, 병합을 여러 건 예정했다면 **마지막에 한 번 갱신**하십시오.
