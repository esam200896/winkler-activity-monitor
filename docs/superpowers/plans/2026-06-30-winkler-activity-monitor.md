# Winkler Activity Availability Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A free GitHub Actions cron that polls the City of Winkler ActiveCommunities public JSON API and emails the user when a watched activity's `space_status` leaves `"Full"`.

**Architecture:** A single Python module (`monitor.py`) exposes small, individually-testable pure functions (status extraction, open detection, transition detection, state I/O, email) plus a `main()` that wires them together. State persists in `state.json`, committed back by the workflow each run. No login and no site credentials are used — availability is public JSON.

**Tech Stack:** Python 3.12, `requests`, `pytest`, Python stdlib `smtplib`/`email`, GitHub Actions.

## Global Constraints

- API endpoint (exact): `https://anc.ca.apm.activecommunities.com/cityofwinkler/rest/activity/detail/{id}?onlineSiteId=0&locale=en-US`
- Registration link (exact, for email body): `https://anc.ca.apm.activecommunities.com/cityofwinkler/activity/search/detail/{id}?onlineSiteId=0&from_original_cui=true`
- Watched activities: `2258` (label "Swimmer 4 July 6-17, 2026") and `2257` (label "Swimmer 4 July 6-17, 2026 10:00AM").
- "Open" = `space_status` present and, trimmed + lowercased, **not equal to** `"full"`.
- Alert only on a **Full(or unknown)→open transition**; never re-alert while open.
- Email sender: `your-sender@gmail.com` via Gmail App Password. Recipient: `your-recipient@example.com`.
- Secrets (GitHub Actions): `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `NOTIFY_EMAIL`. Never hardcode credentials.
- HTTP requests use a 20s timeout and a browser-like `User-Agent`.
- All files live at the repo root of `D:\winkler-activity-monitor`.

---

## File Structure

- `requirements.txt` — `requests`, `pytest`
- `monitor.py` — all logic + `main()`
- `activities.json` — `[{ "id": "2258", "label": "..." }, { "id": "2257", "label": "..." }]`
- `state.json` — `{ "2258": "Full", "2257": "Full" }` (updated by CI)
- `tests/fixtures/full.json` — captured live response for 2258 (Full)
- `tests/fixtures/open.json` — captured live response for 2259 (open, reference)
- `tests/test_monitor.py` — unit tests
- `.github/workflows/monitor.yml` — cron workflow
- `.gitignore` — `.env`, `__pycache__/`, `*.pyc`
- `README.md` — setup + secrets + Gmail App Password steps

---

### Task 1: Fetch + status extraction

**Files:**
- Create: `requirements.txt`, `monitor.py`, `.gitignore`
- Create (test data): `tests/fixtures/full.json`, `tests/fixtures/open.json`
- Test: `tests/test_monitor.py`

**Interfaces:**
- Produces: `API_URL: str`; `fetch_activity(activity_id: str) -> dict`; `find_first(data, key: str)`; `extract_status(data: dict) -> str` (returns trimmed `space_status`, raises `ValueError` if absent).

- [ ] **Step 1: Create `requirements.txt`**

```text
requests
pytest
```

- [ ] **Step 2: Install dependencies**

Run: `cd "D:/winkler-activity-monitor" && pip install -r requirements.txt`
Expected: requests and pytest install successfully.

- [ ] **Step 3: Create `.gitignore`**

```text
.env
__pycache__/
*.pyc
```

- [ ] **Step 4: Capture real fixtures from the live API**

Run (creates the `tests/fixtures/` files from live data):

```bash
cd "D:/winkler-activity-monitor"
python -c "import requests, pathlib; \
h={'User-Agent':'Mozilla/5.0 (winkler-monitor)'}; \
u='https://anc.ca.apm.activecommunities.com/cityofwinkler/rest/activity/detail/{}?onlineSiteId=0&locale=en-US'; \
pathlib.Path('tests/fixtures').mkdir(parents=True, exist_ok=True); \
open('tests/fixtures/full.json','w',encoding='utf-8').write(requests.get(u.format(2258),headers=h,timeout=20).text); \
open('tests/fixtures/open.json','w',encoding='utf-8').write(requests.get(u.format(2259),headers=h,timeout=20).text)"
```

Expected: two files written. Sanity check:
`python -c "import json; print(json.load(open('tests/fixtures/full.json'))!=None)"` → prints `True`.

> Note: 2259 is a reference activity that was open at design time. If it has since filled, substitute any currently-open activity id to capture an open-state fixture; the test below only relies on the value being something other than `"Full"`.

- [ ] **Step 5: Write the failing test for `extract_status`**

Create `tests/test_monitor.py`:

```python
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
```

- [ ] **Step 6: Run the test to verify it fails**

Run: `cd "D:/winkler-activity-monitor" && python -m pytest tests/test_monitor.py -v`
Expected: FAIL — `AttributeError`/`ModuleNotFoundError` because `monitor.extract_status` does not exist yet.

- [ ] **Step 7: Implement fetch + extraction in `monitor.py`**

```python
import requests

