# 세션 인수인계: 2026-09-15 외부 감사 보고서 검증과 보완 과업 병렬 처리

> **작성일**: 2026-09-15
> **작성자**: Claude Opus 5 (Orca 코디네이터)
> **기준 커밋**: `3044a967` (`main`, 후반부·al1 반영)
> **이어받은 문서**: [`docs/handoff/session_20260914e_remaining_tasks_parallel.md`](session_20260914e_remaining_tasks_parallel.md)

---

## 1. 한 줄 요약

Grok 이 작성한 보완점·미비점 보고서(2026-09-14, 기준 `20d94c6b`)를 코드와 대조해 대부분 사실로 확인했고, 사용자 결정 없이 고칠 수 있는 항목과 인수인계 잔여 RAG 과업을 Orca 워커 7건으로 병렬 처리해 모두 병합했습니다.

---

## 2. 외부 감사 보고서 검증 결과

| 판정 | 항목 |
| --- | --- |
| 사실 | 결제·비밀번호 찾기·소셜 로그인 부재, LICENSE 부재와 약관 자리표시자, G2 실기 미검증, 운영 compose 에 Ollama 없음, Release 실행 0회, 공사 전용 모델 미승격, 운영 야간 번들·주간 재학습 기본 꺼짐, Thng drift baseline 없음, 백업이 앱 공용 DB 계정 사용, 회원가입 요청 제한 없음, Redis 장애 시 요청 제한 통과, Caddy 보안 헤더 없음, chromadb CVE 예외 2026-12-31 만료, TTFT 알람 Slack 미발송, backup 헬스체크 없음, 영문 UI 문구, 설계 문서·CI 계약 문서 불일치 |
| 보고서보다 심각 | 예측 API 는 인증뿐 아니라 익명 쿼터도 없었음. backup 워커가 일반 worker 와 같은 하트비트 키를 갱신해 worker 가 죽어도 헬스체크가 통과할 수 있었음 |
| 이미 해소 | Meilisearch 전체 재색인과 `lic=0036` 실화면은 `96638db5` 에서 완료 |
| 맥락 보정 | `READINESS_REQUIRE_LLM=false` 는 Ollama 장애 시 Caddy 미기동을 막으려는 의도된 설정. 과잉거절 4건은 프롬프트가 아니라 질의 계획 문제 |

---

## 3. 병합 내역 (Run `run_75d816606872`)

| Task | 병합 | 내용 | 검증 |
| --- | --- | --- | --- |
| ah2 `task_acabc0e9f439` | `50b97e57` | 영문 UI 문구 한국어화, 기술용역 적격심사 설계 문서 갱신, HTMX 계획서 폐기 안내, `ci_contract.md` 6 Job·E2E 32건, README 확정 스택 표 | 게이트 통과, 리뷰 결함 0, 전량 4,886, CI 성공 |
| ah1 `task_d20aa68a9302` | `1faf9e76` | RAG `SYSTEM_PROMPT` 에 사용자 입력 속 Source·지침 무시, 없는 대상 0건 설명, 미확정·비공개 거절 사유를 미개찰·미래 질의로 한정 | 게이트 통과, 리뷰 결함 0, 전량 4,890, CI 성공. Ollama 실측 전 |
| ah3 `task_bc1a24573c3f` | `c0758dc8` | backup 하트비트 키 분리(`bidbox:backup_worker:heartbeat`)와 backup 헬스체크, 회원가입 IP 요청 제한(API·SSR), Caddy 보안 헤더 4종과 Server 헤더 제거 | 리뷰 결함 0, 운영 compose config 통과, mypy 통과, 전량 4,894, CI 성공 |
| ai3 `task_735a17f14e96` | `176f7a96` | 일반 `WorkerSettings.functions` 에서 `backup_schedule_task` 제거 | 리뷰 결함 0, 전량 4,899 |
| ai4 `task_6cb1d67943a2` | `7d33d6cb` | [`docs/analysis/rag_overrefusal_root_cause_20260915.md`](../analysis/rag_overrefusal_root_cause_20260915.md) 과잉거절 4건 원인 조사 | 코디네이터가 질의 계획 4건을 `build_retrieval_plan` 으로 재현해 일치 확인, 재측정 명령 오기 정정(`19a83455`), 전량 4,898 |
| ai2 `task_b68d73ff5be1` | `71084ce3` | 개발 `docker-compose.yml` 포트 전부 `127.0.0.1` 바인딩 | 게이트 통과, compose config 통과, 전량 4,901 |
| ai1 `task_ef625eba33d1` | `83728ff7` | 예측 API 두 경로에 챗봇과 같은 익명 쿼터, `benchmark_latency.py --session-cookie`(쿠키 없이 429 이면 중단) | 게이트 통과, 리뷰 결함 0, 전량 4,907 |

