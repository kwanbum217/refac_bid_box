# 핸드오프 인수인계 — Z·Q 차수(manifest 서명, 세션 세대 DB 영속화, 감시기 경로 제한, 스캔본 OCR, 기관 산식 재조사)와 CI 회귀 2건

> **작성일**: 2026-10-12
> **작성**: Claude 코디네이터 (Orca Run `run_75c43ef48072`)
> **기준 커밋**: `fc0da032` (이 문서가 들어가는 최종 병합의 부모)
> **직전 인수인계**: [handoff_20261012_grok_residual_close.md](handoff_20261012_grok_residual_close.md) (같은 날 X·Y 차수)

---

## 0. 다음 세션이 가장 먼저 할 일

| 우선 | 과제 | 선행 |
| --- | --- | --- |
| 1 | 이 문서가 들어간 최종 병합 커밋의 CI 가 원격 `main` 에서 녹색인지 확인(이 세션에서 CI 전용 회귀가 두 번 있었다, 4절) | 없음 |
| 2 | Docker 는 정지 상태다. 다음 시동은 `docker compose up -d`. app·worker 이미지는 OCR 의존성 반영 재빌드 상태다(6절) | 없음 |
| 3 | 운영 서버에 Z1 서명 키와 Z2 마이그레이션을 적용(1.1, 1.2) | 운영 서버 접근(사용자) |
| 4 | 직전 인수인계 0절의 사용자 조치(비공개 취약점 제보 활성화, 로그인 화면 브라우저 확인)는 그대로 남아 있다 | 사용자 |

---

## 1. 운영 주의 사항

### 1.1 모델 manifest HMAC 서명 (Z1, `a9310e9c`)

- `artifact_manifest.json` 에 `signature`(hmac-sha256)가 들어간다. 키는 `MODEL_MANIFEST_SIGNING_KEY`(compose 두 파일의 app·worker 에 전달).
- **production·staging 은 키가 없거나 manifest 에 서명이 없으면 모델 로드를 거부한다.** 운영 서버에서는 앱 기동 전에 다음을 반드시 한다.

  ```bash
  python -c "import secrets; print(secrets.token_hex(32))"   # 서버에서 새 키 생성, .env 에 MODEL_MANIFEST_SIGNING_KEY=<값>
  uv run python scripts/write_model_manifests.py              # 서명된 manifest 재작성
  ```

- 키를 바꾸면 manifest 를 다시 써야 한다. 승격·롤백·모델 들여오기(`import_data_assets.py`, `sync_model_files.py import`)는 manifest 를 자동으로 다시 쓴다(X1).
- 이 맥은 2026-10-12 에 `.env` 에 키를 생성해 넣고 manifest 5개(파일 19개)를 서명해 다시 썼다. 검증 경로로 19개 파일 통과를 확인했다. 키 값은 어디에도 출력·기록하지 않았다.
- development 는 키나 서명이 없으면 경고 후 해시 검증만 한다. 서명이 있는데 틀리면 환경과 무관하게 거부한다.

### 1.2 세션 세대 번호 DB 영속화 (Z2, `fc0da032`)

- 모든 기기 로그아웃의 세대 번호 정본이 새 테이블 `accounts_session_generation`(user_id PK·FK CASCADE)이다. Redis `auth:user_epoch:<id>` 는 TTL 30일 캐시다. Redis 를 비워도 다음 요청에서 DB 값으로 복원되어 무효화한 세션이 되살아나지 않는다(직전 인수인계 1.7 의 한계 해소).
- 마이그레이션 `b7c8d9e0f1a2`. **이 맥 운영 DB 는 2026-10-12 적용 완료**(적용 전 백업 `data/backups/snapshots/snapshot_20261011_225021`, 2.27GB). 다른 DB 는 `alembic upgrade head` 가 필요하다. G1 기준선(`data/backups/schema_signature_baseline.json`)은 적용 후 재생성했다(새 테이블 추가만, 기존 테이블 무변경).
- 캐시 정합성: 미스 경로는 `SET NX` 로만 채우고, 증가 경로는 캐시 삭제 → DB 원자 증가 → `setex` 순서다. 코디네이터 Level 3 에서 찾은 경쟁 조건 2건을 재작업으로 고쳤다(4절).
- DB 조회 실패 시에는 경고 후 세대 0 으로 처리한다(fail-open, 계약상 허용). 그 동안 캐시도 비어 있으면 무효화한 세션이 일시적으로 통과할 수 있다.

### 1.3 자동 승인 감시기 경로 제한 (Z3, `8097cd95`)

- 개발 도구 `scripts/orca_auto_approve.py` 가 작업 트리 밖 경로(`~`, 절대 경로, `..`, 링크 우회, 경로 인자의 셸 변수 확장)를 쓰는 명령을 보류한다. 임시 디렉터리는 허용한다. 워커가 작업 트리 밖을 읽으려 하면 이제 사람 승인을 기다린다.

