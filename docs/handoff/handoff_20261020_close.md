# 핸드오프 인수인계 — 외부 감사 보고서 보완, 규칙 레지스트리 분리, 인수인계 보관, HWP 추출기 결함

> **작성일**: 2026-10-20
> **작성**: Claude 코디네이터 (Orca Run `run_d913e6ff3d23`)
> **기준 커밋**: `3ff3b71b` (이 문서가 들어가는 병합의 부모)
> **직전 인수인계**: [handoff_20261019_close.md](handoff_20261019_close.md)
> **범위**: Grok 감사 보고서(`refac_bid_box_gap_review.md`, 기준 `4d971598`) 검증과 보완, 그 과정에서 드러난 HWP 추출기 결함 수정과 후속 대조.

---

## 0. 다음 세션이 가장 먼저 할 일

| 우선 | 과제 | 선행 |
| --- | --- | --- |
| 1 | Docker 재기동(`docker compose up -d`) 뒤 컨테이너 5개 healthy 확인, 8절 마지막 병합들의 main CI 녹색 확인 | 없음 |
| 2 | **H 재기동**: 4절 원문 19개의 통과점수 인용처 전수 대조(조사 문서 하나). 결과 목록으로 과거 문서·규칙 출처 정정 Task 를 따로 만든다 | 없음 |
| 3 | 한국농어촌공사(6건)·한국공항공사 제777호 이전판(11건) 구판 규칙 등록. 원문과 시행 구간은 [inst_regime_remaining_20261020.md](../analysis/inst_regime_remaining_20261020.md) 에 확보됨. 등록 뒤 31,305건 판정 비교 필수 | 사용자 결정 |
| 4 | 직전 문서 0절 2·3·5번(`LOCAL_RULE_NOT_FOUND` 조달청 준용, 공고명 미표기 건설폐기물, 띠 표기·2027 고시금액)은 그대로 결정 대기 | 사용자 결정 |
| 5 | chromadb 취약점 예외 3건 만료(2026-12-31) 전 재판단 | 외부(상류 수정) |

---

## 1. 세션 요약

Grok 감사 보고서의 지적을 코드로 하나씩 검증한 뒤 실결함만 고쳤다. 보고서 기준 커밋이 당시 HEAD 와 같아 지적은 모두 유효한 시점의 것이었다.

| 보고서 항목 | 판정 | 조치 |
| --- | --- | --- |
| H1 aiohttp 3.14.3 취약점 3건 | 실재(CI 명령으로 재현) | 3.14.5 로 상향, `constraints.txt` 동기화 |
| M1 `evaluation_rules.py` 10,007줄 | 실재 | 사용자 결정 (가)안: 시·도·기관 모듈 분리, 판정 비교 차이 0 |
| M2 B·k·T 상한 없음, 하한율 미상 시 0 계산 | 실재 | 적격심사·예측 요청 모두 ≤100, 미상이면 최저 투찰금액 null + 경고 |
| L1 세션 선택 시험 mtime 의존 | 실재 | 시각 명시 |
| L1 coverage·훅 미설치 시험 실패 | 감사 환경 문제 | 조치 없음 |
| L2 compose 기본 비밀번호 | 운영 compose 는 필수 지정 | 조치 없음 |
| L3 문서 추출 동시성 프로세스별 | 기본 프로세스 1개라 실위험 작음 | 조치 없음 |
| 문서: CURRENT_STATE "14종만", README 기능 누락 | 실재 | 갱신 |
| 문서: DOCUMENT_* 운영 문서 부재 | 오지적(`docs/ops/environment_variables.md` 에 있음) | 조치 없음 |
| 문서: 인수인계 109개 누적 | 실재 | 사용자 결정: 30일 보관 + 위치 통일 + 검증기 검사 |

---

## 2. 병합