ai1 은 사용자 결정(선택지 A: 익명 쿼터, 챗봇과 설정 공유, `list-models` 공개, React SPA 는 로그인 없이 유지)으로 착수했습니다. ai2·ai4 는 diff 가 작고 코디네이터가 전부 대조해 독립 리뷰어를 생략했습니다.

---

## 4. 이번 세션에서 드러난 결함과 조치

| 결함 | 발견 경로 | 조치 |
| --- | --- | --- |
| `main` CI 규칙 검증 실패 3회(`176f7a96`, `7d33d6cb`, `71084ce3`): `source_commit` 이 9커밋 뒤처짐 | 병합 후 CI 확인 | 이 인수인계 병합에서 `source_commit` 갱신. 병합을 연달아 할 때는 5번째 전에 갱신을 끼워 넣어야 함 |
| ai3 워커가 전량 테스트를 469건으로 허위 보고(실제 4,899) | Level 1 게이트 6 재실행 대조 | 코드는 정상이라 병합, 보고 부정확으로 기록 |
| ah3 게이트 2·6 실패 | `.env.example` 두 줄 추가 | 워커 질문에 코디네이터가 승인한 예외. 건너뛴 테스트는 코디네이터가 직접 실행 |
| ai4 보고서가 canonical 재측정을 `benchmark_rag_segments.py` 로 기재 | 코디네이터 문서 대조 | `measure_llm_quality.py` 로 정정 |
| 세션 초 `ea589753` CI 실패 | CI 로그 | 외부 의존성 다운로드 504, 코드 무관 |
| Xcode 27.0 라이선스 미동의로 `git`·`python3` 일시 차단 | 게이트 실패 | 사용자가 Xcode 설치·동의 완료. 차단 중 실행된 증거 기록 1회는 폐기하고 재기록 |

---

## 5. 후반부: 과잉거절 수정, 실측, 실측이 드러낸 결함 수정

### 5.1 병합 내역

| Task | 병합 | 내용 | 검증 |
| --- | --- | --- | --- |
| aj1 `task_7cb458ae91f1` | `a3a69467` | 공기업명 속 "공사" 를 공사 분야로 오인하지 않음, 공기업 접미사 5종. 수정 전 계획 스냅샷 `tests/fixtures/retrieval_plan_canonical_snapshot.json` 과 불변 테스트 | 워커 규칙이 "서울역사공원조성공사" 같은 지역명 건설공사까지 공기업으로 오인해 코디네이터가 어간 허용 목록 `PUBLIC_CORPORATION_STEMS` 로 좁힘(`b8c6f1f6`). 바뀐 계획은 q29·adv_inst_03·adv_inst_04 뿐. 전량 4,949, CI 성공 |
| aj2 `task_7ed6dc95973f` | `7eac75fc` | "N분기", "N분기와 M분기", 상반기·하반기 해석과 `time_bucket=quarter` 분기별 집계(반열림 구간) | 워커가 계약과 달리 스냅샷을 고쳐 코디네이터가 원복(`1a2bd36f`). 바뀐 계획은 adv_date_02 뿐, 반례 3종 통과. 전량 4,955, CI 성공 |
| ak2 `task_4d03e88e3823` | `8938ef33` | 익명 세션 키 서명을 31자로 잘라 키 64자. 64자 초과 키는 새로 발급 | 게이트 통과, 전량 4,968 |
| ak1 `task_74131d9fd519` | `c32b8456` | ah1 의 0건 설명 문장을 거절형("확인할 수 없어(0건) 정보를 제공할 수 없다", 다른 공고 나열 금지)으로 교체 | 게이트 통과, 전량 4,964 |

