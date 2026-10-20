# 핸드오프 인수인계 — 재발주 조회 인덱스, 충남 별표 2·3·4, 회원정보 수정, 보안 검토 후속 전량, 등급확인서 PDF 자동 입력

> **작성일**: 2026-10-11
> **작성**: Claude 코디네이터 (Orca Run `run_38d15a53246a`)
> **기준 커밋**: `6edc8dd3` (이 문서가 들어가는 최종 병합의 부모)
> **직전 인수인계**: [handoff_20261009_mypage_detail_latency_close.md](handoff_20261009_mypage_detail_latency_close.md)

---

## 0. 다음 세션이 가장 먼저 할 일

| 우선 | 과제 | 선행 |
| --- | --- | --- |
| 1 | 이 문서가 들어간 최종 병합 커밋의 CI 가 원격 `main` 에서 녹색인지 확인 | 없음 |
| 2 | 1절 운영 주의 사항 중 사용자 조치 항목(1.9 GitHub 비공개 취약점 제보 활성화)을 사용자에게 확인 | 사용자 |
| 3 | 로그인 상태로 마이페이지(정보 수정·모든 기기 로그아웃), 공고 상세, 챗봇 답변, 대시보드를 브라우저에서 열어 CSP 위반 콘솔 오류가 없는지 확인 | 스택 기동, 계정 비밀번호(사용자) |
| 4 | 같은 로그인 상태로 마이페이지 정보 수정 화면에서 등급확인서 자동 채우기를 브라우저로 확인(1.12). 토글을 켜야 보인다 | 3번과 같음 |
| 5 | 다른 클론·머신에서 이 `main` 을 받았으면 1.13 의 Chroma 백업 tar 복원 명령 실행 | 해당 클론 |
| 6 | 6절 잔여 항목의 처리 여부를 사용자에게 받기 | 사용자 결정 |

---

## 1. 운영 주의 사항 (반드시 읽을 것)

이번 세션의 변경으로 배포·운영 절차가 바뀐 지점이다. 하나라도 빠뜨리면 서비스가 뜨지 않거나 기능이 조용히 막힌다.

### 1.1 모델 무결성 manifest (M4, `48b6ac0c`)

- 서빙 모델 디렉터리마다 `artifact_manifest.json`(sha256)이 있어야 한다. 이 파일은 **머신별 산출물이라 `.gitignore` 대상**이고 git 으로 배포되지 않는다.
- **manifest 가 없으면 `ENVIRONMENT=production`·`staging` 에서 모델 로드를 거부한다.** development 는 경고 후 로드한다. manifest 가 있는데 해시가 다르면 환경과 무관하게 거부한다.
- 새 머신, 운영 서버, 모델 파일을 손으로 교체·복원한 뒤에는 **앱 기동 전에** 반드시 실행한다.

  ```bash
  uv run python scripts/write_model_manifests.py
  ```

- 승격·롤백(`src/ml/promotion.py`)은 서빙 공개 전에 manifest 를 자동으로 쓴다. **확인하지 않은 것**: 데이터 자산 import(`scripts/import_data_assets.py`)와 모델 번들 동기화(`scripts/sync_model_files.py`)가 manifest 를 쓰는지는 확인하지 않았다. 그 경로로 모델을 바꿨으면 위 스크립트를 다시 실행한다.
- 운영 Compose 는 `./data` 를 읽기 전용으로 마운트하므로 manifest 는 컨테이너 밖(호스트)에서 만들어야 한다.
- 이 맥은 2026-10-11 에 manifest 5개(파일 19개)를 생성했다. v25·ssh_hist_premium·v13_hybrid 는 2026-08 G1 기준선(`data/backups/data_assets_checksums.json`)과 해시가 같고, quantum_leap_v25_pro 는 2026-08-06 재학습 승격 커밋(`73dd49f3`)으로 다르다(정상).
- **한계**: manifest 에 서명이 없다. 모델 디렉터리에 쓸 수 있는 공격자가 모델과 manifest 를 함께 바꾸면 막지 못한다. 막으려면 서명 또는 별도 저장소의 해시 대조가 필요하다(6절).

### 1.2 새 의존성 defusedxml (L9, T3)