| main 커밋 | 내용 | 검증 |
| --- | --- | --- |
| `f0274da5` | aiohttp 3.14.5·yarl 1.25.1, `constraints.txt`, cmd MiniMax M3.1 Flash 무료 빌더 풀 등록, 세션 선택 시험 mtime 고정 | pip-audit 0건(chromadb 예외 3), 전량 8,096 |
| `df18e1d9` | CURRENT_STATE `institution_formula_absence` → `rule_coverage`, `price_score_verification` 범위 문구, README 주요 기능·규칙 범위·활성화 설정 | 리뷰 pass, 7,990자 |
| `35e39086` | 적격심사 입력 B·k·T `le=100`, 지방계약·수기심사 경로 하한율 미상 시 최저 투찰금액·하한율·가격보완 null + `낙찰하한율 미상` 경고 | 리뷰가 두 경로 5종 입력에서 500 없음 재현, 전량 8,105 |
| `78818f80` | predict-price 요청 B·k·T·Q `le=100`, `compute_price_bounds` 하한율 `Decimal \| None` | 리뷰 pass, 전량 8,099 |
| `eabcbf35` | 한국농어촌공사 20251001판·한국공항공사 10차판 원문 확보 조사 | 재리뷰 pass(레코드 순번 17곳 대조) |
| `7e5735ce` | 인수인계 128건 `docs/archive/handoff/YYYY-MM/` 보관, 51건 `docs/handoff/` 통일, 검증기 22번째 검사 `인수인계 문서 위치` | 리뷰 pass, rename 155·경로 외 변경 0, 전량 8,120 |
| `0251a2fe` | `evaluation_rules.py` 10,007줄 → 4,646줄. `evaluation_rules_core.py`(184), `_local.py`(2,177), `_institution.py`(3,160) 분리, 재수출로 import 경로 유지 | 지문 10종·이름 312개 동일, 이동 외 변경 0, **31,397건 판정 키 차이 0** |
| `3ff3b71b` | HWP 평문(flat)을 레코드 단위 문단으로 생성(`_hwp_section_flat`) | 원문 193개 비교: 가격 상한·k 변화 0, 통과점수 새로 읽힘 19개 |

---

## 3. HWP 추출기 결함 (중요)

`scripts/extract_score_params.py` 의 바이너리 HWP flat 이 본문 스트림을 통째로 UTF-16LE 디코딩해, 홀수 크기 레코드 뒤 문단이 1바이트씩 어긋나 사라졌다. 같은 결함을 알고 만든 `_hwp_record_text` 가 커밋 `f7d177df` 에서 계산식 행에만 연결되고 flat 에는 연결되지 않았다. rows 에도 본문 조문은 들어가지 않는다.

| 경과 | 판단 |
| --- | --- |
| D 빌더 | 한국농어촌공사 원문 제10조 통과점수를 인용(사실이었음) |
| D 리뷰어·코디네이터 | flat 에 '85점' 0회 → 허위 인용으로 오판 |
| D 재작업 워커 | 레코드 직접 파싱으로 반증해 question 으로 제기(`escalate_when` 사실 불일치 조항이 작동) |
| 코디네이터 | 독립 파서와 원 바이트 UTF-16 검색으로 재확인 후 정정 |

`3ff3b71b` 로 고쳤다. 고치기 전 판정은 과거 조사에서 '통과점수 원문 미인쇄' 오판을 낳았을 수 있어 H 로 전수 대조했다(4절).

---

## 4. H: 통과점수 원문 인용처 전수 대조

HWP 추출기 수정(`3ff3b71b`) 전에는 '통과점수' 를 읽지 못했고 수정 뒤에는 읽히는 원문이 19개다. 과거 조사 문서와 규칙 출처 문자열 중 이 원문을 근거로 '통과점수 원문 미인쇄, 공고문 인용' 으로 적은 곳이 있을 수 있다. 예: [inst_predecessor_attach_20261019.md](../analysis/inst_predecessor_attach_20261019.md) 는 한국공항공사 통과점수를 '첨부에 문구 없음, 공고문 인용' 으로 적었으나 `kac_3553810_file1.bin` 에서 85점이 읽힌다.

**상태: 미완료, 다음 세션 0절 2번.** H 빌더(`task_b97554ffd749`)를 띄웠으나 사용자 지시로 세션 종료를 위해 조사 도중 중단했다(커밋 0, 미커밋 0, Task 는 사유와 함께 failed 기록).

대상 원문 19개(코디네이터가 원문 캐시 193개를 수정 전후 추출기로 비교해 얻음. kac777 전문 두 경로는 같은 파일):

