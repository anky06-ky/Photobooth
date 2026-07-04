import base64
import json
import mimetypes
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse


PORT = int(os.environ.get("PORT", "8000"))
HOST = os.environ.get("HOST", "0.0.0.0" if "PORT" in os.environ else "127.0.0.1")
ROOT_DIR = Path(__file__).resolve().parent
WEB_DIR = ROOT_DIR / "web"
MODEL_DIR = ROOT_DIR / "models"
DATA_DIR = ROOT_DIR / "web_data"
DATA_URL_RE = re.compile(r"^data:image/(?P<ext>png|jpeg|jpg);base64,(?P<data>.+)$")
DEVICE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{12,80}$")

mimetypes.add_type("application/manifest+json", ".webmanifest")


def init_storage():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def device_id_from_value(value):
    device_id = value or ""
    if not DEVICE_ID_RE.match(device_id):
        raise ValueError("Missing or invalid device id.")
    return device_id


def device_paths(device_id):
    device_dir = DATA_DIR / "devices" / device_id
    return device_dir, device_dir / "photos", device_dir / "photos.json"


def load_manifest(device_id):
    _, _, manifest_path = device_paths(device_id)
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"next_id": 1, "sessions": []}


def save_manifest(device_id, manifest):
    device_dir, photo_dir, manifest_path = device_paths(device_id)
    device_dir.mkdir(parents=True, exist_ok=True)
    photo_dir.mkdir(parents=True, exist_ok=True)
    temp_path = manifest_path.with_suffix(".tmp")
    temp_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(manifest_path)


def session_response(session, device_id):
    shots = session["shotFilenames"]
    return {
        "id": session["id"],
        "createdAt": session["createdAt"],
        "stripUrl": photo_url(session["stripFilename"], device_id),
        "stripFilename": session["stripFilename"],
        "shots": [photo_url(filename, device_id) for filename in shots],
        "shotFilenames": shots,
    }


def photo_url(filename, device_id):
    return f"/saved/{filename}?device={quote(device_id)}"


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
            self.send_saved_photo(parsed.path.removeprefix("/saved/"), parsed.query)
            return
        if parsed.path.startswith("/models/"):
            self.send_model_file(parsed.path.removeprefix("/models/"))
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
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_saved_photo(self, filename, query):
        try:
            device_id = device_id_from_value(parse_qs(query).get("device", [""])[0])
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)
            return

        safe_name = Path(filename).name
        _, photo_dir, _ = device_paths(device_id)
        target = (photo_dir / safe_name).resolve()
        if not str(target).startswith(str(photo_dir.resolve())) or not target.exists():
            self.send_json({"error": "Not found"}, status=404)
            return
        content_type = mimetypes.guess_type(str(target))[0] or "image/png"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_model_file(self, filename):
        safe_name = Path(filename).name
        target = (MODEL_DIR / safe_name).resolve()
        if not str(target).startswith(str(MODEL_DIR.resolve())) or not target.exists():
            self.send_json({"error": "Not found"}, status=404)
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_photos(self):
        try:
            device_id = self.device_id_from_header()
            manifest = load_manifest(device_id)
            sessions = [session_response(session, device_id) for session in manifest.get("sessions", [])]
            self.send_json({"sessions": sessions})
        except ValueError as exc:
            self.send_json({"error": str(exc)}, status=400)

    def save_photo_session(self):
        try:
            device_id = self.device_id_from_header()
            body = self.read_json_body()
            shots = body.get("shots") or []
            strip = body.get("strip")
            if len(shots) != 3:
                raise ValueError("A session must include exactly 3 different shots.")
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            unique = f"{timestamp}_{int((time.time() % 1) * 1000):03d}"
            shot_filenames = []
            _, photo_dir, _ = device_paths(device_id)
            photo_dir.mkdir(parents=True, exist_ok=True)

            for index, data_url in enumerate(shots, start=1):
                ext, image_bytes = decode_image(data_url)
                filename = f"shot_{unique}_{index}.{ext}"
                (photo_dir / filename).write_bytes(image_bytes)
                shot_filenames.append(filename)

            ext, strip_bytes = decode_image(strip)
            strip_filename = f"strip_{unique}.{ext}"
            (photo_dir / strip_filename).write_bytes(strip_bytes)
            created_at = time.strftime("%Y-%m-%d %H:%M:%S")
            manifest = load_manifest(device_id)
            session_id = int(manifest.get("next_id", 1))
            session = {
                "id": session_id,
                "createdAt": created_at,
                "stripFilename": strip_filename,
                "shotFilenames": shot_filenames,
            }
            manifest["next_id"] = session_id + 1
            manifest.setdefault("sessions", []).insert(0, session)
            save_manifest(device_id, manifest)

            self.send_json(session_response(session, device_id), status=201)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=400)

    def delete_photo_session(self, session_id):
        try:
            device_id = self.device_id_from_header()
            session_id_int = int(session_id)
        except ValueError:
            self.send_json({"error": "Invalid id or device"}, status=400)
            return

        manifest = load_manifest(device_id)
        sessions = manifest.get("sessions", [])
        match_index = next(
            (index for index, session in enumerate(sessions) if int(session.get("id", -1)) == session_id_int),
            None,
        )
        if match_index is None:
            self.send_json({"error": "Not found"}, status=404)
            return

        session = sessions.pop(match_index)
        save_manifest(device_id, manifest)

        filenames = [session["stripFilename"], *session["shotFilenames"]]
        _, photo_dir, _ = device_paths(device_id)
        for filename in filenames:
            target = photo_dir / Path(filename).name
            if target.exists():
                target.unlink()
        self.send_json({"ok": True})

    def device_id_from_header(self):
        return device_id_from_value(self.headers.get("X-Photobooth-Device", ""))

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
    display_host = "127.0.0.1" if HOST == "0.0.0.0" else HOST
    print(f"PhotoBooth web app: http://{display_host}:{PORT}")
    print(f"Data directory: {DATA_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
