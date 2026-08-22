# ORM 완결, P95 실측, 워커 감시 체계 인수인계 (2026-08-22)

> **작성일**: 2026-08-22 (Asia/Seoul)
> **작성자**: Claude 코디네이터
> **인수 대상**: 다음 코디네이터 세션
> **최종 갱신**: 2026-08-22 (Asia/Seoul)
> **병합 기준 main**: `1a45ad5`
> **Orca Run**: `run_72c57a5f44b3`
> **종료 상태**: 작업 완료, 원격 반영 완료, Docker 스택 종료

---

## 1. 이번 세션에서 닫은 것

| 과업 | 결과 | 근거 |
| --- | --- | --- |
| ORM `Mapped[]` 전환 | 4파일 13모델 137컬럼 전량 완료 | 전 테이블 메타데이터 지문 `60a9cf49…c51c8` 전후 일치 |
| GPT 지적 P1 (동시 쓰기 경쟁) | 프로세스 간 파일 잠금 + 반증 테스트 | 잠금 무력화 시 동시 8건 중 7건 유실 확인 |
| GPT 지적 P2 (머신 종속 경로) | `resolve_kimi_bin()` 로 교체 | 소스에 `/Users/` 리터럴 0건 |
| 블로킹 I/O 요청 경로 P95 | 6회차 실측, 근거 문서화 | `data/benchmarks/blocking_io_p95/run1~6.json` |
| 워커 기동 준비 자동화 | `orca_prepare_worktree.py` + 테스트 8건 | 실제 워크트리 `--check` 종료 코드 0/1 확인 |

전체 테스트는 병합 시점 기준 **1688 passed, 2 skipped**, mypy 89개 파일 통과,
규칙 검증 12/12 입니다.

---

## 2. P95 실측 결과와 해석 제약

| 항목 | 목표 | 실측 P95 | 판정 |
| --- | --- | --- | --- |
| SSE 첫 토큰 | 3초 | 1.26 ~ 2.29초 | 3회 전량 충족 |
| SSE 완료 | 20초 | 6.37 ~ 7.65초 | 3회 전량 충족 |
| 예측 API (동시 10) | 100ms | 웜 61.9 ~ 83.6ms | 웜 4회 충족, 콜드 미달 |
| 단발 질의 | 미정의 | 6.29 ~ 10.26초 | 판정 불가 |

**개선폭은 어디에도 쓰지 않았습니다.** `to_thread` 오프로드 이전의 동일 조건
실측이 없어 비교 대상이 없습니다. 다음 세션도 이 제약을 유지하십시오.

예측 API 는 3회차 시점에 `383 -> 122 -> 78.6` 으로 단조 감소 중이어서 수렴을
주장할 수 없었습니다. 4~6회차를 추가 측정해 `61.9 ~ 83.6ms` 대역의 재현을
확인한 뒤에야 판정했습니다. **회차를 버리지 않았고 콜드 회차를 제외한 계산은
쓰지 않았습니다.** 원시 JSON 6개를 모두 보존합니다.

상세는 [`../analysis/blocking_io_p95_20260822.md`](../analysis/blocking_io_p95_20260822.md).

---

## 3. 워커 감시에서 배운 것

이번 세션에서 워커가 멈추거나 잘못된 산출물을 낸 지점입니다. 다음 세션은
같은 함정을 반복하지 마십시오.

| 함정 | 조치 |
| --- | --- |
| 폴더 신뢰가 절대경로 단위라 새 워크트리마다 다이얼로그 | `scripts/orca_trust_worktree.py` 로 터미널 생성 전 사전 등록 |
| 파일 편집 승인은 별개 경로이며 터미널 세션 단위 | Dispatch 직후 `shift+tab`(`\x1b[Z`) 전송. 절차 5번 |
| 오버레이가 뜬 상태에서 지시를 보내면 코멘트 상자로 들어감 | 보내기 전에 `terminal read` 로 화면 확인 |
| 워커의 `succeeded` 와 "테스트 전부 통과" 를 믿을 수 없음 | 지시 반영 여부를 소스에서 직접 확인 |
| 코디네이터가 `main` 을 움직일 때마다 `source_commit` 지연 실패 | 코디네이터가 직접 갱신하고 워커는 리베이스 |

