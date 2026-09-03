# 백업 실패 종료 작업 분석

> **Task**: `task_033ef1fb805d`
> **범위**: 필수 자산 누락·0바이트 백업의 성공 보고 차단
> **기준일**: 2026-09-03

## 적용 내용

`scripts.backup_recovery_core.REQUIRED_BACKUP_ASSETS`에 `database`, `chroma_db`,
`models`를 명시하고, `chroma_db`와 `data/model_files`의 실제 존재·내용을
사전 점검합니다. 실행 백업은 DB 덤프와 생성된 각 아카이브의 존재 및 0바이트
여부를 다시 확인하며, 조건을 만족하지 못하면 `BackupAssetError`로 종료하고
매니페스트를 작성하지 않습니다.

개발 머신과 CI를 위한 부분 백업 허용 수단은 `backup --allow-partial` 하나로
제한했습니다. 해당 플래그를 사용한 누락은 매니페스트의
`partial_backup: true`, `recovery_trusted: false`, `missing_assets`에 기록하고,
누락 컴포넌트의 아카이브는 생성하지 않습니다. 복원과 복원 리허설은 이 표기를
확인하여 부분 백업을 신뢰하지 않습니다.

매니페스트에는 DB 덤프 시작·종료 시각과 파일 자산 수집 시각을
`consistency_window`로 기록했습니다. 암호화·오프사이트 보관과 RPO/RTO 판정은
구현하지 않고 런북의 미결 항목으로 남겼습니다.

## 검증

실제 MySQL 백업이나 복원은 실행하지 않고 임시 디렉터리와 대역을 사용했습니다.
필수 자산 누락, 소스 및 DB 덤프 0바이트, 아카이브 0바이트, 부분 매니페스트,
CLI 플래그 및 기존 백업·복원 테스트를 검증했습니다.

최종 검증 결과:

- `uv run pytest tests/ -q -m 'not data_assets'`: `3374 passed, 40 skipped, 3 deselected in 87.17s (0:01:27)` (exit code 0)
- `python3 scripts/validate_agent_rules.py --quiet`: `검증 통과: 19/19 건.` (exit code 0)
- `uv run ruff check scripts/backup_recovery.py scripts/backup_recovery_core.py tests/test_backup_fail_closed.py`: `All checks passed!` (exit code 0)