| 원문(주 저장소 `.cache/` 기준) | sha256 앞 16자 | 바이트 | 수정 후 T |
| --- | --- | ---: | ---: |
| `.cache/inst_candidates/add/입찰공고문_R26BK01767428.hwp` | `2d440250ff402c14` | 99,840 | 88 |
| `.cache/inst_candidates/bpa/R26BK01768734_f2.hwp` | `3a98e8c20a3f46bc` | 86,016 | 85 |
| `.cache/inst_candidates/khs/입찰공고서_R26BK01706896.hwp` | `9d2b42871fb9176e` | 70,656 | 88 |
| `.cache/inst_candidates/koem/입찰공고서_R26BK01723384.hwp` | `1c54616d1bb41d57` | 105,984 | 95 |
| `.cache/inst_candidates/koem/해양폐기물정화용역_적격심사_세부기준_20250306.hwp` | `77d90d9434d1c043` | 130,560 | 95 |
| `.cache/inst_candidates/nhis/R26BK01766450_f3.hwp` | `a53e23610a870eab` | 236,032 | 85 |
| `.cache/inst_regime_20261020/kac/kac777_일반용역_적격심사세부기준_전문_260227.hwp` | `763cf4912b0e322b` | 221,696 | 85 |
| `.cache/inst_regime_20261020/krc/KRC_일반용역_적격심사세부기준_20220105.hwp` | `7ca61faa8ac65e1e` | 225,280 | 85 |
| `.cache/inst_regime_20261020/krc/KRC_일반용역_적격심사세부기준_20230901.hwp` | `1c5c6a8c9afa2b73` | 476,672 | 85 |
| `.cache/inst_regime_20261020/krc/KRC_일반용역_적격심사세부기준_20251001.hwp` | `2da8cfdcc90e3985` | 244,224 | 85 |
| `.cache/inst_regime_20261020/krc/KRC_일반용역_적격심사세부기준_20260624.hwp` | `47bd22d690136e47` | 249,344 | 85 |
| `.cache/predecessor_20261019/incheon_inst/raw/incheon_3061300_attach1.bin` | `c3b2610483e6d185` | 117,760 | 95 |
| `.cache/predecessor_20261019/incheon_inst/raw/incheon_3061306_attach1.bin` | `ed0ed1ae0a694bc1` | 113,664 | 95 |
| `.cache/predecessor_20261019/incheon_inst/raw/kac_3553810_file1.bin` | `1157b860e85725b0` | 222,208 | 85 |
| `.cache/predecessor_20261019/inst_attach/R25BK01101479/seq1_ord000.bin` | `e2597f6828156844` | 396,288 | 85 |
| `.cache/predecessor_20261019/inst_attach/R25BK01166116/seq3_ord000.bin` | `ca0ffcddcfed8bbe` | 1,458,176 | 88 |
| `.cache/predecessor_20261019/inst_attach/R25BK01223455/seq3_ord000.bin` | `f540bc6b3a5131db` | 5,685,248 | 85 |
| `.cache/predecessor_20261019/inst_attach/R26BK01514656/seq1_ord000.bin` | `3ca7dee221f263ef` | 916,480 | 85 |
| `.cache/predecessor_20261019/kac_777/kac_777_full.hwp` | `763cf4912b0e322b` | 221,696 | 85 |

입찰공고서·공고문에서 읽힌 T 는 여전히 '공고문 근거' 이므로, 파일마다 세부기준 원문인지 공고서인지 구분해 판정한다. 가격 상한·k 값이 바뀐 원문은 0개다.

**재기동**: 빌더 Intent `.orca/intents/hwp_threshold_reaudit_20261020.yaml`, 리뷰 Intent `.orca/intents/hwp_threshold_reaudit_review_20261020.yaml`(로컬, gitignore). 새 워크트리에 위 19개 파일을 같은 상대 경로로 복사한 뒤 띄운다. Intent 가 없으면 이 표와 3절로 다시 쓴다. 산출물은 `docs/analysis/hwp_threshold_reaudit_20261020.md` 하나이고, 기존 문서·규칙 정정은 그 목록을 보고 별도 Task 로 한다.

---

## 5. 판단 기록

