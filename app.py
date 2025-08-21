import os, json, re, hashlib, time, uuid
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename

# ---------- Branding ----------
APP_NAME   = os.getenv("BRAND_NAME", "Studio RS TV")
PRIMARY    = os.getenv("BRAND_COLOR", "#0a2458")                 # azul marinho
LOGO_URL   = os.getenv("BRAND_LOGO_URL", "")                    # png branco recomendado
SUPPORT_WA = os.getenv("SUPPORT_WA", "https://wa.me/5512996273989")

# ---------- Paths ----------
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "static/uploads")
DB_PATH    = os.getenv("DB_PATH",    "data/db.json")

ALLOWED_EXT = {".mp4", ".mov", ".mkv", ".webm", ".png", ".jpg", ".jpeg", ".gif", ".webp"}
CODE_RE     = re.compile(r'^([A-Za-z0-9]+)-([0-9]{1,3})$')

app = Flask(__name__, static_folder="static", template_folder="templates")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# ---------- utils ----------
def now_utc(): return datetime.now(timezone.utc)
def iso(dt):   return dt.astimezone(timezone.utc).isoformat()
def parse_iso(s): return datetime.fromisoformat(s.replace("Z","+00:00"))

def norm_client(c): return f"{int(c):03d}" if (c or "").isdigit() else (c or "").strip()
def norm_term(t):   return f"{int(t):02d}" if (t or "").isdigit()   else (t or "").strip()

def split_code(code:str):
    m = CODE_RE.match((code or "").strip())
    if not m: return None, None
    return norm_client(m.group(1)), norm_term(m.group(2))

def _is_image(path:str):
    return os.path.splitext((path or "").lower())[1] in (".png",".jpg",".jpeg",".gif",".webp")

def _abs_url(u:str):
    if not u: return u
    if u.startswith("http://") or u.startswith("https://"): return u
    if not u.startswith("/"): u="/"+u
    return request.url_root.rstrip("/") + u

def sha256_of_file(path:str):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda: f.read(1024*256), b""):
            h.update(chunk)
    return h.hexdigest()

def ensure_db():
    if not os.path.exists(DB_PATH):
        with open(DB_PATH,"w",encoding="utf-8") as f:
            json.dump({"clients": {}, "pairs": {}}, f, ensure_ascii=False, indent=2)

def load_db():
    ensure_db()
    with open(DB_PATH,"r",encoding="utf-8") as f:
        return json.load(f)

def save_db(db:dict):
    tmp=DB_PATH+".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        json.dump(db,f,ensure_ascii=False,indent=2)
    os.replace(tmp,DB_PATH)

def get_branding(): return {"name":APP_NAME,"primary_color":PRIMARY,"logo_url":LOGO_URL}

# ---------- modelo ----------
def ensure_client(db, client_code, name=None, license_days=30):
    c=norm_client(client_code)
    cli=db.setdefault("clients",{}).get(c)
    if not cli:
        exp=now_utc()+timedelta(days=license_days)
        cli={"code":c,"name":name or f"Cliente {c}","license_expires_at":iso(exp),"terminals":{}}
        db["clients"][c]=cli
    else:
        if name: cli["name"]=name
    return cli

def ensure_terms(cli, q):
    for i in range(1,int(q)+1):
        t=norm_term(i)
        cli["terminals"].setdefault(t,{
            "playlist":[],
            "refresh_minutes":10,
            "update_schedule_hours":[6,12,18],      # 06:00 / 12:00 / 18:00
            "config_version":0,
            "last_applied_version":0,
            "last_applied_at":None,
            "last_seen_at":None,
            "commands":[],                           # fila: [{id,type,params,status}]
        })

def license_ok(cli): 
    try: return parse_iso(cli["license_expires_at"]) >= now_utc()
    except: return False

def get_term(db, ccode, tcode):
    cli = db.get("clients",{}).get(norm_client(ccode))
    if not cli: return None, None
    return cli, cli["terminals"].get(norm_term(tcode))

# ---------- views ----------
@app.get("/")
def index():        return render_template("index.html", branding=get_branding(), support_link=SUPPORT_WA)
@app.get("/clients")
def clients():      return render_template("clients.html", branding=get_branding())

# ---------- uploads ----------
@app.post("/upload")
def upload():
    f = request.files.get("file")
    if not f or not f.filename: return jsonify({"ok":False,"error":"empty_filename"}),400
    name=secure_filename(f.filename); ext=os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXT: return jsonify({"ok":False,"error":"ext_not_allowed"}),400
    ts=datetime.now().strftime("%Y%m%d-%H%M%S")
    final=f"{ts}-{name}"; path=os.path.join(UPLOAD_DIR,final); f.save(path)
    rel=f"/static/uploads/{final}"
    return jsonify({"ok":True,"url":rel,"type":"image" if _is_image(rel) else "video"})

