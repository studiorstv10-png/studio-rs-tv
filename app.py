import os
import json
from pathlib import Path
from datetime import datetime
from mimetypes import guess_type

from flask import Flask, render_template, jsonify, request
from werkzeug.utils import secure_filename

# ------- paths -------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PLAYLISTS_DIR = DATA_DIR / "playlists"
STATUS_FILE = DATA_DIR / "status.json"
TERMINALS_FILE = DATA_DIR / "terminals.json"
CAMPAIGNS_FILE = DATA_DIR / "campaigns.json"

STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = STATIC_DIR / "uploads"

for p in (DATA_DIR, PLAYLISTS_DIR, UPLOAD_DIR):
    p.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTS = {
    ".mp4", ".webm", ".mkv", ".mov",       # vídeo
    ".jpg", ".jpeg", ".png", ".gif",       # imagem
    ".xml"                                 # rss
}

app = Flask(__name__, static_folder="static", template_folder="templates")


# ------------------------ utils ------------------------

def now_iso():
    return datetime.utcnow().isoformat() + "Z"

def read_json(path: Path, default):
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default

def write_json(path: Path, data):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)

def _file_type_by_ext(ext: str) -> str:
    ext = (ext or "").lower()
    if ext in {".mp4", ".webm", ".mkv", ".mov"}:
        return "video"
    if ext in {".jpg", ".jpeg", ".png", ".gif"}:
        return "image"
    if ext in {".xml"}:
        return "rss"
    mime, _ = guess_type("x" + ext)
    if mime:
        if mime.startswith("video/"): return "video"
        if mime.startswith("image/"): return "image"
    return "file"

def get_branding():
    return {
        "name": os.getenv("BRAND_NAME", "Studio RS TV"),
        "primary_color": os.getenv("BRAND_PRIMARY", "#0d1b2a"),
        "logo": os.getenv("BRAND_LOGO", "/static/logo.png"),
        "support_wa": os.getenv("SUPPORT_WA", "https://wa.me/5512999999999"),
    }

def _term_key(t):
    return t.get("code") or t.get("name")

# ------------------------ pages ------------------------

@app.route("/")
def index():
    return render_template("index.html", brand=get_branding())

# ------------------------ diag / config ----------------

@app.route("/api/v1/ping")
def ping():
    return jsonify({"ok": True, "ts": now_iso()})

@app.route("/api/v1/config")
def config():
    code = request.args.get("code", "").strip()
    pfile = PLAYLISTS_DIR / f"{code}.json" if code else None
    playlist_items = read_json(pfile, []) if pfile else []
    return jsonify({
        "ok": True,
        "code": code or "DEMO",
        "refresh_minutes": int(os.getenv("REFRESH_MINUTES", "10")),
        "playlist": playlist_items,
        "updated_at": now_iso(),
    })

# ------------------------ terminals (individual + lote) --------------------

@app.route("/api/v1/terminals", methods=["GET", "POST"])
def terminals():
    terms = read_json(TERMINALS_FILE, [])
    if request.method == "GET":
        return jsonify({"ok": True, "items": terms})

    payload = request.get_json(force=True, silent=True) or {}
    name = (payload.get("name") or "").strip()
    code = (payload.get("code") or "").strip()
    client = (payload.get("client") or "").strip()
    group = (payload.get("group") or "").strip()

    if not name and not code:
        return jsonify({"ok": False, "error": "Informe pelo menos Nome ou Código."}), 400

    key = code or name
    # update if exists
    for t in terms:
        if (_term_key(t)) == key:
            t.update({
                "name": name or t.get("name"),
                "code": code or t.get("code"),
                "client": client,
                "group": group
            })
            write_json(TERMINALS_FILE, terms)
            return jsonify({"ok": True, "items": terms})

    # create
    terms.append({"name": name or code, "code": code, "client": client, "group": group})
    write_json(TERMINALS_FILE, terms)
    return jsonify({"ok": True, "items": terms})

