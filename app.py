import os, json, mimetypes, time
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, request, jsonify, render_template, send_from_directory

# ----------------------------
#   CONFIG BÁSICA
# ----------------------------
ROOT = Path(__file__).parent.resolve()
DATA_DIR = ROOT / "data"
PLAY_DIR = DATA_DIR / "playlists"
STATIC_DIR = ROOT / "static"
UPLOAD_DIR = STATIC_DIR / "uploads"

DATA_DIR.mkdir(exist_ok=True)
PLAY_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(STATIC_DIR))

BRANDING_FILE = DATA_DIR / "branding.json"
TERMINALS_FILE = DATA_DIR / "terminals.json"

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def write_json(path, obj):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def get_branding():
    b = read_json(BRANDING_FILE, {})
    if not b:
        b = {
            "name": "Studio RS TV",
            "primary_color": os.getenv("PRIMARY_COLOR", "#0d1b2a"),
            "logo": os.getenv("BRAND_LOGO", "")
        }
    return b

def detect_type(url_or_path):
    u = url_or_path.lower()
    if any(u.endswith(ext) for ext in [".mp4", ".mov", ".mkv", ".webm"]):
        return "video"
    if any(u.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]):
        return "image"
    if u.startswith("http") and "rss" in u:
        return "rss"
    return "file"

# estrutura:
# {
#   "clients": { "001": {"name":"joao","qty":2,"days":30} },
#   "terminals": { "001-01":{"display":"joao — 001-01","group":""}, ... }
# }
def get_terms():
    return read_json(TERMINALS_FILE, {"clients":{}, "terminals":{}})

def save_terms(obj):
    write_json(TERMINALS_FILE, obj)

def terminal_display(client_name, code_full):
    return f"{client_name} — {code_full}"

def playlist_path(code):
    return PLAY_DIR / f"{code}.json"

# ----------------------------
#   ROTAS PÚBLICAS (PAINEL)
# ----------------------------
@app.route("/")
def index():
    return render_template(
        "index.html",
        branding=get_branding(),
        support_link=os.getenv("SUPPORT_WA", "https://wa.me/5512996273989")
    )

# ----------------------------
#   DIAGNÓSTICO
# ----------------------------
@app.get("/api/v1/ping")
def ping():
    return jsonify({"ok": True, "ts": utcnow()})

# ----------------------------
#   UPLOADS
# ----------------------------
@app.get("/api/v1/uploads")
def list_uploads():
    items = []
    for p in sorted(UPLOAD_DIR.glob("*")):
        if p.is_file():
            url = f"/static/uploads/{p.name}"
            items.append({"url": url, "type": detect_type(url)})
    return jsonify({"ok": True, "uploads": items})

@app.post("/api/v1/upload")
def do_upload():
    if "files" not in request.files:
        return jsonify({"ok": False, "error": "no files"}), 400
    saved = []
    for f in request.files.getlist("files"):
        name = f.filename or "file"
        name = name.replace(" ", "_")
        ts = time.strftime("%Y%m%d-%H%M%S")
        fn = f"{ts}-{name}"
        dest = UPLOAD_DIR / fn
        f.save(dest)
        url = f"/static/uploads/{fn}"
        saved.append({"url": url, "type": detect_type(url)})
    return jsonify({"ok": True, "saved": saved})

# ----------------------------
#   TERMINAIS (CRUD SIMPLES)
# ----------------------------
@app.get("/api/v1/terminal")
def get_terminal():
    terms = get_terms()

    # lista
    if request.args.get("list"):
        out = []
        for code_full, meta in terms["terminals"].items():
            out.append({
                "code": code_full,
                "display": meta.get("display", code_full),
                "group": meta.get("group", ""),
                "online": False
            })
        return jsonify({"ok": True, "terminals": out})

    # detalhes
    code = request.args.get("code", "").strip()
    if not code:
        return jsonify({"ok": False, "error": "code required"}), 400

    # uploads (globais)
    uploads = []
    for p in sorted(UPLOAD_DIR.glob("*")):
        if p.is_file():
            url = f"/static/uploads/{p.name}"
            uploads.append({"url": url, "type": detect_type(url)})

    # playlist do terminal
    plf = playlist_path(code)
    playlist = read_json(plf, {"ok": True, "playlist": []}).get("playlist", [])

    disp = terms["terminals"].get(code, {}).get("display", code)

    return jsonify({"ok": True, "code": code, "display": disp, "uploads": uploads, "playlist": playlist})

@app.post("/api/v1/terminal")
def create_terminals():
    """
    body: { name, code, qty, days }
    cria codes: 001-01, 001-02, ... e exibe "nome — 001-01"
    """
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    code = (data.get("code") or "").strip()
    qty  = int(data.get("qty") or 1)
    days = int(data.get("days") or 30)

    if not name or not code:
        return jsonify({"ok": False, "error": "name and code required"}), 400

    terms = get_terms()
    terms["clients"][code] = {"name": name, "qty": qty, "days": days}

    for i in range(1, qty+1):
        code_full = f"{code}-{i:02d}"
        disp = terminal_display(name, code_full)
        terms["terminals"][code_full] = terms["terminals"].get(code_full, {})
        terms["terminals"][code_full]["display"] = disp
        terms["terminals"][code_full].setdefault("group", "")

    save_terms(terms)
    return jsonify({"ok": True, "created": qty})

# ----------------------------
#   PLAYLIST / CONFIG
# ----------------------------
@app.post("/api/v1/playlist")
def save_playlist():
    """
    body: { code, campaign?, items:[{type,url,duration?}, ...] }
    """
    data = request.get_json(force=True, silent=True) or {}
    code = (data.get("code") or "").strip()
    if not code:
        return jsonify({"ok": False, "error": "invalid code"}), 400

    items = data.get("items") or []
    out = []
    for it in items:
        t = it.get("type") or detect_type(it.get("url",""))
        url = it.get("url","").strip()
        if not url: 
            continue
        item = {"type": t, "url": url}
        if t != "video":
            item["duration"] = int(it.get("duration") or 10)
        out.append(item)

    pl = {
        "ok": True,
        "code": code,
        "campaign": data.get("campaign"),
        "playlist": out,
        "refresh_minutes": 10,
        "updated_at": utcnow()
    }
    write_json(playlist_path(code), pl)
    return jsonify({"ok": True})

@app.get("/api/v1/config")
def get_config():
    code = (request.args.get("code") or "").strip()
    if not code:
        return jsonify({"ok": False, "error": "code required"}), 400
    pl = read_json(playlist_path(code), {})
    if not pl:
        pl = {
            "ok": True,
            "code": code,
            "playlist": [],
            "refresh_minutes": 10,
            "updated_at": utcnow()
        }
    else:
        pl["ok"] = True
    return jsonify(pl)

# ----------------------------
#   STATIC
# ----------------------------
@app.get("/static/uploads/<path:fn>")
def static_uploads(fn):
    return send_from_directory(UPLOAD_DIR, fn)

# ----------------------------
#   MAIN
# ----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
