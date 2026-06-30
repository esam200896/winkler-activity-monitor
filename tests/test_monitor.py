import json
import pathlib
import pytest
import monitor

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_extract_status_full():
    assert monitor.extract_status(load_fixture("full.json")) == "Full"


def test_extract_status_open_is_not_full():
    status = monitor.extract_status(load_fixture("open.json"))
    assert status.strip().lower() != "full"
    assert status  # non-empty


def test_extract_status_missing_raises():
    with pytest.raises(ValueError):
        monitor.extract_status({"unrelated": {"foo": "bar"}})


def test_extract_status_null_raises():
    with pytest.raises(ValueError):
        monitor.extract_status({"space_status": None})


def test_is_open_full_is_false():
    assert monitor.is_open("Full") is False
    assert monitor.is_open("full") is False
    assert monitor.is_open("  FULL  ") is False


def test_is_open_openings_is_true():
    assert monitor.is_open("3 openings remaining") is True
    assert monitor.is_open("Enroll Now") is True


def test_is_open_none_is_false():
    assert monitor.is_open(None) is False


def test_should_alert_full_to_open():
    assert monitor.should_alert("Full", "3 openings remaining") is True


def test_should_alert_unknown_to_open():
    assert monitor.should_alert(None, "3 openings remaining") is True


def test_no_alert_open_to_open():
    assert monitor.should_alert("3 openings remaining", "2 openings remaining") is False


def test_no_alert_open_to_full():
    assert monitor.should_alert("3 openings remaining", "Full") is False


def test_no_alert_full_to_full():
    assert monitor.should_alert("Full", "Full") is False


def test_load_state_missing_returns_empty(tmp_path):
    assert monitor.load_state(tmp_path / "nope.json") == {}


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    monitor.save_state({"2258": "Full"}, path)
    assert monitor.load_state(path) == {"2258": "Full"}


def test_send_email_dry_run_prints_and_no_network(capsys):
    monitor.send_email(
        "SUBJ",
        "BODY",
        gmail_address="x@gmail.com",
        app_password="secret",
        recipient="y@yahoo.com",
        dry_run=True,
    )
    out = capsys.readouterr().out
    assert "SUBJ" in out
    assert "BODY" in out


def test_build_alert_contains_label_status_and_link():
    subject, body = monitor.build_alert("Swim A", "2258", "3 openings remaining")
    assert "2258" in subject
    assert "3 openings remaining" in subject
    assert "Swim A" in body
    assert "activity/search/detail/2258" in body
    assert "from_original_cui=true" in body
    assert "onlineSiteId=0" in body


def test_run_alerts_only_on_transition(monkeypatch):
    # 2258 flips Full -> open (alert); 2257 stays Full (no alert)
    responses = {"2258": "3 openings remaining", "2257": "Full"}
    monkeypatch.setattr(monitor, "fetch_activity", lambda aid: {"space_status": responses[aid]})

    sent = []
    activities = [
        {"id": "2258", "label": "Swim A"},
        {"id": "2257", "label": "Swim B"},
    ]
    state = {"2258": "Full", "2257": "Full"}

    new_state = monitor.run(activities, state, lambda subject, body: sent.append(subject))

    assert len(sent) == 1
    assert "2258" in sent[0]
    assert new_state == {"2258": "3 openings remaining", "2257": "Full"}


def test_run_no_re_alert_when_already_open(monkeypatch):
    monkeypatch.setattr(monitor, "fetch_activity", lambda aid: {"space_status": "2 openings remaining"})
    sent = []
    state = {"2258": "3 openings remaining"}
    new_state = monitor.run([{"id": "2258", "label": "Swim A"}], state,
                            lambda subject, body: sent.append(subject))
    assert sent == []
    assert new_state == {"2258": "2 openings remaining"}


def test_run_fetch_error_keeps_prior_state_and_no_alert(monkeypatch):
    def boom(aid):
        raise RuntimeError("network down")

    monkeypatch.setattr(monitor, "fetch_activity", boom)
    sent = []
    state = {"2258": "Full"}
    new_state = monitor.run([{"id": "2258", "label": "Swim A"}], state,
                            lambda s, b: sent.append(s))
    assert sent == []
    assert new_state == {"2258": "Full"}


def test_is_open_empty_or_whitespace_is_false():
    assert monitor.is_open("") is False
    assert monitor.is_open("   ") is False
