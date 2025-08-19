import os
import re
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, render_template_string, abort

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURAÇÃO
# ──────────────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = BASE_DIR / "uploads"

DATA_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

BRAND = {
    "name": os.getenv("BRAND_NAME", "Studio RS TV"),
    "color": os.getenv("BRAND_COLOR", "#0d1b2a"),
    "logo": os.getenv("BRAND_LOGO_URL", None)
}

DEFAULT_POLL_SECONDS = 60
DEFAULT_LAYOUT = "16:9"

# Arquivos JSON do "banco"
PATH_TERMINALS = DATA_DIR / "terminals.json"   # {code: {...}}
PATH_PLAYLISTS = DATA_DIR / "playlists.json"   # {code: [items]}
PATH_UPLOADS   = DATA_DIR / "uploads.json"     # {"items":[...]}

def _load(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text("utf-8"))
        except Exception:
            return default
    return default

def _save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

DB_TERMINALS = _load(PATH_TERMINALS, {})
DB_PLAYLISTS = _load(PATH_PLAYLISTS, {})
DB_UPLOADS   = _load(PATH_UPLOADS, {"items": []})

def now_utc_iso():
    return datetime.now(timezone.utc).isoformat()

def sanitize_filename(name: str) -> str:
    # remove path e caracteres ruins
    base = Path(name).name
    base = re.sub(r"[^\w\-. ]+", "", base, flags=re.UNICODE)  # mantém letras, números, _, -, ., espaço
    base = base.strip().replace(" ", "_")
    if not base:
        base = "arquivo"
    return base

# ──────────────────────────────────────────────────────────────────────────────
# APP
# ──────────────────────────────────────────────────────────────────────────────
app = Flask(__name__, static_url_path="/static", static_folder="static")

