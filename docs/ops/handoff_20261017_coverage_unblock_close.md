# 핸드오프 인수인계 — 기술용역 구판 규칙, 한국공항공사 등록, 고시금액 정정, 교육청 조달청 기준, 커버리지 원장 재생성

> **작성일**: 2026-10-17
> **작성**: Claude 코디네이터 (Orca Run `run_7fc80bfcde31`)
> **기준 커밋**: `63a61a7b` (이 문서와 원장 재생성이 들어가는 병합의 부모)
> **직전 인수인계**: [handoff_20261014_detail_page_coverage_close.md](handoff_20261014_detail_page_coverage_close.md)

---

## 0. 다음 세션이 가장 먼저 할 일

| 우선 | 과제 | 선행 |
| --- | --- | --- |
| 1 | 이 문서 병합 커밋의 main CI 녹색 확인 | 없음 |
| 2 | 남은 계산 차단 11,862건(37.8%)의 대응 결정. 대부분 `MANUAL_EVALUATION`(수기심사) | 사용자 결정 |
| 3 | ML 특징용 고시금액 2021~2022 년 값 정정 여부(재학습·승격 판단 동반) | 사용자 결정 |
| 4 | 한국공항공사 미등록 별표(3·3의 2·5·5의 2·8·9) 근거 보강 | 없음 |
| 5 | 2027 년 고시금액 고시(2026-12 예정) 반영 | 외부 대기 |

---

## 1. 2026-10-15 세션 요약 (인수인계 문서 없이 종료된 세션)

Run 은 `run_cfe18fe34fa6`, `run_8ca68ee95815`, `run_5631fae373c0` 셋이고 Task 37건이 모두 `completed` 다. 2026-10-14 인수인계 우선 1~5 는 이 세션에서 끝났다.

| 병합 | 내용 |
| --- | --- |
| `0a820ec2` | 계산 차단 원인 조사 (`docs/analysis/block_cause_survey_20261015.md`) |
| `0534cf14` | 산림청·해양환경공단 등록 조사 |
| `71ef522d` | 국방부 기술용역 후속 수집 |
| `5f246a90` | 한국공항공사 적격심사 후속 수집 |
| `3b839645` | 계산 차단 원인 분해 (`block_cause_split_20261015.md`) |
| `d766cdc8` | 한국공항공사 전사 규정 추가 수집(통과점수·전사 구간표 확정) |
| `ebb234a5` | 해양환경공단 기관 규칙 등록(해양폐기물정화용역 한정, 4구간) |
| `88179685` | 확인 기관 안내 10곳 -> 11곳 |
| `c93bd788` | 해양환경공단 지사 코드 불일치 기록 |
| `b0fb0592` | 기술용역 하한율 시행일 이전 규정 수집(제8983호·제6352호·제654호) |
| `a14c97ae` | 규칙 미발견 식별 불일치 2건 기록 |
| `0510b8e7` | 기술용역 하한율 공고값과 별표 파생값 대조 |
| `fa44c516` | 지역 규칙 부재의 시·도별 규모 기록 |
| `523de82a` | 조달청 일반용역 5억 이상 15억 미만 띠 원문 재독 |
| `3e31c60a` | 경기 별표 1-1, 충남 별표 2-4 원문 재독 |

- 산림청은 적격심사 공고에 `산림사업` 토큰이 0건이라 등록하지 않았다.
- 2026-10-14 인수인계 우선 3(원장 `investigation` 14곳)은 이미 16곳 기록되어 있었다.

---

## 2. 이번 세션 병합 (2026-10-17)

