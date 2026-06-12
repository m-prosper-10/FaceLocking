#!/usr/bin/env python3
"""
Download the ArcFace ONNX embedder expected by this project.

Default model:
  InsightFace antelopev2 / glintr100.onnx

Why this default:
  The project already performs detection and 5-point alignment locally, so it
  only needs the recognition ONNX. antelopev2 is the larger InsightFace Python
  model pack from the official v0.7 model-package release and uses the
  ResNet100@Glint360K recognition model, while still exposing the 112x112
  ArcFace-style ONNX input compatible with src/embed.py.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path


INSIGHTFACE_RELEASE_BASE = (
    "https://github.com/deepinsight/insightface/releases/download/v0.7"
)


@dataclass(frozen=True)
class ModelChoice:
    pack: str
    onnx_name: str
    reason: str


MODEL_CHOICES = {
    "buffalo_l": ModelChoice(
        pack="buffalo_l",
        onnx_name="w600k_r50.onnx",
        reason="balanced default: ResNet50@WebFace600K, strong accuracy, CPU practical",
    ),
    "antelopev2": ModelChoice(
        pack="antelopev2",
        onnx_name="glintr100.onnx",
        reason="larger model: ResNet100@Glint360K, heavier CPU cost",
    ),
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    print(f"Downloading: {url}")
    with urllib.request.urlopen(url, timeout=60) as response:
        total_header = response.headers.get("Content-Length")
        total = int(total_header) if total_header else None
        downloaded = 0

        with dest.open("wb") as f:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 / total
                    print(f"\rDownloaded {downloaded / 1048576:.1f} MB ({pct:.1f}%)", end="")
                else:
                    print(f"\rDownloaded {downloaded / 1048576:.1f} MB", end="")
    print()


def find_zip_member(zf: zipfile.ZipFile, onnx_name: str) -> str:
    matches = [name for name in zf.namelist() if Path(name).name == onnx_name]
    if not matches:
        available = "\n".join(
            f"  - {name}" for name in zf.namelist() if name.lower().endswith(".onnx")
        )
        raise FileNotFoundError(
            f"Could not find {onnx_name} in downloaded archive. ONNX files found:\n{available}"
        )
    return matches[0]


def extract_onnx(zip_path: Path, onnx_name: str, output: Path, force: bool) -> None:
    if output.exists() and not force:
        raise FileExistsError(
            f"{output} already exists. Use --force to replace it."
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        member = find_zip_member(zf, onnx_name)
        tmp_output = output.with_suffix(output.suffix + ".tmp")
        with zf.open(member) as src, tmp_output.open("wb") as dst:
            shutil.copyfileobj(src, dst)
        tmp_output.replace(output)


def validate_with_onnxruntime(path: Path) -> None:
    try:
        import onnxruntime as ort
    except ImportError:
        print("onnxruntime is not installed; skipped runtime validation.")
        return

    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    inputs = sess.get_inputs()
    outputs = sess.get_outputs()
    if len(inputs) != 1:
        raise RuntimeError(f"Expected 1 model input, found {len(inputs)}")

    input_shape = inputs[0].shape
    if len(input_shape) != 4:
        raise RuntimeError(f"Expected NCHW image input, got shape {input_shape}")

    channels = input_shape[1]
    height = input_shape[2]
    width = input_shape[3]
    if channels != 3 or height != 112 or width != 112:
        raise RuntimeError(
            f"Expected input shape [N,3,112,112], got {input_shape}"
        )

    print("Validated with onnxruntime:")
    print(f"  input:  {inputs[0].name} {input_shape}")
    print(f"  output: {outputs[0].name} {outputs[0].shape}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pack",
        choices=sorted(MODEL_CHOICES),
        default="antelopev2",
        help="InsightFace model pack to download. Default is the most capable supported choice.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repo_root() / "models" / "embedder_arcface.onnx",
        help="Destination ONNX path.",
    )
    parser.add_argument("--force", action="store_true", help="Replace existing output file.")
    parser.add_argument(
        "--keep-archive",
        action="store_true",
        help="Keep the downloaded zip under models/ after extraction.",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip ONNX Runtime shape validation.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    choice = MODEL_CHOICES[args.pack]
    url = f"{INSIGHTFACE_RELEASE_BASE}/{choice.pack}.zip"
    output = args.output.resolve()

    print(f"Selected model pack: {choice.pack}")
    print(f"Recognition model:   {choice.onnx_name}")
    print(f"Reason:              {choice.reason}")
    print(f"Destination:         {output}")

    with tempfile.TemporaryDirectory() as td:
        archive = Path(td) / f"{choice.pack}.zip"
        download(url, archive)

        if not zipfile.is_zipfile(archive):
            raise RuntimeError(f"Downloaded file is not a valid zip: {archive}")

        extract_onnx(archive, choice.onnx_name, output, args.force)

        if args.keep_archive:
            archive_dest = output.parent / f"{choice.pack}.zip"
            shutil.copy2(archive, archive_dest)
            print(f"Kept archive: {archive_dest}")

    if not args.no_validate:
        validate_with_onnxruntime(output)

    size_mb = output.stat().st_size / 1048576
    print(f"Saved: {output}")
    print(f"Size:  {size_mb:.1f} MB")
    print(f"SHA256: {sha256_file(output)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        raise SystemExit(130)