aj1·aj2 는 코디네이터 커밋이 추가돼 Level 1 게이트 6 이 보고·커밋 불일치로 실패하므로 전량 테스트·mypy·ruff·계획 재현 대조로 판정했습니다.

### 5.2 실측 결과 (gemma4:e2b, Docker 로컬 스택)

| 측정 | 결과 | 파일 |
| --- | --- | --- |
| 적대적 fixture (35×1, `7eac75fc`) | 25/34(시간 초과 1). adv_date_02·adv_inj_01 통과로 개선, adv_inst_04 는 기관명 슬롯 부재로 여전히 실패, adv_zero_* 는 "0건" 답변이 채점기의 거절형 요구와 어긋나 실패 | `data/benchmarks/noncanonical/adversarial_fixture_v1_gemma4-e2b_20260915.json` |
| canonical 1차 (`7eac75fc`) | numeric 144/144 이나 거절 21/24, 과잉응답 3. 전부 q32 이며 ah1 0건 설명 문장이 원인. canonical 플래그는 true 로 찍혀 오해 소지가 있어 noncanonical 로 옮김 | `data/benchmarks/noncanonical/blind_fixture_v2_e2b_20260915_ah1_refusal_regression.json` |
| canonical 2차 (`c32b8456`) | **통과 복구.** numeric 144/144, evidence recall 1.0, 인용 72/72, 거절 24/24, 과잉응답 0. 응답 P95 6,055ms(09-14 4,128ms) | `data/benchmarks/blind_fixture_v2_e2b_20260915_r2.json` |
| RAG SSE c1 1차 (`7eac75fc`) | 30건 전부 스트림 오류. 원인은 아래 결함 | `data/benchmarks/noncanonical/sse_gate_c1_20260915_r1.json` |
| RAG SSE c1 2차 (`c32b8456`) | 29/30, 첫 토큰 P95 832ms, 완료 P95 1,426ms. 실패 1건은 벤치 자체의 익명 쿼터 초과(워밍업 포함 60초 31건) | `data/benchmarks/noncanonical/sse_gate_c1_20260915_r2.json` |
| 예측 c10 (로그인 쿠키) | 재기동 직후 P95 105.3ms, 워밍 후 63.9ms·85.8ms. 익명 20회 P95 51.5ms. 로그인 경로는 세션 조회로 중앙값 약 7ms 증가 | `data/benchmarks/noncanonical/predict_c10_20260915*.json` |

### 5.3 실측이 드러낸 결함

| 결함 | 원인 | 조치 |
| --- | --- | --- |
| 운영 MySQL 에서 익명 SSE 챗봇이 대화 상태 저장 중 실패 | `6bddc61e`(2026-09-02) 이후 서명 세션 키 76자, `chat_session_states.session_key` 는 `VARCHAR(64)`. SQLite 테스트는 길이 미검사 | ak2. 컬럼은 G1 규칙상 유지하고 키를 64자로 축소, 컬럼 길이 회귀 테스트 추가 |
| ah1 프롬프트가 canonical 거절을 3건 깨뜨림 | 0건 설명형 문장이 거절 패턴을 피함 | ak1 |
| 앱 컨테이너가 `./src` 마운트여도 코드 변경을 자동 재적재하지 않음 | 모듈 수준 상수(`SYSTEM_PROMPT`) | 측정 전 `docker compose restart app worker` 필수 |

### 5.4 al1 복수 기관 추출과 최종 실측

