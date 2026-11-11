"""Unit test untuk normalisasi lead, model, dan identitas dedupe."""

import pytest

from app.apify import first_value, lead_identity, normalize_lead
from app.models import SearchRequest


def test_first_value_prefers_first_non_empty():
    item = {"a": "", "b": None, "c": "hello"}
    assert first_value(item, ("a", "b", "c")) == "hello"


def test_first_value_returns_empty_when_missing():
    assert first_value({}, ("x", "y")) == ""


def test_normalize_lead_maps_fields_and_timestamp():
    item = {"title": "Villa Damai", "fullAddress": "Ubud", "phone": "0812"}
    lead = normalize_lead(item)
    assert lead["company_name"] == "Villa Damai"
    assert lead["address"] == "Ubud"
    assert lead["phone"] == "0812"
    assert lead["collected_at"]


def test_lead_identity_uses_place_id():
    lead = {"place_id": "ChIJ123", "company_name": "X"}
    assert lead_identity(lead) == ("place_id", "chij123")


def test_lead_identity_falls_back_without_place_id():
    lead = {"company_name": "Cafe Alam", "address": "Ubud", "phone": "081"}
    kind, name, addr, phone = lead_identity(lead)
    assert kind == "fallback"
    assert name == "cafe alam"
    assert addr == "ubud"
    assert phone == "081"


def test_search_request_cleans_niches():
    req = SearchRequest(niches=[" villa ", "villa", "  "], location="  Ubud  ")
    assert req.niches == ["villa"]
    assert req.location == "Ubud"


def test_search_request_rejects_empty_niches():
    with pytest.raises(Exception):
        SearchRequest(niches=["  ", ""], location="Ubud")


def test_search_request_rejects_blank_location():
    with pytest.raises(Exception):
        SearchRequest(niches=["villa"], location="   ")


def test_require_api_key_rejects_placeholder_value(monkeypatch):
    from fastapi import HTTPException

    from app.security import require_api_key

    monkeypatch.setenv("API_KEY", "replace_with_sadasdasdsaa_long_random_secret")
    with pytest.raises(HTTPException) as excinfo:
        require_api_key("replace_with_sadasdasdsaa_long_random_secret")
    assert excinfo.value.status_code == 503


def test_require_api_key_handles_non_ascii_header(monkeypatch):
    from fastapi import HTTPException

    from app.security import require_api_key

    monkeypatch.setenv("API_KEY", "y" * 24)
    # compare_digest pada str non-ASCII melempar TypeError; harus tetap 401.
    with pytest.raises(HTTPException) as excinfo:
        require_api_key("kunci-rahasia-café")
    assert excinfo.value.status_code == 401


def test_require_api_key_accepts_matching_key(monkeypatch):
    from app.security import require_api_key

    monkeypatch.setenv("API_KEY", "y" * 24)
    assert require_api_key("y" * 24) is None
