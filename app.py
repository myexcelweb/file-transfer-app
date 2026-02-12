# pyright: reportOptionalMemberAccess=false
from flask import Flask, render_template, request, send_file, jsonify, send_from_directory
import os
import random
import string
import logging
from datetime import datetime, timedelta
from pathlib import Path
import threading
import time
import zipfile
from io import BytesIO
from werkzeug.utils import secure_filename

app = Flask(__name__)

# ────────────────────────────────────────────────
#  CONFIGURATION
# ────────────────────────────────────────────────

UPLOAD_FOLDER = "uploads"
MAX_TOTAL_SIZE_BYTES = 100 * 1024 * 1024      # 100 MB total
MAX_SINGLE_FILE_SIZE_BYTES = 80 * 1024 * 1024  # prevent one huge file

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_TOTAL_SIZE_BYTES

# Ensure upload folder exists
Path(UPLOAD_FOLDER).mkdir(parents=True, exist_ok=True)

# ────────────────────────────────────────────────
#  LOGGING
# ────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────
#  STARTUP CLEANUP – aggressive cleanup of old files
# ────────────────────────────────────────────────

def startup_cleanup():
    MAX_STARTUP_AGE_MIN = 30
    count = 0
    now = time.time()
    for path in Path(UPLOAD_FOLDER).iterdir():
        if path.is_file():
            age_min = (now - path.stat().st_mtime) / 60
            if age_min > MAX_STARTUP_AGE_MIN:
                try:
                    path.unlink()
                    count += 1
                    logger.info(f"Startup deleted old file: {path.name} ({age_min:.1f} min old)")
                except Exception as e:
                    logger.error(f"Startup delete failed {path.name}: {e}")
    if count:
        logger.info(f"Startup cleanup removed {count} old files")

startup_cleanup()

# ────────────────────────────────────────────────
#  IN-MEMORY STORE (still used, but not the only truth)
# ────────────────────────────────────────────────

file_store = {}  # code → {"files": [...], "timestamp": datetime}

def generate_code(length: int = 6) -> str:
    return ''.join(random.choices(string.digits, k=length))

def get_human_size(size_bytes: int | float) -> str:
    size: float = float(size_bytes)
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"

def get_file_type(filename: str) -> str:
    ext = Path(filename).suffix.lstrip('.')
    return ext.upper() if ext else "FILE"

# ────────────────────────────────────────────────
#  STRONG BACKGROUND CLEANUP – disk-first + unknown files
# ────────────────────────────────────────────────

def cleanup_old_files():
    EXPIRATION_SECONDS = 15 * 60          # 15 minutes
    CHECK_INTERVAL_SECONDS = 60           # check every 1 minute

    while True:
        try:
            now = time.time()
            upload_path = Path(UPLOAD_FOLDER)

            if not upload_path.exists():
                time.sleep(CHECK_INTERVAL_SECONDS)
                continue

            deleted_expired = 0
            deleted_unknown = 0

            for path in upload_path.iterdir():
                if not path.is_file():
                    continue

                age_seconds = now - path.stat().st_mtime

                # Delete expired files (based on disk timestamp)
                if age_seconds > EXPIRATION_SECONDS:
                    try:
                        path.unlink()
                        deleted_expired += 1
                        logger.info(f"Deleted expired file: {path.name} (age: {age_seconds//60:.0f} min)")
                    except Exception as e:
                        logger.error(f"Failed to delete expired {path.name}: {e}")

                # Delete unknown/orphan files (not matching 6digits_ pattern)
                elif not (path.name[:6].isdigit() and path.name[6] == '_'):
                    try:
                        path.unlink()
                        deleted_unknown += 1
                        logger.info(f"Deleted unknown/orphan file: {path.name}")
                    except Exception as e:
                        logger.error(f"Failed to delete unknown {path.name}: {e}")

            if deleted_expired or deleted_unknown:
                logger.info(
                    f"Cleanup: removed {deleted_expired} expired + {deleted_unknown} unknown files"
                )

            # Also clean memory store (optional but good hygiene)
            expired_codes = []
            for code, data in list(file_store.items()):
                ts = data.get("timestamp")
                if ts and (datetime.now() - ts).total_seconds() > EXPIRATION_SECONDS:
                    expired_codes.append(code)

            for code in expired_codes:
                del file_store[code]
                logger.debug(f"Removed expired code from memory: {code}")

        except Exception as e:
            logger.error(f"Cleanup thread error: {e}")

        time.sleep(CHECK_INTERVAL_SECONDS)

