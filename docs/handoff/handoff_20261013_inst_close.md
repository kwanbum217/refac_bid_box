# 핸드오프 인수인계 — 기관 적격심사 규칙 반영, 등급확인서 추출기 개선, 바이너리 HWP 표 복원

> **작성일**: 2026-10-13
> **작성**: Claude 코디네이터 (Orca Run `run_0d4a9e8bdeb1`, `run_489be1064df2`, `run_594cea228379`, `run_274587559d7b`)
> **기준 커밋**: `871e2b11` (이 문서가 들어가는 병합의 부모)
> **직전 인수인계**: [handoff_20261013_yolo_close.md](handoff_20261013_yolo_close.md)

---

## 0. 다음 세션이 가장 먼저 할 일

| 우선 | 과제 | 선행 |
| --- | --- | --- |
| 1 | 이 문서가 들어간 병합과 `871e2b11` 의 원격 CI 녹색 확인 | 없음 |
| 2 | 리뷰어 풀 확인. opencode Muse Spark 1.3 무료는 한도 소진(약 20시간 재시도), Antigravity 도 사용량 99% 였다. 사용자 지시로 hermes(OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`)를 리뷰어로 썼다(2절) | 없음 |
| 3 | 직전 인수인계 0절의 사용자 조치(운영 서버 Z1·Z2, 비공개 취약점 제보 활성화)는 그대로 남아 있다 | 사용자 |

---

## 1. 이 세션에서 병합한 것

빌더는 전부 cmd `deepseek/deepseek-v4.1-flash`(yolo 기동). 전부 `--no-ff`, strict 게이트 증거, 병합 전 전량 시험 증거, 직전 병합 CI 녹색 확인을 거쳤다.

| Task | 병합 | 내용 | 리뷰어 |
| --- | --- | --- | --- |
| E1 | `18aea8e2` | cmd 워커 정책 `.env` 읽기 deny 를 비밀값 파일 12종 열거로 좁혀 `.env.example` 허용 | Muse |
| L1 | `96cf5e6e` | 서울 별표 1~4·경기 보험 별표 1-5 하한율 원문 산식 역산 대조. 수치 정정 0, 근거 표기 정리 | Muse |
| Z4W | `ef0068bd` | 웹 공개 등급확인서 샘플 27건 참고 실측(정식 Z4 아님). 등급 13/23, high 신뢰도 오추출 4 | Muse |
| R1 | `f40465b5` | 기관 18곳·구간 189개 산식 명세(`data/reference/institution_rules_20261013.yaml`)와 판정 설계 | Muse |
| X1 | `efd07bae` | 등급확인서 추출기 수정. 같은 27건에서 등급 22/23, high 신뢰도 오추출 0 | Muse |
| H1 | `b9bdacff` | 과거 용역 공고서(2015~2024) 표본 500건 실측. B·k 동시 1/431, 전량 비권고 | Muse |
| R2 | `d602f308` | 확인 기관 10곳 규칙 69개·140구간 반영, 수요기관 코드·이름·별칭 정확 일치, 조달청 대행 배제 플래그 | Muse |
| R3 | `defe5b73` | 한수원 본사 별칭(0→94건), 인천공항 두 곳 별표 8 임대차를 고시금액 경계 k=2/k=4 로 확정, docstring 정정 | Muse |
| P1 | `54295f36` | 바이너리 HWP 5.x 표 레코드 복원. 기준서 샘플 표 28개·행 170개, B·k 추출 | Muse |
| S1 | `66e6aa30` | 하위 조직 적용 범위 조사. 적용 3곳(국토교통부·환경부·한국석유공사), 근거 부족 7곳 | cmd glm-5.3-flash(예외) |
| H2 | `74416a32` | P1 이후 과거 공고서 재측정. B·k 동시 1→10(2.32%), 회귀 0 | hermes(예외) |
| R4 | `871e2b11` | 하위 조직 매칭 3곳 구현. 2025-06 이후 기관 축 신규 일치 국토교통부 4,460·환경부 2,161 | hermes(예외) |

---

## 2. 사용자 결정과 정책 예외

1. **기관 규칙 반영 범위**: R1 명세 status=confirmed 10곳만. 조달청 대행 공고(공고기관=조달청 계열)는 기관 규칙 배제(플래그 `EXCLUDE_INSTITUTION_RULES_FOR_PPS_PROXY=True`). 기관 규칙이 매칭되지만 시행일·제도가 맞지 않는 기관 자체 공고는 조달청 대체 계산 없이 차단 유지(실측 20건, 주로 한국농어촌공사).
2. **매칭 원칙**: 규칙과 공고 양쪽에 코드가 있으면 코드, 아니면 이름·별칭 정확 일치. 접두 일치는 R4 의 3곳(원문으로 하위 조직 적용 확인)에만 허용.
3. **olefile 추가 승인**을 받았으나 쓰지 않았다. `scripts/extract_score_params.py` 의 자체 OLE 판독기로 충분했다.
4. **독립 리뷰 정책 예외(사용자 지시)**: S1 은 빌더와 같은 계열인 cmd `z-ai/glm-5.3-flash`, H2·R4 는 hermes(OpenRouter nemotron-3-ultra free)로 리뷰했다. 둘 다 `orca_taskctl.py dispatch` 의 모델 라우터를 거치지 않는 저수준 경로(`orca orchestration dispatch --return-preamble` 후 런처 또는 hermes `-z` 단발 실행)라 자동 승인·감시기가 붙지 않았다. hermes 실행 명령은 Claude Code 자동 모드 분류기가 막아 사용자가 직접 `! orca terminal send ...` 로 실행했다.

---

## 3. 운영 주의 사항

- **`source_commit` 허용치(5커밋)**: 병합 두 번이면 넘는다. `git merge --no-ff --no-commit <브랜치>` 후 `docs/context/CURRENT_STATE.md` 의 `source_commit` 을 병합 직전 main 으로 고쳐 같은 병합 커밋에 넣으면 별도 브랜치 없이 해결된다(R3·P1·S1·H2·R4 에서 사용).
- **워커 워크트리에 없는 자료**: 기관 원문(`.orca/capsules/<task>/external/`, 336MB), `data/sources/qualification/files/`, 등급확인서 샘플, HWP 샘플은 gitignore 라 워크트리에 직접 복사해야 한다. 워크트리를 지우면 함께 사라진다. 이번에 웹 등급확인서 샘플 PDF(27건)와 `sources.csv` 를 그렇게 잃었다.
- **Command Code 크레딧**: 세션 중 플랜 사용량 80%→85%(크레딧 10.7). 다음 세션 cmd 빌더 가용성을 먼저 확인한다.
- **Claude Code 자동 모드 분류기**: 워커 권한을 넓히거나 무승인 에이전트를 띄우는 명령(대화창 일괄 승인 감시, `--yolo` 단발 에이전트 실행, 저수준 dispatch 직후 조회)을 막는다. 막히면 우회하지 말고 사용자에게 실행을 요청한다.

---

## 4. 남은 일

| 항목 | 상태 |
| --- | --- |
| 등급확인서 OCR 잔여 실패 7건 | 샘플 PDF 재수집 후 재측정 필요(X1 문서 잔여 항목) |
| 등급확인서 기능 토글 | `DOCUMENT_EXTRACTION_ENABLED`·`DOCUMENT_OCR_ENABLED` 기본 false. 실물 확인서 Z4 실측 뒤 노출 결정 |
| 한국가스공사 B(30/50/70) | 원문 제16조 용역수행능력 계량화 정도로 정해져 공고 데이터로 판정 불가. None 유지 |
| 기관 정량 배점표 | 기관 세부기준 심사항목 배점한도 미반영(정량점수 직접 입력 필요) |
| 옛 환경부 코드 `1481xxx` | R4 코드 대역(1482) 밖이라 하위 조직 매칭 제외(R4 문서 6절) |
| 메타 안내 문구 | R4 의 하위 조직 확장이 `SERVC_RULE_META_SCOPE_NOTE` 에 아직 반영되지 않음 |
| 과거 공고서 전량 추출(22.7만 건) | B·k 2.32% 라 아직 비권고. 남은 B 미추출 원인은 H2 문서에 분해 |
| partial 5곳·unresolved 3곳 기관 | 조달청 규칙 그대로. 원문 추가 확보 필요 |
| Z4 정식 실측, G2 Windows 실기 | 직전 인수인계와 같다 |

---

## 5. 종료 시 자원

| 자원 | 상태 |
| --- | --- |
| Orca Run 4개 | 전 Task completed, 활성 Dispatch 없음 |
| 워커 터미널 | 전부 회수·종료 |
| 워크트리 | 주 저장소만 남김 |
| Docker | 이번 세션에 올린 `db` 컨테이너를 종료 직전에 내림 |
| 배경 프로세스 | 감시·대기 스크립트 전부 종료 |

---

## 6. 추가 병합 (같은 날 후반, `bfab6d7d` 이후)

빌더는 cmd `deepseek/deepseek-v4.1-flash`, 리뷰어는 사용자 지시로 qwen 경유 OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free`(max). 전부 strict 게이트, 병합 전 전량 시험, 직전 병합 CI 녹색 확인, 병합 커밋 안 `source_commit` 갱신을 거쳤다.

| Task | 병합 | 내용 |
| --- | --- | --- |
| TUI 규칙 | `428dfee9` | 모든 워커를 Orca 터미널의 대화형 TUI 로 실행(`multi_agent_setup.md` 5.3절, 사용자 결정) |
| M1 | `1ca4f189` | 메타 범위 안내에 하위 조직 확장 반영, 환경부 옛 코드 대역 `1481` 포함 |
| B1 | `67b0f3e8` | 과거 공고서 B·k 동시 추출 10→23, 회귀 0 |
| O1 | `98d06541` | 등급확인서 웹 샘플 재수집, 등급 23/23·평가일 19/23, 오추출·오탐 0. 샘플은 주 저장소 `.cache/credit_cert_samples/` 에 보존 |
| N1 | `95baa02a` | Nemotron 3 Ultra(free)를 MODEL_POOL(`qwen-nemotron-ultra-free`, 리뷰어 전용, 자동 배정 금지)과 qwen 런처 허용 목록에 등록 |
| I1 | `42228670` | partial 기관 5곳 미확정 13구간 재수집, 새 확정 0 |
| K1 | `db473092` | 바이너리 HWP 수식 개체 레코드 판독, k 23→24. k 미추출 407건은 첨부에 별표 없음 |
| Q1 | `03199869` | qwen 런처 기본 기동을 `--yolo -i`(대화형)로 |
| S2 | `e1670787` | 추정가격 구간으로 B·k 후보 하나를 고르는 `select_band` |
| C1 | `c7674ebc` | 과거 공고 기준명→규칙 대응 실측. 11/227(4.85%), 2023-05-01 이전 조달청 규칙이 레지스트리에 없어 169건 대응 불가 |

### 6.1 리뷰어 운용

- N1·Q1 이후 Nemotron 리뷰어는 `orca_taskctl.py dispatch --launcher scripts/orca_qwen_launch.py --agent qwen --model nvidia/nemotron-3-ultra-550b-a55b:free` 정규 경로로 뜬다. 단 워커 워크트리가 N1 이전 main 에서 갈라졌으면 그 안의 옛 런처가 모델을 거부하므로, 리뷰어 터미널은 주 저장소 런처를 절대 경로로 실행한다.
- M1·B1·O1·N1(일부)·I1 리뷰는 정규 등록 전이라 저수준 경로(`dispatch --return-preamble` 뒤 고유 이름 preamble 파일 또는 `qwen -i` 직접 실행)였다.
- Orca 코디네이터 터미널은 마지막에 만든 Run 에 묶인다. 이전 Run 의 미처리 배치(`run_7815d8daf16a` 의 K1 리뷰 결과 `delivery_54d5d3ed4302`)는 ack 하지 못했다. 내용은 확인했다.

### 6.2 다음 과업

| 과업 | 상태 |
| --- | --- |
| P2: 2015~2022 조달청 용역 적격심사 별표 개정판 수집 | 진행 중(Run `run_83f128ff89f8`). 끝나면 레지스트리 반영 과업으로 이어진다 |
| 과거 공고서 별표 미첨부 407건 | 첨부 구성 문제. 기준명→규칙 대응(P2 이후)으로 보완 |
| 등급확인서 기능 노출 | 웹 샘플 수준은 확보. 실물 Z4 여부와 토글은 사용자 결정 |