- **M1 분리 방식**: `evaluation_rules.py` 에서 재수출해 `from src.app.services.evaluation_rules import X` 312개 이름을 모두 유지했다. 선택 로직은 원 모듈에 남아 monkeypatch 대상이 그대로다. 순환 import 는 `evaluation_rules_core.py` 로 공통 자료형을 빼서 풀었다.
- **하한율 미상 처리**: 0 으로 대체하지 않고 None 으로 둔다. 점수 역산만 하고(`CALCULATED_SCORE_RATE`) 최저 투찰금액·가격보완은 null 이다. 차단 응답 세 곳에 남은 `assert effective_lwlt_rate is not None` 은 사용자 입력 규칙이 `AGENCY_DOCUMENT_NOT_LOADED` 고정이라 구조적으로 닿지 않는다.
- **인수인계 위치**: 새 인수인계는 `docs/handoff/` 에만 쓴다. 30일이 지나면 `docs/archive/handoff/YYYY-MM/` 로 옮긴다. 검증기가 그 밖의 위치를 막는다.
- **과거 기록 수치 불변**: 검증기 검사 수가 22로 늘었어도 과거 분석 문서의 '21/21' 실행 기록은 고치지 않는다.

---

## 6. 운영 교훈

| 교훈 | 내용 |
| --- | --- |
| HWP 조문 대조는 레코드로 | flat·rows 로 '없음' 을 판정하지 않는다. `_ole_streams` + `_hwp_records` 의 PARA_TEXT 순번이나 원 바이트 UTF-16 검색으로 본다 |
| 워커 stash 는 워크트리 간 공유 | E·F 가 main 기준값을 재려고 각자 stash 해 한 스택에 섞였다. 기준값은 코디네이터가 미리 계산해 박고 stash·체크아웃 금지를 Intent 에 넣는다. 발견 시 `refs/backup/` 고정 |
| 사양 문구가 게이트 실패를 만든다 | 이번 Level 1 실패 3건(D 검증 명령 허용 목록 밖, F changed_files 옛 경로, E 보고 문자열 'failed 0')은 모두 코디네이터 사양 문구가 원인. 셋 다 `coordinator-capsule` 로 strict 증거를 남겼다 |
| "숫자를 맞춰라" 는 과거 기록을 위조한다 | F 가 과거 분석 문서 36곳의 '21/21' 을 '22/22' 로 바꾸다가 커밋 전에 정정됐다. 범위를 '현재 동작을 설명하는 문서' 로 못박는다 |
| 증거 파일은 하나 | strict·premerge 증거가 주 저장소 파일 하나라 병렬 기록이 서로 덮는다. 병합 직전에 증거 커밋과 브랜치 HEAD 를 대조한다 |
| cmd 무료 모델의 내장 웹 검색 | 유료 크레딧이 없으면 400 으로 실패한다. 워커는 셸 조회로 넘어간다 |

---

## 7. 워커 풀

빌더 cmd `minimax/minimax-m3.1-flash:free` `--effort max`(이번 세션 등록, 계열 minimax), 리뷰어 cmd `reflection/beam:free` `--effort max`. 기동은 정책 배치 뒤 `cmd --model … --effort max --trust --yolo` TUI, `orca orchestration worker-start --task <id> --terminal <h> --worktree path:<wt>`. `worker-start --terminal` 은 상시 감시기를 붙이지 않으므로 보고 파일·정체 신호에서 종료하는 배경 감시를 따로 붙였다. TUI 가 뜨기 전에 `worker-start` 하면 빈 결과가 오므로 화면에서 `models:` 줄을 확인한 뒤 Dispatch 한다.

---

## 8. 종료 상태

| 항목 | 상태 |
| --- | --- |
| Orca Run | `run_d913e6ff3d23`. 빌더·리뷰 Task 는 completed, D 1차 리뷰는 fail 판정 뒤 재작업·재리뷰 pass, H 는 중단(failed, 사유 기록) |
| 워커 | 터미널·워크트리 전부 회수·제거. 남은 창은 코디네이터뿐 |
| 저장소 | main 이 origin/main 과 같다. 오늘 작업 브랜치는 병합 뒤 모두 삭제 |
| 원문 캐시 | 한국농어촌공사·한국공항공사 원문 13개를 주 저장소 `.cache/inst_regime_20261020/` 로 회수 |
| stash 백업 | `refs/backup/stash-*` 두 개는 E·F 병합 뒤 삭제 |
| 배경 프로세스 | 코디네이터 감시 스크립트 전부 종료 |
| Docker | 컴퓨터 종료를 위해 전부 정지(`docker compose down`, 볼륨 유지) |
