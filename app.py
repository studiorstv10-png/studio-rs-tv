import os, json, re, uuid
from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify, request, send_from_directory, abort

# ------------------------------
# CONFIG
# ------------------------------
APP_TITLE = "Studio RS TV"
ADMIN_KEY = os.environ.get("ADMIN_KEY", "admin123")
DB_PATH = os.environ.get("DB_PATH", "data/db.json")

# Marca (fixa por env)
BRAND_NAME  = os.environ.get("BRAND_NAME",  "Studio RS TV")
BRAND_COLOR = os.environ.get("BRAND_COLOR", "#0d1b2a")
BRAND_LOGO  = os.environ.get("BRAND_LOGO",  None)  # URL PNG (opcional)
BRAND_LOCKED = os.environ.get("BRAND_LOCKED", "1") == "1"

POLL_SECONDS_DEFAULT = int(os.environ.get("POLL_SECONDS", "60"))

# ------------------------------
# APP / STATIC
# ------------------------------
app = Flask(
    __name__,
    static_folder="static",         # painéis, assets, uploads
    static_url_path=""              # / -> static/index.html, /uploads -> static/uploads
)

# Garante pastas
os.makedirs("data", exist_ok=True)
os.makedirs(os.path.join(app.static_folder, "uploads"), exist_ok=True)

# ------------------------------
# HELPERS
# ------------------------------
CODE_RX = re.compile(r"^[A-Za-z0-9_\-]{1,32}$")

def _now():
    return datetime.now(timezone.utc)

def _now_iso():
    return _now().isoformat()

def _in_days(n):
    return (_now() + timedelta(days=n)).date().isoformat()

def load_db():
    if not os.path.exists(DB_PATH):
        db = {
            "brand": {
                "name": BRAND_NAME,
                "primary_color": BRAND_COLOR,
                "logo": BRAND_LOGO
            },
            "terminals": {},   # "CODE": {...}
            "playlists": {}    # "CODE": [ {type,url,duration}, ...]
        }
        save_db(db)
        return db
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # Se corromper, recomeça básico (poderia logar)
        db = {
            "brand": {
                "name": BRAND_NAME,
                "primary_color": BRAND_COLOR,
                "logo": BRAND_LOGO
            },
            "terminals": {},
            "playlists": {}
        }
        save_db(db)
        return db

def save_db(db):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def require_admin(data):
    key = (data.get("key") or "").strip()
    if key != ADMIN_KEY:
        abort(401)

# ------------------------------
# ROTAS PÁGINA
# ------------------------------
@app.get("/")
def index():
    # Serve painel (static/index.html)
    return app.send_static_file("index.html")

# (Opcional) Favicon silencioso
@app.get("/favicon.ico")
def favicon():
    return ("", 204)

# ------------------------------
# MARCA
# ------------------------------
@app.get("/api/v1/brand")
def brand_get():
    db = load_db()
    brand = db.get("brand", {})
    # força env (se travado)
    if BRAND_LOCKED:
        brand = {"name": BRAND_NAME, "primary_color": BRAND_COLOR, "logo": BRAND_LOGO}
    return jsonify({"brand": brand, "locked": BRAND_LOCKED})

@app.post("/api/v1/brand")
def brand_set():
    if BRAND_LOCKED:
        return jsonify({"error": "locked"}), 403
    data = request.get_json(silent=True) or {}
    require_admin(data)

    name  = (data.get("name") or BRAND_NAME).strip()
    color = (data.get("primary_color") or BRAND_COLOR).strip()
    logo  = (data.get("logo") or BRAND_LOGO)

    db = load_db()
    db["brand"] = {"name": name, "primary_color": color, "logo": logo}
    save_db(db)
    return jsonify({"ok": True, "brand": db["brand"]})

# ------------------------------
# TERMINAIS
# ------------------------------
@app.get("/api/v1/admin/terminals")
def list_terminals():
    # listagem simples (sem key pra facilitar select do painel)
    db = load_db()
    terms = list(db.get("terminals", {}).values())
    return jsonify({"items": terms})

