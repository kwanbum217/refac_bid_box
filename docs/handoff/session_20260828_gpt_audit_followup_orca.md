# 인수인계: 2026-08-28 GPT 재감사 후속 (Orca Run run_43d9937ac156)

> **작성일**: 2026-08-28
> **Run**: `run_43d9937ac156`
> **코디네이터**: Claude Opus 5
> **워커**: Antigravity `gemini-3.7-flash-high` 6대 (2차수 x 3대)
> **결과**: Task 6건 전부 병합. 전량 테스트 **2461 passed**, `validate_agent_rules.py` **12/12 PASS**
> **시작 HEAD**: `d9a0536` / **종료 HEAD**: `0c22474`

---

## 1. 이번 세션이 닫은 것

GPT 재감사가 남긴 5개 후속 중 **3개를 종결**하고 1개를 부분 진전시켰습니다.

| 감사 후속 | 상태 | 근거 |
| --- | --- | --- |
| 1. 현 HEAD blind fixture 재측정 | **완료** | [`blind_fixture_remeasure_20260828.md`](../analysis/blind_fixture_remeasure_20260828.md) |
| 2. 후보 풀 30 이후 RAG 레이턴시 재측정 | **부분** | 느린 4문항 전후 실측 완료. 전량 규약 측정은 미실시 |
| 3. `ORCA_WORKER_DONE_V2` 실행 게이트 승격 | **완료** | 보고 누락·위조 커밋·changed_files 불일치·조작된 verification 전부 FAIL |
| 4. 정확 제목 lexical 독립 채널 | **완료** | 구현·병합 후 실측으로 효과 확인 |
| 5. Windows Docker Desktop 실기 | **미착수** | 장비 부재. 코드로 닫을 수 없음 |
| (감사 9번) 실제 CPU utilization 계측 | **완료** | 외부 의존성 없이 macOS/Linux 양쪽 지원 |

---

## 2. 처리한 Task

| Task | 내용 | 브랜치 |
| --- | --- | --- |
| `task_ea688271d62b` | worker_done 진실성 검증(커밋·브랜치 실존, changed_files 대조) + 보고 누락 시 Level 1 FAIL | `t1-workerdone-gate` |
| `task_a2764ba98c7c` | 정확 제목 Meilisearch 어휘 독립 채널, 정규화 충돌 제거, 결정적 tie-breaker | `t2-lexical-channel` |
| `task_dda88e2e6fe3` | `Accept this file edit?` 등 Antigravity 대화창 탐지 | `t3-watch-dialog` |
| `task_57b62635a363` | RAG 구간 계측(sql/vector/lexical/llm/total), 노출 플래그 기본 False | `t4-rag-segments` |
| `task_ac1c2f9da231` | 실제 CPU utilization 계측을 벤치마크 리포트에 추가 | `t5-cpu-util` |
| `task_1049283686bf` | verification 배열 진실성 게이트(화이트리스트 재실행, 그 밖은 unverified 표기) | `t6-verif-truth` |

워크트리 6개, 워커 터미널 6개 전부 반납·종료했습니다. 남은 워크트리는 주 저장소 하나입니다.

---

## 3. 측정 결과 (오늘의 핵심)

### 3.1 현 HEAD 전량 재측정 (`d9a0536`, e2b, 32문항 x 3회)

| 지표 | 2026-08-27 | **현 HEAD** |
| --- | ---: | ---: |
| Numeric 정확도 | 87.5% | **95.7%** (67/70) |
| Evidence recall | 0.875 | **0.957** |
| Citation | 91.7% | **100.0%** |
| Refusal 정확 | 8/8 | **24/24** |
| 과잉응답 | 0 | **0** |
| 요청 실패 | - | **2/96** (q03 타임아웃) |

품질은 전 지표 개선입니다. 그러나 **긴 정확 공고명 질의가 58~180초**를 소모했고
q03 은 3회 중 2회 타임아웃했습니다.

### 3.2 lexical 채널 병합 후 (같은 4문항 x 3회)

