# H3 Web — MiniMax H3 (video generation) Web UI

Interfaz web Flask para generar videos con **MiniMax H3** (33B, open weights) corriendo en ComfyUI sobre GPU rentada (Vast.ai, RTX 5090).

## Funciones

- **i2v** (imagen → video) y **v2v** (video → video con edición fiel: mismo inicio, pose, fondo y **audio original**; solo cambia lo que pide el prompt)
- Duración 5/10/15 s (en v2v se usa la duración del video original automáticamente)
- Calidad 480p (rápido) / 768p (nativo)
- Orientación **Auto** (igual que tu archivo), 16:9, 9:16, 1:1
- Barra de progreso real (WebSocket de ComfyUI)
- Resultado MP4 embebido en la página, con audio
- Accesible en la red local: `http://<IP-LAN>:18189`

## Despliegue en Vast.ai

Instancia: imagen `vastai/comfy` (ya trae ComfyUI + pytorch), RTX 5090, ~$0.336/h.
Template privado creado: busca "MiniMax H3" en tus templates, o usa el CLI:
`vastai create instance --template_hash a7c81127cded78225c3a2f3ae7c45222`

### Setup manual (si no usas el template)

```bash
# 1) Instalar torch (CUDA 13, Blackwell) en el python de la imagen
/opt/miniforge3/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130

# 2) ComfyUI ya viene en /opt/workspace-internal/ComfyUI — instalar sus deps:
cd /opt/workspace-internal/ComfyUI && /opt/miniforge3/bin/pip install -r requirements.txt

# 3) Modelos H3 (~63.5GB) en:
#   models/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors   (21GB, i2v)
#   models/diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors (21GB, v2v)
#   models/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors         (15.7GB)
#   models/vae/minimax_h3_video_vae_fp16.safetensors                          (5.2GB)
#   models/vae/minimax_h3_audio_vae_fp32.safetensors                          (0.6GB)
#   Fuente: https://huggingface.co/Comfy-Org/MiniMax-H3

# 4) Lanzar ComfyUI en 18188 (--listen 127.0.0.1 --port 18188) y la web:
bash start_h3web.sh
```

### Túnel SSH local (para acceder desde tu PC)

```bash
ssh -N -i ~/.ssh/id_ed25519 -p <PORT> -L 0.0.0.0:18189:127.0.0.1:18189 -L 0.0.0.0:18188:127.0.0.1:18188 root@ssh8.vast.ai
```

Luego abre `http://localhost:18189` (o `http://<IP-LAN>:18189` desde cualquier dispositivo en tu WiFi; firewall: `netsh advfirewall firewall add rule name=H3 dir=in action=allow protocol=TCP localport=18189`).

## Pipeline ComfyUI (nativo, sin login)

```
UNETLoader (fl2va/ref2va) → MODEL
CLIPLoader (qwen3vl, type=minimax) → CLIP
VAELoader (video_vae) → VAE
VAELoader (audio_vae) → AUDIO_VAE
LoadImage / LoadVideo → first_frame / ref_videos
MiniMaxH3ImageToVideo | MiniMaxH3ReferenceToVideo (ref_image_size=match, ref_video_audios para audio original)
KSampler → VAEDecode + VAEDecodeAudio → CreateVideo (24fps, audio) → SaveVideo
```

Nota: los nodos legacy (`MinimaxHailuo03*`) piden login — usar los nativos `MiniMaxH3*`.

## Costos

- Instancia RTX 5090: ~$0.336/h
- Clip 480p 5s i2v: ~2 min GPU (~$0.01)
- Clip v2v (ref2va): ~5× más lento
- Botón de apagado: destruir instancia desde la consola Vast (el disco se pierde; los modelos se re-descargan con el template)

## Estado

- [x] i2v funcional con audio
- [x] v2v edición fiel (audio + duración original + pose/fondo)
- [x] Aspect ratio auto
- [x] Progreso real vía WebSocket
- [x] Acceso LAN
