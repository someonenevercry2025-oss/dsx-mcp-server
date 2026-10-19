# Cara Hosting MCP Server DSX (Gratis / Murah)

## 1. Render.com (paling mudah, free tier)

1. Push repo ini ke GitHub.
2. Buka https://render.com → **New → Web Service** → connect repo.
3. Settings:
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python server.py`
   - **Instance type**: Free
4. Environment variables:
   - `MCP_TRANSPORT` = `streamable-http`
   - `HOST` = `0.0.0.0`
   - (PORT di-set otomatis oleh Render; pastikan `server.py` membaca `os.environ.get("PORT", "8000")`)
5. Deploy. URL contoh: `https://dsx-mcp-xxxx.onrender.com`
6. Endpoint MCP: `https://dsx-mcp-xxxx.onrender.com/mcp`

**Catatan free tier:** service sleep setelah ~15 menit idle. Request pertama bisa 30–60 detik cold start.

## 2. Fly.io

```bash
# Install flyctl, lalu:
fly launch --name dsx-mcp --region sin   # atau region terdekat
# Ikuti prompt; pilih Dockerfile
fly deploy
fly apps open
```

Endpoint: `https://dsx-mcp.fly.dev/mcp`

Free allowance cukup untuk traffic rendah. Bisa set machine stop when idle.

## 3. Railway

1. https://railway.app → New Project → Deploy from GitHub
2. Add variables `MCP_TRANSPORT=streamable-http`, `HOST=0.0.0.0`
3. Start command: `python server.py`
4. Generate domain.

Railway memberikan credit gratis terbatas (bukan unlimited free selamanya).

## 4. Google Cloud Run (scale-to-zero)

```bash
gcloud run deploy dsx-mcp \
  --source . \
  --region asia-southeast2 \
  --allow-unauthenticated \
  --port 8000
```

Free tier generous untuk request sedikit. Cocok production ringan.

## 5. Lokal + tunnel (untuk testing)

```bash
MCP_TRANSPORT=streamable-http python server.py
# Di terminal lain:
npx ngrok http 8000
# atau cloudflared tunnel --url http://localhost:8000
```

Pakai URL ngrok sebagai custom connector sementara.

## Verifikasi

Setelah live:

```bash
# Claude Code
claude mcp add --transport http dsx https://YOUR-URL/mcp

# Lalu di sesi Claude:
/mcp
# Pastikan tool check_dsx, generate_dsx muncul
```

Atau dari browser / curl, pastikan server merespons di path `/mcp` (status 200/405 tergantung method).

## Tips hemat free tier

- Hanya support **docx** (jangan install LibreOffice).
- Biarkan scale-to-zero / sleep.
- Jangan simpan state; server ini stateless.
- Rate-limit di reverse proxy jika dibuka publik.
