# 인수인계: 2026-08-30 GPT 감사 P0 시정과 조율 도구 정리

> **작성일**: 2026-08-30
> **Run**: `run_e8135591d19b`(P0 2건), `run_5ebd142b81d9`(Wave A 3건), `run_c5e4af9d9378`(Wave B 3건)
> **코디네이터**: Claude Opus 5
> **워커**: Antigravity `gemini-3.7-flash-high` 5대, `gemini-3.7-flash-medium` 2대
> **시작 HEAD**: `8684d64` / **종료 HEAD**: `852206d` (커밋 28건)
> **결과**: Task 8건 전부 병합. 전량 2,686 passed. RAG 정본 갱신, T7 판정 종료

---

## 1. 이번 세션이 닫은 것

GPT 감사 지적 사항 중 P0 4건과 P1 2건, 그리고 세션 중 새로 드러난 4건을 닫았습니다.

| GPT 항목 | Task | 결과 |
| --- | --- | --- |
| 1. canonical 판정 수정 | `task_ca9b69568ca4` | fixture sha256·limit·전량·3회·무실패 게이트 결박 |
| 2. 오분류 벤치마크 정리 | 동일 | `noncanonical/` 격리, 측정값 바이트 동일 |
| 3. 상세 쿼리 개선 | `task_971c2f56f882` | NOT EXISTS 전환 |
| 4. EXPLAIN + 실측 | 코디네이터 | 60초 미완료 -> **5.09ms** |
| 5. RAG v2 재측정 | 코디네이터 | `canonical=true`, 96/96 성공 |
| 6. T7 판정 | 코디네이터 | **회귀 없음. 종료** |
| 9. launcher/dispatch 통합 | `task_aaa3793b55f9` | 공통 준비 상태 기계 |
| 10. CLI identity 구조화 | 동일 | 기동 시 메타데이터 기록 우선 |
| 11. reject/revision lifecycle | `task_75eda04c0e78` | rework 명령 추가 |
| 신규: 채점 규약 결함 | `task_44eb5fa51a0c` | `retrieval_miss` 분리 + `summary` 블록 |
| 신규: 모델 배정 자동화 | `task_75eda04c0e78` | 라우터 결선 |
| 신규: 비명령 프롬프트 | `task_8512dbfc034b` | CLI 설문 자동 해제 |
| 신규: 감시 상시화 | `task_58593d56ea19` | `--watch` 모드 |

---

## 2. RAG 정본과 T7 판정 (가장 중요)

**정본이 갱신됐습니다.** `data/benchmarks/blind_fixture_v2_e2b_20260830.json`,
HEAD `6210ee1`, v2 32문항 x 3회, `canonical=true`, 요청 실패 0/96.

**T7 conditional vector bypass 는 품질 회귀가 없습니다. 판정을 종료했습니다.**

판정 근거는 지표가 아니라 **검색 결과의 동일성**입니다. T7 전후 두 측정에서 성공한
**공통 94개 요청의 `retrieved_evidence_ids` 가 순서까지 한 건도 다르지 않습니다.**
`d9a0536` 은 T7 병합(`07bc710`)의 조상이 아니고 현 HEAD 는 T7 을 포함하므로 유효한
대조입니다.

### 2.1 지표만 읽었다면 회귀로 오판했을 것입니다

원시 집계로는 citation 이 100% -> 97.2%, 과잉응답이 1 -> 3 으로 나빠져 보입니다.
전부 q21 한 문항이고, 실제로는 **환각이 정직한 거부로 바뀐 개선**입니다. 채점기를
고친 뒤 보정값은 citation 69/69(100%), 과잉응답 0 으로 T7 이전과 정확히 일치합니다.

**이 저장소의 채점 지표는 검색 실패 상황에서 환각을 보상하고 정직을 벌합니다.**
`summary` 블록의 보정값과 원시값을 함께 보십시오. 상세는
[`blind_fixture_v2_canonical_20260830.md`](../analysis/blind_fixture_v2_canonical_20260830.md).

---

## 3. 남은 작업 (다음 세션 착수 순서)

| 순서 | 작업 | 제약 | 근거 |
| --- | --- | --- | --- |
| **1** | q21 재순위 결함 수정 + 32문항 회귀 실측 | Ollama 단독 | 4.1 |
| **2** | `benchmark_rag_segments.py` 구간 레이턴시 정본 생성 | Ollama 단독 | GPT 7 |
| **3** | 느린 문항 q03·q08·q25·q31 cold/warm 분해 | Ollama 단독 | GPT 8 |
| **4** | Servc 3,589 OOS Champion 고정 평가 | 서빙 루트 점유 | GPT 12 |
| **5** | Windows Docker Desktop 실기 | **장비 부재로 보류** | GPT 13 |
| 마지막 | G3 cutover 최종 판정 | 위 전부 완료 후 | GPT 14 |

