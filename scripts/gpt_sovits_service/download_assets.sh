#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASTRBOT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

GPT_SOVITS_HOME="${GPT_SOVITS_HOME:-${ASTRBOT_ROOT}/.local-services/GPT-SoVITS}"
GPT_SOVITS_VENV="${GPT_SOVITS_VENV:-${ASTRBOT_ROOT}/.venv-gpt-sovits}"
GPT_SOVITS_SOURCE="${GPT_SOVITS_SOURCE:-HF}"
GPT_SOVITS_PYTHON_BIN="${GPT_SOVITS_PYTHON_BIN:-${GPT_SOVITS_VENV}/bin/python}"
GPT_SOVITS_DOWNLOAD_UVR5="${GPT_SOVITS_DOWNLOAD_UVR5:-false}"

case "${GPT_SOVITS_SOURCE}" in
  HF)
    ASSET_BASE="https://huggingface.co/XXXXRT/GPT-SoVITS-Pretrained/resolve/main"
    ;;
  HF-Mirror)
    ASSET_BASE="https://hf-mirror.com/XXXXRT/GPT-SoVITS-Pretrained/resolve/main"
    ;;
  ModelScope)
    ASSET_BASE="https://www.modelscope.cn/models/XXXXRT/GPT-SoVITS-Pretrained/resolve/master"
    ;;
  *)
    echo "GPT_SOVITS_SOURCE must be HF, HF-Mirror, or ModelScope" >&2
    exit 2
    ;;
esac

if [[ ! -d "${GPT_SOVITS_HOME}" ]]; then
  echo "GPT-SoVITS checkout not found. Run setup.sh first." >&2
  exit 1
fi

if [[ ! -x "${GPT_SOVITS_PYTHON_BIN}" ]]; then
  echo "Python runtime not found: ${GPT_SOVITS_PYTHON_BIN}" >&2
  exit 1
fi

download() {
  local url="$1"
  local out="$2"
  curl -L --retry 5 --retry-delay 5 --fail -o "${out}" "${url}"
}

download_zip() {
  local name="$1"
  local target_dir="$2"
  local url="${ASSET_BASE}/${name}.zip"
  local tmp="${GPT_SOVITS_HOME}/${name}.zip"

  download "${url}" "${tmp}"
  unzip -q -o "${tmp}" -d "${target_dir}"
  rm -f "${tmp}"
}

cd "${GPT_SOVITS_HOME}"

if [[ ! -f "GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt" ]]; then
  download_zip "pretrained_models" "GPT_SoVITS"
fi

if [[ ! -d "GPT_SoVITS/text/G2PWModel" ]]; then
  download_zip "G2PWModel" "GPT_SoVITS/text"
fi

PY_PREFIX="$("${GPT_SOVITS_PYTHON_BIN}" -c 'import sys; print(sys.prefix)')"
if [[ ! -d "${PY_PREFIX}/nltk_data" ]]; then
  download_zip "nltk_data" "${PY_PREFIX}"
fi

PYOPENJTALK_PREFIX="$("${GPT_SOVITS_PYTHON_BIN}" -c 'import os, pyopenjtalk; print(os.path.dirname(pyopenjtalk.__file__))')"
if [[ ! -d "${PYOPENJTALK_PREFIX}/open_jtalk_dic_utf_8-1.11" ]]; then
  tmp="${GPT_SOVITS_HOME}/open_jtalk_dic_utf_8-1.11.tar.gz"
  download "${ASSET_BASE}/open_jtalk_dic_utf_8-1.11.tar.gz" "${tmp}"
  tar -xzf "${tmp}" -C "${PYOPENJTALK_PREFIX}"
  rm -f "${tmp}"
fi

if [[ "${GPT_SOVITS_DOWNLOAD_UVR5}" == "true" ]]; then
  if ! find -L "tools/uvr5/uvr5_weights" -mindepth 1 ! -name ".gitignore" | grep -q .; then
    download_zip "uvr5_weights" "tools/uvr5"
  fi
fi

echo "GPT-SoVITS assets ready at ${GPT_SOVITS_HOME}"
