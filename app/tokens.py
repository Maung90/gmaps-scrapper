"""Penyimpanan token Apify per job.

Token Apify yang dikirim dari dashboard TIDAK boleh masuk ke database atau ke
`request_json`, karena `GET /api/v1/jobs` mengembalikan `request` apa adanya ke
klien. Modul ini menyimpannya di memori proses, hanya selama job diproses, dan
menghapusnya setelah dipakai.
"""

import threading
import time

# Job yang tidak pernah dijalankan (mis. server mati) tidak boleh menyisakan token.
_TTL_SECONDS = 60 * 60
_tokens = {}
_created_at = {}
_lock = threading.Lock()


def _purge_expired(now):
    expired = [job_id for job_id, stamp in _created_at.items() if now - stamp > _TTL_SECONDS]
    for job_id in expired:
        _tokens.pop(job_id, None)
        _created_at.pop(job_id, None)


def put(job_id, tokens):
    """Simpan daftar token untuk satu job."""
    if not tokens:
        return
    now = time.monotonic()
    with _lock:
        _purge_expired(now)
        _tokens[job_id] = list(tokens)
        _created_at[job_id] = now


def take(job_id):
    """Ambil lalu hapus token milik job (sekali pakai)."""
    with _lock:
        _created_at.pop(job_id, None)
        return _tokens.pop(job_id, [])


def discard(job_id):
    """Hapus token tanpa memakainya."""
    with _lock:
        _created_at.pop(job_id, None)
        _tokens.pop(job_id, None)


def clear():
    """Kosongkan seluruh penyimpanan (untuk pengujian)."""
    with _lock:
        _tokens.clear()
        _created_at.clear()
