#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASTRBOT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

GPT_SOVITS_HOME="${GPT_SOVITS_HOME:-${ASTRBOT_ROOT}/.local-services/GPT-SoVITS}"
GPT_SOVITS_ENV="${GPT_SOVITS_ENV:-GPTSoVits}"
GPT_SOVITS_VENV="${GPT_SOVITS_VENV:-${ASTRBOT_ROOT}/.venv-gpt-sovits}"
GPT_SOVITS_HOST="${GPT_SOVITS_HOST:-127.0.0.1}"
GPT_SOVITS_PORT="${GPT_SOVITS_PORT:-9880}"
GPT_SOVITS_TTS_CONFIG="${GPT_SOVITS_TTS_CONFIG:-GPT_SoVITS/configs/tts_infer.yaml}"

if [[ ! -f "${GPT_SOVITS_HOME}/api_v2.py" ]]; then
  echo "GPT-SoVITS not found. Run scripts/gpt_sovits_service/setup.sh first." >&2
  exit 1
fi

cd "${GPT_SOVITS_HOME}"

if command -v conda >/dev/null 2>&1 && conda env list | awk '{print $1}' | grep -qx "${GPT_SOVITS_ENV}"; then
  eval "$(conda shell.bash hook)"
  conda activate "${GPT_SOVITS_ENV}"
  exec python api_v2.py -a "${GPT_SOVITS_HOST}" -p "${GPT_SOVITS_PORT}" -c "${GPT_SOVITS_TTS_CONFIG}"
fi

if [[ -x "${GPT_SOVITS_VENV}/bin/python" ]]; then
  exec "${GPT_SOVITS_VENV}/bin/python" api_v2.py -a "${GPT_SOVITS_HOST}" -p "${GPT_SOVITS_PORT}" -c "${GPT_SOVITS_TTS_CONFIG}"
fi

exec python api_v2.py -a "${GPT_SOVITS_HOST}" -p "${GPT_SOVITS_PORT}" -c "${GPT_SOVITS_TTS_CONFIG}"
