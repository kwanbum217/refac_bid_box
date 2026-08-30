# 인수인계: 2026-08-30 콜드 스타트 SQL 규명과 워커 도구 정비

> **작성일**: 2026-08-30
> **다음 코디네이터**: Codex `gpt-5.6-sol` effort `medium`
> **Run**: `run_ff539c1cf332`(Wave D 3건 완료), `run_8af9dd5d2783`(Wave E 3건 진행 중)
> **이전 인수인계**: [`session_20260830_wave_c_and_serial_measurement.md`](session_20260830_wave_c_and_serial_measurement.md)
> **결과**: G3 컷오버를 막는 신규 결함 1건 규명, 워커 승인 대기 원인 3건 제거

---

## 0. 다음 세션 첫 명령

```bash
cat docs/context/CURRENT_STATE.md
docker compose up -d && docker compose ps
git status --porcelain      # 측정 전 반드시 비어 있어야 함
orca status                 # runtime ready 확인
```

**미완 작업이 워크트리에 남아 있습니다. 1장을 먼저 읽으십시오.**

---

## 1. 이어받아야 할 미완 작업

| 대상 | 위치 | 상태 | 다음 행동 |
| --- | --- | --- | --- |
| **E1** probe 제거 + 공고 힌트 | 워크트리 `orca-e1-probe`, 브랜치 `kwanbum217/orca-e1-probe` | 표준 `finalize --reviewer` **pass**, `a53b01a` | 병합 후 워커·워크트리 회수 |
| **E3** 콜드SQL 귀속 하네스 | 워크트리 `orca-e3-harness`, 브랜치 `kwanbum217/orca-e3-harness` | canonical 재작업 포함 표준 최종화 **pass**, `7ec1d23` | 병합 후 워커·워크트리 회수 |
| **E2** `contains()` 전수 조사 | 워크트리 `orca-e2-contains`, 브랜치 `kwanbum217/orca-e2-contains` | 표준 `finalize --reviewer` **pass**, `500e70a` | 병합 후 워커·워크트리 회수. 결론은 2.5 절 |

E1 과 E3 의 Level 2 리뷰 보고는 `/tmp/e1_review.json`, `/tmp/e3_review.json` 에 있으나
**임시 디렉터리이므로 사라졌을 수 있습니다.** 없으면 리뷰어를 다시 돌리십시오.

2026-08-30 인수 후 세 Task 모두 `scripts/orca_taskctl.py finalize --reviewer`로 다시
검증했습니다. E1은 2,821건, E3는 2,829건의 전체 테스트를 통과했고 E2는 문서 전용
게이트와 독립 Reviewer를 통과했습니다. E3는 캐시 비움 요청과 실제 성공을 canonical
판정에 결박하는 재작업까지 포함합니다.

표준 최종화 과정에서 바깥 `summarize` 30초와 Level 1 120초 상한이 내부 pytest 900초
계약보다 짧아 JSON 출력 전에 종료되는 결함을 확인했습니다. `scripts/orca_taskctl.py`의
두 바깥 상한을 내부 게이트 합계보다 길게 맞추고 회귀 테스트를 추가했습니다.

```bash
python3 scripts/orca_level1_gate.py --base main --branch kwanbum217/orca-e1-probe \
  --repo ~/orca/workspaces/refac_bid_box/orca-e1-probe \
  --tests 'tests/test_structured_data_cache.py -q' \
  --capsule .orca/capsules/task_4a485df361bd/capsule.yaml --json
```

**`--tests` 는 전체 명령이 아니라 pytest 인자만 받습니다**(`orca_level1_gate.py:624`).
`uv run pytest ...` 를 통째로 넘기면 오탐 실패합니다.

---

## 2. 가장 중요한 발견: RAG 정형 질의가 콜드 스타트에 97초 (미해결)

**G3 컷오버를 막는 항목입니다.** 상세는
[`rag_structured_sql_coldstart_20260830.md`](../analysis/rag_structured_sql_coldstart_20260830.md).

### 2.1 기전

```
질의에 날짜 필터("2026년") 또는 기관명이 붙음
  -> _snapshot_scope() 가 None 반환, 사전 집계 스냅샷 포기
  -> 실시간 집계로 넘어감
  -> Redis 캐시 조회 (AGGREGATE_CACHE_TTL = 3,600초)
       hit  -> 7ms
       miss -> 46,579 ~ 97,088ms
```

**같은 질의가 캐시 상태에 따라 최대 10,900배 차이가 납니다.**
`AGGREGATE_CACHE_TTL` 이 만료될 때마다 다음 사용자 한 명이 그 비용을 부담합니다.

### 2.2 비용 귀속 (performance_schema 실측)

