
import os
from flask import Flask, request, jsonify, send_from_directory, render_template_string, abort
from werkzeug.utils import secure_filename
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PLAYLISTS_DIR = os.path.join(DATA_DIR, "playlists")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
STATIC_DIR = os.path.join(BASE_DIR, "static")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PLAYLISTS_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

ADMIN_KEY = os.environ.get("ADMIN_KEY", "admin123")

def utcnow_iso():
    return datetime.now(timezone.utc).isoformat()

def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ----- App -----
app = Flask(__name__, static_folder="static", static_url_path="/static")

# Admin UI (served as a simple template wrapper to the admin SPA file)
@app.route("/")
def index():
    # Serve the admin single-file HTML
    try:
        with open(os.path.join(BASE_DIR, "admin", "admin.html"), "r", encoding="utf-8") as f:
            html = f.read()
        return render_template_string(html)
    except Exception as e:
        return f"Admin UI missing: {e}", 500

@app.route("/api/v1/ping")
def ping():
    return jsonify({"ok": True, "ts": utcnow_iso()})

# ----- Terminals storage -----
TERMINALS_PATH = os.path.join(DATA_DIR, "terminals.json")

def list_terminals():
    return read_json(TERMINALS_PATH, default=[])

def save_terminals(items):
    write_json(TERMINALS_PATH, items)

# ----- Branding storage -----
BRAND_PATH = os.path.join(DATA_DIR, "branding.json")

def get_branding():
    return read_json(BRAND_PATH, default={
        "name": "Studio RS TV",
        "primary": "#0a2342",
        "accent": "#1f6feb",
        "logo_url": ""
    })

def save_branding(obj):
    write_json(BRAND_PATH, obj)

# ----- Admin endpoints -----
def check_admin():
    key = request.headers.get("x-admin-key") or request.args.get("admin_key")
    if not key or key != ADMIN_KEY:
        abort(401, description="Unauthorized")

@app.route("/api/v1/admin/terminals", methods=["GET", "POST", "DELETE"])
def admin_terminals():
    check_admin()
    if request.method == "GET":
        return jsonify(list_terminals())

    if request.method == "POST":
        payload = request.get_json(force=True, silent=True) or {}
        code = payload.get("code", "").strip()
        if not code:
            return jsonify({"ok": False, "error": "code is required"}), 400
        title = payload.get("title", code)
        group = payload.get("group", "")
        items = list_terminals()
        if any(t.get("code") == code for t in items):
            return jsonify({"ok": False, "error": "code already exists"}), 400
        items.append({
            "code": code,
            "title": title,
            "group": group,
            "created_at": utcnow_iso(),
            "active": True
        })
        save_terminals(items)
        return jsonify({"ok": True})

    if request.method == "DELETE":
        code = request.args.get("code", "").strip()
        items = list_terminals()
        items = [t for t in items if t.get("code") != code]
        save_terminals(items)
        # also remove playlist file if exists
        pl_path = os.path.join(PLAYLISTS_DIR, f"{code}.json")
        if os.path.exists(pl_path):
            os.remove(pl_path)
        return jsonify({"ok": True})

@app.route("/api/v1/admin/branding", methods=["GET", "POST"])
def admin_branding():
    check_admin()
    if request.method == "GET":
        return jsonify(get_branding())
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name") or "Studio RS TV"
    primary = data.get("primary") or "#0a2342"
    accent = data.get("accent") or "#1f6feb"
    logo_url = data.get("logo_url") or ""
    save_branding({"name": name, "primary": primary, "accent": accent, "logo_url": logo_url})
    return jsonify({"ok": True})

# ----- Uploads -----
ALLOWED_EXTS = {"mp4", "mov", "mkv", "jpg", "jpeg", "png", "gif", "webp"}

def allowed_file(fname):
    return "." in fname and fname.rsplit(".", 1)[1].lower() in ALLOWED_EXTS

@app.route("/api/v1/admin/upload", methods=["POST"])
def upload_file():
    check_admin()
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "no file part"}), 400
    f = request.files["file"]
    if f.filename == "":
        return jsonify({"ok": False, "error": "empty filename"}), 400
    if not allowed_file(f.filename):
        return jsonify({"ok": False, "error": "unsupported file type"}), 400
    fname = secure_filename(f.filename)
    dest = os.path.join(UPLOADS_DIR, fname)
    f.save(dest)
    url = f"/uploads/{fname}"
    return jsonify({"ok": True, "filename": fname, "url": url})

@app.route("/api/v1/admin/list_uploads")
def list_uploads():
    check_admin()
    files = []
    for fname in sorted(os.listdir(UPLOADS_DIR)):
        path = os.path.join(UPLOADS_DIR, fname)
        if os.path.isfile(path) and allowed_file(fname):
            files.append({
                "name": fname,
                "size": os.path.getsize(path),
                "url": f"/uploads/{fname}"
            })
    return jsonify(files)

@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(UPLOADS_DIR, filename, as_attachment=False)

# ----- Playlists -----
def playlist_path(code):
    return os.path.join(PLAYLISTS_DIR, f"{code}.json")

@app.route("/api/v1/admin/playlist/<code>", methods=["GET", "POST"])
def admin_playlist(code):
    check_admin()
    code = secure_filename(code)
    path = playlist_path(code)
    if request.method == "GET":
        return send_from_directory(PLAYLISTS_DIR, f"{code}.json") if os.path.exists(path) else jsonify({"items":[],"updated_at": utcnow_iso()})
    # POST save
    data = request.get_json(force=True, silent=True) or {}
    data["updated_at"] = utcnow_iso()
    write_json(path, data)
    return jsonify({"ok": True})

# ----- Public: config for player -----
@app.route("/api/v1/config")
def config():
    code = request.args.get("code", "").strip()
    if not code:
        return jsonify({"ok": False, "error": "code required"}), 400
    # find terminal
    terminals = list_terminals()
    term = next((t for t in terminals if t.get("code") == code), None)
    if not term or not term.get("active", True):
        return jsonify({"ok": False, "error": "terminal not found or inactive"}), 404

    path = playlist_path(code)
    playlist = read_json(path, default={"items": [], "updated_at": utcnow_iso()})
    brand = get_branding()
    base_url = request.url_root.rstrip("/")

    # Build a compact payload for the player
    payload = {
        "ok": True,
        "terminal": {"code": code, "title": term.get("title", code)},
        "branding": brand,
        "playlist": playlist.get("items", []),
        "updated_at": playlist.get("updated_at", utcnow_iso()),
        "assets_base": base_url  # so player can resolve /uploads/xyz
    }
    return jsonify(payload)

# Pretty short link: /c/<code>
@app.route("/c/<code>")
def short_config(code):
    return config()

# favicon (avoid 404 noise)
@app.route("/favicon.ico")
def favicon():
    return ("", 204)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
