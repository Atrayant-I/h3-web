#!/bin/bash
# Setup remoto en instancia vastai/comfy: torch + ComfyUI deps + modelos H3 + interfaz
set -e
export DEBIAN_FRONTEND=noninteractive
export PATH=/opt/miniforge3/bin:$PATH
export COMFY=/opt/workspace-internal/ComfyUI

echo "=== 0. python base ==="
python -V

echo "=== 1. Instalar torch CUDA 13 (Blackwell 5090) ==="
pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu130 2>&1 | tail -2 || \
pip install --no-cache-dir torch torchvision torchaudio 2>&1 | tail -2
python -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')" 2>&1 | tail -1

echo "=== 2. Deps de ComfyUI ==="
cd $COMFY
pip install --no-cache-dir -q -r requirements.txt 2>&1 | tail -2 || true
pip install --no-cache-dir -q huggingface_hub flask requests 2>&1 | tail -1 || true

echo "=== 3. Modelos H3 ==="
mkdir -p models/diffusion_models models/text_encoders models/vae
python - <<'EOF'
import os
from huggingface_hub import hf_hub_download
repo = "Comfy-Org/MiniMax-H3"
base = "/opt/workspace-internal/ComfyUI/models"
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
    out = os.path.join(dest, os.path.basename(fname))
    if os.path.exists(out) and os.path.getsize(out) > 1e9:
        print(f"Ya existe: {fname}", flush=True)
        continue
    print(f"Descargando {fname} ...", flush=True)
    try:
        p = hf_hub_download(repo, fname, local_dir=dest)
        print(f"  OK -> {p}", flush=True)
    except Exception as e:
        print(f"  FALLO {fname}: {e}", flush=True)
EOF

echo "=== 4. Lanzar ComfyUI (18188) ==="
cd $COMFY
pkill -f "main.py" 2>/dev/null || true
sleep 2
nohup python main.py --listen 0.0.0.0 --port 18188 --enable-cors-header > /workspace/comfy.log 2>&1 &
sleep 12
curl -s http://127.0.0.1:18188/system_stats | head -c 300 || echo "ComfyUI aún no responde (revisar /workspace/comfy.log)"
echo
echo "=== 5. Lanzar interfaz web (18189) ==="
if [ -f /workspace/h3_web.py ]; then
  cd /workspace
  pkill -f h3_web.py 2>/dev/null || true
  COMFY_URL=http://127.0.0.1:18188 PORT=18189 nohup python h3_web.py > /workspace/h3web.log 2>&1 &
  sleep 4
  curl -s -o /dev/null -w "h3_web HTTP: %{http_code}\n" http://127.0.0.1:18189/ || echo "h3_web no responde"
fi
echo "=== SETUP COMPLETO $(date) ==="
