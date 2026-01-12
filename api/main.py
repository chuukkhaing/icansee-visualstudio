import os, io, uuid, base64, sqlite3
from typing import Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from PIL import Image

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

DATA_DIR = os.getenv("DATA_DIR", "./data")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
OUTPUTS_DIR = os.path.join(DATA_DIR, "outputs")
DB_PATH = os.path.join(DATA_DIR, "app.db")

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)

app = FastAPI(title="ICANSEE Visual Studio API (No AWS)")

# Add this CORS configuration
origins = [
    "https://icansee.infinityglobals.com",  # your frontend
    # "*"  # optionally allow all origins (not recommended for production)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,        # allowed origins
    allow_credentials=True,
    allow_methods=["*"],          # GET, POST, PUT, DELETE
    allow_headers=["*"],          # any headers
)

def db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute("""
      CREATE TABLE IF NOT EXISTS templates (
        id TEXT PRIMARY KEY,
        category TEXT NOT NULL,
        name TEXT NOT NULL,
        prompt TEXT NOT NULL,
        negative_prompt TEXT NOT NULL
      )
    """)
    cur.execute("""
      CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        category TEXT NOT NULL,
        input_path TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
      )
    """)
    cur.execute("""
      CREATE TABLE IF NOT EXISTS generations (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        template_id TEXT NOT NULL,
        status TEXT NOT NULL,
        output_path TEXT,
        error_message TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
      )
    """)
    conn.commit()
    conn.close()

def seed_templates():
    conn = db()
    cur = conn.cursor()
    items = [
      ("cos_01_clean_white","cosmetics","Clean Studio White",
       "Seamless pure white studio background, soft diffused light, premium e-commerce product photography, subtle gradient, soft contact shadow.",
       "text, watermark, logo, people, hands, extra products, distorted, cartoon, low quality"),
      ("fmcg_02_kitchen","fmcg","Kitchen Table Lifestyle",
       "Modern kitchen table lifestyle scene, soft daylight, warm inviting mood, shallow depth of field.",
       "text, watermark, logo, people, hands, extra products, distorted, cartoon, low quality"),
      ("wat_01_black_gold","watches","Black & Gold Luxury",
       "Luxury black background with subtle gold accents (abstract), dramatic but clean studio lighting, premium watch campaign.",
       "text, watermark, logo, people, hands, extra products, distorted, cartoon, low quality"),
      ("re_01_mls","real_estate","Neutral MLS Style",
       "Neutral MLS listing photo look, true-to-life colors, clean bright exposure, minimal staging, realistic interior photography.",
       "text, watermark, cartoon, distorted walls, bent lines, extreme HDR"),
    ]
    for t in items:
        cur.execute("""
          INSERT OR IGNORE INTO templates (id, category, name, prompt, negative_prompt)
          VALUES (?,?,?,?,?)
        """, t)
    conn.commit()
    conn.close()

@app.on_event("startup")
def startup():
    init_db()
    seed_templates()

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/templates")
def templates(category: Optional[str] = None):
    conn = db(); cur = conn.cursor()
    if category:
        cur.execute("SELECT * FROM templates WHERE category=? ORDER BY name", (category,))
    else:
        cur.execute("SELECT * FROM templates ORDER BY category, name")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

@app.post("/projects/upload")
async def upload_project(
    user_id: str = Form(...),
    category: str = Form(...),
    image: UploadFile = File(...),
):
    ext = (image.filename.split(".")[-1] if image.filename and "." in image.filename else "png").lower()
    pid = str(uuid.uuid4())
    in_path = os.path.join(UPLOADS_DIR, f"{pid}.{ext}")
    data = await image.read()
    with open(in_path, "wb") as f:
        f.write(data)

    conn = db(); cur = conn.cursor()
    cur.execute("INSERT INTO projects (id, user_id, category, input_path) VALUES (?,?,?,?)",
                (pid, user_id, category, in_path))
    conn.commit(); conn.close()
    return {"project_id": pid}

def openai_edit_image(input_path: str, prompt: str, size: str="1024x1024") -> Image.Image:
    if client is None:
        raise RuntimeError("OPENAI_API_KEY missing. Set it in Render environment variables.")
    with open(input_path, "rb") as f:
        result = client.images.generate(
            model="gpt-image-1",
            image=f,
            prompt=prompt,
            size=size
        )
    img_b64 = result.data[0].b64_json
    img_bytes = base64.b64decode(img_b64)
    return Image.open(io.BytesIO(img_bytes)).convert("RGBA")

@app.post("/projects/{project_id}/generate")
def generate(project_id: str, template_id: str = Form(...)):
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT * FROM projects WHERE id=?", (project_id,))
    proj = cur.fetchone()
    if not proj:
        conn.close()
        raise HTTPException(404, "Project not found")

    cur.execute("SELECT * FROM templates WHERE id=?", (template_id,))
    tpl = cur.fetchone()
    if not tpl:
        conn.close()
        raise HTTPException(400, "Template not found")

    gid = str(uuid.uuid4())
    cur.execute("INSERT INTO generations (id, project_id, template_id, status) VALUES (?,?,?,?)",
                (gid, project_id, template_id, "running"))
    conn.commit(); conn.close()

    try:
        base_prompt = (
            "Use the provided photo as the main subject. "
            "Do NOT change the subject shape, color, branding, or text. "
            "Create a new realistic background only. "
            f"Style: {tpl['prompt']} "
            f"Avoid: {tpl['negative_prompt']} "
            "No additional text or watermarks."
        )
        out_img = openai_edit_image(proj["input_path"], base_prompt, size="1024x1024")
        out_path = os.path.join(OUTPUTS_DIR, f"{gid}.png")
        out_img.save(out_path, format="PNG")

        conn = db(); cur = conn.cursor()
        cur.execute("UPDATE generations SET status=?, output_path=? WHERE id=?", ("succeeded", out_path, gid))
        conn.commit(); conn.close()

        return {"generation_id": gid, "status": "succeeded", "download_url": f"/outputs/{gid}.png"}
    except Exception as e:
        conn = db(); cur = conn.cursor()
        cur.execute("UPDATE generations SET status=?, error_message=? WHERE id=?", ("failed", str(e), gid))
        conn.commit(); conn.close()
        raise HTTPException(500, f"Generation failed: {e}")

@app.get("/outputs/{filename}")
def outputs(filename: str):
    safe = filename.replace("..","").replace("/","")
    path = os.path.join(OUTPUTS_DIR, safe)
    if not os.path.exists(path):
        raise HTTPException(404, "Not found")
    return FileResponse(path, media_type="image/png")
