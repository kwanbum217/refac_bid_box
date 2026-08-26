"""등록 모델 실재 대조 도구 테스트.

이 도구가 막으려는 것은 2026-08-20 의 실제 사고입니다. 무료 풀 1순위가
제공자에서 사라졌는데 라우터는 그대로 들고 있었고, 선택되는 순간에야
`Model not found` 로 드러났습니다.

관측 이력 기반 반복 확인 로직 검증을 위해 3회 연속 absent가 확인될 때만
소멸로 판정합니다.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from scripts import audit_model_inventory as audit_tool


@pytest.fixture
def fake_pool(monkeypatch):
    def _apply(pool: dict) -> None:
        monkeypatch.setattr(audit_tool, "MODEL_POOL", pool)

    return _apply


@pytest.fixture
def temp_state_path() -> Path:
    """임시 상태 파일 경로를 반환합니다."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = Path(f.name)
    return path


@pytest.fixture(autouse=True)
def reset_state_file(temp_state_path):
    """각 테스트 전후에서 상태 파일을 정리합니다."""
    if temp_state_path.exists():
        temp_state_path.unlink()
    yield
    if temp_state_path.exists():
        temp_state_path.unlink()


# ============================================================
# 기존 테스트 4건 (관측 이력 로직에 맞게 수정)
# ============================================================


def test_missing_model_detection_after_three_runs(fake_pool, monkeypatch, temp_state_path):
    """3회 연속 absent가 확인되면 소멸로 판정되고 종료 코드 1 이 납니다."""
    fake_pool(
        {
            "gone": {
                "id": "opencode/vanished-free",
                "provider": "opencode",
                "suitable_for": ["investigator"],
            }
        }
    )
    monkeypatch.setattr(audit_tool, "_run_listing", lambda cmd: {"opencode/alive-free"})

    # 첫 번째 실행: 의심 1/3
    missing1, _ = audit_tool.audit(state_path=temp_state_path)
    assert missing1 == 0

    # 두 번째 실행: 의심 2/3
    missing2, _ = audit_tool.audit(state_path=temp_state_path)
    assert missing2 == 0

    # 세 번째 실행: 소멸
    missing3, lines = audit_tool.audit(state_path=temp_state_path)
    assert missing3 == 1
    assert any("소멸" in line for line in lines)
    assert audit_tool.main(["--state", str(temp_state_path)]) == 1


def test_present_model_passes(fake_pool, monkeypatch, temp_state_path):
    fake_pool(
        {
            "alive": {
                "id": "opencode/alive-free",
                "provider": "opencode",
                "suitable_for": ["investigator"],
            }
        }
    )
    monkeypatch.setattr(audit_tool, "_run_listing", lambda cmd: {"opencode/alive-free"})

    missing, _ = audit_tool.audit(state_path=temp_state_path)

    assert missing == 0
    assert audit_tool.main(["--state", str(temp_state_path)]) == 0


def test_unassignable_entry_is_skipped(fake_pool, monkeypatch, temp_state_path):
    """suitable_for 가 비어 있으면 소멸해도 배정되지 않으므로 검사하지 않습니다."""
    fake_pool(
        {
            "retired": {
                "id": "opencode/vanished-free",
                "provider": "opencode",
                "suitable_for": [],
            }
        }
    )

    def _fail(cmd):
        raise AssertionError("배정 대상이 아닌 항목은 조회하지 않아야 합니다")

    monkeypatch.setattr(audit_tool, "_run_listing", _fail)

    missing, lines = audit_tool.audit(state_path=temp_state_path)

    assert missing == 0
    assert any("건너뜀" in line for line in lines)


def test_listing_failure_is_not_reported_as_vanished(fake_pool, monkeypatch, temp_state_path):
    """조회 실패와 소멸은 다릅니다. 실패를 소멸로 승격하면 fail-open 의 반대편입니다."""
    fake_pool(
        {
            "alive": {
                "id": "opencode/alive-free",
                "provider": "opencode",
                "suitable_for": ["investigator"],
            }
        }
    )

    def _boom(cmd):
        raise RuntimeError("opencode models 실패 (종료 코드 1)")

    monkeypatch.setattr(audit_tool, "_run_listing", _boom)

    missing, lines = audit_tool.audit(state_path=temp_state_path)

    assert missing == 0
    assert any("확인불가" in line for line in lines)


