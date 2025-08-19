
Studio RS TV — Painel (Render-ready)

1) Local:
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1     (Windows PowerShell)
   pip install -r requirements.txt
   setx ADMIN_KEY "admin123"  (Windows)  |  export ADMIN_KEY=admin123 (mac/linux)
   python app.py
   Painel: http://127.0.0.1:8000

2) Render:
   - Build: pip install -r requirements.txt
   - Start: gunicorn app:app --bind 0.0.0.0:$PORT
   - Env: ADMIN_KEY = SUA_SENHA
   - Disk: mount /opt/render/project/src/uploads  (persistente)

3) Endpoints principais:
   GET  /api/v1/ping
   GET  /api/v1/admin/terminals          (header x-admin-key)
   POST /api/v1/admin/terminals          (create)
   DELETE /api/v1/admin/terminals?code=X
   GET/POST /api/v1/admin/branding
   POST /api/v1/admin/upload             (FormData: file=...)
   GET  /api/v1/admin/list_uploads
   GET/POST /api/v1/admin/playlist/<code>

   Público para APK:
   GET  /api/v1/config?code=<TERMINAL>
   GET  /c/<TERMINAL>   (atalho)

4) Uploads:
   - Arraste arquivos na aba "Uploads" → URLs ficam em /uploads/NOME
   - Use essas URLs na playlist (vídeo/imagem)

5) Player:
   - No box, configure apenas o link curto: https://SEU-DOMINIO/c/LOJA-59
   - O player baixa a playlist e toca na ordem.

