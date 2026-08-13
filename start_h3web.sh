#!/bin/bash
# Arranca la interfaz web H3 de forma persistente
export PATH=/opt/miniforge3/bin:$PATH
export COMFY_URL=http://127.0.0.1:18188
export PORT=18189
cd /workspace
pkill -9 -f h3_web.py 2>/dev/null
sleep 1
setsid nohup python h3_web.py > /workspace/h3web.log 2>&1 < /dev/null &
disown
sleep 5
echo "PID: $(pgrep -f h3_web.py)"
curl -s -o /dev/null -w "HTTP: %{http_code}\n" --max-time 8 http://127.0.0.1:18189/
