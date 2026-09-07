# Task task_b7f70a86d03e 분석 및 작업 보고서

> **작업일**: 2026-09-07
> **과업 ID**: `task_b7f70a86d03e`
> **역할**: builder
> **목적**: 커밋 메시지 제목의 한국어 규약 정본 확정 및 기계적 거부 검사기(pre-commit commit-msg 훅 & Level 1 게이트) 연결

---

## 1. 개요 및 배경

2026-09-07 Wave AH 인수인계(8.1절 후속 과제)에서 확인된 바와 같이, 기존 규약 문서(`docs/ops/git_branching_strategy.md` 3장)는 "영어 또는 한국어 가능"으로 기술되어 있어 규약 정본 자체가 불일치했으며, Level 1 게이트에 커밋 메시지 검사가 없어 규약 위반이 기계적으로 차단되지 않았습니다.

본 작업에서는 사용자가 확정한 커밋 메시지 제목 한국어 필수 규약을 정본 문서에 명시하고, 이를 기계적으로 강제하는 검사기 및 게이트(pre-commit `commit-msg` 훅, Level 1 `게이트 8 커밋 메시지`)를 구축했습니다.

---

## 2. 확정 규약 사양

1. **커밋 제목 형식**: `<type>: <subject>`
   - `type`: 영어 소문자 알파벳 8종 (`feat`, `fix`, `docs`, `refactor`, `chore`, `test`, `ci`, `merge`)
   - `subject`: 한국어 필수 (한글 음절 `U+AC00~U+D7A3` 최소 1자 포함)
2. **이모지 금지**: AGENTS.md 7장 1번 조항에 따라 커밋 제목 내 이모지 포함 시 거부
3. **검사 대상 범위**: 제목 줄(첫 번째 비주석, 비공백 줄)만 검사하며, 본문 및 트레일러(`Co-Authored-By`, `Signed-off-by` 등)는 검사 대상에서 제외
4. **검사 면제 대상**:
   - `Merge branch` 또는 `Merge remote-tracking`으로 시작하는 git 자동 생성 병합 커밋
   - `Revert "`로 시작하는 되돌리기 커밋
   - `fixup!` 또는 `squash!`로 시작하는 커밋
   - *(주의: 저장소의 표준 병합 커밋 `merge: ...`는 수동 작성 형식이므로 한국어 규약 적용 대상)*

---

## 3. 구현 내용

### 3.1 `scripts/validate_commit_message.py`
- 커밋 메시지 제목 규약 검증 독립 CLI 스크립트
- 위치 인자(파일 경로)와 `--message` 옵션 양방향 지원
- 위반 시 종료 코드 1 반환, 위반 사유와 올바른 한국어 예시 출력
- 통과 시 종료 코드 0 반환

### 3.2 `scripts/orca_level1_gate.py` (게이트 8 추가)
- `run_gate8_commit_message` 구현 및 `run_level1_gate`의 `gates` 리스트에 연결
- `git log --format=%H%x00%P%x00%s base..branch`를 통해 브랜치의 신규 커밋을 수집하고 제목 검사
- Capsule 미지정 또는 `base == branch` 시 `skipped` (`required=False`, not_applicable) 처리하여 fail-open 건너뜀과 명확히 구분
- JSON 출력(`gate8_commit_message`) 및 사람용 정형 텍스트 출력 모두 연동

### 3.3 `.pre-commit-config.yaml`
- `commit-msg` stage에 `validate-commit-message` 로컬 훅 등록
- `entry: python3 scripts/validate_commit_message.py`, `language: system`

### 3.4 규약 문서 및 예시 정합성 동기화
- `docs/ops/git_branching_strategy.md`: 3장 허용 type에 `merge` 추가, 한국어 필수 규약 명시, 영어 예시를 한국어 예시로 교체, 4.1절 훅 설치 명령에 `--hook-type commit-msg` 추가
- `AGENTS.md`: 6장 커밋 메시지 예시를 한국어 예시(`feat: 재학습 트레이너 추가`)로 변경

---

## 4. 검증 결과

- `tests/test_validate_commit_message.py`: 38개 테스트 전량 통과 (한국어 제목, merge 타입, 여러 줄 본문 및 트레일러, 면제 3종, 영어 제목/타입 누락/미허용 타입/이모지 등 거부 사례, CLI 파일 및 메시지 인자)
- `tests/test_orca_level1_gate.py`: 50개 테스트 전량 통과 (게이트 8 통과, 위반, 적용 대상 아님 경로 및 기존 1~7 게이트 회귀 없음)
- `uv run pre-commit validate-config`: 정상 통과
- `python3 scripts/validate_agent_rules.py --quiet`: 20/20 전량 통과
