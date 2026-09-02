import json

from src.app.api.v1 import health
from src.ml.model_registry import ModelRegistry


class _Wrapper:
    def __init__(self, version: str):
        self.metadata = {"version": version}


def test_served_version_detects_disk_promotion_without_reload(tmp_path, monkeypatch):
    serving = tmp_path / "models" / "demo"
    serving.mkdir(parents=True)
    (serving / "metadata.json").write_text(json.dumps({"version": "v_new"}), encoding="utf-8")
    monkeypatch.setattr(ModelRegistry, "_models", {"demo": _Wrapper("v_old")})
    monkeypatch.setattr(
        ModelRegistry, "_get_model_root", classmethod(lambda cls: str(tmp_path / "models"))
    )

    result = ModelRegistry.get_served_version("demo")

    assert result["in_memory_version"] == "v_old"
    assert result["disk_version"] == "v_new"
    assert result["consistent"] is False
    assert result["status"] == "mismatch"


def test_health_served_version_returns_unknown_when_disk_lookup_fails(monkeypatch):
    monkeypatch.setattr(ModelRegistry, "_models", {"demo": _Wrapper("v_old")})
    monkeypatch.setattr(
        ModelRegistry,
        "_discover_model_ids_on_disk",
        classmethod(lambda cls: (_ for _ in ()).throw(OSError("unreadable"))),
    )
    monkeypatch.setattr(ModelRegistry, "_get_model_root", classmethod(lambda cls: "/unreadable"))

    response = health.served_version_check()

    assert response["status"] == "ok"
    assert response["models"][0]["in_memory_version"] == "v_old"
    assert response["models"][0]["disk_version"] is None
    assert response["models"][0]["status"] == "not_on_disk"


def test_health_served_version_is_safe_without_loaded_models(monkeypatch):
    monkeypatch.setattr(ModelRegistry, "_models", {})
    monkeypatch.setattr(ModelRegistry, "_discover_model_ids_on_disk", classmethod(lambda cls: []))

    response = health.served_version_check()

    assert response == {"status": "ok", "models": [], "mismatches": []}
