# Natural Decor Prospecting API

API MVP untuk membuat daftar prospek bisnis melalui Actor Apify `compass/crawler-google-places`. Aplikasi menyimpan job dan hasilnya di SQLite, kemudian menyediakan hasil sebagai JSON atau CSV untuk dipakai aplikasi lain.

> Gunakan Actor dan data hasilnya sesuai ketentuan Apify, sumber data, serta peraturan privasi dan pemasaran yang berlaku. Data kontak mungkin tidak tersedia atau tidak selalu akurat. Verifikasi sebelum menghubungi prospek.

## Fitur

- Mencari satu atau beberapa niche/kata kunci di lokasi yang ditentukan.
- Membatasi jumlah hasil maksimum per job (1–500).
- Meminta detail bisnis dan kontak yang tersedia dari Actor.
- Job berjalan di background; API mengembalikan ID untuk pengecekan status.
- Hasil tersimpan per job di SQLite dan tidak tertimpa oleh pencarian lain.
- Membaca hasil berhalaman sebagai JSON, menyertakan data mentah Actor bila diminta, atau mengunduh CSV.
- Menghapus hasil job yang sudah selesai melalui API.
- API key untuk endpoint pencarian dan data; endpoint health tetap publik.
- Filter CORS opsional untuk pemanggilan dari aplikasi browser.

## Prasyarat

- Python 3.10 atau lebih baru.
- Akun Apify, token API, dan akses ke Actor `compass/crawler-google-places`.

## Menjalankan di Windows

Buka PowerShell di folder proyek:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Isi file `.env`:

```env
APIFY_TOKEN=token_apify_anda
APIFY_ACTOR_ID=compass~crawler-google-places
API_KEY=ganti_dengan_secret_acak_panjang
DATABASE_PATH=leads.db
CORS_ORIGINS=
```

Buat API key acak, misalnya:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Salin hasilnya ke `API_KEY`. Jangan commit atau membagikan `.env`. File ini sudah dikecualikan melalui `.gitignore`.

Jalankan server lokal:

```powershell
uvicorn app:app --host 127.0.0.1 --port 8000
```

atau langsung:

```powershell
python main.py
```

- Health check: <http://127.0.0.1:8000/health>
- Dokumentasi interaktif: <http://127.0.0.1:8000/docs>
- Dokumentasi OpenAPI: <http://127.0.0.1:8000/openapi.json>
- Endpoint lengkap dan contoh payload: [`docs/API.md`](docs/API.md)

Untuk akses dari aplikasi pada komputer lain, server perlu bind ke alamat jaringan yang sesuai, misalnya `--host 0.0.0.0`. Lakukan hanya di jaringan tepercaya dan letakkan di belakang HTTPS/reverse proxy serta firewall. Jangan mengekspos server development langsung ke internet.

Untuk aplikasi browser lintas origin, set `CORS_ORIGINS` ke daftar origin dipisahkan koma, contohnya:

```env
CORS_ORIGINS=http://localhost:3000,https://crm.perusahaan.example
```

## Alur penggunaan

1. Kirim `POST /api/v1/jobs` dengan niches, lokasi, dan jumlah maksimum.
2. Simpan `job_id` pada aplikasi pemanggil.
3. Poll `GET /api/v1/jobs/{job_id}` sampai status `succeeded` atau `failed`.
4. Ambil hasil JSON atau CSV dari endpoint job.

Status yang mungkin: `queued`, `running`, `succeeded`, `failed`.

Jumlah hasil adalah batas maksimum, bukan jaminan jumlah minimum. API membagi batas hasil secara rata ke jumlah niche sebelum memanggil Actor; duplikasi antarniche dapat membuat jumlah unik lebih sedikit. Batas maksimum job dibatasi 500 hasil dan 10 job aktif/menunggu secara bersamaan. Scraping dan enrichment dapat dikenai biaya Apify sesuai penggunaan akun dan Actor.

## Data hasil

Data terstruktur mencakup place ID, nama bisnis, kategori, alamat, lokasi, telepon, email, WhatsApp bila tersedia, website, rating, jumlah ulasan, harga, jam buka, URL sumber, dan waktu pengambilan. Field `raw` pada opsi `include_raw=true` memuat item lengkap yang dikembalikan Actor.

Data hasil disimpan lokal di `DATABASE_PATH` (default `leads.db`). Atur backup, akses file, retensi, dan penghapusan data sesuai kebutuhan operasional.

## Batasan MVP

- Belum ada user/tenant terpisah, billing, rate limit per API key, atau job queue persisten.
- Job yang sedang berjalan tidak otomatis dilanjutkan jika proses server berhenti; job akan ditandai gagal saat server hidup kembali.
- API key bersama digunakan untuk semua pemanggil.
- Bentuk/field input dan output Actor dapat berubah; sesuaikan integrasi bila schema Actor berubah.
- Penggunaan data kontak untuk pemasaran perlu ditinjau terhadap hukum/ketentuan yang berlaku, termasuk permintaan opt-out.
