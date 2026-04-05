import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from proxy.proxy import _classify_text, _normalize_text


def test_normalize_text_collapses_whitespace():
    assert _normalize_text("  hello\n\nworld \r\n") == "hello world"


def test_normalize_text_fixes_common_mojibake_chars():
    normalized = _normalize_text("HÃ©robrine a quittÃ© la partie")
    assert normalized == "Herobrine a quitte la partie"


def test_classify_text_kill_fr():
    event = _classify_text("Notch a tue Steve", server="NG", source="proxy")
    assert event is not None
    assert event["type"] == "kill"
    assert event["actor"] == "Notch"
    assert event["target"] == "Steve"


def test_classify_text_join_fr():
    event = _classify_text("Alex a rejoint la partie", server="NG", source="proxy")
    assert event is not None
    assert event["type"] == "join"
    assert event["actor"] == "Alex"


def test_classify_text_leave_en():
    event = _classify_text("Steve left the game", server="NG", source="proxy")
    assert event is not None
    assert event["type"] == "leave"
    assert event["actor"] == "Steve"


def test_classify_text_chat():
    event = _classify_text("<Dinnerbone> en guerre", server="NG", source="proxy")
    assert event is not None
    assert event["type"] == "chat"
    assert event["actor"] == "Dinnerbone"


def test_classify_text_war_alert_keyword():
    event = _classify_text("Raid detecte base nord", server="NG", source="proxy")
    assert event is not None
    assert event["type"] == "war_alert"


def test_classify_text_unknown_returns_none():
    assert _classify_text("packet 0x99 opaque binary", server="NG", source="proxy") is None
