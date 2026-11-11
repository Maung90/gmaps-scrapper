"""Model permintaan (Pydantic) untuk endpoint API."""

from pydantic import BaseModel, Field, field_validator


class SearchRequest(BaseModel):
    niches: list[str] = Field(
        min_length=1,
        max_length=10,
        examples=[["villa management", "natural restaurant"]],
    )
    location: str = Field(min_length=2, max_length=200, examples=["Ubud, Bali, Indonesia"])
    max_results: int = Field(default=50, ge=1, le=500)
    language: str = Field(default="id", min_length=2, max_length=10)
    scrape_contacts: bool = True
    scrape_social_media: bool = False

    @field_validator("niches")
    @classmethod
    def clean_niches(cls, values):
        cleaned = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if not cleaned:
            raise ValueError("Isi minimal satu niche yang tidak kosong.")
        if len(cleaned) > 10:
            raise ValueError("Maksimal 10 niche per job.")
        if any(len(value) > 100 for value in cleaned):
            raise ValueError("Setiap niche maksimal 100 karakter.")
        return cleaned

    @field_validator("location")
    @classmethod
    def clean_location(cls, value):
        # min_length pada Field dihitung sebelum strip, sehingga spasi saja lolos.
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("Lokasi minimal 2 karakter setelah spasi dihapus.")
        return cleaned
