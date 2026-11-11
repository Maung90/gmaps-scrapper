"""Routing endpoint API."""

import csv
import io
import json
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from .config import CSV_FIELDS, MAX_OUTSTANDING_JOBS
from .db import get_connection, utc_now
from .jobs import get_job_or_404, run_search, serialize_job
from .models import SearchRequest
from .security import require_api_key

router = APIRouter()


@router.get("/niches", dependencies=[Depends(require_api_key)])
def list_niches():
    return {
        "niches": [
            {"id": "villa_management", "label": "Manajemen villa", "search_term": "villa management"},
            {"id": "hotel_resort", "label": "Hotel dan resort", "search_term": "boutique hotel resort"},
            {"id": "natural_restaurant", "label": "Restoran natural", "search_term": "natural concept restaurant"},
            {"id": "cafe", "label": "Kafe", "search_term": "natural concept cafe"},
            {"id": "interior_retail", "label": "Retail interior", "search_term": "interior home decor store"},
            {"id": "custom", "label": "Niche khusus", "search_term": "isi sesuai target"},
        ],
        "note": "Kirim search_term sebagai nilai niches pada endpoint pencarian.",
    }


@router.post("/jobs", status_code=202, dependencies=[Depends(require_api_key)])
def create_job(search: SearchRequest, request: Request):
    token = os.getenv("APIFY_TOKEN", "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="APIFY_TOKEN belum dikonfigurasi.")
    with get_connection() as connection:
        outstanding = connection.execute(
            "SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')"
        ).fetchone()[0]
        if outstanding >= MAX_OUTSTANDING_JOBS:
            raise HTTPException(
                status_code=429,
                detail="Batas job aktif tercapai. Coba lagi setelah ada job selesai.",
            )

        job_id = str(uuid.uuid4())
        now = utc_now()
        connection.execute(
            """
            INSERT INTO jobs (id, status, request_json, created_at, updated_at)
            VALUES (?, 'queued', ?, ?, ?)
            """,
            (job_id, search.model_dump_json(), now, now),
        )

    request.app.state.executor.submit(run_search, job_id, search)
    return {
        "job_id": job_id,
        "status": "queued",
        "status_url": f"/api/v1/jobs/{job_id}",
        "results_url": f"/api/v1/jobs/{job_id}/leads",
    }


@router.get("/jobs", dependencies=[Depends(require_api_key)])
def list_jobs(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return {"items": [serialize_job(row) for row in rows], "limit": limit, "offset": offset}


@router.get("/jobs/{job_id}", dependencies=[Depends(require_api_key)])
def get_job(job_id: str):
    return serialize_job(get_job_or_404(job_id))


@router.get("/jobs/{job_id}/leads", dependencies=[Depends(require_api_key)])
def get_leads(
    job_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    include_raw: bool = False,
):
    job = get_job_or_404(job_id)
    if job["status"] not in {"succeeded", "failed"}:
        raise HTTPException(status_code=409, detail="Hasil belum siap; periksa status job.")
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT data_json, raw_json FROM leads
            WHERE job_id = ? ORDER BY id LIMIT ? OFFSET ?
            """,
            (job_id, limit, offset),
        ).fetchall()
    items = []
    for row in rows:
        item = json.loads(row["data_json"])
        if include_raw:
            item["raw"] = json.loads(row["raw_json"])
        items.append(item)
    return {
        "job_id": job_id,
        "total": job["result_count"],
        "limit": limit,
        "offset": offset,
        "items": items,
    }


@router.get("/jobs/{job_id}/leads.csv", dependencies=[Depends(require_api_key)])
def download_csv(job_id: str):
    job = get_job_or_404(job_id)
    if job["status"] not in {"succeeded", "failed"}:
        raise HTTPException(status_code=409, detail="Hasil belum siap; periksa status job.")
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT data_json FROM leads WHERE job_id = ? ORDER BY id",
            (job_id,),
        ).fetchall()

    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, restval="")
    writer.writeheader()
    for row in rows:
        lead = json.loads(row["data_json"])
        safe_lead = {}
        for key, value in lead.items():
            if key not in CSV_FIELDS:
                continue
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                value = "'" + value
            safe_lead[key] = value
        writer.writerow(safe_lead)
    filename = f"leads-{job_id}.csv"
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/jobs/{job_id}", status_code=204, dependencies=[Depends(require_api_key)])
def delete_job(job_id: str):
    job = get_job_or_404(job_id)
    if job["status"] in {"queued", "running"}:
        raise HTTPException(
            status_code=409,
            detail="Job yang masih berjalan tidak dapat dihapus.",
        )
    with get_connection() as connection:
        connection.execute("DELETE FROM leads WHERE job_id = ?", (job_id,))
        connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    return Response(status_code=204)
