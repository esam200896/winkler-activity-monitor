import json
import os
import smtplib
import sys
from email.message import EmailMessage

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

_MISSING = object()


def find_first(data, key):
    """Return the first value for `key` found anywhere in nested dict/list JSON."""
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for value in data.values():
            found = find_first(value, key)
            if found is not _MISSING:
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_first(item, key)
            if found is not _MISSING:
                return found
    return _MISSING


def fetch_activity(activity_id):
    resp = requests.get(API_URL.format(id=activity_id), headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.json()


def extract_status(data):
    status = find_first(data, "space_status")
    if status is _MISSING or status is None:
        raise ValueError("space_status missing or null in response")
    return str(status).strip()


def is_open(status):
    if status is None:
        return False
    s = str(status).strip()
    return bool(s) and s.lower() != "full"


def should_alert(prev_status, curr_status):
    return is_open(curr_status) and not is_open(prev_status)


def load_state(path="state.json"):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_state(state, path="state.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")


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
    # Make console output UTF-8 safe so emoji in alert subjects don't crash
    # printing on Windows terminals (e.g. cp1252) during DRY_RUN/local runs.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    dry_run = os.environ.get("DRY_RUN") == "1"
    gmail_address = os.environ.get("GMAIL_ADDRESS", "")
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    recipient = os.environ.get("NOTIFY_EMAIL", "")

    if not dry_run and not all([gmail_address, app_password, recipient]):
        sys.exit("ERROR: GMAIL_ADDRESS, GMAIL_APP_PASSWORD, and NOTIFY_EMAIL must all be set")

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