@app.route("/api/v1/terminals/bulk", methods=["POST"])
def terminals_bulk():
    """
    body:
    {
      "client": "João",
      "base_name": "BOX",
      "count": 10,
      "code_start": 1,
      "code_digits": 3,
      "groups": ["Bebidas","Açougue","Caixa"]  # opcional: se tiver menos que count, repete vazio
    }
    """
    payload = request.get_json(force=True, silent=True) or {}
    client = (payload.get("client") or "").strip()
    base_name = (payload.get("base_name") or "").strip() or "BOX"
    count = int(payload.get("count", 0))
    code_start = int(payload.get("code_start", 1))
    code_digits = int(payload.get("code_digits", 3))
    groups = payload.get("groups") or []

    if not client or count <= 0:
        return jsonify({"ok": False, "error": "Informe client e count > 0."}), 400

    terms = read_json(TERMINALS_FILE, [])
    created = []
    for i in range(count):
        n = code_start + i
        code = str(n).zfill(code_digits)
        name = f"{base_name} {n}"
        group = groups[i] if i < len(groups) else ""
        key = code or name
        # evita duplicados pelo code
        if not any((_term_key(t)) == key for t in terms):
            term = {"name": name, "code": code, "client": client, "group": group}
            terms.append(term)
            created.append(term)

    write_json(TERMINALS_FILE, terms)
    return jsonify({"ok": True, "created": created, "total": len(terms)})

# ------------------------ uploads ----------------------

@app.route("/api/v1/uploads", methods=["GET"])
def list_uploads():
    items = []
    for f in sorted(UPLOAD_DIR.glob("*")):
        if f.is_file():
            items.append({
                "name": f.name,
                "url": f"/static/uploads/{f.name}",
                "type": _file_type_by_ext(f.suffix),
                "size": f.stat().st_size
            })
    return jsonify({"ok": True, "items": items})

@app.route("/api/v1/upload", methods=["POST"])
def upload():
    if "files" not in request.files:
        return jsonify({"ok": False, "error": "Nenhum arquivo (files)."}), 400
    files = request.files.getlist("files")
    saved = []
    for f in files:
        if not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in ALLOWED_EXTS:
            return jsonify({"ok": False, "error": f"Extensão não permitida: {ext}"}), 400
        safe = secure_filename(f.filename)
        ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        final_name = f"{ts}-{safe}"
        dest = UPLOAD_DIR / final_name
        f.save(dest)
        saved.append({
            "name": final_name,
            "url": f"/static/uploads/{final_name}",
            "type": _file_type_by_ext(ext)
        })
    return jsonify({"ok": True, "items": saved})

# ------------------------ playlists por terminal ----------------------

@app.route("/api/v1/playlists/<terminal>", methods=["GET", "POST"])
def playlists(terminal: str):
    terminal = terminal.strip()
    if not terminal:
        return jsonify({"ok": False, "error": "Terminal inválido."}), 400
    pfile = PLAYLISTS_DIR / f"{terminal}.json"
    if request.method == "GET":
        items = read_json(pfile, [])
        return jsonify({"ok": True, "items": items})
    payload = request.get_json(force=True, silent=True) or {}
    items = payload.get("items", [])
    if not isinstance(items, list):
        return jsonify({"ok": False, "error": "items inválido."}), 400
    norm = []
    for it in items:
        t = (it.get("type") or "").lower()
        u = (it.get("url") or "").strip()
        if not t or not u: 
            continue
        d = int(it.get("duration", 0)) if t in ("image", "rss") else 0
        norm.append({"type": t, "url": u, "duration": d})
    write_json(pfile, norm)
    return jsonify({"ok": True, "items": norm})

# ------------------------ campanhas (playlist nome + múltiplos alvos) ----

def _load_campaigns():
    return read_json(CAMPAIGNS_FILE, {"campaigns": []})

def _save_campaigns(data):
    write_json(CAMPAIGNS_FILE, data)

@app.route("/api/v1/campaigns", methods=["GET"])
def campaigns_list():
    return jsonify(_load_campaigns())

