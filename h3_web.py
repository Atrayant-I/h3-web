#!/usr/bin/env python3
"""
Interfaz web para MiniMax H3 en ComfyUI (Vast.ai).
- Subir IMAGEN (i2v) o VIDEO (v2v/r2v) + casilla de prompt -> genera video 480p 5s
- Se comunica con ComfyUI local (127.0.0.1:8188)
- Muestra el resultado en la misma página
"""
import json, os, sys, time, uuid, io, subprocess, threading
import requests
from flask import Flask, request, render_template_string, jsonify, send_file

COMFY = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
RESOLUTION = os.environ.get("RESOLUTION", "480P")   # 480P o 768P
DURATION = float(os.environ.get("DURATION", "5"))
STEPS = int(os.environ.get("STEPS", "30"))
MODEL_NAME = os.environ.get("MODEL_NAME", "MiniMax H3")
# Clave de Vast: desde env o desde /workspace/.env (para el badge de saldo)
def _load_env_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())
    except OSError:
        pass
_load_env_file("/workspace/.env")
VAST_API_KEY = os.environ.get("VAST_API_KEY", "")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200MB upload

# --- WebSocket de progreso ---
CLIENT_ID = str(uuid.uuid4())
PROGRESS = {}   # pid -> {"value": int, "max": int}
EXECUTING = {}  # pid -> True/False

def ws_listener():
    """Conecta al WS de ComfyUI y guarda progreso/ejecución por prompt."""
    import websocket
    ws_url = COMFY.replace("http", "ws", 1) + f"/ws?clientId={CLIENT_ID}"
    while True:
        try:
            ws = websocket.create_connection(ws_url, timeout=30, origin=COMFY)
            while True:
                raw = ws.recv()
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                mtype = msg.get("type")
                data = msg.get("data", {})
                if mtype == "progress":
                    PROGRESS[data.get("prompt_id", "")] = {
                        "value": data.get("value", 0), "max": data.get("max", 1)}
                elif mtype == "executing":
                    pid = data.get("prompt_id")
                    node = data.get("node")
                    if node is None and pid:
                        EXECUTING[pid] = False  # terminó
                    elif pid:
                        EXECUTING[pid] = True
        except Exception as e:
            print(f"[h3_web] ws reconectando: {e}")
            time.sleep(3)

threading.Thread(target=ws_listener, daemon=True).start()

