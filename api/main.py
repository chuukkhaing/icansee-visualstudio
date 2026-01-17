import os, io, uuid, base64, sqlite3
from typing import Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from PIL import Image

# -------------------------------------------------
# CONFIG
# -------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

DATA_DIR = os.getenv("DATA_DIR", "./data")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
OUTPUTS_DIR = os.path.join(DATA_DIR, "outputs")
DB_PATH = os.path.join(DATA_DIR, "app.db")

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(OUTPUTS_DIR, exist_ok=True)

# -------------------------------------------------
# APP
# -------------------------------------------------
app = FastAPI(title="ICANSEE Visual Studio API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://icansee.infinityglobals.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------
# DATABASE
# -------------------------------------------------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS templates (
        id TEXT PRIMARY KEY,
        category TEXT,
        name TEXT,
        prompt TEXT,
        negative_prompt TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        category TEXT,
        input_path TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS generations (
        id TEXT PRIMARY KEY,
        project_id TEXT,
        template_id TEXT,
        status TEXT,
        output_path TEXT,
        error_message TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()

@app.on_event("startup")
def startup():
    init_db()

# -------------------------------------------------
# HEALTH
# -------------------------------------------------
@app.get("/health")
def health():
    return {"ok": True}

# -------------------------------------------------
# UPLOAD PROJECT IMAGE
# -------------------------------------------------
@app.post("/projects/upload")
async def upload_project(
    user_id: str = Form(...),
    category: str = Form(...),
    image: UploadFile = File(...)
):
    ext = image.filename.split(".")[-1].lower()
    pid = str(uuid.uuid4())
    in_path = os.path.join(UPLOADS_DIR, f"{pid}.{ext}")

    with open(in_path, "wb") as f:
        f.write(await image.read())

    conn = db()
    conn.execute(
        "INSERT INTO projects VALUES (?,?,?, ?,CURRENT_TIMESTAMP)",
        (pid, user_id, category, in_path)
    )
    conn.commit()
    conn.close()

    return {"project_id": pid}

# -------------------------------------------------
# OPENAI BACKGROUND GENERATION
# -------------------------------------------------
def generate_background(prompt: str, size="1024x1024") -> Image.Image:
    if not client:
        raise RuntimeError("OPENAI_API_KEY missing")

    result = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size=size
    )

    img_bytes = base64.b64decode(result.data[0].b64_json)
    return Image.open(io.BytesIO(img_bytes)).convert("RGBA")

# -------------------------------------------------
# COMPOSITE ORIGINAL IMAGE ON BACKGROUND
# -------------------------------------------------
def compose_image(product_path: str, background: Image.Image) -> Image.Image:
    product = Image.open(product_path).convert("RGBA")

    background = background.resize(product.size)

    x = (background.width - product.width) // 2
    y = (background.height - product.height) // 2

    background.paste(product, (x, y), product)
    return background

# -------------------------------------------------
# MAIN GENERATION FUNCTION
# -------------------------------------------------
def openai_edit_image(input_path: str, prompt: str) -> Image.Image:
    bg = generate_background(prompt)
    return compose_image(input_path, bg)

# -------------------------------------------------
# GENERATE FINAL IMAGE
# -------------------------------------------------
@app.post("/projects/{project_id}/generate")
def generate(project_id: str, template_prompt: str = Form(...)):
    conn = db()
    proj = conn.execute(
        "SELECT * FROM projects WHERE id=?",
        (project_id,)
    ).fetchone()

    if not proj:
        conn.close()
        raise HTTPException(404, "Project not found")

    gid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO generations (id, project_id, status) VALUES (?,?,?)",
        (gid, project_id, "running")
    )
    conn.commit()
    conn.close()

    try:
        final_prompt = (
            "Create a realistic professional studio background only. "
            "Do NOT add text, logos, people, or products. "
            "Soft natural shadows. "
            f"Style: {template_prompt}"
        )

        img = openai_edit_image(proj["input_path"], final_prompt)

        out_path = os.path.join(OUTPUTS_DIR, f"{gid}.png")
        img.save(out_path, "PNG")

        conn = db()
        conn.execute(
            "UPDATE generations SET status=?, output_path=? WHERE id=?",
            ("succeeded", out_path, gid)
        )
        conn.commit()
        conn.close()

        return {
            "generation_id": gid,
            "status": "succeeded",
            "download_url": f"/outputs/{gid}.png"
        }

    except Exception as e:
        conn = db()
        conn.execute(
            "UPDATE generations SET status=?, error_message=? WHERE id=?",
            ("failed", str(e), gid)
        )
        conn.commit()
        conn.close()
        raise HTTPException(500, str(e))

# -------------------------------------------------
# DOWNLOAD OUTPUT
# -------------------------------------------------
@app.get("/outputs/{filename}")
def outputs(filename: str):
    path = os.path.join(OUTPUTS_DIR, filename.replace("..", ""))
    if not os.path.exists(path):
        raise HTTPException(404)
    return FileResponse(path, media_type="image/png")
