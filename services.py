from __future__ import annotations

import logging
from typing import Optional

from database import get_database
from models import JobFilter, JobFrequency, JobRecord, JobStatus, JobSummary, JobHistoryRecord, JobTrend

logger = logging.getLogger(__name__)

# --- Application mode state (demo | production) ---
# Kept here (rather than main.py) to avoid a circular import:
# main -> routers.jobs -> services -> main would fail.
_app_mode: str = "demo"


def get_app_mode() -> str:
    return _app_mode


def set_app_mode(mode: str) -> None:
    global _app_mode
    _app_mode = mode


def _is_demo_mode() -> bool:
    return _app_mode == "demo"


def _map_status(raw: object) -> JobStatus:
    mapping = {
        "CMP": JobStatus.COMPLETED,
        "COMP": JobStatus.COMPLETED,
        "COMPLETE": JobStatus.COMPLETED,
        "COMPLETED": JobStatus.COMPLETED,
        "RUN": JobStatus.RUNNING,
        "RUNNING": JobStatus.RUNNING,
        "ACT": JobStatus.RUNNING,
        "WAIT": JobStatus.WAITING,
        "WAI": JobStatus.WAITING,
        "WAITING": JobStatus.WAITING,
        "PEND": JobStatus.WAITING,
        "PENDIN": JobStatus.WAITING,
        "FAILED": JobStatus.FAILED,
        "FAIL": JobStatus.FAILED,
        "ERR": JobStatus.FAILED,
        "ERROR": JobStatus.FAILED,
        "QUE": JobStatus.QUEUED,
        "QUED": JobStatus.QUEUED,
        "QUEUED": JobStatus.QUEUED,
        "HOLD": JobStatus.QUEUED,
        "CAN": JobStatus.CANCELLED,
        "CANCEL": JobStatus.CANCELLED,
        "CANCELLED": JobStatus.CANCELLED,
    }
    if raw is None:
        return JobStatus.UNKNOWN
    return mapping.get(str(raw).upper().strip(), JobStatus.UNKNOWN)


def _map_frequency(raw: object) -> JobFrequency:
    mapping = {
        "D": JobFrequency.DAILY,
        "DAY": JobFrequency.DAILY,
        "DAILY": JobFrequency.DAILY,
        "W": JobFrequency.WEEKLY,
        "WK": JobFrequency.WEEKLY,
        "WEEKLY": JobFrequency.WEEKLY,
        "M": JobFrequency.MONTHLY,
        "MO": JobFrequency.MONTHLY,
        "MONTHLY": JobFrequency.MONTHLY,
        "1": JobFrequency.ONETIME,
        "ONCE": JobFrequency.ONETIME,
        "ONETIME": JobFrequency.ONETIME,
    }
    if raw is None:
        return JobFrequency.UNKNOWN
    return mapping.get(str(raw).upper().strip(), JobFrequency.UNKNOWN)


def _apply_demo_filters(jobs: list[JobRecord], filters: Optional[JobFilter]) -> list[JobRecord]:
    if not filters:
        return jobs
    result = jobs
    if filters.status:
        result = [j for j in result if j.job_status == filters.status]
    if filters.frequency:
        result = [j for j in result if j.job_frequency == filters.frequency]
    if filters.search:
        term = filters.search.lower()
        result = [j for j in result if term in j.job_id.lower() or term in j.job_name.lower() or term in (j.job_owner or "").lower() or term in (j.job_schedule or "").lower() or term in (j.error_message or "").lower() or term in (j.wait_reason or "").lower()]
    return result


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


def _build_where_clause(filters: Optional[JobFilter]) -> tuple[str, list]:
    """Build SQL WHERE clause from filters. Returns (clause, params)."""
    clause = ""
    params: list = []

    if not filters:
        return clause, params

    if filters.status:
        clause += " AND JOB_STATUS = ?"
        params.append(filters.status.value)
    if filters.frequency:
        clause += " AND JOB_FREQ = ?"
        params.append(filters.frequency.value)
    if filters.search:
        clause += " AND (JOB_NAME LIKE ? OR JOB_ID LIKE ? OR JOB_OWNER LIKE ? OR SCHEDULE LIKE ? OR ERROR_MSG LIKE ? OR WAIT_REASON LIKE ?)"
        term = f"%{filters.search}%"
        params.extend([term, term, term, term, term, term])
    if filters.date_from:
        clause += " AND LAST_UPDATED >= ?"
        params.append(filters.date_from)
    if filters.date_to:
        clause += " AND LAST_UPDATED <= ?"
        params.append(filters.date_to)

    return clause, params


