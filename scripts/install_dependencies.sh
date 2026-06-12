#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${ROOT_DIR}/venv"
LOCAL_BIN="${HOME}/.local/bin"
export PATH="${LOCAL_BIN}:${PATH}"

SKIP_SYSTEM=0
SKIP_ARDUINO=0
SKIP_MODEL=0

usage() {
  cat <<'EOF'
Usage: bash scripts/install_dependencies.sh [options]

Options:
  --skip-system    Skip OS package installation
  --skip-arduino   Skip Arduino CLI core/library installation
  --skip-model     Skip ArcFace model download
  -h, --help       Show this help message

What it installs:
  - System tools: Python, pip/venv, Node.js, npm, Mosquitto, arduino-cli
  - Python packages from requirements.txt into ./venv
  - Backend npm packages in ./backend
  - Arduino support: esp8266 core, PubSubClient, Servo
  - ArcFace ONNX model into models/embedder_arcface.onnx
EOF
}

log() {
  printf '\n[%s] %s\n' "$1" "$2"
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

run_maybe_sudo() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

detect_pkg_manager() {
  if need_cmd pacman; then
    echo pacman
  elif need_cmd apt-get; then
    echo apt
  elif need_cmd dnf; then
    echo dnf
  else
    echo unknown
  fi
}

install_system_packages() {
  local pkg_manager
  pkg_manager="$(detect_pkg_manager)"

  case "${pkg_manager}" in
    pacman)
      log SYSTEM "Installing system packages with pacman"
      run_maybe_sudo pacman -Sy --needed --noconfirm \
        python python-pip python-virtualenv nodejs npm mosquitto arduino-cli
      ;;
    apt)
      log SYSTEM "Installing system packages with apt"
      run_maybe_sudo apt-get update
      run_maybe_sudo apt-get install -y \
        python3 python3-pip python3-venv nodejs npm mosquitto curl
      ;;
    dnf)
      log SYSTEM "Installing system packages with dnf"
      run_maybe_sudo dnf install -y \
        python3 python3-pip nodejs npm mosquitto arduino-cli curl
      ;;
    *)
      log SYSTEM "Unsupported package manager. Install Python, Node.js, Mosquitto, and arduino-cli manually."
      return 1
      ;;
  esac
}

install_arduino_cli_if_missing() {
  if need_cmd arduino-cli; then
    return 0
  fi

  if ! need_cmd curl; then
    log ARDUINO "curl is required to install arduino-cli automatically"
    return 1
  fi

  log ARDUINO "Installing arduino-cli into ${LOCAL_BIN}"
  mkdir -p "${LOCAL_BIN}"
  curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR="${LOCAL_BIN}" sh
}

setup_python() {
  log PYTHON "Creating virtual environment if needed"
  if [[ ! -d "${VENV_DIR}" ]]; then
    python3 -m venv "${VENV_DIR}"
  fi

  log PYTHON "Installing Python dependencies"
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip
  "${VENV_DIR}/bin/python" -m pip install -r "${ROOT_DIR}/requirements.txt"
}

setup_node() {
  log NODE "Installing backend npm dependencies"
  (cd "${ROOT_DIR}/backend" && npm install)
}

setup_arduino() {
  install_arduino_cli_if_missing

  if ! need_cmd arduino-cli; then
    log ARDUINO "arduino-cli is still unavailable; skipping Arduino provisioning"
    return 1
  fi

  log ARDUINO "Updating Arduino package indexes"
  arduino-cli core update-index
  arduino-cli lib update-index

  log ARDUINO "Installing ESP8266 core"
  arduino-cli core install esp8266:esp8266

  log ARDUINO "Installing required Arduino libraries"
  arduino-cli lib install PubSubClient || true
  arduino-cli lib install Servo || true
}

download_model() {
  log MODEL "Downloading ArcFace model if needed"
  if [[ -f "${ROOT_DIR}/models/embedder_arcface.onnx" ]]; then
    log MODEL "Model already exists at models/embedder_arcface.onnx"
    return 0
  fi

  "${VENV_DIR}/bin/python" "${ROOT_DIR}/scripts/download_arcface_model.py"
}

run_checker() {
  log VERIFY "Running dependency checker"
  "${VENV_DIR}/bin/python" "${ROOT_DIR}/scripts/check_dependencies.py"
}

main() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --skip-system)
        SKIP_SYSTEM=1
        ;;
      --skip-arduino)
        SKIP_ARDUINO=1
        ;;
      --skip-model)
        SKIP_MODEL=1
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        echo "Unknown option: $1" >&2
        usage
        exit 2
        ;;
    esac
    shift
  done

  if [[ "${SKIP_SYSTEM}" -eq 0 ]]; then
    install_system_packages
  fi

  setup_python
  setup_node

  if [[ "${SKIP_ARDUINO}" -eq 0 ]]; then
    setup_arduino || true
  fi

  if [[ "${SKIP_MODEL}" -eq 0 ]]; then
    download_model
  fi

  run_checker
}

main "$@"
