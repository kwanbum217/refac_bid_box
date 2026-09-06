# Task task_f7bde5d00f87 분석 보고

> 작성일: 2026-09-06
> 대상: Level 1 게이트 3 docker 검증 허용 목록

## 결함

`scripts/orca_level1_gate.py`의 `_parse_docker_command`가 `tokens[1:3] == ['compose', 'config']`만 허용했습니다.
`docker compose -f docker-compose.prod.yml config -q`는 `compose`와 `config` 사이에 `-f`가 끼어 거부됐습니다.

## 수정

- `compose` 뒤에 `-f <파일>`, `--file <파일>`, `--file=<파일>` 반복을 허용하고 그 뒤에 `config`를 요구합니다.
- 파일값은 저장소 안 상대 경로만 허용합니다. 절대 경로와 `..` 포함 경로를 거부합니다.
- 능력 계산은 `-f` 유무와 무관하게 `compose_config` 하나로 유지합니다.
- `docker build` 판정과 능력 계산, 게이트 번호와 이름, 종료 코드 규약은 그대로 둡니다.

## 검증

- `uv run pytest tests/test_orca_level1_gate.py -q` 통과
- `uv run pytest tests/ -q -m 'not data_assets'` 통과
- `python3 scripts/validate_agent_rules.py --quiet` 통과
