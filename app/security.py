"""Autentikasi API key."""

import hmac
import os

from fastapi import Header, HTTPException

_PLACEHOLDER_PREFIX = "replace_with"
MIN_API_KEY_LENGTH = 16


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    expected = os.getenv("API_KEY", "").strip()
    if (
        not expected
        or expected.lower().startswith(_PLACEHOLDER_PREFIX)
        or len(expected) < MIN_API_KEY_LENGTH
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "API_KEY belum dikonfigurasi dengan benar di environment. "
                f"Gunakan secret acak minimal {MIN_API_KEY_LENGTH} karakter."
            ),
        )
    # compare_digest pada str melempar TypeError untuk karakter non-ASCII,
    # jadi bandingkan sebagai bytes agar header aneh tetap berakhir 401 bukan 500.
    supplied = (x_api_key or "").encode("utf-8")
    if not supplied or not hmac.compare_digest(supplied, expected.encode("utf-8")):
        raise HTTPException(status_code=401, detail="API key tidak valid.")
