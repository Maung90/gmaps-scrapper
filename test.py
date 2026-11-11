"""Unit test untuk normalisasi lead, model, identitas dedupe, dan token Apify."""

import json

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


def test_search_request_cleans_keyword():
    req = SearchRequest(keyword="  coffee shop in Ubud  ", location="  Ubud  ")
    assert req.keyword == "coffee shop in Ubud"
    assert req.location == "Ubud"


def test_search_request_rejects_blank_keyword():
    with pytest.raises(Exception):
        SearchRequest(keyword="   ", location="Ubud")


def test_actor_input_uses_one_exact_keyword_and_full_result_limit():
    from app.apify import build_actor_input

    search = SearchRequest(
        keyword="coffee shop in Ubud",
        location="Ubud, Bali, Indonesia",
        max_results=40,
    )
    actor_input = build_actor_input(search)
    assert actor_input["searchStringsArray"] == ["coffee shop in Ubud"]
    assert actor_input["maxCrawledPlacesPerSearch"] == 40


def test_search_request_rejects_blank_location():
    with pytest.raises(Exception):
        SearchRequest(keyword="villa", location="   ")


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


def _client():
    from fastapi.testclient import TestClient

    from app import app

    return TestClient(app)


def test_frontend_is_served_at_root(monkeypatch):
    monkeypatch.setenv("API_KEY", "k" * 24)
    with _client() as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "X-API-Key" in response.text


def test_legacy_dashboard_still_available(monkeypatch):
    monkeypatch.setenv("API_KEY", "k" * 24)
    with _client() as client:
        for path in ("/dashboard", "/index.html"):
            assert client.get(path).status_code == 200


def test_static_routes_do_not_expose_secrets(monkeypatch):
    monkeypatch.setenv("API_KEY", "k" * 24)
    with _client() as client:
        for path in ("/.env", "/leads.db", "/app/config.py", "/../.env"):
            assert client.get(path).status_code == 404, path


def test_split_tokens_dedupes_and_cleans():
    from app.apify import split_tokens

    raw = " apify_api_aaaaaaaaaaaaaaaaaaaa, apify_api_bbbbbbbbbbbbbbbbbbbb ; apify_api_aaaaaaaaaaaaaaaaaaaa "
    assert split_tokens(raw) == ["apify_api_aaaaaaaaaaaaaaaaaaaa", "apify_api_bbbbbbbbbbbbbbbbbbbb"]


def test_split_tokens_rejects_short_and_unsafe_tokens():
    from app.apify import split_tokens

    with pytest.raises(ValueError):
        split_tokens("terlalu-pendek")
    with pytest.raises(ValueError):
        split_tokens("apify_api_aaaaaaaaaaaaaaaaaaaa\nX-Api-Key: curang")


def test_mask_token_hides_most_of_the_secret():
    from app.apify import mask_token

    masked = mask_token("apify_api_sangatrahasia1234")
    assert masked.endswith("1234")
    assert "rahasia" not in masked


def test_create_job_requires_a_token_when_server_has_none(monkeypatch):
    monkeypatch.setenv("API_KEY", "k" * 24)
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    with _client() as client:
        response = client.post(
            "/api/v1/jobs",
            headers={"X-API-Key": "k" * 24},
            json={"keyword": "villa", "location": "Ubud"},
        )
    assert response.status_code == 503
    assert "Token Apify" in response.json()["detail"]


