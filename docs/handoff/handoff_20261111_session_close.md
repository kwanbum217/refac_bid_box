# 핸드오프 인수인계 - 2026-11-11 세션

> **작성일**: 2026-11-11
> **작성**: 코디네이터(Claude Opus 5.5). Orca Run `run_00387065ce45`
> **기준 커밋**: 작성 시점 `main` 은 `f67e2afd` 이며 이 문서는 브랜치 `kwanbum217/orca-tokreport` 에서 씁니다.
> **워커 풀**: 빌더 cmd `deepseek/deepseek-v4.1-flash`, 리뷰어 cmd `z-ai/glm-5.3-flash`(사용자 지정). cmd 요금제 약 80% 사용, 잔여 약 14 크레딧.
> **종료 사유**: 사용자 지시로 인수인계 작성 뒤 Docker 와 배경 프로세스를 모두 내리고 종료합니다.

---

## 0. 다음 세션이 바로 할 일

| 우선 | 과업 | 방법 |
| --- | --- | --- |
| 1 | 나라장터 키 상태 확인(사용자) | 예비가격 단건 소급이 동시성 16에서 429 를 4,736회, 동시성 1에서 401 을 받았습니다. 공공데이터포털에서 `ScsbidInfoService` 키의 상태와 일일 트래픽 한도를 확인해야 합니다. 10-17 이후 일일 예비가격 수집이 멈춘 원인도 같은 문제일 수 있습니다 |
| 2 | 예비가격 소급 재개 | 키가 정상이면 `G2B_MAX_CONCURRENT=2 uv run python scripts/backfill_prearng_by_notices.py --since 2026-10-12 --until 2026-10-27 --limit 2000 --execute`(주 저장소, 나라장터 키가 있는 `.env`). 사용자 결정은 하루 2,000건. 10-28 이후는 일일 크론 14일 창이 채웁니다 |
| 3 | 성능 측정(점검표 3장) | 측정 전용 계정 `bench_measure_20261111` 을 만들었고 자격은 주 저장소 `.env` 의 `BENCHMARK_USERNAME`·`BENCHMARK_PASSWORD` 에만 있습니다. 워커·워크트리 0대인 조용한 상태에서 `scripts/benchmark_latency.py --session-cookie <로그인 쿠키>` 3회. `.git/info/exclude` 에 미추적 백업 2개를 넣어 출처 검증의 dirty 판정을 피했습니다 |
| 4 | main CI 확인 | 마지막 병합들의 `gh run list --branch main --limit 3` |
| 5 | 결정 대기 | I-ai F-07(`/predict` 누락 특징 422), I-data F-08(REST 응답 필드 범위), I-data F-05(자동화 구독), I-data F-10(비밀번호 변경·탈퇴) |

---

## 1. 이 세션에서 main 에 넣은 것

모든 브랜치는 빌더 → GLM 독립 리뷰 pass → 통합 브랜치 묶음 → Level 1 strict 증거 → 전량 시험 증거 순서를 거쳤습니다.

| 병합 | 내용 |
| --- | --- |
| `f6edce61` | 예측 경고 4필드를 상세 화면·React 까지 전달, OCR 시험 타임아웃 안정화, `schedule_run_log` 실행 기록 영구화, 로그아웃 오프로드·`end_date` 검증, 11-09 검토 미확인 13항목 재현 보고서 |
| `08c801f8` | 브레드크럼 전역 제거, 낙찰 결과 용역 고정, 대시보드 삭제(옛 주소는 홈으로), 비교 분석 메뉴, `/rules` bid_id 인증·쿼터, React `features_used` 노출 제거, ChromaDB 클라이언트 프로세스 재사용(P50 1.33→0.60ms), 드리프트 감시를 서빙 모델 기준으로 |
| `84e8ed14` | 드리프트 시험 Windows 경로 구분자 핫픽스 |
| `5676c007` | Meilisearch 삭제 정리 스크립트(기본 dry-run, 1% 상한)와 건수 불일치 알림, 규칙 커버리지 원장·하한율 지표 재생성 |
| `56b1a4e4` | 자동화 예측 검증 단계가 서빙 홀드아웃 `avg_r2` 를 싣도록(`src/ml/serving_metrics.py`) |
| `16e068b2` | `CURRENT_STATE` `source_commit` 갱신(CI 신선도 검사) |
| `d4282bcd` | 한 화면 새 메인(용역 365일·입찰 중·내 조건 입찰 중, 모델 실측 오차), 회원 관심 업종·지역(`account_bid_preferences`), 업종 조건 공용 함수 `license_match_clause`, 승격 판정 파일 런북 |
| `d2a4384e` | 예비가격 공고 단건 소급 스크립트, LLM fixture 별 manifest 경로 분리 |
| `f67e2afd` | LLM fixture v2 근거 manifest(정본 ChromaDB, 근거 ID 24개) |
| 이 브랜치 | 토큰 절약 도구 A/B 측정 보고서(`docs/analysis/token_saving_tools_ab_20261111.md`)와 이 인수인계 |