# Painel simplificado (sem editor de marca)
INDEX_HTML = """
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <title>{{ brand.name }} — Painel</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root { --brand: {{ brand.color }}; }
    body{margin:0;font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif;background:#0b1220;color:#e5e7eb}
    header{display:flex;align-items:center;gap:12px;padding:16px;background:#0f1629;border-bottom:1px solid #1e2a44}
    header img{height:32px}
    h1{font-size:16px;margin:0}
    a.btn,button.btn{background:var(--brand);border:0;color:white;padding:10px 14px;border-radius:8px;cursor:pointer}
    .wrap{max-width:1200px;margin:24px auto;padding:0 16px;display:grid;gap:16px}
    .card{background:#0f1629;border:1px solid #1e2a44;border-radius:12px;padding:16px}
    .row{display:flex;gap:12px;flex-wrap:wrap}
    .row>input,.row>select{flex:1 1 220px;background:#0b1220;border:1px solid #1e2a44;border-radius:8px;color:#e5e7eb;padding:10px}
    .list{font-family:ui-monospace,Consolas,monospace;font-size:13px;line-height:1.6}
    .ok{color:#4ade80}.warn{color:#fbbf24}.err{color:#f87171}
    small{opacity:.7}
    .pill{padding:4px 8px;border-radius:999px;background:#13203d;border:1px solid #223152}
  </style>
</head>
<body>
<header>
  {% if brand.logo %}<img src="{{ brand.logo }}" alt="logo">{% endif %}
  <h1>{{ brand.name }} — Painel <span class="pill">{{ brand.color }}</span></h1>
</header>

<div class="wrap">

  <div class="card">
    <h2>Terminais</h2>
    <div class="row">
      <input id="t_code"   placeholder="Código (ex.: BOX-0001)">
      <input id="t_name"   placeholder="Nome visível (ex.: AÇOUGUE02)">
      <input id="t_group"  placeholder="Grupo (opcional, ex.: MATRIZ)">
      <button class="btn" onclick="createTerminal()">Criar</button>
    </div>
    <div style="margin-top:12px" class="list" id="terms"></div>
  </div>

  <div class="card">
    <h2>Uploads</h2>
    <div class="row">
      <input id="up_file" type="file" multiple>
      <button class="btn" onclick="doUpload()">Enviar</button>
    </div>
    <div style="margin-top:12px" class="list" id="uploads"></div>
  </div>

  <div class="card">
    <h2>Playlist</h2>
    <div class="row">
      <select id="p_term"></select>
      <button class="btn" onclick="loadPlaylist()">Carregar</button>
    </div>
    <div class="row" style="margin-top:12px">
      <select id="p_type">
        <option value="video">Vídeo</option>
        <option value="image">Imagem</option>
        <option value="rss">RSS</option>
      </select>
      <input id="p_url" placeholder="URL ou /uploads/arquivo.ext">
      <input id="p_dur" placeholder="Duração (s) p/ imagem/RSS">
      <button class="btn" onclick="addItem()">Adicionar</button>
    </div>
    <div style="margin-top:12px" class="list" id="plist"></div>
    <div style="margin-top:12px">
      <button class="btn" onclick="savePlaylist()">Salvar Playlist</button>
    </div>
  </div>

</div>

<script>
const ADMIN_PASS = "{{ admin }}";

// utils
const $ = (q)=>document.querySelector(q);
const fmt = (n)=> new Intl.NumberFormat('pt-BR').format(n);

async function api(path, opt={}){
  const r = await fetch(path, Object.assign({headers:{'x-admin-pass': ADMIN_PASS}}, opt));
  if(!r.ok){const tx=await r.text(); throw new Error(tx||('HTTP '+r.status))}
  return r.json();
}

async function refreshTerms(){
  const {items}= await api('/api/v1/admin/terminals');
  const el = $('#terms'); el.innerHTML = '';
  const sel = $('#p_term'); sel.innerHTML = '';
  items.forEach(t=>{
    el.innerHTML += `• <b>${t.code}</b> — ${t.name} <small>(grupo: ${t.group||'-'})</small> — status: <span class="${t.status==='ok'?'ok':'warn'}">${t.status}</span> — trial até ${t.trial_until||'-'}<br>`;
    sel.innerHTML += `<option value="${t.code}">${t.code} — ${t.name}</option>`;
  });
}

async function createTerminal(){
  const code=$('#t_code').value.trim();
  const name=$('#t_name').value.trim();
  const group=$('#t_group').value.trim();
  if(!code||!name) return alert('Código e Nome são obrigatórios');
  await api('/api/v1/admin/terminal',{method:'POST',body:JSON.stringify({code,name,group,trial_days:15})});
  $('#t_code').value=''; $('#t_name').value=''; $('#t_group').value='';
  await refreshTerms();
  alert('Criado com sucesso.');
}

async function refreshUploads(){
  const {items} = await api('/api/v1/admin/uploads');
  const el = $('#uploads'); el.innerHTML='';
  items.slice().reverse().forEach(u=>{
    el.innerHTML += `• ${u.display_name} <small>(${u.type}, ${fmt(u.size)} bytes)</small> — <code>${u.path}</code><br>`;
  });
}

async function doUpload(){
  const f = $('#up_file').files;
  if(!f.length) return alert('Selecione arquivos.');
  const fd = new FormData();
  [...f].forEach(x=>fd.append('files', x));
  const r = await fetch('/api/v1/admin/upload', {method:'POST', headers:{'x-admin-pass': ADMIN_PASS}, body: fd});
  if(!r.ok){return alert('Falha no upload');}
  await refreshUploads();
  alert('Enviado.');
}

let currentPlaylist = [];
async function loadPlaylist(){
  const term=$('#p_term').value;
  const {items}= await api(`/api/v1/admin/playlist/${encodeURIComponent(term)}`);
  currentPlaylist = items || [];
  renderPlaylist();
}
function renderPlaylist(){
  const el=$('#plist'); el.innerHTML='';
  if(!currentPlaylist.length){el.innerHTML='<i>vazia</i>';return;}
  currentPlaylist.forEach((it,i)=>{
    el.innerHTML += `${i+1}. [${it.type}] ${it.url||it.path} ${it.duration?('('+it.duration+'s)'):''} <button onclick="rem(${i})">remover</button><br>`;
  });
}
function rem(i){ currentPlaylist.splice(i,1); renderPlaylist(); }

function addItem(){
  const type=$('#p_type').value;
  const url=$('#p_url').value.trim();
  const duration=parseInt($('#p_dur').value.trim()||'0',10)||0;
  if(!url) return alert('Informe URL ou /uploads/arquivo.ext');
  const it={type};
  if(url.startsWith('/uploads/')) it.path=url; else it.url=url;
  if(type!=='video') it.duration = duration||10;
  currentPlaylist.push(it);
  $('#p_url').value=''; $('#p_dur').value='';
  renderPlaylist();
}

async function savePlaylist(){
  const term=$('#p_term').value;
  await api(`/api/v1/admin/playlist/${encodeURIComponent(term)}`,{method:'POST', body:JSON.stringify({items: currentPlaylist})});
  alert('Playlist salva.');
}

(async function init(){
  await refreshTerms();
  await refreshUploads();
})();
</script>
</body>
</html>
"""

# ──────────────────────────────────────────────────────────────────────────────
# ROTAS DO PAINEL
# ──────────────────────────────────────────────────────────────────────────────
def _check_admin():
    if request.headers.get("x-admin-pass") != ADMIN_PASSWORD:
        abort(401, "unauthorized")

@app.get("/")
def index():
    return render_template_string(INDEX_HTML, brand=BRAND, admin=ADMIN_PASSWORD)