- `defusedxml==0.7.1` 이 `uv.lock` 에 추가됐다. 다른 머신은 `uv sync --frozen`, Docker 는 **app·worker 이미지를 다시 빌드**해야 한다(`docker compose up -d --build app worker`). 재시작만 하면 수집기 import 가 실패한다. 이 맥은 재빌드 완료.

### 1.3 staging 설정 fail-closed (M3, S3)

- `ENVIRONMENT=staging` 도 예제 `SECRET_KEY`, `DEBUG=true`, 기본 DB 비밀번호를 거부하고 시동하지 않는다. 기존 staging `.env` 가 예제 값을 쓰면 기동이 멈춘다.
- `.env` 는 실행 위치가 아니라 프로젝트 루트(`src/app/core/config.py` 의 `PROJECT_ROOT`)에서 읽는다.

### 1.4 CSP 헤더 (U1, `fe350d3d`)

- 앱이 HTML 응답마다 요청별 nonce 로 `Content-Security-Policy` 를 단다(`src/app/core/csp.py`). `/docs`·`/redoc` 은 제외.
- **템플릿 규칙**: 새 인라인 `<script>` 는 `nonce="{{ csp_nonce }}"` 필수. `onclick=` 같은 인라인 이벤트 속성과 `javascript:` URL 은 금지(정적 JS 의 `addEventListener` 로). `tests/test_csp_nonce.py` 가 막는다.
- 새 외부 도메인(이미지·스크립트·API)을 쓰려면 `csp.py` 정책을 고쳐야 한다. 현재 외부 허용은 `img-src https://upload.wikimedia.org` 하나뿐이다.
- HEAD 요청 응답에는 CSP 헤더가 붙지 않는 것을 관찰했다(GET 은 붙음). 영향은 없지만 헤더 검사 도구가 HEAD 를 쓰면 누락으로 보인다.
- 브라우저 실측은 비로그인 화면(로그인·가입)만 했다. 로그인 화면들은 0절 3번에서 확인한다.

### 1.5 API 출처 검사 (L4, T2)

- 세션 쿠키가 실린 `/api/v1` 의 POST·PUT·PATCH·DELETE 는 Origin(없으면 Referer)이 같은 출처이거나 `CORS_ALLOWED_ORIGINS` 에 있어야 한다. 아니면 403.
- 프런트를 다른 도메인에서 서빙하게 되면 그 출처를 `CORS_ALLOWED_ORIGINS` 에 넣어야 한다. Origin·Referer 가 둘 다 없는 비브라우저 요청과 워커 콜백은 통과한다.

### 1.6 권한·요청 제한 변화 (H1·M6, S1)

- 채팅의 자동화 실행·확인과 REST `/automation/job/{id}/confirm`·`/cancel` 은 **staff 또는 superuser 전용**이다. 일반 회원은 채팅으로 수집·재색인·재학습을 실행할 수 없다(의도된 변경).
- 로그인 사용자 API 요청 제한은 60초 120회(`src/app/core/security.py` 상수)다. 예측을 몰아 부르는 사용자는 429 를 받을 수 있다.

### 1.7 인증·세션 변화 (L1·L2·L3·L11, S2·T1·V1)

- 비밀번호 최대 4,096자. 옛 반복 수 해시는 다음 로그인 때 자동 재해시된다(점진 전환).
- 세션은 유휴 7일 또는 절대 14일에 만료된다.
- 모든 기기 로그아웃(`POST /accounts/mypage/logout-all/`)은 세션 저장소의 사용자별 세대 번호(`auth:user_epoch:<user_id>`, TTL 없음)로 동작한다. **Redis 데이터가 지워지면(FLUSH, 볼륨 삭제) 세대가 0 으로 돌아가 이미 무효화한 세션이 되살아날 수 있다.** Redis 는 `SHUTDOWN NOSAVE` 대신 정상 저장 종료를 쓰고, 볼륨을 지우지 않는다.
- 운영 Redis 는 `--maxmemory 512mb` 다. 이전 정책 `allkeys-lru` 에서는 **메모리 압박만으로도** TTL 없는 세대 키가 축출돼 같은 부활이 생길 수 있었다. 2026-10-11 에 `docker-compose.prod.yml` 을 `volatile-lru` 로 바꿨다(사용자 결정). 이제 TTL 없는 키는 축출되지 않는다. 대신 TTL 있는 키(캐시·세션)가 먼저 축출되고, TTL 있는 키가 하나도 없는데 메모리가 차면 쓰기가 OOM 오류로 실패한다. **운영 Redis 는 컨테이너를 다시 만들어야 새 정책이 적용된다**(`docker compose -f docker-compose.prod.yml up -d redis`). 적용 뒤 `redis-cli CONFIG GET maxmemory-policy` 로 확인한다. 개발 `docker-compose.yml` 의 Redis 정책은 바꾸지 않았다.
- TTL 없는 키를 새로 만드는 기능(예: 업로드 원본 보관)을 추가할 때는 반드시 TTL 을 건다. 그렇지 않으면 축출되지 않고 메모리를 채운다.
- CSRF 쿠키는 development 외 환경에서 Secure 다. HTTP 로 운영하면 SSR 폼이 403 이 된다(운영은 HTTPS 전제).