### 1.4 스캔본 등급확인서 OCR (Q1, 이 문서와 같은 병합)

- 텍스트 PDF 에서 등급을 못 찾으면 앞쪽 최대 3쪽을 메모리에서 렌더링해 rapidocr(onnxruntime)로 읽는다. OCR 결과 confidence 는 최대 medium. 10초 제한 유지.
- 토글 `DOCUMENT_OCR_ENABLED` 기본 false(compose 두 파일 app 에 전달). `DOCUMENT_EXTRACTION_ENABLED` 도 켜져 있어야 한다.
- **한글 인식 모델은 런타임에 내려받지 않는다.** `scripts/fetch_ocr_models.py` 가 고정 URL·sha256 으로 Docker 빌드 단계에서 `/opt/ocr_models` 에 넣는다. 개발 맥에서 OCR 을 쓰려면 `uv run python scripts/fetch_ocr_models.py` 를 한 번 실행한다(`data/ocr_models`, gitignore). 모델이 없거나 해시가 다르면 OCR 만 꺼지고 경고가 남는다.
- 새 의존성: rapidocr 3.10.0, opencv-python-headless, pyclipper, shapely, omegaconf, colorlog(사용자 승인 2026-10-12). 다른 머신은 `uv sync --frozen`, Docker 는 `docker compose up -d --build app worker`. `constraints.txt` 도 재생성됐다.
- 합성 한글 스캔 실측: 1쪽 1.35초(콜드, 모델 적재 포함), 3쪽 0.87초(웜). 실제 신용평가사 확인서 적중률은 여전히 미실측(Z4, 5절).

### 1.5 시험이 `.env` 를 읽는다

- `tests/test_model_integrity.py` 는 키가 없다고 가정했는데, 이 맥 `.env` 에 서명 키를 넣자 실패했다. autouse fixture 로 키를 비우게 고쳤다(`575221dc`). 다른 시험도 `settings` 를 `.env` 에서 읽으므로 `.env` 에 새 값을 넣은 뒤에는 전량 시험을 다시 돌린다.

---

## 2. 이 세션(Z·Q 차수)에서 병합한 것

빌더는 cmd `deepseek/deepseek-v4.1-flash`(위험도 high 는 effort max, medium 은 high), 리뷰어는 Antigravity `gemini-3.8-flash-medium` 이다. 전부 `--no-ff`, strict 게이트 증거와 병합 전 전량 시험 증거를 거쳤다.

| Task | 병합 | 내용 | 검증 |
| --- | --- | --- | --- |
| Z1 manifest 서명 | `a9310e9c` | HMAC-SHA256 서명, 환경별 규칙, compose 전달 | 리뷰 pass(위조·변조 반례), 전량 7,169 |
| Windows 경로 회귀 수정 | `e5843c93` | Y1 정규화가 Windows 에서 `/app/x` 를 `D:\app\x` 로 바꾼 것 수정(`path.root`) | CI Windows 녹색 |
| Z3 감시기 경로 제한 | `8097cd95` | 작업 트리 밖 경로·변수 확장 보류 | Level 3 반례로 재작업 1회, 리뷰 pass, 전량 7,202 |
| Q2 기관 산식 재조사 | `9b90ffd8` | 수자원공사·도로공사 미확정 9행 보고서 `docs/analysis/institution_formula_unresolved_20261012.md` | 리뷰 pass(Decimal 재계산), 코디네이터 해시 재대조 |
| CI 커버리지·시험 격리 | `e7741d12` | Z3 새 시험을 ci.yml 개별 커버리지 목록에 추가, 무결성 시험 키 격리 | 전량 7,237 |
| Z2 세션 세대 DB | `fc0da032` | 새 테이블·마이그레이션, DB 정본·Redis 캐시, 운영 적용, G1 기준선 | Level 3 결함 2건 재작업, 리뷰 pass(경쟁 순서 4종 재현) |
| Q1 스캔본 OCR | 이 문서와 같은 병합 | OCR 경로, 빌드 시 모델 고정 다운로드, 토글 | 리뷰 pass(네트워크 차단·파일 미잔존 실측) |

### 2.1 Q2 조사 결론

9행 모두 여전히 미확정이다(확정 0/9). 재계산값이 인쇄 점수와 0.010~0.025점씩 어긋나고 소수점 조항으로도 맞지 않으며, 계수 생략 2행의 k 는 원문 어디에도 없다. 원문 출처 중 기관 공식 경로는 수자원공사 38차뿐이고 40차·39차·도로공사는 제3자 게시물이다. 코디네이터가 URL 을 다시 내려받아 38차 PDF·40차 첨부는 sha256 일치, 39차·도로공사는 게시글 페이지 URL 이라 재대조 불가를 확인했다. 확정하려면 기관 질의회신이나 평탄 점수가 인쇄된 공고 첨부 평가표가 필요하다. 코드 반영은 없다.

### 2.2 경북 하한율

