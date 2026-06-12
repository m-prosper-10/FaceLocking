"""
vision_node.py
Simulated Vision Node for Distributed Vision-Control System.
Tracks face and publishes movement commands via MQTT.
Topic: benax/camera/control
"""

import time
import argparse
import cv2
import json
import csv
import numpy as np
import paho.mqtt.client as mqtt
from pathlib import Path
import sys
import base64

# Add src to path if needed
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

# Import Face Locking modules
try:
    from src.camera_utils import open_camera
    from src.haar_5pt import Haar5ptDetector
    from src.recognize import ArcFaceEmbedderONNX, FaceDBMatcher, load_db_npz
    from src.face_locking import FaceLockSystem
except ImportError:
    from camera_utils import open_camera
    from haar_5pt import Haar5ptDetector
    from recognize import ArcFaceEmbedderONNX, FaceDBMatcher, load_db_npz
    from face_locking import FaceLockSystem

# Configuration
DEFAULT_BROKER = "[IP_ADDRESS]" 
PORT = 1883
TEAM_ID = "team313"
TOPIC_CONTROL = "benax/camera/control"
LOG_PATH = ROOT / "logs" / "tracking_log.csv"


def ensure_log_file() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LOG_PATH.exists():
        return

    with open(LOG_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["timestamp", "speaker_id", "confidence", "face_distance", "command"]
        )


def distance_to_confidence(distance: float, threshold: float) -> float:
    confidence = max(0.0, 1.0 - (distance / max(threshold, 1e-6)))
    return min(confidence, 1.0)

class VisionNode:
    def __init__(self, broker, port, target_name, camera_index=None):
        # MQTT Setup
        self.client = mqtt.Client(client_id=f"{TEAM_ID}_vision_node")
        self.client.on_connect = self.on_connect
        self.client.connect(broker, port, 60)
        self.client.loop_start()
        
        # Face Recognition & Locking Setup
        print("Initializing Face Recognition...")
        self.det = Haar5ptDetector(min_size=(70, 70))
        self.embedder = ArcFaceEmbedderONNX(input_size=(112, 112))
        
        # Load Database
        db_path = Path(__file__).parent.parent / "data/db/face_db.npz"
        if not db_path.exists():
            print(f"ERROR: Face DB not found at {db_path}. Run enroll.py first!")
            sys.exit(1)
            
        db = load_db_npz(db_path)
        if target_name not in db:
            print(f"WARNING: Target '{target_name}' not in database. Available: {list(db.keys())}")
        
        self.matcher = FaceDBMatcher(db, dist_thresh=0.60)
        self.system = FaceLockSystem(target_name, self.matcher, self.det)
        
        self.running = True
        self.last_publish_time = 0
        self.mqtt_topic = TOPIC_CONTROL
        self.snapshot_sent = False  # Track if we've sent the face snapshot
        self.track_threshold = self.matcher.dist_thresh
        self.camera_index = camera_index
        ensure_log_file()

    def on_connect(self, client, userdata, flags, rc):
        print(f"Connected to MQTT Broker with result code {rc}")
        
    def publish_control(
        self,
        command,
        confidence=0.0,
        speaker_id="UNKNOWN",
        face_distance=999.0,
        locked=False,
        face_image=None,
    ):
        payload = {
            "command": command,
            "speaker_id": speaker_id,
            "confidence": confidence,
            "face_distance": face_distance,
            "locked": locked,
            "timestamp": time.time()
        }
        
        # Add face image if available
        if face_image is not None:
            _, buffer = cv2.imencode('.jpg', face_image, [cv2.IMWRITE_JPEG_QUALITY, 70])
            payload["face_image"] = base64.b64encode(buffer).decode('utf-8')
        
        self.client.publish(self.mqtt_topic, json.dumps(payload))
        self.log_tracking(payload)
        print(f"Published: {command} (image: {'yes' if face_image is not None else 'no'})")

    def log_tracking(self, payload):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(payload["timestamp"]))
        with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    timestamp,
                    payload["speaker_id"],
                    round(float(payload["confidence"]), 4),
                    round(float(payload["face_distance"]), 4),
                    payload["command"],
                ]
            )

    def run(self):
        cap = cv2.VideoCapture(0) # Use default camera
        if not cap.isOpened():
             cap = cv2.VideoCapture(0)
        
        print(f"Vision Node Started. Tracking target: {self.system.target_name}")
        print(f"Using camera index: {camera_index}")
        print(f"Publishing to {TOPIC_CONTROL}")
        
        while self.running:
            ret, frame = cap.read()
            if not ret: break
            
            # Flip for mirror effect
            frame = cv2.flip(frame, 1)
            H, W = frame.shape[:2]
            
            # Process Frame using FaceLockSystem
            # Note: process_frame now returns (vis_frame, target_face_obj)
            vis, target_match = self.system.process_frame(frame, self.embedder)
            
            command = "SCAN"
            face_crop = None
            face_distance = 999.0
            confidence = 0.0
            speaker_id = "UNKNOWN"
            
            if target_match:
                # Target is found and locked
                f = target_match.face
                face_distance = target_match.distance
                confidence = distance_to_confidence(face_distance, self.track_threshold)
                speaker_id = self.system.target_name
                
                # Extract face crop for dashboard (only if not sent yet)
                if not self.snapshot_sent:
                    x1, y1, x2, y2 = int(f.x1), int(f.y1), int(f.x2), int(f.y2)
                    # Add padding
                    pad = 20
                    x1 = max(0, x1 - pad)
                    y1 = max(0, y1 - pad)
                    x2 = min(W, x2 + pad)
                    y2 = min(H, y2 + pad)
                    face_crop = frame[y1:y2, x1:x2]
                    self.snapshot_sent = True  # Mark as sent
                    print("📸 Face snapshot captured and will be sent")
                
                # Calculate Center
                cx = (f.x1 + f.x2) / 2.0
                cx_norm = cx / W
                
                # Movement logic with a centered deadband mapped to STOP
                if cx_norm < 0.4:
                    command = "LEFT"
                elif cx_norm > 0.6:
                    command = "RIGHT"
                else:
                    command = "STOP"
            else:
                # No face detected - reset snapshot flag
                if self.snapshot_sent:
                    self.snapshot_sent = False
                    print("🔓 Target lost - snapshot flag reset")

                if self.system.lost_frames > self.system.MAX_LOST_FRAMES:
                    command = "OUT_OF_FRAME"
            
            # --- RATE LIMITING (10Hz) ---
            current_time = time.time()
            if current_time - self.last_publish_time >= 0.1:
                is_locked = target_match is not None
                self.publish_control(
                    command,
                    confidence=confidence,
                    speaker_id=speaker_id,
                    face_distance=face_distance,
                    locked=is_locked,
                    face_image=face_crop,
                )
                self.last_publish_time = current_time
            
            cv2.imshow("Vision Node (Locked)", vis)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        
        cap.release()
        cv2.destroyAllWindows()
        self.client.loop_stop()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--broker", type=str, default=DEFAULT_BROKER, help="MQTT Broker Address")
    parser.add_argument("--name", type=str, default="andrew", help="Target name to lock onto")
    parser.add_argument(
        "--camera-index",
        type=int,
        default=None,
        help="Preferred camera index. Falls back to 0,1,2 if not available.",
    )
    args = parser.parse_args()

    node = VisionNode(args.broker, PORT, args.name, camera_index=args.camera_index)
    node.run()
