"""worker 가 낙찰결과 매칭률 감시 스위치를 compose 에서 전달받는지 검증합니다.

worker 이미지는 .env 를 담지 않고 environment 목록만 받으므로, 목록에 없으면
.env 에 값을 넣어도 설정이 켜지지 않습니다.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FLAGS = (
    "RESULT_COVERAGE_EXCLUDE_LATER_CANCELLED=${RESULT_COVERAGE_EXCLUDE_LATER_CANCELLED:-false}",
    "RESULT_COVERAGE_EXCLUDE_OFFLINE_BIDS=${RESULT_COVERAGE_EXCLUDE_OFFLINE_BIDS:-false}",
    "RESULT_COVERAGE_ALERT_SUPPRESS=${RESULT_COVERAGE_ALERT_SUPPRESS:-}",
)


def _worker_block(compose_file: str) -> str:
    text = (ROOT / compose_file).read_text(encoding="utf-8")
    worker = text.split("\n  worker:\n", maxsplit=1)[1]
    next_service = worker.find("\n  ", 1)
    while next_service != -1 and worker[next_service + 3] == " ":
        next_service = worker.find("\n  ", next_service + 1)
    return worker if next_service == -1 else worker[:next_service]


@pytest.mark.parametrize("compose_file", ["docker-compose.yml", "docker-compose.prod.yml"])
@pytest.mark.parametrize("flag", FLAGS)
def test_worker_receives_result_coverage_flag(compose_file: str, flag: str) -> None:
    assert f"      - {flag}\n" in _worker_block(compose_file)
