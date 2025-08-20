import os
import json
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data"
PLAYLISTS_DIR = DATA_DIR / "playlists"
STATIC_DIR = BASE / "static"
UPLOADS_DIR = STATIC_DIR / "uploads"

for p in (DATA_DIR, PLAYLISTS_DIR, STATIC_DIR, UPLOADS_DIR):
    p.mkdir(parents=True, exist_ok=True)

BRANDING_FILE = DATA_DIR / "branding.json"
TERMINALS_FILE = DATA_DIR / "terminals.json"

app = Flask(
    __name__, static_folder="static", template_folder="templates", static_url_path="/static"
)
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024 * 1024  # 256 MB

ALLOWED = {".mp4", ".mov", ".mkv", ".webm", ".jpg", ".jpeg", ".png", ".gif"}

# ---------------- utils ----------------
def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def _read_json(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default

def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ---------------- branding ----------------
def get_branding():
    file_data = _read_json(BRANDING_FILE, {
        "name": "Studio RS TV",
        "primary_color": "#0d1b2a",
        "logo_url": ""
    })
    name = os.getenv("BRAND_NAME") or file_data.get("name", "Studio RS TV")
    color = os.getenv("BRAND_PRIMARY") or file_data.get("primary_color", "#0d1b2a")
    logo = os.getenv("BRAND_LOGO") or file_data.get("logo_url") or ""

    # fallback para static/logo.png se existir
    if not logo and (STATIC_DIR / "logo.png").exists():
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

# ---------------- terminais ----------------
def load_terminals():
    return _read_json(TERMINALS_FILE, [])

def save_terminals(data):
    _write_json(TERMINALS_FILE, data)

def upsert_terminal(code, name, group):
    code = code.strip()
    terminals = load_terminals()
    found = next((t for t in terminals if t["code"] == code), None)
    now = _now_iso()
    if found:
        found["name"] = name
        found["group"] = group
        found.setdefault("created_at", now)
    else:
        terminals.append({"code": code, "name": name, "group": group, "created_at": now})
    save_terminals(terminals)
    return terminals

def touch_terminal_seen(code):
    terminals = load_terminals()
    for t in terminals:
        if t["code"] == code:
            t["last_seen"] = _now_iso()
            break
    save_terminals(terminals)

# ---------------- playlists ----------------
def pl_path(code): return PLAYLISTS_DIR / f"{code}.json"

def get_playlist(code):
    return _read_json(pl_path(code), {"code": code, "items": []})

def set_playlist(code, payload):
    payload["code"] = code
    _write_json(pl_path(code), payload)
    return payload

# ---------------- páginas ----------------
@app.get("/")
def index():
    return render_template(
        "index.html",
        branding=get_branding(),
        support_link=os.getenv("SUPPORT_WA", "https://wa.me/5512999999999")
    )

# ---------------- API branding ----------------
@app.get("/api/v1/branding")
def api_get_branding():
    return jsonify(get_branding())

@app.post("/api/v1/branding")
def api_post_branding():
    return jsonify(set_branding(request.get_json(force=True) or {}))

# ---------------- API terminais ----------------
@app.get("/api/v1/terminals")
def api_terminals():
    return jsonify(load_terminals())

@app.post("/api/v1/terminals")
def api_create_terminal():
    p = request.get_json(force=True) or {}
    code = (p.get("code") or "").strip()
    name = (p.get("name") or "").strip()
    group = (p.get("group") or "").strip()
    if not code or not name:
        return jsonify({"ok": False, "error": "code e name são obrigatórios"}), 400
    if any(t["code"] == code for t in load_terminals()):
        return jsonify({"ok": False, "error": "código já existe"}), 409
    upsert_terminal(code, name, group)
    return jsonify({"ok": True})

# ---------------- API uploads ----------------
@app.get("/api/v1/uploads")
def api_list_uploads():
    items = []
    for p in sorted(UPLOADS_DIR.iterdir()):
        if not p.is_file(): continue
        ext = p.suffix.lower()
        if ext not in ALLOWED: continue
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
        # aceita 'files' ou 'files[]'
        files = request.files.getlist("files[]") or request.files.getlist("files")
        if not files:
            return jsonify({"ok": False, "error": "nenhum arquivo enviado"}), 400

        saved = []
        for f in files:
            ext = Path(f.filename).suffix.lower()
            if ext not in ALLOWED:
                return jsonify({"ok": False, "error": f"extensão não suportada: {ext}"}), 400
            safe = secure_filename(f.filename.replace(" ", "_"))
            unique = f"{datetime.now().strftime('%Y-%m-%d-%H%M%S')}-{safe}"
            dest = UPLOADS_DIR / unique
            f.save(dest)
            saved.append(f"/static/uploads/{unique}")

        return jsonify({"ok": True, "saved": saved})
    except Exception as e:
        # ajuda no diagnóstico se algo der ruim no Render
        return jsonify({"ok": False, "error": f"upload falhou: {e}"}), 500

# ---------------- API playlist ----------------
@app.get("/api/v1/playlist/<code>")
def api_get_pl(code):
    return jsonify(get_playlist(code))

@app.post("/api/v1/playlist/<code>")
def api_post_pl(code):
    p = request.get_json(force=True) or {}
    items = []
    for it in p.get("items", []):
        t = (it.get("type") or "").lower()
        if t not in {"video", "image", "rss"}: continue
        rec = {"type": t, "url": it.get("url", "")}
        if t in {"image", "rss"}: rec["duration"] = int(it.get("duration") or 10)
        items.append(rec)
    return jsonify(set_playlist(code, {"code": code, "items": items, "updated_at": _now_iso()}))

# -------- BOX consome isso --------
@app.get("/api/v1/config")
def api_config():
    code = (request.args.get("code") or "").strip()
    if not code:
        return jsonify({"status": "error", "error": "missing code"}), 400
    touch_terminal_seen(code)
    return jsonify({
        "branding": get_branding(),
        "config_version": 1,
        "poll_seconds": 60,
        "terminal": {"code": code},
        "playlist": get_playlist(code).get("items", []),
        "updated_at": _now_iso(),
        "status": "ok"
    })

@app.get("/favicon.ico")
def favicon(): return ("", 204)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
