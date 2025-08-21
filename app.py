import os, json, datetime, random, string
from pathlib import Path
from flask import Flask, request, jsonify, render_template, send_from_directory

# -----------------------------------------------------------------------------
# Configurações
# -----------------------------------------------------------------------------
APP_ROOT   = Path(__file__).parent.resolve()
STATIC_DIR = APP_ROOT / "static"
UPLOAD_DIR = STATIC_DIR / "uploads"

# Onde vamos persistir os JSONs (mude em Render via env var e um Disk)
DATA_DIR   = Path(os.getenv("DATA_DIR", APP_ROOT / "data"))
PLAY_DIR   = DATA_DIR / "playlists"
DATA_DIR.mkdir(parents=True, exist_ok=True)
PLAY_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

CLIENTS_FILE   = DATA_DIR / "clients.json"   # {"clients":[{code,name,terminals:[1,2],license_until: "ISO"}]}
BRANDING_FILE  = DATA_DIR / "branding.json"  # opcional
PAIRS_FILE     = DATA_DIR / "pairs.json"     # {"<pairCode>": {"client_code":..., "term":...}}

ALLOWED_EXT = {".mp4",".mov",".mkv",".webm",".png",".jpg",".jpeg",".gif",".webp",".mp3",".wav"}

# -----------------------------------------------------------------------------
# Utilidades
# -----------------------------------------------------------------------------
def utcnow_iso():
    return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat()

def load_json(path: Path, default):
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default

def save_json(path: Path, data):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)

def safe_filename(name: str) -> str:
    ok = "-_.() %s%s" % (string.ascii_letters, string.digits)
    return "".join(c for c in name if c in ok)

def guess_type(p: Path) -> str:
    ext = p.suffix.lower()
    if ext in {".png",".jpg",".jpeg",".gif",".webp"}:
        return "image"
    if ext in {".mp4",".mov",".mkv",".webm"}:
        return "video"
    if ext in {".mp3",".wav"}:
        return "audio"
    return "file"

def parse_code(code: str):
    """Retorna (client_code, term_int) a partir de '001-02'."""
    code = (code or "").strip()
    if "-" not in code:
        return None, None
    c, t = code.split("-", 1)
    try:
        term = int(t)
        return c, term
    except Exception:
        return None, None

# -----------------------------------------------------------------------------
# Branding
# -----------------------------------------------------------------------------
def get_branding():
    b = load_json(BRANDING_FILE, {})
    # sobrescreve por ENV se tiver
    b.setdefault("name",  os.getenv("BRAND_NAME", "Studio RS TV"))
    b.setdefault("primary_color", os.getenv("PRIMARY_COLOR", "#0d1b2a"))
    b.setdefault("logo_url", os.getenv("BRAND_LOGO_URL", ""))  # png transparente recomendado
    return b

# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
app = Flask(__name__, static_folder=str(STATIC_DIR), template_folder=str(APP_ROOT / "templates"))

@app.route("/")
def index():
    return render_template(
        "index.html",
        branding=get_branding(),
        support_link=os.getenv("SUPPORT_WA", "https://wa.me/5512996273989")
    )

# -----------------------------------------------------------------------------
# Uploads
# -----------------------------------------------------------------------------
@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "missing file"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"ok": False, "error": "empty filename"}), 400

    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"ok": False, "error": "ext not allowed"}), 400

    # prefixo com data/hora para evitar colisão
    stamp = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    fname = f"{stamp}-{safe_filename(f.filename)}"
    dest  = UPLOAD_DIR / fname
    f.save(dest)

    url = f"/static/uploads/{fname}"
    return jsonify({"ok": True, "url": url, "type": guess_type(dest), "filename": fname})

@app.route("/api/v1/uploads")
def api_list_uploads():
    items = []
    for p in sorted(UPLOAD_DIR.glob("*")):
        if not p.is_file(): 
            continue
        items.append({
            "filename": p.name,
            "url": f"/static/uploads/{p.name}",
            "type": guess_type(p),
            "size": p.stat().st_size
        })
    return jsonify({"ok": True, "items": items})

