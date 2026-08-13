#!/bin/bash
# Provisioning script para template privado "MiniMax H3 ComfyUI" en Vast.ai
# Basado en el template oficial (vastai/comfy) pero optimizado para H3.
# Se ejecuta UNA VEZ al primer arranque de la instancia.
set -e
export DEBIAN_FRONTEND=noninteractive
echo "=== PROVISION H3: inicio $(date) ==="

# 1. Asegurar python/pip y herramientas base
apt-get update -qq 2>&1 | tail -1 || true
apt-get install -y -qq git curl wget tmux 2>&1 | tail -1 || true

# 2. ComfyUI (la imagen vastai/comfy puede traerlo; si no, clonar)
COMFY_DIR=/workspace/ComfyUI
if [ ! -d "$COMFY_DIR" ]; then
  git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git "$COMFY_DIR"
fi
cd "$COMFY_DIR"
pip install --no-cache-dir -q -r requirements.txt 2>&1 | tail -2 || true

# 3. Modelos MiniMax H3 (Comfy-Org/MiniMax-H3)
mkdir -p models/diffusion_models models/text_encoders models/vae
pip install --no-cache-dir -q huggingface_hub 2>&1 | tail -1 || true
python - <<'EOF'
import os
from huggingface_hub import hf_hub_download
repo = "Comfy-Org/MiniMax-H3"
base = "/workspace/ComfyUI/models"
files = {
    "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors": "diffusion_models",
    "diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors": "diffusion_models",
    "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors": "text_encoders",
    "vae/minimax_h3_video_vae_fp16.safetensors": "vae",
    "vae/minimax_h3_audio_vae_fp32.safetensors": "vae",
}
for fname, folder in files.items():
    dest = os.path.join(base, folder)
    os.makedirs(dest, exist_ok=True)
    if os.path.exists(os.path.join(dest, os.path.basename(fname))):
        print(f"Ya existe: {fname}", flush=True)
        continue
    print(f"Descargando {fname} ...", flush=True)
    try:
        p = hf_hub_download(repo, fname, local_dir=dest)
        print(f"  OK -> {p}", flush=True)
    except Exception as e:
        print(f"  FALLO {fname}: {e}", flush=True)
EOF

# 4. Interfaz web (h3_web.py se monta como volumen o se descarga del repo)
pip install --no-cache-dir -q flask requests 2>&1 | tail -1 || true

# 5. Lanzar ComfyUI en 18188 (proxy de Vast lo expone en 8188)
cd "$COMFY_DIR"
if ! pgrep -f "main.py" > /dev/null; then
  nohup python main.py --listen 0.0.0.0 --port 18188 --enable-cors-header > /workspace/comfy.log 2>&1 &
  echo "ComfyUI lanzado en :18188 (log: /workspace/comfy.log)"
else
  echo "ComfyUI ya estaba corriendo"
fi

# 6. Lanzar interfaz web en 18189 (proxy de Vast lo expone en 8189)
if [ -f /workspace/h3_web.py ] && ! pgrep -f "h3_web.py" > /dev/null; then
  cd /workspace
  COMFY_URL=http://127.0.0.1:18188 PORT=18189 nohup python h3_web.py > /workspace/h3web.log 2>&1 &
  echo "Interfaz web lanzada en :18189 (log: /workspace/h3web.log)"
fi

echo "=== PROVISION H3: fin $(date) ==="
