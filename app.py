import os, json, sqlite3, mimetypes, time
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify, render_template, send_from_directory, g

# ---------- Config ----------
APP_TITLE = os.getenv("APP_TITLE", "Studio RS TV")
BRAND_COLOR = os.getenv("BRAND_COLOR", "#0d1b2a")
LOGO_URL = os.getenv("LOGO_URL", "/static/logo.png")  # coloque seu PNG/WEBP branco aqui
SUPPORT_WA = os.getenv("SUPPORT_WA", "https://wa.me/5512996273989")
REFRESH_MINUTES_DEFAULT = int(os.getenv("REFRESH_MINUTES", "10"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
DB_PATH = os.path.join(DATA_DIR, "panel.sqlite3")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__, static_url_path="/static", template_folder="templates")

# ---------- DB helpers ----------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            name TEXT,
            license_days INTEGER DEFAULT 30,
            theme TEXT DEFAULT 'dark'
        );

        CREATE TABLE IF NOT EXISTS terminals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_code TEXT,
            code TEXT UNIQUE,
            name TEXT,
            tgroup TEXT,
            playlist_json TEXT,        -- [{type, url, duration, kind}]
            campaign TEXT,
            updated_at TEXT,
            last_seen TEXT
        );

        CREATE TABLE IF NOT EXISTS media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT,
            display TEXT,
            mime TEXT,
            size INTEGER,
            uploaded_at TEXT
        );
        """
    )
    db.commit()

with app.app_context():
    init_db()

# ---------- Utils ----------
UTC = timezone.utc
def now_iso():
    return datetime.now(UTC).isoformat()

def db_all(q, args=()):
    return [dict(r) for r in get_db().execute(q, args).fetchall()]

def db_one(q, args=()):
    r = get_db().execute(q, args).fetchone()
    return dict(r) if r else None

def db_exec(q, args=()):
    db = get_db()
    db.execute(q, args)
    db.commit()

def ensure_client(code, name, license_days=30):
    if not db_one("SELECT id FROM clients WHERE code=?", (code,)):
        db_exec("INSERT INTO clients(code,name,license_days) VALUES(?,?,?)",
                (code, name, license_days))

# ---------- Routes: UI ----------
@app.route("/")
def index():
    branding = {
        "title": APP_TITLE,
        "color": BRAND_COLOR,
        "logo_url": LOGO_URL,
        "support": SUPPORT_WA,
    }
    # contadores rápidos
    c_clients = db_one("SELECT COUNT(*) as n FROM clients")["n"]
    c_terms   = db_one("SELECT COUNT(*) as n FROM terminals")["n"]
    c_media   = db_one("SELECT COUNT(*) as n FROM media")["n"]
    return render_template("index.html",
                           branding=branding,
                           counters={"clients":c_clients, "terminals":c_terms, "media":c_media})

# ---------- Routes: Admin API ----------
@app.get("/api/v1/branding")
def api_branding():
    return jsonify({
        "title": APP_TITLE,
        "color": BRAND_COLOR,
        "logo_url": LOGO_URL,
        "support": SUPPORT_WA,
    })

@app.get("/api/v1/clients")
def api_clients():
    clients = db_all("SELECT * FROM clients ORDER BY code")
    for c in clients:
        c["terminals"] = db_all(
            "SELECT code,name,tgroup,updated_at,last_seen,campaign FROM terminals WHERE client_code=? ORDER BY code",
            (c["code"],)
        )
    return jsonify(clients)

@app.post("/api/v1/client/create")
def api_client_create():
    data = request.json or {}
    name   = (data.get("name") or "").strip()
    code   = (data.get("code") or "").strip()
    qty    = int(data.get("qty") or 1)
    lic    = int(data.get("license_days") or 30)
    if not name or not code or qty < 1:
        return jsonify({"ok": False, "error": "dados inválidos"}), 400
    ensure_client(code, name, lic)
    # cria terminais sequenciais
    for i in range(1, qty+1):
        tcode = f"{code}-{i:02d}"
        if not db_one("SELECT id FROM terminals WHERE code=?", (tcode,)):
            db_exec("INSERT INTO terminals(client_code,code,name,tgroup,playlist_json,updated_at) VALUES(?,?,?,?,?,?)",
                    (code, tcode, f"{name} — {tcode}", None, json.dumps([]), now_iso()))
    return jsonify({"ok": True})

@app.get("/api/v1/uploads")
def api_list_uploads():
    rows = db_all("SELECT id, path, display, mime, size, uploaded_at FROM media ORDER BY id DESC LIMIT 500")
    return jsonify(rows)

@app.post("/api/v1/upload")
def api_upload():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "sem arquivo"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"ok": False, "error": "sem nome"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    safe = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}{ext}"
    full = os.path.join(UPLOAD_DIR, safe)
    f.save(full)
    size = os.path.getsize(full)
    mime = mimetypes.guess_type(full)[0] or "application/octet-stream"
    rel  = f"/static/uploads/{safe}"
    db_exec("INSERT INTO media(path,display,mime,size,uploaded_at) VALUES(?,?,?,?,?)",
            (rel, f.filename, mime, size, now_iso()))
    return jsonify({"ok": True, "url": rel, "display": f.filename, "mime": mime, "size": size})

@app.get("/api/v1/playlist/get")
def api_playlist_get():
    code = request.args.get("terminal")
    t = db_one("SELECT code,playlist_json,campaign FROM terminals WHERE code=?", (code,))
    if not t: return jsonify({"ok": False, "error":"terminal não encontrado"}), 404
    items = json.loads(t["playlist_json"] or "[]")
    return jsonify({"ok": True, "items": items, "campaign": t.get("campaign")})

@app.post("/api/v1/playlist/save")
def api_playlist_save():
    data = request.json or {}
    term_code = (data.get("terminal") or "").strip()
    items     = data.get("items") or []
    campaign  = (data.get("campaign") or "").strip() or None

    if not term_code:
        return jsonify({"ok": False, "error": "terminal vazio"}), 400

    # normaliza: vídeo com duração 0 (player toca inteiro); imagem/rss precisa de duration>0
    norm = []
    for it in items:
        t = (it.get("type") or "video").lower()
        url = it.get("url") or ""
        dur = int(it.get("duration") or 0)
        if t in ("image","rss") and dur <= 0:
            dur = 10   # mínimo para imagem/rss
        norm.append({"type": t, "url": url, "duration": dur})

    if not db_one("SELECT id FROM terminals WHERE code=?", (term_code,)):
        return jsonify({"ok": False, "error": "terminal inexistente"}), 404

    db_exec("UPDATE terminals SET playlist_json=?, campaign=?, updated_at=? WHERE code=?",
            (json.dumps(norm), campaign, now_iso(), term_code))
    return jsonify({"ok": True})

@app.get("/api/v1/status")
def api_status():
    # resumo por cliente para o “dashboard dobrável”
    rows = db_all("""
    SELECT c.code as client_code, c.name as client_name,
           t.code as term_code, t.name as term_name, t.updated_at, t.last_seen, t.campaign
    FROM clients c
    LEFT JOIN terminals t ON t.client_code=c.code
    ORDER BY c.code, t.code
    """)
    out = {}
    for r in rows:
        if r["client_code"] not in out:
            out[r["client_code"]] = {"client": {"code": r["client_code"], "name": r["client_name"]}, "terminals": []}
        if r["term_code"]:
            out[r["client_code"]]["terminals"].append({
                "code": r["term_code"],
                "name": r["term_name"],
                "updated_at": r["updated_at"],
                "last_seen": r["last_seen"],
                "campaign": r["campaign"],
            })
    return jsonify(list(out.values()))

# ---------- Routes: Player (box) ----------
@app.get("/api/v1/config")
def api_config():
    """Box consulta usando ?code=001-02"""
    code = request.args.get("code","").strip()
    t = db_one("SELECT code,playlist_json FROM terminals WHERE code=?", (code,))
    if not t:
        return jsonify({"ok": False, "error":"invalid code"}), 404
    items = json.loads(t["playlist_json"] or "[]")
    return jsonify({
        "ok": True,
        "code": code,
        "playlist": items,          # vídeo com duration=0 => tocar inteiro; imagem/rss usa duration
        "refresh_minutes": REFRESH_MINUTES_DEFAULT,
        "updated_at": now_iso(),
        "brand": {"name": APP_TITLE, "color": BRAND_COLOR, "logo": LOGO_URL}
    })

@app.get("/api/v1/ping")
def api_ping():
    code = request.args.get("code","").strip()
    if not db_one("SELECT id FROM terminals WHERE code=?", (code,)):
        return jsonify({"ok": False, "error":"invalid code"}), 404
    db_exec("UPDATE terminals SET last_seen=? WHERE code=?", (now_iso(), code))
    return jsonify({"ok": True, "ts": now_iso()})

# ---------- Static uploads (opcional) ----------
@app.route("/static/uploads/<path:fname>")
def serve_upload(fname):
    return send_from_directory(UPLOAD_DIR, fname, conditional=True)

# ---------- Run ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)), debug=True)