# ============================================================
# 신규 테스트: 관측 이력 기반 반복 확인 로직 검증
# ============================================================


def test_unknown_preserves_counter(fake_pool, monkeypatch, temp_state_path):
    """조회 실패(unknown) 관측이 연속 absent 카운터를 증가시키지 않고 보존한다."""
    fake_pool(
        {
            "model1": {
                "id": "opencode/alive-free",
                "provider": "opencode",
                "suitable_for": ["investigator"],
            }
        }
    )
    monkeypatch.setattr(audit_tool, "_run_listing", lambda cmd: {"opencode/other"})

    # 첫 번째 실행: absent (모델이 목록에 없음), counter = 1
    missing1, _ = audit_tool.audit(state_path=temp_state_path)
    assert missing1 == 0
    assert any("의심" in line for line in _)

    # 두 번째 실행: unknown (목록 조회 실패), counter 보존
    def _fail(cmd):
        raise RuntimeError("opencode models 실패")

    monkeypatch.setattr(audit_tool, "_run_listing", _fail)
    _, _ = audit_tool.audit(state_path=temp_state_path)
    # unknown은 카운터를 보존하므로 history에서 counter = 1 유지
    if temp_state_path.exists():
        history = json.loads(temp_state_path.read_text())
        assert history.get("model1", {}).get("counter") == 1


def test_unknown_not_reset_counter(fake_pool, monkeypatch, temp_state_path):
    """조회 실패(unknown) 관측이 연속 absent 카운터를 0 으로 초기화하지 않는다."""
    fake_pool(
        {
            "model1": {
                "id": "opencode/alive-free",
                "provider": "opencode",
                "suitable_for": ["investigator"],
            }
        }
    )
    # 첫 번째 실행: absent
    monkeypatch.setattr(audit_tool, "_run_listing", lambda cmd: {"opencode/other"})
    missing1, _ = audit_tool.audit(state_path=temp_state_path)
    assert missing1 == 0

    # 두 번째 실행: unknown
    def _fail(cmd):
        raise RuntimeError("opencode models 실패")

    monkeypatch.setattr(audit_tool, "_run_listing", _fail)
    _, _ = audit_tool.audit(state_path=temp_state_path)

    # history에서 카운터가 1로 유지됨을 확인
    if temp_state_path.exists():
        history = json.loads(temp_state_path.read_text())
        assert history.get("model1", {}).get("counter") == 1


def test_absent_thresholds_boundary(fake_pool, monkeypatch, temp_state_path):
    """absent 2회에서는 종료 코드 0, 3회째에서 종료 코드 1 이 되는 경계를 검증."""
    fake_pool(
        {
            "model1": {
                "id": "opencode/alive-free",
                "provider": "opencode",
                "suitable_for": ["investigator"],
            }
        }
    )
    monkeypatch.setattr(audit_tool, "_run_listing", lambda cmd: {"opencode/other"})

    # 첫 번째 absent: 의심 1/3
    missing1, lines1 = audit_tool.audit(state_path=temp_state_path)
    assert missing1 == 0
    assert any("의심" in line for line in lines1)
    assert "1/3" in lines1[0]

    # 두 번째 absent: 의심 2/3
    missing2, lines2 = audit_tool.audit(state_path=temp_state_path)
    assert missing2 == 0
    assert any("의심" in line for line in lines2)
    assert "2/3" in lines2[0]

    # 세 번째 absent: 소멸
    missing3, lines3 = audit_tool.audit(state_path=temp_state_path)
    assert missing3 == 1
    assert any("소멸" in line for line in lines3)


