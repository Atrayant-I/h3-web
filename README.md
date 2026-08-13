# h3-web — Interfaz web MiniMax H3 (ComfyUI en Vast.ai)

Web UI para generar/editar video con MiniMax H3 open-weights corriendo en ComfyUI
(instancia RTX 5090 en Vast.ai). Sirve para: i2v (imagen→video), v2v (video→video
con edición fiel), multi-archivo (hasta 5 refs), galería de resultados, pegado de
imágenes desde portapapeles (incl. móvil).

## Archivos

- `h3_web.py` — app Flask: endpoints `/generate`, `/status/<pid>`, `/result/<pid>`,
  `/api/gallery`, `/thumb/<path>`, `/media/<path>`. Se comunica con ComfyUI local.
- `start_h3web.sh` — arranca/relanza la interfaz en `:18189` (PATH miniforge,
  COMFY_URL, PORT). Uso: `bash /workspace/start_h3web.sh`.

## Despliegue en instancia Vast (template 535237)

El template privado de Vast (hash actual: consultar en consola; cambia en cada
update) ejecuta un onstart que: instala torch cu130 si falta, descarga modelos H3
(Comfy-Org/MiniMax-H3), baja estos archivos desde este repo con curl, y lanza
ComfyUI (`:18188`) + la web (`:18189`).

Acceso: túnel SSH `ssh -L 0.0.0.0:18189:127.0.0.1:18189 root@<host> -p <port>`
(bind 0.0.0.0 para red LAN; firewall Windows: reglas H3-Web-18189 / H3-Comfy-18188).

## Notas técnicas (importantes)

### Modelos H3
- `diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors` (21GB, i2v)
- `diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors` (21GB, v2v)
- `text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` (15.7GB, CLIPLoader type=minimax)
- `vae/minimax_h3_video_vae_fp16.safetensors` + `vae/minimax_h3_audio_vae_fp32.safetensors`

### Workflow API ComfyUI 0.32 — PUNTOS CRÍTICOS (bugs sufridos)
- Upload: `POST /upload/image`, campo multipart SIEMPRE `image` (server.py hace
  `post.get("image")`); `/api/upload/video` NO existe (405).
- Endpoints SIN prefijo `/api/`: `/prompt`, `/history/{pid}`, `/view`, `/object_info`, `/queue`, `/interrupt`.
- **LoadVideo: el input se llama `file` (COMBO), NO `video`** — si mandas `video`,
  ComfyUI lo ignora y carga el PRIMER archivo del combo (bug que rompía el v2v).
- SaveVideo requiere `format` y `codec` ("auto" como string, no dict).
- Nodos legacy `MinimaxHailuo03*` piden LOGIN (Unauthorized) — NO usar.
- v2v `MiniMaxH3ReferenceToVideo`: refs AUTOGROW como dict `{"ref_videos": {"ref_video_1": ["5",0]}}`,
  `{"ref_video_audios": {"ref_video_audio_1": ["13",0]}}`; `ref_image_size: "match"`.
  object_info: input = `{"required":{...},"optional":{...}}` (buscar refs en optional).
- Salida: history guarda el MP4 bajo clave `images` (animated:true), NO `videos`;
  status/result deben buscar en videos+images+gifs+files.
- Progreso: solo por WebSocket `/ws?clientId=X` con `origin=<COMFY_URL>` (sin origin da timeout).
- **reference_videos solo soportado a 480p** (doc oficial): si el video excede 480p
  en su lado corto, escalarlo con ffmpeg antes de subirlo.
- **Tokens de referencia en el prompt**: el modelo requiere `<Video 1>`, `<Picture N>`
  explícitos en el prompt para aplicar las referencias (igual que la API de Wavespeed).

### Costos/velocidad (Vast, ago-2026)
- RTX 5090 ~$0.336/h; i2v 480p 5s ≈ 108s; v2v ref2va ≈ 17s/paso (30 pasos ≈ 8-9 min).
- Usar imagen `vastai/comfy` (pull rápido); NO `pytorch/pytorch` (build 20+ min) ni
  `comfyanonymous/comfyui` (no existe en Docker Hub).
- On-demand vs interruptible: interruptible = puja baja pero te pueden quitar la
  máquina a mitad de una generación (9-10 min) — para uso interactivo, on-demand.