@app.post("/api/v1/admin/terminals")
def create_terminal():
    data = request.get_json(silent=True) or {}
    require_admin(data)

    code  = (data.get("code") or "").strip()
    name  = (data.get("name") or "").strip()
    group = (data.get("group") or "").strip()

    if not code or not CODE_RX.match(code):
        return jsonify({"error": "invalid_code",
                        "detail": "Use apenas letras, números, '-' ou '_' (até 32 chars)."}), 400
    if not name:
        name = code

    db = load_db()
    if code in db["terminals"]:
        return jsonify({"error": "exists"}), 409

    db["terminals"][code] = {
        "code": code,
        "name": name,
        "group": group,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "trial_until": _in_days(15)
    }
    db["playlists"].setdefault(code, [])
    save_db(db)
    return jsonify({"ok": True, "terminal": db["terminals"][code]})

# ------------------------------
# PLAYLIST
# ------------------------------
@app.get("/api/v1/playlist")
def get_playlist():
    code = (request.args.get("code") or "").strip()
    db = load_db()
    items = db.get("playlists", {}).get(code, [])
    return jsonify({"code": code, "items": items})

@app.post("/api/v1/playlist")
def set_playlist():
    data = request.get_json(silent=True) or {}
    require_admin(data)

    code  = (data.get("code") or "").strip()
    items = data.get("items", [])

    if not code:
        return jsonify({"error": "missing_code"}), 400

    db = load_db()
    if code not in db["terminals"]:
        return jsonify({"error": "not_found"}), 404

    # valida itens básicos
    sanitized = []
    for it in items:
        t = (it.get("type") or "").strip().lower()
        url = (it.get("url") or "").strip()
        dur = it.get("duration")
        if t not in ("video","image","rss"):
            continue
        if not url:
            continue
        if t == "image":
            # duração obrigatória para image/rss
            try:
                dur = int(dur)
            except Exception:
                dur = 10
        sanitized.append({"type": t, "url": url, "duration": dur})

    db["playlists"][code] = sanitized
    db["terminals"][code]["updated_at"] = _now_iso()
    save_db(db)
    return jsonify({"ok": True, "count": len(sanitized)})

# ------------------------------
# CONFIG PARA O PLAYER
# ------------------------------
@app.get("/api/v1/config")
def get_config():
    code = (request.args.get("code") or "").strip()
    db = load_db()

    term = db.get("terminals", {}).get(code)
    if not term:
        return jsonify({"error": "terminal_not_found"}), 404

    brand = db.get("brand", {"name": BRAND_NAME, "primary_color": BRAND_COLOR, "logo": BRAND_LOGO})
    if BRAND_LOCKED:
        brand = {"name": BRAND_NAME, "primary_color": BRAND_COLOR, "logo": BRAND_LOGO}

    playlist = db.get("playlists", {}).get(code, [])

    resp = {
        "brand": brand,
        "name": APP_TITLE,
        "layout": "16:9",
        "poll_seconds": POLL_SECONDS_DEFAULT,
        "playlist": playlist,
        "terminal": {"code": code, "name": term.get("name")},
        "trial_until": term.get("trial_until"),
        "updated_at": _now_iso(),
        "status": "ok",
        "config_version": 1
    }
    return jsonify(resp)

# ------------------------------
# UPLOADS
# ------------------------------
@app.post("/api/v1/upload")
def upload_file():
    # multipart/form-data  -> field: file
    if "file" not in request.files:
        return jsonify({"error": "missing_file"}), 400
    f = request.files["file"]
    if f.filename == "":
        return jsonify({"error": "empty_filename"}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    safe_name = uuid.uuid4().hex + ext
    dest_dir = os.path.join(app.static_folder, "uploads")
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, safe_name)
    f.save(path)

    # URL pública
    url = f"/uploads/{safe_name}"
    return jsonify({"ok": True, "url": url})

# ------------------------------
# PING
# ------------------------------
@app.get("/api/v1/ping")
def ping():
    return jsonify({"ok": True, "ts": _now_iso()})

# ------------------------------
# START
# ------------------------------
if __name__ == "__main__":
    # Dev: http://localhost:8000
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
