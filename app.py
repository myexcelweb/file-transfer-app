# pyright: reportOptionalMemberAccess=false
import os
import random
import string
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, request, send_file, jsonify, send_from_directory, redirect, url_for, session
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='static')
app.secret_key = "super_secret_key_for_session" # Needed for unique usernames

# CONFIGURATION
UPLOAD_FOLDER = "uploads"
ROOM_DURATION_MINS = 30
MAX_TOTAL_SIZE = 100 * 1024 * 1024 
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

Path(UPLOAD_FOLDER).mkdir(parents=True, exist_ok=True)

# In-memory store
room_store = {}

# Names for random username generation
ADJECTIVES = ["Swift", "Brave", "Shiny", "Cool", "Clever", "Happy", "Silver", "Neon"]
ANIMALS = ["Tiger", "Panda", "Fox", "Eagle", "Wolf", "Dolphin", "Lion", "Falcon"]

# ────────────────────────────────────────────────
#  HELPERS
# ────────────────────────────────────────────────

def get_or_create_user():
    """Assigns a unique username to the user's browser session."""
    if 'username' not in session:
        name = f"{random.choice(ADJECTIVES)}-{random.choice(ANIMALS)}-{random.randint(10, 99)}"
        session['username'] = name
    return session['username']

def generate_code(length=6):
    while True:
        code = ''.join(random.choices(string.digits, k=length))
        if code not in room_store: return code

def get_human_size(size_bytes):
    size = float(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0: return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"

def add_history(code, user, action):
    """Adds an event to the room activity log."""
    if code in room_store:
        timestamp = datetime.now().strftime("%I:%M %p")
        room_store[code]['history'].insert(0, {
            "user": user,
            "action": action,
            "time": timestamp
        })

# ────────────────────────────────────────────────
#  CLEANUP THREAD
# ────────────────────────────────────────────────
def cleanup_expired_rooms():
    while True:
        now = datetime.now()
        expired_codes = [c for c, d in room_store.items() if now - d['timestamp'] > timedelta(minutes=ROOM_DURATION_MINS)]
        for code in expired_codes:
            for f in room_store[code]['files']:
                Path(UPLOAD_FOLDER, f['stored_name']).unlink(missing_ok=True)
            del room_store[code]
        time.sleep(60)

threading.Thread(target=cleanup_expired_rooms, daemon=True).start()

# ────────────────────────────────────────────────
#  ROUTES
# ────────────────────────────────────────────────

@app.route("/")
def index():
    user = get_or_create_user() # Assign name on first visit
    error = request.args.get('error')
    return render_template("index.html", error=error, username=user)

@app.route("/create-room", methods=["POST"])
def create_room():
    user = get_or_create_user()
    code = generate_code()
    room_store[code] = {
        "timestamp": datetime.now(),
        "host": user,
        "files": [],
        "history": []
    }
    add_history(code, user, "created the room (Host)")
    return redirect(url_for('room_page', code=code))

@app.route("/join", methods=["POST"])
def join_room():
    code = request.form.get("code", "").strip()
    if code in room_store:
        user = get_or_create_user()
        add_history(code, user, "joined the room")
        return redirect(url_for('room_page', code=code))
    return redirect(url_for('index', error="Room not found"))

@app.route("/room/<code>", methods=["GET", "POST"])
def room_page(code):
    if code not in room_store:
        return redirect(url_for('index', error="Room expired"))

    user = get_or_create_user()
    room = room_store[code]

    if request.method == "POST":
        uploaded_files = request.files.getlist("file")
        for file in uploaded_files:
            if file and file.filename:
                orig = file.filename
                stored = f"{code}_{int(time.time())}_{secure_filename(orig)}"
                path = Path(UPLOAD_FOLDER) / stored
                file.save(path)
                
                file_data = {
                    "original_name": orig,
                    "stored_name": stored,
                    "size": get_human_size(path.stat().st_size),
                    "type": orig.split('.')[-1].upper() if '.' in orig else "FILE",
                    "sender": user
                }
                room["files"].append(file_data)
                add_history(code, user, f"sent: {orig}")
        return redirect(url_for('room_page', code=code))

    return render_template("room.html", 
                           code=code, 
                           files=room["files"], 
                           history=room["history"],
                           host=room["host"],
                           my_username=user,
                           share_url=f"{request.url_root.rstrip('/')}/room/{code}")

@app.route("/download/<code>/<int:index>")
def download_file(code, index):
    if code in room_store and index < len(room_store[code]["files"]):
        user = get_or_create_user()
        file_info = room_store[code]["files"][index]
        add_history(code, user, f"downloaded: {file_info['original_name']}")
        return send_from_directory(UPLOAD_FOLDER, file_info["stored_name"], 
                                   as_attachment=True, download_name=file_info["original_name"])
    return "Not found", 404

@app.route("/api/timer/<code>")
def api_timer(code):
    if code not in room_store: return jsonify({"expired": True})
    rem = (timedelta(minutes=ROOM_DURATION_MINS) - (datetime.now() - room_store[code]["timestamp"])).total_seconds()
    return jsonify({"expired": rem <= 0, "remaining_seconds": int(max(0, rem))})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)