# 핸드오프 인수인계 — 적격심사 산식 정본화 세션

> **작성일**: 2026-10-01
> **작성**: Hermes 코디네이터 (run_9a021218449f, run_7e3d6efced97)
> **기준 커밋**: `78b217e2` (main)
> **세션 성격**: Orca 병렬 워커 4대 기동 → 검증 → 반려 → 재작업 → 병합. 기동 중 결함 3건을 발견해 전부 수정 후 병합했다.

---

## 1. 이번 세션에서 main 에 병합된 것

| 커밋 | 내용 | 게이트 |
| --- | --- | --- |
| `54506adc` → `8900d43f` | 규칙 레지스트리에 B·k·T·score_table_source 선언, 미확인 경고 경로 | 10대 통과 |
| `cd3f26de` → `7991c72a` | 헤더 로그아웃 폼 CSRF 토큰 결함 수정 | 10대 통과 |
| `c9031789` → `bf8666c4` | 미확정 7건 B·k·T 근거 조사 + 별표 매핑표 (문서 279줄) | 10대 통과 |
| `b996aed5` → `78b217e2` | 정량평가 배점한도 합계에서 신인도를 가감분으로 분리 (7파일 2386줄) | 10대 통과 |

전량 테스트는 5878 → 5899 passed 로 증가했다.

---

## 2. 세션 중 발견해 고친 결함 3건

### 2.1 로그아웃 403 (코디네이터 직접 발견)

`src/app/templates/base.html` 에 로그아웃 폼이 두 개인데 CSRF hidden input이 하나(97번째 줄)에만 있었다. 145번째 줄 폼(헤더 텍스트 버튼)에 없어서 항상 403이 났다. 사이드바 폼은 `hidden lg:block`이라 lg 미만에서 사라지고 헤더 폼은 항상 보여 lg 미만 화면에서만 재현된다.

재현 방법: `POST /accounts/logout/` 에 토큰 없이 → 403, 토큰 포함 → 303.

### 2.2 정량평가 하드코딩 (사용자 질문으로 발견)

화면 상수(실적 30·경영상태 20·근로조건 10·신인도 ±5)가 배점표와 어긋나고, 배점표의 **기술능력 항목이 아예 없었다**. 이 두 오류로 정량 70 + 가격점수 70 = **140점**이 나왔고, 조달청 별표는 어떤 구간도 100을 넘지 않는다.

근본 원인은 입력 구조를 별표별로 다르게 안 만든 것이었다. 근로조건 10점은 별표 2(시설)만 존재하고, 기술능력은 별표마다 구성이 다르다(단일 10 / 폐기물처리 9+1 / 시설 없음).

### 2.3 신인도 합계 산입 (Level 3 검토로 발견)

첫 시도는 **Level 1 게이트 10대 전부 통과**했지만 반려했다. `test_every_band_sums_to_100` 이 하드코딩된 7개 별표만 순회해 별표 6·7·8·9를 검사하지 않았기 때문이다. 제외된 ATTACH_17이 169.25를 내고 있었다.

재작업(`b996aed5`)에서 신인도를 `limit=None`으로 분리하고, 검사 범위를 `QUANT_SCORE_TABLES` 데이터 기반으로 바꿨다. 현재 상태: 고정 합 22건 전부 100 위반 0건, 범위 구간 1건(별표 9).

---

## 3. 남은 Task (다음 세션이 먼저 볼 것)

### `task_c4b1c413d054` — ready 상태, 선행 의존성 해소됨

**미확인 사유 문구 정정 + 4건 B·k·T 세대별 선언**

Capsule: `.orca/capsules/task_c4b1c413d054/capsule.yaml`
작업 브랜치: 새로 만들어야 함. `kwanbum217/orca-quant-table` 은 병합 완료라 정리 대상이다.

해야 할 일 두 가지입니다.

첫째, 코드의 미확인 사유가 "문서 간 불일치"인데 이건 틀렸습니다. `docs/analysis/servc_post_rules_audit_20260929.md:131` 이 "SW(대상)·여객·보험은 개정 후에도 기준값이 바뀌지 않았습니다. ±2%p 일반화가 틀리는 지점" 이라고 기록합니다. 불일치가 아니라 **개정 세대별 정상 차이**라서 세대를 분리하면 확정됩니다. 이 잘못된 문구가 지금 API로 사용자에게 노출되고 있습니다.

둘째, 조사(`c9031789`)가 판정한 4건을 선언합니다.

| rule_id | 별표 | B | k | T |
| --- | --- | --- | --- | --- |
| ATTACH_01 시설 | 별표 2 | 60/70 | 5 단일 | 85 |
| ATTACH_03 여객 | 별표 5 | 60/70 | 4 단일 | 88 |
| ATTACH_04 SW대상 | 별표 3의2 | 60/70 | 4 단일 | 88 |
| ATTACH_05 SW비대상 | 별표 3 | 60/70 | 2/4 | 85 |

일반 띠 3건(ATTACH_12·13·14)은 귀속 자체가 없어 계속 미확인으로 둡니다.

---

## 4. 알려진 공백 (조사 문서에 근거 있음)

