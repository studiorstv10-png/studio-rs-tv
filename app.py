import os, json, uuid, pathlib
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify, send_from_directory, make_response, Response

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = os.path.join(os.getcwd(), "uploads")
app.config["DATA_FOLDER"]   = os.path.join(os.getcwd(), "data")
app.config["SECRET_KEY"]    = os.environ.get("PANEL_SECRET", "studio-rs-tv-secret")

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["DATA_FOLDER"],   exist_ok=True)

DATA_FILE = os.path.join(app.config["DATA_FOLDER"], "data.json")
DEFAULT_BRAND = {"name": "Studio RS TV", "primary_color": "#0d1b2a", "logo": None}

def _now_iso(): return datetime.now(timezone.utc).isoformat()

def load_db():
    if not os.path.exists(DATA_FILE):
        db = {
            "brand": DEFAULT_BRAND,
            "terminals": {},
            "admin_password": os.environ.get("ADMIN_PASSWORD", "admin123"),
            "poll_seconds": 60,
            "trial_days": 15
        }
        save_db(db); return db
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(db):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)

def require_login(req): return req.cookies.get("srs_auth") == "ok"

# ---------------------- PAINEL (HTML embutido)
PANEL_HTML = r"""<!doctype html>
<html lang="pt-BR"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Studio RS TV — Painel</title>
<style>
:root{--bg:#0b1220;--card:#101828;--muted:#a8b3cf;--ok:#2563eb;--okh:#1e4fd1}
*{box-sizing:border-box}body{margin:0;background:#0b1220;color:#e6e9f4;font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial}
.wrap{max-width:1150px;margin:32px auto;padding:0 16px}
h1{margin:0 0 16px;font-size:22px}
.card{background:#101828;border-radius:12px;padding:16px;margin:12px 0;box-shadow:0 1px 0 #0005}
.row{display:flex;gap:12px;flex-wrap:wrap}.col{flex:1;min-width:300px}
label{display:block;font-size:12px;color:#a8b3cf;margin:6px 0 6px}
input,select,button{width:100%;padding:10px 12px;border-radius:10px;border:1px solid #232d43;background:#0e1628;color:#e6e9f4}
button{background:var(--ok);border:0;font-weight:600;cursor:pointer}button:hover{background:var(--okh)}
.small{font-size:12px;color:#a8b3cf}
.list{max-height:250px;overflow:auto;border:1px dashed #232d43;border-radius:10px;padding:8px}
.item{padding:8px;border-radius:8px;display:flex;align-items:center;gap:10px;background:#0f1a2d;margin:6px 0;cursor:pointer}
.item:hover{background:#132243}.badge{padding:2px 8px;border-radius:30px;font-size:11px;background:#16233b;color:#bcd}
.hidden{display:none}.preview{background:#0c1426;border:1px solid #1b2438;border-radius:10px;padding:10px}
.kv{display:flex;gap:10px;align-items:center}.kv>div{flex:1}hr{border:none;border-top:1px solid #1b2438;margin:16px 0}
</style></head><body>
<div class="wrap">
  <h1 id="brandTitle">Studio RS TV — Painel</h1>
  <div class="card" id="cardLogin">
    <div class="row">
      <div class="col"><label>Senha de administrador</label><input id="inPwd" type="password" placeholder="admin123"/></div>
      <div class="col" style="max-width:220px"><label>&nbsp;</label><button id="btLogin">Entrar</button></div>
    </div>
    <div class="small">Senha padrão: <b>admin123</b> (troque em <code>ADMIN_PASSWORD</code>).</div>
  </div>

  <div id="app" class="hidden">
    <div class="card">
      <h3>Terminais</h3>
      <div class="row">
        <div class="col"><label>Código</label><input id="tCode" placeholder="BOX-0001"/></div>
        <div class="col"><label>Nome visível</label><input id="tName" placeholder="AÇOUGUE 02"/></div>
        <div class="col"><label>Grupo (opcional)</label><input id="tGroup" placeholder="MATRIZ"/></div>
        <div class="col" style="max-width:220px"><label>&nbsp;</label><button id="btCreate">Criar</button></div>
      </div><hr/>
      <div class="row">
        <div class="col"><label>Todos os terminais</label><div id="listTerms" class="list"></div>
          <div class="small">Clique em um terminal para editar a playlist.</div></div>
        <div class="col"><label>Uploads (clique para inserir)</label><div id="listUploads" class="list"></div>
          <div class="kv"><div><input id="filePick" type="file"/></div><div style="max-width:200px"><button id="btSendFile">Enviar</button></div></div>
        </div>
      </div>
    </div>

    <div class="card">
      <h3>Playlist do terminal selecionado</h3>
      <div class="row">
        <div class="col" style="max-width:220px"><label>Tipo</label>
          <select id="selType"><option value="video">Vídeo</option><option value="image">Imagem</option><option value="rss">RSS</option></select></div>
        <div class="col"><label>URL / arquivo</label><input id="inURL" placeholder="/uploads/arquivo.mp4 ou https://..."/></div>
        <div class="col" style="max-width:220px"><label>Duração (s) — imagem/RSS</label><input id="inDur" type="number" min="1" value="10"/></div>
        <div class="col" style="max-width:220px"><label>&nbsp;</label><button id="btAdd">Adicionar</button></div>
      </div>
      <div class="row">
        <div class="col"><label>Itens</label><div id="listPL" class="list"></div>
          <div class="small" id="saveMsg" style="margin-top:8px"></div>
          <div style="margin-top:10px;max-width:220px"><button id="btSave">Salvar Playlist</button></div>
        </div>
        <div class="col"><label>Preview</label>
          <div class="preview">
            <div id="pvImg" class="hidden"><img id="pvImgTag" style="max-width:100%"/></div>
            <div id="pvVid" class="hidden"><video id="pvVidTag" style="max-width:100%" controls></video></div>
            <div id="pvRss" class="hidden small">Prévia RSS: <span id="pvRssTxt"></span></div>
          </div>
        </div>
      </div>
    </div>

    <div class="card">
      <h3>Marca (opcional)</h3>
      <div class="row">
        <div class="col"><label>Nome</label><input id="brandName" value="Studio RS TV"/></div>
        <div class="col" style="max-width:220px"><label>Cor primária</label><input id="brandColor" value="#0d1b2a"/></div>
        <div class="col"><label>URL do logo (PNG fundo branco)</label><input id="brandLogo" placeholder="https://.../logo.png"/></div>
        <div class="col" style="max-width:220px"><label>&nbsp;</label><button id="btBrand">Salvar marca</button></div>
      </div>
    </div>
  </div>
</div>
<script>
const $=s=>document.querySelector(s);const api=(m,u,b)=>fetch(u,{method:m,headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});
let currentCode=null,playlist=[];
$("#btLogin").onclick=async()=>{const r=await api("POST","/api/v1/login",{password:$("#inPwd").value.trim()});const j=await r.json();
 if(!j.ok){alert(j.error||"Erro de login");return;}$("#cardLogin").classList.add("hidden");$("#app").classList.remove("hidden");await refreshBrand(j.brand);await refreshTerms();await refreshUploads();};
async function refreshBrand(br){if(!br){const r=await fetch("/api/v1/admin/brand");br=(await r.json()).brand;}
 $("#brandTitle").innerText=(br?.name||"Studio RS TV")+" — Painel";$("#brandName").value=br?.name||"Studio RS TV";$("#brandColor").value=br?.primary_color||"#0d1b2a";$("#brandLogo").value=br?.logo||"";}
$("#btBrand").onclick=async()=>{const body={name:$("#brandName").value,primary_color:$("#brandColor").value,logo:$("#brandLogo").value||null};
 const r=await api("POST","/api/v1/admin/brand",body);const j=await r.json();if(j.ok){await refreshBrand(j.brand);alert("Marca salva.");}else alert("Erro ao salvar marca");};
async function refreshTerms(){const r=await fetch("/api/v1/admin/terminals");const j=await r.json();const box=$("#listTerms");box.innerHTML="";
 (j.terminals||[]).sort((a,b)=>a.code.localeCompare(b.code)).forEach(t=>{const d=document.createElement("div");d.className="item";
 d.innerHTML=`<div class="badge">${t.code}</div><div>${t.name||""}</div><div class="small" style="margin-left:auto">${t.items} itens</div>`;
 d.onclick=()=>selectTerminal(t.code,t.name);box.append(d);});}
$("#btCreate").onclick=async()=>{const body={code:$("#tCode").value.trim(),name:$("#tName").value.trim(),group:$("#tGroup").value.trim()};
 const r=await api("POST","/api/v1/admin/terminals",body);const j=await r.json();if(!j.ok){alert(j.error||"Erro ao criar");return;}await refreshTerms();alert("Criado com sucesso.");};
async function refreshUploads(){const r=await fetch("/api/v1/uploads");const j=await r.json();const box=$("#listUploads");box.innerHTML="";
 (j.files||[]).reverse().forEach(u=>{const ext=u.split(".").pop().toLowerCase();const kind=(["mp4","mov","mkv","webm"].includes(ext)?"video":(["png","jpg","jpeg","webp"].includes(ext)?"image":"file"));
 const it=document.createElement("div");it.className="item";it.innerHTML=`<div class="badge">${kind}</div><div class="small">${u}</div>`;
 it.onclick=()=>{$("#inURL").value=u;if(kind==="image"){ $("#selType").value="image";showPreview("image",u);} if(kind==="video"){ $("#selType").value="video";showPreview("video",u);} };box.append(it);});}
$("#btSendFile").onclick=async()=>{const f=$("#filePick").files[0];if(!f){alert("Escolha um arquivo");return;}const fd=new FormData();fd.append("file",f);
 const r=await fetch("/api/v1/upload",{method:"POST",body:fd});const j=await r.json();if(!j.ok){alert("Falha no upload");return;}$("#filePick").value="";await refreshUploads();$("#inURL").value=j.url;};
async function selectTerminal(code,name){currentCode=code;const r=await fetch(`/api/v1/admin/playlist?code=${encodeURIComponent(code)}`);const j=await r.json();
 playlist=j.items||[];drawPL();$("#saveMsg").innerText=`Editando: ${code} • ${name}`;}
function drawPL(){const box=$("#listPL");box.innerHTML="";playlist.forEach((it,idx)=>{const n=document.createElement("div");n.className="item";
 const dur=(it.type==="video")?"":` • ${it.duration||10}s`;n.innerHTML=`<div class="badge">${it.type}</div><div class="small" style="flex:1">${it.url}${dur}</div>
 <button style="max-width:90px" onclick="rmItem(${idx})">remover</button>`;
 n.onclick=e=>{if(e.target.tagName==="BUTTON")return;$("#selType").value=it.type;$("#inURL").value=it.url;$("#inDur").value=it.duration||10;showPreview(it.type,it.url);};box.append(n);});}
window.rmItem=(idx)=>{playlist.splice(idx,1);drawPL();};
$("#btAdd").onclick=()=>{const type=$("#selType").value;const url=$("#inURL").value.trim();let dur=parseInt($("#inDur").value||"10",10);
 if(!url){alert("Informe a URL / escolha um upload");return;} if(type!=="video") dur=Math.max(dur,1);
 playlist.push(type==="video"?{type,url}:{type,url,duration:dur});drawPL();showPreview(type,url);};
$("#btSave").onclick=async()=>{if(!currentCode){alert("Selecione um terminal na lista.");return;}
 const r=await api("POST","/api/v1/admin/playlist",{code:currentCode,items:playlist});const j=await r.json();
 if(j.ok){$("#saveMsg").innerText="Playlist salva. O player atualiza no próximo poll.";} else alert(j.error||"Erro ao salvar");};
function showPreview(type,url){$("#pvImg").classList.add("hidden");$("#pvVid").classList.add("hidden");$("#pvRss").classList.add("hidden");
 if(type==="image"){ $("#pvImgTag").src=url; $("#pvImg").classList.remove("hidden");}
 else if(type==="video"){ $("#pvVidTag").src=url; $("#pvVid").classList.remove("hidden");}
 else{ $("#pvRssTxt").innerText=url; $("#pvRss").classList.remove("hidden");}}
</script></body></html>"""

