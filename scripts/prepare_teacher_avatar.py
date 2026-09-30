"""Prepare the generated teacher portrait for LiveTalking's one-frame Wav2Lip avatar.

The crop coordinates are measured for web/assets/teacher-avatar.png only.
Run again if that source image changes.
"""

from pathlib import Path
import pickle

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "web" / "assets" / "teacher-avatar.png"
TARGET = ROOT / "data" / "avatars" / "teacher-tutor"
COORDS = (70, 305, 170, 355)  # y1, y2, x1, x2 on the 512 x 768 frame


def main():
    with Image.open(SOURCE) as source:
        frame = source.convert("RGB").resize((512, 768), Image.Resampling.LANCZOS)
    y1, y2, x1, x2 = COORDS
    face = frame.crop((x1, y1, x2, y2)).resize((256, 256), Image.Resampling.LANCZOS)
    full_dir = TARGET / "full_imgs"
    face_dir = TARGET / "face_imgs"
    full_dir.mkdir(parents=True, exist_ok=True)
    face_dir.mkdir(parents=True, exist_ok=True)
    frame.save(full_dir / "00000000.png")
    face.save(face_dir / "00000000.png")
    with (TARGET / "coords.pkl").open("wb") as output:
        pickle.dump([COORDS], output)


if __name__ == "__main__":
    main()
