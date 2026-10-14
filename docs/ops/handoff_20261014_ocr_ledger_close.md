# 핸드오프 인수인계 — 신용등급 중복 제거, 같은 줄 근거 절단, 원장 조사 결론

> **작성일**: 2026-10-14
> **작성**: Grok 코디네이터 (Orca Run `run_d58eab3c7c15`)
> **기준 커밋**: `b67f3356` (이 문서가 들어가는 병합의 부모)
> **직전 인수인계**: [handoff_20261014_detail_page_coverage_close.md](handoff_20261014_detail_page_coverage_close.md)

---

## 0. 다음 세션이 가장 먼저 할 일

| 우선 | 과제 | 선행 |
| --- | --- | --- |
| 1 | 이 문서가 들어간 병합의 main CI 녹색 확인 | 없음 |
| 2 | 산림청·해양환경공단을 기관 규칙 명단과 `INSTITUTION_RULES` 에 반영 | 사용자 승인 |
| 3 | 커버리지 원장 재생성. `investigation` 16행은 이미 기록되어 있고 생성기는 `dminstt_cd` 로 그 값을 보존한다 | Docker 와 DB |
| 4 | 국방부·한국공항공사 partial 구간 원문(전사 규정·통과점수) 추가 수집 | 없음 |
| 5 | 계산 차단 약 67% 의 원인별 대응 결정. 정본 설명은 직전 인수인계 4절 | 사용자 결정 |

---

## 1. 이번 세션 병합

