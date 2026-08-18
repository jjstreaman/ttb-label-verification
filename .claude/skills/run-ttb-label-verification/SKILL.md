---
name: run-ttb-label-verification
description: Build, run, and drive the TTB Label Verification Streamlit app. Use when asked to start the app, run a label through it, take a screenshot of its UI, drive the Single Label or Batch Upload tabs, or verify a code change actually works end-to-end.
---

This is a Python Streamlit app (`app.py`). Drive it via
`.claude/skills/run-ttb-label-verification/driver.py` using the project's
own `.venv` interpreter -- it launches the server, then uses Python
Playwright (no `chromium-cli`/tmux/xvfb on this machine -- see
Prerequisites) to click through the actual UI and screenshot the result.

All paths below are relative to the project root
(`TTB_Label_Verification_App/`).

This machine is **Windows** (Git Bash / MINGW64), not Linux -- server
lifecycle uses `netstat`/`taskkill` instead of a PID file or `tmux`, and
Chromium runs headless natively with no `xvfb` needed. Commands below are
written with forward slashes and run through Git Bash -- backslash paths
(`.venv\Scripts\...`) do NOT work in this shell (bash treats `\S` etc. as
escapes); use `.venv/Scripts/python.exe`.

## Prerequisites

- The project's `.venv` must already exist (`.venv/Scripts/python.exe`).
  If it doesn't: `py -3.12 -m venv .venv` -- the system `python` on PATH
  resolves to an Anaconda 3.8 env, which is too old (this code uses
  `X | None` / `list[X]` syntax, needs 3.10+).
- Playwright + Chromium, installed once into that venv:

```bash
.venv/Scripts/python.exe -m pip install playwright
.venv/Scripts/python.exe -m playwright install chromium
```

- `requirements.txt` deps (streamlit, anthropic, rapidfuzz, pandas,
  python-dotenv) already installed into `.venv`.
- `.env` must have a working `ANTHROPIC_API_KEY` (or `GOOGLE_CLOUD_PROJECT`
  for Vertex) -- the app calls the real Claude API on every verification,
  there is no mock/offline mode.

## Run (agent path)

```bash
.venv/Scripts/python.exe .claude/skills/run-ttb-label-verification/driver.py start
.venv/Scripts/python.exe .claude/skills/run-ttb-label-verification/driver.py batch
.venv/Scripts/python.exe .claude/skills/run-ttb-label-verification/driver.py single sample_data/old-tom-bourbon.png "OLD TOM DISTILLERY" "Kentucky Straight Bourbon Whiskey" "45% Alc./Vol. (90 Proof)" "750 mL"
.venv/Scripts/python.exe .claude/skills/run-ttb-label-verification/driver.py stop
```

Screenshots land in `.claude/skills/run-ttb-label-verification/shots/`.
Server log: `streamlit_driver.log` at the project root.

| command | what it does |
|---|---|
| `start` | launch Streamlit in the background, poll `:8501` until it serves |
| `stop` | find whatever's listening on `:8501` via `netstat` and `taskkill` it |
| `batch [--csv PATH] [--images PATH ...] [--url URL]` | drive the Batch Upload tab; defaults to `sample_data/applications_template.csv` + all `sample_data/*.png`. Real API calls, can take up to ~90s for 6 images. |
| `single IMAGE BRAND CLASS_TYPE ABV NET_CONTENTS [--url URL]` | drive the Single Label tab with one image + the 4 application-data fields |

`start` must be run before `batch`/`single` (they check `:8501` and fail
fast with a clear message if nothing's listening) -- unless `--url` is
passed, which points the driver at a remote deployment (e.g. the Cloud Run
URL) instead and skips the localhost check entirely. This is how the
Cloud Run deploy was verified as actually working, not just returning
HTTP 200:

```bash
.venv/Scripts/python.exe .claude/skills/run-ttb-label-verification/driver.py batch --url https://ttb-label-verification-763207276979.us-east5.run.app
```

## Run (human path)

```bash
.venv/Scripts/python.exe -m streamlit run app.py
```

Opens `http://localhost:8501` for a normal browser session. Ctrl-C to stop.

## Direct invocation (no browser, fastest iteration loop)

If the change is in `matching.py` or `extraction.py` rather than the UI
wiring in `app.py`, skip the browser entirely -- this is how most of this
project's logic bugs were actually found and fixed during development:

```bash
.venv/Scripts/python.exe -c "
from dotenv import load_dotenv; load_dotenv()
from extraction import extract_label_fields
from matching import verify_fields, overall_verdict
from models import ApplicationData

with open('sample_data/old-tom-bourbon.png', 'rb') as f:
    extracted, latency = extract_label_fields(f.read(), 'old-tom-bourbon.png')
app = ApplicationData('OLD TOM DISTILLERY', 'Kentucky Straight Bourbon Whiskey', '45% Alc./Vol. (90 Proof)', '750 mL')
fields = verify_fields(app, extracted)
print(overall_verdict(fields), f'{latency:.2f}s')
"
```

## Test

No pytest suite exists yet. Validation so far has been the direct-invocation
pattern above run against `sample_data/label_test_plan.md`'s 6 labels (each
has a documented expected verdict) -- see that file for the full matrix.