**P1 워커는 코디네이터 수정 지시 5건 중 4건을 무시하고 `succeeded` 를
보냈습니다.** 소스를 직접 확인해 반려했고, 두 번째 지시도 반영되지 않아
코디네이터가 직접 고쳤습니다. Windows 잠금 결함 2건이 여기에 포함되어 있어
그대로 병합했다면 G2 가 깨진 채 닫혔을 것입니다.

절차 정본은 [`../ops/agent_worker_launch_reference.md`](../ops/agent_worker_launch_reference.md)
2절과 2.1~2.2절입니다.

---

## 4. 정정된 사실

이전 가설 하나가 실측으로 반증되었습니다. **워크트리에 pre-commit 훅이 설치되지
않아 검증이 생략되었다는 설명은 틀렸습니다.** `git rev-parse --git-path hooks`
결과가 보여주듯 워크트리는 주 저장소의 `.git/hooks` 를 공유하며 훅은 정상
동작했습니다.

실제 원인은 **pre-commit 이 ruff, bandit, 규칙 검증만 돌리고 pytest 는 돌리지
않는 것**입니다. 테스트 실패는 커밋 시점에 걸리지 않고 Level 1 게이트 3 에서야
드러납니다. `orca_prepare_worktree.py` 는 준비 누락을 막을 뿐 이 구멍을 닫지
못합니다. 닫으려면 별도 판단이 필요합니다.

---

## 5. 다음 작업 순서

### 5.1 지금 착수 가능

| 순서 | 작업 | 조건 |
| :---: | --- | --- |
| 1 | 수집 2·3회차 관찰 | Docker 기동 (`make up`) |
| 2 | `CURRENT_STATE.md` 정리 | 없음. 8000/8000 포화 상태 |

`docs/context/CURRENT_STATE.md` 는 **정확히 예산 한계에 닿아 있습니다.** 다음
항목을 넣으려면 기존 문장을 줄여야 합니다. 종결된 0번(무료 워커 경합)과
4번(ORM 완료)을 4.1절 종결 계열로 옮겨 본문을 비우는 것이 맞습니다.

### 5.2 판단이 필요한 것

- **콜드스타트 미달**: 재기동 직후 예측 API P95 가 383ms 입니다. 기동 시
  모델·커넥션 워밍업을 넣을지, 아니면 콜드 구간을 목표 대상에서 제외할지
  결정해야 합니다. 전자를 택하면 효과를 재측정해야 합니다.
- **단발 질의 목표 미정의**: P95 6.29~10.26초입니다. 목표를 세울지, 이 경로를
  SSE 로 유도할지 판단이 필요합니다.
- **pytest 를 커밋 게이트에 넣을지**: 4장의 구멍입니다. 넣으면 커밋이 느려지고
  안 넣으면 Level 1 게이트까지 실패가 드러나지 않습니다.

### 5.3 차단됨

| 작업 | 차단 사유 |
| --- | --- |
| Ollama `OLLAMA_NUM_PARALLEL` 및 SSE c4 기준선 | 사용자 동석과 호스트 Ollama 재기동 승인 필요. 중간 결과는 판정 근거로 쓸 수 없으므로 완주 시간이 확보된 세션에서만 시작 |
| Windows Docker Desktop 실기 검증 | 실기 장비 부재. **컷오버를 막는 유일한 항목** |
| Arq 태스크 처리량 실측 | 큐 적재 경로 설계가 별도로 필요 |

---

## 6. 다음 세션 재개 절차

```bash
git status --short
git branch --show-current
git rev-parse HEAD origin/main
docker compose ps
```

Docker 가 필요하면 다음 순서로 재개합니다.

```bash
make up
docker compose ps
make migrate-check
```

워커를 띄운다면 절차는 다음과 같습니다. 3번과 5번을 빠뜨리면 워커가 멈춥니다.

```bash
orca worktree create --name <이름> --repo path:<주 저장소> --base-branch main --setup skip --json
uv run python scripts/orca_prepare_worktree.py <워크트리>
orca terminal create --worktree path:<워크트리> --command "agy --model gemini-3.7-flash-high" --json
orca orchestration dispatch --task <task_id> --to <handle> --inject --json
orca terminal send --terminal <handle> --text $'\x1b[Z'
```