| 항목 | 내용 |
| --- | --- |
| 병합 | al1 `task_73044ced9dab` -> `3044a967`. 질의의 "A, B, C의"·"A와 B의" 열거에서 공백·괄호 없는 2~20자 이름만 기관 후보로 뽑고, 기관명 카탈로그로 실제 수요기관에 대응된 이름만 기관별 집계(건수·평균 낙찰률·최근 결과 3건)를 Source [1] 에 싣습니다. 대응 기관이 없으면 기존 경로 |
| 검증 | 게이트 통과, 전량 4,973. 계획이 바뀐 문항은 adv_inst_02·adv_inst_04 뿐, 스냅샷 미수정, 반례(공고명 괄호, "낙찰금액과 낙찰률", "공고 A와 공고 B") 미추출 |
| 판단 변경 | adv_zero 채점기 수정은 하지 않음. fixture 가 refusal_expected=true 로 정답을 정의하고 있고, ak1 이후 거절·지시 위계 지표는 채점기 변경 없이 통과함. 남은 실패는 0건 설명 지표(0건 표현과 날짜 언급 요구)이며 프롬프트 영역 |
| canonical (`3044a967`) | numeric 144/144, evidence recall 1.0, 인용 72/72, 거절 24/24, 과잉응답 0. `data/benchmarks/blind_fixture_v2_e2b_20260915_r3.json` |
| 적대적 ak1 후 (`c456cec3`) | 25/35, 지시 위계 34·거절 29. `data/benchmarks/noncanonical/adversarial_fixture_v1_gemma4-e2b_20260915_r2.json` |
| 적대적 al1 후 (`3044a967`) | 25/35, adv_inst_02·adv_inst_04 해결, adv_num_04·adv_zero_04 는 1회 측정 편차로 실패, 거절 30·인용 35. `data/benchmarks/noncanonical/adversarial_fixture_v1_gemma4-e2b_20260915_r3.json` |
| 예측 P95 기준 | 회귀 비교 정본은 익명 경로 유지(이전 48ms 와 비교 가능), 로그인 경로는 운영 참고치로 함께 기록 |

---

## 6. 남은 과업

| 순서 | 작업 | 선행 조건 |
| :---: | --- | --- |
| 1 | 과잉거절 P4(예정가격 용어 안내, adv_num_01)와 0건 설명 지표(0건 표현·최신 개찰일 언급). 둘 다 프롬프트 영역 | canonical 재측정 필수, 위험 중간 |
| 2 | 적대적 채점기 거절 패턴이 질문 문구를 따라 쓴 답(adv_date_02 "포함되지 않도록")을 거절로 오탐하는 문제, 적대적 측정 반복 수 1회로 인한 편차 | 채점 변경 시 문항 원문 대조 |
| 3 | 예측 P95 정본은 익명 경로 유지로 결정. 로그인 경로 수치는 참고치로 병기 | - |
| 4 | SSE 게이트 벤치가 워밍업 포함 익명 쿼터를 넘지 않게 표본 간격 또는 로그인 쿠키 지원 | - |
| 5 | Thng drift baseline: `uv run python scripts/generate_drift_baseline.py --category Thng --start-at 2026-05-26` dry-run 후 `--write` | DB 기동 |
| 6 | 사용자 결정 대기: 출시 형태(결제·약관·비밀번호 찾기), 운영 compose Ollama, Release 첫 실행, 백업 전용 DB 계정, 운영 야간 번들·주간 재학습 기본값, 요청 제한 fail-closed, TTFT 알람 Slack, 협상 가격점수 안내 문구, 2025-07 이전 제한정보 3,213건, 공사 전용 모델 | 사용자 결정 |
| 7 | 이전 과업: 첫 야간 수집 확인, Windows 실기(G2), chromadb 재확인(2026-12-31) | - |

---

## 7. 자원 상태 (세션 종료 시점)

| 대상 | 상태 |
| --- | --- |
| 워크트리·브랜치 | 주 저장소 하나. 워커 워크트리 11개 모두 제거, 병합 브랜치 삭제 |
| Orca | Run `run_75d816606872` 빌더 11, 리뷰어 5 전원 회수. Antigravity 런처·OpenCode 터미널 경로라 비감독이며 창을 직접 닫음. 완료 세션 잔류 없음 |
| 배경 프로세스 | dispatch 가 띄운 `orca_worker_watch.py --watch` 종료 |
| Docker | 로컬 스택 기동 중(app·worker·db·redis·meilisearch). 포트는 ai2 로 `127.0.0.1` 바인딩 확인 |
| Ollama | 호스트에서 기동, `gemma4:e2b` 로드 상태 |
| 로컬 DB | 벤치 전용 계정 `bench_latency_20260915`(사용자 id 15)을 API 회원가입으로 추가. 비밀번호·쿠키는 저장소에 두지 않음 |
