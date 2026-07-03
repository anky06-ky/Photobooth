import base64
import json
import mimetypes
import re
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


HOST = "127.0.0.1"
PORT = 8000
ROOT_DIR = Path(__file__).resolve().parent
WEB_DIR = ROOT_DIR / "web"
DATA_DIR = ROOT_DIR / "web_data"
PHOTO_DIR = DATA_DIR / "photos"
DB_PATH = DATA_DIR / "photobooth.sqlite3"
DATA_URL_RE = re.compile(r"^data:image/(?P<ext>png|jpeg|jpg);base64,(?P<data>.+)$")


def init_storage():
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS photo_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                strip_filename TEXT NOT NULL,
                shot_filenames TEXT NOT NULL
            )
            """
        )
        conn.commit()


def db_rows():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, created_at, strip_filename, shot_filenames
            FROM photo_sessions
            ORDER BY id DESC
            """
        ).fetchall()
    return rows


def photo_url(filename):
    return f"/saved/{filename}"


def decode_image(data_url):
    match = DATA_URL_RE.match(data_url or "")
    if not match:
        raise ValueError("Expected a PNG or JPG data URL.")
    ext = "jpg" if match.group("ext") in ("jpg", "jpeg") else "png"
    return ext, base64.b64decode(match.group("data"), validate=True)


def safe_static_path(path):
    if path == "/":
        path = "/index.html"
    relative = path.lstrip("/")
    target = (WEB_DIR / relative).resolve()
    if not str(target).startswith(str(WEB_DIR.resolve())):
        return None
    return target


class PhotoBoothHandler(BaseHTTPRequestHandler):
    server_version = "PhotoBoothWeb/1.0"

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/photos":
            self.send_photos()
            return
        if parsed.path.startswith("/saved/"):
            self.send_saved_photo(parsed.path.removeprefix("/saved/"))
            return
        self.send_static(parsed.path)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/photos":
            self.save_photo_session()
            return
        self.send_json({"error": "Not found"}, status=404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/photos/"):
            session_id = parsed.path.removeprefix("/api/photos/")
            self.delete_photo_session(session_id)
            return
        self.send_json({"error": "Not found"}, status=404)

    def send_static(self, path):
        target = safe_static_path(path)
        if target is None or not target.exists() or not target.is_file():
            self.send_json({"error": "Not found"}, status=404)
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_saved_photo(self, filename):
        safe_name = Path(filename).name
        target = (PHOTO_DIR / safe_name).resolve()
        if not str(target).startswith(str(PHOTO_DIR.resolve())) or not target.exists():
            self.send_json({"error": "Not found"}, status=404)
            return
        content_type = mimetypes.guess_type(str(target))[0] or "image/png"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_photos(self):
        rows = db_rows()
        sessions = []
        for row in rows:
            shots = json.loads(row["shot_filenames"])
            sessions.append(
                {
                    "id": row["id"],
                    "createdAt": row["created_at"],
                    "stripUrl": photo_url(row["strip_filename"]),
                    "stripFilename": row["strip_filename"],
                    "shots": [photo_url(filename) for filename in shots],
                    "shotFilenames": shots,
                }
            )
        self.send_json({"sessions": sessions})

    def save_photo_session(self):
        try:
            body = self.read_json_body()
            shots = body.get("shots") or []
            strip = body.get("strip")
            if len(shots) != 3:
                raise ValueError("A session must include exactly 3 different shots.")
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            unique = f"{timestamp}_{int((time.time() % 1) * 1000):03d}"
            shot_filenames = []

            for index, data_url in enumerate(shots, start=1):
                ext, image_bytes = decode_image(data_url)
                filename = f"shot_{unique}_{index}.{ext}"
                (PHOTO_DIR / filename).write_bytes(image_bytes)
                shot_filenames.append(filename)

            ext, strip_bytes = decode_image(strip)
            strip_filename = f"strip_{unique}.{ext}"
            (PHOTO_DIR / strip_filename).write_bytes(strip_bytes)
            created_at = time.strftime("%Y-%m-%d %H:%M:%S")

            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO photo_sessions (created_at, strip_filename, shot_filenames)
                    VALUES (?, ?, ?)
                    """,
                    (created_at, strip_filename, json.dumps(shot_filenames)),
                )
                conn.commit()

            self.send_json(
                {
                    "id": cursor.lastrowid,
                    "createdAt": created_at,
                    "stripUrl": photo_url(strip_filename),
                    "stripFilename": strip_filename,
                    "shots": [photo_url(filename) for filename in shot_filenames],
                    "shotFilenames": shot_filenames,
                },
                status=201,
            )
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=400)

    def delete_photo_session(self, session_id):
        try:
            session_id_int = int(session_id)
        except ValueError:
            self.send_json({"error": "Invalid id"}, status=400)
            return

        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT strip_filename, shot_filenames FROM photo_sessions WHERE id = ?",
                (session_id_int,),
            ).fetchone()
            if row is None:
                self.send_json({"error": "Not found"}, status=404)
                return
            conn.execute("DELETE FROM photo_sessions WHERE id = ?", (session_id_int,))
            conn.commit()

        filenames = [row["strip_filename"], *json.loads(row["shot_filenames"])]
        for filename in filenames:
            target = PHOTO_DIR / Path(filename).name
            if target.exists():
                target.unlink()
        self.send_json({"ok": True})

    def read_json_body(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            return {}
        return json.loads(self.rfile.read(content_length).decode("utf-8"))

    def send_json(self, payload, status=200):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        print(f"[web] {self.address_string()} - {fmt % args}")


def main():
    init_storage()
    server = ThreadingHTTPServer((HOST, PORT), PhotoBoothHandler)
    print(f"PhotoBooth web app: http://{HOST}:{PORT}")
    print(f"Database: {DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