@app.get("/")
def panel():
    return Response(PANEL_HTML, mimetype="text/html")

# ---------------------- API
@app.post("/api/v1/login")
def api_login():
    data = request.get_json(silent=True) or {}
    pwd  = (data.get("password") or "").strip()
    db   = load_db()
    if pwd != db.get("admin_password"):
        return jsonify({"ok": False, "error": "Senha inválida"}), 401
    resp = make_response(jsonify({"ok": True, "brand": db.get("brand", DEFAULT_BRAND)}))
    resp.set_cookie("srs_auth", "ok", expires=datetime.now(timezone.utc)+timedelta(hours=12),
                    httponly=True, samesite="Lax")
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
    db["brand"] = {
        "name": data.get("name", DEFAULT_BRAND["name"]),
        "primary_color": data.get("primary_color", DEFAULT_BRAND["primary_color"]),
        "logo": data.get("logo")
    }
    save_db(db); return jsonify({"ok": True, "brand": db["brand"]})

@app.get("/api/v1/admin/terminals")
def list_terminals():
    if not require_login(request): return jsonify({"ok": False, "error": "auth"}), 401
    db = load_db()
    out = []
    for code, t in db["terminals"].items():
        out.append({
            "code": code, "name": t.get("name"), "group": t.get("group"),
            "updated_at": t.get("updated_at"), "items": len(t.get("playlist", []))
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
    save_db(db); return jsonify({"ok": True})

@app.get("/api/v1/uploads")
def list_uploads():
    if not require_login(request): return jsonify({"ok": False, "error": "auth"}), 401
    files = []
    for p in sorted(pathlib.Path(app.config["UPLOAD_FOLDER"]).glob("*")):
        if p.is_file(): files.append(f"/uploads/{p.name}")
    return jsonify({"ok": True, "files": files})

@app.post("/api/v1/upload")
def upload_file():
    if not require_login(request): return jsonify({"ok": False, "error": "auth"}), 401
    f = request.files.get("file")
    if not f: return jsonify({"ok": False, "error": "sem arquivo"}), 400
    ext = pathlib.Path(f.filename).suffix.lower()
    safe = uuid.uuid4().hex + ext
    f.save(os.path.join(app.config["UPLOAD_FOLDER"], safe))
    return jsonify({"ok": True, "url": f"/uploads/{safe}"})

@app.get("/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

@app.post("/api/v1/admin/playlist")
def save_playlist():
    if not require_login(request): return jsonify({"ok": False, "error": "auth"}), 401
    data = request.get_json(silent=True) or {}
    code = data.get("code"); items= data.get("items", [])
    db   = load_db()
    if code not in db["terminals"]:
        return jsonify({"ok": False, "error": "terminal não existe"}), 404
    norm = []
    for it in items:
        typ = it.get("type"); url = it.get("url"); dur = int(it.get("duration", 0) or 0)
        if typ not in ("video","image","rss") or not url: continue
        out={"type":typ,"url":url}
        if typ!="video": out["duration"]=max(dur,1)
        norm.append(out)
    db["terminals"][code]["playlist"]=norm
    db["terminals"][code]["updated_at"]=_now_iso()
    save_db(db); return jsonify({"ok": True})

@app.get("/api/v1/admin/playlist")
def load_playlist():
    if not require_login(request): return jsonify({"ok": False, "error": "auth"}), 401
    code = request.args.get("code"); db= load_db()
    pl = db["terminals"].get(code,{}).get("playlist",[])
    return jsonify({"ok": True, "items": pl})

@app.get("/api/v1/config")
def player_config():
    code = request.args.get("code"); db = load_db()
    t = db["terminals"].get(code)
    if not t: return jsonify({"ok": False, "error": "terminal não encontrado"}), 404
    brand = db.get("brand", DEFAULT_BRAND)
    return jsonify({
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
    })

@app.get("/api/v1/ping")
def ping(): return jsonify({"ok": True, "ts": _now_iso()})

@app.get("/favicon.ico")
def fav(): return ("", 204)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=False)
