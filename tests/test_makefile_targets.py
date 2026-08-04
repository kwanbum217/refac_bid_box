import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAKE = shutil.which("make")


@pytest.mark.skipif(MAKE is None, reason="make 실행 파일이 없는 환경")
@pytest.mark.parametrize(
    "target",
    ["setup", "dev", "db-up", "build", "test", "migrate-current", "migrate-check"],
)
def test_makefile_target_has_executable_recipe(target):
    result = subprocess.run(  # noqa: S603
        [MAKE, "-n", target],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Nothing to be done" not in result.stdout