# Start cleanup thread
threading.Thread(target=cleanup_old_files, daemon=True).start()

# ────────────────────────────────────────────────
#  ROUTES
# ────────────────────────────────────────────────

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        files = request.files.getlist("file")
        if not files or all(not f.filename.strip() for f in files):
            return render_template("index.html", error="No files selected")

        code = generate_code()
        uploaded_files = []
        total_size = 0

        for file in files:
            if not file or not file.filename:
                continue

            original_name = file.filename
            safe_name = secure_filename(original_name)
            stored_name = f"{code}_{safe_name}"

            path = Path(UPLOAD_FOLDER) / stored_name
            file.save(path)

            file_size = path.stat().st_size
            total_size += file_size

            if total_size > MAX_TOTAL_SIZE_BYTES:
                for f in uploaded_files:
                    (Path(UPLOAD_FOLDER) / f["filename"]).unlink(missing_ok=True)
                path.unlink(missing_ok=True)
                return render_template("index.html", error="Total size exceeds 100 MB limit")

            if file_size > MAX_SINGLE_FILE_SIZE_BYTES:
                path.unlink(missing_ok=True)
                return render_template("index.html", error="Single file too large (max ~80 MB)")

            uploaded_files.append({
                "filename": stored_name,
                "original_name": original_name,
                "size": get_human_size(file_size),
                "type": get_file_type(original_name)
            })

        if not uploaded_files:
            return render_template("index.html", error="No valid files uploaded")

        file_store[code] = {
            "files": uploaded_files,
            "timestamp": datetime.now()
        }

        base = request.url_root.rstrip("/")
        share_url = f"{base}/d/{code}"

        logger.info(f"New upload – code: {code} – files: {len(uploaded_files)}")

        return render_template(
            "index.html",
            code=code,
            files=uploaded_files,
            share_url=share_url
        )

    return render_template("index.html")


@app.route("/d/<code>")
@app.route("/download", methods=["POST"])
def download_page(code: str | None = None):
    if code is None and request.method == "POST":
        code = request.form.get("code", "").strip()

    if not code or code not in file_store:
        return render_template("download.html", error="Invalid or expired code")

    data = file_store[code]
    files = data["files"]

    base = request.url_root.rstrip("/")
    share_url = f"{base}/d/{code}"

    return render_template(
        "download.html",
        code=code,
        files=files,
        share_url=share_url
    )


@app.route("/get_file/<code>/<int:index>")
def get_file(code: str, index: int):
    if code not in file_store:
        return "Not found", 404

    files = file_store[code].get("files", [])
    if not (0 <= index < len(files)):
        return "Invalid file index", 404

    info = files[index]
    return send_from_directory(
        UPLOAD_FOLDER,
        info["filename"],
        as_attachment=True,
        download_name=info["original_name"]
    )


@app.route("/get_all_files/<code>")
def get_all_files(code: str):
    if code not in file_store:
        return "Not found", 404

    files = file_store[code].get("files", [])

    if len(files) == 1:
        info = files[0]
        return send_from_directory(
            UPLOAD_FOLDER,
            info["filename"],
            as_attachment=True,
            download_name=info["original_name"]
        )

    memory = BytesIO()
    with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as zf:
        for info in files:
            path = Path(UPLOAD_FOLDER) / info["filename"]
            if path.is_file():
                zf.write(path, info["original_name"])

    memory.seek(0)

    return send_file(
        memory,
        as_attachment=True,
        download_name=f"files_{code}.zip",
        mimetype="application/zip"
    )


@app.route("/api/check/<code>")
def api_check(code: str):
    if code not in file_store:
        return jsonify({"valid": False, "expired": True, "remaining_seconds": 0})

    ts = file_store[code].get("timestamp")
    if not ts:
        return jsonify({"valid": False, "expired": True, "remaining_seconds": 0})

    remaining = (timedelta(minutes=15) - (datetime.now() - ts)).total_seconds()
    if remaining <= 0:
        return jsonify({"valid": False, "expired": True, "remaining_seconds": 0})

    return jsonify({
        "valid": True,
        "expired": False,
        "remaining_seconds": int(remaining),
        "minutes": int(remaining // 60),
        "seconds": int(remaining % 60)
    })


@app.route("/static/<path:filename>")
def static_files(filename: str):
    return send_from_directory("static", filename)


# ────────────────────────────────────────────────
#  ENTRY POINT
# ────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)