| 순위 | 쿼리 | 누적 | 최대 |
| :---: | --- | ---: | ---: |
| 1 | `COUNT(bid_announcements.id) WHERE dminstt_nm LIKE concat('%',?,'%')` | 89.09s | 15,539ms |
| 2 | `bidwinnr_nm GROUP BY` | 78.41s | 23,030ms |
| 3 | `dminstt_nm GROUP BY` | 72.09s | 13,160ms |
| 4 | `bid_ntce_nm GROUP BY` | 69.92s | 12,648ms |
| 5~8 | `bid_announcements.id WHERE ... LIKE concat('%',?,'%')` | 67s, 67s, 46s | 27,668ms |

**지배 패턴은 선행 와일드카드 `LIKE '%...%'` 입니다.** 어떤 인덱스도 쓸 수 없어
항상 2,179,319행을 훑습니다. SQLAlchemy 의 `.contains()` 가 이 형태로 컴파일됩니다.

### 2.3 지금까지 닫은 것

| 항목 | 상태 | 효과 |
| --- | --- | --- |
| `bidwinnr_nm GROUP BY` 날짜 인덱스 힌트 | **병합 `3c27ed3`** | 13,446ms -> 698ms (19.3배), 반환 15행 동일 |
| `corrupted_probe` 제거 + 공고 GROUP BY 힌트 | **E1, 미병합** | 최대 27.6초 스캔 3회 제거 |
| `contains()` 대체 경로 설계 | **E2, 진행 중** | - |

### 2.4 남은 것

1. E1 병합 후 **캐시를 비우고 재측정**해 실제 개선폭 확정
2. E2 조사 결과로 `contains()` 대체 여부 판정
3. `_snapshot_scope` 가 날짜 필터에서 스냅샷을 포기하는 설계 자체를 재검토

### 2.5 E2 조사 결론: 접두 일치 전환은 기각, Meilisearch 위임은 즉시 가능

상세 산출물은 E2 브랜치의 `docs/analysis/contains_scan_survey_20260830.md`입니다.
`.contains()` 호출 13건을 4개 파일 7개 그룹으로 분류하고 DB 실측으로 판정했습니다.

| 그룹 | 판정 | 근거 |
| --- | --- | --- |
| G1 RAG 기관명 | **대체 불가** | 접두 전환 시 "거제시" 입력이 10,148 + 3,742건에서 36 + 36건으로 **99.6% 손실** |
| G5·G6 자유 검색 q | **부분 대체 가능 (최우선)** | `_meili_enabled()` 분기가 이미 있어 `MEILI_ENABLED=true` 만으로 풀스캔 우회 |
| 손상값 probe 3건 | **중복 비용** | 질의당 약 27초. `bid_ranking_snapshots.rank=0` 이 같은 정보를 이미 관리 |

**접두 일치로의 단순 전환을 제안하지 마십시오.** 사용자는 기관명을 부분 토큰으로
입력하며(예: "경상남도 거제시" 대신 "거제시"), 접두 전환은 그 대부분을 잃습니다.

**G5·G6 는 코드 변경 없이 설정만으로 해소됩니다.** 다만 Meilisearch 가 비정상일 때
폴백이 같은 풀스캔이므로 **fail-closed 운영이 전제**입니다. 이것을 먼저 확인하십시오.

손상값 probe 중복 비용은 E1 이 이미 스냅샷 마커 재사용으로 닫았습니다(미병합).

---

## 3. 반복해서 저지른 판정 오류 두 가지

### 3.1 실제 소비자를 확인하지 않고 후보를 골라 고쳤습니다

`EXPLAIN` 결과가 나쁜 쿼리 하나를 주 원인으로 지목해 고쳤는데, 나중에
`performance_schema` 로 보니 비용이 8개 이상에 퍼져 있었고 **시정한 것은 전체의 약
15%** 였습니다.

**반드시 `performance_schema.events_statements_summary_by_digest` 로 귀속시킨 뒤
고치십시오.** E3 가 그 절차를 하네스로 만들었습니다
(`scripts/measure_coldsql_attribution.py`, 미병합).

### 3.2 캐시 상태를 밝히지 않은 수치는 의미가 없습니다

같은 코드가 캐시 상태에 따라 10,900배 다른 값을 냅니다. 이 때문에 다음 판정 두 건을
철회했습니다.

| 철회한 판정 | 실제 |
| --- | --- |
| "q25, q31 은 최적화 대상이 아니다" | cold 에서 61.8초, 46.6초 |
| "느린 문항의 지배 요인은 벡터 콜드 미스" | 지배 요인은 SQL |

**코드 주석 두 곳이 같은 함정에 빠져 있었습니다.** `structured_data.py` 의
"매번 2초"(실측 46~97초)와 "첫 건에서 멈추므로 전체 스캔이 되지 않습니다"(손상 행이
없으면 전체를 훑음)입니다. 둘 다 E1 에서 정정했습니다.

