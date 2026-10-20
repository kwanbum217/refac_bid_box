# 핸드오프 인수인계 — 등급확인서 파서·추출 API 방어, 공고 상세(낙찰방법·첨부파일·재계산), 미등록 기관 조사, 규칙 커버리지 원장

> **작성일**: 2026-10-14
> **작성**: Claude 코디네이터 (Orca Run `run_43cef2f8bd69`)
> **기준 커밋**: `fd1a88a0` (이 문서가 들어가는 병합의 부모)
> **직전 인수인계**: [handoff_20261013_history_quant_close.md](handoff_20261013_history_quant_close.md)

---

## 0. 다음 세션이 가장 먼저 할 일

| 우선 | 과제 | 선행 |
| --- | --- | --- |
| 1 | 이 문서 병합 커밋의 main CI 녹색 확인 | 없음 |
| 2 | 산림청·해양환경공단을 기관 규칙 명단과 코드(`INSTITUTION_RULES`)에 반영하는 R2 형 Task | 사용자 승인 |
| 3 | 커버리지 원장 `investigation` 필드에 ICA·ICB 조사 결론 14곳 기록 후 원장 재생성 | 없음 |
| 4 | 국방부·한국공항공사 partial 구간 원문(전사 규정·통과점수) 추가 수집 | 없음 |
| 5 | 계산 차단 67% 의 원인별 대응 결정(아래 4절) | 사용자 결정 |

---

## 1. 이번 세션 병합

빌더는 cmd `deepseek/deepseek-v4.1-flash`(effort default·high, `--auto` yolo), 리뷰어는 qwen 경유 OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`(`~/.qwen/settings.json` 의 `reasoningEffort: max`, YOLO TUI). 모든 병합은 Level 1 strict 증거, 워커 워크트리에서 기록한 전량 시험 증거, 직전 병합 CI 녹색 확인, 병합 커밋 안 `source_commit` 갱신을 거쳤다. 병합 직후 워크트리를 제거했다.

| Task | 병합 | 내용 |
| --- | --- | --- |
| OCR2 | `4a1f7d5e` | 문서 추출 API: 동시 처리 상한 2(BoundedSemaphore, 초과 503), 요청 제한기 Redis 장애 시 503 fail-closed, Content-Length 선검사와 스트림 누적 5MB 초과 즉시 413 |
| OCR3 | `e78cd6be` | `doc-autofill.js`: 등급 미인식이어도 평가일만 미리 채움, 근거 계약을 단일 객체로 정리 |
| OCR1 | `f88ee56a` | 등급확인서 파서: 상품 등급(회사채·기업어음·단기·CP)만 있으면 미채택, 제목 '신용평가등급확인서' 를 라벨에서 제외, 근거를 값 줄로 한정(개인정보 노출 차단), 중복 키 (page, value) |
| AM1 | `a250e246` | 공고 상세 사양 카드 '낙찰 방법' 칸. `raw_data` 의 sucsfbidMthdNm, 원문이 '공고서참조' 면 코드 계열명 + '(코드 기준)' |
| AT1 | `42d4a389` | 공고 상세 '공고 첨부파일' 카드. ntceSpecDocUrl1~10, 표준공고문, 나라장터 원문 링크. `https://www.g2b.go.kr` 만 허용, 새 탭 직접 다운로드(서버 중계 없음) |
| ICA | `299795cc` | 미등록 국가계약 기관 7곳 조사 후보(`institution_rules_candidates_a_20261014.yaml`) |
| ICB | `95c75601` | 미등록 국가계약 기관 7곳 조사 후보(`institution_rules_candidates_b_20261014.yaml`) |
| CL1 | `cbc85ae3` | 규칙 커버리지 원장 `data/reference/rule_coverage_ledger.yaml` 과 생성 스크립트 `scripts/report_rule_coverage.py`, 정합 시험 |
| RC1 | `fd1a88a0` | 공고 상세 '점수 반영해 다시 계산' 버튼 복원(자동 계산 유지), PRICE_BOUNDS_UNRESOLVED 차단 시 부족 정량점수와 여지 항목 안내 |

---

## 2. 사용자 결정 (2026-10-14)

| 결정 | 내용 |
| --- | --- |
| 등급확인서 F1 | 상품 등급만 있는 문서는 값을 만들지 않는다(low 고정 대안 기각) |
| 낙찰방법 표시 | 공고 상세만. 코드 추정은 '계열명 (코드 기준)' |
| 첨부파일 | 나라장터 직접 링크. 첨부 1~10, 표준공고문, 나라장터 원문 모두 |
| 커버리지 원장 | 미등록 기관 목록의 정본을 원장으로 둔다 |
| 재계산 버튼 | 자동 계산 유지 + 명시적 버튼 + 차단 갭 안내 |
| 빌더 대체 | Command Code 크레딧 소진 시 grok-4.7, effort 는 Task 위험도별 low·medium. 라우터·런처에 4.7 미등록이라 교체 시 보강 필요 |

---

## 3. 미등록 기관 조사 결과 (ICA·ICB, 리뷰 pass)