def test_present_resets_counter(fake_pool, monkeypatch, temp_state_path):
    """present 관측 후 카운터가 0 으로 초기화된다."""
    fake_pool(
        {
            "model1": {
                "id": "opencode/alive-free",
                "provider": "opencode",
                "suitable_for": ["investigator"],
            }
        }
    )
    monkeypatch.setattr(audit_tool, "_run_listing", lambda cmd: {"opencode/alive-free"})

    # 첫 번째 실행: present
    missing1, _ = audit_tool.audit(state_path=temp_state_path)
    assert missing1 == 0

    # history에서 카운터가 0으로 초기화됨을 확인
    if temp_state_path.exists():
        history = json.loads(temp_state_path.read_text())
        assert history.get("model1", {}).get("counter") == 0


def test_present_after_absent_resets_counter(fake_pool, monkeypatch, temp_state_path):
    """absent 이후 present 가 오면 카운터가 초기화되어 그 뒤 absent 2회로는
    소멸 판정이 나지 않음을 검증."""
    fake_pool(
        {
            "model1": {
                "id": "opencode/model1-free",
                "provider": "opencode",
                "suitable_for": ["investigator"],
            }
        }
    )
    # 첫 번째: 목록에 모델이 없음 (absent 1회)
    monkeypatch.setattr(audit_tool, "_run_listing", lambda cmd: {"opencode/other"})
    missing1, _ = audit_tool.audit(state_path=temp_state_path)
    assert missing1 == 0

    # 두 번째: 모데이 목록에 있음 (present), 카운터 초기화
    monkeypatch.setattr(audit_tool, "_run_listing", lambda cmd: {"opencode/model1-free"})
    missing2, _ = audit_tool.audit(state_path=temp_state_path)
    assert missing2 == 0

    # 세 번째: 다시 사라짐 (absent 1회)
    monkeypatch.setattr(audit_tool, "_run_listing", lambda cmd: {"opencode/other"})
    missing3, _ = audit_tool.audit(state_path=temp_state_path)
    assert missing3 == 0  # 1회 absent는 소멸 아님

    # 네 번째: 다시 사라짐 (absent 2회)
    missing4, _ = audit_tool.audit(state_path=temp_state_path)
    assert missing4 == 0  # 2회 absent는 소멸 아님


def test_corrupt_state_file_not_fatal(fake_pool, monkeypatch, temp_state_path):
    """손상된 상태 파일에서 종료 코드 2 로 죽지 않음을 검증."""
    fake_pool(
        {
            "model1": {
                "id": "opencode/alive-free",
                "provider": "opencode",
                "suitable_for": ["investigator"],
            }
        }
    )
    monkeypatch.setattr(audit_tool, "_run_listing", lambda cmd: {"opencode/alive-free"})

    # 손상된 JSON 파일 생성
    temp_state_path.write_text("invalid json {{{", encoding="utf-8")

    missing, _ = audit_tool.audit(state_path=temp_state_path)
    # 손상된 파일은 빈 이력으로 시작하고 정상 종료
    assert missing == 0

    # main()에서도 종료 코드 2로 죽지 않음
    result = audit_tool.main(["--state", str(temp_state_path)])
    assert result == 0


def test_reset_state_option(fake_pool, monkeypatch, temp_state_path):
    """--reset-state 옵션으로 상태 파일을 비울 수 있다."""
    fake_pool(
        {
            "model1": {
                "id": "opencode/model1-free",
                "provider": "opencode",
                "suitable_for": ["investigator"],
            }
        }
    )
    monkeypatch.setattr(audit_tool, "_run_listing", lambda cmd: {"opencode/other"})

    # 상태 파일 생성
    audit_tool.audit(state_path=temp_state_path)

    # 상태 파일이 존재하는지 확인
    assert temp_state_path.exists()

    # reset-state 실행
    result = audit_tool.main(["--state", str(temp_state_path), "--reset-state"])
    assert result == 0

    # 파일이 삭제되었는지 확인
    assert not temp_state_path.exists()


# ============================================================
# 신규 테스트: --json 출력 및 audit_with_state 함수 검증
# ============================================================