API_URL = (
    "https://anc.ca.apm.activecommunities.com/cityofwinkler/rest/activity/detail/"
    "{id}?onlineSiteId=0&locale=en-US"
)
REG_URL = (
    "https://anc.ca.apm.activecommunities.com/cityofwinkler/activity/search/detail/"
    "{id}?onlineSiteId=0&from_original_cui=true"
)
HEADERS = {"User-Agent": "Mozilla/5.0 (winkler-monitor)"}


def find_first(data, key):
    """Return the first value for `key` found anywhere in nested dict/list JSON."""
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for value in data.values():
            found = find_first(value, key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_first(item, key)
            if found is not None:
                return found
    return None


def fetch_activity(activity_id):
    resp = requests.get(API_URL.format(id=activity_id), headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.json()


def extract_status(data):
    status = find_first(data, "space_status")
    if status is None:
        raise ValueError("space_status not found in response")
    return str(status).strip()
```

- [ ] **Step 8: Run the test to verify it passes**

Run: `cd "D:/winkler-activity-monitor" && python -m pytest tests/test_monitor.py -v`
Expected: 3 passed.

- [ ] **Step 9: Commit**

```bash
cd "D:/winkler-activity-monitor"
git add requirements.txt .gitignore monitor.py tests/
git commit -m "feat: fetch activity JSON and extract space_status"
```

---

### Task 2: Availability + transition logic

**Files:**
- Modify: `monitor.py`
- Test: `tests/test_monitor.py`

**Interfaces:**
- Produces: `is_open(status) -> bool`; `should_alert(prev_status, curr_status) -> bool`.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_monitor.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd "D:/winkler-activity-monitor" && python -m pytest tests/test_monitor.py -k "is_open or should_alert" -v`
Expected: FAIL — `monitor.is_open` not defined.

- [ ] **Step 3: Implement in `monitor.py`**

Add after `extract_status`:

```python
def is_open(status):
    return status is not None and str(status).strip().lower() != "full"


def should_alert(prev_status, curr_status):
    return is_open(curr_status) and not is_open(prev_status)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd "D:/winkler-activity-monitor" && python -m pytest tests/test_monitor.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
cd "D:/winkler-activity-monitor"
git add monitor.py tests/test_monitor.py
git commit -m "feat: add open detection and Full->open transition rule"
```

---

### Task 3: State persistence

**Files:**
- Modify: `monitor.py`
- Test: `tests/test_monitor.py`

**Interfaces:**
- Produces: `load_state(path="state.json") -> dict`; `save_state(state: dict, path="state.json") -> None`. Missing file ⇒ empty dict.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_monitor.py`:

```python
def test_load_state_missing_returns_empty(tmp_path):
    assert monitor.load_state(tmp_path / "nope.json") == {}


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    monitor.save_state({"2258": "Full"}, path)
    assert monitor.load_state(path) == {"2258": "Full"}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd "D:/winkler-activity-monitor" && python -m pytest tests/test_monitor.py -k state -v`
Expected: FAIL — `monitor.load_state` not defined.

- [ ] **Step 3: Implement in `monitor.py`**

Add `import json` and `import os` at the top of `monitor.py` (above `import requests`), then add:

```python
def load_state(path="state.json"):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_state(state, path="state.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")
```

- [ ] **Step 4: Run to verify pass**

Run: `cd "D:/winkler-activity-monitor" && python -m pytest tests/test_monitor.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
cd "D:/winkler-activity-monitor"
git add monitor.py tests/test_monitor.py
git commit -m "feat: add state.json load/save"
```

---

### Task 4: Email sending (with dry-run)

**Files:**
- Modify: `monitor.py`
- Test: `tests/test_monitor.py`

**Interfaces:**
- Produces: `send_email(subject, body, *, gmail_address, app_password, recipient, dry_run=False) -> None`. When `dry_run` is true it prints and returns without any network call.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_monitor.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd "D:/winkler-activity-monitor" && python -m pytest tests/test_monitor.py -k email -v`
Expected: FAIL — `monitor.send_email` not defined.

- [ ] **Step 3: Implement in `monitor.py`**

Add `import smtplib` and `from email.message import EmailMessage` near the top imports, then add:

```python
def send_email(subject, body, *, gmail_address, app_password, recipient, dry_run=False):
    if dry_run:
        print(f"[DRY_RUN] To: {recipient}\nSubject: {subject}\n\n{body}")
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = recipient
    msg.set_content(body)
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
        server.starttls()
        server.login(gmail_address, app_password)
        server.send_message(msg)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd "D:/winkler-activity-monitor" && python -m pytest tests/test_monitor.py -v`
Expected: all passed.

- [ ] **Step 5: Commit**

```bash
cd "D:/winkler-activity-monitor"
git add monitor.py tests/test_monitor.py
git commit -m "feat: add SMTP email sender with dry-run mode"
```

---

### Task 5: Main orchestration + config

**Files:**
- Create: `activities.json`, `state.json`
- Modify: `monitor.py`
- Test: `tests/test_monitor.py`

**Interfaces:**
- Produces: `build_alert(label, activity_id, status) -> tuple[str, str]` (subject, body); `run(activities, state, send) -> dict` (pure orchestration: returns updated state, calls `send(subject, body)` per alert); `main() -> None` (loads config/env, wires `run`).
- Consumes: `fetch_activity`, `extract_status`, `should_alert`, `is_open`, `load_state`, `save_state`, `send_email`, `REG_URL` from Tasks 1–4.

- [ ] **Step 1: Create `activities.json`**

```json
[
  { "id": "2258", "label": "Swimmer 4 July 6-17, 2026" },
  { "id": "2257", "label": "Swimmer 4 July 6-17, 2026 10:00AM" }
]
```

- [ ] **Step 2: Create initial `state.json`**

```json
{
  "2258": "Full",
  "2257": "Full"
}
```

- [ ] **Step 3: Write the failing tests for `build_alert` and `run`**

Append to `tests/test_monitor.py`:

```python
def test_build_alert_contains_label_status_and_link():
    subject, body = monitor.build_alert("Swim A", "2258", "3 openings remaining")
    assert "2258" in subject
    assert "3 openings remaining" in subject
    assert "Swim A" in body
    assert "activity/search/detail/2258" in body


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
```

- [ ] **Step 4: Run to verify failure**

Run: `cd "D:/winkler-activity-monitor" && python -m pytest tests/test_monitor.py -k "build_alert or run_" -v`
Expected: FAIL — `monitor.build_alert` / `monitor.run` not defined.

- [ ] **Step 5: Implement in `monitor.py`**

Add at the top imports: `import sys`. Then add:

```python
def build_alert(label, activity_id, status):
    subject = f"\U0001F7E2 Opening: {label} ({activity_id}) - {status}"
    body = (
        f"{label}\n"
        f"Status: {status}\n\n"
        f"Register now: {REG_URL.format(id=activity_id)}\n"
    )
    return subject, body


def run(activities, state, send):
    state = dict(state)
    for activity in activities:
        activity_id = activity["id"]
        label = activity["label"]
        try:
            status = extract_status(fetch_activity(activity_id))
        except Exception as exc:  # network/HTTP/JSON/shape errors
            print(f"[warn] {activity_id}: {exc}", file=sys.stderr)
            continue
        prev = state.get(activity_id)
        if should_alert(prev, status):
            subject, body = build_alert(label, activity_id, status)
            send(subject, body)
        state[activity_id] = status
    return state


def main():
    dry_run = os.environ.get("DRY_RUN") == "1"
    gmail_address = os.environ.get("GMAIL_ADDRESS", "")
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    recipient = os.environ.get("NOTIFY_EMAIL", "")

    with open("activities.json", encoding="utf-8") as f:
        activities = json.load(f)
    state = load_state()

    def send(subject, body):
        send_email(
            subject,
            body,
            gmail_address=gmail_address,
            app_password=app_password,
            recipient=recipient,
            dry_run=dry_run,
        )

    new_state = run(activities, state, send)
    save_state(new_state)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run to verify pass**

Run: `cd "D:/winkler-activity-monitor" && python -m pytest tests/test_monitor.py -v`
Expected: all passed.

- [ ] **Step 7: End-to-end dry-run against live API**

Run (no email actually sent; uses the committed `state.json` of both "Full"):

```bash
cd "D:/winkler-activity-monitor"
DRY_RUN=1 python monitor.py
```

Expected: completes with no errors. Because both watched activities are currently `Full`, no `[DRY_RUN]` email block prints. To prove the alert path end-to-end, temporarily seed an unknown state and watch the open reference:

```bash
cd "D:/winkler-activity-monitor"
printf '[{"id":"2259","label":"Open reference"}]' > /tmp/act.json
python -c "import monitor, json; \
state=monitor.run(json.load(open('/tmp/act.json')), {}, lambda s,b: print('[DRY_RUN]', s)); \
print('state:', state)"
```

Expected: prints a `[DRY_RUN] 🟢 Opening: ... (2259) - N openings remaining` line (confirming the alert fires when status is not Full).

> Note: `git checkout state.json` afterward if it was modified, so the committed baseline stays both-`Full`.

- [ ] **Step 8: Commit**

```bash
cd "D:/winkler-activity-monitor"
git add monitor.py activities.json state.json tests/test_monitor.py
git commit -m "feat: wire orchestration, config, and main entry point"
```

---

### Task 6: GitHub Actions workflow + README

**Files:**
- Create: `.github/workflows/monitor.yml`, `README.md`

**Interfaces:**
- Consumes: `monitor.py`, secrets `GMAIL_ADDRESS`/`GMAIL_APP_PASSWORD`/`NOTIFY_EMAIL`.

- [ ] **Step 1: Create `.github/workflows/monitor.yml`**

```yaml
name: Winkler Activity Monitor

on:
  schedule:
    - cron: "*/5 * * * *"
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: monitor
  cancel-in-progress: false

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - name: Run monitor
        env:
          GMAIL_ADDRESS: ${{ secrets.GMAIL_ADDRESS }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          NOTIFY_EMAIL: ${{ secrets.NOTIFY_EMAIL }}
        run: python monitor.py
      - name: Commit state changes
        run: |
          if [ -n "$(git status --porcelain state.json)" ]; then
            git config user.name "github-actions[bot]"
            git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
            git add state.json
            git commit -m "chore: update state [skip ci]"
            git push
          else
            echo "No state change."
          fi
```

- [ ] **Step 2: Create `README.md`**

```markdown
# Winkler Activity Availability Monitor

Polls the City of Winkler ActiveCommunities public availability API every ~5
minutes (GitHub Actions cron) and emails you when a watched activity's
`space_status` leaves `"Full"` (i.e. spots open / "Enroll Now" appears).

No login or site credentials are used — availability data is public JSON.

## Watched activities

Edit `activities.json` to add/remove activities:

```json
[{ "id": "2258", "label": "Swimmer 4 July 6-17, 2026" }]
```

Find an activity's id in its detail URL: `.../activity/search/detail/<ID>?...`.

## One-time setup

1. **Create a private GitHub repo** under your account (`esam200896`) and push
   this folder to it.
2. **Enable a Gmail App Password** for `your-sender@gmail.com`:
   - Google Account → Security → turn on **2-Step Verification**.
   - Security → **App passwords** → create one ("winkler monitor"); copy the
     16-character value.
3. **Add repository secrets** (repo → Settings → Secrets and variables →
   Actions → New repository secret):
   - `GMAIL_ADDRESS` = `your-sender@gmail.com`
   - `GMAIL_APP_PASSWORD` = the 16-char app password
   - `NOTIFY_EMAIL` = `your-recipient@example.com`
4. **Enable Actions:** repo → Actions tab → enable workflows. Run the
   **Winkler Activity Monitor** workflow once via **Run workflow**
   (workflow_dispatch) to confirm it works.

## How it alerts

- Sends **one email per Full→open transition**, not every run.
- State is tracked in `state.json`, committed back by the workflow.

## Caveats

- GitHub Actions cron has a **5-minute minimum** and may be delayed or skipped
  under load — expect ~5–10 minute granularity, not a guaranteed 3-minute tick.

## Local testing

```bash
pip install -r requirements.txt
python -m pytest -v          # run tests
DRY_RUN=1 python monitor.py  # run without sending email
```
```

- [ ] **Step 3: Run the full test suite once more**

Run: `cd "D:/winkler-activity-monitor" && python -m pytest -v`
Expected: all passed.

- [ ] **Step 4: Commit**

```bash
cd "D:/winkler-activity-monitor"
git add .github/workflows/monitor.yml README.md
git commit -m "feat: add GitHub Actions cron workflow and README"
```

---

## Post-implementation (manual, by the user)

These steps are done by Essam, not the implementing agent, because they require
account access:

1. Create the private GitHub repo under `esam200896` and push.
2. Generate the Gmail App Password and add the three secrets.
3. Trigger the workflow once (Run workflow) and confirm a green run.
4. Optional: temporarily add the currently-open `2259` to `activities.json` and
   reset its state to confirm a real alert email arrives, then revert.