HTML = """<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MiniMax H3 — Generador de video</title>
<style>
  body{font-family:system-ui,sans-serif;background:#0f1117;color:#e6e6e6;margin:0;padding:24px}
  .card{max-width:720px;margin:0 auto;background:#1a1d27;border:1px solid #2c3040;border-radius:12px;padding:24px}
  h1{font-size:20px;margin:0 0 4px}
  .sub{color:#8b93a7;font-size:13px;margin-bottom:20px}
  .bal{display:inline-block;margin-left:8px;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;vertical-align:middle}
  .bal.ok{background:#052e16;color:#4ade80;border:1px solid #166534}
  .bal.warn{background:#2e1c05;color:#facc15;border:1px solid #713f12}
  .bal.low{background:#2e0505;color:#f87171;border:1px solid #7f1d1d}
  .bal.off{background:#151823;color:#8b93a7;border:1px solid #2c3040}
  label{display:block;font-size:13px;margin:14px 0 6px;color:#aab3c5}
  input[type=file]{width:100%;padding:10px;background:#0f1117;border:1px solid #2c3040;border-radius:8px;color:#e6e6e6}
  textarea{width:100%;height:110px;padding:10px;background:#0f1117;border:1px solid #2c3040;border-radius:8px;color:#e6e6e6;font-family:inherit;resize:vertical}
  select{padding:8px;background:#0f1117;border:1px solid #2c3040;border-radius:8px;color:#e6e6e6}
  button{margin-top:18px;width:100%;padding:12px;background:#4f46e5;border:none;border-radius:8px;color:#fff;font-size:15px;font-weight:600;cursor:pointer}
  button:disabled{opacity:.5;cursor:wait}
  #status{margin-top:14px;font-size:13px;color:#8b93a7;white-space:pre-wrap}
  video{width:100%;margin-top:16px;border-radius:8px;background:#000}
  .bar{height:6px;background:#2c3040;border-radius:3px;margin-top:10px;overflow:hidden;display:none}
  .bar div{height:100%;background:#4f46e5;width:0%;transition:width .5s}
  .err{color:#f87171;margin-top:10px;font-size:13px;white-space:pre-wrap}
  .ok{color:#34d399}
  .tabs{display:flex;gap:8px;margin-bottom:18px;border-bottom:1px solid #2c3040;padding-bottom:10px}
  .tab{flex:1;text-align:center;padding:10px;border-radius:8px;cursor:pointer;color:#8b93a7;font-weight:600;font-size:14px;background:#151823;border:1px solid #2c3040}
  .tab.active{background:#4f46e5;color:#fff;border-color:#4f46e5}
  .view{display:none}
  .view.active{display:block}
  #gal{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px;margin-top:10px}
  .gitem{background:#151823;border:1px solid #2c3040;border-radius:10px;overflow:hidden;cursor:pointer;transition:border-color .2s}
  .gitem:hover{border-color:#4f46e5}
  .gitem img{width:100%;display:block;aspect-ratio:9/16;object-fit:cover;background:#000}
  .gitem .gname{padding:8px 10px;font-size:11px;color:#8b93a7;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .gitem .gmeta{font-size:10px;color:#5c6478;padding:0 10px 8px}
  #drop{border:2px dashed #3a4156;border-radius:10px;padding:18px;text-align:center;cursor:pointer;color:#8b93a7;font-size:13px;transition:border-color .2s,background .2s}
  #drop.dragover{border-color:#4f46e5;background:#1e2130}
  #drop small{color:#5c6478}
  #previews{display:grid;grid-template-columns:repeat(auto-fill,minmax(90px,1fr));gap:8px;margin-top:12px}
  .pitem{position:relative;border:1px solid #2c3040;border-radius:8px;overflow:hidden;background:#0f1117}
  .pitem img,.pitem video{width:100%;aspect-ratio:9/16;object-fit:cover;display:block;background:#000}
  .pitem .px{position:absolute;top:3px;right:3px;width:18px;height:18px;border:none;border-radius:50%;background:#f87171;color:#fff;font-size:11px;line-height:18px;cursor:pointer;text-align:center;padding:0}
  .pitem .ptag{position:absolute;bottom:3px;left:3px;font-size:9px;background:#000a;color:#cbd5e1;padding:1px 5px;border-radius:4px}
  .cliprow{margin-top:8px;text-align:center}
  #pastebtn{display:inline-flex;align-items:center;gap:6px;background:#151823;border:1px solid #2c3040;color:#aab3c5;padding:8px 14px;border-radius:8px;font-size:12px;cursor:pointer}
  #pastebtn:hover{border-color:#4f46e5;color:#fff}
</style></head><body><div class="card">
<div class="tabs">
  <button class="tab active" id="tab-gen" onclick="showTab('gen')">⚡ Generador</button>
  <button class="tab" id="tab-gal" onclick="showTab('gal')">🎬 Galería</button>
  <button class="tab danger" id="tab-off" onclick="apagar()">⏻ Apagar servidor</button>
</div>
<div class="view active" id="view-gen">
<h1>🎬 MiniMax H3 — i2v / v2v <span class="bal off" id="bal" title="Saldo Vast.ai">Saldo…</span></h1>
<div class="sub">RTX 5090 · {{res}} · ~{{dur}}s · Genera video + audio nativo</div>
<form id="f">
  <label>Archivos — arrastra hasta 5 (imágenes o videos)</label>
  <div id="drop" onclick="$('file').click()">
    <div id="dropmsg">📁 Arrastra archivos aquí o haz clic para seleccionar<br><small>hasta 5 · imagen (i2v) o video (v2v)</small></div>
    <div id="previews"></div>
    <input type="file" id="file" accept="image/*,video/*" multiple hidden>
  </div>
  <div class="cliprow">
    <button type="button" id="pastebtn" title="Pegar imagen del portapapeles">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><path d="M12 11v6M9 14h6"/></svg>
      Pegar imagen (Ctrl+V)
    </button>
  </div>
  <label>Prompt (describe movimiento, cámara y audio)</label>
  <textarea id="prompt" placeholder="Ej: La persona camina hacia la cámara sonriendo, plano medio, luz cálida, viento suave, sonido ambiente de calle..."></textarea>
  <label>Modo: <select id="mode">
    <option value="auto">Auto (imagen→i2v, video→v2v)</option>
    <option value="i2v">i2v (imagen a video)</option>
    <option value="v2v">v2v (video a video)</option>
  </select>
  &nbsp;·&nbsp; Duración: <select id="dur">
    <option value="5" selected>5 s</option>
    <option value="10">10 s</option>
    <option value="15">15 s (máx)</option>
  </select> <span id="durnote" style="display:none;color:#f0c060">(bloqueada — usará la duración del video)</span>
  &nbsp;·&nbsp; Calidad: <select id="qual">
    <option value="480" selected>480p (rápido)</option>
    <option value="768">768p (nativo)</option>
  </select>
  &nbsp;·&nbsp; Orientación: <select id="orient">
    <option value="auto" selected>Auto (igual que tu archivo)</option>
    <option value="16:9">16:9 horizontal</option>
    <option value="9:16">9:16 vertical</option>
    <option value="1:1">1:1 cuadrado</option>
  </select></label>
  <div class="sub">480p = ~2-3× más rápido que 768p · 9:16 en 480p = 480×864</div>
  <button id="go" type="submit">Generar video</button>
</form>
<div id="status"></div><div class="bar" id="bar"><div id="barfill"></div></div>
<div id="res"></div>
</div>
<div class="view" id="view-gal">
  <h1>🎬 Galería</h1>
  <div class="sub">Todos los videos generados · clic para abrir en ventana nueva</div>
  <div id="gal"></div>
</div>
</div>
<script>
const $=id=>document.getElementById(id);
function showTab(name){
  $('tab-gen').classList.toggle('active', name==='gen');
  $('tab-gal').classList.toggle('active', name==='gal');
  $('view-gen').classList.toggle('active', name==='gen');
  $('view-gal').classList.toggle('active', name==='gal');
  if(name==='gal') loadGallery();
}
function fmtSize(b){
  if(b>1048576) return (b/1048576).toFixed(1)+' MB';
  if(b>1024) return (b/1024).toFixed(0)+' KB';
  return b+' B';
}
async function loadBalance(){
  const el=$('bal');
  try{
    const j=await (await fetch('/api/balance')).json();
    if(j.credit===undefined){ el.textContent='Saldo n/d'; el.className='bal off'; return; }
    el.textContent='Saldo $'+j.credit.toFixed(2)+(j.hours?' · ~'+j.hours+'h':'');
    el.className='bal '+(j.credit<0.5?'low':j.credit<2?'warn':'ok');
  }catch(e){
    el.textContent='Saldo n/d'; el.className='bal off';
  }
}
loadBalance();
setInterval(loadBalance, 60000);
async function loadGallery(){
  $('gal').innerHTML='<div class="sub">Cargando…</div>';
  try{
    const vids=await (await fetch('/api/gallery')).json();
    if(!vids.length){ $('gal').innerHTML='<div class="sub">Aún no hay videos generados.</div>'; return; }
    $('gal').innerHTML=vids.map(v=>{
      const url='/media/'+v.rel.split('/').map(encodeURIComponent).join('/');
      return '<div class="gitem" data-url="'+url+'">'+
        '<img loading="lazy" src="/thumb/'+v.rel.split('/').map(encodeURIComponent).join('/')+'" alt="'+v.name.replace(/"/g,'&quot;')+'">'+
        '<div class="gname">'+v.name.replace(/"/g,'&quot;')+'</div>'+
        '<div class="gmeta">'+fmtSize(v.size)+' · '+new Date(v.mtime*1000).toLocaleString()+'</div>'+
      '</div>';
    }).join('');
    $('gal').addEventListener('click', e=>{
      const it=e.target.closest('.gitem');
      if(it) window.open(it.dataset.url,'_blank');
    });
  }catch(err){ $('gal').innerHTML='<div class="err">'+err+'</div>'; }
}
// --- múltiples archivos: drop + pegar portapapeles ---
const FILES=[];
const MAXF=5;
function isVidFile(f){ return f && (f.type.startsWith('video/') || /\.(mp4|webm|mov|mkv|avi)$/i.test(f.name)); }
function addFiles(list){
  for(const f of list){
    if(FILES.length>=MAXF) break;
    if(f.type.startsWith('image/')||f.type.startsWith('video/')||isVidFile(f)) FILES.push(f);
  }
  renderPreviews();
}
function renderPreviews(){
  $('previews').innerHTML=FILES.map((f,i)=>{
    const url=URL.createObjectURL(f);
    const tag=isVidFile(f)?'🎬':'🖼';
    return '<div class="pitem"><div class="ptag">'+tag+'</div><button class="px" onclick="removeFile('+i+')">×</button>'+
      (isVidFile(f)?'<video src="'+url+'" muted preload="metadata"></video>':'<img src="'+url+'">')+
      '</div>';
  }).join('');
  $('dropmsg').style.display=FILES.length?'none':'block';
  // bloquear duración cuando hay video
  const hasVid=FILES.some(isVidFile);
  $('dur').disabled=hasVid;
  $('durnote').style.display=hasVid?'inline':'none';
}
function removeFile(i){ FILES.splice(i,1); renderPreviews(); }
$('drop').addEventListener('dragover', e=>{ e.preventDefault(); $('drop').classList.add('dragover'); });
$('drop').addEventListener('dragleave', ()=>$('drop').classList.remove('dragover'));
$('drop').addEventListener('drop', e=>{ e.preventDefault(); $('drop').classList.remove('dragover'); addFiles(e.dataTransfer.files); });
$('file').addEventListener('change', ()=>{ addFiles($('file').files); $('file').value=''; });
// pegar imagen del portapapeles (Ctrl+V, botón, o menú "Pegar" de móvil)
document.addEventListener('paste', e=>{
  const items=(e.clipboardData||{}).items||[];
  const files=[];
  for(const it of items) if(it.type.startsWith('image/')) files.push(it.getAsFile());
  if(files.length) addFiles(files);
});
// zona contenteditable para móvil: permite pegar imágenes donde el textarea NO
// (los navegadores móviles bloquean pegar imágenes en campos de texto)
const pz=document.createElement('div');
pz.contentEditable='true';
pz.style.cssText='position:fixed;left:-9999px;top:0;width:2px;height:2px;opacity:0.01;overflow:hidden';
pz.setAttribute('aria-hidden','true');
document.body.appendChild(pz);
pz.addEventListener('paste', e=>{
  const items=(e.clipboardData||{}).items||[];
  let found=false;
  for(const it of items){
    if(it.type.startsWith('image/')){
      const f=it.getAsFile();
      if(f){ addFiles([f]); found=true; }
    }
  }
  if(!found){
    // navegador pegó <img> interno: capturarla desde su src
    setTimeout(()=>{
      pz.querySelectorAll('img').forEach(im=>{
        const url=im.src;
        if(url.startsWith('blob:')||url.startsWith('data:')){
          fetch(url).then(r=>r.blob()).then(b=>{
            addFiles([new File([b],'pegar_'+Date.now()+'.png',{type:b.type||'image/png'})]);
          }).catch(()=>{});
        }
        im.remove();
      });
    },150);
  }
  pz.innerHTML='';
});
$('pastebtn').addEventListener('click', async ()=>{
  // 1) contexto seguro (https/localhost): API de portapapeles
  if(window.isSecureContext && navigator.clipboard && navigator.clipboard.read){
    try{
      const items=await navigator.clipboard.read();
      const files=[];
      for(const it of items){
        if(it.types.includes('image/png')) files.push(new File([await it.getType('image/png')],'pegar_'+Date.now()+'.png',{type:'image/png'}));
        else if(it.types.includes('image/jpeg')) files.push(new File([await it.getType('image/jpeg')],'pegar_'+Date.now()+'.jpg',{type:'image/jpeg'}));
      }
      if(files.length){ addFiles(files); return; }
    }catch(err){ /* falla silenciosa -> fallback móvil */ }
  }
  // 2) móvil / http: enfocar la zona contenteditable -> el teclado abre con "Pegar"
  pz.innerHTML='';
  pz.focus();
  pz.scrollIntoView({behavior:'smooth', block:'center'});
  const nota=document.createElement('div');
  nota.style.cssText='position:fixed;bottom:90px;left:50%;transform:translateX(-50%);background:#1a1d27;border:1px solid #4f46e5;color:#cbd5e1;padding:8px 14px;border-radius:8px;font-size:12px;z-index:99;pointer-events:none';
  nota.textContent='Toca "Pegar" en el teclado para insertar la imagen';
  document.body.appendChild(nota);
  setTimeout(()=>nota.remove(), 4000);
});
// --- apagar servidor (stop Vast, conserva disco y modelos) ---
async function apagar(){
  if(!confirm('¿Apagar el servidor? Se detiene el cobro de GPU. El disco y los modelos se conservan (puedes reiniciarlo después).')) return;
  const pin=prompt('PIN de apagado (para evitar que cualquiera apague el servidor):');
  if(pin===null) return;
  try{
    const r=await fetch('/shutdown',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'pin='+encodeURIComponent(pin)});
    const j=await r.json();
    if(j.ok){ alert('✔ Servidor apagado. Se detuvo el cobro de GPU. Para volver a encender: abre una sesión conmigo y ejecuto el start.'); }
    else alert('Error: '+(j.error||j.resp||JSON.stringify(j)));
  }catch(e){ alert('Error de red: '+e); }
}
$('f').addEventListener('submit', async e=>{
  e.preventDefault();
  if(!FILES.length) return;
  $('go').disabled=true; $('status').textContent='Subiendo archivo...'; $('bar').style.display='block';
  const fd=new FormData();
  FILES.forEach(f=>fd.append('files',f));
  fd.append('prompt',$('prompt').value); fd.append('mode',$('mode').value); fd.append('duration',$('dur').value); fd.append('quality',$('qual').value); fd.append('orientation',$('orient').value);
  try{
    const r=await fetch('/generate',{method:'POST',body:fd});
    const j=await r.json();
    if(!r.ok){ $('res').innerHTML='<div class="err">'+j.error+'</div>'; return; }
    $('status').textContent='Generando (puede tardar 1-5 min)...';
    const pid=j.prompt_id;
    // poll
    while(true){
      await new Promise(res=>setTimeout(res,2500));
      const s=await (await fetch('/status/'+pid)).json();
      $('barfill').style.width=(s.progress||0)+'%';
      if(s.error){ $('status').innerHTML='<span class="err">'+s.error+'</span>'; break; }
      if(s.done){
        $('status').innerHTML='<span class="ok">✔ Listo</span>';
        $('res').innerHTML='<video controls autoplay loop src="/result/'+pid+'"></video>';
        break;
      }
    }
  }catch(err){ $('res').innerHTML='<div class="err">'+err+'</div>'; }
  finally{ $('go').disabled=false; }
});
</script></body></html>"""