| 지표 | 전 | 후 |
| --- | ---: | ---: |
| 요청 실패 | 2/12 | **0/12** |
| P50 | 58,352ms | **5,941ms** |
| 최대 | 180,045ms | **41,874ms** |
| numeric / evidence / refusal | - | **6/6 · 6/6 · 6/6** |

**타임아웃이 사라졌고 정확도 손실은 없습니다.** 후보 풀 30 을 장기 해법으로 두지
않는다는 방향이 실측으로 뒷받침됐습니다.

### 3.3 같은 조건 e4b 대조 (부분집합)

| 모델 | 품질 | P50 | 최대 |
| --- | :---: | ---: | ---: |
| **e2b** | numeric 6/6, evidence 6/6, refusal 6/6 | **5,941ms** | **41,874ms** |
| e4b | 동일 | 6,245ms | 81,234ms |

**e2b 승격 유지 근거가 최신 코드에서 보강**됐습니다.

### 3.4 측정의 한계 (다음 세션이 반드시 볼 것)

1. 3.2·3.3 은 **부분집합 12회 표본**입니다. 전량 32문항 x 3회 재측정으로 정본을
   갱신해야 합니다.
2. 측정 중 **워커 3대가 같은 기계에서 돌고 있었습니다.** 절대값에 부하가 섞여
   있으므로 상대 비교로만 읽으십시오.
3. q03 r1 이 여전히 41.9s 입니다. 이번에 들어간 구간 계측으로 원인을 분해해야 합니다.
4. 레이턴시 게이트 정본 판정은 `benchmark_rag_segments.py` 규약 측정이며 위 수치는
   그 대체물이 아닙니다.

---

## 4. 이번 세션의 코디네이터 실패와 그 조치

**워커가 권한 승인 대화창에서 반복해 멈췄고, 사용자가 먼저 지적했습니다.**
플레이북상 코디네이터 실패입니다.

원인은 두 층을 구분하지 못한 것입니다.

| 층 | 무엇을 막아 주는가 |
| --- | --- |
| `shift+tab` (accept-edits) | **파일 편집 대화창만** |
| `scripts/orca_auto_approve.py` | **셸 명령 승인 대화창** |

`shift+tab` 만 보내고 자동 승인 감시기를 띄우지 않아, `cat > file`, `mkdir`, `top`
같은 명령마다 워커가 멈췄습니다. 감시기는 이미 있었는데 **기동하지 않은 것이 문제**입니다.

조치로 `scripts/orca_taskctl.py dispatch --terminal` 이 Dispatch 직후 감시기를
자동으로 붙이도록 바꾸고(`start_auto_approve()`), 실패 시 경고를 출력하게 했습니다.
회귀 테스트 3건과 [`agent_worker_launch_reference.md`](../ops/agent_worker_launch_reference.md)
0.5 절 절차화를 함께 넣었습니다.

**터미널을 `terminal create` 로 직접 만들고 taskctl 을 거치지 않으면 감시기도 직접
띄워야 합니다.** 이번 6대가 그 경로였습니다.

---

## 5. 다음 착수 (우선순위)

| 순위 | 작업 | 비고 |
| --- | --- | --- |
| 1 | 전량 32문항 x 3회 재측정으로 RAG 정본 갱신 | 저장소 동결 + **다른 부하 없는 상태**에서. 3.4 참조 |
| 2 | 구간 계측으로 q03 잔여 41.9s 분해 | 이번에 들어간 sql/vector/lexical/llm 지표 사용 |
| 3 | `benchmark_rag_segments.py` 규약 레이턴시 재측정 | G3 판정 정본 |
| 4 | Servc 3,589 OOS 현 Champion 고정 평가 | 재학습 게이트 3,098 을 491 초과 |
| 5 | Windows Docker Desktop 실기 | 장비 확보 시 |

---

## 6. 미푸시 상태

`main` 이 `origin/main` 대비 크게 앞서 있습니다. 푸시는 담당자 확인 후 수행합니다.
