# Mainframe Job Monitor

Real-time dashboard for monitoring Mainframe batch job statuses via ODBC. Built with FastAPI and a lightweight vanilla JS frontend.

## Features

- **Job Status Dashboard** — Table and grid views with live status badges (Running, Completed, Waiting, Failed, Queued, Cancelled)
- **Filtering & Search** — Filter by status, frequency (Daily/Weekly/Monthly), date range, and free-text search across job name, ID, owner
- **SQL Pagination** — Server-side `LIMIT/OFFSET` pagination (no full-table scan)
- **Summary Cards** — Clickable cards showing job counts per status
- **Job Detail Modal** — Click any job row/card to see full details (owner, schedule, duration, wait reasons, errors)
- **Dark/Light Theme** — Toggle with persistence in `localStorage`
- **Loading Skeletons** — Shimmer placeholders while data loads
- **Accessibility** — ARIA labels, keyboard navigation, focus trap in modal, screen reader announcements, `prefers-reduced-motion` support
- **Demo / Production Mode Toggle** — Switch between curated sample data and live DB2 data from the header (persisted server-side, see [Application Modes](#application-modes-demo-vs-production))
- **Readable Typography** — Inter font with enlarged table/body text; table scrolls horizontally so columns keep their widths

## Project Structure

```
021_BMO_MainframeApp/
├── main.py              # FastAPI app, startup/shutdown, health endpoint
├── config.py            # Settings from .env via dataclass
├── database.py          # ODBC connection wrapper (pyodbc)
├── models.py            # Pydantic models & enums
├── services.py          # Business logic, SQL queries, demo data
├── routers/
│   └── jobs.py          # REST API endpoints
├── static/
│   ├── index.html       # Single-page dashboard
│   ├── css/styles.css   # Theme variables, skeleton loading
│   └── js/app.js        # Frontend logic (fetch, render, modal, a11y)
├── .env.example         # Environment variable template
├── pyproject.toml       # Project metadata & dependencies
└── requirements.txt     # pip-compatible dependencies
```

## Application Modes (Demo vs Production)

The app has an explicit mode, stored server-side in `services.py` (`get_app_mode()` / `set_app_mode()`), seeded from `APP_MODE` at startup.

| | Demo | Production |
|---|---|---|
| Data source | 25 curated sample jobs in `_get_demo_jobs()` (9 completed, 4 running, 5 waiting, 3 failed, 2 queued, 2 cancelled) with realistic wait reasons and error messages | Live IBM DB2 via ODBC (`JOB_STATUS_TABLE`) |
| DB2 unreachable | N/A (no DB call) | **No fallback** — API returns `HTTP 503`, job list empties, summary cards reset to 0, badge shows `Connection Error` |
| Badge | `Demo Mode — Sample Data` (amber) | `Connected — Live` (green) |
| Switch | Header **Demo / Production** toggle → `POST /api/mode` → data refreshes | Same toggle back |

Sample-data highlights: fixed job IDs (`JOB_INVOICE`, `JOB_PAYROLL`, `JOB_FRDSCREEN`, …), status-appropriate details (wait reasons only on `WAITING`, e.g. tape mount / MQ queue / DB lock; errors only on `FAILED`, e.g. SOC7 abend / ORA-00001 / JCL error), and start times spread over the last 12 hours. Filters, search, and pagination all work against the sample set.

To default to live data on startup, set `APP_MODE=production` in `.env`.

## Prerequisites

- Python 3.12+
- IBM DB2 ODBC driver installed on your system

### Installing the IBM DB2 ODBC Driver

The DB2 driver is a **system-level** package (not installed via pip):

| Platform | Installation |
|----------|-------------|
| RHEL/CentOS | `sudo yum install -y ibm_db2-devel` |
| Ubuntu/Debian | Download from [IBM](https://www.ibm.com/docs/en/db2/11.5?topic=drivers-python) |
| macOS | `brew install --cask ibm-db2-odbc-driver` |
| Windows | [Download installer](https://www.ibm.com/support/pages/db2-odbc-driver-download) |

## Quick Start

```bash
# Clone and enter the project
cd 021_BMO_MainframeApp

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt
# Or with uv:
# uv pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your Mainframe ODBC credentials

# Run the app
python main.py
```

The dashboard opens at **http://localhost:8000**.

### Running with uv (recommended)

```bash
uv venv
uv pip install -r requirements.txt
python main.py
```

## Configuration

All settings are in `.env` (copy from `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `ODBC_DRIVER` | `{IBM DB2 ODBC DRIVER}` | ODBC driver name (platform-specific) |
| `ODBC_HOST` | `localhost` | Mainframe hostname or IP |
| `ODBC_PORT` | `50000` | DB2 port |
| `ODBC_DATABASE` | `MFGDB` | Database name |
| `ODBC_UID` | — | Username |
| `ODBC_PWD` | — | Password |
| `APP_HOST` | `0.0.0.0` | Server bind address |
| `APP_PORT` | `8000` | Server port |
| `APP_DEBUG` | `false` | Enable auto-reload |
| `APP_MODE` | `demo` | Startup mode: `demo` (sample data) or `production` (live DB2) |

## Production Setup

End-to-end guide to switch from sample data to your live mainframe. (Background details live under [Database Configuration](#database-configuration) and [Application Modes](#application-modes-demo-vs-production).)

### Step 1 — Install the DB2 ODBC driver

The driver is a **system package**, not a pip package. Pick your platform from [Prerequisites](#prerequisites), then verify Python can reach the mainframe:

```bash
./venv/bin/python -c "
import pyodbc
conn = pyodbc.connect('DRIVER={IBM DB2 ODBC DRIVER};HOST=your-host;PORT=50000;DATABASE=MFGDB;UID=user;PWD=pass;')
print('Connected:', conn.getinfo(0))
conn.close()
"
```

If this fails, the app's Production mode will return `503` — fix connectivity before continuing.

### Step 2 — Configure credentials

```bash
cp .env.example .env
```

Edit `.env` with your real values:

```
ODBC_DRIVER={IBM DB2 ODBC DRIVER}   # or the full .so path on Linux
ODBC_HOST=your-mainframe-host
ODBC_PORT=50000
ODBC_DATABASE=MFGDB
ODBC_UID=your_username
ODBC_PWD=your_password
APP_MODE=production
```

### Step 3 — Point the queries at your real table

In `services.py`, replace the placeholder `JOB_STATUS_TABLE` in `get_all_jobs()`, `get_all_jobs_count()`, and `get_paginated_jobs()`, and align `SELECT_COLUMNS` with your scheduler's column names (see [Expected Table Schema](#expected-table-schema) and the CA-7 / Control-M / TWS reference). For complex schemas, create the `V_JOB_MONITOR` view from [Using Views](#using-views) and point the queries at it instead.

### Step 4 — Use DB2 pagination syntax

In `get_paginated_jobs()`, replace the generic paging clause:

```sql
-- Before (not valid on DB2):
ORDER BY LAST_UPDATED DESC LIMIT ? OFFSET ?
-- After (DB2):
ORDER BY LAST_UPDATED DESC OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
```

passing `offset` first, then `page_size`.

### Step 5 — Map your scheduler's codes

Update `_map_status()` and `_map_frequency()` in `services.py` with your scheduler's status/frequency codes (tables under [Status Code Mapping](#status-code-mapping)). At minimum, cover your waiting codes so the Wait Reason column displays, and check the `WHERE JOB_STATUS = 'WAITING'` filter if your DB stores short codes (`PEND`, `WAI`, …) instead of full words.

### Step 6 — Run and verify

```bash
python main.py
curl -s localhost:8000/api/health          # expect "mode": "production"
curl -s "localhost:8000/api/jobs?page=1&page_size=10"  # expect 200 with your rows
```

Open the dashboard — the badge should read `Connected — Live`. The header toggle (`POST /api/mode`) switches back to sample data anytime without restarting.

### Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `/api/jobs` → `503 pyodbc/ODBC driver not installed` | `pyodbc` missing or driver `.so` not found | Reinstall driver, check `ODBC_DRIVER` path |
| `/api/jobs` → `503 ... SQLDriverConnect` | Wrong host/port/credentials | Verify with the `isql`/Python snippet in [Connecting to DB2](#connecting-to-db2) |
| `/api/jobs` → `200` but `items: []` | Table name/columns don't match your schema | Recheck Step 3; query the table directly via `isql` |
| Rows show `UNKNOWN` status, no Wait Reason | Codes not in `_map_status()` | Recheck Step 5 |
| Empty list + `Connection Error` badge | Any of the above (Production never falls back to demo data) | Check server logs for `Production DB ... failed` lines |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Dashboard UI |
| `GET` | `/api/health` | Health check (includes current `mode`) |
| `GET` | `/api/mode` | Current mode (`{"mode": "demo" \| "production"}`) |
| `POST` | `/api/mode` | Switch mode (`{"mode": "demo" \| "production"}`; anything else → `400`) |
| `GET` | `/api/jobs` | Paginated jobs (filters: `status`, `frequency`, `search`, `date_from`, `date_to`, `page`, `page_size`). Returns `{items, total, page, page_size, total_pages}` — the frontend unwraps `items`. In Production with no DB → `503` |
| `GET` | `/api/jobs/summary` | Job counts by status. In Production with no DB → `503` (frontend resets cards to 0) |
| `GET` | `/api/jobs/{job_id}` | Single job detail |
| `GET` | `/api/jobs/{job_id}/history` | Job run history |
| `GET` | `/api/jobs/{job_id}/trends` | Job trend data |

## Database Configuration

### Production Behavior (No Silent Fallback)

In Production mode every DB call (`get_all_jobs`, `get_all_jobs_count`, `get_paginated_jobs`) queries DB2 directly. On any failure (missing `pyodbc`, bad driver, unreachable host, SQL error) it raises `ConnectionError("Mainframe DB2 unavailable: ...")`, which the routers translate to `HTTP 503`. The UI then clears the job list, zeroes the summary cards, and shows `Connection Error`. Sample data is **never** mixed into Production responses.

### Going Live Checklist (Demo → Production Data)

Right now Production queries a **placeholder** table, so these 5 changes are required before real data flows:

1. **Install the DB2 ODBC driver** (system package, not pip) — see [Prerequisites](#prerequisites) — and verify `pyodbc` can connect (test snippet under [Connecting to DB2](#connecting-to-db2)). Without this you get `503 file not found` / `pyodbc/ODBC driver not installed`.
2. **Set real credentials** in `.env` (`ODBC_DRIVER`, `ODBC_HOST`, `ODBC_PORT`, `ODBC_DATABASE`, `ODBC_UID`, `ODBC_PWD`) and `APP_MODE=production`, then restart (`python main.py`).
3. **Point the SQL at your real table/columns.** In `services.py`, replace `JOB_STATUS_TABLE` in `get_all_jobs()`, `get_all_jobs_count()`, and `get_paginated_jobs()`, and align `SELECT_COLUMNS` with your schema (or create the `V_JOB_MONITOR` view described under [Using Views](#using-views)). See the scheduler table-name reference below.
4. **Adapt pagination syntax to DB2.** The code uses `LIMIT ? OFFSET ?`, which DB2 does not accept. In `get_paginated_jobs()`, replace the paging clause with DB2 syntax:
   ```sql
   ... ORDER BY LAST_UPDATED DESC OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
   ```
   (passing `offset` first, then `page_size`).
5. **Map your status/frequency codes** in `_map_status()` / `_map_frequency()` (e.g. CA-7 or Control-M codes → `COMPLETED/RUNNING/WAITING/FAILED/QUEUED/CANCELLED`). Unmapped values show as `UNKNOWN` and hide the Wait Reason cell, so cover at least your waiting codes. Note the SQL status filter (`WHERE JOB_STATUS = 'WAITING'`) assumes full enum words — adjust it if your DB stores short codes.

**Verify:** open `GET /api/health` (should show `"mode": "production"`), then `GET /api/jobs?page=1&page_size=10` should return `200` with your rows instead of `503`. Flip back to sample data anytime via the header toggle (`POST /api/mode {"mode": "demo"}`).

### Connecting to DB2

The app connects via ODBC using the connection string built from your `.env` values:

```
DRIVER={IBM DB2 ODBC DRIVER};
HOST=your-host;
PORT=50000;
DATABASE=MFGDB;
UID=user;
PWD=pass;
```

**Verify your ODBC connection** before running the app:

```bash
# Linux/macOS — test with isql
isql -v "IBM DB2 ODBC DRIVER" your_user your_password

# Or with Python
python -c "
import pyodbc
conn = pyodbc.connect('DRIVER={IBM DB2 ODBC DRIVER};HOST=your-host;PORT=50000;DATABASE=MFGDB;UID=user;PWD=pass;')
print('Connected:', conn.catalog_name)
conn.close()
"
```

### Expected Table Schema

The app queries a single table. Create or adapt a table with this structure:

```sql
CREATE TABLE JOB_STATUS_TABLE (
    JOB_ID          VARCHAR(20)   NOT NULL,
    JOB_NAME        VARCHAR(100)  NOT NULL,
    JOB_STATUS      VARCHAR(20)   NOT NULL,
    JOB_FREQ        VARCHAR(10)   NOT NULL,
    SCHEDULE        VARCHAR(50),
    START_TIME      TIMESTAMP,
    END_TIME        TIMESTAMP,
    DURATION_MIN    DECIMAL(10,1),
    WAIT_REASON     VARCHAR(200),
    WAIT_SINCE      TIMESTAMP,
    ERROR_MSG       VARCHAR(500),
    JOB_OWNER       VARCHAR(20),
    LAST_UPDATED    TIMESTAMP
);

-- Recommended indexes for filtering and sorting
CREATE INDEX IDX_JOB_STATUS     ON JOB_STATUS_TABLE (JOB_STATUS);
CREATE INDEX IDX_JOB_FREQ       ON JOB_STATUS_TABLE (JOB_FREQ);
CREATE INDEX IDX_LAST_UPDATED   ON JOB_STATUS_TABLE (LAST_UPDATED DESC);
CREATE INDEX IDX_JOB_OWNER      ON JOB_STATUS_TABLE (JOB_OWNER);
```

### Column Mapping

Update `SELECT_COLUMNS` in `services.py` to map your actual column names:

```python
# Default column names (change these to match your schema)
SELECT_COLUMNS = """
    JOB_ID,
    JOB_NAME,
    JOB_STATUS,
    JOB_FREQ,
    SCHEDULE,
    START_TIME,
    END_TIME,
    DURATION_MIN,
    WAIT_REASON,
    WAIT_SINCE,
    ERROR_MSG,
    JOB_OWNER,
    LAST_UPDATED
"""
```

Also update the `FROM` clause in `get_all_jobs()` and `get_all_jobs_count()`:

```python
# Change this line in both functions:
query = f"SELECT {SELECT_COLUMNS} FROM YOUR_ACTUAL_TABLE WHERE 1=1 ..."
```

### Common Scheduler Table/Column Names

| Scheduler | Table | Status Column | ID Column |
|-----------|-------|---------------|-----------|
| CA-7 | `CA7JOBSTATUS` | `JOBSTATUS` | `JOBNAME` |
| Control-M | `CTM_JOB_HISTORY` | `RUN_STATUS` | `JOB_NAME` |
| IBM TWS | `IBMOPR.JOBSTATUS` | `STATUS` | `JOB_NAME` |
| Direct (JCL) | `SYSIBM.SYSPROCLIB` | N/A | `NAME` |

### Status Code Mapping

The app maps raw DB status codes to internal statuses. Update `_map_status()` in `services.py` if your DB uses different codes:

| Internal Status | Currently Recognized Codes |
|-----------------|---------------------------|
| `COMPLETED` | `CMP`, `COMP`, `COMPLETE`, `COMPLETED` |
| `RUNNING` | `RUN`, `RUNNING`, `ACT` |
| `WAITING` | `WAIT`, `WAI`, `WAITING`, `PEND`, `PENDIN` |
| `FAILED` | `FAILED`, `FAIL`, `ERR`, `ERROR` |
| `QUEUED` | `QUE`, `QUED`, `QUEUED`, `HOLD` |
| `CANCELLED` | `CAN`, `CANCEL`, `CANCELLED` |
| `UNKNOWN` | (anything not matched) |

Row conversion (`_row_to_job_record`) is NULL-safe: `None`/blank strings become `""` (IDs, names, schedule) or `None` (owner, wait reason, error), `DURATION_MIN` accepts `DECIMAL` via float cast, status/frequency mappers accept `None` and tolerate lowercase and `CHAR`-padded values, and unrecognized codes fall back to `UNKNOWN` (`JobFrequency` fallback is its own enum, not `JobStatus`). Every table column — including **Wait Reason** (shown whenever `job_status == "WAITING"`, with full text in the detail modal) — populates from its DB column when present.

One caveat: the SQL `WHERE JOB_STATUS = 'WAITING'` filter assumes the DB stores full enum words. If your mainframe stores short codes (`PEND`, `WAI`, …), adapt the filter or normalize values in your view.

Example — if your DB uses `S` for Success and `F` for Failure:

```python
def _map_status(raw: object) -> JobStatus:
    mapping = {
        "S": JobStatus.COMPLETED,
        "SUCCESS": JobStatus.COMPLETED,
        "OK": JobStatus.COMPLETED,
        "R": JobStatus.RUNNING,
        "ACTIVE": JobStatus.RUNNING,
        "W": JobStatus.WAITING,
        "PEND": JobStatus.WAITING,
        "F": JobStatus.FAILED,
        "ERROR": JobStatus.FAILED,
        "Q": JobStatus.QUEUED,
        "HOLD": JobStatus.QUEUED,
        "X": JobStatus.CANCELLED,
        "CANCEL": JobStatus.CANCELLED,
    }
    return mapping.get(raw.upper().strip(), JobStatus.UNKNOWN)
```

### Frequency Code Mapping

Similarly, update `_map_frequency()` if your DB uses different codes:

| Internal Frequency | Currently Recognized Codes |
|--------------------|---------------------------|
| `DAILY` | `D`, `DAY`, `DAILY` |
| `WEEKLY` | `W`, `WK`, `WEEKLY` |
| `MONTHLY` | `M`, `MO`, `MONTHLY` |
| `ONETIME` | `1`, `ONCE`, `ONETIME` |
| `UNKNOWN` | (anything not matched) |

### Reading from Multiple Tables (Joins)

If job data spans multiple tables, modify the query in `get_all_jobs()` to use a JOIN:

```python
query = f"""
    SELECT {SELECT_COLUMNS}
    FROM JOB_STATUS_TABLE j
    JOIN JOB_SCHEDULE_TABLE s ON j.JOB_ID = s.JOB_ID
    WHERE 1=1 {where_clause}
    ORDER BY j.LAST_UPDATED DESC
"""
```

### Using Views

If your schema is complex, create a database view and point the app at it:

```sql
CREATE VIEW V_JOB_MONITOR AS
SELECT
    j.JOB_ID,
    j.JOB_NAME,
    j.JOB_STATUS,
    s.JOB_FREQ,
    s.SCHEDULE,
    j.START_TIME,
    j.END_TIME,
    j.DURATION_MIN,
    j.WAIT_REASON,
    j.WAIT_SINCE,
    j.ERROR_MSG,
    j.JOB_OWNER,
    j.LAST_UPDATED
FROM CA7JOBSTATUS j
LEFT JOIN CA7SCHEDULE s ON j.JOBNAME = s.JOBNAME;
```

Then set the table name to `V_JOB_MONITOR` in `services.py`.

## UI Notes

- **Font** — Inter from Google Fonts (`index.html`), with system fallbacks (`-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`) when offline.
- **Readability** — Base font is 16px; the job table renders at ~15px with 1.5 line-height, larger status/frequency badges, and larger cell text. Column widths are preserved via unchanged padding, fixed wait-reason `max-width`, `nowrap` only on date columns, and horizontal scrolling on the table container.
- **Empty states** — Demo fetch failure keeps the error badge; Production DB failure clears rows, zeroes all summary cards, shows `Connection Error`, and announces the outage to screen readers.

## License

Internal use.