### 1.8 CI 변화 (L12·L13)

- CI 에 `gitleaks git`(전체 이력 스캔)이 추가됐고 checkout 이 전체 이력을 받는다. 이력 어디에든 비밀값처럼 보이는 문자열을 새로 커밋하면 CI 가 실패한다. 오탐은 `.gitleaks.toml` 에 사유와 함께 허용한다.
- 워크플로 기본 토큰 권한은 `contents: read` 다. 쓰기가 필요한 새 잡은 잡 단위 `permissions` 를 줘야 한다.

### 1.9 공개 저장소 문서 (L14, V3) — 사용자 조치 필요

- `SECURITY.md` 는 GitHub 의 비공개 취약점 제보(Security 탭의 Report a vulnerability)로 안내한다. **이 기능은 저장소 소유자가 Settings > Code security 에서 Private vulnerability reporting 을 켜야 동작한다.** 켜졌는지 확인하지 않았다.
- LICENSE 는 All rights reserved(사전 서면 허락 없는 복제·배포 금지)다.
- Chroma 백업 tar 는 추적만 해제했다. **git 이력에는 남아 있어 공개 저장소에서 여전히 내려받을 수 있다.** 이력 재작성은 하지 않았다(사용자 결정).
- 워커 로그 꼬리 34개는 추적 유지, `/Users/kwanbum` 경로만 `~/` 로 치환했다. 문서(docs/)의 로컬 절대 경로는 그대로다.

### 1.10 데이터·규칙

- 운영 DB alembic head 는 `a6b7c8d9e0f1`(재발주 이력 커버링 인덱스)이다. 다른 DB 는 `alembic upgrade head` 가 필요하다.
- 충남 별표 2·3·4 의 고시금액 경계 230,000,000 은 2026년 값이다. 고시금액이 바뀌면 `tests/test_local_regime_rules_wave2.py` 가 실패하도록 고정했으니, 그때 구간 상한을 갱신한다.
- vendor 정적 파일을 바꾸면 해당 `SOURCE.txt` 의 SHA-256 도 같이 바꿔야 `tests/test_vendor_integrity.py` 가 통과한다.

### 1.11 재시작 규칙

- app 컨테이너는 코드 변경을 자동 반영하지 않는다(uvicorn --reload 없음). 병합 뒤 `docker compose restart app`, 의존성 변경 뒤에는 `--build`.

### 1.12 등급확인서 PDF 자동 입력 (W1 `6edc8dd3`, W2 `2c64a701`)