**1~4 는 전부 병렬 불가입니다.** Ollama 는 요청을 직렬화하고, 측정 중 병합은
canonical 게이트의 SHA 결박에 걸려 결과를 무효로 만듭니다. 워커를 띄우면 테스트
실행 부하가 레이턴시 표본을 오염시킵니다. 순차로 하십시오.

### 3.1 q21 재순위 결함 (다음 1순위, 수정 미적용)

원인이 규명됐고 수정안이 나와 있으나 **적용하지 않았습니다.**

`src/rag/vector_store.py:203` 의 `_rerank_by_exact_title` 이 **자연어 질의 전체
문자열과 공고명을 동치(`==`)로** 비교합니다. 질의는 "…동부지구)의 공고번호,
수요기관, … 알려줘" 이고 공고명은 "…동부지구)" 이므로 절대 일치하지 않습니다.
정확 일치 승격이 작동하지 않아 동명 공고 밀집군에서 `top_k=5` 절단선 밖으로
밀립니다.

기대 문서 `bid_10169448` 은 DB·ChromaDB·Meilisearch 모두에 정상 실재하며 벡터
후보 30건 중 **9위(거리 0.3161)** 로 후보 풀에도 있습니다. **색인 누락이 아니라
재순위 결함입니다.**

포함 관계(`in`) 기반 수정안이 제안됐습니다. 상세와 재현 명령은
[`q21_retrieval_miss_20260830.md`](../analysis/q21_retrieval_miss_20260830.md).

**수정만 하고 끝내지 마십시오.** 정확 일치 재순위의 동작을 바꾸는 변경이므로
다른 문항 회귀 위험이 있습니다. 수정과 32문항 정본 재측정을 한 Task 로 묶으십시오.

---

## 4. 워커 운용에서 확인한 것

### 4.1 워커 보고는 여전히 품질 보증이 아닙니다

**Task 8건 중 3건에서 반려가 필요했습니다.** 모두 워커가 "전량 통과" 를 보고하고
Level 1 게이트의 테스트·범위·린터를 통과한 뒤, **코디네이터가 diff 를 직접 읽어서**
나왔습니다.

| Task | 반려 사유 |
| --- | --- |
| A1 | `accept-edits` 판정이 화면 전체 검색이라 대화 본문 오염에 노출(이 Task 의 목적 자체를 무력화). 테스트 전용 분기를 프로덕션 코드에 생성. 화면 무변화 시 성공 반환 |
| A2 | `worker_done.json` 누락 |
| A1 | `worker_done.json` 누락 |

`worker_done.json` 누락이 반복됩니다. **Capsule 의 acceptance 최상단과 기동
고지문 양쪽에 명시하십시오.** Wave B 에서 그렇게 했더니 3건 모두 제출했습니다.

### 4.2 Antigravity `dispatch --inject` 는 동작하지 않습니다

터미널 5대, 시도 여러 회에서 **전부 `agent_prompt_blocked`** 로 실패했습니다.
신뢰 대화창이 없는 준비 완료 프롬프트에서도 실패하므로 대화창 탓이 아닙니다.

동작하는 경로는 이것뿐입니다.

```bash
orca terminal create --worktree path:<트리> --title "<이름>" --command "agy --model <id>"
orca terminal send --terminal <handle> --text "" --enter        # 신뢰 대화창 승인
orca orchestration dispatch --task <id> --to <handle> --run <run> --return-preamble --json
# preamble 에 Capsule 고지문을 붙여 terminal send --enter 로 전달
```

**여러 줄 지시문은 한 번에 제출되지 않는 경우가 있습니다.** 전달 후 화면을 읽어
워커가 실제로 처리를 시작했는지 확인하고, 아니면 Enter 를 한 번 더 보내십시오.

### 4.3 shift+tab 을 blind 로 보내지 마십시오

**코디네이터가 이것으로 워커 한 대를 plan 모드(편집 금지)에 빠뜨렸습니다.**
shift+tab 은 토글이 아니라 `normal -> accept-edits -> plan -> normal` 3단 순환입니다.

