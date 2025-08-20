import os
import json
import csv
import random
from pathlib import Path
from datetime import datetime, timedelta
from mimetypes import guess_type

from flask import Flask, render_template, jsonify, request
from werkzeug.utils import secure_filename

# ---------- paths ----------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PLAYLISTS_DIR = DATA_DIR / "playlists"
STATUS_FILE = DATA_DIR / "status.json"
TERMINALS_FILE = DATA_DIR / "terminals.json"
CAMPAIGNS_FILE = DATA_DIR / "campaigns.json"
PAIR_FILE = DATA_DIR / "pairings.json"
ALERTS_FILE = DATA_DIR / "alerts.json"

STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = STATIC_DIR / "uploads"

for p in (DATA_DIR, PLAYLISTS_DIR, UPLOAD_DIR):
    p.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTS = {
    ".mp4", ".webm", ".mkv", ".mov",
    ".jpg", ".jpeg", ".png", ".gif",
    ".xml"
}

PAIR_TTL_SECONDS = 15 * 60  # 15 min

app = Flask(__name__, static_folder="static", template_folder="templates")


# ---------- utils ----------
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


# ---------- pages ----------
@app.route("/")
def index():
    return render_template("index.html", brand=get_branding())


# ---------- diag / config ----------
@app.route("/api/v1/ping")
def ping():
    return jsonify({"ok": True, "ts": now_iso()})


# -------- campaigns helpers --------
def _load_campaigns():
    return read_json(CAMPAIGNS_FILE, {"campaigns": []})

def _save_campaigns(data):
    write_json(CAMPAIGNS_FILE, data)

_DAYS_MAP = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6
}

def _schedule_match(schedule: dict, now: datetime) -> bool:
    """schedule:
       {
         "days": ["mon","tue",...],  # opcional
         "start_time": "08:00",      # opcional
         "end_time": "18:00",        # opcional
         "start_date": "2025-08-01", # opcional
         "end_date": "2025-09-01"    # opcional
       }
    """
    if not schedule:
        return True
    # days
    days = schedule.get("days") or []
    if days:
        wd = now.weekday()
        valid = any(_DAYS_MAP.get(d) == wd for d in days if d in _DAYS_MAP)
        if not valid:
            return False
    # date range
    sd = schedule.get("start_date")
    ed = schedule.get("end_date")
    if sd:
        try:
            d0 = datetime.fromisoformat(sd).date()
            if now.date() < d0:
                return False
        except Exception:
            pass
    if ed:
        try:
            d1 = datetime.fromisoformat(ed).date()
            if now.date() > d1:
                return False
        except Exception:
            pass
    # time window (naive local/UTC do servidor)
    st = schedule.get("start_time")
    et = schedule.get("end_time")
    if st and et:
        try:
            h0, m0 = map(int, st.split(":"))
            h1, m1 = map(int, et.split(":"))
            t0 = h0 * 60 + m0
            t1 = h1 * 60 + m1
            cur = now.hour * 60 + now.minute
            if t0 <= t1:
                return t0 <= cur <= t1
            else:
                # janela atravessa meia-noite
                return cur >= t0 or cur <= t1
        except Exception:
            pass
    return True

def _best_active_campaign_for_terminal(code: str, now: datetime):
    camp = _load_campaigns()
    best = None
    best_dt = None
    for c in camp.get("campaigns", []):
        targets = c.get("targets") or []
        if code in targets:
            if _schedule_match(c.get("schedule") or {}, now):
                ts = c.get("updated_at")
                dt = None
                if ts:
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z","+00:00"))
                    except Exception:
                        dt = None
                if best is None or (dt and (best_dt is None or dt > best_dt)):
                    best = c
                    best_dt = dt
    return best

@app.route("/api/v1/config")
def config():
    code = request.args.get("code", "").strip()
    now = datetime.utcnow()
    items = []
    campaign_name = None

    if code:
        # campanha ativa no momento
        best = _best_active_campaign_for_terminal(code, now)
        if best:
            items = best.get("items", [])
            campaign_name = best.get("name")

        # fallback: playlist física do terminal (se existir)
        if not items:
            pfile = PLAYLISTS_DIR / f"{code}.json"
            items = read_json(pfile, [])

    return jsonify({
        "ok": True,
        "code": code or "DEMO",
        "campaign": campaign_name,
        "refresh_minutes": int(os.getenv("REFRESH_MINUTES", "10")),
        "playlist": items,
        "updated_at": now_iso(),
    })