@app.get("/api/v1/uploads")
def list_uploads():
    items=[]
    for fname in sorted(os.listdir(UPLOAD_DIR)):
        p=os.path.join(UPLOAD_DIR,fname)
        if not os.path.isfile(p): continue
        ext=os.path.splitext(fname)[1].lower()
        if ext not in ALLOWED_EXT: continue
        items.append({"filename":fname,"url":f"/static/uploads/{fname}","type":"image" if _is_image(fname) else "video"})
    return jsonify({"ok":True,"items":items})

# ---------- clientes/licença ----------
@app.get("/api/v1/clients")
def api_clients():
    db=load_db(); out=[]
    for c,cli in db.get("clients",{}).items():
        out.append({
            "code":cli["code"],"name":cli.get("name"),
            "license_expires_at":cli.get("license_expires_at"),
            "license_ok":license_ok(cli),
            "terminals":sorted(list(cli.get("terminals",{}).keys()))
        })
    out=sorted(out,key=lambda x:x["code"])
    return jsonify({"ok":True,"items":out})

@app.post("/api/v1/client")
def api_upsert_client():
    d=request.get_json(force=True,silent=True) or {}
    code=d.get("client_code"); name=d.get("name"); days=int(d.get("license_days") or 30)
    terms=int(d.get("terminals") or 1)
    if not code: return jsonify({"ok":False,"error":"missing client_code"}),400
    db=load_db(); cli=ensure_client(db,code,name,days); ensure_terms(cli,terms); save_db(db)
    return jsonify({"ok":True,"client":cli})

@app.post("/api/v1/client/<code>/license/extend")
def api_extend_license(code):
    days=int((request.get_json(force=True,silent=True) or {}).get("days") or 15)
    db=load_db(); cli=db.get("clients",{}).get(norm_client(code))
    if not cli: return jsonify({"ok":False,"error":"client_not_found"}),404
    base=max(parse_iso(cli["license_expires_at"]), now_utc())
    cli["license_expires_at"]=iso(base+timedelta(days=days)); save_db(db)
    return jsonify({"ok":True,"license_expires_at":cli["license_expires_at"]})

# ---------- playlist / terminal ----------
def bump_version(term:dict):
    term["config_version"] = int(term.get("config_version") or 0) + 1

@app.post("/api/v1/playlist")
def api_set_playlist():
    d=request.get_json(force=True,silent=True) or {}
    code=(d.get("code") or "").strip()
    client,term = split_code(code)
    if not client:
        client = norm_client(d.get("client_code") or "")
        term   = norm_term(d.get("term") or "1")
    if not client or not term: return jsonify({"ok":False,"error":"invalid code"}),400

    db=load_db(); cli, t = get_term(db,client,term)
    if not cli or not t: return jsonify({"ok":False,"error":"client_or_terminal_not_found"}),404

    t["playlist"] = d.get("items") or []
    if "refresh_minutes" in d: t["refresh_minutes"]=int(d["refresh_minutes"])
    if "update_schedule_hours" in d: t["update_schedule_hours"] = list(map(int, d["update_schedule_hours"]))
    bump_version(t); save_db(db)
    return jsonify({"ok":True,"code":f"{client}-{term}","config_version":t["config_version"]})

@app.post("/api/v1/terminal/settings")
def api_term_settings():
    d=request.get_json(force=True,silent=True) or {}
    client=norm_client(d.get("client_code") or ""); term=norm_term(d.get("term") or "1")
    if not client or not term: return jsonify({"ok":False,"error":"invalid"}),400
    db=load_db(); cli, t = get_term(db,client,term)
    if not cli or not t: return jsonify({"ok":False,"error":"not_found"}),404
    if "refresh_minutes" in d: t["refresh_minutes"]=int(d["refresh_minutes"])
    if "update_schedule_hours" in d: t["update_schedule_hours"]=list(map(int,d["update_schedule_hours"]))
    save_db(db); return jsonify({"ok":True})

# ---------- comandos para o box ----------
def queue_cmd(t:dict, cmd_type:str, params:dict=None):
    t.setdefault("commands",[])
    t["commands"].append({
        "id": str(uuid.uuid4()),
        "type": cmd_type,
        "params": params or {},
        "status": "pending",
        "issued_at": iso(now_utc())
    })

@app.post("/api/v1/terminal/command")
def api_command():
    d=request.get_json(force=True,silent=True) or {}
    client=norm_client(d.get("client_code") or ""); term=norm_term(d.get("term") or "1")
    cmd = d.get("type") or "restart_player"
    db=load_db(); cli,t=get_term(db,client,term)
    if not cli or not t: return jsonify({"ok":False,"error":"not_found"}),404
    queue_cmd(t, cmd, d.get("params") or {})
    save_db(db); return jsonify({"ok":True})