- 마이페이지 정보 수정 화면에서 신용평가등급확인서 **텍스트 PDF** 를 올리면 `POST /api/v1/documents/extract` 가 신용평가등급·평가일을 추출해 입력칸을 미리 채운다. 저장·제출은 사용자가 직접 한다. 신뢰도 low 이거나 등급 코드 목록에 없는 값은 채우지 않고 근거만 보여 준다.
- **기능 토글 `DOCUMENT_EXTRACTION_ENABLED` 기본값은 false 다.** 꺼져 있으면 API 는 404, 화면에는 업로드 블록이 나오지 않는다.
- **켜는 법**: `.env` 에 `DOCUMENT_EXTRACTION_ENABLED=true` 를 넣고 `docker compose up -d app`(운영은 `-f docker-compose.prod.yml`). 컨테이너는 `.env` 파일을 직접 읽지 않고 compose 의 `environment` 목록만 받는다. 이 세션 최종 병합에서 두 compose 의 app 서비스에 이 변수 전달을 추가했다. 그 전 compose 로는 `.env` 에 넣어도 꺼진 채로 남는다. 켠 뒤 `docker exec refac_bid_box-app-1 printenv DOCUMENT_EXTRACTION_ENABLED` 로 확인한다.
- **새 의존성**: `pdfplumber 0.11.x` 와 전이 의존성 `pdfminer-six`·`pypdfium2`(사용자 승인 범위). 다른 머신은 `uv sync --frozen`, Docker 는 `docker compose up -d --build app worker`. 재시작만 하면 문서 추출 라우터 import 가 실패해 **앱이 뜨지 않는다**. 이 맥은 재빌드 완료. PyMuPDF(AGPL)는 금지.
- **원본 미저장**: 업로드 파일은 요청 안에서 메모리(`io.BytesIO`)로만 처리하고 디스크·Redis·DB 에 남기지 않는다. 로그에는 크기·소요 시간·상태만 남는다. 이 성질을 깨는 변경(원본 보관, 비동기 큐 처리)은 개인정보 고지(`terms_content.html`)와 함께 바꿔야 한다.
- **제한**: 본문 5MB, 10쪽, 처리 10초, 암호화 PDF 거부. 요청 제한은 사용자 시간당 10회, IP 시간당 30회(`src/app/core/security.py` 상수, 키 `api:ratelimit:document_extraction:*`, TTL 3600초). 형식 오류 요청도 한도를 1회 소모한다(계약에 순서 규정 없음, 리뷰에서 결함 아님으로 판정).
- **범위**: 텍스트 PDF 만. 스캔본(이미지 PDF)은 `unrecognized` 로 돌려주고 직접 입력을 안내한다. OCR 은 후속(6절). LLM·외부 API·클라우드 OCR 은 쓰지 않는다(정규식 파서, `src/app/services/document_extraction/credit_certificate.py`).
- **파서 한계**: 합성 문서로만 시험했다. 실제 신용평가사 확인서 양식(표 배치, 기업어음·회사채 등급 병기)에서의 적중률은 실측하지 않았다. 공개 저장소라 실제 확인서를 시험 픽스처로 커밋하면 안 된다. 실물 검증은 로컬에서만 하고 결과 수치만 남긴다.
- 출처 검사(1.5)가 자동 적용된다. 다른 도메인에서 프런트를 서빙하면 `CORS_ALLOWED_ORIGINS` 가 필요하다.

### 1.13 다른 클론의 Chroma 백업 tar 복원 (V3)

- V3 가 `data/backups/chroma_db_before_rebuild_20260731_204932.tar.gz` 의 **추적을 해제**했다. 추적 해제 커밋을 병합·pull 하면 git 이 그 파일을 **작업 트리에서 실제로 삭제한다.** 이 맥은 병합 직후 복원했다(835,335바이트, ignore 대상).
- 이 `main` 을 pull 한 다른 클론·머신에서는 다음으로 복원한다.

  ```bash
  git show 22a3ccb6:data/backups/chroma_db_before_rebuild_20260731_204932.tar.gz > data/backups/chroma_db_before_rebuild_20260731_204932.tar.gz
  git check-ignore data/backups/chroma_db_before_rebuild_20260731_204932.tar.gz
  ```

---

## 2. 이 세션에서 병합한 것

빌더는 cmd `deepseek/deepseek-v4.1-flash`(effort high, 위험도 high 는 max), 리뷰어는 opencode `muse-spark-1.3-contributor-free` 다. 전부 `--no-ff` 병합, 원격 반영, strict 게이트 증거와 병합 전 전량 시험 증거를 거쳤다.

