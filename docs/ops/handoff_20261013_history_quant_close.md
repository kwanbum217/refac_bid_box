# 핸드오프 인수인계 — 과거 공고 이력 레지스트리, 기관 정량 배점표 반영, 등급확인서 기능 활성화

> **작성일**: 2026-10-13
> **작성**: Claude 코디네이터 (Orca Run `run_7aa274a7a180`, `run_83f128ff89f8`, `run_b596a890c5b6`)
> **기준 커밋**: `c79969fc` (이 문서가 들어가는 병합의 부모)
> **직전 인수인계**: [handoff_20261013_inst_close.md](handoff_20261013_inst_close.md)

---

## 0. 다음 세션이 가장 먼저 할 일

| 우선 | 과제 | 선행 |
| --- | --- | --- |
| 1 | 직전 병합(`이 문서 병합 커밋`)의 main CI 녹색 확인 | 없음 |
| 2 | P3 기술용역 명세를 이력 레지스트리에 반영하고 과거 공고 대응률 재측정(H4) | P3 병합(`c79969fc`) |
| 3 | 평가 화면에서 기관 공고(예: 한국농어촌공사)를 열어 배점표 입력칸을 눈으로 확인 | app 기동 |
| 4 | 운영 서버에 등급확인서 플래그 두 줄 반영 여부 결정 | 사용자 결정 |

---

## 1. 이번 세션 병합