@app.route("/api/v1/campaigns/save", methods=["POST"])
def campaigns_save():
    """
    {
      "name": "Campanha Setembro",
      "items": [ {type,url,duration?}, ... ],
      "targets": ["001","002"]
    }
    """
    payload = request.get_json(force=True, silent=True) or {}
    name = (payload.get("name") or "").strip()
    items = payload.get("items", [])
    targets = payload.get("targets", [])
    if not name:
        return jsonify({"ok": False, "error": "Informe o nome da campanha."}), 400
    if not isinstance(items, list) or not items:
        return jsonify({"ok": False, "error": "items vazio/ inválido."}), 400
    if not isinstance(targets, list) or not targets:
        return jsonify({"ok": False, "error": "Selecione ao menos um terminal."}), 400

    norm = []
    for it in items:
        t = (it.get("type") or "").lower()
        u = (it.get("url") or "").strip()
        if not t or not u: 
            continue
        d = int(it.get("duration", 0)) if t in ("image", "rss") else 0
        norm.append({"type": t, "url": u, "duration": d})
    if not norm:
        return jsonify({"ok": False, "error": "items inválidos."}), 400

    camp = _load_campaigns()
    now = now_iso()

    updated = False
    for c in camp["campaigns"]:
        if (c.get("name") or "").strip().lower() == name.lower():
            c["items"] = norm
            c["targets"] = targets
            c["updated_at"] = now
            updated = True
            break
    if not updated:
        camp["campaigns"].append({
            "id": f"cmp_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            "name": name,
            "items": norm,
            "targets": targets,
            "updated_at": now
        })
    _save_campaigns(camp)

    # grava playlist física por terminal (para o player)
    for t in targets:
        write_json(PLAYLISTS_DIR / f"{t}.json", norm)

    return jsonify({"ok": True, "campaign": name, "targets": targets})

# ------------------------ status / heartbeat ----------------------

@app.route("/api/v1/heartbeat", methods=["POST"])
def heartbeat():
    payload = request.get_json(force=True, silent=True) or {}
    code = (payload.get("code") or "").strip()
    if not code:
        return jsonify({"ok": False, "error": "code é obrigatório"}), 400

    st = read_json(STATUS_FILE, {})
    st[code] = {
        "last_seen": now_iso(),
        "ip": request.headers.get("X-Forwarded-For", request.remote_addr),
        "player": payload.get("player"),
        "version": payload.get("version"),
        "playing": payload.get("playing"),
    }
    write_json(STATUS_FILE, st)
    return jsonify({"ok": True})

def _campaign_for_terminal(code: str):
    camp = _load_campaigns()
    best_name = None
    best_ts = None
    for c in camp.get("campaigns", []):
        if code in (c.get("targets") or []):
            ts = c.get("updated_at")
            dt = None
            if ts:
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except Exception:
                    dt = None
            if best_ts is None or (dt and dt > best_ts):
                best_ts = dt
                best_name = c.get("name")
    return best_name

@app.route("/api/v1/status", methods=["GET"])
def status_list():
    terms = read_json(TERMINALS_FILE, [])
    st = read_json(STATUS_FILE, {})
    refresh = int(os.getenv("REFRESH_MINUTES", "10"))
    now = datetime.utcnow()

    items = []
    for t in terms:
        key = _term_key(t)
        s = st.get(key, {})
        last_seen = s.get("last_seen")
        online = False
        if last_seen:
            try:
                dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                delta = (now - dt.replace(tzinfo=None)).total_seconds()
                online = (delta <= (refresh * 120))  # janela 2×
            except Exception:
                pass

        items.append({
            "name": t.get("name"),
            "code": t.get("code"),
            "client": t.get("client"),
            "group": t.get("group"),
            "campaign": _campaign_for_terminal(key),
            "online": online,
            "last_seen": last_seen,
            "playing": s.get("playing"),
            "ip": s.get("ip"),
            "player": s.get("player"),
            "version": s.get("version"),
        })
    return jsonify({"ok": True, "items": items})

@app.route("/healthz")
def healthz():
    return "ok", 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=True)