# ──────────────────────────────────────────────────────────────────────────────
# ADMIN API
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/api/v1/admin/terminals")
def list_terminals():
    _check_admin()
    items = []
    for code, t in DB_TERMINALS.items():
        items.append({
            "code": code,
            "name": t.get("name"),
            "group": t.get("group"),
            "status": t.get("status","ok"),
            "trial_until": t.get("trial_until")
        })
    return jsonify({"items": items})

@app.post("/api/v1/admin/terminal")
def create_terminal():
    _check_admin()
    data = request.get_json(force=True)
    code = data.get("code","").strip()
    name = data.get("name","").strip()
    group = data.get("group") or None
    if not code or not name:
        abort(400, "code and name required")

    if code in DB_TERMINALS:
        abort(409, "already exists")

    trial_days = int(data.get("trial_days") or 15)
    trial_until = (datetime.now(timezone.utc) + timedelta(days=trial_days)).date().isoformat()

    DB_TERMINALS[code] = {
        "name": name,
        "group": group,
        "status": "ok",
        "trial_until": trial_until,
        "created_at": now_utc_iso()
    }
    _save(PATH_TERMINALS, DB_TERMINALS)
    return jsonify({"ok": True})

@app.get("/api/v1/admin/uploads")
def admin_list_uploads():
    _check_admin()
    return jsonify(DB_UPLOADS)

@app.post("/api/v1/admin/upload")
def admin_upload():
    _check_admin()
    files = request.files.getlist("files")
    if not files:
        abort(400, "no files")
    saved = []
    day_dir = UPLOADS_DIR / datetime.now().strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)

    for f in files:
        original = f.filename or "arquivo"
        safe = sanitize_filename(original)
        ext = "".join(Path(safe).suffixes) or ""
        base_no_ext = Path(safe).stem
        short = uuid.uuid4().hex[:8]
        new_name = f"{base_no_ext}-{short}{ext}"
        f.save(day_dir / new_name)

        size = (day_dir / new_name).stat().st_size
        item = {
            "id": uuid.uuid4().hex,
            "display_name": original,
            "path": f"/uploads/{day_dir.name}/{new_name}",
            "type": "video" if ext.lower() in (".mp4",".mov",".mkv",".webm") else ("image" if ext.lower() in (".png",".jpg",".jpeg",".gif",".webp") else "file"),
            "size": size,
            "uploaded_at": now_utc_iso()
        }
        DB_UPLOADS["items"].append(item)
        saved.append(item)

    _save(PATH_UPLOADS, DB_UPLOADS)
    return jsonify({"saved": saved})

@app.get("/uploads/<path:subpath>")
def serve_upload(subpath):
    # segurança simples: só servir dentro da pasta uploads
    full = (UPLOADS_DIR / subpath).resolve()
    if not str(full).startswith(str(UPLOADS_DIR)):
        abort(404)
    return send_from_directory(full.parent, full.name)

@app.get("/api/v1/admin/playlist/<code>")
def admin_get_playlist(code):
    _check_admin()
    return jsonify({"items": DB_PLAYLISTS.get(code, [])})

@app.post("/api/v1/admin/playlist/<code>")
def admin_set_playlist(code):
    _check_admin()
    data = request.get_json(force=True)
    items = data.get("items") or []
    # validação simples
    cleaned = []
    for it in items:
        t = it.get("type")
        if t not in ("video","image","rss"): continue
        obj = {"type": t}
        if "path" in it: obj["path"] = it["path"]
        if "url" in it:  obj["url"] = it["url"]
        if t != "video":
            dur = int(it.get("duration") or 10)
            obj["duration"] = max(1, dur)
        cleaned.append(obj)

    DB_PLAYLISTS[code] = cleaned
    _save(PATH_PLAYLISTS, DB_PLAYLISTS)
    return jsonify({"ok": True})

# ──────────────────────────────────────────────────────────────────────────────
# ENDPOINT DO PLAYER
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/api/v1/config")
def player_config():
    code = (request.args.get("code") or "").strip()
    t = DB_TERMINALS.get(code)
    if not t:
        return jsonify({"status":"not_found"}), 404

    # licença / trial
    today = datetime.now(timezone.utc).date()
    trial_until = datetime.fromisoformat(t.get("trial_until")+"T00:00:00+00:00").date() if t.get("trial_until") else None
    status = "ok"
    if trial_until and today > trial_until:
        status = "trial_expired"

    cfg = {
        "brand": BRAND,
        "config_version": 1,
        "layout": DEFAULT_LAYOUT,
        "playlist": DB_PLAYLISTS.get(code, []),
        "poll_seconds": DEFAULT_POLL_SECONDS,
        "status": status,
        "terminal": {"code": code, "name": t.get("name")},
        "updated_at": now_utc_iso(),
        "trial_until": t.get("trial_until")
    }
    return jsonify(cfg)

@app.get("/api/v1/ping")
def ping():
    return jsonify({"ok": True, "ts": now_utc_iso()})

# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