---

## 4. 워커 승인 대기 원인 제거 (병합 완료)

한 세션에서 승인 대기가 여덟 차례 넘게 발생했고 여러 번을 사용자가 먼저 발견했습니다.
`scripts/orca_auto_approve.py` 를 고쳐 원인을 닫았습니다.

| 원인 | 조치 |
| --- | --- |
| 셸 메타문자 일괄 보류 | 파이프라인 구간별 판정. 모든 구간이 승인일 때만 승인 |
| `python` 실행 보류 | 셸 탈출 토큰(`os.system`, `subprocess`, `eval` 등) 없을 때만 승인 |
| 히어독 보고서 쓰기 보류 | 따옴표 구분자(`<<'EOF'`)만 허용. 쓰기 대상 경로 검증 |

**함께 발견한 기존 결함**: `cat` 이 안전 목록에 있어 `cat .env` 가 승인되고 있었습니다.
인자에 비밀 파일이 있으면 보류하도록 고쳤습니다.

**기존 테스트가 제 실수를 잡았습니다.** 개행과 캐리지 리턴을 구분자에서 빠뜨려
`git diff\recho x` 가 승인됐습니다. 구분자에 반드시 포함해야 합니다.

상세는 [`orca_do_not_repeat.md`](../ops/orca_do_not_repeat.md) 22장.

---

## 5. 그 밖에 기계로 못박은 것

| 항목 | 내용 | 근거 |
| --- | --- | --- |
| kimi 런처 모델 검증 | 기동 전 대상 프로필 `config.toml` 확인. 없으면 사용 가능 목록과 함께 즉시 중단 | 23장 |
| `CURRENT_STATE` 신선도 | 기준을 `HEAD` 에서 `HEAD`·`main` 공통 조상으로 변경 | 24장 |
| Capsule 템플릿 | acceptance 최상단에 반복 위반 3건 고정 | 21, 22장 |

**24장이 특히 중요합니다.** 종전 기준으로는 워커가 커밋을 낼수록 문서가 낡은 것으로
오판되어, 한 세션에서 갱신을 네 번 반복했고 두 번은 **어떤 값으로도 수렴하지
않았습니다.** 그 때문에 실질 게이트를 전부 통과한 Task 두 건을 게이트 실패 상태로
병합해야 했습니다.

---

## 6. 워커 배정에서 확인한 것

| 풀 | 상태 |
| --- | --- |
| Antigravity Gemini | 주력. **기본값은 `flash-medium`**. `flash-high` 는 high 위험도에만 쓰고 `WORKER_MODEL_NOTICE` 필수 |
| Antigravity Claude | **5시간 한도가 병목.** 워커 1대 + 리뷰어 2건으로 18%까지 떨어짐 |
| kimi `or-free/minimax-m3` | **사용 가능 확인.** 3회 정상 응답. 읽기 전용 조사에 배정 |
| cursor | **사용 불가.** named model 이 요금제로 차단됨(`Free plans can only use Auto`) |

**`flash-high` 배정 시 `WORKER_MODEL_NOTICE` 를 빠뜨린 사례가 이번 세션에 두 번
있었습니다**(D3, E1). E1 은 medium 으로 되돌렸습니다. AGENTS.md 5장을 지키십시오.

---

## 7. 세션 종료 상태

| 항목 | 상태 |
| --- | --- |
| main HEAD | 본 문서 병합 시점 |
| 전량 테스트 | 2,812 passed (E1·E3 미병합 상태 기준) |
| 규칙 검증 | 12/12 통과 |
| 워크트리 | **3개 남음** (`orca-e1-probe`, `orca-e2-contains`, `orca-e3-harness`) |
| 작업 브랜치 | **3개 남음** (위 워크트리에 대응) |
| Docker | 기동 중 |
| `.env` | `LATENCY_SEGMENT_LOGGING` 원복(`false`) |

---

## 8. 다음 세션 우선순위

| 순서 | 작업 | 근거 |
| --- | --- | --- |
| **1** | E1·E2·E3 병합 후 워커·워크트리 반납 | 1장 |
| **2** | 콜드 SQL 정본 측정의 revision 동결 | 2.4 |
| **3** | 캐시 비우고 콜드 SQL 재측정으로 개선폭 확정 | 2.4 |
| **4** | `MEILI_ENABLED=true` 전환 검토 (fail-closed 확인 선행) | 2.5 |
| 5 | Windows Docker Desktop 실기 | **장비 부재로 보류** |
| 마지막 | G3 cutover 최종 판정 | 2장이 닫힌 뒤 |

**측정은 여전히 직렬입니다.** Ollama 가 요청을 직렬화하고, 측정 중 병합은 canonical
게이트의 SHA 결박에 걸립니다. 저장소를 동결하고 진행하십시오.
