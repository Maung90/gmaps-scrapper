"""Routing endpoint API."""

import csv
import io
import json
import os
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response

from .apify import mask_token, probe_account, split_tokens
from .config import CSV_FIELDS, MAX_OUTSTANDING_JOBS
from .db import get_connection, utc_now
from .jobs import get_job_or_404, run_search, serialize_job
from . import tokens
from .models import SearchRequest, TokenCheckRequest
from .security import require_api_key

router = APIRouter()


@router.post("/apify-tokens/check", dependencies=[Depends(require_api_key)])
def check_apify_tokens(payload: TokenCheckRequest):
    """Periksa token Apify dari dashboard tanpa menyimpannya di server."""
    try:
        tokens = split_tokens(payload.token)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    results = []
    for token in tokens:
        info = probe_account(token, force=True)
        results.append(
            {
                "token": mask_token(token),
                "valid": info["valid"],
                "username": info["username"],
                "plan": info["plan"],
                "usage_usd": info["usage_usd"],
                "limit_usd": info["limit_usd"],
                "cycle_end_at": info["cycle_end_at"],
                "exhausted": info["exhausted"],
                "error": info["error"],
            }
        )
    return {
        "tokens": results,
        # Dashboard memakai ini untuk menonaktifkan tombol tanpa menebak-nebak.
        "usable": any(item["valid"] and not item["exhausted"] for item in results),
    }


@router.post("/jobs", status_code=202, dependencies=[Depends(require_api_key)])
def create_job(
    search: SearchRequest,
    request: Request,
    x_apify_token: str | None = Header(default=None, alias="X-Apify-Token"),
):
    # Token Apify dari header, bukan dari body: `request_json` dikembalikan apa adanya
    # oleh GET /jobs, sehingga token di body akan bocor ke setiap pembaca daftar job.
    supplied_tokens = []
    if x_apify_token:
        try:
            supplied_tokens = split_tokens(x_apify_token)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not supplied_tokens and not os.getenv("APIFY_TOKEN", "").strip():
        raise HTTPException(
            status_code=503,
            detail=(
                "Token Apify belum tersedia. Isi token Apify di dashboard "
                "atau set APIFY_TOKEN di environment server."
            ),
        )
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

    # Simpan token hanya di memori, sekali pakai, dan jangan pernah ke database.
    tokens.put(job_id, supplied_tokens)
    try:
        request.app.state.executor.submit(run_search, job_id, search)
    except Exception:
        tokens.discard(job_id)
        raise
    return {
        "job_id": job_id,
        "status": "queued",
        "token_source": "dashboard" if supplied_tokens else "server",
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
