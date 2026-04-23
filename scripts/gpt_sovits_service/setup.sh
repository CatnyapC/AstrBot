#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASTRBOT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

GPT_SOVITS_REPO="${GPT_SOVITS_REPO:-https://github.com/RVC-Boss/GPT-SoVITS.git}"
GPT_SOVITS_BRANCH="${GPT_SOVITS_BRANCH:-main}"
GPT_SOVITS_HOME="${GPT_SOVITS_HOME:-${ASTRBOT_ROOT}/.local-services/GPT-SoVITS}"
GPT_SOVITS_INSTALL_MODE="${GPT_SOVITS_INSTALL_MODE:-auto}"
GPT_SOVITS_ENV="${GPT_SOVITS_ENV:-GPTSoVits}"
GPT_SOVITS_VENV="${GPT_SOVITS_VENV:-${ASTRBOT_ROOT}/.venv-gpt-sovits}"
GPT_SOVITS_DEVICE="${GPT_SOVITS_DEVICE:-MPS}"
GPT_SOVITS_SOURCE="${GPT_SOVITS_SOURCE:-HF}"
GPT_SOVITS_DOWNLOAD_UVR5="${GPT_SOVITS_DOWNLOAD_UVR5:-false}"
GPT_SOVITS_SKIP_INSTALL="${GPT_SOVITS_SKIP_INSTALL:-false}"

clone_or_update() {
  if [[ -d "${GPT_SOVITS_HOME}/.git" ]]; then
    git -C "${GPT_SOVITS_HOME}" fetch origin "${GPT_SOVITS_BRANCH}"
    git -C "${GPT_SOVITS_HOME}" checkout "${GPT_SOVITS_BRANCH}"
    git -C "${GPT_SOVITS_HOME}" pull --ff-only origin "${GPT_SOVITS_BRANCH}"
  else
    mkdir -p "$(dirname "${GPT_SOVITS_HOME}")"
    git clone --branch "${GPT_SOVITS_BRANCH}" "${GPT_SOVITS_REPO}" "${GPT_SOVITS_HOME}"
  fi
}

install_with_conda() {
  if ! command -v conda >/dev/null 2>&1; then
    return 1
  fi

  eval "$(conda shell.bash hook)"
  if ! conda env list | awk '{print $1}' | grep -qx "${GPT_SOVITS_ENV}"; then
    conda create -n "${GPT_SOVITS_ENV}" python=3.10 -y
  fi

  conda activate "${GPT_SOVITS_ENV}"
  cd "${GPT_SOVITS_HOME}"

  install_args=(--device "${GPT_SOVITS_DEVICE}" --source "${GPT_SOVITS_SOURCE}")
  if [[ "${GPT_SOVITS_DOWNLOAD_UVR5}" == "true" ]]; then
    install_args+=(--download-uvr5)
  fi
  bash install.sh "${install_args[@]}"
}

install_with_venv() {
  local python_bin="${GPT_SOVITS_PYTHON:-python3.10}"

  if ! command -v "${python_bin}" >/dev/null 2>&1; then
    echo "python3.10 not found; set GPT_SOVITS_PYTHON or install Conda" >&2
    return 1
  fi

  "${python_bin}" -m venv "${GPT_SOVITS_VENV}"
  "${GPT_SOVITS_VENV}/bin/python" -m pip install -U pip
  cd "${GPT_SOVITS_HOME}"
  "${GPT_SOVITS_VENV}/bin/python" -m pip install -r extra-req.txt --no-deps
  "${GPT_SOVITS_VENV}/bin/python" -m pip install -r requirements.txt
}

clone_or_update

if [[ "${GPT_SOVITS_SKIP_INSTALL}" == "true" ]]; then
  echo "GPT-SoVITS cloned at ${GPT_SOVITS_HOME}"
  exit 0
fi

case "${GPT_SOVITS_INSTALL_MODE}" in
  conda)
    install_with_conda
    ;;
  venv)
    install_with_venv
    ;;
  auto)
    if ! install_with_conda; then
      install_with_venv
    fi
    ;;
  *)
    echo "GPT_SOVITS_INSTALL_MODE must be auto, conda, or venv" >&2
    exit 2
    ;;
esac

echo "GPT-SoVITS ready at ${GPT_SOVITS_HOME}"
