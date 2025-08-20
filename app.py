from flask import request, jsonify
from datetime import datetime
import os, os.path

def _is_image(path: str) -> bool:
    return os.path.splitext((path or "").lower())[1] in (".png", ".jpg", ".jpeg", ".gif", ".webp")

def _is_video(path: str) -> bool:
    return os.path.splitext((path or "").lower())[1] in (".mp4", ".mov", ".mkv", ".webm")

def _abs_url(u: str) -> str:
    if u.startswith("http://") or u.startswith("https://"):
        return u
    if not u.startswith("/"):
        u = "/" + u
    return request.url_root.rstrip("/") + u

@app.get("/api/v1/config")
def api_config():
    code = (request.args.get("code") or "").strip()
    if not code:
        return jsonify({"ok": False, "error": "missing code"}), 400

    # >>> Traga aqui a SUA playlist já salva para esse code (lista de dicts)
    raw_playlist = load_playlist_for(code)  # use sua função atual

    normalized = []
    for item in raw_playlist:
        url = (item.get("url") or "").strip()
        t = (item.get("type") or "").strip().lower()
        dur = item.get("duration", 0) or 0

        if not t:
            t = "image" if _is_image(url) else "video"

        if t == "video":
            dur = 0  # vídeo: sempre toca até o fim
        elif t == "image":
            if not isinstance(dur, int) or dur <= 0:
                dur = int(os.getenv("IMAGE_DURATION_SECONDS", "10"))

        normalized.append({
            "type": t,
            "url": _abs_url(url),
            "duration": int(dur)
        })

    return jsonify({
        "ok": True,
        "code": code,
        "campaign": current_campaign_name_for(code),  # opcional
        "playlist": normalized,
        "refresh_minutes": int(os.getenv("REFRESH_MINUTES", "10")),
        "updated_at": datetime.utcnow().isoformat() + "Z"
    })
