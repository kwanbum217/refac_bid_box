# 핸드오프 인수인계 - 2026-11-06 세션

> **작성일**: 2026-11-06
> **작성**: 코디네이터(Claude Opus 5.5). Orca Run `run_8734173629f4`
> **기준 커밋**: 작성 시점 `main` 과 `origin/main` 은 `f7b558d8` 입니다. 이 문서는 브랜치 `kwanbum217/handoff-20261106` 에서 병합합니다.
> **상태 문서**: `docs/context/CURRENT_STATE.md` 의 `source_commit` 은 `a6f40cc3` 이며, 이 문서 병합까지 거리 4 로 허용치 5 안입니다. 다음 병합 전에 갱신하십시오.
> **워커 풀**: 빌더 cmd `deepseek/deepseek-v4.1-flash`, 리뷰어 cmd `z-ai/glm-5.3-flash`(사용자 지정). 워커 0대, 남은 워크트리 0개.
> **Docker**: app·db·redis·meilisearch·worker 기동 중. 워커는 `OPENG_RESULT_COLLECTION_ENABLED=true`(로컬 `.env`)로 개찰결과를 정기 적재합니다.

---

## 0. 다음 세션이 바로 할 일

| 우선 | 과제 | 선행 |
| --- | --- | --- |
| 1 | 이 문서 병합 커밋의 main CI 확인(`gh run list --branch main --limit 3`). 직전 `4620e7a8` 은 전 job 통과 | 없음 |
| 2 | 다음 병합 전에 `CURRENT_STATE` `source_commit` 을 그 병합 커밋 안에서 갱신(거리 4) | 없음 |
| 3 | 첨부 판별(결정 3)은 운영 반영까지 끝났습니다. 새 띠 표기 공고가 쌓이면 `uv run python scripts/classify_band_regime.py --max-calls 400 --execute` 로 미판별분을 채웁니다(기본 최근 12개월, CLASSIFIED·NO_ATTACHMENT 는 다시 처리하지 않음) | 없음 |
| 4 | 후속 관찰 두 건은 착수하지 않았습니다(3절) | 사용자 결정 |

---

## 1. 이 세션에서 main 에 넣은 것

| 병합 | 내용 | 검증 |
| --- | --- | --- |
| `35f280b2` | 유찰 목록 막연한 '최근' 표지를 30일 창으로, 감시기 cmd 500 차단 신호, 개찰결과 수집 OTel 지표와 Grafana 대시보드 | 리뷰 3건 pass, 전량 10,137 passed |
| `2c139111` | 결정 1: 전남 예규 제1075호 제11조 조달청 준용 | 전체 판정 비교에서 전남 36건만 전이 |
| `3e26d516` | 결정 3 1단계: 행안부 학술연구 2억미만 1억이상 규칙(격리) | 판정 변화 0건 |
| `bd068701` | 결정 3 2단계: 판별 함수·저장 테이블 `bid_announcement_regime`(운영 적용), 일괄 판별 스크립트, 해석기 `attachment_regime` 인자, G1 기준선 46테이블 | 백업 `snapshot_20261106_022951`, 판정 변화 0건 |
| `4bd4e92b` | 감사 AUT-01(익명 자동화 상태·확인 토큰 노출), SSE-01(스트림 DB 세션), TZ-01(앱 KST) | 리뷰 3건 pass |
| `49bc9b5f` | 원장 재생성, 개찰결과 런북, oauthlib 4.0.1·constraints, 분석 문서 5건, 기관 명세 근거, 개찰결과 수집 플래그 compose 전달 | 전량 10,258 passed |
| `8c6673ff` | F-05 Alertmanager warning 비밀 파일, A1 측정 준비, INPUT·CACHE·POL, A2~A4, ASYNC·RATE | 리뷰 6건 pass |
| `a6f40cc3` | ML 도구 정리(A6·A12·주간 따라잡기), A5, 운영 문서·compose(F-02~F-07·F-10·F-14~F-16·A9·DOC-01), 프런트(F-09·F-11~F-13), 백엔드 잔여(API-01·A10·VAL-01·TEST-01/02·DEBT-01/02) | 리뷰 5건 pass |
| `4620e7a8` | **A1 서빙 금액 특징 교정**과 A7 패리티 시험, A8 폴백 지표, A11 서빙 세대 체크섬, apt CVE-2026-109518 | main CI 전 job 통과 |
| `db19f7f3` | 일괄 판별 upsert 의 MySQL None 컬럼 결함 수정 | 운영 실행으로 확인 |
| `f7b558d8` | F-08 check-all 정렬, 저장된 판별 결과를 해석기 호출부 5곳·원장 경로에 연결, 원장 갱신 | 전체 판정 비교 45건(전부 MOIS_ACADEMIC) |

---

## 2. 운영 데이터 작업