빌더는 Command Code `deepseek/deepseek-v4.1-flash`(effort high, `scripts/orca_cmd_launch.py --auto`). 리뷰어는 qwen 경유 OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`(`~/.qwen/settings.json` 의 `reasoningEffort: max`). 리뷰어는 빌더 `worker_done` 뒤에만 띄웠다. 병합은 Level 1 strict 증거, 워커 워크트리에서 기록한 전량 시험 증거, 직전 `main` CI 녹색, 병합 커밋 안 `source_commit` 갱신을 거쳤다.

| 작업 | 병합 | 작업 커밋 | 내용 |
| --- | --- | --- | --- |
| 같은 줄 근거 | `2d8bb7c2` | `5e36055a` | 등급·평가일 근거를 라벨 시작부터 값 끝까지로 자름. 2열 표는 라벨과 값을 유지. `_dedupe` 는 이 브랜치에서 바꾸지 않음 |
| 원장 조사 결론 | `b67f3356` | `9bfff08e` | ICA·ICB 14곳 결론을 원장 `investigation` 16행에 기록. 재생성은 하지 않음 |
| 등급 중복 제거 | 이 문서의 병합 | `e5b87c6f` | `_dedupe` 키를 `(page, value, preferred)` 로 바꿔 같은 쪽의 상품 등급이 일반 신용등급을 지우지 않게 함 |

전량 시험은 `uv run pytest tests/ -q -m 'not data_assets'` 이다.

| 작업 커밋 | 전량 시험 | Level 1 | 직전 main CI |
| --- | --- | --- | --- |
| `5e36055a` | 7633 passed, 50 skipped, 3 deselected, 239.57s | strict 11/11 | `4128569d` 녹색, Actions `38531354588` |
| `9bfff08e` | 7630 passed, 50 skipped, 3 deselected, 249.57s | strict 11/11 | `2d8bb7c2` 녹색, Actions `38580757719` |
| `e5b87c6f` | 7635 passed, 50 skipped, 3 deselected, 241.80s | strict 11/11. 파서 묶음 122 passed, 1 skipped. mypy 소스 135파일 이상 없음 | `b67f3356` 녹색, Actions `38583180690` |

파서 묶음 통과 건수가 브랜치마다 다른 것은 각 브랜치가 서로 다른 회귀 시험을 더했기 때문이다. 게이트가 워크트리에서 다시 센 값이다.

---

## 2. 등급확인서 파서

허용 파일은 `src/app/services/document_extraction/credit_certificate.py` 와 파서·API 시험뿐이었다. 등급 허용 목록, 응답 스키마, `MAX_EVIDENCE_LENGTH` 120, 상품 등급만 있을 때 `credit_grade` 가 None 인 규칙은 유지한다.

| 입력 | 결과 |
| --- | --- |
| 회사채등급 AA- 다음 줄 신용등급 AA- | 값 AA-. 근거에 신용등급이 있고 회사채는 없다 |
| 기업어음등급 A0 다음 줄 신용평가등급 A0, 평가일 2026.02.01 | 등급 A0, 평가일 2026-02-01 |
| 신용등급 A+ 두 번 | 값 A+, confidence high. 같은 일반 등급은 한 후보로 접히므로 high 유지는 의도이며 커밋 본문에 적었다 |
| 같은 줄의 상호·대표·등급·평가일 | 값은 유지하고 근거에서 상호·대표·이름·사업자번호·비고·유효기간을 뺀다 |
| 신용등급 다음 줄 A+ | 근거에 신용등급과 A+ 가 함께 있다 |

날짜 중복 제거 키는 `(page, value)` 그대로다.

---

## 3. 원장 investigation

행 수 1,112 는 그대로다. 바뀐 필드는 `investigation` 뿐이고 16행만 값이 있다. 없는 행은 만들지 않았다. 후보 `name_aliases` 와 겹치는 김포공항, 지방청, 지방산림청, 환경본부, 일산병원, 지역본부 등은 null 이다. 빌더가 별칭 54행과 16행 중 어디를 채울지 물었고, 코디네이터는 16행으로 확정했다.

| 행 | status | recommendation |
| --- | --- | --- |
| 해양환경공단, 산림청 | confirmed | add_to_registry |
| 한국공항공사, 국방부 별칭 3행 | partial | partial |
| 해양수산부, 한국농수산식품유통공사, 국민건강보험공단, 부산항만공사 | confirmed | pps_standard_applies |
| 국방과학연구소, 한국환경공단, 한국어촌어항공단, 국가유산진흥원, 한국광해광업공단, 한국원자력환경공단 | unresolved | pps_standard_applies |

국방부라는 이름의 행은 없다. 같은 결론을 적은 별칭 3행은 국방부 국군재정관리단, 국방부 국군조직 육군 군단 제3군단, 국방부 한국국방연구원이다. `date` 는 2026-10-14 이고 `source` 는 해당 후보 YAML 의 프로젝트 상대 경로다. Docker 데몬이 꺼져 있어 `scripts/report_rule_coverage.py` 는 실행하지 않았다.

---

## 4. 하지 않은 일

| 항목 | 이유 |
| --- | --- |
| 산림청·해양환경공단 코드 등록 | 사용자 승인 전 |
| 계산 차단 약 67% 대응 | 사용자 결정 전. 근사 집계는 쓰지 않고 원장 비율을 정본으로 둔다 |
| 국방부·한국공항공사 원문 추가 수집 | 이번 세션의 한 쓰기 작업은 원장 기록이었다 |
| 원장 재생성 | Docker 가 꺼져 있었다. 기록된 `investigation` 은 재생성 때 코드 키로 남는다 |

---

## 5. 운영 교훈

| 교훈 | 내용 |
| --- | --- |
| 증거 파일은 한 커밋 | `.cache/level1_strict_evidence.json` 과 `premerge_full_suite_evidence.json` 은 마지막 기록만 가진다. 한 브랜치를 기록하고 병합한 뒤에 다음 브랜치를 기록한다 |
| 완료 터미널이 다음 배정을 막음 | `worker_done` 뒤 터미널을 닫지 않으면 다음 dispatch 가 `settled_session_lingering` 으로 거절된다. `worker-release` 후 `orca terminal close --terminal` 만 쓴다. `--tab` 은 코디네이터 창까지 닫는다 |
| 리뷰 보고 파일 | 리뷰어 산출물은 `review_done.json` 이다. 런처 안내의 전송 유형은 `worker_done` 이다 |
| 런처 배정 | cmd 와 qwen 은 `worker-start --agent` 에 없다. 워크트리 안에서 런처 터미널을 만든 뒤 `taskctl dispatch --launcher` 를 쓴다. `terminal_not_settled` exit 3 은 오탐일 수 있으니 `terminal read` 로 확인한다 |

---

## 6. 세션 종료 상태

| 항목 | 상태 |
| --- | --- |
| Orca Run `run_d58eab3c7c15` | 빌더 3, 리뷰어 3 모두 completed. 워커 터미널은 회수 |
| 워커 워크트리 | 병합 후 제거 |
| Docker | 데몬이 꺼져 있었다. 종료 준비에서 Docker Desktop 과 남은 백그라운드 감시도 내림 |
| `source_commit` | 이 병합 직전 `main` 인 `b67f3356` |