| 판정 | 기관 |
| --- | --- |
| 명단 추가 가능 | 산림청(산림사업 적격심사 세부기준 예규 제728호, 5구간, 통과 95), 해양환경공단(해양폐기물정화용역 세부기준, 4구간) |
| 일부 확정 | 국방부(기술용역 훈령, 별표 본문 미확보), 한국공항공사(구간 라벨·통과점수 미확보) |
| 조달청·국가유산청 기준 준용 | 해양수산부, 부산항만공사, 한국농수산식품유통공사, 국민건강보험공단, 국방과학연구소, 한국환경공단, 한국어촌어항공단, 국가유산진흥원, 한국광해광업공단, 한국원자력환경공단 |

- 산림청 별표 PDF 는 `scripts/extract_score_params.extract_document_text` 가 읽지 못한다(PDF 미지원). `pdfplumber` 로 읽으면 B·k·기준 88·통과 95 가 확인된다. 후보 YAML 의 PDF 행 번호는 빌더 CLI 리더 기준이라 pdfplumber 행과 다르다.
- 수집 원문은 주 저장소 `.cache/inst_candidates/`(gitignore)에 옮겨 두었다.

---

## 4. 규칙 커버리지 원장 첫 결과

최근 12개월 용역 적격심사(`낙030001`) 공고 31,485건, 수요기관 3,433곳을 서비스 판정 함수 그대로 분류했다.

| 분류 | 공고 | 비율 |
| --- | ---: | ---: |
| 계산 차단 | 20,973 | 66.6% |
| 조달청 기본 규칙 | 8,804 | 28.0% |
| 지역 규칙 | 1,655 | 5.3% |
| 기관 규칙 | 53 | 0.2% |

| 차단 원인 | 의미 |
| --- | --- |
| RULE_REGIME_MISMATCH | 공고일이 적용 별표 시행일보다 앞섬(1년 창에 시행일 이전 공고 포함) |
| MANUAL_EVALUATION | 낙찰방법 '관리규정외 수기심사' |
| LOCAL_SERVICE_TYPE_UNRESOLVED | 지자체 별표 세부유형을 사용자가 고르기 전 상태(화면에서 선택하면 풀림) |
| RULE_NOT_FOUND, LOCAL_RULE_NOT_FOUND | 기관·지역 규칙 부재 |

- 세션 중 코디네이터가 기관명 문자열 포함으로 낸 근사 집계(지역 규칙 66%)는 틀렸다. 정본은 원장이다.
- 재생성: `uv run python scripts/report_rule_coverage.py`(DB 읽기 전용), 차이 확인은 `--check`.

---

## 5. 운영 교훈

| 교훈 | 내용 |
| --- | --- |
| 병합 직후 워크트리 제거 | OCR2·OCR3 를 병합하고 워크트리를 남겨 사용자가 지적했다. `orca worktree rm` 은 비동기라 디렉터리 소멸까지 기다린 뒤 `git worktree prune` |
| Capsule 재작성 들여쓰기 | `yaml.safe_dump` 로 Capsule 을 다시 쓰면 목록 들여쓰기가 사라져 scope guard 가 빈 목록으로 읽고 커밋을 막는다. `increase_indent` 를 덮어쓴 Dumper 로 쓰고 `parse_capsule_list` 로 확인 |
| 템플릿 개수 단정 | 템플릿 파일을 추가하면 `tests/test_ui_ssr.py` 와 `tests/test_tailwind_build.py` 의 개수 단정을 함께 올려야 한다. Intent 범위에 미리 넣을 것 |
| Command Code 학습 대화창 | 'Build Your Coding Taste' 가 작업 중간에도 뜬다. 상시 감시기는 못 잡으므로 bash 루프로 `n` 을 자동 전송했다 |
| 셸 함정 재발 | bash 3.2 의 `${g^^}`, zsh 의 `for h in $H`, heredoc 안 한글 파이썬의 인코딩 오류. 생성 스크립트는 파일로 쓰고 `uv run python` 으로 실행 |
| 증거 파일 직렬 | `.cache/level1_strict_evidence.json` 과 `premerge_full_suite_evidence.json` 은 공용이라 브랜치마다 기록-병합을 한 번에 하나씩 |
| Level 1 게이트 CSS 능력 | 템플릿 변경 브랜치는 `--verify "npm run build:css" --verify "git diff --exit-code -- src/app/static/css/tailwind.css"` 를 붙여야 strict 통과 |

---

## 6. 결정 대기와 외부 대기

| 항목 | 상태 |
| --- | --- |
| 산림청·해양환경공단 명단·코드 반영 | 사용자 승인 대기 |
| 계산 차단 67% 대응(시행일 이전 공고용 구판 별표, 수기심사 안내, 세부유형 기본값) | 사용자 결정 |
| Command Code 플랜 잔량 92%(약 5.7 credits) | 소진 시 grok-4.7 대체, 라우터·런처 보강 필요 |
| 운영 서버 등급확인서 플래그, 과거 공고 22.7만 건 추출 | 이전 세션부터 사용자 결정 |
| 한국도로공사 현행판, G2 Windows | 외부 대기 |

---

## 7. 세션 종료 상태

| 항목 | 상태 |
| --- | --- |
| Orca 워커 터미널 | 전부 회수, 코디네이터 창만 남김 |
| 워커 워크트리 | 전부 제거 |
| Docker Compose(app, db, redis, meilisearch, worker) | 사용자 요청으로 컴퓨터 종료를 위해 전부 정지 |
| Vite 개발 서버, 배경 감시 작업 | 종료 |
