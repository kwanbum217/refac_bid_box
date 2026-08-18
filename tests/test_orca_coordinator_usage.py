"""
tests/test_orca_coordinator_usage.py

scripts/orca_coordinator_usage.py 의 단위 테스트입니다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.orca_coordinator_usage import (
    collect_usage,
    default_transcript_dir,
    iter_usage_records,
    main,
    project_slug,
)

# --------------------------------------------------------------------------
# 픽스처
# --------------------------------------------------------------------------


@pytest.fixture
def sample_records() -> list[str]:
    """기본 테스트용 JSONL 문자열 줄 목록을 반환합니다."""
    return [
        # (1) 요청 1: 3회 반복 (동일 message.id)
        json.dumps(
            {
                "type": "assistant",
                "timestamp": "2026-08-16T10:00:00.000Z",
                "message": {
                    "id": "msg_001",
                    "model": "claude-opus-5",
                    "role": "assistant",
                    "usage": {
                        "input_tokens": 100,
                        "cache_creation_input_tokens": 2000,
                        "cache_read_input_tokens": 3000,
                        "output_tokens": 150,
                    },
                },
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "timestamp": "2026-08-16T10:00:01.000Z",
                "message": {
                    "id": "msg_001",
                    "model": "claude-opus-5",
                    "role": "assistant",
                    "usage": {
                        "input_tokens": 100,
                        "cache_creation_input_tokens": 2000,
                        "cache_read_input_tokens": 3000,
                        "output_tokens": 150,
                    },
                },
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "timestamp": "2026-08-16T10:00:02.000Z",
                "message": {
                    "id": "msg_001",
                    "model": "claude-opus-5",
                    "role": "assistant",
                    "usage": {
                        "input_tokens": 100,
                        "cache_creation_input_tokens": 2000,
                        "cache_read_input_tokens": 3000,
                        "output_tokens": 150,
                    },
                },
            }
        ),
        # (2) 파싱 실패 손상 줄
        "not-a-valid-json {[[",
        # (3) 요청 2: 다른 시간대 (2026-08-16T11:00:00Z)
        json.dumps(
            {
                "type": "assistant",
                "timestamp": "2026-08-16T11:00:00.000Z",
                "message": {
                    "id": "msg_002",
                    "model": "claude-opus-5",
                    "role": "assistant",
                    "usage": {
                        "input_tokens": 50,
                        "cache_creation_input_tokens": 500,
                        "cache_read_input_tokens": 1000,
                        "output_tokens": 80,
                    },
                },
            }
        ),
        # (4) 요청 3: 사이드체인 메시지 (isSidechain = True)
        json.dumps(
            {
                "type": "assistant",
                "isSidechain": True,
                "timestamp": "2026-08-16T11:30:00.000Z",
                "message": {
                    "id": "msg_sidechain_01",
                    "model": "claude-opus-5",
                    "role": "assistant",
                    "usage": {
                        "input_tokens": 10,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 100,
                        "output_tokens": 20,
                    },
                },
            }
        ),
        # (5) 요청 4: message.id 없고 최상위 uuid 만 있는 메시지
        json.dumps(
            {
                "type": "assistant",
                "uuid": "uuid_msg_004",
                "timestamp": "2026-08-16T12:00:00.000Z",
                "message": {
                    "model": "claude-opus-5",
                    "role": "assistant",
                    "usage": {
                        "input_tokens": 30,
                        "cache_creation_input_tokens": 100,
                        "cache_read_input_tokens": 200,
                        "output_tokens": 40,
                    },
                },
            }
        ),
        # (6) 요청 5: timestamp 가 없는 레코드
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "msg_undated_01",
                    "model": "claude-opus-5",
                    "role": "assistant",
                    "usage": {
                        "input_tokens": 15,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 50,
                        "output_tokens": 10,
                    },
                },
            }
        ),
    ]


@pytest.fixture
def transcript_file(tmp_path: Path, sample_records: list[str]) -> Path:
    """테스트용 트랜스크립트 파일을 생성합니다."""
    p = tmp_path / "sess_main.jsonl"
    p.write_text("\n".join(sample_records), encoding="utf-8")
    return p


# --------------------------------------------------------------------------
# 단위 테스트
# --------------------------------------------------------------------------


def test_project_slug_converts_separators_and_underscore() -> None:
    """(1) project_slug 가 경로 구분자와 밑줄을 모두 하이픈으로 바꿉니다.

    Windows 는 구분자가 역슬래시이고 드라이브 문자가 앞에 붙으므로, 기대값을
    POSIX 경로로 못박지 않고 resolve 결과에서 파생시킵니다.
    """
    p = Path("/Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box")
    slug = project_slug(p)
    assert "/" not in slug
    assert "\\" not in slug
    assert "_" not in slug
    expected = str(p.resolve()).replace("\\", "-").replace("/", "-").replace("_", "-")
    assert slug == expected
    assert slug.endswith("-refac-bid-box")


def test_default_transcript_dir() -> None:
    """default_transcript_dir 가 올바른 경로를 반환합니다."""
    p = Path("/Users/kwanbum/test_project_dir")
    tdir = default_transcript_dir(p)
    assert tdir == Path.home() / ".claude" / "projects" / project_slug(p)
    assert tdir.name.endswith("-test-project-dir")


def test_duplicates_dropped_when_same_message_id_repeated(transcript_file: Path) -> None:
    """(2) 같은 message.id 가 세 줄 반복되면 한 번만 계상되고 duplicates_dropped 가 2 입니다."""
    res = collect_usage(transcript_file)
    assert res["duplicates_dropped"] == 2


def test_input_tokens_is_sum_of_three_components(transcript_file: Path) -> None:
    """(3) 입력 토큰이 uncached + cache_creation + cache_read 세 항목의 합입니다."""
    # msg_001 만 포함하는 시간대 선택 (10:00 ~ 10:05)
    res = collect_usage(
        transcript_file,
        since="2026-08-16T10:00:00Z",
        until="2026-08-16T10:05:00Z",
    )
    assert res["messages_counted"] == 1
    assert res["uncached_input_tokens"] == 100
    assert res["cache_creation_input_tokens"] == 2000
    assert res["cache_read_input_tokens"] == 3000
    # 합산 5100
    assert res["coordinator_input_tokens"] == 5100
    assert res["coordinator_output_tokens"] == 150
    # fresh_input_tokens = uncached (100) + cache_creation (2000) = 2100 (cache_read 제외)
    assert res["fresh_input_tokens"] == 2100


def test_fresh_input_tokens_null_when_zero_messages(transcript_file: Path) -> None:
    """messages_counted 가 0 일 때 fresh_input_tokens 는 null(None) 입니다."""
    res = collect_usage(
        transcript_file,
        since="2026-08-17T00:00:00Z",
        until="2026-08-17T01:00:00Z",
    )
    assert res["messages_counted"] == 0
    assert res["fresh_input_tokens"] is None
    assert res["coordinator_input_tokens"] is None


def test_records_outside_window_are_excluded(transcript_file: Path) -> None:
    """(4) since/until 창 밖 레코드가 제외됩니다."""
    # 10:30 ~ 11:15 창: msg_002 (11:00:00) 만 해당
    res = collect_usage(
        transcript_file,
        since="2026-08-16T10:30:00Z",
        until="2026-08-16T11:15:00Z",
    )
    assert res["messages_counted"] == 1
    assert res["coordinator_input_tokens"] == (50 + 500 + 1000)
    assert res["coordinator_output_tokens"] == 80


def test_window_boundary_values_are_inclusive(transcript_file: Path) -> None:
    """(5) 창 경계값(since, until)과 정확히 일치하는 레코드가 포함됩니다."""
    # msg_001 (10:00:00) 과 msg_002 (11:00:00) 경계 테스트
    res = collect_usage(
        transcript_file,
        since="2026-08-16T10:00:00.000Z",
        until="2026-08-16T11:00:00.000Z",
    )
    # msg_001, msg_002 두 개 모두 포함되어야 함
    assert res["messages_counted"] == 2
    assert res["coordinator_input_tokens"] == (5100 + 1550)


def test_issidechain_records_excluded_by_default_and_included_with_flag(
    transcript_file: Path,
) -> None:
    """(6) isSidechain 레코드가 기본 제외되고 include_sidechain=True 로 포함됩니다."""
    # 기본: isSidechain 메시지(msg_sidechain_01) 제외
    res_default = collect_usage(
        transcript_file,
        since="2026-08-16T11:15:00Z",
        until="2026-08-16T11:45:00Z",
    )
    assert res_default["messages_counted"] == 0
    assert res_default["sidechain_skipped"] == 1
    assert res_default["coordinator_input_tokens"] is None

    # include_sidechain = True
    res_sidechain = collect_usage(
        transcript_file,
        since="2026-08-16T11:15:00Z",
        until="2026-08-16T11:45:00Z",
        include_sidechain=True,
    )
    assert res_sidechain["messages_counted"] == 1
    assert res_sidechain["sidechain_skipped"] == 0
    assert res_sidechain["coordinator_input_tokens"] == (10 + 0 + 100)
    assert res_sidechain["coordinator_output_tokens"] == 20


def test_message_id_missing_falls_back_to_uuid(transcript_file: Path) -> None:
    """(7) message.id 가 없으면 최상위 uuid 로 식별 및 중복 제거됩니다."""
    res = collect_usage(
        transcript_file,
        since="2026-08-16T11:50:00Z",
        until="2026-08-16T12:10:00Z",
    )
    assert res["messages_counted"] == 1
    assert res["coordinator_input_tokens"] == (30 + 100 + 200)
    assert res["coordinator_output_tokens"] == 40


def test_malformed_lines_counted_and_continues(transcript_file: Path) -> None:
    """(8) JSON 파싱 실패 줄이 malformed_lines 로 계상되고 집계는 계속됩니다."""
    res = collect_usage(transcript_file)
    assert res["malformed_lines"] == 1
    assert res["messages_counted"] >= 3


def test_undated_records_counted_as_undated_skipped_when_window_given(
    transcript_file: Path,
) -> None:
    """일시 정보가 없는 레코드는 창 지정 시 undated_skipped 로 계상됩니다."""
    res = collect_usage(
        transcript_file,
        since="2026-08-16T09:00:00Z",
        until="2026-08-16T13:00:00Z",
    )
    assert res["undated_skipped"] == 1


def test_cli_exit_code_1_and_null_tokens_when_no_messages_in_window(tmp_path: Path) -> None:
    """(9) 창 안에 메시지가 없으면 종료 코드 1 이고 토큰이 null 입니다."""
    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    trans_dir = tmp_path / "trans"
    trans_dir.mkdir()

    sess = trans_dir / "sess1.jsonl"
    sess.write_text(
        json.dumps(
            {
                "type": "assistant",
                "timestamp": "2026-08-16T10:00:00Z",
                "message": {
                    "id": "m1",
                    "role": "assistant",
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            }
        ),
        encoding="utf-8",
    )

    # 창을 미래로 설정하여 메시지 0건 유도
    argv = [
        "--transcript-dir",
        str(trans_dir),
        "--since",
        "2026-08-17T00:00:00Z",
        "--json",
    ]
    rc = main(argv)
    assert rc == 1


def test_cli_exit_code_2_when_transcript_dir_missing(tmp_path: Path) -> None:
    """(10) 트랜스크립트 디렉터리가 없으면 종료 코드 2 입니다."""
    nonexistent = tmp_path / "does_not_exist"
    rc = main(["--transcript-dir", str(nonexistent)])
    assert rc == 2


def test_cli_json_output_is_pure_json(
    tmp_path: Path, transcript_file: Path, capsys: pytest.CaptureFixture
) -> None:
    """(11) --json 출력이 stdout 에 순수 JSON 으로 파싱됩니다."""
    argv = [
        "--transcript-dir",
        str(transcript_file.parent),
        "--all-sessions",
        "--json",
    ]
    rc = main(argv)
    assert rc == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "coordinator_input_tokens" in data
    assert "coordinator_output_tokens" in data
    assert "messages_counted" in data
    assert data["messages_counted"] >= 3


def test_cli_picks_newest_session_by_default(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """(12) --session 과 --all-sessions 가 없으면 수정 시각이 가장 최근인 세션 파일 하나만 집계합니다."""
    trans_dir = tmp_path / "trans"
    trans_dir.mkdir()

    old_sess = trans_dir / "old_sess.jsonl"
    old_sess.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "m_old",
                    "role": "assistant",
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                },
            }
        ),
        encoding="utf-8",
    )

    new_sess = trans_dir / "new_sess.jsonl"
    new_sess.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "m_new",
                    "role": "assistant",
                    "usage": {"input_tokens": 200, "output_tokens": 80},
                },
            }
        ),
        encoding="utf-8",
    )

    argv = ["--transcript-dir", str(trans_dir), "--json"]
    rc = main(argv)
    assert rc == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["sessions"] == ["new_sess.jsonl"]
    assert data["coordinator_input_tokens"] == 200


def test_iter_usage_records_directly(transcript_file: Path) -> None:
    """iter_usage_records 가 유효 레코드와 malformed 여부를 튜플로 올바르게 yield 합니다."""
    records = list(iter_usage_records(transcript_file))
    # sample_records 에는 유효 레코드 7개(중복 3개 포함), 손상 1개 있음
    assert len(records) == 8
    malformed = [r for r, is_m in records if is_m]
    assert len(malformed) == 1
    valid = [r for r, is_m in records if not is_m and r is not None]
    assert len(valid) == 7


def test_cli_human_output_contains_fresh_guidance(
    transcript_file: Path, capsys: pytest.CaptureFixture
) -> None:
    """사람용 텍스트 출력에 fresh_input_tokens 대표 지표 안내와 99.5% 실측 문구가 포함됩니다."""
    argv = [
        "--transcript-dir",
        str(transcript_file.parent),
        "--all-sessions",
    ]
    rc = main(argv)
    assert rc == 0
    captured = capsys.readouterr()
    assert "Fresh Input Tokens" in captured.out
    assert "99.5%" in captured.out
    assert "대표 지표" in captured.out