| 차수 | Task | 병합 | 내용 | 검증 |
| --- | --- | --- | --- | --- |
| 인수인계 | N1 재발주 이력 인덱스 | `9e543d6e` | `ix_bid_results_repeat_hist`, 마이그레이션 `a6b7c8d9e0f1`, G1 기준선 | 리뷰 pass, 운영 적용 20초 |
| 인수인계 | N2 충남 별표 2·3·4 | `a8c3504c` | ATTACH_02(SW)·03(WASTE)·04(LAND_TRANSPORT) 3구간 | 리뷰 pass |
| 인수인계 | N3 회원정보 수정 | `19992761` | `/accounts/mypage/edit/` | 리뷰 pass(반례 5종) |
| 보안 High·Medium | S3 설정·헬스·검색·CI | `724eb9ca` | M3, M5, L6, L13, `.env` 경로 | 리뷰 pass |
| 보안 High·Medium | S2 XSS·인증 경계 | `5c592bf8` | H2(renderer), M1, M2, L1, L3, L5 | 리뷰 pass, 펜스 보완은 코디네이터 |
| 보안 High·Medium | S1 채팅 자동화 staff | `fe6126c7` | H1, M6 | 리뷰 pass(반례 7종) |
| 보안 Low | T2 API 출처 검사 | `0034b9e4` | L4, L10 | 리뷰 pass(반례 12종) |
| 보안 Low | T1 인증·세션 | `7873de70` | L2, L11 유휴 만료 | 리뷰 pass(반례 30건) |
| 보안 Low | T3 스크립트·CI·XML | `e9559d7e` | L7, L8, L9, L12, L16 안내 | 리뷰 pass |
| 잔여 | U1 CSP nonce | `fe350d3d` | 요청별 nonce CSP, 인라인 이벤트 11곳 이전 | 리뷰 pass, 브라우저 실측 |
| 잔여 | U3 오류 마스킹 | `4c5805d0` | 작업 결과 예외 원문 마스킹, 수집 엔드포인트 비차단 | 리뷰 pass |
| 잔여 | V2 vendor 감사 | `f221ba96` | vendor SOURCE.txt·SHA-256 고정 시험 | 리뷰 pass(28/28) |
| 잔여 | U2 모델 무결성 | `48b6ac0c` | manifest 검증, print → logger | 1차 리뷰 fail → 재작업 → 재리뷰 pass |
| 잔여 | V1 모든 기기 로그아웃 | `22a3ccb6` | 세션 세대 번호 | 리뷰 pass(반례 9종) |
| 잔여 | V3 저장소 정리 | `dadc6420` | tar 추적 해제, 경로 치환, LICENSE, SECURITY.md, Redis volatile-lru | 리뷰 pass |
| PDF 자동 입력 | W2 화면 | `2c64a701` | 정보 수정 화면 업로드 블록, `doc-autofill.js`, 이용약관 고지 | 리뷰 pass |
| PDF 자동 입력 | W1 API | `6edc8dd3` | `POST /api/v1/documents/extract`, pdfplumber, 전용 요청 제한기, 토글 | 리뷰 pass(반례 33항), 전량 7,139 통과 |
| PDF 자동 입력 | 코디네이터 | 이 문서와 같은 병합 | 두 compose 의 app 에 토글 전달, 인수인계, 현황판 `source_commit` | `docker compose config` |

---

## 3. 실측과 판정

### 3.1 predict-price 지연

원인은 `src/ml/repeat_history.py` `lookup_repeat_history` 였다(기관+업무구분 최대 5,000행, `bid_ntce_nm` 본문 랜덤 조회). 처음 여는 공고 기준 적용 전 0.1~29.5초, 적용 후 11~36ms(24건, 중앙값 16ms). 인덱스 생성 직후라 완전한 콜드 값은 아니다.

### 3.2 Grok 보안 검토 보고서

기준 커밋 `dc843e89`. High 2건과 Medium 대부분을 코드로 확인했고 수치 오차는 두 곳(print 8곳, escapejs U+2028)뿐이었다.

### 3.3 vendor 감사(V2)

npm audit 결과 bootstrap·chartjs·daisyui·fontawesome·jquery·marked 는 취약점 없음. tailwindcss 는 high 5·moderate 2 지만 **빌드 도구 의존성 취약점이고 `vendor/tailwindcss/3.4.16/tailwindcss.js` 는 어떤 템플릿·JS 도 참조하지 않는 미사용 파일**이다. 그 디렉터리 표기는 3.4.16 이지만 내용은 3.4.17 이다. bootstrap·daisyui·fontawesome 3개 파일은 원본보다 후행 개행 1바이트가 많다.