def test_token_check_endpoint_reports_invalid_token(monkeypatch):
    from app import apify

    monkeypatch.setenv("API_KEY", "k" * 24)

    class FakeResponse:
        status_code = 401
        text = '{"error":{"type":"invalid-token"}}'

        def json(self):
            raise ValueError("bukan json")

    monkeypatch.setattr(apify.requests, "get", lambda *a, **k: FakeResponse())
    apify.invalidate_account_cache()

    token = "apify_api_" + "z" * 20
    with _client() as client:
        response = client.post(
            "/api/v1/apify-tokens/check",
            headers={"X-API-Key": "k" * 24},
            json={"token": token},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["usable"] is False
    assert payload["tokens"][0]["valid"] is False
    assert payload["tokens"][0]["token"] == "…" + token[-4:]
    # Token mentah tidak boleh dipantulkan kembali ke klien.
    assert token not in response.text


def test_resolve_tokens_skips_exhausted_and_invalid(monkeypatch):
    from app import apify, tokens as token_store

    healthy = "apify_api_" + "h" * 20
    exhausted = "apify_api_" + "e" * 20
    invalid = "apify_api_" + "i" * 20

    table = {
        healthy: {"valid": True, "exhausted": False},
        exhausted: {"valid": True, "exhausted": True},
        invalid: {"valid": False, "exhausted": False},
    }

    def fake_probe(token, force=False):
        info = {
            "valid": False,
            "username": "",
            "plan": "",
            "usage_usd": None,
            "limit_usd": None,
            "cycle_end_at": "",
            "exhausted": False,
            "error": "",
        }
        info.update(table.get(token, {}))
        if not info["valid"]:
            info["error"] = "Token Apify ditolak oleh Apify."
        return info

    monkeypatch.setattr(apify, "probe_account", fake_probe)
    token_store.clear()
    token_store.put("job-1", [exhausted, invalid, healthy])

    from app.jobs import resolve_tokens

    assert resolve_tokens("job-1") == [healthy]
    # Sekali pakai: pemanggilan kedua jatuh ke APIFY_TOKEN server.
    monkeypatch.setenv("APIFY_TOKEN", "server-token-fallback")
    assert resolve_tokens("job-1") == ["server-token-fallback"]


def test_resolve_tokens_explains_when_no_token_is_usable(monkeypatch):
    from app import apify, tokens as token_store
    from app.jobs import resolve_tokens

    monkeypatch.setattr(
        apify,
        "probe_account",
        lambda token, force=False: {
            "valid": True,
            "username": "demo",
            "plan": "",
            "usage_usd": 49.0,
            "limit_usd": 49.0,
            "cycle_end_at": "",
            "exhausted": True,
            "error": "Kuota habis.",
        },
    )
    token_store.clear()
    token_store.put("job-2", ["apify_api_" + "e" * 20])

    with pytest.raises(apify.ApifyQuotaError) as excinfo:
        resolve_tokens("job-2")
    assert "kuotanya habis" in str(excinfo.value)


def test_tokens_are_not_persisted_in_job_request(monkeypatch):
    """Token Apify tidak boleh muncul di request_json yang dikembalikan API."""
    monkeypatch.setenv("API_KEY", "k" * 24)
    monkeypatch.setenv("APIFY_TOKEN", "server-token")
    submitted = []

    from app import tokens as token_store

    token_store.clear()

    with _client() as client:
        # Ganti executor supaya job tidak benar-benar memanggil Apify.
        class Recorder:
            def submit(self, fn, job_id, search):
                submitted.append((job_id, search))

            def shutdown(self, **kwargs):
                pass

        client.app.state.executor = Recorder()
        secret = "apify_api_" + "s" * 20
        response = client.post(
            "/api/v1/jobs",
            headers={"X-API-Key": "k" * 24, "X-Apify-Token": secret},
            json={"keyword": "villa", "location": "Ubud"},
        )
        assert response.status_code == 202
        assert response.json()["token_source"] == "dashboard"

        job_id = response.json()["job_id"]
        detail = client.get(f"/api/v1/jobs/{job_id}", headers={"X-API-Key": "k" * 24})

    assert secret not in detail.text
    assert secret not in response.text
    assert "apify" not in json.dumps(detail.json()["request"]).lower()
    # Token tersedia di memori untuk worker, lalu habis setelah diambil.
    assert len(submitted) == 1
    token_store.clear()


def test_token_check_marks_exhausted_account(monkeypatch):
    from app import apify

    monkeypatch.setenv("API_KEY", "k" * 24)

    calls = []

    class FakeResponse:
        status_code = 200

        def __init__(self, body):
            self._body = body
            self.text = "ok"

        def json(self):
            return self._body

    def fake_get(url, **kwargs):
        calls.append(url)
        if url.endswith("/users/me"):
            return FakeResponse({"data": {"username": "demo", "plan": {"id": "Personal"}}})
        return FakeResponse(
            {
                "data": {
                    "monthlyUsageCycle": {"startAt": "2026-01-01T00:00:00Z", "endAt": "2026-02-01T00:00:00Z"},
                    "limits": {"maxMonthlyUsageUsd": 49},
                    "current": {"monthlyUsageUsd": 49},
                }
            }
        )

    monkeypatch.setattr(apify.requests, "get", fake_get)
    apify.invalidate_account_cache()

    token = "apify_api_" + "q" * 20
    with _client() as client:
        response = client.post(
            "/api/v1/apify-tokens/check",
            headers={"X-API-Key": "k" * 24},
            json={"token": token},
        )
    payload = response.json()
    assert payload["usable"] is False
    item = payload["tokens"][0]
    assert item["valid"] is True
    assert item["exhausted"] is True
    assert item["usage_usd"] == 49.0 and item["limit_usd"] == 49.0
    assert item["username"] == "demo"
    assert len(calls) == 2
