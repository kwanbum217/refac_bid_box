import threading

from src.ml.model_registry import ModelRegistry


def test_concurrent_load_and_lookup_share_one_discovery_without_partial_registry(monkeypatch):
    previous_registry = {"previous": object()}
    first_model = object()
    second_model = object()
    discovery_started = threading.Event()
    allow_discovery_to_finish = threading.Event()
    lookup_finished = threading.Event()
    calls = 0

    monkeypatch.setattr(ModelRegistry, "_models", previous_registry)
    monkeypatch.setattr(
        ModelRegistry,
        "_discover_model_ids_on_disk",
        classmethod(lambda cls: ["first", "second"]),
    )

    def slow_discover(cls, registry=None):
        nonlocal calls
        calls += 1
        registry["first"] = first_model
        discovery_started.set()
        assert allow_discovery_to_finish.wait(timeout=2)
        registry["second"] = second_model

    monkeypatch.setattr(ModelRegistry, "discover_models", classmethod(slow_discover))

    loader = threading.Thread(target=ModelRegistry.load_all_models)
    lookup_result = []

    def lookup():
        lookup_result.extend(ModelRegistry.available_models())
        lookup_finished.set()

    loader.start()
    assert discovery_started.wait(timeout=2)
    lookup_thread = threading.Thread(target=lookup)
    lookup_thread.start()

    assert not lookup_finished.wait(timeout=0.1)
    assert ModelRegistry._models is previous_registry

    allow_discovery_to_finish.set()
    loader.join(timeout=2)
    lookup_thread.join(timeout=2)

    assert not loader.is_alive()
    assert not lookup_thread.is_alive()
    assert calls == 1
    assert lookup_result == ["first", "second"]
    assert ModelRegistry._models == {"first": first_model, "second": second_model}
