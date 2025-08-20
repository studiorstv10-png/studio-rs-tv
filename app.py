import os
import json
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, request, jsonify, render_template, send_from_directory

# --- Pastas base ---
BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
PLAYLISTS_DIR = DATA_DIR / "playlists"
UPLOADS_DIR = BASE / "static" / "uploads"

for p in (DATA_DIR, PLAYLISTS_DIR, UPLOADS_DIR):
    p.mkdir(parents=True, exist_ok=True)

BRANDING_FILE = DATA_DIR / "branding.json"
TERMINALS_FILE = DATA_DIR / "terminals.json"

# --- App ---
app = Flask(__name__, static_folder="static", template_folder="templates", static_url_path="/static")

# --- Helpers de JSON em disco ---
def _read_json(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default

def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

# --- Branding: ENV tem prioridade; se não, arquivo ---
def get_branding():
    name = os.getenv("BRAND_NAME")
    color = os.getenv("BRAND_PRIMARY")
    logo = os.getenv("BRAND_LOGO")

    file_data = _read_json(BRANDING_FILE, {
        "name": "Studio RS TV",
        "primary_color": "#0d1b2a",
        "logo_url": ""
    })

    return {
        "name": name or file_data.get("name", "Studio RS TV"),
        "primary_color": color or file_data.get("primary_color", "#0d1b2a"),
        "logo_url": logo or file_data.get("logo_url", "")
    }

def set_branding(payload):
    # Salva no arquivo; ENV sempre tem prioridade em runtime
    current = get_branding()
    current.update({
        "name": payload.get("name", current["name"]),
        "primary_color": payload.get("primary_color", current["primary_color"]),
        "logo_url": payload.get("logo_url", current["logo_url"]),
    })
    _write_json(BRANDING_FILE, current)
    return current

# --- Terminais ---
def load_terminals():
    return _read_json(TERMINALS_FILE, [])

def save_terminals(list_):
    _write_json(TERMINALS_FILE, list_)

def upsert_terminal(code, name, group):
    code = code.strip()
    terminals = load_terminals()
    existing = next((t for t in terminals if t["code"] == code), None)
    now = _now_iso()
    if existing:
        existing["name"] = name
        existing["group"] = group
        existing.setdefault("created_at", now)
    else:
        terminals.append({
            "code": code,
            "name": name,
            "group": group,
            "created_at": now
        })
    save_terminals(terminals)
    return terminals

def touch_terminal_seen(code):
    terminals = load_terminals()
    for t in terminals:
        if t["code"] == code:
            t["last_seen"] = _now_iso()
            break
    save_terminals(terminals)

# --- Playlist por terminal ---
def playlist_path(code):
    return PLAYLISTS_DIR / f"{code}.json"

def get_playlist(code):
    return _read_json(playlist_path(code), {"code": code, "items": []})

def set_playlist(code, payload):
    payload["code"] = code
    _write_json(playlist_path(code), payload)
    return payload

# --- Uploads ---
ALLOWED = {".mp4", ".mov", ".mkv", ".jpg", ".jpeg", ".png", ".gif", ".webm"}

def list_uploads():
    items = []
    for p in sorted(UPLOADS_DIR.iterdir()):
        if p.is_file():
            ext = p.suffix.lower()
            if ext in ALLOWED:
                kind = "video" if ext in {".mp4", ".mov", ".mkv", ".webm"} else "image"
                items.append({
                    "name": p.name,
                    "url": f"/static/uploads/{p.name}",
                    "type": kind,
                    "bytes": p.stat().st_size
                })
    return items

# --- Rotas páginas ---
@app.get("/")
def index():
    b = get_branding()
    return render_template("index.html", branding=b)

# --- API Branding ---
@app.get("/api/v1/branding")
def api_get_branding():
    return jsonify(get_branding())

@app.post("/api/v1/branding")
def api_set_branding():
    payload = request.get_json(force=True) or {}
    return jsonify(set_branding(payload))

# --- API Terminais ---
@app.get("/api/v1/terminals")
def api_terminals_list():
    return jsonify(load_terminals())

@app.post("/api/v1/terminals")
def api_terminals_create():
    payload = request.get_json(force=True) or {}
    code = (payload.get("code") or "").strip()
    name = (payload.get("name") or "").strip()
    group = (payload.get("group") or "").strip()

    if not code or not name:
        return jsonify({"ok": False, "error": "code e name são obrigatórios"}), 400

    # não duplica
    terms = load_terminals()
    if any(t["code"] == code for t in terms):
        return jsonify({"ok": False, "error": "código já existe"}), 409

    upsert_terminal(code, name, group)
    return jsonify({"ok": True})

# --- API Uploads ---
@app.get("/api/v1/uploads")
def api_list_uploads():
    return jsonify(list_uploads())

@app.post("/api/v1/upload")
def api_upload():
    files = request.files.getlist("files")
    saved = []
    for f in files:
        ext = Path(f.filename).suffix.lower()
        if ext not in ALLOWED:
            continue
        safe_name = f"{datetime.now().strftime('%Y-%m-%d-%H%M%S')}-{f.filename.replace(' ', '_')}"
        dest = UPLOADS_DIR / safe_name
        f.save(dest)
        saved.append(f"/static/uploads/{safe_name}")
    return jsonify({"ok": True, "saved": saved})

# --- API Playlists ---
@app.get("/api/v1/playlist/<code>")
def api_get_playlist(code):
    return jsonify(get_playlist(code))

@app.post("/api/v1/playlist/<code>")
def api_post_playlist(code):
    payload = request.get_json(force=True) or {}
    # payload esperado: {"items":[{"type":"video|image|rss","url":"...","duration":10?}, ...]}
    items = payload.get("items", [])
    norm = []
    for it in items:
        t = (it.get("type") or "").lower()
        if t not in {"video", "image", "rss"}:
            continue
        entry = {"type": t, "url": it.get("url", "")}
        if t in {"image", "rss"}:
            entry["duration"] = int(it.get("duration") or 10)
        norm.append(entry)
    data = {"code": code, "items": norm, "updated_at": _now_iso()}
    return jsonify(set_playlist(code, data))

# --- API Config para o BOX ---
@app.get("/api/v1/config")
def api_config():
    code = (request.args.get("code") or "").strip()
    if not code:
        return jsonify({"status": "error", "error": "missing code"}), 400

    touch_terminal_seen(code)
    pl = get_playlist(code)
    return jsonify({
        "branding": get_branding(),
        "config_version": 1,
        "poll_seconds": 60,
        "terminal": {"code": code},
        "playlist": pl.get("items", []),
        "updated_at": _now_iso(),
        "status": "ok"
    })

# --- Favicon opcional ---
@app.get("/favicon.ico")
def favicon():
    return ("", 204)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
