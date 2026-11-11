"""Konfigurasi aplikasi dan pemuatan environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

API_BASE = "https://api.apify.com/v2"
ACTOR_ID = os.getenv("APIFY_ACTOR_ID", "compass~crawler-google-places")

# Path relatif di DATABASE_PATH harus relatif terhadap folder proyek, bukan CWD,
# supaya database yang sama dipakai walau server dijalankan dari folder lain.
_database_path = Path(os.getenv("DATABASE_PATH", "") or BASE_DIR / "leads.db")
DATABASE_PATH = (
    _database_path if _database_path.is_absolute() else (BASE_DIR / _database_path).resolve()
)

MAX_OUTSTANDING_JOBS = 10
PAGE_SIZE = 1000
TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}

# Field hasil terstruktur beserta alias nama field yang mungkin dikembalikan Actor.
FIELDS = {
    "place_id": ("placeId", "place_id", "id", "cid"),
    "company_name": ("title", "name", "businessName", "companyName"),
    "category": ("categoryName", "category", "categories"),
    "address": ("address", "fullAddress"),
    "city": ("city", "municipality"),
    "region": ("state", "region", "province"),
    "country": ("country",),
    "postal_code": ("postalCode", "postal_code", "zipCode"),
    "phone": ("phone", "phoneNumber", "phoneUnformatted"),
    "email": ("email", "emails", "emailAddress"),
    "whatsapp": ("whatsapp", "whatsApp", "whatsappNumber", "whatsappUrl"),
    "website": ("website", "websiteUrl"),
    "rating": ("totalScore", "rating", "aggregateRating"),
    "reviews_count": ("reviewsCount", "reviewCount", "reviews"),
    "price": ("price", "priceLevel"),
    "opening_hours": ("openingHours", "hours"),
    "source_url": ("googleMapsUrl", "placeUrl", "url"),
}
CSV_FIELDS = list(FIELDS.keys()) + ["collected_at"]
