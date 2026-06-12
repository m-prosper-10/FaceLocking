# src/camera.py
import cv2
from .camera_utils import open_camera


def main():
    cap, camera_index = open_camera()

    print(f"Camera test using index {camera_index}. Press 'q' to quit.")

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Failed to read frame.")
            break

        cv2.imshow("Camera Test", frame)

        if (cv2.waitKey(1) & 0xFF) == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