# ---------------- ComfyUI helpers ----------------

def random_seed():
    import random
    return random.randint(0, 2**53 - 1)

def comfy_get(path):
    return requests.get(f"{COMFY}{path}", timeout=15)

def object_info():
    r = comfy_get("/object_info")
    return r.json()

def find_h3_nodes():
    """Detecta nodos H3 disponibles en el servidor (prioriza nativos sobre legacy)."""
    info = object_info()
    native = [n for n in info if n.startswith("MiniMaxH3")]
    if native:
        return native, info
    legacy = [n for n in info if "hailuo" in n.lower() or "minimax" in n.lower()]
    return legacy, info

def upload_file(path_or_bytes, name, filetype):
    """Sube a ComfyUI. El campo multipart SIEMPRE es 'image' (server.py: post.get('image'))."""
    if isinstance(path_or_bytes, (bytes, io.BytesIO)):
        data = path_or_bytes.getvalue() if isinstance(path_or_bytes, io.BytesIO) else path_or_bytes
        files = {"image": (name, data)}
    else:
        files = {"image": (name, open(path_or_bytes, "rb"))}
    r = requests.post(f"{COMFY}/upload/image", files=files,
                      data={"overwrite": "true", "type": "input"}, timeout=180)
    r.raise_for_status()
    return r.json()["name"]

