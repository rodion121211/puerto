from flask import Flask, send_file
from threading import Thread
import os

app = Flask('')

@app.route('/')
def home():
    return "ativo"

@app.route('/status')
def status():
    return {"status": "online", "bot": "MXP VADOS", "system": "active"}

# ✅ Rota para download do arquivo diretamente da raiz
@app.route('/download/<filename>')
def download_file(filename):
    file_path = os.path.join(os.getcwd(), filename)  # Busca na raiz do projeto
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    return {"error": "Arquivo não encontrado"}, 404

def run():
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()
    print(f"🌐 Keep Alive server iniciado na porta {os.getenv('PORT', 5000)}")
