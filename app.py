import os, json, re
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify, render_template, send_from_directory
from werkzeug.utils import secure_filename

# ------------------------------
# Config
# ------------------------------
APP_NAME = os.getenv("BRAND_NAME", "Studio RS TV")
PRIMARY_COLOR = os.getenv("BRAND_COLOR", "#0a2458")  # azul marinho
LOGO_URL = os.getenv("BRAND_LOGO_URL", "")           # pode por URL pública do Drive (modo público)
SUPPORT_WA = os.getenv("SUPPORT_WA", "https://wa.me/5512999999999")

UPLOAD_DIR = os.getenv("UPLOAD_DIR", "static/uploads")
DB_PATH = os.getenv("DB_PATH", "data/db.json")

ALLOWED_EXT = {
    ".mp4", ".mov", ".mkv", ".webm",
    ".png", ".jpg", ".jpeg", ".gif", ".webp"
}

# ------------------------------
# App
# ------------------------------
app = Flask(__name__, static_folder="static", template_folder="templates")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# ------------------------------
# Helpers
# ------------------------------
CODE_RE = re.compile(r'^([A-Za-z0-9]+)-([0-9]{1,3})$')

def now_utc():
    return datetime.now(timezone.utc)

def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()

def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

def ensure_db():
    if not os.path.exists(DB_PATH):
        with open(DB_PATH, "w", encoding="utf-8") as f:
            json.dump({"clients": {}}, f, ensure_ascii=False, indent=2)

def load_db():
    ensure_db()
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(db: dict):
    tmp = DB_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DB_PATH)

def norm_client_code(c: str) -> str:
    c = (c or "").strip()
    if c.isdigit():
        return f"{int(c):03d}"
    return c

def norm_terminal_code(t: str) -> str:
    t = (t or "").strip()
    if t.isdigit():
        return f"{int(t):02d}"
    return t

def split_code(code: str):
    """Aceita '1-3' ou '001-03' -> ('001','03')"""
    code = (code or "").strip()
    m = CODE_RE.match(code)
    if not m:
        return None, None
    client_raw, term_raw = m.group(1), m.group(2)
    return norm_client_code(client_raw), norm_terminal_code(term_raw)

def _is_image(path: str) -> bool:
    ext = os.path.splitext((path or "").lower())[1]
    return ext in (".png", ".jpg", ".jpeg", ".gif", ".webp")

def _is_video(path: str) -> bool:
    ext = os.path.splitext((path or "").lower())[1]
    return ext in (".mp4", ".mov", ".mkv", ".webm")

def _abs_url(u: str) -> str:
    if not u:
        return u
    if u.startswith("http://") or u.startswith("https://"):
        return u
    if not u.startswith("/"):
        u = "/" + u
    return request.url_root.rstrip("/") + u

def get_branding():
    return {
        "name": APP_NAME,
        "primary_color": PRIMARY_COLOR,
        "logo_url": LOGO_URL
    }

# ------------------------------
# Modelo de dados (clientes/terminais/licença)
# ------------------------------
def ensure_client(db: dict, client_code: str, name: str = None, license_days: int = 30):
    client_code = norm_client_code(client_code)
    clients = db.setdefault("clients", {})
    cli = clients.get(client_code)
    if not cli:
        expires = now_utc() + timedelta(days=license_days)
        cli = {
            "code": client_code,
            "name": name or f"Cliente {client_code}",
            "license_expires_at": iso(expires),
            "terminals": {}  # "01": {"playlist": [], "refresh_minutes": 10}
        }
        clients[client_code] = cli
    else:
        if name:
            cli["name"] = name
    return cli

def ensure_terminals(cli: dict, terminals: int):
    for i in range(1, int(terminals) + 1):
        tcode = norm_terminal_code(str(i))
        cli["terminals"].setdefault(tcode, {"playlist": [], "refresh_minutes": 10})

def extend_license_days(cli: dict, days: int):
    current = parse_iso(cli["license_expires_at"])
    base = current if current > now_utc() else now_utc()
    cli["license_expires_at"] = iso(base + timedelta(days=int(days)))

def license_ok(cli: dict) -> bool:
    try:
        return parse_iso(cli["license_expires_at"]) >= now_utc()
    except Exception:
        return False

def get_terminal(db: dict, client_code: str, term_code: str):
    cli = db.get("clients", {}).get(client_code)
    if not cli:
        return None, None
    term = cli["terminals"].get(term_code)
    return cli, term

# ------------------------------
# Páginas
# ------------------------------
@app.get("/")
def index():
    return render_template(
        "index.html",
        branding=get_branding(),
        support_link=SUPPORT_WA
    )

@app.get("/clients")
def clients_page():
    return render_template("clients.html", branding=get_branding())

# ------------------------------
# Uploads
# ------------------------------
@app.post("/upload")
def upload():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "file_field_missing"}), 400
    f = request.files["file"]
    if not f or f.filename == "":
        return jsonify({"ok": False, "error": "empty_filename"}), 400

    name = secure_filename(f.filename)
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"ok": False, "error": "ext_not_allowed"}), 400

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    final_name = f"{ts}-{name}"
    save_path = os.path.join(UPLOAD_DIR, final_name)
    f.save(save_path)
    rel_url = f"/static/uploads/{final_name}"
    return jsonify({"ok": True, "url": rel_url, "type": ("image" if _is_image(rel_url) else "video")})