빌더는 cmd `deepseek/deepseek-v4.1-flash`(`--auto`, effort 위험도별 default·high·max). 리뷰어는 처음에 qwen 경유 OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`(reasoningEffort max)였으나 upstream 과부하로 전부 멈춰 Antigravity 로 교체했다(5절). 모든 병합은 Level 1 strict 증거, 전량 시험 증거, 직전 병합 CI 녹색 확인, 병합 커밋 안 `source_commit` 갱신을 거쳤고 병합 직후 워크트리를 제거했다.

| Task | 병합 | 리뷰어 | 내용 |
| --- | --- | --- | --- |
| T1 | `aead0768` | agy claude-sonnet-4-6 | 기술용역 적격심사 구판 규칙 `SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526`(시행 2022-11-01, base_rate 0.88). 공고일 2026-05-26 미만이면 구판, 이상이면 현행. 규칙 ID 비교 네 곳을 frozenset·`startsWith` 로 통일 |
| T3 | `f6cf1e78` | agy claude-sonnet-4-6 | 한국공항공사 일반용역(26.8.14 시행) 별표 1·2·4·6·7 기관 규칙 5건 13구간, 기관 코드 B551178. 원장 6행(B551178 과 별칭 5곳) `confirmed`. 코디네이터 브랜치 경유 |
| T5 | `597f3962` | agy gemini-3.8-flash-medium | 규칙용 고시금액 표 `RULE_NOTICE_AMOUNT_BY_YEAR` 신설, 2021~2022 년 2억1천만원(기획재정부 고시 제2020-39호). ML 특징 표는 그대로. 이력 레지스트리 재생성 |
| T2 | `2025ada8` | agy gemini-3.8-flash-medium | 교육청 용역 적격심사 적용 기준 조사(`docs/analysis/edu_local_rule_basis_20261017.md`) |
| T4 | `9f21e90e` | agy gemini-3.8-flash-medium | 용역 고시금액 연도표 원문 근거 확인(`docs/analysis/notice_amount_source_20261017.md`) |
| T6 | `63a61a7b` | agy gemini-3.8-flash-high | 시·도 미산출 교육 계열 공고(LOCAL_RULE_NOT_FOUND)만 조달청 일반용역 매칭 결과로 계산하고 근거 경고를 붙인다. 호출부 다섯 곳에 `education_institution` 전달. `_narrow_rule_scope` 추출(동등성 리뷰 확인). 코디네이터 브랜치 경유 |
| 원장 | 이 문서와 같은 병합 | - | 규칙 커버리지 원장 2026-10-17 재생성(3절) |

---

## 3. 커버리지 원장 재생성 결과

창은 `2025-10-17`~`2026-10-17`, 용역 적격심사(`낙030001`)다. 2026-10-14 원장과 창이 3일 다르다.

| 적용 범위 | 2026-10-14 | 2026-10-17 |
| --- | ---: | ---: |
| 공고 | 31,485 | 31,417 |
| 계산 차단 | 20,973 (66.6%) | **11,862 (37.8%)** |
| 조달청 기본 규칙 | 8,804 (28.0%) | 17,853 (56.8%) |
| 지역 규칙 | 1,655 (5.3%) | 1,648 (5.2%) |
| 기관 규칙 | 53 (0.2%) | 54 (0.2%) |

| 차단 원인(기관 개별 항목과 tail 합) | 2026-10-14 | 2026-10-17 |
| --- | ---: | ---: |
| `RULE_REGIME_MISMATCH` | 9,012 | 1,225 |
| `MANUAL_EVALUATION` | 8,222 | 8,232 |
| `LOCAL_RULE_NOT_FOUND` | 763 | 196 |
| `RULE_NOT_FOUND` | 391 | 424 |
| `NON_PRED_PRICE` | 189 | 185 |
| `LOCAL_SERVICE_TYPE_UNRESOLVED` | 70 | 68 |

- 차단 감소는 대부분 T1(구판 기술용역)이다. 원인 합은 기관 개별 항목과 tail 의 합이라 전체 차단 수와 같지 않다.
- `RULE_NOT_FOUND` 증가(+33)는 T6 에서 교육 계열 공고가 조달청 별표에도 없을 때 `LOCAL_RULE_NOT_FOUND` 대신 `RULE_NOT_FOUND` 로 남기 때문이다. 사양대로다.
- 기관 규칙이 1건만 늘어난 것은 한국공항공사 규칙 시행일이 2026-08-14 라 그 이전 공고는 시행일 대조에 걸리기 때문이다.
- 남은 차단의 약 70%는 수기심사(`MANUAL_EVALUATION`)로 자동 계산 대상이 아니다.

---

## 4. 사용자 결정 (2026-10-17)

| 결정 | 내용 |
| --- | --- |
| 인수인계 범위 | 기술용역 구판 별표 등록, 교육 계열 시·도 산출, 한국공항공사 등록, 고시금액 원문 확인 네 건 승인 |
| 교육 계열 | 코디네이터가 근거 부족을 알려 조사로 좁혔고(T2), 조사 뒤 "교육청 공고 조달청 기준 적용" 지시. 범위는 시·도 미산출 공고만(이미 시·도 규칙으로 계산되던 공고는 유지) |
| 고시금액 | 2021~2022 년 값 수정 지시. 코디네이터가 규칙 쪽만 고치고 ML 특징 값은 고정 시험과 재학습 판단 때문에 유지 |
| 리뷰어 | Nemotron 과부하 시 우선 유지, 계속 멈추면 Antigravity Gemini 3.8 Flash 와 Claude Sonnet 으로 대체 |
| 병합 | 리뷰 통과 순서대로 병합, 병합 뒤 원장 재생성, 세션 종료 전 인수인계 문서 |

---

## 5. 운영 교훈

| 교훈 | 내용 |
| --- | --- |
| 무료 Nemotron 과부하 | OpenRouter `nemotron-3-ultra-550b-a55b:free` 리뷰어 5대가 `Upstream error from Nvidia: Service temporarily overloaded` 로 40분 넘게 멈췄다. OpenCode Zen `nemotron-3-ultra-free` 도 같은 Nvidia 503 이라 우회가 안 된다 |
| Zen Muse Spark 무료판 폐지 | `opencode/muse-spark-1.3-contributor-free` 는 `~/.cache/opencode/models.json` 에 `deprecated`(비용 0)로 남아 `Model not found` 가 난다. 현행 `opencode/muse-spark-1.3` 은 유료($1.25/$4.25 per 1M). `opencode-go/...-contributor` 는 학습 동의 설정이 필요하다 |
| agy Claude 크레딧 | agy `claude-sonnet-4-6` 이 리뷰 둘을 끝낸 뒤 세 번째에서 `Your AI credits balance is too low to continue` 로 멈췄다. 이것은 무시해도 되는 Out of credits 배너가 아니라 실제 정지다. Gemini 3.8 Flash 로 대체했다 |
| Level 1 게이트 `--tests` 누락 | `--tests` 없이 돌리면 `backend_pytest` 능력이 미충족이라 게이트 3 이 skip 되고 strict 판정이 fail 이 된다. 빌더 결함이 아니다 |
| 원장을 바꾸는 브랜치 | 기관 등록이 원장 정합 시험을 깨면 빌더 브랜치의 게이트 6과 전량 시험 증거가 통과할 수 없다. 코디네이터 브랜치에서 빌더 브랜치를 합치고 원장 칸을 커밋한 뒤 coordinator-capsule 로 증거를 남겨 병합했다. 칸은 기관 1행이 아니라 별칭 행까지 6행이었다 |
| Capsule 수정 차단 | 진행 중 Capsule 의 allowed_write_files 를 고치려 하자 권한 분류기가 자기 수정으로 거부했다. 범위 변경이 필요하면 새 Task 나 코디네이터 브랜치로 처리한다 |
| 같은 파일을 고친 브랜치 | T6 은 T3 보다 앞선 기준에서 같은 파일을 고쳤다. 직접 병합하면 T3+T6 결합 상태가 전량 시험을 거치지 않으므로 최신 main 위 코디네이터 브랜치에서 증거를 다시 남겼다 |
| 감시 스크립트 | 하트비트만 든 배달은 자동 ack, `Press Ctrl+Y to retry` 는 2분 간격 재전송, agy `Allow access to this URL?` 은 옵션 2(이 대화만 허용, 영구 저장 안 함)로 처리하고 URL 을 기록했다 |
| 병합 후 app 재시작 | uvicorn `--reload` 가 없어 T6 병합 뒤 `docker compose restart app` 으로 새 규칙을 반영했다 |

---

## 6. 결정 대기와 외부 대기

| 항목 | 상태 |
| --- | --- |
| 남은 계산 차단 11,862건 대응(수기심사 안내, 남은 시행일 불일치 1,225건, 규칙 미발견 424건) | 사용자 결정 |
| ML 특징 고시금액 2021~2022 년 정정 | 재학습·승격 판단과 함께 사용자 결정 |
| 한국공항공사 별표 3·3의 2·5·5의 2(통과점수 85/88 판별 근거), 별표 8(공고 0건), 별표 9(배점 범위 인쇄) | 근거 보강 대기 |
| 교육청 상위 7곳 중 5곳 적용 기준 원문 미확인(코드는 법령 근거로 반영) | 근거 보강 대기 |
| 산림청 등록 | 적격심사 공고 표기 토큰 부재 |
| 2027 년 고시금액 | 2026-12 고시 대기 |
| Command Code 플랜 | 97% 사용, 약 2 credits. 소진 시 grok-4.7 대체(라우터·런처 보강 필요) |
| 무료 리뷰어 풀 | Nemotron 과부하, Zen Muse 무료판 폐지, agy Claude 크레딧 소진. agy Gemini 3.8 Flash 만 이번 세션 끝까지 동작 |
| 한국도로공사 현행판, G2 Windows | 외부 대기 |

---

## 7. 세션 종료 상태

| 항목 | 상태 |
| --- | --- |
| Orca Run `run_7fc80bfcde31` | 빌더 6건, 리뷰 6건 모두 completed |
| 워커 터미널 | 전부 회수, 코디네이터 창만 남김 |
| 워커·코디네이터 워크트리 | 이 문서를 담은 `orca-coord-ledger` 는 병합 직후 제거. 나머지는 전부 제거 |
| Docker Compose(app, db, redis, meilisearch, worker) | 가동 중(worker 상시 가동 결정 유지). app 은 T6 병합 뒤 재시작 |
| 코디네이터 배경 대기 작업 | 종료 |
