import os
import json
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, request, jsonify, render_template

# --- Pastas base ---
BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
PLAYLISTS_DIR = DATA_DIR / "playlists"
UPLOADS_DIR = BASE / "static" / "uploads"

for p in (DATA_DIR, PLAYLISTS_DIR, UPLOADS_DIR):
    p.mkdir(parents=True, exist_ok=True)

BRANDING_FILE = DATA_DIR / "branding.json"
TERMINALS_FILE = DATA_DIR / "terminals.json"

app = Flask(__name__, static_folder="static", template_folder="templates", static_url_path="/static")
# até 256 MB por upload (ajuste se quiser)
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024 * 1024

ALLOWED = {".mp4", ".mov", ".mkv", ".webm", ".jpg", ".jpeg", ".png", ".gif"}

# ---------------- utils ----------------
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

# -------------- branding ----------------
def get_branding():
    """ENV > arquivo > fallback em static/logo.png"""
    file_data = _read_json(BRANDING_FILE, {
        "name": "Studio RS TV",
        "primary_color": "#0d1b2a",
        "logo_url": ""
    })
    name = os.getenv("BRAND_NAME") or file_data.get("name", "Studio RS TV")
    color = os.getenv("BRAND_PRIMARY") or file_data.get("primary_color", "#0d1b2a")
    logo = os.getenv("BRAND_LOGO") or file_data.get("logo_url") or ""
    # se não veio nada, tenta static/logo.png
    if not logo and (BASE / "static" / "logo.png").exists():
        logo = "/static/logo.png"
    return {"name": name, "primary_color": color, "logo_url": logo}

def set_branding(payload):
    current = get_branding()
    current.update({
        "name": payload.get("name", current["name"]),
        "primary_color": payload.get("primary_color", current["primary_color"]),
        "logo_url": payload.get("logo_url", current["logo_url"]),
    })
    _write_json(BRANDING_FILE, current)
    return current

# -------------- terminais --------------
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

# -------------- playlists --------------
def playlist_path(code):
    return PLAYLISTS_DIR / f"{code}.json"

def get_playlist(code):
    return _read_json(playlist_path(code), {"code": code, "items": []})

def set_playlist(code, payload):
    payload["code"] = code
    _write_json(playlist_path(code), payload)
    return payload

# ----------------- rotas páginas ----------------
@app.get("/")
def index():
    branding = get_branding()
    support_link = os.getenv("SUPPORT_WA", "https://wa.me/5512999999999")  # ajuste seu número
    return render_template("index.html", branding=branding, support_link=support_link)

# ----------------- API branding ----------------
@app.get("/api/v1/branding")
def api_get_branding():
    return jsonify(get_branding())

@app.post("/api/v1/branding")
def api_set_branding():
    payload = request.get_json(force=True) or {}
    return jsonify(set_branding(payload))

# ----------------- API terminais ----------------
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
    terms = load_terminals()
    if any(t["code"] == code for t in terms):
        return jsonify({"ok": False, "error": "código já existe"}), 409
    upsert_terminal(code, name, group)
    return jsonify({"ok": True})

# ----------------- API uploads ----------------
@app.get("/api/v1/uploads")
def api_list_uploads():
    items = []
    for p in sorted(UPLOADS_DIR.iterdir()):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext not in ALLOWED:
            continue
        kind = "video" if ext in {".mp4", ".mov", ".mkv", ".webm"} else "image"
        items.append({
            "name": p.name,
            "url": f"/static/uploads/{p.name}",
            "type": kind,
            "bytes": p.stat().st_size
        })
    return jsonify(items)

@app.post("/api/v1/upload")
def api_upload():
    try:
        files = request.files.getlist("files")
        if not files:
            return jsonify({"ok": False, "error": "nenhum arquivo"}), 400
        saved = []
        for f in files:
            ext = Path(f.filename).suffix.lower()
            if ext not in ALLOWED:
                return jsonify({"ok": False, "error": f"extensão não permitida: {ext}"}), 400
            safe_name = f"{datetime.now().strftime('%Y-%m-%d-%H%M%S')}-{f.filename.replace(' ', '_')}"
            dest = UPLOADS_DIR / safe_name
            f.save(dest)
            saved.append(f"/static/uploads/{safe_name}")
        return jsonify({"ok": True, "saved": saved})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ----------------- API playlists ----------------
@app.get("/api/v1/playlist/<code>")
def api_get_pl(code):
    return jsonify(get_playlist(code))

@app.post("/api/v1/playlist/<code>")
def api_post_pl(code):
    payload = request.get_json(force=True) or {}
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

# -------- BOX consome isso --------
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

@app.get("/favicon.ico")
def favicon():
    return ("", 204)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
