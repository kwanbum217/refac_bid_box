from pathlib import Path

from scripts.tune_servc_hyperparams import PROJECT_ROOT, display_output_path


def test_display_output_path_for_project_file():
    assert display_output_path(PROJECT_ROOT / "data" / "result.json") == Path("data/result.json")


def test_display_output_path_for_external_file(tmp_path):
    external = tmp_path / "result.json"
    assert display_output_path(external) == external