# ---------- pareamento ----------
@app.post("/api/v1/pair/request")
def pair_request():
    d=request.get_json(force=True,silent=True) or {}
    device_id=(d.get("device_id") or str(uuid.uuid4()))[:64]
    code=str(uuid.uuid4())[:6].upper()
    db=load_db()
    db.setdefault("pairs",{})[code]={
        "device_id": device_id,
        "created_at": iso(now_utc()),
        "expires_at": iso(now_utc()+timedelta(minutes=10)),
        "attached_code": None
    }
    save_db(db)
    return jsonify({"ok":True,"pair_code":code})

@app.post("/api/v1/pair/attach")
def pair_attach():
    d=request.get_json(force=True,silent=True) or {}
    pair_code=(d.get("pair_code") or "").strip().upper()
    client=norm_client(d.get("client_code") or ""); term=norm_term(d.get("term") or "1")
    db=load_db(); pair=db.get("pairs",{}).get(pair_code)
    if not pair: return jsonify({"ok":False,"error":"invalid_pair"}),404
    if parse_iso(pair["expires_at"]) < now_utc(): return jsonify({"ok":False,"error":"expired"}),400
    pair["attached_code"]=f"{client}-{term}"; save_db(db)
    return jsonify({"ok":True})

@app.get("/api/v1/pair/poll")
def pair_poll():
    code=(request.args.get("pair_code") or "").strip().upper()
    db=load_db(); pair=db.get("pairs",{}).get(code)
    if not pair: return jsonify({"ok":False,"error":"invalid_pair"}),404
    if pair.get("attached_code"):
        return jsonify({"ok":True,"code":pair["attached_code"]})
    return jsonify({"ok":True,"waiting":True})

# ---------- heartbeat & ack ----------
@app.post("/api/v1/heartbeat")
def heartbeat():
    """
    body: { "code":"001-01", "player_version":"x", "state":"playing|downloading|idle",
            "applied_version": 3 }
    server returns pending commands.
    """
    d=request.get_json(force=True,silent=True) or {}
    client,term=split_code(d.get("code") or "")
    if not client: return jsonify({"ok":False,"error":"invalid"}),400
    db=load_db(); cli,t=get_term(db,client,term)
    if not cli or not t: return jsonify({"ok":False,"error":"not_found"}),404
    t["last_seen_at"]=iso(now_utc())
    if "applied_version" in d:
        t["last_applied_version"]=int(d["applied_version"])
        t["last_applied_at"]=iso(now_utc())
    cmds=[c for c in t.get("commands",[]) if c.get("status")=="pending"]
    for c in cmds: c["status"]="sent"
    save_db(db)
    return jsonify({"ok":True,"commands":cmds})

@app.post("/api/v1/ack_config")
def ack_config():
    d=request.get_json(force=True,silent=True) or {}
    client,term=split_code(d.get("code") or "")
    version=int(d.get("config_version") or 0)
    db=load_db(); cli,t=get_term(db,client,term)
    if not cli or not t: return jsonify({"ok":False,"error":"not_found"}),404
    t["last_applied_version"]=version; t["last_applied_at"]=iso(now_utc()); save_db(db)
    return jsonify({"ok":True})

# ---------- config para o APK ----------
@app.get("/api/v1/config")
def api_config():
    code=(request.args.get("code") or "").strip()
    client,term=split_code(code)
    if not client: return jsonify({"ok":False,"error":"invalid_code_format"}),400
    db=load_db(); cli,t=get_term(db,client,term)
    if not cli or not t: return jsonify({"ok":False,"error":"not_found"}),404
    if not license_ok(cli): return jsonify({"ok":False,"error":"license_expired"}),403

    items=[]; assets=[]
    for it in t.get("playlist") or []:
        url=(it.get("url") or "").strip()
        typ=(it.get("type") or "").strip().lower()
        dur=int(it.get("duration") or 0)
        if not typ: typ="image" if _is_image(url) else "video"
        if typ=="image" and dur<=0: dur=int(os.getenv("IMAGE_DURATION_SECONDS","10"))
        if typ=="video": dur=0
        absurl=_abs_url(url)
        items.append({"type":typ,"url":absurl,"duration":dur})
        assets.append({"url":absurl,"type":typ})

    cfg={
        "ok": True,
        "code": f"{client}-{term}",
        "campaign": f"{cli.get('name','Cliente')} — {client}-{term}",
        "playlist": items,
        "assets": assets,
        "config_version": int(t.get("config_version") or 0),
        "refresh_minutes": int(t.get("refresh_minutes") or 10),
        "update_schedule_hours": t.get("update_schedule_hours") or [6,12,18],
        "updated_at": iso(now_utc())
    }
    return jsonify(cfg)

# ---------- health ----------
@app.get("/api/v1/ping")
def ping(): return jsonify({"ok":True,"ts":iso(now_utc())})

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","8000")), debug=True)
