import os, json, datetime, random, string
from pathlib import Path
from flask import Flask, request, jsonify, render_template

# ---------------------------------------------------------------------------
# Paths & diretórios
# ---------------------------------------------------------------------------
APP_ROOT   = Path(__file__).parent.resolve()
STATIC_DIR = APP_ROOT / "static"
UPLOAD_DIR = STATIC_DIR / "uploads"

DATA_DIR = Path(os.getenv("DATA_DIR", APP_ROOT / "data"))  # monte um Disk e aponte aqui
PLAY_DIR = DATA_DIR / "playlists"

DATA_DIR.mkdir(parents=True, exist_ok=True)
PLAY_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

CLIENTS_FILE  = DATA_DIR / "clients.json"   # {"clients":[{code,name,terminals:[1,2],license_until}]}
BRANDING_FILE = DATA_DIR / "branding.json"
PAIRS_FILE    = DATA_DIR / "pairs.json"
STATUS_FILE   = DATA_DIR / "status.json"    # {"001-01":{"last_seen": "...", "online":true, "playing": "..."}}

ALLOWED_EXT = {".mp4",".mov",".mkv",".webm",".png",".jpg",".jpeg",".gif",".webp",".mp3",".wav"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
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
    if ext in {".png",".jpg",".jpeg",".gif",".webp"}: return "image"
    if ext in {".mp4",".mov",".mkv",".webm"}:         return "video"
    if ext in {".mp3",".wav"}:                        return "audio"
    return "file"

def parse_code(code: str):
    code = (code or "").strip()
    if "-" not in code:
        return None, None
    c, t = code.split("-", 1)
    try:
        term = int(t)
        return c, term
    except Exception:
        return None, None

# ---------------------------------------------------------------------------
# Branding
# ---------------------------------------------------------------------------
def get_branding():
    b = load_json(BRANDING_FILE, {})
    b.setdefault("name",  os.getenv("BRAND_NAME", "Studio RS TV"))
    b.setdefault("primary_color", os.getenv("PRIMARY_COLOR", "#0d1b2a"))
    b.setdefault("logo_url", os.getenv("BRAND_LOGO_URL", ""))  # png branco/transparent
    return b

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder=str(STATIC_DIR), template_folder=str(APP_ROOT / "templates"))

@app.route("/")
def index():
    return render_template(
        "index.html",
        branding=get_branding(),
        support_link=os.getenv("SUPPORT_WA", "https://wa.me/5512996273989")
    )

# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Clientes / Terminais
# ---------------------------------------------------------------------------
def read_clients():
    data = load_json(CLIENTS_FILE, {"clients": []})
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
    items = []
    for c in data["clients"]:
        items.append({"code": c["code"], "name": c["name"], "terminals": c["terminals"]})
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

# ---------------------------------------------------------------------------
# Playlists / Config do terminal
# ---------------------------------------------------------------------------
DEFAULT_SCHEDULE_HOURS = [6, 12, 18]

def playlist_path(client_code: str, term: int) -> Path:
    return PLAY_DIR / f"{client_code}-{str(term).zfill(2)}.json"

def read_config_for(code: str):
    client, term = parse_code(code)
    if not client or not term:
        return None
    p = playlist_path(client, term)
    if p.exists():
        cfg = load_json(p, {})
        cfg.setdefault("refresh_minutes", 10)
        cfg.setdefault("update_schedule_hours", DEFAULT_SCHEDULE_HOURS)
        cfg.setdefault("code", f"{client}-{str(term).zfill(2)}")
        cfg.setdefault("updated_at", utcnow_iso())
        cfg.setdefault("ok", True)
        return cfg
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

    norm = []
    for it in items:
        t = (it.get("type") or "").lower()
        url = (it.get("url") or "").strip()
        dur = int(it.get("duration") or 0)
        if t == "image" and dur <= 0:
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

# ---------------------------------------------------------------------------
# Status / Summary (para os blocos do painel) e Heartbeat do player
# ---------------------------------------------------------------------------
def read_status():
    return load_json(STATUS_FILE, {})

def write_status(s):
    save_json(STATUS_FILE, s)

@app.route("/api/v1/heartbeat", methods=["POST"])
def api_heartbeat():
    """
    Enviado pelo player periodicamente:
    { "code":"001-01", "playing":"url", "volume":70 }
    """
    j = request.get_json(silent=True) or {}
    code = (j.get("code") or "").strip()
    if not code:
        return jsonify({"ok": False, "error": "missing code"}), 400

    s = read_status()
    s[code] = {
        "last_seen": utcnow_iso(),
        "online": True,
        "playing": j.get("playing"),
        "extra": {k:v for k,v in j.items() if k not in {"code","playing"}}
    }
    write_status(s)
    return jsonify({"ok": True})

@app.route("/api/v1/summary")
def api_summary():
    """
    Retorna blocos: clientes -> terminais com contagem de itens, atualizado, status etc.
    """
    clients = read_clients()["clients"]
    status  = read_status()
    blocks = []
    for c in clients:
        for term in c["terminals"]:
            code = f"{c['code']}-{str(term).zfill(2)}"
            cfg = load_json(playlist_path(c["code"], term), {})
            items = cfg.get("playlist", [])
            st = status.get(code, {})
            # offline se não visto há > 3 minutos
            online = False
            last_seen = st.get("last_seen")
            if last_seen:
                try:
                    dt = datetime.datetime.fromisoformat(last_seen.replace("Z","+00:00"))
                    online = (datetime.datetime.utcnow() - dt.replace(tzinfo=None)).total_seconds() < 180
                except Exception:
                    online = False
            blocks.append({
                "client_name": c["name"],
                "client_code": c["code"],
                "term": term,
                "display_code": code,
                "items": len(items),
                "updated_at": cfg.get("updated_at"),
                "config_version": cfg.get("config_version", 0),
                "online": online,
                "last_seen": last_seen,
                "playing": st.get("playing")
            })
    # agrupa por cliente no front; aqui só mandamos a lista
    return jsonify({"ok": True, "items": blocks})

@app.route("/api/v1/terminal")
def api_terminal_detail():
    """
    Retorna detalhe do terminal + playlist + uploads (para carregar a tela de edição direto).
    ?code=001-01
    """
    code = request.args.get("code","").strip()
    cfg = read_config_for(code)
    if not cfg:
        return jsonify({"ok": False, "error": "invalid code"}), 400
    # uploads
    ups = []
    for p in sorted(UPLOAD_DIR.glob("*")):
        if not p.is_file(): 
            continue
        ups.append({"filename": p.name, "url": f"/static/uploads/{p.name}", "type": guess_type(p)})
    return jsonify({"ok": True, "config": cfg, "uploads": ups})

# ---------------------------------------------------------------------------
# Comandos (stub)
# ---------------------------------------------------------------------------
@app.route("/api/v1/terminal/command", methods=["POST"])
def api_command():
    # enfileirar comandos específicos depois; por ora, só OK
    return jsonify({"ok": True})

# ---------------------------------------------------------------------------
# Saúde
# ---------------------------------------------------------------------------
@app.route("/api/v1/ping")
def api_ping():
    return jsonify({"ok": True, "ts": utcnow_iso()})

@app.route("/favicon.ico")
def favicon():
    return "", 204

# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
