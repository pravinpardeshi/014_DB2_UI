from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from models import JobFilter, JobRecord, JobStatus, JobFrequency, PaginatedJobs
from services import get_all_jobs, get_job_summary, get_paginated_jobs, get_job_history, get_job_trends

router = APIRouter(prefix="/api", tags=["jobs"])


@router.get("/jobs", response_model=PaginatedJobs)
def list_jobs(
    status: Optional[str] = Query(None, description="Filter by job status"),
    frequency: Optional[str] = Query(None, description="Filter by job frequency"),
    search: Optional[str] = Query(None, description="Search job name, id, or owner"),
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=1000, description="Items per page (up to 1000; use a large value to fetch all)"),
):
    filters = JobFilter(
        status=JobStatus(status) if status else None,
        frequency=JobFrequency(frequency) if frequency else None,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )
    try:
        result = get_paginated_jobs(filters if any(filters.model_dump().values()) else None, page, page_size)
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return PaginatedJobs(
        items=[job.model_dump(mode="json") for job in result["items"]],
        total=result["total"],
        page=page,
        page_size=page_size,
        total_pages=result["total_pages"]
    )


@router.get("/jobs/summary")
def job_summary(
    status: Optional[str] = Query(None),
    frequency: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    filters = JobFilter(
        status=JobStatus(status) if status else None,
        frequency=JobFrequency(frequency) if frequency else None,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )
    try:
        jobs = get_all_jobs(filters if any(filters.model_dump().values()) else None)
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))
    summary = get_job_summary(jobs)
    return summary.model_dump()


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    jobs = get_all_jobs()
    for job in jobs:
        if job.job_id == job_id:
            return job.model_dump(mode="json")
    raise HTTPException(status_code=404, detail=f"Job {job_id} not found")


@router.get("/jobs/{job_id}/history", response_model=list[dict])
def get_job_history_endpoint(
    job_id: str,
    days: int = Query(7, description="Number of days to look back"),
):
    history = get_job_history(job_id, days)
    return [h.model_dump(mode="json") for h in history]


@router.get("/jobs/{job_id}/trends", response_model=list[dict])
def get_job_trends_endpoint(
    job_id: str,
    days: int = Query(30, description="Number of days for trends"),
):
    trends = get_job_trends(job_id, days)
    return [t.model_dump(mode="json") for t in trends]
