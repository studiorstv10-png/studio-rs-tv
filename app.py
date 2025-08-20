# --- IMPORTS no topo do arquivo (garanta que tem estes) ---
from flask import Flask, request, jsonify, render_template, url_for
from datetime import datetime
import os

# --- HELPERS: cole estes helpers em qualquer lugar acima das rotas ---
def _is_image(path: str) -> bool:
    ext = os.path.splitext(path.lower())[1]
    return ext in (".png", ".jpg", ".jpeg", ".gif", ".webp")

def _is_video(path: str) -> bool:
    ext = os.path.splitext(path.lower())[1]
    return ext in (".mp4", ".mov", ".mkv", ".webm")

def _abs_url(u: str) -> str:
    # Se já é absoluta, retorna como está
    if u.startswith("http://") or u.startswith("https://"):
        return u
    # Garante barra inicial
    if not u.startswith("/"):
        u = "/" + u
    # Monta absoluta com o host atual
    return request.url_root.rstrip("/") + u

# Se você já tem essa função, mantenha; senão, deixa genérica:
def current_campaign_name_for(code: str) -> str | None:
    # TODO: se você guarda o nome da campanha em algum lugar, retorne aqui.
    # Por ora, None está ok.
    return None

# Se você já carrega a playlist de outro lugar, mantenha e ignore esse stub.
def load_playlist_for(code: str) -> list[dict]:
    """
    Retorne aqui a playlist RAW que você já monta hoje (lista de dicts com url/type/duration).
    Se você já tem essa lista pronta numa variável, basta retornar ela.
    """
    # EXEMPLO (remova se já tiver sua própria leitura):
    return []

# --- ROTA DE CONFIG: SUBSTITUA A SUA POR ESTA COMPLETA ---
@app.get("/api/v1/config")
def api_config():
    code = (request.args.get("code") or "").strip()
    if not code:
        return jsonify({"ok": False, "error": "missing code"}), 400

    # Pegue a sua playlist "crua" (a mesma que você está retornando hoje)
    raw_playlist = load_playlist_for(code)

    # Se você já montava self.playlist em outra variável, troque aqui:
    # raw_playlist = self.playlist_que_voce_ja_tem

    normalized = []
    for item in raw_playlist:
        u = (item.get("url") or "").strip()
        t = (item.get("type") or "").strip().lower()
        dur = item.get("duration", 0) or 0

        # Se não veio type, infere por extensão
        if not t:
            t = "image" if _is_image(u) else "video"

        # Garante duração pra imagens
        if t == "image" and (not isinstance(dur, int) or dur <= 0):
            dur = int(os.getenv("IMAGE_DURATION_SECONDS", "10"))

        normalized.append({
            "type": t,
            "url": _abs_url(u),
            "duration": int(dur)
        })

    return jsonify({
        "ok": True,
        "code": code,
        "campaign": current_campaign_name_for(code),
        "playlist": normalized,
        "refresh_minutes": int(os.getenv("REFRESH_MINUTES", "10")),
        "updated_at": datetime.utcnow().isoformat() + "Z"
    })
