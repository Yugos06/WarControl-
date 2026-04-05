import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from collector.agent import generate_demo_event


def test_demo_event_has_required_fields():
    event = generate_demo_event()
    assert "ts" in event
    assert "type" in event
    assert "message" in event
    assert event["source"] == "demo"


def test_demo_event_type_is_valid():
    valid_types = {"kill", "join", "leave", "chat"}
    seen = set()
    for _ in range(200):
        e = generate_demo_event()
        seen.add(e["type"])
    assert seen == valid_types, f"Types vus: {seen}"


def test_demo_kill_has_actor_and_target():
    for _ in range(50):
        e = generate_demo_event()
        if e["type"] == "kill":
            assert e["actor"] is not None
            assert e["target"] is not None
            assert e["actor"] != e["target"]
            return
    assert False, "Aucun kill généré en 50 essais"


def test_demo_join_has_actor():
    for _ in range(50):
        e = generate_demo_event()
        if e["type"] == "join":
            assert e["actor"] is not None
            return
    assert False, "Aucun join généré en 50 essais"