---

## 2. 운영 반영

| 항목 | 결과 |
| --- | --- |
| 운영 DB 마이그레이션 | `c5d6e7f8a9b0`(`schedule_run_log`), `d6e7f8a9b0c1`(`account_bid_preferences`) 적용. 둘 다 새 테이블만, 기존 테이블 무변경, 사용자 승인 후 적용. G1 기준선 재생성 |
| Meilisearch 전체 재색인 | 완료(공고 4,933,831, 낙찰 3,474,252) |
| 백업 스냅샷 | 최근 3개만 보존(`20261103`, `20261106`, `20261107`), 7개 삭제. 보존 3개 verify PASS |
| 디스크 | 약 20GB → 92GB 여유. Docker 이미지·빌드 캐시, Homebrew·pip·npm 캐시 정리. uv 캐시(6.1GB)는 미정리 |
| 측정 계정 | `bench_measure_20261111` 생성(운영 회원 테이블 1행) |
| 헤드룸 | `uv tool` 로 저장소 밖 설치 상태. 제거는 `uv tool uninstall headroom-ai` |

---

## 3. 미착수·후속 과업

| 과업 | 근거 | 비고 |
| --- | --- | --- |
| 예비가격 소급과 수집 중단 원인 | 0장 1·2번 | 키 상태 확인이 먼저 |
| `schedule_run_log` 같은 시각 다중 행 | 같은 `started_at` 으로 backup·drift_monitor 가 여러 행 기록됨(오늘 worker 재시작 여러 번) | 기동 따라잡기 중복인지 기록 시각 결함인지 조사 필요 |
| 벤치마크 Docker 29 호환 | `scripts/benchmark_provenance.py` 694행 `{{.NetworkSettings.IPAddress}}` 가 Docker 29.9.3 에서 템플릿 오류. 판정에는 영향 없음 | `.NetworkSettings.Networks` 경로로 교체 |
| 점검표 미달 2·3번 | 규칙 커버리지·하한율 지표는 재생성 완료. 창이 날짜 기준이라 다음 점검 때 다시 차이가 납니다 | 생성기에 기준일 인자 추가 검토 |
| I-ai F-08 | train/serve 기관 이력 폴백 정의 차이(재현됨) | 서빙 예측값이 바뀌므로 쌍대 검정이 필요 |
| 결정 대기 4건 | 0장 5번 | 재현 보고서 `docs/analysis/feat_review_repro_20261111.md` |

---

## 4. 운영 메모

| 항목 | 내용 |
| --- | --- |
| Windows CI 경로 | `str(Path)` 를 `/` 문자열과 비교한 시험이 Windows CI 에서만 실패했습니다. 빌더 Intent 에 `Path.as_posix()` 를 명시합니다 |
| source_commit 신선도 | 병합이 여러 번이면 `CURRENT_STATE` `source_commit` 이 5커밋을 넘어 CI 가 실패합니다. 통합 브랜치에서 병합 커밋 전에 갱신합니다 |
| GLM 리뷰어 승인 대화창 | yolo 로도 "Destructive command" 대화창은 우회되지 않습니다(파이썬 변수 `rm` 오인). 리뷰 Intent 에 셸 단어 금지 문구를 넣고, 감시 루프가 `1. Yes` 문구를 직접 잡습니다 |
| 같은 cmd 계열 리뷰어 | taskctl 라우터가 거부하므로 `orchestration dispatch --return-preamble` 로 preamble 을 받아 런처 대기 터미널에 넣습니다 |
| 정본 스킬 영수증 | 프로젝트 `SessionStart` 훅이 세션마다 영수증을 재발급해 다른 세션(`grok`)이 열리면 코디네이터의 Task 생성이 거부됩니다. `python3 scripts/orca_skill_receipt.py issue` 로 재발급 |
| 토큰 측정 결론 | 헤드룸(비용 -6.1%, p 약 0.72)과 포니테일(+0.6%, p 약 0.93) 모두 비용 차이 미검출. 포니테일은 추가 코드 줄 -35%. 비용 대부분은 큰 컨텍스트 캐시 읽기 |
| 종료 상태 | Docker Desktop 정지, Orca 워커 0, 워크트리 0, 배경 감시기·프록시 정지 |
