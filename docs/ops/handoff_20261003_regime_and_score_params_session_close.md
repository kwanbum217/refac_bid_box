# 핸드오프 인수인계 — 기관축·지방계약 판별·배점표 확정 세션

> **작성일**: 2026-10-03
> **작성**: Claude 코디네이터 (run_7e3d6efced97)
> **기준 커밋**: `8c8f3f8a` (main, origin 동기화. 이 문서는 그 다음 병합으로 들어감)
> **직전 인수인계**: [handoff_20261002_servc_axis_session_close.md](handoff_20261002_servc_axis_session_close.md)

---

## 0. 다음 세션이 가장 먼저 할 일

**컴퓨터 종료를 위해 Docker 를 전부 내렸습니다. worker 도 내려가 있습니다.** 2026-09-26 사용자 결정(개발 환경 worker 상시 가동, 용역 주간 재학습 유지)에 따라 다음 세션은 시작하자마자 worker 까지 올려야 합니다. worker 가 내려가 있는 동안 공고·낙찰 수집, 01:30 수요기관 증분 수집, 04:00 드리프트 감시, 월요일 03:00 주간 재학습이 모두 멈춥니다.

```bash
cd /Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box
open -a Docker                      # Docker Desktop 기동, docker info 가 성공할 때까지 대기
docker compose up -d                # db·redis·meilisearch·worker 전부(app 은 필요할 때)
docker compose ps                   # worker 가 Up 인지 확인
docker compose logs worker --tail 50   # 기동 직후 따라잡기 수집 로그 확인
```

01:30 수요기관 증분 수집(`collect_demand_institutions_task`)은 **아직 한 번도 실행 결과를 확인하지 못했습니다.** worker 를 올린 뒤 다음 01:30 이후 아래로 확인하십시오.

```bash
docker compose logs worker | grep -i "demand\|수요기관" | tail -20
uv run python scripts/db_readonly_query.py --sql "SELECT COUNT(*) n, MAX(fetched_at) last FROM g2b_demand_institutions"
```

정상이면 `fetched_at` 이 그날 01:30 이후로 갱신됩니다. 키가 비면 실패가 아니라 '건너뜀' 으로 기록되므로 로그에서 건너뜀 여부를 꼭 보십시오.

---

## 1. 이번 세션에서 main 에 병합된 것

| 병합 | 내용 | 검증 |
| --- | --- | --- |
| `e813798b` | 용역 지방계약 판별 원천 조사 문서 | strict, 조사 워커 |
| `a41fe8dd` | 적격심사 규칙 기관·지역·계약법령 축, 스냅샷 판정 문맥 nullable 5컬럼(리비전 `a2c7e9f1b4d6`, 운영 DB 적용) | 리뷰 pass, strict |
| `e5abfbe0` | 현황판 source_commit 갱신 | strict |
| `d0532f1e` | CI Tailwind 재현성, Python 취약 전이 의존성 4개 상향 | strict |
| `81de7718` | 프런트엔드 npm audit(brace-expansion) | strict |
| `cf40cf25` | 런타임 이미지 Trivy(openssl·pcre2·perl-base) | strict, 로컬 Trivy |
| `37e9cf3f` | 조달청 수요기관 정보 수집(`g2b_demand_institutions`, 리비전 `bd7c2e9a104f`, 102,244건 적재)과 지방계약 판별 | 리뷰 pass, strict |
| `a37c8835` | compose 가 `G2B_USRINFO_SERVICE_KEY` 를 app·worker 에 전달 | strict |
| `3860566e` | 제2023-53호 판 T 선언 | strict |
| `5a83c55d` | 제2023-53호 ATTACH_06 B=70 | strict |
| `69b65277` | 제2023-53호 원문 확보, B·k A 등급 확정 | strict |
| `892657c8` | B·k 금액 구간 선택 설계 | strict |
| `071e2d89` | B·k 금액 구간 선택 구현 | 리뷰 pass, strict |
| `8c8f3f8a` | 지방계약 판별 결과 화면 표시(상세 머리말 배지, 분석 응답·결과 범위 줄), 리뷰 비차단 주석 2건 | 리뷰 pass, strict |

main CI 는 2026-09-30 부터 공급망 job 이 실패하던 것을 이번 세션에 해소해 12개 job 전부 통과 상태입니다(`a37c8835` 이후).

---

## 2. 운영 DB 와 환경 변경

| 항목 | 내용 | 백업 |
| --- | --- | --- |
| 리비전 `a2c7e9f1b4d6` | `bid_evaluation_snapshots` nullable 5컬럼 | `data/backups/pre_a2c7e9f1b4d6_bid_evaluation_snapshots_20261002.sql` |
| 리비전 `bd7c2e9a104f` | 새 테이블 `g2b_demand_institutions` 102,244건 | `data/backups/pre_bd7c2e9a104f_alembic_version_20261002.sql` |
| G1 스키마 기준선 | 두 리비전 반영해 재생성 | 커밋됨 |
| `.env` | `G2B_USRINFO_SERVICE_KEY` 추가(조달청_나라장터 사용자정보 서비스 일반 인증키) | 값은 문서에 쓰지 않음 |