| 작업 | 결과 |
| --- | --- |
| 개찰결과 소급 | 2023-11-04 ~ 2025-11-03 315창 전량 성공(824,441행, 유찰 125,053), 빈 기간 2026-11-04~06 보충. `bid_openg_results` 1,240,698행(유찰 198,725) |
| 개찰결과 정기 수집 | compose 워커 전달 추가 후 로컬 `.env` 로 켬. 2026-11-04 이후 0건이던 적재가 재개 |
| 판별 저장 테이블 | 운영 DB 에 `b4e5f6a7c8d9` 적용(백업 후, 기존 테이블 행 수 불변). G1 기준선 갱신 |
| 첨부 일괄 판별 | 외부 호출 290회, CLASSIFIED 88·NO_ATTACHMENT 11. MOIS_ACADEMIC 65, UNSPECIFIED_SUBTABLE 11, MOIS_OTHER 7, LOCAL 2, PPS 2, UNSPECIFIED 2 |
| 원장 | 최근 12개월 Servc 31,348건 중 차단 9,911(10-19) → 9,856(전남 준용) → 9,811(판별 연결) |

---

## 3. 결정과 판단 기록

| 항목 | 내용 |
| --- | --- |
| 정량평가 결정 1~6 | 1 전남 45건만 준용, 2 시·도 규칙 유지, 3 첨부 판별 설계부터(이후 구현), 4 산림청 미등록·원장 재생성·'계산 차단 응답' 은 B안(항목 닫기), 5 현행 유지, 6 LH·KPS 근거만 추가(상태 unresolved 유지), 전력연구원 조사 종료, 도로공사 2022-10-01판은 원문 제공 대기 |
| A1 | 쌍대 실측(서빙 모델 고정, 금액 특징 기준만 교체) 2025년 4,965건 MAE 1.2112 → 1.2041 (t=-2.70), 2026년 1,985건 1.1988 → 1.1861 (t=-2.60), 구간 폭 쌍대 축소. 사용자 승인으로 적용. 모델 가중치 불변 |
| 판별 연결 범위 | 판정 비교 45건 중 11건은 `LOCAL_SERVICE_TYPE_UNRESOLVED` 에서 풀렸습니다. 2b 사양(규칙 미발견 차단만)보다 넓지만, 첨부가 시·도 별표 대신 행안부 별표를 지정하므로 시·도 세부유형 선택이 의미가 없다고 보고 코디네이터가 수용했습니다 |
| 드리프트 따라잡기 | HEAVY_TASK_NAMES 에 넣지 않고 기존 1시간 등록 유지(시험 이름에 박힌 의도된 값). 1시간 안에서 가드 대기를 소비하는 점은 후속 관찰 |
| A8 정의 변경 | 신규·비활성 기관 폴백을 학습 정의로 맞추면 추천가가 바뀌므로 쌍대 실측 전까지 보류. 이번에는 폴백 사용 지표만 추가 |

---

## 4. 운영 교훈

| 항목 | 내용 |
| --- | --- |
| ORM 일괄 INSERT | 모델 클래스로 만든 MySQL `insert().on_duplicate_key_update` 는 ORM 일괄 경로에서 None 값 컬럼을 빼고, 갱신 절은 `new.<컬럼>` 을 참조해 1054 로 실패합니다. Core 테이블(`Model.__table__`)로 만들고 행 키를 정규화합니다. SQLite 시험은 이를 잡지 못합니다 |
| `build:css` | 저장소 루트 `package.json` 스크립트입니다. 게이트 검증은 `npm ci`, `npm run build:css`, `git diff --exit-code -- src/app/static/css/tailwind.css` 순서입니다 |
| 조사 워커와 상한 | `orca_taskctl.py dispatch` 의 동시 3대 상한은 investigator 역할도 셉니다 |
| cmd 워커 답장 | `orchestration reply` 는 질문 뒤 턴을 끝낸 cmd 워커를 깨우지 못합니다. 같은 내용을 `orca terminal send --enter` 로 넣어야 재개합니다 |
| 통합 브랜치 compose 검증 | 워커 최소 `.env` 로는 `docker compose config` 가 실패합니다. 코디네이터 전용 워크트리에만 검증 동안 전체 `.env` 를 두고 되돌립니다. 운영 compose 는 개발 `.env` 에 운영 비밀값이 없어 main 에서도 해석에 실패하는 기존 성질입니다 |
| 재작업 Capsule 범위 | `orca_taskctl.py rework` 는 원 Capsule 의 쓰기 범위를 그대로 물려받습니다. 사유 문장에서 범위 밖 파일을 허용해도 반영되지 않습니다 |
| Trivy | 공급망 job 의 세 번째 층은 베이스 이미지 OS 패키지입니다. Dockerfile 의 `--only-upgrade` 목록에 패키지를 더하고 이미지를 빌드해 버전을 확인합니다 |

---

## 5. 남은 것

| 항목 | 상태 |
| --- | --- |
| 드리프트 따라잡기 가드 대기 예산 | 관찰. 착수 전 사용자 결정 |
| A8 폴백 정의 학습 일치 | 쌍대 실측 필요. 착수 전 사용자 결정 |
| MOIS_OTHER(행안부 기술·일반용역 1억~2억) 7건 | 규칙 값(B·k·통과점수) 미확인이라 계산하지 않음 |
| UNSPECIFIED_SUBTABLE·UNSPECIFIED 13건 | 첨부에 세부표 지정이 없어 차단 유지 |
| 도로공사 2022-10-01판 원문 | 사용자 제공 대기 |
| 챗봇 v3 점검 세트 등 2026-10-26 결정 대기 항목 | 변동 없음 |
