"""Klien HTTP untuk berinteraksi dengan Apify API."""

import os
import re
import threading
import time
from urllib.parse import quote

import requests

from .config import API_BASE, ACTOR_ID, FIELDS, PAGE_SIZE, TERMINAL_STATUSES
from .db import utc_now

USERS_ME_URL = f"{API_BASE}/users/me"
USERS_ME_LIMITS_URL = f"{API_BASE}/users/me/limits"

# Token Apify berbentuk "apify_api_<acak>"; jangan terlalu ketat agar token lama tetap diterima.
TOKEN_MIN_LENGTH = 20
TOKEN_MAX_LENGTH = 200
MAX_TOKENS_PER_REQUEST = 5
_ACCOUNT_CACHE_TTL = 60

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.~\-]+$")
_account_cache = {}
_account_lock = threading.Lock()


class ApifyAuthError(RuntimeError):
    """Token Apify tidak valid atau tidak punya izin."""


class ApifyQuotaError(RuntimeError):
    """Akun Apify kehabisan kuota pemakaian."""


class ApifyRequestError(RuntimeError):
    """Kegagalan lain saat menghubungi Apify."""


def clean_token(raw):
    """Validasi bentuk token sebelum dikirim ke Apify."""
    token = (raw or "").strip()
    if not token:
        return ""
    if len(token) < TOKEN_MIN_LENGTH:
        raise ValueError(f"Token Apify terlalu pendek (minimal {TOKEN_MIN_LENGTH} karakter).")
    if len(token) > TOKEN_MAX_LENGTH:
        raise ValueError(f"Token Apify terlalu panjang (maksimal {TOKEN_MAX_LENGTH} karakter).")
    if not _TOKEN_RE.match(token):
        raise ValueError("Token Apify mengandung karakter yang tidak diizinkan.")
    return token


def split_tokens(raw):
    """Pecah daftar token (dipisah koma/titik koma/spasi) tanpa duplikat."""
    if not raw:
        return []
    tokens = []
    for chunk in re.split(r"[,;\s]+", raw):
        token = clean_token(chunk)
        if token and token not in tokens:
            tokens.append(token)
    if len(tokens) > MAX_TOKENS_PER_REQUEST:
        raise ValueError(f"Maksimal {MAX_TOKENS_PER_REQUEST} token Apify per permintaan.")
    return tokens


def mask_token(token):
    """Bentuk aman untuk ditampilkan/di-log: hanya 4 karakter terakhir."""
    token = token or ""
    return f"…{token[-4:]}" if len(token) > 8 else "…"


def _get_json(url, token):
    try:
        response = requests.get(
            url,
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise ApifyRequestError("Tidak dapat menghubungi Apify. Periksa koneksi server.") from exc

    if response.status_code in (401, 403):
        raise ApifyAuthError("Token Apify ditolak oleh Apify.")
    if response.status_code >= 400:
        raise ApifyRequestError(
            f"Apify menolak permintaan (HTTP {response.status_code}): {response.text[:300]}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise ApifyRequestError("Apify mengembalikan respons JSON yang tidak valid.") from exc


def probe_account(token, force=False):
    """Periksa token dan kuota akun Apify. Hasil di-cache singkat agar hemat request.

    Mengembalikan dict: valid, username, plan, usage_usd, limit_usd, cycle_end_at,
    exhausted, error.
    """
    now = time.monotonic()
    with _account_lock:
        cached = _account_cache.get(token)
    if cached and not force and now - cached["checked_at"] < _ACCOUNT_CACHE_TTL:
        return dict(cached["result"])

    result = {
        "valid": False,
        "username": "",
        "plan": "",
        "usage_usd": None,
        "limit_usd": None,
        "cycle_end_at": "",
        "exhausted": False,
        "error": "",
    }
    try:
        me = _get_json(USERS_ME_URL, token).get("data") or {}
        result["valid"] = True
        result["username"] = str(me.get("username") or "")
        plan = me.get("plan") or {}
        result["plan"] = str(plan.get("id") or plan.get("tier") or "")
    except (ApifyAuthError, ApifyRequestError) as exc:
        result["error"] = str(exc)

    if result["valid"]:
        try:
            limits = _get_json(USERS_ME_LIMITS_URL, token).get("data") or {}
            current = limits.get("current") or {}
            ceiling = limits.get("limits") or {}
            cycle = limits.get("monthlyUsageCycle") or {}
            usage = current.get("monthlyUsageUsd")
            cap = ceiling.get("maxMonthlyUsageUsd")
            result["usage_usd"] = float(usage) if isinstance(usage, (int, float)) else None
            result["limit_usd"] = float(cap) if isinstance(cap, (int, float)) else None
            result["cycle_end_at"] = str(cycle.get("endAt") or "")
            if (
                result["usage_usd"] is not None
                and result["limit_usd"] is not None
                and result["limit_usd"] > 0
                and result["usage_usd"] >= result["limit_usd"]
            ):
                result["exhausted"] = True
                result["error"] = "Kuota pemakaian bulanan akun Apify sudah habis."
        except (ApifyAuthError, ApifyRequestError) as exc:
            # Kuota hanya informasi tambahan; token tetap bisa dipakai walau ini gagal.
            result["error"] = result["error"] or str(exc)

    with _account_lock:
        _account_cache[token] = {"checked_at": now, "result": dict(result)}
    return result


def invalidate_account_cache(token=None):
    """Buang cache pemeriksaan token (semua bila token tidak diberikan)."""
    with _account_lock:
        if token is None:
            _account_cache.clear()
        else:
            _account_cache.pop(token, None)


def select_token(tokens):
    """Pilih token pertama yang valid dan belum kehabisan kuota.

    Mengembalikan (token_terpilih, daftar_status_token).
    """
    statuses = []
    for token in tokens:
        info = probe_account(token)
        statuses.append(
            {
                "token": mask_token(token),
                "valid": info["valid"],
                "exhausted": info["exhausted"],
                "usage_usd": info["usage_usd"],
                "limit_usd": info["limit_usd"],
                "error": info["error"],
            }
        )
        if info["valid"] and not info["exhausted"]:
            return token, statuses
    return None, statuses


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
        status = response.status_code if response is not None else None
        # Token kedaluwarsa/dicabut dan kuota habis perlu sinyal berbeda agar UI bisa
        # menyarankan penggantian token, bukan sekadar menampilkan error generik.
        if status in (401, 403):
            invalidate_account_cache(token)
            raise ApifyAuthError("Token Apify ditolak atau tidak punya izin.") from exc
        if status == 402 or "not-enough-usage" in message or "limit-reached" in message:
            invalidate_account_cache(token)
            raise ApifyQuotaError(
                "Kuota atau saldo Apify habis untuk token ini. Ganti token Apify lalu jalankan ulang."
            ) from exc
        if status == 429:
            raise ApifyQuotaError("Apify menolak karena batas pemakaian tercapai. Coba lagi nanti.") from exc
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
    social_profiles = {
        "facebooks": search.scrape_social_media,
        "instagrams": search.scrape_social_media,
        "youtubes": False,
        "tiktoks": False,
        "twitters": False,
    }
    return {
        "searchStringsArray": [search.keyword],
        "locationQuery": search.location,
        "maxCrawledPlacesPerSearch": search.max_results,
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