def detect_dims(path, is_vid):
    """Devuelve (w, h) del archivo subido: PIL para imagen, ffprobe para video."""
    try:
        if is_vid:
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", path],
                capture_output=True, text=True, timeout=30)
            if out.returncode == 0 and out.stdout.strip():
                w, h = out.stdout.strip().split("x")
                return int(w), int(h)
        else:
            from PIL import Image as PILImage
            with PILImage.open(path) as im:
                return im.size
    except Exception as e:
        print(f"[h3_web] detect_dims fallo: {e}")
    return None

def detect_duration(path):
    """Devuelve la duración en segundos de un video (ffprobe)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=s=x:p=0", path],
            capture_output=True, text=True, timeout=30)
        if out.returncode == 0 and out.stdout.strip():
            return float(out.stdout.strip())
    except Exception as e:
        print(f"[h3_web] detect_duration fallo: {e}")
    return None

def submit_workflow(workflow):
    r = requests.post(f"{COMFY}/prompt", json={"prompt": workflow, "client_id": CLIENT_ID}, timeout=30)
    r.raise_for_status()
    return r.json()["prompt_id"]

def history(pid):
    r = comfy_get(f"/history/{pid}")
    return r.json()

def progress(pid):
    """Progreso real capturado por el WS de ComfyUI."""
    p = PROGRESS.get(pid, {})
    if p:
        mx = p.get("max", 1) or 1
        return {"value": int(p.get("value", 0) * 100 / mx)}
    return {"value": 0}

# ---------------- rutas web ----------------

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "/opt/workspace-internal/ComfyUI/output")
THUMB_DIR = "/workspace/thumbs"
GEN_FILE = "/workspace/generations.json"   # registro SOLO de lo generado vía esta web
INSTANCE_ID = int(os.environ.get("INSTANCE_ID", "0") or 0)
VAST_KEY = os.environ.get("VAST_API_KEY", "") or (open("/workspace/.env_vast").read().strip() if os.path.exists("/workspace/.env_vast") else "")

def vast_stop():
    """Detiene la instancia Vast (stop): conserva disco, deja de cobrar GPU."""
    if not VAST_KEY or not INSTANCE_ID:
        return {"ok": False, "error": "Sin VAST_API_KEY o INSTANCE_ID configurados"}
    try:
        r = requests.put(
            f"https://console.vast.ai/api/v0/instances/{INSTANCE_ID}/",
            headers={"Authorization": f"Bearer {VAST_KEY}", "Content-Type": "application/json"},
            json={"state": "stopped"}, timeout=30)
        return {"ok": r.status_code == 200, "status": r.status_code, "resp": r.text[:300]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}

@app.route("/shutdown", methods=["POST"])
def shutdown():
    """Apaga el servidor (stop Vast) para no gastar créditos. Requiere PIN."""
    pin = request.form.get("pin", "")
    if pin != os.environ.get("SHUTDOWN_PIN", "H3-APAGAR"):
        return jsonify({"ok": False, "error": "PIN incorrecto"}), 403
    return jsonify(vast_stop())

def load_generations():
    try:
        with open(GEN_FILE) as f:
            return json.load(f)
    except Exception:
        return []

def save_generation(rel):
    """Registra un video completado vía la web (dedupe por ruta relativa)."""
    gens = load_generations()
    if rel not in [g["rel"] for g in gens]:
        full = os.path.join(OUTPUT_DIR, rel)
        gens.append({"rel": rel, "name": os.path.basename(rel),
                     "size": os.path.getsize(full) if os.path.isfile(full) else 0,
                     "mtime": os.path.getmtime(full) if os.path.isfile(full) else time.time()})
        gens.sort(key=lambda g: g["mtime"], reverse=True)
        try:
            with open(GEN_FILE, "w") as f:
                json.dump(gens, f)
        except Exception as e:
            print(f"[h3_web] save_generation fallo: {e}")

def list_videos():
    """Solo los videos generados a través de esta interfaz (registro local)."""
    gens = load_generations()
    out = []
    for g in gens:
        full = os.path.join(OUTPUT_DIR, g["rel"])
        if os.path.isfile(full):
            out.append({"name": g["name"], "rel": g["rel"],
                        "size": os.path.getsize(full), "mtime": os.path.getmtime(full)})
    return out

@app.route("/api/gallery")
def api_gallery():
    return jsonify(list_videos())

@app.route("/api/balance")
def api_balance():
    """Saldo de la cuenta Vast en tiempo real (campo credit, USD)."""
    if not VAST_API_KEY:
        return jsonify({"error": "sin VAST_API_KEY"}), 503
    try:
        r = requests.get("https://console.vast.ai/api/v0/users/current/",
                         headers={"Authorization": f"Bearer {VAST_API_KEY}"}, timeout=15)
        if r.status_code != 200:
            return jsonify({"error": f"HTTP {r.status_code}"}), 502
        credit = r.json().get("credit", 0)
        rate = float(os.environ.get("VAST_RATE_H", "0.40"))
        return jsonify({"credit": credit, "rate": rate,
                        "hours": round(credit / rate, 1) if rate else 0,
                        "ts": time.time()})
    except Exception as e:
        return jsonify({"error": str(e)}), 502

@app.route("/thumb/<path:rel>")
def thumb(rel):
    """Genera (cachea) y sirve una miniatura del video."""
    full = os.path.join(OUTPUT_DIR, rel)
    if not os.path.isfile(full):
        return jsonify({"error": "no encontrado"}), 404
    os.makedirs(THUMB_DIR, exist_ok=True)
    thumb_path = os.path.join(THUMB_DIR, rel.replace("/", "_") + ".jpg")
    if not os.path.exists(thumb_path):
        try:
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "0.3", "-i", full,
                            "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "5", thumb_path],
                           capture_output=True, timeout=20)
        except Exception as e:
            print(f"[h3_web] thumb fallo: {e}")
    if os.path.exists(thumb_path):
        return send_file(thumb_path, mimetype="image/jpeg")
    return jsonify({"error": "sin thumb"}), 404

@app.route("/media/<path:rel>")
def media(rel):
    """Sirve el video directamente desde el disco (misma máquina que ComfyUI)."""
    full = os.path.join(OUTPUT_DIR, rel)
    if not os.path.isfile(full):
        return jsonify({"error": "no encontrado"}), 404
    mime = "video/mp4" if full.endswith(".mp4") else "video/webm" if full.endswith(".webm") else "video/mp4"
    return send_file(full, mimetype=mime, as_attachment=False)

@app.route("/")
def index():
    return render_template_string(HTML, res=RESOLUTION, dur=DURATION)

@app.route("/generate", methods=["POST"])
def generate():
    files = request.files.getlist("files") or ([request.files.get("file")] if request.files.get("file") else [])
    prompt = request.form.get("prompt", "").strip()
    mode = request.form.get("mode", "auto")
    try:
        dur = float(request.form.get("duration", DURATION))
    except ValueError:
        dur = DURATION
    dur = min(max(dur, 1), 15)  # H3: máx ~15s
    orient = request.form.get("orientation", "auto")
    quality = request.form.get("quality", "480")
    # H3: width/height libres (mín 32, step 32) — menor resolución = más rápido
    # 480p: 480x864 (9:16), 832x480 (16:9), 512x512 (1:1)
    # 768p: 768x1344 (9:16), 1344x768 (16:9), 768x768 (1:1)
    W_H = {
        "768": {"16:9": (1344, 768), "9:16": (768, 1344), "1:1": (768, 768)},
        "480": {"16:9": (832, 480), "9:16": (480, 864), "1:1": (512, 512)},
    }
    width, height = W_H.get(quality, W_H["480"]).get(orient, (480, 864))
    if not files or not prompt:
        return jsonify({"error": "Falta archivo o prompt"}), 400
    files = files[:5]

    # clasificar cada archivo
    infos = []
    for f in files:
        name = f.filename or "archivo"
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        is_img = f.content_type.startswith("image/") or ext in ("png","jpg","jpeg","webp","bmp")
        is_vid = f.content_type.startswith("video/") or ext in ("mp4","webm","mov","mkv","avi")
        infos.append({"f": f, "name": name, "is_img": is_img, "is_vid": is_vid})
    if not any(i["is_img"] or i["is_vid"] for i in infos):
        return jsonify({"error": "Formato no soportado (usa imagen o video)"}), 400

    # el primer archivo decide el modo principal
    first = infos[0]
    is_vid = first["is_vid"]
    if mode == "i2v":
        is_vid = False
    elif mode == "v2v":
        is_vid = True

    try:
        nodes, info = find_h3_nodes()
    except Exception as e:
        return jsonify({"error": f"No se pudo contactar ComfyUI: {e}"}), 502

    # elegir nodo
    ref_node = next((n for n in nodes if "Reference" in n), None)
    img_node = next((n for n in nodes if "ImageToVideo" in n), None)
    use_ref = is_vid or len(infos) > 1  # multi-imagen o video -> nodo referencia (omni-reference)
    if use_ref:
        if not ref_node:
            return jsonify({"error": f"El servidor no tiene nodo de referencia. Nodos H3: {nodes}"}), 400
        node_type = ref_node
    else:
        if not img_node:
            return jsonify({"error": f"El servidor no tiene nodo i2v. Nodos H3: {nodes}"}), 400
        node_type = img_node

    # subir archivos (guardar a temp para detectar dims si orient=auto)
    tmp_path = None
    try:
        # subir cada archivo; guardar nombre subido por tipo
        img_names, vid_names, audio_name = [], [], None
        for i, it in enumerate(infos):
            data = it["f"].read()
            is_v = it["is_vid"] or (is_vid and i == 0 and not it["is_img"] and not it["is_vid"])
            is_v = it["is_vid"]
            # orientación auto: detectar dims del PRIMER archivo
            if i == 0 and orient == "auto":
                tmp_path = f"/tmp/h3up_{os.getpid()}_{int(time.time())}_{it['name']}"
                with open(tmp_path, "wb") as tf:
                    tf.write(data)
                dims = detect_dims(tmp_path, it["is_vid"])
                if dims:
                    w, h = dims
                    short_edge = 768 if quality == "768" else 480
                    if w >= h:  # horizontal: height = short_edge
                        height = short_edge
                        width = int(round(short_edge * w / h / 32)) * 32
                    else:  # vertical: width = short_edge
                        width = short_edge
                        height = int(round(short_edge * h / w / 32)) * 32
                    width = max(32, min(width, 1344))
                    height = max(32, min(height, 1344))
            fname = upload_file(data, it["name"], "video" if is_v else "image")
            # audio del primer video (v2v edición) + escalado a 480p si excede
            # (el append a vid_names va DESPUÉS, para que use el video escalado si aplica)
            if i == 0 and is_v:
                if not tmp_path:
                    tmp_path = f"/tmp/h3up_{os.getpid()}_{int(time.time())}_{it['name']}"
                    with open(tmp_path, "wb") as tf:
                        tf.write(data)
                vdur = detect_duration(tmp_path)
                if vdur:
                    dur = min(max(vdur, 1), 15)
                # IMPORTANTE (doc oficial MiniMax H3): reference_videos SOLO se soportan a 480p.
                # Si el video original excede 480p (short edge), escalarlo con ffmpeg ANTES de subirlo.
                dims_v = detect_dims(tmp_path, True)
                if dims_v:
                    vw, vh = dims_v
                    short = min(vw, vh)
                    if short > 480:
                        scaled_path = f"/tmp/h3scaled_{os.getpid()}_{int(time.time())}.mp4"
                        r2 = subprocess.run(
                            ["ffmpeg", "-y", "-v", "error", "-i", tmp_path,
                             "-vf", "scale='min(480,iw)':-2", "-c:v", "libx264", "-preset", "fast",
                             "-crf", "18", "-c:a", "aac", "-b:a", "128k", scaled_path],
                            capture_output=True, timeout=120)
                        if r2.returncode == 0 and os.path.exists(scaled_path) and os.path.getsize(scaled_path) > 1000:
                            with open(scaled_path, "rb") as sf:
                                fname = upload_file(sf.read(), f"scaled_{int(time.time())}.mp4", "video")
                            print(f"[h3_web] video escalado {short}->480p")
                        if os.path.exists(scaled_path):
                            os.remove(scaled_path)
                audio_path = f"/tmp/h3aud_{os.getpid()}_{int(time.time())}.m4a"
                r = subprocess.run(
                    ["ffmpeg", "-y", "-i", tmp_path, "-vn", "-c:a", "aac", "-b:a", "128k", audio_path],
                    capture_output=True, timeout=60)
                if r.returncode == 0 and os.path.exists(audio_path) and os.path.getsize(audio_path) > 1000:
                    try:
                        with open(audio_path, "rb") as af:
                            audio_name = upload_file(af.read(), f"aud_{int(time.time())}.m4a", "audio")
                    except Exception as ae:
                        print(f"[h3_web] audio upload fallo: {ae}")
                if os.path.exists(audio_path):
                    os.remove(audio_path)
            if is_v:
                vid_names.append(fname)
            else:
                img_names.append(fname)
        if not img_names and not vid_names:
            return jsonify({"error": "No se subió ningún archivo válido"}), 400
    except Exception as e:
        return jsonify({"error": f"Error subiendo a ComfyUI: {e}"}), 502
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

    # construir workflow API format — pipeline nativo completo H3
    node_spec_i = info.get(node_type, {}).get("input", {})
    all_inputs = {}
    for grp in ("required", "optional"):
        all_inputs.update(node_spec_i.get(grp, {}))
    length = int(round(dur * 24))  # 24fps; el nodo ajusta a grid 17k+5
    length = max(length, 124)  # mínimo 124 frames (~5s)

    base = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "vae/minimax_h3_video_vae_fp16.safetensors"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "vae/minimax_h3_audio_vae_fp32.safetensors"}},
    }

    # prompt oculto: misma persona/cara/pose/fondo, sin música ni diálogos salvo petición
    # (usa tokens oficiales <Picture 1>/<Video 1> para que el modelo aplique las referencias)
    hidden_p = ("Keep the exact same person, face, pose, framing and background as the input. "
                "Preserve the facial identity and features with high fidelity. "
                "Do not add any other people or persons in the background or scene. "
                "If the person is holding a phone or any object in their hand, remove the object "
                "and show that hand making the peace sign (love and peace hand gesture) in the same position. "
                "Do not add music, dialogue, voices or speech unless explicitly requested "
                "in the user instructions. ")

    if use_ref:
        # nodo ReferenceToVideo con ref_videos y/o ref_images (omni-reference)
        nid = 5
        refs = {}
        # videos -> LoadVideo + ref_videos
        if vid_names:
            if "LoadVideo" not in info:
                return jsonify({"error": "El servidor no tiene nodo LoadVideo para v2v"}), 400
            vid_refs = {}
            for j, vn in enumerate(vid_names, 1):
                # IMPORTANTE: el input de LoadVideo se llama 'file' (COMBO), NO 'video'.
                # Si se manda 'video', ComfyUI ignora el input y carga el primer archivo del combo.
                base[str(nid)] = {"class_type": "LoadVideo", "inputs": {"file": vn}}
                vid_refs[f"ref_video_{j}"] = [str(nid), 0]
                nid += 1
            ref_keys = [k for k in all_inputs if k == "ref_videos" or "reference_videos" in k]
            if not ref_keys:
                return jsonify({"error": f"Nodo {node_type} sin input ref_videos"}), 400
            refs[sorted(ref_keys)[0]] = vid_refs
            if audio_name and "ref_video_audios" in all_inputs:
                base[str(nid)] = {"class_type": "LoadAudio", "inputs": {"audio": audio_name}}
                refs["ref_video_audios"] = {"ref_video_audio_1": [str(nid), 0]}
                nid += 1
        # imágenes -> LoadImage + ref_images
        if img_names:
            img_refs = {}
            for j, iname in enumerate(img_names, 1):
                base[str(nid)] = {"class_type": "LoadImage", "inputs": {"image": iname}}
                img_refs[f"ref_image_{j}"] = [str(nid), 0]
                nid += 1
            img_keys = [k for k in all_inputs if k == "ref_images" or "reference_images" in k]
            if img_keys:
                refs[sorted(img_keys)[0]] = img_refs
            elif not vid_names:
                # sin input ref_images: usar la primera imagen como first_frame
                base["6"] = {
                    "class_type": node_type,
                    "inputs": {
                        "clip": ["2", 0], "vae": ["3", 0], "audio_vae": ["4", 0],
                        "prompt": hidden_p + prompt,
                        "width": width, "height": height, "length": length,
                        "ref_image_size": "match",
                        "first_frame": [str(5), 0],
                    },
                }
        # prompt de edición con tokens de referencia oficiales de H3: <Video 1>, <Picture N>
        # (la API oficial requiere referenciar los inputs como <Video 1>..<Video 3>, <Picture 1>..)
        refs_txt = ""
        if vid_names:
            refs_txt += "".join(f"<Video {j}>" for j in range(1, len(vid_names) + 1))
        if img_names:
            refs_txt += "".join(f"<Picture {j}>" for j in range(1, len(img_names) + 1))
        if not refs_txt:
            refs_txt = "<Video 1>"
        edit_p = (f"Keep the exact same scene, background, person, pose, motion, "
                  f"camera and audio as {refs_txt}, frame by frame. "
                  f"Only apply the requested change to every frame from start to end: " + prompt)
        if not vid_names:
            # i2v multi-imagen: el hidden_p debe referenciar las fotos con sus tokens
            edit_p = hidden_p.replace("as the input", f"as {refs_txt}") + prompt
        base["6"] = {
            "class_type": node_type,
            "inputs": {
                "clip": ["2", 0], "vae": ["3", 0], "audio_vae": ["4", 0],
                "prompt": edit_p, "width": width, "height": height, "length": length,
                "ref_image_size": "match",
            },
        }
        base["6"]["inputs"].update(refs)
    else:
        # i2v simple: ImageToVideo con first_frame
        base["5"] = {"class_type": "LoadImage", "inputs": {"image": img_names[0]}}
        base["6"] = {
            "class_type": node_type,
            "inputs": {
                "clip": ["2", 0], "vae": ["3", 0],
                "prompt": hidden_p + prompt,
                "width": width, "height": height, "length": length,
                "first_frame": ["5", 0],
            },
        }

    base["7"] = {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["6", 0]}}
    base["8"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": ["1", 0], "seed": random_seed(), "steps": STEPS, "cfg": 1.0,
            "sampler_name": "euler", "scheduler": "simple",
            "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["6", 1], "denoise": 1.0,
        },
    }
    base["9"] = {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}}
    base["10"] = {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["8", 0], "vae": ["4", 0]}}
    base["11"] = {"class_type": "CreateVideo", "inputs": {"images": ["9", 0], "fps": 24.0, "audio": ["10", 0]}}
    base["12"] = {"class_type": "SaveVideo", "inputs": {"video": ["11", 0], "filename_prefix": "video/MiniMax_H3", "format": "auto", "codec": "auto"}}
    wf = base

    try:
        pid = submit_workflow(wf)
    except Exception as e:
        return jsonify({"error": f"Error enviando workflow: {e}"}), 502
    return jsonify({"prompt_id": pid, "mode": "v2v" if is_vid else "i2v"})

@app.route("/status/<pid>")
def status(pid):
    try:
        h = history(pid)
    except Exception:
        return jsonify({"done": False, "progress": None})
    if pid not in h:
        p = progress(pid)
        return jsonify({"done": False, "progress": p.get("value", 0)})
    entry = h[pid]
    if entry.get("status", {}).get("status_str") == "error":
        msgs = [o.get("messages", []) for o in entry.get("outputs", {}).values()]
        err = "Error de generación"
        for m in msgs:
            for mm in m:
                if isinstance(mm, list) and mm and isinstance(mm[0], str) and "error" in mm[0].lower():
                    err = str(mm[1])[:400]
        return jsonify({"done": True, "error": err})
    outs = entry.get("outputs", {})
    files = []
    for oid, o in outs.items():
        # ComfyUI 0.32: SaveVideo publica el mp4 bajo 'images' (con animated=true); buscar en todas las claves
        for key in ("videos", "images", "gifs", "files"):
            for f in o.get(key, []):
                fn = f.get("filename", "")
                if fn and fn.lower().endswith((".mp4", ".webm", ".mov", ".mkv", ".gif")):
                    files.append((fn, f.get("subfolder", ""), f.get("type", "output")))
    if files:
        save_generation(files[0][1] + "/" + files[0][0] if files[0][1] else files[0][0])
        return jsonify({"done": True, "file": files[0]})
    return jsonify({"done": True, "error": "Sin archivo de salida"})

@app.route("/result/<pid>")
def result(pid):
    h = history(pid)
    entry = h.get(pid, {})
    for oid, o in entry.get("outputs", {}).items():
        for key in ("videos", "images", "gifs", "files"):
            for f in o.get(key, []):
                fn = f.get("filename", "")
                if not fn or not fn.lower().endswith((".mp4", ".webm", ".mov", ".mkv", ".gif")):
                    continue
                sub, typ = f.get("subfolder", ""), f.get("type", "output")
                r = comfy_get(f"/view?filename={fn}&subfolder={sub}&type={typ}")
                if r.status_code == 200:
                    return send_file(io.BytesIO(r.content), mimetype="video/mp4",
                                     download_name=fn, as_attachment=False)
    return jsonify({"error": "no encontrado"}), 404

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8189"))
    print(f"Interfaz H3 en http://0.0.0.0:{port} (ComfyUI: {COMFY})", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
