"""Klien HTTP untuk berinteraksi dengan Apify API."""

import math
import os
import time
from urllib.parse import quote

import requests

from .config import API_BASE, ACTOR_ID, FIELDS, PAGE_SIZE, TERMINAL_STATUSES
from .db import utc_now


def apify_request(url, token, method="GET", body=None, params=None):
    """Kirim permintaan ke Apify dan kembalikan JSON, dengan error yang jelas."""
    try:
        response = requests.request(
            method=method,
            url=url,
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            json=body,
            params=params,
            timeout=90,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.JSONDecodeError as exc:
        raise RuntimeError("Apify mengembalikan respons JSON yang tidak valid.") from exc
    except requests.RequestException as exc:
        response = exc.response
        message = response.text[:1000] if response is not None else str(exc)
        raise RuntimeError(f"Permintaan ke Apify gagal: {message}") from exc


def first_value(item, aliases):
    for key in aliases:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return ""


def normalize_lead(item):
    lead = {key: first_value(item, aliases) for key, aliases in FIELDS.items()}
    lead["collected_at"] = utc_now()
    return lead


def lead_identity(lead):
    place_id = str(lead.get("place_id") or "").strip().lower()
    if place_id:
        return ("place_id", place_id)
    return (
        "fallback",
        str(lead.get("company_name") or "").strip().lower(),
        str(lead.get("address") or "").strip().lower(),
        str(lead.get("phone") or "").strip().lower(),
    )


def fetch_dataset(dataset_id, token):
    """Ambil seluruh item dataset Apify secara berhalaman."""
    items = []
    offset = 0
    while True:
        page = apify_request(
            f"{API_BASE}/datasets/{quote(dataset_id, safe='')}/items",
            token,
            params={
                "format": "json",
                "clean": "true",
                "limit": PAGE_SIZE,
                "offset": offset,
            },
        )
        if not isinstance(page, list):
            raise RuntimeError("Format dataset Apify bukan daftar JSON.")
        items.extend(item for item in page if isinstance(item, dict))
        if len(page) < PAGE_SIZE:
            return items
        offset += PAGE_SIZE


def build_actor_input(search):
    """Susun payload input Actor dari SearchRequest."""
    max_per_niche = max(1, math.ceil(search.max_results / len(search.niches)))
    social_profiles = {
        "facebooks": search.scrape_social_media,
        "instagrams": search.scrape_social_media,
        "youtubes": False,
        "tiktoks": False,
        "twitters": False,
    }
    return {
        "searchStringsArray": search.niches,
        "locationQuery": search.location,
        "maxCrawledPlacesPerSearch": max_per_niche,
        "language": search.language,
        "searchMatching": "all",
        "website": "allPlaces",
        "skipClosedPlaces": True,
        "scrapePlaceDetailPage": True,
        "scrapeContacts": search.scrape_contacts,
        "scrapeSocialMediaProfiles": social_profiles,
        "maximumLeadsEnrichmentRecords": 0,
        "maxReviews": 0,
        "scrapeReviewsPersonalData": False,
        "maxImages": 0,
        "scrapeImageAuthors": False,
        "enableCompetitorAnalysis": False,
    }


def run_actor(search, token, poll_interval=5, deadline_minutes=30):
    """Jalankan Actor, tunggu selesai, dan kembalikan (run, dataset_id)."""
    actor_input = build_actor_input(search)
    actor_id = quote(ACTOR_ID.replace("/", "~"), safe="~")
    run_response = apify_request(
        f"{API_BASE}/acts/{actor_id}/runs",
        token,
        method="POST",
        body=actor_input,
        params={"waitForFinish": 60},
    )
    run = run_response.get("data", {})
    run_id = run.get("id")
    if not run_id:
        raise RuntimeError("Respons Apify tidak berisi ID run.")

    status = run.get("status", "UNKNOWN")
    deadline = time.monotonic() + deadline_minutes * 60
    while status not in TERMINAL_STATUSES:
        if time.monotonic() >= deadline:
            raise TimeoutError("Apify job melebihi batas waktu 30 menit.")
        time.sleep(poll_interval)
        response = apify_request(
            f"{API_BASE}/actor-runs/{quote(run_id, safe='')}",
            token,
        )
        run = response.get("data", {})
        status = run.get("status", "UNKNOWN")

    if status != "SUCCEEDED":
        message = run.get("statusMessage") or f"Actor berakhir dengan status {status}."
        raise RuntimeError(message)

    dataset_id = run.get("defaultDatasetId")
    if not dataset_id:
        raise RuntimeError("Run berhasil tetapi dataset hasil tidak ditemukan.")

    return run_id, dataset_id
