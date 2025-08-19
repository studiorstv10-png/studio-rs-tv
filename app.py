import os, json, uuid, pathlib
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify, send_from_directory, make_response

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = os.path.join(os.getcwd(), "uploads")
app.config["DATA_FOLDER"]   = os.path.join(os.getcwd(), "data")
app.config["SECRET_KEY"]    = os.environ.get("PANEL_SECRET", "studio-rs-tv-secret")  # para cookie simples

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["DATA_FOLDER"],   exist_ok=True)

DATA_FILE = os.path.join(app.config["DATA_FOLDER"], "data.json")
DEFAULT_BRAND = {
    "name": "Studio RS TV",
    "primary_color": "#0d1b2a",
    "logo": None
}

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def load_db():
    if not os.path.exists(DATA_FILE):
        db = {
            "brand": DEFAULT_BRAND,
            "terminals": {},  # "BOX-0001": {"name":"AÇOUGUE", "group":"MATRIZ", "playlist":[...], "updated_at": "..."}
            "admin_password": os.environ.get("ADMIN_PASSWORD", "admin123"),
            "poll_seconds": 60,
            "trial_days": 15
        }
        save_db(db)
        return db
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(db):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)

def require_login(req):
    # Cookie ultra simples (MVP). Se quiser endurecer, trocamos para sessão assinada.
    return req.cookies.get("srs_auth") == "ok"

@app.get("/")
def panel():
    # sempre serve a página do painel (login embutido)
    return send_from_directory(".", "panel.html")

@app.post("/api/v1/login")
def api_login():
    data = request.get_json(silent=True) or {}
    pwd  = (data.get("password") or "").strip()
    db   = load_db()
    if pwd != db.get("admin_password"):
        return jsonify({"ok": False, "error": "Senha inválida"}), 401
    resp = make_response(jsonify({"ok": True, "brand": db.get("brand", DEFAULT_BRAND)}))
    # cookie simples (expira em 12h)
    expires = datetime.now(timezone.utc) + timedelta(hours=12)
    resp.set_cookie("srs_auth", "ok", expires=expires, httponly=True, samesite="Lax")
    return resp

@app.get("/api/v1/admin/brand")
def get_brand():
    if not require_login(request): return jsonify({"ok": False, "error": "auth"}), 401
    db = load_db()
    return jsonify({"ok": True, "brand": db.get("brand", DEFAULT_BRAND)})

@app.post("/api/v1/admin/brand")
def set_brand():
    if not require_login(request): return jsonify({"ok": False, "error": "auth"}), 401
    db   = load_db()
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip() or DEFAULT_BRAND["name"]
    color= data.get("primary_color", DEFAULT_BRAND["primary_color"])
    logo = data.get("logo")
    db["brand"] = {"name": name, "primary_color": color, "logo": logo}
    save_db(db)
    return jsonify({"ok": True, "brand": db["brand"]})

@app.get("/api/v1/admin/terminals")
def list_terminals():
    if not require_login(request): return jsonify({"ok": False, "error": "auth"}), 401
    db = load_db()
    # devolve como lista
    out = []
    for code, t in db["terminals"].items():
        out.append({
            "code": code,
            "name": t.get("name"),
            "group": t.get("group"),
            "updated_at": t.get("updated_at"),
            "items": len(t.get("playlist", []))
        })
    return jsonify({"ok": True, "terminals": out})

@app.post("/api/v1/admin/terminals")
def create_terminal():
    if not require_login(request): return jsonify({"ok": False, "error": "auth"}), 401
    db   = load_db()
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    name = (data.get("name") or "").strip()
    group= (data.get("group")or "").strip() or None
    if not code or not name:
        return jsonify({"ok": False, "error": "code/name obrigatórios"}), 400
    if code in db["terminals"]:
        return jsonify({"ok": False, "error": "Código já existe"}), 409
    db["terminals"][code] = {
        "name": name, "group": group, "playlist": [],
        "updated_at": _now_iso(),
        "trial_until": (datetime.now(timezone.utc) + timedelta(days=db.get("trial_days", 15))).date().isoformat()
    }
    save_db(db)
    return jsonify({"ok": True})

@app.get("/api/v1/uploads")
def list_uploads():
    if not require_login(request): return jsonify({"ok": False, "error": "auth"}), 401
    files = []
    for p in sorted(pathlib.Path(app.config["UPLOAD_FOLDER"]).glob("*")):
        if p.is_file():
            files.append(f"/uploads/{p.name}")
    return jsonify({"ok": True, "files": files})

@app.post("/api/v1/upload")
def upload_file():
    if not require_login(request): return jsonify({"ok": False, "error": "auth"}), 401
    f = request.files.get("file")
    if not f: return jsonify({"ok": False, "error": "sem arquivo"}), 400
    ext = pathlib.Path(f.filename).suffix.lower()
    safe = uuid.uuid4().hex + ext
    path = os.path.join(app.config["UPLOAD_FOLDER"], safe)
    f.save(path)
    return jsonify({"ok": True, "url": f"/uploads/{safe}"})

@app.get("/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

@app.post("/api/v1/admin/playlist")
def save_playlist():
    if not require_login(request): return jsonify({"ok": False, "error": "auth"}), 401
    data = request.get_json(silent=True) or {}
    code = data.get("code")
    items= data.get("items", [])
    db   = load_db()
    if code not in db["terminals"]:
        return jsonify({"ok": False, "error": "terminal não existe"}), 404
    # normaliza itens
    norm = []
    for it in items:
        typ = it.get("type")
        url = it.get("url")
        dur = int(it.get("duration", 0) or 0)
        if typ not in ("video", "image", "rss"): continue
        if not url: continue
        out = {"type": typ, "url": url}
        if typ != "video": out["duration"] = max(dur, 1)
        norm.append(out)
    db["terminals"][code]["playlist"] = norm
    db["terminals"][code]["updated_at"] = _now_iso()
    save_db(db)
    return jsonify({"ok": True})

@app.get("/api/v1/admin/playlist")
def load_playlist():
    if not require_login(request): return jsonify({"ok": False, "error": "auth"}), 401
    code = request.args.get("code")
    db   = load_db()
    pl   = db["terminals"].get(code, {}).get("playlist", [])
    return jsonify({"ok": True, "items": pl})

@app.get("/api/v1/config")
def player_config():
    # Sem login — chamado pelo APK. Necessário: ?code=BOX-xxxx
    code = request.args.get("code")
    db   = load_db()
    t    = db["terminals"].get(code)
    if not t:
        return jsonify({"ok": False, "error": "terminal não encontrado"}), 404
    brand = db.get("brand", DEFAULT_BRAND)
    cfg = {
        "logo": brand.get("logo"),
        "name": brand.get("name"),
        "primary_color": brand.get("primary_color"),
        "config_version": 1,
        "layout": "16:9",
        "playlist": t.get("playlist", []),
        "poll_seconds": db.get("poll_seconds", 60),
        "status": "ok",
        "terminal": {"code": code, "name": t.get("name")},
        "trial_until": t.get("trial_until"),
        "updated_at": t.get("updated_at", _now_iso())
    }
    return jsonify(cfg)

@app.get("/api/v1/ping")
def ping():
    return jsonify({"ok": True, "ts": _now_iso()})

# --------- Arquivos estáticos do painel
@app.get("/panel.html")
def panel_html():
    # mesma rota de "/" – facilita hot-reload em alguns hosts
    return send_from_directory(".", "panel.html")

@app.get("/favicon.ico")
def fav():
    return ("", 204)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=False)