| 공백 | 근거 | 처리 |
| --- | --- | --- |
| 일반 띠 3건 별표 귀속 | `servc_pre_rules_2025_2026_tables_20260929.md:299-312` | 미확인 유지 |
| 수리·점검·임대차·수요기관지정형 별표 부재 | `servc_qual_unconfirmed_params_investigation.md` | 신규 별도 과제 |
| 2023-05-01 판 14건 전부 | 제2023-53호 배점표 미조사 | 원문 확보 필요 |
| 기관별·지역별 산식 전무 | `EvaluationRule` 에 해당 축 없음 | 모델 확장 필요 |
| 별표 10·11 → 코드 반영 | 문서 `servc_pre_rules_2025_2026_tables_20260929.md:183-231` | 문서만 있음 |

기관별·지역별 축이 데이터 모델에 없다는 점이 가장 큽니다. `docs/design/g2b_procurement_institution_analysis.md:239-247` 가 이미 지적합니다. 국가계약은 조달청 세부기준, 지방계약은 자치단체 예규(행안부)이고 예비가격 범위도 다릅니다. 하한율만 40%p 차이가 납니다(같은 문서 213행). 코디네이터 실측에서 적격심사 Servc 공고 상위 기관은 서울특별시 956, 충청북도 청주시 434, 서울교통공사 387, 제주특별자치도 343으로 수요기관 자체가 다릅니다. 법령 구분 필드가 DB에 없어 기관명으로 대리해야 합니다.

---

## 5. 조율에서 배운 것 (재발 방지)

**Level 1 게이트는 테스트가 정의한 범위 안에서만 판정한다.** 게이트 10대가 전부 통과했는데 결함이 있었습니다. 하드코딩된 검사 대상 목록처럼 테스트가 자기 범위를 좁게 정의하면 게이트는 그걸 알 수 없습니다. Level 3 코디네이터 전수 계산이 없으면 main 에 들어갑니다.

**워커 보고의 건수는 반드시 재실행으로 대조한다.** `pytest tests/test_evaluation_scoring.py` 를 212 passed로 보고했지만 실제 54였습니다. 게이트 6이 잡아줬지만 지시에서 "추측으로 채우지 말고 다시 돌려 적으라"를 넣어야 합니다.

**Capsule 의 전제가 틀리면 지시 전체가 오염된다.** "문서 간 불일치"라는 제 잘못된 전제가 4건을 불필요하게 미확인으로 만들었고, "합계 100 정합성" 요구에 신인도 처리 구분을 안 적은 탓에 첫 시도가 반려됐습니다.

**cmd 워커는 `--auto`로 띄운다.** `scripts/orca_cmd_launch.py:92-97` 주석이 이미 적고 있습니다. 대화창이 떠서 멈추면 사람이 개입해야 합니다.

**격리 워크트리에서 `evaluation_rules.py` 를 두 Task 가 동시에 잡으면 안 된다.** 파일 충돌이 병합 시점에 발생합니다. `--deps`로 직렬화하십시오.

---

## 6. 인프라 상태

Docker 데몬은 기동 중이고 컨테이너 5대가 healthy였습니다(앱·MySQL·Redis·Meilisearch·워커). 이번 세션 말미에 내려줄 예정입니다.

재기동 명령: `make up` (또는 `docker compose up --build -d`), 기동 확인: `curl http://localhost:8000/api/v1/health/ready`.

확인할 URL: `http://localhost:8000` (로그인 필요), `http://localhost:8000/docs` (Swagger 57개 엔드포인트), `http://localhost:8000/api/v1/evaluations/rules` (배점표 규칙 메타).

`.env` 는 격리 워크트리마다 복사해야 합니다. Git 미추적이라 따라오지 않고, `Settings()` 가 `SECRET_KEY` 를 필수로 검증하므로 없으면 설정 읽기가 전부 실패합니다.

---

## 7. 정리 대상 자원

| 대상 | 상태 | 조치 |
| --- | --- | --- |
| `orca-quant-table` 워크트리 | 병합 완료 | `orca worktree rm` 후 브랜치 정리 |
| `orca-unconfirmed` 워크트리 | 병합 완료 | `orca worktree rm` 후 브랜치 정리 |
| `kwanbum217/servc-formula-handoff` 브랜치 | 미확인 | `git log --oneline main..<branch>` 확인 후 판단 |
| Orca Run `run_9a021218449f` | Task 전부 completed | 종료 가능 |
| Orca Run `run_7e3d6efced97` | `task_c4b1c413d054` 만 ready | 세션 유지 |

완료 Task 의 워커 터미널은 모두 회수했고 `orca_settled_session_audit.py` 통과를 확인했습니다.

---

## 8. 다음 세션 시작 시 첫 순서

```bash
cd /Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box
git log --oneline -3
make up                                    # 인프라 기동
curl -s http://localhost:8000/api/v1/health/ready

# task_c4b1c413d054 Dispatch (새 워크트리 필요)
orca worktree create --name orca-reason-fix \
  --repo "path:/Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box" \
  --base-branch main --setup skip
# .env 복사 → 터미널 생성(--auto) → prepare-worker → dispatch
```

첫 확인은 브라우저에서 정량평가 입력란입니다. 하드코딩 값이 사라지고 별표 선언값이 자동 채움되며, 미확정 항목은 사유와 함께 차단됩니다. 지금 화면에서 넣던 63점 같은 값은 같은 의미로 유지되지 않으며, 그게 이번 작업의 목적입니다.