# -----------------------------------------------------------------------------
# Clientes / Terminais
# -----------------------------------------------------------------------------
def read_clients():
    data = load_json(CLIENTS_FILE, {"clients": []})
    # normaliza
    out = []
    for c in data.get("clients", []):
        code = str(c.get("code","")).strip()
        name = c.get("name") or f"Cliente {code}"
        terms = c.get("terminals") or []
        out.append({
            "code": code,
            "name": name,
            "terminals": terms,
            "license_until": c.get("license_until")
        })
    return {"clients": out}

def write_clients(clients_data):
    save_json(CLIENTS_FILE, clients_data)

@app.route("/api/v1/clients")
def api_clients():
    data = read_clients()
    # devolve em um formato que o index espera
    items = []
    for c in data["clients"]:
        items.append({
            "code": c["code"],
            "name": c["name"],
            "terminals": c["terminals"]
        })
    return jsonify({"ok": True, "items": items})

@app.route("/api/v1/client", methods=["POST"])
def api_upsert_client():
    j = request.get_json(silent=True) or {}
    name  = (j.get("name") or "").strip()
    code  = (j.get("client_code") or "").strip()
    terms = int(j.get("terminals") or 1)
    license_days = int(j.get("license_days") or 30)

    if not code:
        return jsonify({"ok": False, "error": "missing client_code"}), 400
    if terms < 1: terms = 1

    data = read_clients()
    # calcula license_until
    until = (datetime.datetime.utcnow() + datetime.timedelta(days=license_days)).date().isoformat()

    terminals = list(range(1, terms + 1))
    found = False
    for c in data["clients"]:
        if c["code"] == code:
            c["name"] = name or c["name"]
            c["terminals"] = terminals
            c["license_until"] = until
            found = True
            break
    if not found:
        data["clients"].append({
            "code": code,
            "name": name or f"Cliente {code}",
            "terminals": terminals,
            "license_until": until
        })

    write_clients(data)
    return jsonify({"ok": True, "client": code, "terminals": terminals})

# -----------------------------------------------------------------------------
# Playlists / Config do terminal
# -----------------------------------------------------------------------------
def playlist_path(client_code: str, term: int) -> Path:
    return PLAY_DIR / f"{client_code}-{str(term).zfill(2)}.json"

DEFAULT_SCHEDULE_HOURS = [6, 12, 18]

def read_config_for(code: str):
    client, term = parse_code(code)
    if not client or not term:
        return None

    p = playlist_path(client, term)
    if p.exists():
        cfg = load_json(p, {})
        # compat older
        cfg.setdefault("refresh_minutes", 10)
        cfg.setdefault("update_schedule_hours", DEFAULT_SCHEDULE_HOURS)
        cfg.setdefault("code", f"{client}-{str(term).zfill(2)}")
        cfg.setdefault("updated_at", utcnow_iso())
        cfg.setdefault("ok", True)
        return cfg

    # sem playlist salva ainda — devolve básico
    return {
        "code": f"{client}-{str(term).zfill(2)}",
        "ok": True,
        "playlist": [],
        "refresh_minutes": 10,
        "update_schedule_hours": DEFAULT_SCHEDULE_HOURS,
        "updated_at": utcnow_iso(),
        "config_version": 1
    }

@app.route("/api/v1/config")
def api_config():
    code = request.args.get("code","").strip()
    cfg = read_config_for(code)
    if not cfg:
        return jsonify({"ok": False, "error": "invalid code"}), 400
    return jsonify(cfg)

