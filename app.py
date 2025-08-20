import os
from datetime import datetime
from flask import Flask, render_template, jsonify, request

# Pastas padrão do Flask
app = Flask(__name__, static_folder="static", template_folder="templates")


def get_branding():
    """
    Lê as variáveis de ambiente e devolve um dicionário com a marca.
    Se algo não estiver definido no Render, usa os defaults abaixo.
    """
    return {
        "name": os.getenv("BRAND_NAME", "Studio RS TV"),
        "primary_color": os.getenv("BRAND_PRIMARY", "#0d1b2a"),  # azul marinho
        "logo": os.getenv("BRAND_LOGO", "/static/logo.png"),     # coloque seu logo em static/logo.png OU informe uma URL
        "support_wa": os.getenv("SUPPORT_WA", "https://wa.me/5512999999999"),
    }


@app.route("/")
def index():
    brand = get_branding()
    return render_template("index.html", brand=brand)


# ---------- Endpoints simples p/ o player testar ----------
@app.route("/api/v1/ping")
def ping():
    return jsonify({"ok": True, "ts": datetime.utcnow().isoformat() + "Z"})


@app.route("/api/v1/config")
def config():
    """
    Exemplo de resposta de configuração para o app Android:
    - code: código do terminal (opcional)
    - playlist_url: onde o player baixa/conferre a playlist
    - refresh_minutes: frequência de atualização
    """
    code = request.args.get("code", "").strip()

    # Monte aqui lógica real por 'code' quando quiser.
    # Por enquanto devolvemos uma config padrão.
    cfg = {
        "ok": True,
        "code": code or "DEMO",
        "playlist_url": os.getenv("PLAYLIST_URL", "https://example.com/playlist.json"),
        "refresh_minutes": int(os.getenv("REFRESH_MINUTES", "10")),
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }
    return jsonify(cfg)


@app.route("/healthz")
def healthz():
    return "ok", 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=True)
