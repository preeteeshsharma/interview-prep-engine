"""Tests for the Twilio intent parser — pure function, no I/O."""
from app.routes.webhooks.twilio import _parse_intent


def test_prep_single_word():
    assert _parse_intent("prep zapier") == ("prep", ["zapier"])


def test_prep_multiword_company():
    assert _parse_intent("prep clear street") == ("prep", ["clear", "street"])


def test_prep_uppercase():
    intent, args = _parse_intent("PREP Zapier")
    assert intent == "prep"
    assert args == ["Zapier"]


def test_prep_no_args():
    assert _parse_intent("prep") == ("prep", [])


def test_mock_lld():
    assert _parse_intent("mock lld") == ("mock", ["lld"])


def test_mock_no_args():
    assert _parse_intent("mock") == ("mock", [])


def test_done_easy():
    assert _parse_intent("done easy") == ("done", ["easy"])


def test_done_hard():
    assert _parse_intent("done hard") == ("done", ["hard"])


def test_done_no_args():
    assert _parse_intent("done") == ("done", [])


def test_status():
    assert _parse_intent("status") == ("status", [])


def test_status_uppercase():
    assert _parse_intent("STATUS") == ("status", [])


def test_link_with_email():
    assert _parse_intent("link me@example.com") == ("link", ["me@example.com"])


def test_link_no_args():
    assert _parse_intent("link") == ("link", [])


def test_freeform_question():
    intent, args = _parse_intent("what is a deadlock?")
    assert intent == "freeform"


def test_freeform_end():
    intent, _ = _parse_intent("end")
    assert intent == "freeform"


def test_empty_body():
    assert _parse_intent("") == ("unknown", [])


def test_whitespace_only():
    assert _parse_intent("   ") == ("unknown", [])
