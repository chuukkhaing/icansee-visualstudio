# ICANSEE.AI Visual Studio — NO AWS Deployment (Works with SiteGround DNS)

You said: **no AWS at all**.

Important note:
- SiteGround Shared/Cloud plans commonly **do not support Node.js apps** in production.
- The simplest reliable “no-AWS” approach is to keep DNS on SiteGround but host your API on a managed app host like **Render.com** (or Railway/Fly.io).
- Your frontend can still be hosted on SiteGround as a static site at `app.icansee.ai`.

This package is beginner-friendly:
✅ Backend API (FastAPI) + OpenAI Images API  
✅ Local DB (SQLite) for MVP (no DB server needed)  
✅ Local file storage (uploads/outputs)  
✅ Docker-based deploy (Render supports Docker)  
✅ Simple static frontend (HTML) to upload to SiteGround

---

## 1) What you will build (simple)
1) User opens `https://app.icansee.ai`
2) Frontend uploads an image to `https://api.app.icansee.ai`
3) API calls OpenAI Images API to generate the output
4) API returns output image URL

---

## 2) Accounts you need
- OpenAI API key
- Render.com account
- SiteGround access to DNS Zone Editor + subdomain creation

---

# PART A — Deploy the backend API on Render

## A1) Create a GitHub repo
1) Create a repo on GitHub (example: `icansee-visualstudio`)
2) Upload the contents of this package to the repo

## A2) Create a Render Web Service
1) Login Render.com
2) New → **Web Service**
3) Connect your GitHub repo
4) Environment: **Docker**
5) Click Create / Deploy

## A3) Add environment variable
Render → Service → Environment:
- `OPENAI_API_KEY` = your OpenAI key

## A4) Test API
Render gives you a URL like:
`https://your-service.onrender.com`

Open:
- `https://your-service.onrender.com/health`
Expected: `{"ok": true}`

---

# PART B — Connect custom domain (api.app.icansee.ai)

## B1) Add custom domain in Render
Render → Service → Settings → Custom Domains
Add: `api.app.icansee.ai`

Render will show what DNS record to add (usually a CNAME).

## B2) Add DNS record in SiteGround
SiteGround → Services → Domains → icansee.ai → DNS Zone Editor

Add:
- Type: CNAME
- Host/Name: `api.app`
- Points to: (value Render shows, often `your-service.onrender.com`)

Wait 5–30 minutes.

Test:
- `https://api.app.icansee.ai/health`

---

# PART C — Host the frontend on SiteGround (app.icansee.ai)

## C1) Create subdomain `app`
SiteGround Site Tools → Domain → Subdomains → Create New Subdomain → `app`

## C2) Upload frontend files
Upload the contents of `frontend/` to the folder for the `app` subdomain.

## C3) Set your API URL
Open `frontend/index.html` and ensure:
`API_BASE_URL = "https://api.app.icansee.ai"`

---

# PART D — How generation works (MVP)
- Frontend uploads a photo to the API
- API uses OpenAI **Images Edits** with your photo as input and a “template prompt”
- API stores outputs locally and serves them via `/outputs/<id>.png`

---

If you want, after you create your Render service, paste the Render URL here and I’ll tell you exactly what DNS record to add in SiteGround.