# ---------- terminals ----------
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

    terms.append({"name": name or code, "code": code, "client": client, "group": group})
    write_json(TERMINALS_FILE, terms)
    return jsonify({"ok": True, "items": terms})

@app.route("/api/v1/terminals/bulk", methods=["POST"])
def terminals_bulk():
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
        if not any((_term_key(t)) == key for t in terms):
            term = {"name": name, "code": code, "client": client, "group": group}
            terms.append(term)
            created.append(term)

    write_json(TERMINALS_FILE, terms)
    return jsonify({"ok": True, "created": created, "total": len(terms)})

@app.route("/api/v1/terminals/import", methods=["POST"])
def terminals_import():
    """
    multipart/form-data com um arquivo "file" (CSV) com cabeçalho:
    name,code,client,group
    """
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "Envie um arquivo em 'file'."}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"ok": False, "error": "Arquivo inválido."}), 400

    data = f.read().decode("utf-8", errors="ignore").splitlines()
    reader = csv.DictReader(data)
    terms = read_json(TERMINALS_FILE, [])
    added = 0
    for row in reader:
        name = (row.get("name") or "").strip()
        code = (row.get("code") or "").strip()
        client = (row.get("client") or "").strip()
        group = (row.get("group") or "").strip()
        if not name and not code:
            continue
        key = code or name
        if any((_term_key(t)) == key for t in terms):
            continue
        terms.append({"name": name or code, "code": code, "client": client, "group": group})
        added += 1
    write_json(TERMINALS_FILE, terms)
    return jsonify({"ok": True, "added": added, "total": len(terms)})


# ---------- uploads ----------
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


# ---------- playlists por terminal (CRUD direto) ----------
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


# ---------- campanhas (com agendamento) ----------
@app.route("/api/v1/campaigns", methods=["GET"])
def campaigns_list():
    return jsonify(_load_campaigns())

@app.route("/api/v1/campaigns/save", methods=["POST"])
def campaigns_save():
    """
    {
      "name": "Campanha Setembro",
      "items": [ {type,url,duration?}, ... ],
      "targets": ["001","002"],
      "schedule": {
        "days": ["mon","tue","wed"],      # opcional
        "start_time": "08:00",            # opcional
        "end_time": "18:00",              # opcional
        "start_date": "2025-08-01",       # opcional
        "end_date": "2025-09-01"          # opcional
      }
    }
    """
    payload = request.get_json(force=True, silent=True) or {}
    name = (payload.get("name") or "").strip()
    items = payload.get("items", [])
    targets = payload.get("targets", [])
    schedule = payload.get("schedule") or {}

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
            c["schedule"] = schedule
            c["updated_at"] = now
            updated = True
            break
    if not updated:
        camp["campaigns"].append({
            "id": f"cmp_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            "name": name,
            "items": norm,
            "targets": targets,
            "schedule": schedule,
            "updated_at": now
        })
    _save_campaigns(camp)

    # também grava playlist física por terminal (fallback)
    for t in targets:
        write_json(PLAYLISTS_DIR / f"{t}.json", norm)

    return jsonify({"ok": True, "campaign": name, "targets": targets})


# ---------- status / heartbeat / alertas ----------
def _alerts_db():
    return read_json(ALERTS_FILE, {"items": []})

def _alerts_save(db):
    write_json(ALERTS_FILE, db)

@app.route("/api/v1/alerts", methods=["GET"])
def alerts_list():
    return jsonify(_alerts_db())

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
        # guardamos um "is_online" otimista (verdadeiro no batimento):
        "is_online": True
    }
    write_json(STATUS_FILE, st)
    return jsonify({"ok": True})

def _campaign_for_terminal_name(code: str):
    best = _best_active_campaign_for_terminal(code, datetime.utcnow())
    return best.get("name") if best else None