@app.route("/api/v1/playlist", methods=["POST"])
def api_save_playlist():
    j = request.get_json(silent=True) or {}
    code = (j.get("code") or "").strip()
    items = j.get("items") or []
    refresh = int(j.get("refresh_minutes") or 10)
    hours   = j.get("update_schedule_hours") or DEFAULT_SCHEDULE_HOURS

    client, term = parse_code(code)
    if not client or not term:
        return jsonify({"ok": False, "error": "invalid code"}), 400

    # normaliza itens
    norm = []
    for it in items:
        t = (it.get("type") or "").lower()
        url = (it.get("url") or "").strip()
        dur = int(it.get("duration") or 0)
        if t == "image" and (dur <= 0):
            dur = 10
        if t == "video":
            dur = 0
        if not url:
            continue
        norm.append({"type": t or "video", "url": url, "duration": dur})

    cfg_old = read_config_for(code) or {}
    version = int(cfg_old.get("config_version") or 0) + 1

    cfg = {
        "code": f"{client}-{str(term).zfill(2)}",
        "ok": True,
        "playlist": norm,
        "refresh_minutes": refresh,
        "update_schedule_hours": hours,
        "updated_at": utcnow_iso(),
        "config_version": version
    }
    save_json(playlist_path(client, term), cfg)
    return jsonify({"ok": True, "config_version": version})

@app.route("/api/v1/terminal/settings", methods=["POST"])
def api_save_settings():
    j = request.get_json(silent=True) or {}
    client = (j.get("client_code") or "").strip()
    term   = j.get("term")
    try:
        term = int(term)
    except Exception:
        return jsonify({"ok": False, "error": "invalid term"}), 400

    refresh = int(j.get("refresh_minutes") or 10)
    hours   = j.get("update_schedule_hours") or DEFAULT_SCHEDULE_HOURS

    p = playlist_path(client, term)
    cfg = load_json(p, {})
    cfg.setdefault("code", f"{client}-{str(term).zfill(2)}")
    cfg.setdefault("playlist", [])
    cfg["refresh_minutes"] = refresh
    cfg["update_schedule_hours"] = hours
    cfg["updated_at"] = utcnow_iso()
    cfg.setdefault("config_version", 1)
    save_json(p, cfg)
    return jsonify({"ok": True})

# -----------------------------------------------------------------------------
# Comandos / Pareamento (stubs simples)
# -----------------------------------------------------------------------------
@app.route("/api/v1/terminal/command", methods=["POST"])
def api_command():
    # Aqui poderíamos enfileirar comando para o player (ex.: restart).
    # Por enquanto, só retornamos ok.
    return jsonify({"ok": True})

@app.route("/api/v1/pair/request", methods=["POST"])
def api_pair_request():
    # Gera um código que o aparelho exibiria
    code = "".join(random.choices(string.digits, k=8))
    pairs = load_json(PAIRS_FILE, {})
    pairs[code] = {"created_at": utcnow_iso()}
    save_json(PAIRS_FILE, pairs)
    return jsonify({"ok": True, "pair_code": code})

@app.route("/api/v1/pair/attach", methods=["POST"])
def api_pair_attach():
    j = request.get_json(silent=True) or {}
    pair_code  = (j.get("pair_code") or "").strip()
    client     = (j.get("client_code") or "").strip()
    try:
        term = int(j.get("term"))
    except Exception:
        return jsonify({"ok": False, "error": "invalid term"}), 400

    pairs = load_json(PAIRS_FILE, {})
    if pair_code not in pairs:
        return jsonify({"ok": False, "error": "pair not found"}), 404
    pairs[pair_code] = {"client_code": client, "term": term, "attached_at": utcnow_iso()}
    save_json(PAIRS_FILE, pairs)
    return jsonify({"ok": True})

# -----------------------------------------------------------------------------
# Saúde
# -----------------------------------------------------------------------------
@app.route("/api/v1/ping")
def api_ping():
    return jsonify({"ok": True, "ts": utcnow_iso()})

# Favicon opcional
@app.route("/favicon.ico")
def favicon():
    return "", 204

# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