직전 인수인계 계열의 "경북 5~10억 85.495 오류 의심" 은 이미 `9bdae2c8`(2026-10-06)에서 원문 역산값(87.745/87.745/86.745/86.745)으로 반영돼 있었다. 할 일 없음.

---

## 3. 실측과 판정

- Z 차수 빌더 3건 중 2건(Z2, Z3)을 코디네이터 Level 3 반례로 반려했다. 둘 다 리뷰어 이전에 코디네이터가 직접 돌린 반례에서 드러났다(Z3 `cat $HOME/.netrc` 승인, Z2 캐시 미스-증가 경쟁으로 30일 세션 부활).
- 리뷰어는 Z2 의 남은 좁은 창(읽기 요청의 NX 채움 직후 증가 쪽 `setex` 가 Redis 장애로 실패)을 Redis 장애 전제의 극단 상황으로 판정했다.

---

## 4. 이 세션의 절차 함정

| 함정 | 처리 |
| --- | --- |
| 병합 직후 CI 를 확인하지 않고 다음 병합을 진행해 Windows 회귀(Y1)와 커버리지 회귀(Z3)를 각각 한 병합 뒤에야 발견 | 병합마다 CI 결론을 확인한 뒤 다음 병합. `scripts/orca_*` 를 고치는 Intent 에는 새 시험 파일의 ci.yml 개별 커버리지 목록 추가를 넣는다 |
| Level 1 게이트·premerge 전량 시험은 CI 의 파일별 커버리지 단계와 Windows 경로 의미를 재현하지 않는다 | Windows 의미는 `PureWindowsPath` 로, 커버리지는 ci.yml 단계를 로컬에서 그대로 실행해 확인 |
| `.env` 에 새 값을 넣자 `.env` 를 읽는 시험이 로컬에서만 실패해 병합 훅이 막음 | 시험 쪽에서 설정을 monkeypatch 로 고정 |
| 병합 3회 이상이면 현황판 `source_commit` 허용치(5) 초과로 규칙 검증 실패 | 푸시 전 로컬 병합 커밋을 `reset --merge HEAD~1` 로 되돌리고 `--no-commit` 병합 안에서 갱신(amend 금지) |
| 병합 훅이 실패 증거로 병합 커밋을 막으면 MERGE_HEAD 가 남는다 | `git merge --abort` 후 원인 수정 |
| opencode muse 무료 리뷰어 한도 초과, Antigravity 신뢰 대화창, Intent 이름 Capsule 경로 | 직전 인수인계 4절과 같다. Z·Q 리뷰어는 처음부터 Antigravity 로 띄우고 두 Capsule 경로를 모두 복사, 신뢰 대화창은 Dispatch 직후 Enter |
| 범위 밖 시험 수정을 승인하면 게이트 2·6 이 빌더 Capsule 기준으로 실패 | 빌더 위 코디네이터 브랜치 + 범위를 넓힌 coordinator-capsule 로 strict 판정 |
| 운영 DB 백업(mysqldump 2.27GB)이 10분 넘게 걸려 도구 시간 상한을 넘김 | 배경 작업으로 두고 완료 알림을 기다린다 |

---

## 5. 하지 않은 것과 사용자 결정 대기

| 항목 | 상태 |
| --- | --- |
| Z4 등급확인서 실측 적중률 | 실물 PDF 미제공으로 미착수. 로컬에서만 실측하고 수치만 기록, PDF 커밋 금지 |
| G2 Windows 실기 검증 | 보류. Windows 에서 Orca 서버를 띄워 페어링하면 원격 워커(`--on <환경>`)로 재현 가능. 저장된 원격 환경 0개 |
| 운영 서버 Z1 키·Z2 마이그레이션 적용 | 운영 서버 접근 필요(1.1, 1.2) |
| 기관 산식 미확정 9행 | 기관 질의회신 또는 평가표 첨부 공고 확보 필요(2.1) |
| M7 감시기 샌드박스(컨테이너 격리) | 경로 제한(Z3)만 했고 샌드박스는 미착수 |
| 재무제표 PDF 자동 입력, chromadb 1.x | 직전 인수인계와 같다 |

---

## 6. 종료 시 자원

| 자원 | 상태 |
| --- | --- |
| Orca Run `run_75c43ef48072` | Task 전부 `completed`, 워커 창 전부 닫음 |
| 워크트리 | 병합한 워크트리·브랜치 전부 정리. 주 저장소만 남김 |
| 운영 DB | alembic head `b7c8d9e0f1a2`, 적용 전 백업 `snapshot_20261011_225021` |
| Docker | 사용자 요청으로 컴퓨터 종료 전 개발 스택 전부 정지(볼륨 유지). app·worker 이미지는 OCR 의존성 반영 재빌드 |
| 배경 프로세스 | 코디네이터 대기 루프·CI 감시·워커 감시기·자동 승인 감시기 전부 종료 |
| 다른 코디네이터 세션 창 | `term_a814...`(Cursor CLI 코디네이터)는 이 Run 소속이 아니라 건드리지 않음 |