@app.route("/api/v1/status", methods=["GET"])
def status_list():
    terms = read_json(TERMINALS_FILE, [])
    st = read_json(STATUS_FILE, {})
    alerts = _alerts_db()

    refresh = int(os.getenv("REFRESH_MINUTES", "10"))
    now = datetime.utcnow()

    changed = False
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
                online = (delta <= (refresh * 120))  # 2x janela
            except Exception:
                pass

        # detectar transição e gerar alerta
        prev = s.get("is_online")
        if prev is not None and prev != online:
            s["is_online"] = online
            s["state_changed_at"] = now_iso()
            if not online:
                alerts["items"].append({
                    "terminal": key,
                    "client": t.get("client"),
                    "group": t.get("group"),
                    "when": now_iso(),
                    "reason": "offline"
                })
                # Limite simples da fila:
                if len(alerts["items"]) > 500:
                    alerts["items"] = alerts["items"][-500:]
            changed = True
        else:
            s["is_online"] = online

        st[key] = s

        items.append({
            "name": t.get("name"),
            "code": t.get("code"),
            "client": t.get("client"),
            "group": t.get("group"),
            "campaign": _campaign_for_terminal_name(key),
            "online": online,
            "last_seen": last_seen,
            "playing": s.get("playing"),
            "ip": s.get("ip"),
            "player": s.get("player"),
            "version": s.get("version"),
        })

    if changed:
        write_json(STATUS_FILE, st)
        _alerts_save(alerts)

    return jsonify({"ok": True, "items": items})


# ---------- pairing (box <-> terminal) ----------
def _pair_db():
    return read_json(PAIR_FILE, {"codes": {}})

def _pair_save(db):
    write_json(PAIR_FILE, db)

def _cleanup_pairings(db=None):
    if db is None:
        db = _pair_db()
    codes = db.get("codes", {})
    now = datetime.utcnow()
    changed = False
    for c, info in list(codes.items()):
        ts = info.get("created_at")
        exp = info.get("expires_in", PAIR_TTL_SECONDS)
        try:
            dt = datetime.fromisoformat(ts.replace("Z","+00:00"))
        except Exception:
            dt = now - timedelta(seconds=PAIR_TTL_SECONDS*2)
        if (now - dt).total_seconds() > exp:
            codes.pop(c, None); changed = True
    if changed:
        db["codes"] = codes
        _pair_save(db)
    return db

def _gen_code():
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    return "".join(random.choice(alphabet) for _ in range(6))

@app.route("/api/v1/pair/start", methods=["POST"])
def pair_start():
    db = _cleanup_pairings()
    code = _gen_code()
    while code in db.get("codes", {}):
        code = _gen_code()
    db["codes"][code] = {
        "created_at": now_iso(),
        "terminal": None,
        "ip": request.headers.get("X-Forwarded-For", request.remote_addr),
        "expires_in": PAIR_TTL_SECONDS
    }
    _pair_save(db)
    return jsonify({"ok": True, "code": code, "expires_in": PAIR_TTL_SECONDS})

@app.route("/api/v1/pair/claim", methods=["POST"])
def pair_claim():
    payload = request.get_json(force=True, silent=True) or {}
    code = (payload.get("code") or "").strip().upper()
    terminal = (payload.get("terminal") or "").strip()
    if not code or not terminal:
        return jsonify({"ok": False, "error": "code e terminal são obrigatórios."}), 400
    db = _cleanup_pairings()
    info = db.get("codes", {}).get(code)
    if not info:
        return jsonify({"ok": False, "error": "Código inválido / expirado."}), 400
    if info.get("terminal"):
        return jsonify({"ok": False, "error": "Código já utilizado."}), 400
    info["terminal"] = terminal
    _pair_save(db)
    # cria playlist fallback vazia, se não existir
    pfile = PLAYLISTS_DIR / f"{terminal}.json"
    if not pfile.exists():
        write_json(pfile, [])
    return jsonify({"ok": True})

@app.route("/api/v1/pair/poll", methods=["GET"])
def pair_poll():
    code = (request.args.get("code") or "").strip().upper()
    if not code:
        return jsonify({"ok": False, "error": "code é obrigatório."}), 400
    db = _cleanup_pairings()
    info = db.get("codes", {}).get(code)
    if not info:
        return jsonify({"ok": False, "error": "Código inválido / expirado."}), 404
    return jsonify({"ok": True, "terminal": info.get("terminal")})


# ---------- health ----------
@app.route("/healthz")
def healthz():
    return "ok", 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=True)
