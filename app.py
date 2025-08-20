# app.py
import os
from flask import Flask, render_template, jsonify, request, send_from_directory

app = Flask(__name__, static_folder="static", template_folder="templates")

def get_branding():
    return {
        "name": os.getenv("BRAND_NAME", "Studio RS TV"),
        "primary_color": os.getenv("BRAND_PRIMARY", "#0d1b2a"),
        "logo": os.getenv("BRAND_LOGO", "/static/logo.png"),
        "support_wa": os.getenv("SUPPORT_WA", "https://wa.me/5512999999999"),
    }

@app.route("/")
def index():
    brand = get_branding()
    return render_template("index.html", brand=brand)
