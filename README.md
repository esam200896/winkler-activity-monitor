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