### 3.4 PDF 자동 입력 통합 확인 (개발 스택, 2026-10-11)

토글을 셸 변수로만 켜서(`.env` 미변경) app 을 재기동해 확인했다. 시험용 합성 PDF 만 썼다.

| 확인 | 결과 |
| --- | --- |
| 컨테이너 안 추출 서비스(재빌드 이미지의 pdfplumber) | 한국어 합성 확인서에서 등급 `AA-`·평가일 `2026-03-15`, 둘 다 high, 1.9ms |
| 실행 중 서버 HTTP | 비로그인 POST 401, OpenAPI 경로 56개에 등록, `doc-autofill.js` 200, 정보 수정 화면 비로그인 303 로그인 이동 |
| 실제 앱·Redis, 인증만 가짜 사용자로 대체 | 200 계약 JSON 일치, 415·400·413 거부, 11번째 요청 429, 제한 키 2개 TTL 3600. 시험 키는 삭제 |
| 토글 켜진 정보 수정 화면 렌더링(실제 회원 1명으로 GET 만) | 200, CSP 헤더, 업로드 블록·고지 문구 표시, 인라인 이벤트 0, nonce 없는 인라인 스크립트 0 |
| 브라우저에서 PDF 선택 후 자동 채우기 | **미수행**(계정 비밀번호 필요, 0절 4번) |

영문 문구(`Credit Grade AA-`)는 파서 대상이 아니라 `unrecognized` 가 나온다. 파서는 한국어 표기(`신용등급`, `평가등급`, `평가일`, `평가일자`, `발급일`)를 찾는다.

---

## 4. 이 세션의 절차 함정

| 함정 | 처리 |
| --- | --- |
| 셸 `&` 로 띄운 `check --wait` 를 죽이면 서버에 대기자가 남아 새 `--wait` 가 `waiter_exists` 로 거부 | 30초 간격 즉시 조회 루프를 추적되는 배경 작업으로 |
| 즉시 조회 `check` 는 `--types` 를 무시하고 heartbeat 배치도 돌려준다 | heartbeat·status 만 든 배치는 자동 ack |
| `release-worker` 성공 후에도 런처 창이 남아 다음 Dispatch 가 `settled_session_lingering` 으로 거부 | `terminal show` 로 tabId 확인 후 창 단위 close |
| 워크트리의 마지막 워커 창을 닫으면 Orca 가 빈 `Terminal 1` 을 다시 연다 | 종료 전 `orca terminal list` 로 확인해 닫는다 |
| 코디네이터 Capsule 기본 체크리스트(`scope_expanded`)와 리뷰 id 불일치로 strict 게이트 5 실패 | 리뷰 체크리스트 id 를 빌더와 같게 쓰거나 코디네이터 Capsule 체크리스트를 리뷰 Capsule 것으로 교체 |
| 리뷰 Intent 의 이스케이프 큰따옴표가 확장 후 YAML 을 깨뜨림 | `how` 에 큰따옴표를 쓰지 않는다 |
| 게이트 6 이 빌더 보고서 시험 문구의 경위 서술("1차 1 failed")을 실패로 읽고, note 600자 초과를 위반으로 잡는다 | 빌더 Intent 에 "시험 결과 문구는 최종 결과만" 을 넣는다. 이미 회수했으면 코디네이터 Capsule 로 strict 판정 |
| 한 세션 병합 다섯 건 초과 시 현황판 `source_commit` 허용치 초과 | 병합 직전 코디네이터 브랜치에 main 반영 후 갱신을 묶는다 |
| 리뷰 fail 은 같은 Task 에 재작업을 태우지 않는다 | `orca_taskctl.py rework` 로 새 Task, 같은 브랜치에 새 커밋, 새 리뷰어로 재리뷰 |
| `orca worktree rm` 은 비동기이고 브랜치도 함께 지운다 | 몇 초 뒤 재확인, `branch not found` 는 정상 |
| U2 병합 뒤 워크트리 정리를 빠뜨렸다 | 병합 직후 그 Task 의 워크트리·브랜치를 바로 정리 |
| 확인용 서버 정리에 `lsof -ti tcp:8001` 로 잡힌 PID 를 그대로 kill 해 puppeteer Chrome 을 종료했다 | PID 의 명령을 먼저 확인한다 |
| opencode 리뷰어 터미널을 런처로 만든 뒤 `--launcher` 없이 dispatch 하면 `inject_rejected`(에이전트 미탐지). 런처가 `.orca/preamble.txt` 를 기다리는 중이다 | `orca_taskctl.py dispatch` 에 `--launcher scripts/orca_opencode_launch.py --repo <주 저장소> --worktree path:<워크트리> --agent opencode --model ... --allow-unverified-delivery` 를 준다 |
| 새 설정 토글을 `config.py`·`.env.example` 에만 넣으면 Docker 에서는 켤 수 없다(컨테이너는 `.env` 미포함, compose `environment` 만 받음) | 새 토글은 두 compose 의 해당 서비스 `environment` 에도 넣는다. 빌더 Intent 의 허용 파일에 compose 를 포함한다 |
| 컨테이너에 `docker cp` 로 넣은 파일은 root 소유라 앱 사용자로 `rm` 이 거부된다 | `docker exec -u root ... rm -f` |

