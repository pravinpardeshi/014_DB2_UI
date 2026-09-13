from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class JobStatus(str, Enum):
    COMPLETED = "COMPLETED"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    FAILED = "FAILED"
    QUEUED = "QUEUED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class JobFrequency(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    ONETIME = "ONETIME"
    UNKNOWN = "UNKNOWN"


class JobRecord(BaseModel):
    job_id: str
    job_name: str
    job_status: JobStatus
    job_frequency: JobFrequency
    job_schedule: str
    job_start_time: Optional[datetime] = None
    job_end_time: Optional[datetime] = None
    job_duration_minutes: Optional[float] = None
    wait_reason: Optional[str] = None
    wait_since: Optional[datetime] = None
    error_message: Optional[str] = None
    job_owner: Optional[str] = None
    last_updated: Optional[datetime] = None


class JobSummary(BaseModel):
    total_jobs: int
    completed: int
    running: int
    waiting: int
    failed: int
    queued: int
    cancelled: int


class JobFilter(BaseModel):
    status: Optional[JobStatus] = None
    frequency: Optional[JobFrequency] = None
    search: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None


class PaginatedJobs(BaseModel):
    items: list[JobRecord]
    total: int
    page: int
    page_size: int
    total_pages: int


class JobHistoryRecord(BaseModel):
    job_id: str
    job_status: JobStatus
    timestamp: datetime
    duration_minutes: Optional[float] = None
    error_message: Optional[str] = None


class JobTrend(BaseModel):
    date: str
    completed: int
    failed: int
    running: int
    waiting: int