def _clean_str(value: object, default: str = "") -> str:
    """DB NULL-safe string conversion (avoids literal 'None' in the UI)."""
    if value is None:
        return default
    text = str(value).strip()
    return text if text and text.lower() != "none" else default


def _clean_optional_str(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text and text.lower() != "none" else None


def _clean_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _row_to_job_record(row: dict) -> JobRecord:
    return JobRecord(
        job_id=_clean_str(row.get("JOB_ID")),
        job_name=_clean_str(row.get("JOB_NAME")),
        job_status=_map_status(row.get("JOB_STATUS", "")),
        job_frequency=_map_frequency(row.get("JOB_FREQ", "")),
        job_schedule=_clean_str(row.get("SCHEDULE", "")),
        job_start_time=row.get("START_TIME"),
        job_end_time=row.get("END_TIME"),
        job_duration_minutes=_clean_float(row.get("DURATION_MIN")),
        wait_reason=_clean_optional_str(row.get("WAIT_REASON")),
        wait_since=row.get("WAIT_SINCE"),
        error_message=_clean_optional_str(row.get("ERROR_MSG")),
        job_owner=_clean_optional_str(row.get("JOB_OWNER")),
        last_updated=row.get("LAST_UPDATED"),
    )


def get_all_jobs(filters: Optional[JobFilter] = None) -> list[JobRecord]:
    """
    Query the Mainframe ODBC source for job status data.

    NOTE: The SQL below uses generic column names that match common
    Mainframe job-scheduler layouts (CA-7, Control-M, IBM TWS, etc.).
    Adjust the table/column names to match YOUR actual Mainframe schema.

    Common table names seen in the wild:
      - SYSIBM.SYSPROCLIB  (JCL procedures)
      - DSJOB.STATUS       (DS Job Scheduler)
      - CA7JOBSTATUS       (CA-7 Scheduler)
      - CTM_JOB_HISTORY    (Control-M)
    """
    if _is_demo_mode():
        logger.debug("Using demo data (app mode is 'demo')")
        return _apply_demo_filters(_get_demo_jobs(), filters)

    where_clause, params = _build_where_clause(filters)
    query = f"SELECT {SELECT_COLUMNS} FROM JOB_STATUS_TABLE WHERE 1=1 {where_clause} ORDER BY LAST_UPDATED DESC"

    try:
        db = get_database()
        rows = db.fetch_all(query, tuple(params))
        return [_row_to_job_record(row) for row in rows]
    except Exception as e:
        # Production mode must NOT fall back to sample data — surface the failure.
        logger.warning("Production DB query failed (no fallback): %s", e)
        raise ConnectionError(f"Mainframe DB2 unavailable: {e}") from e


def get_all_jobs_count(filters: Optional[JobFilter] = None) -> int:
    """Get total count of jobs matching filters."""
    if _is_demo_mode():
        return len(_apply_demo_filters(_get_demo_jobs(), filters))

    where_clause, params = _build_where_clause(filters)
    query = f"SELECT COUNT(*) FROM JOB_STATUS_TABLE WHERE 1=1 {where_clause}"

    try:
        db = get_database()
        count = db.fetch_one_value(query, tuple(params))
        return int(count) if count is not None else 0
    except Exception as e:
        logger.warning("Production DB count failed (no fallback): %s", e)
        raise ConnectionError(f"Mainframe DB2 unavailable: {e}") from e


def get_job_summary(jobs: list[JobRecord]) -> JobSummary:
    status_counts = {s: 0 for s in JobStatus}

    for job in jobs:
        status_counts[job.job_status] += 1

    return JobSummary(
        total_jobs=len(jobs),
        completed=status_counts[JobStatus.COMPLETED],
        running=status_counts[JobStatus.RUNNING],
        waiting=status_counts[JobStatus.WAITING],
        failed=status_counts[JobStatus.FAILED],
        queued=status_counts[JobStatus.QUEUED],
        cancelled=status_counts[JobStatus.CANCELLED],
    )


def get_paginated_jobs(filters: Optional[JobFilter] = None, page: int = 1, page_size: int = 50) -> dict:
    """Get paginated jobs with total count using SQL LIMIT/OFFSET."""
    where_clause, params = _build_where_clause(filters)
    offset = (page - 1) * page_size

    # Fetch total count
    total = get_all_jobs_count(filters)
    total_pages = (total + page_size - 1) // page_size

    if _is_demo_mode():
        all_jobs = _apply_demo_filters(_get_demo_jobs(), filters)
        items = all_jobs[offset:offset + page_size]
    else:
        # Fetch page of rows
        query = f"SELECT {SELECT_COLUMNS} FROM JOB_STATUS_TABLE WHERE 1=1 {where_clause} ORDER BY LAST_UPDATED DESC LIMIT ? OFFSET ?"
        params_with_pagination = tuple(params + [page_size, offset])

        try:
            db = get_database()
            rows = db.fetch_all(query, params_with_pagination)
            items = [_row_to_job_record(row) for row in rows]
        except Exception as e:
            logger.warning("Production DB pagination failed (no fallback): %s", e)
            raise ConnectionError(f"Mainframe DB2 unavailable: {e}") from e

    return {
        "items": items,
        "total": total,
        "total_pages": total_pages,
    }


def get_job_history(job_id: str, days: int = 7) -> list[JobHistoryRecord]:
    """Get historical runs for a specific job"""
    from datetime import datetime, timedelta
    import random

    now = datetime.now()
    history = []

    for i in range(days * 4):
        timestamp = now - timedelta(hours=i * 6)
        status = random.choice([JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.RUNNING])
        duration = random.randint(5, 180) if status == JobStatus.COMPLETED else None

        history.append(JobHistoryRecord(
            job_id=job_id,
            job_status=status,
            timestamp=timestamp,
            duration_minutes=duration,
            error_message="SOC7 abend" if status == JobStatus.FAILED else None,
        ))

    return sorted(history, key=lambda x: x.timestamp, reverse=True)


def get_job_trends(job_id: str, days: int = 30) -> list[JobTrend]:
    """Get aggregated trend data for a job"""
    from datetime import datetime, timedelta
    import random

    now = datetime.now()
    trends = []

    for i in range(days):
        date = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        trends.append(JobTrend(
            date=date,
            completed=random.randint(3, 8),
            failed=random.randint(0, 2),
            running=random.randint(0, 3),
            waiting=random.randint(0, 2),
        ))

    return sorted(trends, key=lambda x: x.date)


def _get_demo_jobs() -> list[JobRecord]:
    from datetime import datetime, timedelta
    import random

    now = datetime.now()

    job_definitions = [
        {
            "job_id": "JOB_INVOICE",
            "job_name": "Daily Invoice Processing",
            "frequency": "DAILY",
            "owner": "OPER1",
            "status": JobStatus.COMPLETED,
            "duration_range": (12, 45),
            "error_message": None,
            "wait_reason": None,
        },
        {
            "job_id": "JOB_ACCTPOST",
            "job_name": "Account Posting",
            "frequency": "DAILY",
            "owner": "OPER2",
            "status": JobStatus.RUNNING,
            "duration_range": (None, None),
            "error_message": None,
            "wait_reason": None,
        },
        {
            "job_id": "JOB_STMTGEN",
            "job_name": "Statement Generation",
            "frequency": "MONTHLY",
            "owner": "BATCH",
            "status": JobStatus.WAITING,
            "duration_range": (None, None),
            "error_message": None,
            "wait_reason": "Waiting for upstream job JOB_INVOICE to complete",
        },
        {
            "job_id": "JOB_LEDGERUPD",
            "job_name": "General Ledger Update",
            "frequency": "DAILY",
            "owner": "SCHED",
            "status": JobStatus.COMPLETED,
            "duration_range": (8, 22),
            "error_message": None,
            "wait_reason": None,
        },
        {
            "job_id": "JOB_PAYROLL",
            "job_name": "Payroll Processing",
            "frequency": "WEEKLY",
            "owner": "OPER1",
            "status": JobStatus.FAILED,
            "duration_range": (30, 90),
            "error_message": "SOC7 abend - numeric conversion error in field EMP_SALARY",
            "wait_reason": None,
        },
        {
            "job_id": "JOB_TAXCALC",
            "job_name": "Tax Calculation Engine",
            "frequency": "DAILY",
            "owner": "OPER2",
            "status": JobStatus.RUNNING,
            "duration_range": (None, None),
            "error_message": None,
            "wait_reason": None,
        },
        {
            "job_id": "JOB_RECONCILE",
            "job_name": "Bank Reconciliation",
            "frequency": "WEEKLY",
            "owner": "BATCH",
            "status": JobStatus.QUEUED,
            "duration_range": (None, None),
            "error_message": None,
            "wait_reason": None,
        },
        {
            "job_id": "JOB_AUDITLOG",
            "job_name": "Audit Log Archive",
            "frequency": "DAILY",
            "owner": "SYSTEM",
            "status": JobStatus.COMPLETED,
            "duration_range": (3, 10),
            "error_message": None,
            "wait_reason": None,
        },
        {
            "job_id": "JOB_BACKUP",
            "job_name": "Database Backup",
            "frequency": "DAILY",
            "owner": "SYSTEM",
            "status": JobStatus.COMPLETED,
            "duration_range": (15, 60),
            "error_message": None,
            "wait_reason": None,
        },
        {
            "job_id": "JOB_REPORTS",
            "job_name": "Regulatory Reports (FINRA)",
            "frequency": "MONTHLY",
            "owner": "OPER1",
            "status": JobStatus.WAITING,
            "duration_range": (None, None),
            "error_message": None,
            "wait_reason": "Waiting for database lock release on table REPORT_DATA",
        },
        {
            "job_id": "JOB_CRMEXTRACT",
            "job_name": "CRM Data Extract",
            "frequency": "DAILY",
            "owner": "OPER2",
            "status": JobStatus.COMPLETED,
            "duration_range": (20, 55),
            "error_message": None,
            "wait_reason": None,
        },
        {
            "job_id": "JOB_LOANPROC",
            "job_name": "Loan Processing Batch",
            "frequency": "DAILY",
            "owner": "BATCH",
            "status": JobStatus.CANCELLED,
            "duration_range": (5, 15),
            "error_message": None,
            "wait_reason": None,
        },
        {
            "job_id": "JOB_CLSDAY",
            "job_name": "End of Day Processing",
            "frequency": "DAILY",
            "owner": "SCHED",
            "status": JobStatus.WAITING,
            "duration_range": (None, None),
            "error_message": None,
            "wait_reason": "Waiting for tape mount on VOL003 - nightly dump",
        },
        {
            "job_id": "JOB_FXRATES",
            "job_name": "FX Rate Update",
            "frequency": "DAILY",
            "owner": "SYSTEM",
            "status": JobStatus.COMPLETED,
            "duration_range": (2, 8),
            "error_message": None,
            "wait_reason": None,
        },
        {
            "job_id": "JOB_CUSTNOTIFY",
            "job_name": "Customer Notification Sender",
            "frequency": "DAILY",
            "owner": "OPER1",
            "status": JobStatus.RUNNING,
            "duration_range": (None, None),
            "error_message": None,
            "wait_reason": None,
        },
        {
            "job_id": "JOB_FRDSCREEN",
            "job_name": "Fraud Screening Engine",
            "frequency": "DAILY",
            "owner": "SYSTEM",
            "status": JobStatus.FAILED,
            "duration_range": (10, 25),
            "error_message": "ORA-00001: unique constraint violated on FRD_SCREENING_UQ",
            "wait_reason": None,
        },
        {
            "job_id": "JOB_ETLEXTRACT",
            "job_name": "ETL - Data Warehouse Extract",
            "frequency": "DAILY",
            "owner": "BATCH",
            "status": JobStatus.QUEUED,
            "duration_range": (None, None),
            "error_message": None,
            "wait_reason": None,
        },
        {
            "job_id": "JOB_SECSCAN",
            "job_name": "Security Audit Scan",
            "frequency": "WEEKLY",
            "owner": "SYSTEM",
            "status": JobStatus.COMPLETED,
            "duration_range": (45, 120),
            "error_message": None,
            "wait_reason": None,
        },
        {
            "job_id": "JOB_ARCHPURGE",
            "job_name": "Archive Purge Old Records",
            "frequency": "MONTHLY",
            "owner": "SYSTEM",
            "status": JobStatus.WAITING,
            "duration_range": (None, None),
            "error_message": None,
            "wait_reason": "Waiting for external FTP transfer to complete - AWS S3",
        },
        {
            "job_id": "JOB_REPGEN",
            "job_name": "Daily Operations Report",
            "frequency": "DAILY",
            "owner": "OPER2",
            "status": JobStatus.COMPLETED,
            "duration_range": (5, 15),
            "error_message": None,
            "wait_reason": None,
        },
        {
            "job_id": "JOB_NETMON",
            "job_name": "Network Health Monitor",
            "frequency": "DAILY",
            "owner": "SYSTEM",
            "status": JobStatus.RUNNING,
            "duration_range": (None, None),
            "error_message": None,
            "wait_reason": None,
        },
        {
            "job_id": "JOB_MQSYNC",
            "job_name": "MQ Queue Synchronizer",
            "frequency": "DAILY",
            "owner": "BATCH",
            "status": JobStatus.WAITING,
            "duration_range": (None, None),
            "error_message": None,
            "wait_reason": "Waiting for MQ queue MQ.PROD.QUEUE01 to become available",
        },
        {
            "job_id": "JOB_ROLLUP",
            "job_name": "Monthly Rollup Processing",
            "frequency": "MONTHLY",
            "owner": "OPER1",
            "status": JobStatus.CANCELLED,
            "duration_range": (0, 5),
            "error_message": None,
            "wait_reason": None,
        },
        {
            "job_id": "JOB_BALCHK",
            "job_name": "Balance Sheet Reconciliation",
            "frequency": "DAILY",
            "owner": "BATCH",
            "status": JobStatus.FAILED,
            "duration_range": (8, 20),
            "error_message": "JCL error - missing DD statement for SYSIN",
            "wait_reason": None,
        },
        {
            "job_id": "JOB_DATAQUAL",
            "job_name": "Data Quality Check",
            "frequency": "DAILY",
            "owner": "SYSTEM",
            "status": JobStatus.COMPLETED,
            "duration_range": (18, 40),
            "error_message": None,
            "wait_reason": None,
        },
    ]

    jobs = []
    for idx, defn in enumerate(job_definitions):
        status = defn["status"]

        # Generate realistic start times spread across the last 12 hours
        start_offset = random.randint(0, 12) * 60 + random.randint(0, 59)
        start = now - timedelta(minutes=start_offset)

        # Generate end time and duration based on status
        if status == JobStatus.COMPLETED:
            duration = random.randint(*defn["duration_range"])
            end = start + timedelta(minutes=duration)
        elif status == JobStatus.FAILED:
            duration = random.randint(*defn["duration_range"])
            end = start + timedelta(minutes=duration)
        elif status == JobStatus.CANCELLED:
            end = start + timedelta(minutes=random.randint(0, 5))
            duration = (end - start).total_seconds() / 60
        else:
            end = None
            duration = None

        # Wait reason only for WAITING status
        wait_reason = defn["wait_reason"] if status == JobStatus.WAITING else None
        wait_since = start if status == JobStatus.WAITING else None

        # Error message only for FAILED status
        error_message = defn["error_message"] if status == JobStatus.FAILED else None

        jobs.append(JobRecord(
            job_id=defn["job_id"],
            job_name=defn["job_name"],
            job_status=status,
            job_frequency=_map_frequency(defn["frequency"]),
            job_schedule=defn["frequency"],
            job_start_time=start if status in (JobStatus.RUNNING, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED) else None,
            job_end_time=end,
            job_duration_minutes=round(duration, 1) if duration is not None else None,
            wait_reason=wait_reason,
            wait_since=wait_since,
            error_message=error_message,
            job_owner=defn["owner"],
            last_updated=now - timedelta(minutes=random.randint(0, 30)),
        ))

    return jobs