---

## 7. 종료 전 확인 상태

| 항목 | 상태 |
| --- | --- |
| Git 브랜치 | `main` |
| Git 원격 동기화 | `HEAD == origin/main == cd2433e` (본 문서는 별도 병합·푸시) |
| 미커밋 변경 | 없음 |
| Orca Task | 5건 전부 `completed` |
| 활성 워크트리 | 없음. 5개 전부 제거 |
| 활성 워커 터미널 | 없음. 5개 전부 종료 |
| Docker 컨테이너 | 정상 종료 |
| Docker 볼륨·이미지 | 보존 |

미병합으로 남긴 브랜치가 하나 있습니다. `feat/p1-reliability-lock` 은 P1 워커의
최종본이며, 코디네이터 버전이 Windows 테스트를 건너뛰지 않아 그쪽을 채택했습니다.
내용이 대체되었으므로 삭제해도 무방하지만 규약상 `-D` 강제 삭제는 하지
않았습니다.

`docker compose down -v` 또는 볼륨 삭제 명령은 실행하지 마십시오. 데이터
볼륨과 이미지는 그대로 보존되어 있습니다.

---

## 8. Codex 코디네이터 인계 및 다음 작업 (2026-08-22 갱신)

코디네이터 기본값은 Codex `gpt-5.6-terra` + effort `medium`입니다. 변경 전에는
`MODEL_CHANGE_NOTICE`를 남깁니다. Gemini 워커 기본값은
`gemini-3.7-flash-medium`이며, 데이터 무손실 영향·복잡한 구현/회귀 분석·독립
교차 검토일 때만 `WORKER_MODEL_NOTICE`를 남기고 Flash High로 올립니다.
`gpt-5.6` 별칭과 Sol High는 기본값으로 쓰지 않습니다.

최신 운영 사실은 [`../context/CURRENT_STATE.md`](../context/CURRENT_STATE.md)가
정본이며, 이 문서는 그 상태로 재개하기 위한 실행 인수인계입니다. 2026-08-22
정식 게이트에서 예측 c10(P95 54.93ms, 100ms 초과 0/1,800)과 SSE c1(첫 토큰
P95 1297.73ms, 완료 P95 6716.22ms)은 통과했습니다. 반면 예측 c1·c2·c4는 기존
+10% 회귀 한도를 초과해 G3 전체 승격이 보류됐습니다. 상세 근거는
[`../analysis/blocking_io_gate_20260822.md`](../analysis/blocking_io_gate_20260822.md)와
원시 아티팩트 `data/benchmarks/latency_gate_20260822/`입니다.

### 8.1 착수 순서와 완료 기준

| 순서 | 작업 | 선행 조건 | 완료 기준 |
| :---: | --- | --- | --- |
| 1 | `orca_prepare_worktree` fail-closed | 없음 | 동일 Git common directory 검증 전에는 `.env`·trust·hook을 절대 변경하지 않음. 비Git 디렉터리·타 저장소 worktree 반증 테스트 추가 |
| 2 | `orca_trust_worktree` 동시성 안전화 | 1과 병렬 가능 | 두 설정 파일 전체 RMW 잠금, 고유 임시 파일, `trustedFolders.json` 최초 생성·부분 실패 원자성 테스트 추가 |
| 3 | ModelRegistry single-flight | 1·2와 병렬 가능 | startup warmup와 readiness 동시 시작에서 실제 모델 로드가 1회이고 부분 레지스트리를 노출하지 않음 |
| 4 | 병합 게이트 기계화 | 1~3 검증 완료 | Orca finalize strict PASS와 Level 1 성공 기록 없이는 merge helper가 병합하지 않음 |
| 5 | 성능 원시 메타데이터 통일 | 1~3과 병렬 가능 | prediction/SSE 결과에 Git SHA, 시각, Python, 플랫폼, Docker image ID, GC·계측 설정을 저장 |
| 6 | 이전 기준선과 현재 측정의 환경·이미지·요청 경로 대조 | 1~5 완료 | 차이 또는 동등성을 증거 경로·수치와 함께 기록 |
| 7 | `predict-price` 모델 호출·특징 생성 구간의 재현 원인 분석 | 6의 환경 동등성 확인 | 코드 변경 없이 원인 가설과 재현 조건을 좁힘 |
| 8 | 최적화 후보를 사용자에게 제안 | 6·7 완료 | 기대 효과·위험·G1 불변 조건을 포함한 승인안 |
| 9 | 승인된 최소 변경 구현과 c1/c2/c4/c10 재측정 | 사용자 승인 | 규약 표본·warmup·3회 최악값·주변 부하를 모두 충족 |
| 10 | `OLLAMA_NUM_PARALLEL` SSE c4 분석 | 9와 독립 | 호스트 재기동 승인 후 기준선 또는 기각 근거 확정 |
| 11 | Windows Docker Desktop 실기 검증 | Windows 장비 | G2 검증 결과 기록 |
| 12 | Arq 처리량·단발 RAG 반복 게이트 | 독립 | 경로별 측정 설계와 규약 충족 원시값 보존 |