def test_audit_with_state_returns_pools_json(fake_pool, monkeypatch, temp_state_path):
    """audit_with_state 함수가 missing, lines, pools_json 을 올바르게 반환한다."""
    fake_pool(
        {
            "present_model": {
                "id": "opencode/alive-free",
                "provider": "opencode",
                "suitable_for": ["investigator"],
            },
            "absent_model": {
                "id": "opencode/absent-free",
                "provider": "opencode",
                "suitable_for": ["investigator"],
            },
            "skipped_model": {
                "id": "opencode/skipped-free",
                "provider": "opencode",
                "suitable_for": [],
            },
        }
    )
    monkeypatch.setattr(audit_tool, "_run_listing", lambda cmd: {"opencode/alive-free"})

    missing, _lines, pools_json = audit_tool.audit_with_state(state_path=temp_state_path)

    assert missing == 0
    assert "present_model" in pools_json
    assert pools_json["present_model"] == {"status": "present", "streak": 0}
    assert "absent_model" in pools_json
    assert pools_json["absent_model"] == {"status": "absent", "streak": 1}
    assert "skipped_model" in pools_json
    assert pools_json["skipped_model"] == {"status": "skipped", "streak": 0}


def test_json_flag_output_format(fake_pool, monkeypatch, temp_state_path, capsys):
    """--json 플래그 실행 시 유효한 JSON 포맷을 출력하고 종료 코드 0 을 반환한다."""
    fake_pool(
        {
            "alive": {
                "id": "opencode/alive-free",
                "provider": "opencode",
                "suitable_for": ["investigator"],
            }
        }
    )
    monkeypatch.setattr(audit_tool, "_run_listing", lambda cmd: {"opencode/alive-free"})

    ret = audit_tool.main(["--state", str(temp_state_path), "--json"])
    assert ret == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert data["extinct"] == 0
    assert "alive" in data["pools"]
    assert data["pools"]["alive"]["status"] == "present"
    assert data["pools"]["alive"]["streak"] == 0


def test_json_flag_missing_model(fake_pool, monkeypatch, temp_state_path, capsys):
    """3회 연속 absent 후 --json 플래그 실행 시 extinct=1 과 종료 코드 1 을 낸다."""
    fake_pool(
        {
            "gone": {
                "id": "opencode/vanished-free",
                "provider": "opencode",
                "suitable_for": ["investigator"],
            }
        }
    )
    monkeypatch.setattr(audit_tool, "_run_listing", lambda cmd: set())

    # 1회, 2회 실행
    audit_tool.audit(state_path=temp_state_path)
    audit_tool.audit(state_path=temp_state_path)

    # 3회 실행 (--json)
    ret = audit_tool.main(["--state", str(temp_state_path), "--json"])
    assert ret == 1

    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert data["extinct"] == 1
    assert data["pools"]["gone"]["status"] == "absent"
    assert data["pools"]["gone"]["streak"] == 3


def test_json_flag_error_handling(fake_pool, monkeypatch, temp_state_path, capsys):
    """도구 오류 발생 시 --json 플래그 실행이 extinct=0, 빈 pools JSON 을 내고 종료 코드 2 를 반환한다."""

    def _boom(*args, **kwargs):
        raise RuntimeError("예기치 못한 도구 오류")

    monkeypatch.setattr(audit_tool, "audit_with_state", _boom)

    ret = audit_tool.main(["--state", str(temp_state_path), "--json"])
    assert ret == 2

    captured = capsys.readouterr()
    data = json.loads(captured.out.strip())
    assert data == {"extinct": 0, "pools": {}}


def test_json_flag_reset_state(fake_pool, monkeypatch, temp_state_path, capsys):
    """--reset-state 와 --json 함께 사용 시 안내 문구를 출력하지 않고 정상 종료한다."""
    temp_state_path.write_text("{}", encoding="utf-8")
    assert temp_state_path.exists()

    ret = audit_tool.main(["--state", str(temp_state_path), "--reset-state", "--json"])
    assert ret == 0
    assert not temp_state_path.exists()

    captured = capsys.readouterr()
    assert captured.out.strip() == ""
