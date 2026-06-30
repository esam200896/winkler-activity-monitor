# Winkler Activity Availability Monitor — Design Spec

- **Date:** 2026-06-30
- **Owner:** Essam Gamal
- **Status:** Approved design, pending spec review

## 1. Purpose

Watch specific City of Winkler ActiveCommunities swim activities and **email an
alert the moment a spot opens** (registration status leaves `"Full"`), so the
user can register before it fills again. Runs free, in the cloud, 24/7.

## 2. Key finding (validated against live data)

ActiveCommunities is a JavaScript single-page app, but it exposes a **public
JSON availability API that requires no login**:

```
GET https://anc.ca.apm.activecommunities.com/cityofwinkler/rest/activity/detail/{id}?onlineSiteId=0&locale=en-US
```

The field `space_status` directly encodes availability. Confirmed live values:

| Activity | State | `space_status` |
|----------|-------|----------------|
| 2258 — Swimmer 4 July 6-17, 2026 | Full | `"Full"` |
| 2257 — Swimmer 4 July 6-17, 2026 10:00AM | Full | `"Full"` |
| 2259 — Swimmer 4 July 20-31, 2026 8:00AM (reference) | Open | `"3 openings remaining"` |

**Consequence:** no credentials are used or stored anywhere. The user's login is
irrelevant to this system. No headless browser is needed — a plain HTTP JSON
fetch is sufficient and robust against page redesigns.

## 3. Monitored activities (initial config)

- `2258` — Swimmer 4 July 6-17, 2026
- `2257` — Swimmer 4 July 6-17, 2026 10:00AM

Stored as a small config list of `{ id, label }`, easy to extend later.

## 4. Detection rule

For each activity each run:

1. Fetch the JSON, read `space_status`.
2. Define **open** = `space_status` is present and not equal to `"Full"`
   (case-insensitive, trimmed). This catches `"N openings remaining"`,
   `"Enroll Now"`, or any future non-Full value.
3. **Alert fires on a transition only:** previous status was `Full` (or unknown)
   **and** current status is open. This prevents repeat emails every 5 minutes
   while a spot stays open.
4. When an activity goes back to `Full`, update stored state silently (no
   "it closed" email in v1).

## 5. Architecture & components

```
winkler-activity-monitor/
├── monitor.py                     # fetch → compare → email → save state
├── activities.json                # [{ "id": "2258", "label": "..." }, ...]
├── state.json                     # last-known status per activity (committed by CI)
├── requirements.txt               # requests
├── tests/
│   ├── fixtures/full.json         # captured 2258 "Full" response
│   ├── fixtures/open.json         # captured 2259 "openings remaining" response
│   └── test_detection.py
└── .github/workflows/monitor.yml  # cron */5, runs monitor.py, commits state.json
```

- **`monitor.py`** — reads `activities.json`, fetches each detail endpoint
  (with timeout, a retry, and a normal browser `User-Agent`), parses
  `space_status` and activity name, compares against `state.json`, sends one
  email per Full→open transition, then writes `state.json`.
- **`state.json`** — `{ "2258": { "status": "Full", "name": "..." }, ... }`,
  committed back by the workflow so state survives between runs.
- **`.github/workflows/monitor.yml`** — `schedule: cron "*/5 * * * *"`,
  `permissions: contents: write`, runs the script, and commits `state.json` if
  it changed (commit by `github-actions[bot]`). A push from the workflow does
  not retrigger the cron, so no loop.

## 6. Email delivery

- **Transport:** SMTP, `smtp.gmail.com:587`, STARTTLS.
- **Sender:** `your-sender@gmail.com` using a **Gmail App Password** (16 chars).
  Requires 2-Step Verification enabled on that Google account; the app password
  — not the real Gmail password — is what gets stored.
- **Recipient:** `your-recipient@example.com`.
- **GitHub Secrets:** `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `NOTIFY_EMAIL`.
- **Email content:** subject like
  `🟢 Opening: Swimmer 4 July 6-17 (2258) — 3 openings remaining`; body includes
  the activity label, the `space_status` text, and a direct registration link
  (`.../activity/search/detail/{id}?onlineSiteId=0&from_original_cui=true`).

### Gmail App Password steps (for the user)

1. Google Account → Security → enable **2-Step Verification** (if not already).
2. Security → **App passwords** → create one (name it "winkler monitor").
3. Copy the 16-character password; store it as the `GMAIL_APP_PASSWORD` secret.

## 7. Error handling

- **Network/HTTP errors or non-200:** log and **skip that activity for this run
  without changing its stored state**, so a transient blip can't cause a false
  "opening" alert next run. The GitHub Action surfaces failures in its run log.
- **Unexpected JSON shape (missing `space_status`):** treat as an error for that
  activity — skip, don't alert.
- **De-duplication:** guaranteed by the transition rule + `state.json`; no repeat
  emails while a spot stays open.

## 8. Cadence caveat (set expectations)

GitHub Actions cron has a **5-minute minimum** and scheduled runs can be
**delayed or occasionally skipped** under platform load. Realistic granularity is
**~5–10 minutes**, not a guaranteed 3-minute tick. Acceptable for this use case.
A hard 3-minute guarantee would require an always-on host (out of scope for v1).

## 9. Testing

- **Unit tests** (`tests/test_detection.py`) using captured fixtures:
  - Full → open ⇒ alert.
  - open → open ⇒ no alert (no repeat).
  - open → Full ⇒ no alert, state updated.
  - error/missing field ⇒ no alert, state unchanged.
- **Email dry-run:** `DRY_RUN=1` prints the email instead of sending, for safe
  local testing; one real test send confirms the SMTP secret works.
- **End-to-end local run** with a seeded `state.json` before enabling the cron.

## 10. Out of scope (YAGNI for v1)

- Automatic registration/enrollment (alert only).
- Any login / credential storage.
- Telegram/SMS/push (email only).
- Web UI or dashboard.
- Dynamic activity discovery (fixed config list).

## 11. Deployment

- New **private** GitHub repo under account `esam200896`.
- Local project directory: `D:\winkler-activity-monitor`.
