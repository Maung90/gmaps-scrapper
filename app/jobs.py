"""Logika bisnis job: menjalankan pencarian dan menyimpan hasil."""

import json
import os

from fastapi import HTTPException

from . import tokens
from .apify import (
    ApifyAuthError,
    ApifyQuotaError,
    fetch_dataset,
    lead_identity,
    normalize_lead,
    run_actor,
    select_token,
)
from .db import get_connection, utc_now


def update_job(job_id, status, *, run_id=None, result_count=None, error=None):
    """Perbarui field job secara parsial dengan query parameterized."""
    assignments = ["status = ?", "updated_at = ?"]
    values = [status, utc_now()]
    if run_id is not None:
        assignments.append("apify_run_id = ?")
        values.append(run_id)
    if result_count is not None:
        assignments.append("result_count = ?")
        values.append(result_count)
    if error is not None:
        assignments.append("error = ?")
        values.append(error[:2000])
    values.append(job_id)
    with get_connection() as connection:
        connection.execute(
            f"UPDATE jobs SET {', '.join(assignments)} WHERE id = ?",
            values,
        )


def resolve_tokens(job_id):
    """Tentukan token Apify untuk job: token dari dashboard, atau APIFY_TOKEN di .env.

    Token dari dashboard bersifat sekali pakai dan tidak pernah disimpan ke database.
    """
    supplied = tokens.take(job_id)
    if not supplied:
        fallback = os.getenv("APIFY_TOKEN", "").strip()
        return [fallback] if fallback else []

    chosen, statuses = select_token(supplied)
    if chosen:
        return [chosen]

    # Tidak ada token yang bisa dipakai: susun pesan yang menjelaskan sebabnya.
    reasons = []
    for status in statuses:
        if not status["valid"]:
            reasons.append(f"token {status['token']} ditolak")
        elif status["exhausted"]:
            reasons.append(f"token {status['token']} kuotanya habis")
        else:
            reasons.append(f"token {status['token']} tidak tersedia")
    raise ApifyQuotaError(
        "Tidak ada token Apify yang bisa dipakai: " + "; ".join(reasons) + "."
    )


def run_search(job_id, search):
    """Jalankan pencarian untuk sebuah job secara sinkron (dipanggil di executor)."""
    try:
        candidates = resolve_tokens(job_id)
    except ApifyQuotaError as exc:
        update_job(
            job_id,
            "failed",
            error=f"{exc} Perbarui token Apify di dashboard lalu jalankan ulang.",
        )
        return

    if not candidates:
        update_job(
            job_id,
            "failed",
            error="Token Apify belum diisi. Masukkan token di dashboard atau set APIFY_TOKEN.",
        )
        return

    try:
        update_job(job_id, "running")
        run_id, dataset_id = run_actor(search, candidates[0])
        update_job(job_id, "running", run_id=run_id)

        unique_leads = {}
        for item in fetch_dataset(dataset_id, candidates[0]):
            lead = normalize_lead(item)
            unique_leads.setdefault(lead_identity(lead), (lead, item))
            if len(unique_leads) >= search.max_results:
                break

        with get_connection() as connection:
            connection.executemany(
                """
                INSERT INTO leads (job_id, place_id, company_name, data_json, raw_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        job_id,
                        str(lead.get("place_id") or ""),
                        str(lead.get("company_name") or ""),
                        json.dumps(lead, ensure_ascii=False),
                        json.dumps(raw, ensure_ascii=False),
                    )
                    for lead, raw in unique_leads.values()
                ],
            )
        update_job(job_id, "succeeded", result_count=len(unique_leads))
    except (ApifyAuthError, ApifyQuotaError) as exc:
        # Pesan ini tampil di kolom error job, jadi harus menjelaskan tindakan berikutnya.
        update_job(job_id, "failed", error=f"{exc} Perbarui token Apify di dashboard lalu coba lagi.")
    except Exception as exc:
        update_job(job_id, "failed", error=str(exc))


def get_job_or_404(job_id):
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan.")
    return dict(row)


def serialize_job(row):
    return {
        "job_id": row["id"],
        "status": row["status"],
        "result_count": row["result_count"],
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "request": json.loads(row["request_json"]),
    }