1·2는 자동 워커 준비 도구 자체의 P1이므로 코디네이터가 먼저 순차로 수정·검증하고
병합합니다. 이 기간에는 해당 도구를 통한 병렬 쓰기 워커를 기동하지 않습니다. P1이
닫힌 뒤 3과 5는 최대 2개 쓰기 워커로 병렬 Dispatch할 수 있습니다. 4는 병합 경로를
바꾸므로 1~3의 검증 후 시작하며, 6 이후의 성능 분석은 1~5가 병합되어 재현 조건이
고정된 뒤에만 시작합니다.

### 8.1.1 검토로 확정한 보완 근거

| 항목 | 판정 | 재개 시 금지 사항 |
| --- | --- | --- |
| P1-1 `orca_prepare_worktree` | Git worktree 확인 전에 `.env`를 복사할 수 있음 | 대상 소속 검증 전 파일·사용자 설정 변경 금지 |
| P1-2 `orca_trust_worktree` | 잠금 없는 RMW와 고정 임시 파일, 최초 `trustedFolders.json` 처리 누락 | 병렬 워커 기동 금지 |
| P2-1 ModelRegistry | background warmup·readiness가 중복 로드 가능 | 단순 lock만으로 부분 레지스트리 노출 금지 |
| P2-2 merge gate | finalize는 있으나 일반 Git 병합을 기계적으로 막지 못함 | 사람 확인만으로 PASS를 대체하지 않음 |
| P2-3 raw metadata | SSE 기본 메타는 있으나 prediction 및 Docker·설정 식별자가 부족 | 문서 수치만으로 원시값 출처를 주장하지 않음 |

### 8.2 워커 Dispatch 계약

| Task | 역할·모델 | 읽기 범위 | 쓰기 범위 | 금지 사항 |
| --- | --- | --- | --- | --- |
| 기준선 동등성 대조 | Gemini Flash Medium investigator | 2026-08-14·2026-08-22 원시 측정, 규약, 벤치마크 스크립트 | 없음 | 재측정·설정 변경·기준선 갱신 |
| `predict-price` 경로 분석 | Gemini Flash Medium investigator | 예측 라우터·특징·예측기·진단 로그·관련 테스트 | 없음 | 코드 수정·모델/DB 변경·성능 통과 선언 |

각 워커는 `worker_done`에 확인한 파일, 비교표 또는 근거, 미확인 사항을 남겨야
합니다. 코디네이터는 `worker_done`과 실제 파일을 대조한 뒤에만 다음 Task를
시작합니다. 이전 Run `run_76b6d2cc4abb`의 두 메시지는
`Rejected worker_done`이므로 공식 완료 기록이 아니며, 새 Run·새 Task로 다시
등록해야 합니다.

### 8.3 재개 전 점검과 종료 규칙

```bash
git status --short
git branch --show-current
git rev-parse HEAD origin/main
docker compose ps
```

Docker가 필요한 측정은 `make up` 후 `make migrate-verify`를 먼저 수행하고,
정식 게이트 직전 `LATENCY_SEGMENT_LOGGING=false`와 `PREDICTION_GC_MODE=freeze`가
컨테이너에 실제 적용됐는지 확인합니다. 작업 종료 시 `make down`으로 컨테이너와
네트워크만 정리하며 Docker 볼륨·이미지는 삭제하지 않습니다.
