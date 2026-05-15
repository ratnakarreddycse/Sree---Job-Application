# Job Applications

Practical job-application pipeline for fast, focused applications.

This project helps you:

- clean and validate raw job records
- score roles for fit (data engineering defaults)
- apply H1B-aware filtering signals
- produce a prioritized queue for immediate applications

## Project layout

- `src/job_applications/`: pipeline package and CLI entry point
- `tests/`: focused tests for pipeline behavior
- `.github/workflows/ci.yml`: basic CI for tests

## Quick start

```bash
/usr/bin/python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .[dev]
pytest
python -m job_applications.cli --input applications.json --top 20 --export-csv top_jobs.csv
```

## Input format

The CLI expects a JSON array of objects with at least:

- `company`
- `role`
- `status`

Example:

```json
[
  {
    "company": "Contoso",
    "role": "Data Engineer",
    "status": "new",
    "notes": "Remote in USA. H1B visa transfer supported. Python SQL ETL Airflow"
  }
]
```

## CLI options

Common usage:

```bash
python -m job_applications.cli \
  --input applications.json \
  --top 25 \
  --output summary.json \
  --export-csv top_jobs.csv
```

Daily run mode (date-stamped outputs + draft files):

```bash
python -m job_applications.cli \
  --input applications.json \
  --daily-run \
  --daily-output-root outputs
```

This creates files like:

- `outputs/YYYY-MM-DD/summary.json`
- `outputs/YYYY-MM-DD/top_jobs.csv`
- `outputs/YYYY-MM-DD/drafts/*.md`

Generate a macOS launchd file for automatic daily runs:

```bash
python -m job_applications.cli \
  --input applications.json \
  --daily-run \
  --daily-output-root outputs \
  --write-macos-launchd \
  --launchd-hour 8 \
  --launchd-minute 0
```

This writes a plist file at `scheduler/com.jobapplications.daily.plist` by default.

Generate and install in one command:

```bash
python -m job_applications.cli \
  --input applications.json \
  --daily-run \
  --daily-output-root outputs \
  --write-macos-launchd \
  --install-macos-launchd
```

Uninstall the launchd agent:

```bash
python -m job_applications.cli --uninstall-macos-launchd
```

Check launchd status:

```bash
python -m job_applications.cli --status-macos-launchd
```

Check combined health (scheduler + latest outputs freshness):

```bash
python -m job_applications.cli --health-report --daily-output-root outputs --freshness-days 1
```

Load it with launchctl:

```bash
mkdir -p "$HOME/Library/LaunchAgents"
cp scheduler/com.jobapplications.daily.plist "$HOME/Library/LaunchAgents/"
launchctl unload "$HOME/Library/LaunchAgents/com.jobapplications.daily.plist" 2>/dev/null || true
launchctl load "$HOME/Library/LaunchAgents/com.jobapplications.daily.plist"
```

You can also ingest from CSV:

```bash
python -m job_applications.cli --input jobs.csv --top 25 --export-csv top_jobs.csv
```

And optionally ingest from one or more RSS feeds:

```bash
python -m job_applications.cli \
  --input applications.json \
  --rss-url "https://example.com/jobs.rss" \
  --rss-url "https://example2.com/feed.xml" \
  --rss-limit 20 \
  --top 25 \
  --output summary.json \
  --export-csv top_jobs.csv
```

Profile tuning:

- `--target-titles "data engineer,analytics engineer"`
- `--required-keywords "python,sql,etl"`
- `--preferred-keywords "airflow,dbt,spark,snowflake,databricks"`
- `--preferred-locations "remote,usa"`
- `--no-require-visa-support` to disable visa-based filtering
- `--no-dedupe` to keep duplicate source records
- `--drafts-dir` to set a custom folder for generated drafts
- `--daily-run` to auto-write date-stamped output files
- `--daily-output-root` to set the root folder for daily output
- `--write-macos-launchd` to generate a launchd plist for daily automation
- `--install-macos-launchd` to install and load the plist in LaunchAgents
- `--uninstall-macos-launchd` to unload and remove the LaunchAgents plist
- `--status-macos-launchd` to show whether the agent is installed and loaded
- `--health-report` to show scheduler state and output freshness in one JSON response
- `--launchd-hour` and `--launchd-minute` to set schedule time
- `--launchd-plist-path` to customize plist output path
- `--launchd-agent-dir` to customize install location (default `~/Library/LaunchAgents`)
- `--freshness-days` to define output freshness threshold for health checks

## Output

The pipeline returns:

- record-level counts (`accepted_records`, `rejected_records`)
- source record count after ingestion (`source_records`)
- status totals (`status_breakdown`)
- action totals (`action_breakdown`: `apply_now`, `review_fast`, `backlog`, `skip`)
- `top_recommendations` sorted by score descending

Generated draft files are created for `apply_now` and `review_fast` recommendations.

## Assisted UI (Buttons)

You can start a local button-based UI for assisted applications.

1. Copy `portal_config.sample.json` to `portal_config.json` and customize URLs.
2. Start UI server:

```bash
python -m job_applications.ui --config portal_config.json --open-browser
```

The UI provides platform buttons (LinkedIn, Indeed, Dice, Greenhouse, Lever, Workday) and a `Run Pipeline Now` button.

Assisted mode behavior:

- Platform button opens your saved search URLs in browser tabs.
- Pipeline button runs scoring + daily output generation.
- You review each form and click final submit manually.

This avoids fragile full auto-submit behavior on third-party portals and keeps you in control of final submissions.

## Browser Autofill Extension (Phase 2)

To auto-populate details on supported job portals after opening a job page from the dashboard, load the extension in:

- `job-apply-autofill-extension/`

### Install (Chrome/Edge)

1. Open `chrome://extensions` (or `edge://extensions`)
2. Enable Developer mode
3. Click Load unpacked
4. Select folder `job-apply-autofill-extension`

### Use

1. Start dashboard UI:

```bash
python -m job_applications.ui --config portal_config.json --open-browser
```

2. In extension popup, click `Sync From Dashboard (localhost)`
3. Open a job posting (from dashboard `Apply Now` button)
4. Click extension `Run Autofill On This Tab`
5. If you see a recurring screening question, add it once in popup `Remember One Q/A`

From second time onward, saved question-answer pairs are reused automatically on supported portals.

Built-in smart mappers currently target:

- LinkedIn Easy Apply-style forms
- Greenhouse application forms
- Lever application forms
- Workday / MyWorkdayJobs forms

When a field is not matched by a portal mapper, the extension falls back to a generic label/placeholder-based matcher.

### Notes

- This tool assists autofill; it does not auto-click final submit.
- You remain in control of final review and submission.