빌더는 cmd `deepseek/deepseek-v4.1-flash`(high), 리뷰어는 qwen 경유 OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`(max, YOLO). 모든 병합은 strict 게이트, 병합 전 전량 시험, 직전 병합 CI 녹색 확인, 병합 커밋 안 `source_commit` 갱신을 거쳤다.

| Task | 병합 | 내용 |
| --- | --- | --- |
| K1 | `db473092` | 바이너리 HWP 수식 개체 판독, k 23→24 |
| Q1 | `03199869` | qwen 런처 기본 기동을 `--yolo -i`(대화형)로 |
| S2 | `e1670787` | 추정가격 구간으로 B·k 후보 하나를 고르는 `select_band` |
| C1 | `c7674ebc` | 과거 공고 기준명→규칙 대응 실측 11/227 |
| 인수인계 | `f7593546` | 직전 인수인계 6절 추가 |
| P2 | `ce5526f2` | 2015~2022 조달청 일반용역 적격심사 12개 판 별표 명세(`data/reference/pps_servc_qual_history_2015_2022.yaml`) |
| Q2 | `97bec112` | 기관 10곳 정량 배점표 명세 67규칙·136구간(`data/reference/institution_quant_tables_20261013.yaml`), 합계 검산 불일치 0 |
| H3 | `2571fa09` | 이력 레지스트리 `src/app/services/evaluation_rules_history.py`(생성물, `scripts/build_pps_history_rules.py --check`), 대응 11→16/227. 서빙 `evaluation_rules.py` 무변경 |
| CI 수정 | `35a5ad6c` | 생성 데이터 모듈 두 개를 jscpd 에서 제외(H3 뒤 207건 7.84% 로 임계 5% 초과), OCR 토글 꺼짐 시험이 로컬 `.env` 에 기대던 것을 고정 |
| Q3 | `f3027f5f` | 기관 65규칙·131구간 배점표를 `INSTITUTION_QUANT_SCORE_TABLES`(생성물, `scripts/build_institution_quant_tables.py --check`)로 반영, `quant_basis=INSTITUTION`. 한국가스공사 2규칙은 직접 입력 유지. 조달청·LOCAL 불변 |
| P3 | `c79969fc` | 2015~2022 조달청 기술용역 적격심사 6개 판 별표1 명세, GENERAL 기준명 69건 분류(미분류 30) |

---

## 2. 등급확인서 자동입력 활성화 (사용자 지시)

- 로컬 `.env` 에 `DOCUMENT_EXTRACTION_ENABLED=true`, `DOCUMENT_OCR_ENABLED=true` 를 추가했다. 백업은 `.cache/env.bak.20261013`.
- OCR 모델은 `scripts/fetch_ocr_models.py` 로 `data/ocr_models/` 에 받았다(sha256 대조 통과).
- 실행 중 app 컨테이너에서 확인: 비로그인 추출 요청 404→401, 텍스트 PDF(동원 2025) A-·2025-06-30, 스캔본(동원 2025) OCR A-·2025-06-30(2.0초), 스캔본(한미 2024) AA0·평가일 없음(4.5초).
- Q3 병합 뒤 app 재시작 후 실행 중 컨테이너 확인: 기관 규칙 `quant_basis` INSTITUTION 65·AGENCY_DOCUMENT_NOT_LOADED 2(한국가스공사), `SERVC_INST_KRC_20260624_ACADEMIC` 은 별표 1 배점표(구간 2개) 반환, 조달청 `SERVC_QUAL_PRE_20250901_ATTACH_01` 은 종전 별표 2 그대로.
- 운영 서버는 그쪽 환경변수에 같은 두 줄을 넣어야 켜진다. 아직 반영하지 않았다.

---

## 3. 과거 공고 B·k 채우기 현황

H3 재측정 기준 대응 불가 211건의 사유는 다음과 같다(`docs/analysis/past_criteria_rule_map_20261013.md` 7.5절).

| 사유 | 건수 | 다음 조치 |
| --- | ---: | --- |
| 기술용역 별표 없음 | 95 | P3 명세를 이력 레지스트리에 반영(H4) |
| 일반용역(GENERAL) 별표 없음 | 61 | P3 문서의 GENERAL 분류표(분류 39, 미분류 30)로 대응 규칙 지정 |
| LOCAL 미등록 유형 | 20 | 시·도 기준 추가 수집 |
| 그 밖 | 35 | 2015-01~04 공고, 고시금액 미상 1건 등 |

결과 CSV 는 주 저장소 `.cache/past_criteria_map_h3/`, 원문은 `.cache/pps_history/`, `.cache/pps_tech_history/`, 기관 원문 추출 텍스트는 `.cache/inst_quant_q2/` 에 있다(gitignore).

---

## 4. 운영 교훈

| 교훈 | 내용 |
| --- | --- |
| 리뷰어가 판정 뒤 보고서를 안 쓰고 멈춘다 | qwen Nemotron 리뷰어가 "이제 review_done.json 을 쓰겠다" 에서 차례를 끝냈다. 보고서 파일 존재와 화면 작업 표시를 같이 보는 감시기로 자동 재지시했다 |
| cmd 연결 오류 | `Connection error` 3회 재시도 실패 시 `continue` 입력이 필요하다. 감시기가 자동으로 보낸다 |
| 게이트 3 능력 | `ci.yml` 변경은 `uv run actionlint`, 템플릿 변경은 `npm run build:css` 와 `git diff --exit-code -- src/app/static/css/tailwind.css`(디렉터리 경로는 거부됨)가 필요하다 |
| 생성 상수 모듈과 jscpd | 명세에서 생성한 상수 모듈은 반복 구조라 jscpd 임계를 넘긴다. 새 생성 모듈은 `.jscpd.json` ignore 에 함께 넣는다 |
| 시험의 로컬 설정 의존 | 플래그 기본값에 기대는 시험은 로컬 `.env` 를 켜는 순간 깨진다. 시험 안에서 설정을 명시한다 |
| 병합 스크립트의 CI 확인 | 주 저장소가 main 이 아닌 브랜치에 있으면 HEAD 로 CI 를 찾지 못해 무한 대기한다. 코디네이터 브랜치 작업 중에는 병합 스크립트를 돌리지 않는다 |
| 보고 건수 | 빌더가 시험을 추가한 뒤 건수를 고치지 않아(178 대 179) 게이트 6 이 거부했다. 코드 수정 없는 보고 정정 Task 로 처리했다 |
| 코디네이터 터미널 Run 바인딩 | 새 Run 을 만들면 이전 Run 배치를 ack 할 수 없다. 병렬 과업은 한 Run 에 묶는다 |

---

## 5. 결정 대기와 외부 대기

| 항목 | 상태 |
| --- | --- |
| 운영 서버 등급확인서 플래그 | 사용자 결정 |
| 과거 공고 22.7만 건 전량 추출 | 사용자 결정 |
| 한국가스공사 정량 배점(별표 9 숫자 미인쇄) | 원문 추가 확보 필요 |
| 한국도로공사 현행판, G2 Windows, 운영 서버 Z1·Z2 | 외부 대기 |
