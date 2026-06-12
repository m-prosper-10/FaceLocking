#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple


ROOT = Path(__file__).resolve().parents[1]
PYTHON_REQUIREMENTS = ROOT / "requirements.txt"
BACKEND_PACKAGE = ROOT / "backend" / "package.json"
MODEL_PATH = ROOT / "models" / "embedder_arcface.onnx"
NODE_MODULES = ROOT / "backend" / "node_modules"

ARDUINO_REQUIRED_HEADERS = (
    "ESP8266WiFi.h",
    "PubSubClient.h",
    "Servo.h",
)

PYTHON_IMPORT_MAP = {
    "opencv-contrib-python": "cv2",
    "paho-mqtt": "paho.mqtt.client",
}

ARDUINO_LIBRARY_HINTS = {
    "ESP8266WiFi.h": "ESP8266 core for Arduino",
    "PubSubClient.h": "PubSubClient",
    "Servo.h": "Servo",
}


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def load_requirements(path: Path) -> List[str]:
    requirements = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pkg = line.split("==", 1)[0].split("<", 1)[0].split(">", 1)[0].strip()
        requirements.append(pkg)
    return requirements


def import_name_for_requirement(requirement: str) -> str:
    return PYTHON_IMPORT_MAP.get(requirement, requirement.replace("-", "_"))


def check_python_dependencies() -> List[CheckResult]:
    results = []
    for requirement in load_requirements(PYTHON_REQUIREMENTS):
        module_name = import_name_for_requirement(requirement)
        try:
            importlib.import_module(module_name)
            results.append(CheckResult(requirement, True, f"import ok: {module_name}"))
        except Exception as exc:
            results.append(CheckResult(requirement, False, f"import failed: {module_name} ({exc})"))
    return results


def load_node_dependencies(path: Path) -> List[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return sorted(data.get("dependencies", {}).keys())


def check_node_dependencies() -> List[CheckResult]:
    results = []
    for dep in load_node_dependencies(BACKEND_PACKAGE):
        dep_path = NODE_MODULES / dep
        if dep_path.exists():
            results.append(CheckResult(dep, True, f"installed in {dep_path}"))
        else:
            results.append(CheckResult(dep, False, f"missing from {NODE_MODULES}"))
    return results


def run_command(cmd: Iterable[str]) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False, "command not found"

    if proc.returncode == 0:
        return True, proc.stdout.strip() or "ok"

    stderr = proc.stderr.strip()
    stdout = proc.stdout.strip()
    detail = stderr or stdout or f"exit code {proc.returncode}"
    return False, detail


def find_arduino_library_dirs() -> List[Path]:
    home = Path.home()
    candidates = [
        home / "Arduino" / "libraries",
        home / "Documents" / "Arduino" / "libraries",
        home / ".arduino15" / "libraries",
        home / ".local" / "share" / "arduino15" / "libraries",
    ]
    return [p for p in candidates if p.exists()]


def library_header_exists(header: str, search_roots: Iterable[Path]) -> bool:
    for root in search_roots:
        for current_root, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in {"examples", "test", "tests", "__pycache__"}]
            if header in filenames:
                return True
    return False


def check_arduino_dependencies() -> List[CheckResult]:
    results: List[CheckResult] = []

    arduino_cli = shutil.which("arduino-cli")
    if arduino_cli:
        ok, detail = run_command([arduino_cli, "version"])
        results.append(CheckResult("arduino-cli", ok, detail))
    else:
        results.append(CheckResult("arduino-cli", False, "not found in PATH"))

    roots = find_arduino_library_dirs()
    root_desc = ", ".join(str(p) for p in roots) if roots else "no common Arduino library directories found"

    for header in ARDUINO_REQUIRED_HEADERS:
        hint = ARDUINO_LIBRARY_HINTS[header]
        ok = library_header_exists(header, roots)
        detail = f"header found ({hint})" if ok else f"header not found ({hint}); searched: {root_desc}"
        results.append(CheckResult(header, ok, detail))

    return results


def check_misc() -> List[CheckResult]:
    results = []
    results.append(
        CheckResult(
            "embedder_arcface.onnx",
            MODEL_PATH.exists(),
            f"found at {MODEL_PATH}" if MODEL_PATH.exists() else f"missing at {MODEL_PATH}",
        )
    )

    mosquitto = shutil.which("mosquitto")
    results.append(
        CheckResult(
            "mosquitto",
            mosquitto is not None,
            mosquitto if mosquitto else "not found in PATH",
        )
    )
    return results


def print_section(title: str, results: List[CheckResult]) -> int:
    failures = 0
    print(f"\n[{title}]")
    for result in results:
        status = "OK" if result.ok else "MISSING"
        print(f"{status:7} {result.name}: {result.detail}")
        if not result.ok:
            failures += 1
    return failures


def main() -> int:
    total_failures = 0
    total_failures += print_section("Python", check_python_dependencies())
    total_failures += print_section("Node", check_node_dependencies())
    total_failures += print_section("Arduino", check_arduino_dependencies())
    total_failures += print_section("Other", check_misc())

    print("\nSummary")
    if total_failures == 0:
        print("All checked dependencies are available.")
        return 0

    print(f"{total_failures} dependency checks failed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