---

## 3. 확정된 사실 (재조사 불필요)

### 3.1 지방계약 판별

- 계약방법명에 '지방' 이 들어간 공고는 운영 데이터에 0건이었다. 판별 원천은 조달청 수요기관 정보의 소관구분(`jrsdctnDivNm`)과 기관유형이다.
- 매핑: LOCAL = 교육청 계열·지방자치단체·지방공기업·공립 초중고·특수·유치원, NATIONAL = 국가기관·공기업·준정부기관·정부투자기관, 그 밖 None. 근거와 반례는 `docs/analysis/demand_institution_regime_mapping_20261002.md`.
- 2025년 이후 용역 공고 기준 LOCAL 47.4%, NATIONAL 22.8%, None 29.8%. LOCAL 은 복수예가 ±3%.
- 수요기관 API 는 코드 단건 조회가 안 되고 1년 구간만 허용하며 초당 요청 제한(429, returnReasonCode 23)이 있다. 수집기는 0.2초 간격과 지수 백오프를 쓴다.

### 3.2 배점표 B·k·T

- 제2023-53호 원문: 국가법령정보센터 `admRulSeq=2100000220190`. 별표 1~9 수식이 대비표 복원값과 전부 일치해 A 등급. 출처·해시는 `docs/analysis/servc_2023_53_original_attachments_20261003.md`.
- 2023 판 14건 선언은 같은 구조의 2025-09-01 판과 같다.
- 축 조건부 B(5억원 미만 70/이상 60)·k(고시금액 미만 4/이상 2)는 낙찰방법명 구간 표기 → 추정가격(`presmpt_prce` 만, 기초금액 대체 없음) 순으로 고른다. 충돌 시 낙찰방법명 우선과 경고.
- 고시금액(기획재정부 공식): 2023~2024 2.2억원, 2025~2026 2.3억원. 단일 정본 `src/ml/notice_amount.py`.
- 여전히 미확정: 별표 9(ATTACH_17) B(수요기관 지정 60~70), 일반 띠 ATTACH_12·13·14(별표 귀속 미확인).

---

## 4. 남은 일과 제안

| 우선 | 항목 | 비고 |
| --- | --- | --- |
| 1 | worker 기동과 01:30 수요기관 증분 수집 첫 실행 확인 | 0절 |
| 2 | 지방계약 미상 29.8% 축소 | 기타기관·기타공공기관·지자체 출자출연기관, 국립 학교·대학은 소분류 오염으로 None. 기관 코드 체계(행정표준코드) 대조로 일부 확정 가능성 |
| 3 | 2027년 고시금액 | 2026-12 기획재정부 고시 후 `src/ml/notice_amount.py` 갱신 필요(2027 은 지금 기본값 2.2억) |
| 4 | 정량평가 배점표 5억 구간 선택의 기초금액 대체 | B·k 선택은 대체하지 않기로 했으나 정량평가 경로(`_bid_estimated_price`)는 대체를 쓴다. 두 경로 일관성 결정 필요 |
| 5 | Orca Task `task_3ea4489c1e90` 상태 | worker_done 이 예상 실패 수 표기 차이로 failed 로 남았으나 산출물은 후속 Task `task_9f2b9a6f8725` 와 함께 병합됨. 상태만 남은 것 |

---

## 5. 이번 세션 조율 함정 (메모리에도 기록)

- `| tail` 파이프 뒤에 `&& git push` 를 이으면 검증 실패가 푸시를 막지 못한다. 병합 세 번이면 source_commit 허용치 5를 넘는다. 병합 커밋에 source_commit 갱신을 함께 넣는다.
- CI 공급망 job 은 pip-audit → npm audit → Trivy 순이라 앞 실패가 뒤를 가린다. 로컬에서 세 층을 한 번에 재현한다.
- 워커가 `.orca/capsules/.../worker_done.json` 을 `git add -f` 로 커밋하면 게이트 7 이 실패한다. Capsule forbidden 에 명시하고, 발생하면 같은 터미널에 정정 Task 를 넣는다(코디네이터가 워커 기록을 직접 고치지 않는다).
- 자동 생성 Capsule 은 `required_change` 잘림, 디렉터리 항목, 접힘 문자열 질문 '>' 결함이 반복됐다. 매번 손으로 다시 썼다.
- Capsule 을 파이썬 치환으로 고칠 때 같은 문자열이 다른 목록에 먼저 있으면 엉뚱한 곳에 들어간다. YAML 로 다시 읽어 `allowed_write_files` 포함 여부를 단언한다.

---

## 6. 종료 시점 상태

- main 은 `8c8f3f8a` 다음의 이 문서 병합 커밋이며 origin 과 동기화, 작업 브랜치 0, 워크트리는 주 저장소 하나.
- `8c8f3f8a` 병합 결과 전량 시험 6,017 passed / 31 skipped / 3 deselected, 규칙 검증 21/21.
- Orca 완료 세션 잔류 0.
- Docker 컨테이너 전부 정지(Redis 는 `SHUTDOWN NOSAVE`), Docker Desktop 종료.