---

## 5. 종료 시 자원

| 자원 | 상태 |
| --- | --- |
| Orca Run `run_38d15a53246a` | 이번 세션 Task 전부 `completed`, 워커 창 전부 닫음, 상시 감시기 종료 |
| 워크트리 | 주 저장소만 남김(W1·W2 워크트리·브랜치 정리). 세션 이전부터 있던 브랜치 4개는 손대지 않음 |
| 운영 DB | alembic head `a6b7c8d9e0f1` |
| 모델 | 이 맥 `data/model_files` 에 manifest 5개 생성 |
| Docker | **사용자 요청으로 컴퓨터 종료 전 개발 스택 전부 정지**(`docker compose stop`, 볼륨 유지). app·worker 이미지는 defusedxml·pdfplumber 반영 재빌드 상태. 다음 시동은 `docker compose up -d`. 토글은 기본값(false)으로 뜬다 |
| 배경 프로세스 | 코디네이터 대기 루프·감시기 전부 종료 |

---

## 6. 하지 않은 것과 사용자 결정 대기

| 항목 | 상태 |
| --- | --- |
| manifest 서명(1.1 한계) | 미착수. 서명 키 보관 방식 결정 필요 |
| 세대 번호 영속화(1.7 한계) | 미착수. Redis 데이터 소실 시 무효 세션 부활 가능 |
| 미사용 `vendor/tailwindcss/3.4.16/tailwindcss.js` 삭제 | 미착수. 삭제하면 SOURCE.txt·무결성 시험도 같이 정리 |
| Chroma 백업 tar 의 git 이력 제거 | 하지 않음(사용자 결정: 추적 해제만) |
| docs 의 로컬 절대 경로 | 그대로 둠(사용자 결정) |
| M7 자동 승인 감시기 샌드박스 | 미착수(개발 도구, 범위 제외) |
| 품질 4(nosec 272개 재점검), 6(에이전트 설정 4벌 미러), 9(uv 없는 설치용 constraints) | 미착수 |
| `retrain_task.py`·`worker.py` 의 예외 원문 기록 | U3 범위 밖이라 남음 |
| 충남 별표 3 두 번째 표(생활폐기물 참고 예시) | 등록하지 않음 |
| 로그인 화면 브라우저 확인 | 계정 비밀번호가 필요해 미수행(0절 3번·4번) |
| 스캔본 등급확인서 OCR | 후속. 로컬 OCR(rapidocr·onnxruntime 등) 의존성 승인 필요. 클라우드 OCR 은 금지 |
| 재무제표 PDF 자동 입력(지시서 B안) | 제품 결정 필요. 지시서가 참조한 `financial_ocr_plan.md` 는 저장소 어디에도 없다 |
| 실제 확인서 양식 적중률 실측 | 미수행. 로컬에서만, 결과 수치만 기록(1.12) |
| 운영 Redis 컨테이너 재생성(volatile-lru 적용) | 운영 서버에서 1.7 명령 실행 필요 |
| GitHub Private vulnerability reporting 활성화 | 사용자 조치(1.9) |