Antigravity 는 생성 중에 화면을 다시 그려서 `terminal read` 가 **상태줄 없이
200자 미만(스피너만)** 을 돌려주는 경우가 있습니다. 그 상태에서는 모드를 알 수
없으므로 키를 보내면 안 됩니다. `orca_taskctl` 은 이제 이 경우 `unknown` 으로
판정해 건너뛰지만, **사람이 손으로 보낼 때는 스스로 지켜야 합니다.**

편집 대화창이 떠 있을 때의 shift+tab 은 승인 동작이 우선하고 모드는 한 칸만
이동합니다. 한 번에 accept-edits 가 되지 않을 수 있으니 상태줄로 재확인하십시오.

### 4.4 감시는 이제 도구가 합니다

자작 셸 루프를 쓰지 마십시오.

```bash
uv run python scripts/orca_worker_watch.py --watch --interval 40 --max-iterations 90 --min-commits 1
```

차단 발견 시 즉시 종료 코드 1, 완료 조건 충족 시 0 입니다. **`--min-commits` 나
`--max-iterations` 를 반드시 주십시오.** 둘 다 없으면 무한 루프입니다.

이 도구가 이번 세션에서 CLI 설문 차단 3건과 편집 승인 대화창 1건을 잡았습니다.

### 4.5 모델 배정은 이제 기계가 정합니다

`taskctl dispatch` 가 `orca_model_router` 배정표를 실제로 씁니다. Intent 의
`role` 과 `risk` 로 정해지고 배정 근거가 출력에 남습니다.

```
[Dry-run] Reason:  라우터 자동 배정: gemini-3.7-flash-medium (role=builder, risk=medium, ...)
```

**2026-08-29 에 코디네이터가 medium 으로 선언한 Task 두 건에 flash-high 를
배정한 사고가 있었습니다.** dry-run 이 `DEFAULT_MODEL` 로 flash-high 를 출력했고
그 값을 그대로 옮겨 적었기 때문입니다. 이제 막힙니다.

---

## 5. 인프라에서 발견한 것

### 5.1 DB 가 기동 불능이었습니다

2026-08-30 측정을 시작하려 하니 `db` 컨테이너가 재시작을 반복하고 있었습니다.
2026-08-28 Docker 데몬 강제 종료가 남긴 소켓 lock 파일의 무효 PID 때문에 MySQL 이
기동을 거부했습니다.

```
[ERROR] [MY-010277] Invalid pid in unix socket lock file /var/run/mysqld/mysqld.sock.lock
```

`/var/run/mysqld` 는 볼륨이 아니라 컨테이너 로컬이므로 **데이터 볼륨을 건드리지
않고 db 컨테이너만 재생성**하면 해소됩니다.

```bash
docker compose up -d --force-recreate --no-deps db
```

`-v` 를 절대 붙이지 마십시오. 행 수는 공고 5,490,072 / 낙찰 3,423,008 로 무손실을
확인했습니다.

### 5.2 상세 페이지 쿼리가 그 부하의 정체였습니다

`EXPLAIN ANALYZE` 로 확정했습니다. 구 구현은 549만 행 풀스캔(23.75초) 후 전역
정렬을 하며 60초 상한 안에 **한 행도 반환하지 못했습니다.** 신 구현은 5.09ms 입니다.
`GET /api/v1/bids/{pk}` 는 P50 10.34ms, P95 47.98ms(120표본)입니다.

**추가 인덱스는 두지 않기로 판단했습니다.** 기존 인덱스 두 개만으로 5ms 대이므로
복합 인덱스는 쓰기 비용만 늘립니다. 상세는
[`detail_query_explain_20260830.md`](../analysis/detail_query_explain_20260830.md).

---

## 6. 세션 종료 상태

| 항목 | 상태 |
| --- | --- |
| 워크트리 | 전부 반납. 주 저장소만 남음 |
| 작업 브랜치 | 전부 병합 후 삭제 |
| 워커 터미널 | 전부 종료 |
| 원격 | `852206d` 까지 푸시 완료 |
| Docker | 세션 종료 시 내림 (Redis 는 `SHUTDOWN NOSAVE`) |

---

## 7. 다음 세션 첫 명령

```bash
# 1. 상태 확인
cat docs/context/CURRENT_STATE.md
docker compose up -d && docker compose ps

# 2. q21 재순위 수정 Task 등록 (3.1 절)
#    수정과 32문항 정본 재측정을 한 Task 로 묶을 것

# 3. 측정 전 반드시 확인
git status --porcelain   # 비어 있어야 함. 측정 중 병합 금지
```
