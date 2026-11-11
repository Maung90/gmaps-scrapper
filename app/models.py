"""Model permintaan (Pydantic) untuk endpoint API."""

from pydantic import BaseModel, Field, field_validator


class TokenCheckRequest(BaseModel):
    """Permintaan pemeriksaan token Apify dari dashboard."""

    token: str = Field(min_length=1, max_length=1000, examples=["apify_api_xxxxxxxxxxxx"])

    @field_validator("token")
    @classmethod
    def require_token(cls, value):
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Token Apify tidak boleh kosong.")
        return cleaned


class SearchRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=200, examples=["coffee shop"])
    location: str = Field(min_length=2, max_length=200, examples=["Ubud, Bali, Indonesia"])
    max_results: int = Field(default=50, ge=1, le=500)
    language: str = Field(default="id", min_length=2, max_length=10)
    scrape_contacts: bool = True
    scrape_social_media: bool = False

    @field_validator("keyword")
    @classmethod
    def clean_keyword(cls, value):
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Keyword tidak boleh kosong.")
        return cleaned

    @field_validator("location")
    @classmethod
    def clean_location(cls, value):
        # min_length pada Field dihitung sebelum strip, sehingga spasi saja lolos.
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("Lokasi minimal 2 karakter setelah spasi dihapus.")
        return cleaned
