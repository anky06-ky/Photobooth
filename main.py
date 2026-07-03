import math
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

try:
    import mediapipe as mp
    from mediapipe.tasks.python import vision
except ImportError:
    mp = None
    vision = None

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None


WINDOW_NAME = "Puzzle Cam Photobooth"
CANVAS_W = 1280
CANVAS_H = 720
SIDEBAR_X = 1000
CAMERA_RECT = (18, 62, 960, 620)
PHOTO_DIR = Path("photos")
STRIP_PATH = PHOTO_DIR / "puzzlecam_strip.png"
AUTO_NEXT_DELAY = 1.4
LIKE_SAVE_HOLD_SECONDS = 0.35
TARGET_PHOTO_COUNT = 3


@dataclass(eq=False)
class Piece:
    image: np.ndarray
    correct_x: int
    correct_y: int
    x: int
    y: int
    size: int
    placed: bool = False


@dataclass
class LandmarkPoint:
    x: float
    y: float
    z: float = 0.0


class PuzzleCamApp:
    def __init__(self):
        self.cap = self.open_capture()
        self.frame = None
        self.display = np.zeros((CANVAS_H, CANVAS_W, 3), dtype=np.uint8)
        self.mode = "camera"
        self.status = "Starting"
        self.gesture = "No hand"
        self.toast = ""
        self.toast_until = 0
        self.countdown_start = None
        self.cooldown_until = 0
        self.capture_box = self.default_capture_box()
        self.captured_photo = None
        self.pieces = []
        self.drag_piece = None
        self.drag_offset = (0, 0)
        self.drag_start_pos = (0, 0)
        self.dragging_by_mouse = False
        self.complete = False
        self.photos = []
        self.last_save = 0
        self.saved_current_photo = False
        self.next_camera_at = 0
        self.clear_session_on_next_camera = False
        self.like_hold_since = None
        self.like_cooldown_until = 0
        self.last_pinch = False
        self.hand_landmarks = None
        self.smoothed_hand_landmarks = None
        self.hand_running_mode = "image"
        self.last_hand_timestamp_ms = 0
        self.gesture_candidate = None
        self.gesture_candidate_since = 0
        self.stable_gesture = "No hand"
        self.frame_index = 0
        self.yolo_model = None
        self.yolo_names = {}
        self.yolo_gesture = None
        self.yolo_gesture_point = None
        self.yolo_gesture_until = 0
        self.yolo_box = None
        self.yolo_box_until = 0
        self.yolo_status = "YOLO off"

        self.face_detector = self.load_face_detector()
        self.load_yolo_model()
        self.hand_landmarker = None
        self.hand_connections = []
        if mp is not None:
            model_path = Path("models") / "hand_landmarker.task"
            if model_path.exists():
                self.hand_landmarker = self.create_hand_landmarker(model_path)
                self.hand_connections = vision.HandLandmarksConnections.HAND_CONNECTIONS

    def open_capture(self):
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            return cap

        sample = Path("mau.mp4")
        if sample.exists():
            cap = cv2.VideoCapture(str(sample))
            if cap.isOpened():
                return cap

        raise RuntimeError("Cannot open webcam or mau.mp4 fallback.")

    def create_hand_landmarker(self, model_path):
        base_options = mp.tasks.BaseOptions(model_asset_path=str(model_path))
        common_options = {
            "base_options": base_options,
            "num_hands": 1,
            "min_hand_detection_confidence": 0.7,
            "min_hand_presence_confidence": 0.7,
            "min_tracking_confidence": 0.72,
        }

        try:
            options = vision.HandLandmarkerOptions(
                **common_options,
                running_mode=vision.RunningMode.VIDEO,
            )
            self.hand_running_mode = "video"
            return vision.HandLandmarker.create_from_options(options)
        except Exception:
            options = vision.HandLandmarkerOptions(
                **common_options,
                running_mode=vision.RunningMode.IMAGE,
            )
            self.hand_running_mode = "image"
            return vision.HandLandmarker.create_from_options(options)

    def load_face_detector(self):
        path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        detector = cv2.CascadeClassifier(str(path))
        return detector if not detector.empty() else None

    def load_yolo_model(self):
        if YOLO is None:
            return

        custom_hand_model = Path("models") / "yolo_hand.pt"
        default_model = Path("models") / "yolo11n.pt"
        configured_model = os.environ.get("YOLO_MODEL")
        model_path = Path(configured_model) if configured_model else custom_hand_model if custom_hand_model.exists() else default_model

        try:
            self.yolo_model = YOLO(str(model_path)) if model_path.exists() else YOLO("yolo11n.pt")
            self.yolo_names = getattr(self.yolo_model, "names", {}) or {}
            self.yolo_status = "YOLO on"
        except Exception as exc:
            self.yolo_model = None
            self.yolo_status = f"YOLO error: {exc.__class__.__name__}"

    def default_capture_box(self):
        vx, vy, vw, vh = CAMERA_RECT
        side = int(min(vw, vh) * 0.62)
        return (vx + (vw - side) // 2, vy + (vh - side) // 2, side, side)

    def show_toast(self, text, seconds=2.2):
        self.toast = text
        self.toast_until = time.time() + seconds

    def run(self):
        cv2.namedWindow(WINDOW_NAME)
        cv2.setMouseCallback(WINDOW_NAME, self.on_mouse)

        while True:
            ok, frame = self.cap.read()
            if not ok:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self.cap.read()
                if not ok:
                    break

            self.frame = cv2.flip(frame, 1)
            self.frame_index += 1
            self.update_yolo_detection()
            self.update_hand_tracking()
            self.update_countdown()
            self.update_auto_next_capture()
            self.draw()

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            self.handle_key(key)

        self.cap.release()
        if self.hand_landmarker is not None:
            self.hand_landmarker.close()
        cv2.destroyAllWindows()

    def handle_key(self, key):
        if key == ord(" "):
            if self.mode == "camera":
                self.start_countdown()
        elif key == ord("c"):
            self.reset_to_camera()
        elif key == ord("r"):
            if self.mode == "puzzle" and self.pieces:
                self.shuffle_pieces()
            else:
                self.reset_to_camera()
        elif key == ord("s"):
            self.save_completed_photo()
        elif key == ord("d"):
            self.create_photo_strip()

    def reset_to_camera(self, clear_session=False):
        self.mode = "camera"
        self.status = "Live"
        self.countdown_start = None
        self.captured_photo = None
        self.pieces = []
        self.drag_piece = None
        self.drag_start_pos = (0, 0)
        self.complete = False
        self.saved_current_photo = False
        self.next_camera_at = 0
        self.clear_session_on_next_camera = False
        self.like_hold_since = None
        self.like_cooldown_until = 0
        self.last_pinch = False
        if clear_session:
            self.photos = []

    def camera_to_screen(self, point):
        vx, vy, vw, vh = CAMERA_RECT
        h, w = self.frame.shape[:2]
        return int(vx + point[0] / w * vw), int(vy + point[1] / h * vh)

    def normalized_to_screen(self, landmark):
        vx, vy, vw, vh = CAMERA_RECT
        return int(vx + landmark.x * vw), int(vy + landmark.y * vh)

    def update_hand_tracking(self):
        self.hand_landmarks = None
        self.gesture = "Keyboard/mouse"
        if self.hand_landmarker is None:
            self.gesture = self.yolo_gesture or self.gesture
            self.handle_yolo_gesture_actions()
            return

        rgb = cv2.cvtColor(self.frame, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        if self.hand_running_mode == "video":
            timestamp_ms = int(time.monotonic() * 1000)
            timestamp_ms = max(timestamp_ms, self.last_hand_timestamp_ms + 1)
            self.last_hand_timestamp_ms = timestamp_ms
            results = self.hand_landmarker.detect_for_video(image, timestamp_ms)
        else:
            results = self.hand_landmarker.detect(image)

        if not results.hand_landmarks:
            self.smoothed_hand_landmarks = None
            self.gesture = self.yolo_gesture or "No hand"
            if self.yolo_gesture:
                self.handle_yolo_gesture_actions()
                return
            self.handle_like_save(False)
            self.handle_pinch(False, None)
            return

        self.hand_landmarks = self.smooth_landmarks(results.hand_landmarks[0])
        raw_gesture = self.recognize_gesture(self.hand_landmarks)
        self.gesture = self.get_stable_gesture(raw_gesture)
        pinch_point = self.get_pinch_point(self.hand_landmarks)
        self.handle_gesture_actions(pinch_point)

    def update_yolo_detection(self):
        now = time.time()
        if now > self.yolo_gesture_until:
            self.yolo_gesture = None
            self.yolo_gesture_point = None
        if now > self.yolo_box_until:
            self.yolo_box = None
        if self.yolo_model is None:
            return
        if self.frame_index % 6 != 0:
            return

        try:
            result = self.yolo_model.predict(self.frame, imgsz=416, conf=0.35, verbose=False)[0]
        except Exception:
            self.yolo_status = "YOLO predict error"
            return

        self.yolo_box = None
        best_person = None
        best_person_area = 0
        best_gesture = None
        best_gesture_conf = 0
        best_gesture_point = None

        for box in result.boxes:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            name = str(self.yolo_names.get(cls_id, cls_id)).lower()
            x1, y1, x2, y2 = [float(value) for value in box.xyxy[0]]
            area = max(0, x2 - x1) * max(0, y2 - y1)

            gesture = self.class_name_to_gesture(name)
            if gesture and conf > best_gesture_conf:
                best_gesture = gesture
                best_gesture_conf = conf
                best_gesture_point = self.camera_to_screen(((x1 + x2) / 2, (y1 + y2) / 2))

            if name == "person" and area > best_person_area:
                best_person = (x1, y1, x2, y2)
                best_person_area = area

        if best_gesture:
            self.yolo_gesture = best_gesture
            self.yolo_gesture_point = best_gesture_point
            self.yolo_gesture_until = now + 0.55
        if best_person and self.mode == "camera":
            self.yolo_box = best_person
            self.yolo_box_until = now + 0.7
            self.update_capture_box_from_person(best_person)

    def class_name_to_gesture(self, name):
        clean = name.replace("-", "_").replace(" ", "_")
        if any(token in clean for token in ["thumb", "thumbs", "like"]):
            return "Like"
        if any(token in clean for token in ["ok", "okay"]):
            return "Like"
        if any(token in clean for token in ["pinch", "pick", "grab"]):
            return "Pinch"
        if any(token in clean for token in ["fist", "closed"]):
            return "Fist"
        if any(token in clean for token in ["open", "palm", "v_sign", "peace"]):
            return "Open / V"
        return None

    def update_capture_box_from_person(self, box):
        x1, y1, x2, y2 = box
        person_w = x2 - x1
        person_h = y2 - y1
        if person_w <= 0 or person_h <= 0:
            return

        head_x1 = x1 - person_w * 0.12
        head_x2 = x2 + person_w * 0.12
        head_y1 = y1 - person_h * 0.04
        head_y2 = y1 + person_h * 0.62
        sx1, sy1 = self.camera_to_screen((head_x1, head_y1))
        sx2, sy2 = self.camera_to_screen((head_x2, head_y2))
        side = int(max(sx2 - sx1, sy2 - sy1, 210))
        cx = (sx1 + sx2) // 2
        cy = (sy1 + sy2) // 2

        vx, vy, vw, vh = CAMERA_RECT
        side = min(side, vw, vh)
        bx = int(np.clip(cx - side // 2, vx, vx + vw - side))
        by = int(np.clip(cy - side // 2, vy, vy + vh - side))
        self.set_capture_box_smooth((bx, by, side, side), alpha=0.28)

    def set_capture_box_smooth(self, target_box, alpha=0.3):
        current = self.capture_box
        self.capture_box = tuple(
            int(round(current[i] * (1 - alpha) + target_box[i] * alpha))
            for i in range(4)
        )

    def smooth_landmarks(self, landmarks, alpha=0.46):
        raw = [
            LandmarkPoint(
                float(point.x),
                float(point.y),
                float(getattr(point, "z", 0.0)),
            )
            for point in landmarks
        ]
        if self.smoothed_hand_landmarks is None or len(self.smoothed_hand_landmarks) != len(raw):
            self.smoothed_hand_landmarks = raw
            return raw

        smoothed = []
        for previous, current in zip(self.smoothed_hand_landmarks, raw):
            smoothed.append(
                LandmarkPoint(
                    previous.x * (1 - alpha) + current.x * alpha,
                    previous.y * (1 - alpha) + current.y * alpha,
                    previous.z * (1 - alpha) + current.z * alpha,
                )
            )
        self.smoothed_hand_landmarks = smoothed
        return smoothed

    def get_stable_gesture(self, raw_gesture):
        now = time.time()
        if raw_gesture != self.gesture_candidate:
            self.gesture_candidate = raw_gesture
            self.gesture_candidate_since = now
        if raw_gesture == self.stable_gesture or now - self.gesture_candidate_since >= 0.12:
            self.stable_gesture = raw_gesture
        return self.stable_gesture

    def recognize_gesture(self, lm):
        pinch = self.normalized_distance(lm[4], lm[8])
        thumb_up = self.thumb_like(lm)
        index = self.finger_extended(lm, 8, 6)
        middle = self.finger_extended(lm, 12, 10)
        ring = self.finger_extended(lm, 16, 14)
        pinky = self.finger_extended(lm, 20, 18)
        extended_count = sum([index, middle, ring, pinky])
        closed = sum(self.normalized_distance(lm[tip], lm[0]) < 0.22 for tip in [8, 12, 16, 20])

        if pinch < 0.065:
            return "Pinch"
        if thumb_up:
            return "Like"
        if closed >= 3 and extended_count == 0:
            return "Fist"
        if extended_count >= 4 or (index and middle and not ring and not pinky):
            return "Open / V"
        return "Tracking"

    def normalized_distance(self, a, b):
        return math.hypot(a.x - b.x, a.y - b.y)

    def finger_extended(self, lm, tip, pip):
        return lm[tip].y < lm[pip].y - 0.02

    def thumb_like(self, lm):
        thumb_tip = lm[4]
        thumb_ip = lm[3]
        thumb_mcp = lm[2]
        wrist = lm[0]
        pinch = self.normalized_distance(lm[4], lm[8])
        if pinch < 0.11:
            return False
        folded_fingers = sum(
            lm[tip].y > lm[pip].y - 0.01
            for tip, pip in [(8, 6), (12, 10), (16, 14), (20, 18)]
        )
        thumb_vertical = thumb_tip.y < thumb_ip.y - 0.035 and thumb_tip.y < thumb_mcp.y - 0.065
        thumb_clear = self.normalized_distance(thumb_tip, wrist) > self.normalized_distance(thumb_mcp, wrist) + 0.08
        return thumb_vertical and thumb_clear and folded_fingers >= 3

    def get_pinch_point(self, lm):
        x = (lm[4].x + lm[8].x) / 2
        y = (lm[4].y + lm[8].y) / 2
        return self.normalized_to_screen(type("Point", (), {"x": x, "y": y})())

    def handle_gesture_actions(self, pinch_point):
        now = time.time()
        if self.gesture == "Open / V" and self.mode == "camera" and now > self.cooldown_until:
            self.start_countdown()
        self.handle_like_save(self.gesture == "Like")
        self.handle_pinch(self.gesture == "Pinch", pinch_point)

    def handle_yolo_gesture_actions(self):
        now = time.time()
        if self.yolo_gesture == "Open / V" and self.mode == "camera" and now > self.cooldown_until:
            self.start_countdown()
        self.handle_like_save(self.yolo_gesture == "Like")
        self.handle_pinch(self.yolo_gesture == "Pinch", self.yolo_gesture_point)

    def handle_like_save(self, is_like):
        now = time.time()
        if not is_like or self.mode != "puzzle":
            self.like_hold_since = None
            return
        if self.drag_piece is not None:
            return
        if self.like_hold_since is None:
            self.like_hold_since = now
        if now - self.like_hold_since < LIKE_SAVE_HOLD_SECONDS or now < self.like_cooldown_until:
            return

        self.like_cooldown_until = now + 1.4
        self.like_hold_since = None
        if not self.complete:
            self.show_toast("Finish the puzzle first")
            return
        self.save_completed_photo()

    def handle_pinch(self, is_pinching, point):
        if self.mode != "puzzle" or point is None:
            self.last_pinch = is_pinching
            return

        if is_pinching:
            if not self.last_pinch:
                piece = self.piece_at(point)
                if piece:
                    self.drag_piece = piece
                    self.drag_offset = (point[0] - piece.x, point[1] - piece.y)
                    self.drag_start_pos = (piece.x, piece.y)
            if self.drag_piece is not None:
                self.drag_piece.x = int(point[0] - self.drag_offset[0])
                self.drag_piece.y = int(point[1] - self.drag_offset[1])
        elif self.last_pinch and self.drag_piece is not None:
            self.release_piece()

        self.last_pinch = is_pinching

    def start_countdown(self):
        if self.countdown_start is not None or self.mode != "camera":
            return
        self.countdown_start = time.time()
        self.cooldown_until = time.time() + 5
        self.status = "Capturing"

    def update_countdown(self):
        if self.countdown_start is None:
            return
        elapsed = time.time() - self.countdown_start
        if elapsed >= 3:
            self.countdown_start = None
            self.capture_photo()

    def capture_photo(self):
        crop = self.crop_capture_box()
        if crop.size == 0:
            self.show_toast("Capture failed")
            return
        board_size = self.board_size()
        self.captured_photo = cv2.resize(crop, (board_size, board_size), interpolation=cv2.INTER_AREA)
        self.saved_current_photo = False
        self.create_puzzle()
        self.mode = "puzzle"
        self.status = "Puzzle"
        self.show_toast("Captured in color")

    def crop_capture_box(self):
        vx, vy, vw, vh = CAMERA_RECT
        x, y, w, h = self.capture_box
        fh, fw = self.frame.shape[:2]
        x1 = max(0, int((x - vx) / vw * fw))
        y1 = max(0, int((y - vy) / vh * fh))
        x2 = min(fw, int((x + w - vx) / vw * fw))
        y2 = min(fh, int((y + h - vy) / vh * fh))
        crop = self.frame[y1:y2, x1:x2]
        side = min(crop.shape[:2]) if crop.size else 0
        if side <= 0:
            return crop
        cy, cx = crop.shape[0] // 2, crop.shape[1] // 2
        half = side // 2
        return crop[cy - half : cy - half + side, cx - half : cx - half + side]

    def board_size(self):
        return 570

    def board_origin(self):
        vx, vy, vw, vh = CAMERA_RECT
        size = self.board_size()
        return vx + (vw - size) // 2, vy + (vh - size) // 2

    def create_puzzle(self):
        self.pieces = []
        size = self.board_size()
        tile = size // 3
        ox, oy = self.board_origin()
        for row in range(3):
            for col in range(3):
                image = self.captured_photo[row * tile : (row + 1) * tile, col * tile : (col + 1) * tile].copy()
                self.pieces.append(
                    Piece(
                        image=image,
                        correct_x=ox + col * tile,
                        correct_y=oy + row * tile,
                        x=ox + col * tile,
                        y=oy + row * tile,
                        size=tile,
                    )
                )
        self.shuffle_pieces()

    def shuffle_pieces(self):
        positions = [(p.correct_x, p.correct_y) for p in self.pieces]
        random.shuffle(positions)
        if all((p.correct_x, p.correct_y) == positions[i] for i, p in enumerate(self.pieces)) and len(positions) > 1:
            positions[0], positions[1] = positions[1], positions[0]
        for piece, (x, y) in zip(self.pieces, positions):
            piece.x = x
            piece.y = y
            piece.placed = False
        self.drag_piece = None
        self.drag_start_pos = (0, 0)
        self.complete = False
        self.status = "Puzzle"
        self.show_toast("Shuffled")

    def piece_at(self, point):
        px, py = point
        for piece in reversed(self.pieces):
            if piece.x <= px <= piece.x + piece.size and piece.y <= py <= piece.y + piece.size:
                return piece
        return None

    def nearest_board_slot(self, point, margin=80):
        px, py = point
        ox, oy = self.board_origin()
        size = self.board_size()
        tile = size // 3
        if px < ox - margin or px > ox + size + margin or py < oy - margin or py > oy + size + margin:
            return None
        col = int(np.clip((px - ox) // tile, 0, 2))
        row = int(np.clip((py - oy) // tile, 0, 2))
        return ox + col * tile, oy + row * tile

    def piece_on_slot(self, slot, exclude=None):
        sx, sy = slot
        for piece in self.pieces:
            if piece is exclude:
                continue
            if abs(piece.x - sx) < 4 and abs(piece.y - sy) < 4:
                return piece
        return None

    def release_piece(self):
        piece = self.drag_piece
        if piece is None:
            return

        center = (piece.x + piece.size // 2, piece.y + piece.size // 2)
        target_slot = self.nearest_board_slot(center)
        if target_slot is None:
            piece.x, piece.y = self.drag_start_pos
        else:
            occupant = self.piece_on_slot(target_slot, exclude=piece)
            if occupant is not None:
                occupant.x, occupant.y = self.drag_start_pos
            piece.x, piece.y = target_slot

        self.drag_piece = None
        self.drag_start_pos = (0, 0)
        self.check_complete()

    def check_complete(self):
        for piece in self.pieces:
            piece.placed = abs(piece.x - piece.correct_x) < 4 and abs(piece.y - piece.correct_y) < 4
        self.complete = all(piece.placed for piece in self.pieces)
        if self.complete:
            self.status = "Complete"
            next_photo = min(len(self.photos) + 1, TARGET_PHOTO_COUNT)
            self.show_toast(f"Photo {next_photo}/{TARGET_PHOTO_COUNT} complete - Like")

    def save_completed_photo(self):
        now = time.time()
        if now - self.last_save < 1.2:
            return
        self.last_save = now
        if self.captured_photo is None:
            self.show_toast("No photo yet")
            return
        if self.saved_current_photo:
            if self.complete:
                if len(self.photos) >= TARGET_PHOTO_COUNT:
                    self.show_toast("Strip already saved")
                else:
                    self.show_toast("Already accepted")
                    self.schedule_next_capture()
            return

        card = self.make_photo_card()
        self.photos.append(card)
        self.saved_current_photo = True

        if len(self.photos) < TARGET_PHOTO_COUNT:
            self.show_toast(f"Accepted {len(self.photos)}/{TARGET_PHOTO_COUNT} - next photo")
            self.schedule_next_capture()
            return

        filename = self.create_photo_strip()
        if filename is None:
            self.photos.pop()
            self.saved_current_photo = False
            return
        self.show_toast(f"Saved strip {filename.name}")
        self.schedule_next_capture(clear_session=True, delay=2.4, status="Strip saved")

    def schedule_next_capture(self, clear_session=False, delay=AUTO_NEXT_DELAY, status="Next photo"):
        self.next_camera_at = time.time() + delay
        self.clear_session_on_next_camera = clear_session
        self.status = status

    def update_auto_next_capture(self):
        if self.next_camera_at and time.time() >= self.next_camera_at:
            clear_session = self.clear_session_on_next_camera
            self.reset_to_camera(clear_session=clear_session)
            if clear_session:
                self.show_toast("Ready for new 3-photo set")
            else:
                self.show_toast(f"Ready for photo {len(self.photos) + 1}/{TARGET_PHOTO_COUNT}")

    def make_photo_card(self):
        card = np.full((360, 270, 3), 248, dtype=np.uint8)
        photo = cv2.resize(self.captured_photo, (230, 230), interpolation=cv2.INTER_AREA)
        card[22:252, 20:250] = photo
        cv2.putText(card, "PUZZLE-CAM", (48, 310), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (25, 22, 20), 2, cv2.LINE_AA)
        cv2.putText(card, time.strftime("%H:%M:%S"), (82, 336), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (25, 22, 20), 1, cv2.LINE_AA)
        return card

    def create_photo_strip(self):
        if len(self.photos) < TARGET_PHOTO_COUNT:
            self.show_toast(f"Need {TARGET_PHOTO_COUNT} photos first")
            return
        PHOTO_DIR.mkdir(exist_ok=True)
        photos = self.photos[:TARGET_PHOTO_COUNT]
        strip = np.full((len(photos) * 380 + 20, 300, 3), 248, dtype=np.uint8)
        for i, photo in enumerate(photos):
            y = 10 + i * 380
            strip[y : y + 360, 15:285] = photo
        now = time.time()
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = PHOTO_DIR / f"puzzlecam_strip_{timestamp}_{int((now % 1) * 1000):03d}.png"
        if cv2.imwrite(str(filename), strip):
            return filename
        self.show_toast("Strip save failed")
        return None

    def on_mouse(self, event, x, y, flags, param):
        if self.mode != "puzzle":
            return
        if event == cv2.EVENT_LBUTTONDOWN:
            piece = self.piece_at((x, y))
            if piece:
                self.drag_piece = piece
                self.drag_offset = (x - piece.x, y - piece.y)
                self.drag_start_pos = (piece.x, piece.y)
                self.dragging_by_mouse = True
        elif event == cv2.EVENT_MOUSEMOVE and self.dragging_by_mouse and self.drag_piece is not None:
            self.drag_piece.x = int(x - self.drag_offset[0])
            self.drag_piece.y = int(y - self.drag_offset[1])
        elif event == cv2.EVENT_LBUTTONUP and self.dragging_by_mouse:
            self.dragging_by_mouse = False
            self.release_piece()

    def draw(self):
        self.display[:] = (23, 20, 22)
        self.draw_header()
        self.draw_sidebar()
        if self.mode == "puzzle":
            self.draw_puzzle()
        else:
            self.draw_camera()
        self.draw_toast()
        cv2.imshow(WINDOW_NAME, self.display)

    def draw_header(self):
        cv2.putText(self.display, "PUZZLE-CAM", (22, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.54, (63, 210, 255), 2, cv2.LINE_AA)
        cv2.putText(self.display, self.status, (760, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (131, 212, 69), 2, cv2.LINE_AA)
        cv2.putText(self.display, self.gesture, (880, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (234, 248, 255), 2, cv2.LINE_AA)
        cv2.putText(self.display, self.yolo_status, (1110, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (115, 216, 255), 1, cv2.LINE_AA)
        cv2.putText(
            self.display,
            "Open/V: capture  Like hand/S: accept photo; 3/3 saves strip  R: shuffle/reset  Q: quit",
            (22, 705),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (189, 179, 169),
            1,
            cv2.LINE_AA,
        )

    def draw_camera(self):
        vx, vy, vw, vh = CAMERA_RECT
        view = cv2.resize(self.frame, (vw, vh), interpolation=cv2.INTER_AREA)
        self.display[vy : vy + vh, vx : vx + vw] = view
        self.update_face_box()
        x, y, w, h = self.capture_box
        cv2.rectangle(self.display, (x, y), (x + w, y + h), (63, 210, 255), 3)
        self.draw_hand()
        if self.hand_landmarker is None:
            cv2.putText(self.display, "MediaPipe model missing: use Space/mouse, or install requirements.txt", (52, 92), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (115, 216, 255), 2, cv2.LINE_AA)
        if self.countdown_start is not None:
            remaining = max(0, 3 - int(time.time() - self.countdown_start))
            cv2.putText(self.display, str(remaining), (vx + vw // 2 - 42, vy + vh // 2 + 58), cv2.FONT_HERSHEY_SIMPLEX, 5.5, (63, 210, 255), 14, cv2.LINE_AA)

    def update_face_box(self):
        if self.yolo_box is not None:
            return
        if self.face_detector is None:
            return
        gray = cv2.cvtColor(self.frame, cv2.COLOR_BGR2GRAY)
        faces = self.face_detector.detectMultiScale(gray, 1.2, 5, minSize=(80, 80))
        if len(faces) == 0:
            return
        x, y, w, h = max(faces, key=lambda face: face[2] * face[3])
        sx, sy = self.camera_to_screen((x, y))
        ex, ey = self.camera_to_screen((x + w, y + h))
        pad_x = int((ex - sx) * 0.62)
        pad_y = int((ey - sy) * 0.75)
        bx = max(CAMERA_RECT[0], sx - pad_x)
        by = max(CAMERA_RECT[1], sy - pad_y)
        bw = min(CAMERA_RECT[0] + CAMERA_RECT[2] - bx, (ex - sx) + pad_x * 2)
        bh = min(CAMERA_RECT[1] + CAMERA_RECT[3] - by, (ey - sy) + pad_y * 2)
        side = max(180, min(max(bw, bh), min(CAMERA_RECT[2], CAMERA_RECT[3])))
        self.set_capture_box_smooth((int(bx), int(by), int(side), int(side)), alpha=0.22)

    def draw_hand(self):
        if self.hand_landmarks is None or not self.hand_connections:
            return
        points = [self.normalized_to_screen(lm) for lm in self.hand_landmarks]
        for connection in self.hand_connections:
            cv2.line(self.display, points[connection.start], points[connection.end], (245, 245, 245), 2, cv2.LINE_AA)
        for point in points:
            cv2.circle(self.display, point, 4, (63, 210, 255), -1, cv2.LINE_AA)

    def draw_puzzle(self):
        vx, vy, vw, vh = CAMERA_RECT
        cv2.rectangle(self.display, (vx, vy), (vx + vw, vy + vh), (10, 10, 10), -1)
        ox, oy = self.board_origin()
        size = self.board_size()
        color = (131, 212, 69) if self.complete else (63, 210, 255)
        cv2.rectangle(self.display, (ox, oy), (ox + size, oy + size), color, 4)

        pieces = list(self.pieces)
        if self.drag_piece in pieces:
            pieces.remove(self.drag_piece)
            pieces.append(self.drag_piece)
        for piece in pieces:
            x, y, s = piece.x, piece.y, piece.size
            x1, y1 = max(0, x), max(0, y)
            x2, y2 = min(CANVAS_W, x + s), min(CANVAS_H, y + s)
            if x2 <= x1 or y2 <= y1:
                continue
            src_x1, src_y1 = x1 - x, y1 - y
            src_x2, src_y2 = src_x1 + (x2 - x1), src_y1 + (y2 - y1)
            self.display[y1:y2, x1:x2] = piece.image[src_y1:src_y2, src_x1:src_x2]
            border = (131, 212, 69) if piece.placed else (235, 235, 235)
            cv2.rectangle(self.display, (x, y), (x + s, y + s), border, 2)

        placed = sum(piece.placed for piece in self.pieces)
        cv2.putText(self.display, f"{placed}/9", (ox + size - 78, oy - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (234, 248, 255), 2, cv2.LINE_AA)
        if self.complete:
            cv2.rectangle(self.display, (ox, oy - 48), (ox + size, oy - 10), (131, 212, 69), -1)
            cv2.putText(self.display, "Rompecabezas completo", (ox + 118, oy - 21), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (7, 21, 13), 2, cv2.LINE_AA)
        self.draw_hand()

    def draw_sidebar(self):
        cv2.rectangle(self.display, (SIDEBAR_X, 0), (CANVAS_W, CANVAS_H), (35, 31, 34), -1)
        cv2.putText(self.display, "TIRA", (SIDEBAR_X + 22, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.56, (63, 210, 255), 2, cv2.LINE_AA)
        cv2.putText(self.display, f"{len(self.photos)}/{TARGET_PHOTO_COUNT}", (CANVAS_W - 82, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.64, (234, 248, 255), 2, cv2.LINE_AA)
        if not self.photos:
            cv2.rectangle(self.display, (SIDEBAR_X + 24, 72), (CANVAS_W - 24, 350), (72, 66, 70), 2)
            cv2.line(self.display, (SIDEBAR_X + 24, 211), (CANVAS_W - 24, 211), (72, 66, 70), 1)
            cv2.line(self.display, (SIDEBAR_X + 140, 72), (SIDEBAR_X + 140, 350), (72, 66, 70), 1)
            return
        y = 58
        for photo in self.photos[:3]:
            thumb = cv2.resize(photo, (180, 240), interpolation=cv2.INTER_AREA)
            x = SIDEBAR_X + 50
            if y + 240 > CANVAS_H - 20:
                break
            self.display[y : y + 240, x : x + 180] = thumb
            y += 216

    def draw_toast(self):
        if not self.toast or time.time() > self.toast_until:
            return
        cv2.rectangle(self.display, (28, 638), (520, 674), (10, 10, 10), -1)
        cv2.putText(self.display, self.toast, (42, 662), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (234, 248, 255), 2, cv2.LINE_AA)


if __name__ == "__main__":
    app = PuzzleCamApp()
    app.run()
