# API Reference

Base URL lokal: `http://127.0.0.1:8000`

Semua endpoint di bawah selain `GET /health` memerlukan header:

```http
X-API-Key: <nilai API_KEY dari .env>
```

Contoh PowerShell:

```powershell
$headers = @{ "X-API-Key" = "secret_anda" }
```

## Health

```http
GET /health
```

Tidak memerlukan API key.

Respons:

```json
{
  "status": "ok",
  "service": "natural-decor-prospecting-api"
}
```

## Daftar saran niche

```http
GET /api/v1/niches
```

Mengembalikan pilihan kata kunci awal. Nilai `search_term` dapat dikirim sebagai elemen `niches` saat membuat job. Anda juga dapat mengirim kata kunci sendiri.

## Membuat job pencarian

```http
POST /api/v1/jobs
Content-Type: application/json
X-API-Key: <api-key>
```

Payload:

```json
{
  "niches": [
    "villa management",
    "natural concept restaurant",
    "interior home decor store"
  ],
  "location": "Ubud, Bali, Indonesia",
  "max_results": 50,
  "language": "id",
  "scrape_contacts": true,
  "scrape_social_media": false
}
```

| Field | Tipe | Wajib | Aturan |
|---|---|---:|---|
| `niches` | array string | ya | 1–10 kata kunci; setiap item maksimum 100 karakter |
| `location` | string | ya | 2–200 karakter, misalnya kota/daerah dan negara |
| `max_results` | integer | tidak | batas hasil unik keseluruhan, 1–500; default 50 |
| `language` | string | tidak | bahasa pencarian, default `id` |
| `scrape_contacts` | boolean | tidak | meminta Actor mengambil kontak yang tersedia, default `true` |
| `scrape_social_media` | boolean | tidak | meminta Facebook/Instagram bila tersedia, default `false` |

Respons `202 Accepted`:

```json
{
  "job_id": "uuid",
  "status": "queued",
  "status_url": "/api/v1/jobs/uuid",
  "results_url": "/api/v1/jobs/uuid/leads"
}
```

Setiap job membagi `max_results` secara rata ke jumlah niche untuk menentukan batas hasil per pencarian Actor. Karena itu jumlah hasil akhir dapat lebih kecil akibat ketersediaan hasil atau duplikasi. Maksimum 10 job berstatus menunggu/berjalan pada satu waktu; setelah batas tersebut API mengembalikan `429`.

Contoh:

```powershell
$body = @{
  niches = @("villa management", "natural concept restaurant")
  location = "Ubud, Bali, Indonesia"
  max_results = 40
  language = "id"
  scrape_contacts = $true
  scrape_social_media = $false
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/jobs" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

## Daftar job

```http
GET /api/v1/jobs?limit=20&offset=0
```

`limit` 1–500 (default 100), `offset` minimal 0 (default 0).

## Status job

```http
GET /api/v1/jobs/{job_id}
```

Contoh respons:

```json
{
  "job_id": "uuid",
  "status": "succeeded",
  "result_count": 38,
  "error": null,
  "created_at": "2026-10-27T09:00:00+00:00",
  "updated_at": "2026-10-27T09:04:00+00:00",
  "request": {
    "niches": ["villa management"],
    "location": "Ubud, Bali, Indonesia",
    "max_results": 40,
    "language": "id",
    "scrape_contacts": true,
    "scrape_social_media": false
  }
}
```

## Mengambil hasil JSON

```http
GET /api/v1/jobs/{job_id}/leads?limit=100&offset=0&include_raw=false
```

- `limit`: 1–500, default 100.
- `offset`: default 0.
- `include_raw`: default `false`; jika `true`, setiap item juga berisi `raw` sesuai hasil penuh Actor.
- Jika job belum selesai, endpoint mengembalikan `409`.

Contoh:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/v1/jobs/uuid/leads?include_raw=true" `
  -Headers $headers
```

Respons:

```json
{
  "job_id": "uuid",
  "total": 1,
  "limit": 100,
  "offset": 0,
  "items": [
    {
      "place_id": "place-id",
      "company_name": "Nama Bisnis",
      "category": "Kategori",
      "address": "Alamat",
      "city": "Ubud",
      "region": "Bali",
      "country": "Indonesia",
      "postal_code": "80571",
      "phone": "+62...",
      "email": ["hello@example.com"],
      "whatsapp": "",
      "website": "https://example.com",
      "rating": 4.8,
      "reviews_count": 120,
      "price": "",
      "opening_hours": [],
      "source_url": "https://www.google.com/maps/...",
      "collected_at": "2026-10-27T09:04:00+00:00",
      "raw": {}
    }
  ]
}
```

Field kontak mengikuti ketersediaan dan bentuk data dari Actor; email, WhatsApp, atau telepon tidak dijamin ada.

## Mengunduh CSV

```http
GET /api/v1/jobs/{job_id}/leads.csv
```

Mengembalikan CSV UTF-8 dengan BOM agar mudah dibuka di spreadsheet. Contoh PowerShell:

```powershell
Invoke-WebRequest `
  -Uri "http://127.0.0.1:8000/api/v1/jobs/uuid/leads.csv" `
  -Headers $headers `
  -OutFile "leads.csv"
```

## Menghapus job dan hasilnya

```http
DELETE /api/v1/jobs/{job_id}
```

Menghapus job dan seluruh prospek yang tersimpan untuk job tersebut. Job harus sudah berstatus `succeeded` atau `failed`; job yang masih `queued`/`running` mengembalikan `409`.

Contoh:

```powershell
Invoke-RestMethod `
  -Method Delete `
  -Uri "http://127.0.0.1:8000/api/v1/jobs/uuid" `
  -Headers $headers
```

## Kode respons umum

| HTTP | Makna |
|---:|---|
| `202` | Job diterima dan berjalan di background |
| `401` | API key tidak ada atau salah |
| `404` | Job tidak ditemukan |
| `409` | Hasil job belum siap |
| `429` | Batas job aktif/menunggu tercapai |
| `503` | `API_KEY` atau `APIFY_TOKEN` belum dikonfigurasi |
| `422` | Payload tidak valid |

Kesalahan job Apify dikembalikan pada field `error` di status job. Jangan mengirim token Apify ke klien; token tersebut hanya digunakan oleh server.
