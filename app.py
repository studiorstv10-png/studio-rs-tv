import os
import json
from pathlib import Path
from datetime import datetime
from mimetypes import guess_type

from flask import (
    Flask, render_template, jsonify, request, send_from_directory
)
from werkzeug.utils import secure_filename

# ------------------------------------------------------------------
# Configuração básica
# ------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PLAYLISTS_DIR = DATA_DIR / "playlists"
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = STATIC_DIR / "uploads"

for p in (DATA_DIR, PLAYLISTS_DIR, UPLOAD_DIR):
    p.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTS = {
    # vídeo
    ".mp4", ".webm", ".mkv", ".mov",
    # imagem
    ".jpg", ".jpeg", ".png", ".gif",
    # rss (opcional)
    ".xml"
}

app = Flask(__name__, static_folder="static", template_folder="templates")


# ------------------------------------------------------------------
# Branding (logo, cor, etc.)
# ------------------------------------------------------------------
def get_branding():
    return {
        "name": os.getenv("BRAND_NAME", "Studio RS TV"),
        "primary_color": os.getenv("BRAND_PRIMARY", "#0d1b2a"),
        "logo": os.getenv("BRAND_LOGO", "/static/logo.png"),
        "support_wa": os.getenv("SUPPORT_WA", "https://wa.me/5512999999999"),
    }


# ------------------------------------------------------------------
# Helpers de persistência
# ------------------------------------------------------------------
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


# ------------------------------------------------------------------
# Rotas de página
# ------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html", brand=get_branding())


# ------------------------------------------------------------------
# API – Diagnóstico / Player
# ------------------------------------------------------------------
@app.route("/api/v1/ping")
def ping():
    return jsonify({"ok": True, "ts": datetime.utcnow().isoformat() + "Z"})


@app.route("/api/v1/config")
def config():
    """
    O player chama: /api/v1/config?code=BOX-001
    Se existir uma playlist com esse code (data/playlists/BOX-001.json)
    ela é retornada embutida no JSON.
    """
    code = request.args.get("code", "").strip()
    playlist_items = []

    if code:
        pfile = PLAYLISTS_DIR / f"{code}.json"
        playlist_items = read_json(pfile, [])

    resp = {
        "ok": True,
        "code": code or "DEMO",
        "refresh_minutes": int(os.getenv("REFRESH_MINUTES", "10")),
        "playlist": playlist_items,
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    return jsonify(resp)


# ------------------------------------------------------------------
# API – Terminais
# ------------------------------------------------------------------
TERMINALS_FILE = DATA_DIR / "terminals.json"

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

    if not name:
        return jsonify({"ok": False, "error": "Nome do terminal é obrigatório."}), 400

    key = code or name  # usa 'code' se houver; senão 'name'
    found = False
    for t in terms:
        if (t.get("code") or t.get("name")) == key:
            t.update({"name": name, "code": code, "client": client, "group": group})
            found = True
            break

    if not found:
        terms.append({"name": name, "code": code, "client": client, "group": group})

    write_json(TERMINALS_FILE, terms)
    return jsonify({"ok": True, "items": terms})


# ------------------------------------------------------------------
# API – Uploads
# ------------------------------------------------------------------
def _file_type_by_ext(ext: str) -> str:
    ext = (ext or "").lower()
    if ext in {".mp4", ".webm", ".mkv", ".mov"}:
        return "video"
    if ext in {".jpg", ".jpeg", ".png", ".gif"}:
        return "image"
    if ext in {".xml"}:
        return "rss"
    # tenta adivinhar
    mime, _ = guess_type("x" + ext)
    if mime:
        if mime.startswith("video/"):
            return "video"
        if mime.startswith("image/"):
            return "image"
    return "file"


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
        return jsonify({"ok": False, "error": "Nenhum arquivo enviado (campo 'files')."}), 400

    files = request.files.getlist("files")
    saved = []

    for f in files:
        if not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in ALLOWED_EXTS:
            return jsonify({"ok": False, "error": f"Extensão não permitida: {ext}"}), 400

        safe = secure_filename(f.filename)
        # prefixo com data/hora para evitar colisão
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


# ------------------------------------------------------------------
# API – Playlists
# ------------------------------------------------------------------
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
        return jsonify({"ok": False, "error": "Formato inválido (items)."}), 400

    # valida estrutura mínima
    norm = []
    for it in items:
        t = (it.get("type") or "").lower()
        u = (it.get("url") or "").strip()
        if not t or not u:
            continue
        d = int(it.get("duration", 0)) if t == "image" else 0
        norm.append({"type": t, "url": u, "duration": d})

    write_json(pfile, norm)
    return jsonify({"ok": True, "items": norm})


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------
@app.route("/healthz")
def healthz():
    return "ok", 200


# ------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=True)