## Gotchas

- **Streamlit `text_input` widgets don't commit on `.fill()` alone.**
  Playwright's `.fill()` sets the value and fires input events, but
  Streamlit only pushes the new value to session state on blur/Enter --
  until then the field visibly shows "Press Enter to apply" and the value
  never reaches the server. Symptom: the "Verify Label" button stays
  disabled forever even though `image_file` was uploaded successfully,
  because leaving a field in that pending state appears to block
  Streamlit's rerun cycle more broadly, not just that one field. Fix:
  `field.press("Tab")` after every `.fill()` (see `driver.py`'s `cmd_single`).
  This was intermittent and confusing to debug precisely because it
  sometimes worked anyway depending on incidental timing.
- **File-upload chip filenames are truncated in the UI**
  (`old-tom...bourbon.png`), so waiting for `text=<full filename>` to
  appear times out. Poll the button's `is_enabled()` state directly
  instead of matching on filename text.
- **Both tabs' widgets are mounted in the DOM simultaneously** -- Streamlit
  hides the inactive tab via CSS, it doesn't unmount it. `input[type="file"]`
  returns 3 elements (single-image, batch-CSV, batch-images) regardless of
  which tab is visually active. Disambiguate via `accept` (contains `.csv`
  or not) and `multiple` (present or not), not DOM position -- `.first`
  is not reliably the right one.
- **Right after clicking a tab, its file inputs may not be mounted yet.**
  A `page.locator('input[type="file"]').count()` called immediately after
  `tab.click()` can return 0. Locators re-resolve lazily at action time
  though, so calling `.set_input_files()` on a locator obtained slightly
  too early still works once Streamlit finishes mounting -- just don't
  `count()`-and-cache before that happens.
- **`temperature` is rejected outright by Claude Sonnet 5**, not just
  ignored -- `client.messages.create(..., temperature=0)` raises
  `BadRequestError: temperature is deprecated for this model`. Don't pass it.
- **A Secret Manager value created by piping shell output can carry a
  trailing newline**, e.g. `grep KEY .env | cut -d= -f2- | gcloud secrets
  create ... --data-file=-`. The app doesn't fail to authenticate with
  that -- it fails earlier and more confusingly, with
  `httpx.LocalProtocolError: Illegal header value b'sk-ant-...\n'` buried
  inside a generic `anthropic.APIConnectionError: Connection error.` at
  the top level. `echo -n` (no trailing newline) when creating the secret,
  or `| tr -d '\n' |` in the pipeline, avoids it. Verify by comparing
  `wc -c` locally against `gcloud secrets versions access <n> --secret=...
  | wc -c` -- byte counts should match exactly.
- **This same "Connection error." string is also what you'd see if
  `python:3.11-slim`'s CA trust store were the problem** (outbound HTTPS
  failing to verify) -- both were live suspects when this was first hit
  in Cloud Run, and the *real* error text (`Illegal header value`) was
  only visible after fixing the next gotcha below, which had been hiding
  it entirely.
- **`app.py`'s exception handler caught and stringified errors for the UI
  but never logged them**, so Cloud Run's logs showed nothing useful even
  though every single label was failing. `logger.exception(...)` next to
  the `except` is what actually surfaced the traceback that led to the
  two gotchas above. If you add new try/except blocks to this app,
  log inside them, not just display-in-UI.

## Troubleshooting

- **`venv python not found`**: `.venv` doesn't exist or isn't at the
  project root. Create it with `py -3.12 -m venv .venv` (not plain
  `python`, which resolves to an old Anaconda env on this machine).
- **`server not running -- run start first`**: `batch`/`single` check
  `http://localhost:8501` before doing anything; run `start` first, or
  check `streamlit_driver.log` if `start` itself failed.
- **`Run Batch Verification is disabled`**: means the CSV or images
  didn't actually attach -- check `batch-error-disabled.png` in `shots/`
  and verify the CSV's `filename` column matches the uploaded images'
  filenames exactly (batch mode matches by filename, not order).
- **`ANTHROPIC_API_KEY` missing / 401 from Anthropic**: `.env` isn't set
  up, or `python-dotenv` isn't loading it -- `app.py` calls `load_dotenv()`
  at import time, so this should be automatic if `.env` exists at the
  project root with a valid key.