@app.get("/api/v1/uploads")
def list_uploads():
    files = []
    for fname in sorted(os.listdir(UPLOAD_DIR)):
        p = os.path.join(UPLOAD_DIR, fname)
        if not os.path.isfile(p):
            continue
        ext = os.path.splitext(fname)[1].lower()
        if ext not in ALLOWED_EXT:
            continue
        files.append({
            "filename": fname,
            "url": f"/static/uploads/{fname}",
            "type": "image" if _is_image(fname) else "video"
        })
    return jsonify({"ok": True, "items": files})

# ------------------------------
# API: Clientes / Licenças
# ------------------------------
@app.get("/api/v1/clients")
def api_list_clients():
    db = load_db()
    items = []
    for code, cli in db.get("clients", {}).items():
        items.append({
            "code": cli["code"],
            "name": cli.get("name"),
            "license_expires_at": cli.get("license_expires_at"),
            "license_ok": license_ok(cli),
            "terminals": sorted(list(cli.get("terminals", {}).keys()))
        })
    return jsonify({"ok": True, "items": sorted(items, key=lambda x: x["code"])})

@app.post("/api/v1/client")
def api_create_or_update_client():
    data = request.get_json(force=True, silent=True) or {}
    client_code = (data.get("client_code") or "").strip()
    name = (data.get("name") or "").strip()
    license_days = int(data.get("license_days") or 30)
    terminals = int(data.get("terminals") or 1)

    if not client_code:
        return jsonify({"ok": False, "error": "missing client_code"}), 400

    db = load_db()
    cli = ensure_client(db, client_code, name=name, license_days=license_days)
    ensure_terminals(cli, terminals)
    save_db(db)

    return jsonify({"ok": True, "client": cli})

@app.post("/api/v1/client/<client_code>/license/extend")
def api_extend_license(client_code):
    days = int((request.get_json(force=True, silent=True) or {}).get("days") or 15)
    db = load_db()
    cli = db.get("clients", {}).get(norm_client_code(client_code))
    if not cli:
        return jsonify({"ok": False, "error": "client_not_found"}), 404
    extend_license_days(cli, days)
    save_db(db)
    return jsonify({"ok": True, "license_expires_at": cli["license_expires_at"]})

# ------------------------------
# API: Playlist por terminal
# ------------------------------
@app.post("/api/v1/playlist")
def api_set_playlist():
    """
    body: { "code": "001-03",
            "items": [{"url":"/static/uploads/x.mp4","type":"video","duration":0}, ...],
            "refresh_minutes": 10 }
    """
    data = request.get_json(force=True, silent=True) or {}
    code = (data.get("code") or "").strip()
    client_code, term_code = split_code(code)
    if not client_code:
        return jsonify({"ok": False, "error": "invalid code"}), 400

    db = load_db()
    cli, term = get_terminal(db, client_code, term_code)
    if not cli or not term:
        return jsonify({"ok": False, "error": "client_or_terminal_not_found"}), 404

    term["playlist"] = data.get("items") or []
    if "refresh_minutes" in data:
        term["refresh_minutes"] = int(data["refresh_minutes"])
    save_db(db)

    return jsonify({"ok": True, "code": f"{client_code}-{term_code}"})

# ------------------------------
# API: Config para o APK
# ------------------------------
@app.get("/api/v1/config")
def api_config():
    code = (request.args.get("code") or "").strip()
    client_code, term_code = split_code(code)
    if not client_code:
        return jsonify({"ok": False, "error": "invalid_code_format", "message": "Use CLIENTE-TERMINAL, ex.: 001-01"}), 400

    db = load_db()
    cli, term = get_terminal(db, client_code, term_code)
    if not cli or not term:
        return jsonify({"ok": False, "error": "not_found", "message": "Cliente ou terminal não encontrado"}), 404

    if not license_ok(cli):
        return jsonify({
            "ok": False,
            "error": "license_expired",
            "message": f"Licença expirada para {cli.get('name') or cli['code']}"
        }), 403

    raw_playlist = term.get("playlist") or []
    normalized = []
    for item in raw_playlist:
        url = (item.get("url") or "").strip()
        t = (item.get("type") or "").strip().lower()
        dur = int(item.get("duration") or 0)

        if not t:
            t = "image" if _is_image(url) else "video"
        if t == "video":
            dur = 0  # vídeo toca até o fim
        elif t == "image":
            if dur <= 0:
                dur = int(os.getenv("IMAGE_DURATION_SECONDS", "10"))

        normalized.append({
            "type": t,
            "url": _abs_url(url),
            "duration": int(dur)
        })

    refresh = int(term.get("refresh_minutes") or os.getenv("REFRESH_MINUTES", "10"))

    return jsonify({
        "ok": True,
        "code": f"{client_code}-{term_code}",
        "campaign": f"{cli.get('name','Cliente')} — {client_code}-{term_code}",
        "playlist": normalized,
        "refresh_minutes": refresh,
        "updated_at": iso(now_utc())
    })

# ------------------------------
# Health
# ------------------------------
@app.get("/api/v1/ping")
def ping():
    return jsonify({"ok": True, "ts": iso(now_utc())})

# ------------------------------
# Run
# ------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=True)
