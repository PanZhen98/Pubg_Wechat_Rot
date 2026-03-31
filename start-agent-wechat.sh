#!/bin/bash
# Start or restart agent-wechat container with proper capabilities
set -e

TOKEN_FILE="/root/.config/agent-wechat/token"
CONTAINER_NAME="agent-wechat"
IMAGE="ghcr.io/thisnick/agent-wechat:0.11.12"

# Stop and remove existing container if running
docker stop "$CONTAINER_NAME" 2>/dev/null || true
docker rm "$CONTAINER_NAME" 2>/dev/null || true

# Start container with SYS_PTRACE capability
docker run -d \
  --name "$CONTAINER_NAME" \
   \
  --cap-add SYS_PTRACE \
  --security-opt seccomp=unconfined \
  -p 127.0.0.1:5900:5900 \
  -p 6174:6174 \
  -v agent-wechat-data:/data \
  -v agent-wechat-wechat-home:/home/wechat \
  -v /opt/entrypoint-rw.sh:/entrypoint.sh:ro \
  -v "$TOKEN_FILE":/data/auth-token:ro \
  -e DISPLAY=:99 \
  -e AGENT_DB_PATH=/data/agent.db \
  -e AGENT_PORT=6174 \
  -e LANG=en_US.UTF-8 \
  -e LC_ALL=en_US.UTF-8 \
  -e DEBIAN_FRONTEND=noninteractive \
  "$IMAGE"

echo "Container started, waiting for agent-server..."
# Wait for agent-server to be ready
for i in $(seq 1 60); do
  if curl -sf http://localhost:6174/api/status >/dev/null 2>&1; then
    echo "Agent server ready"
    break
  fi
  sleep 2
done

echo "Waiting for WeChat to load..."
sleep 30

# Run login WebSocket to extract keys
TOKEN=$(cat "$TOKEN_FILE")
python3 << 'PYEOF'
import asyncio, websockets, json, sys

async def login():
    token = open('/root/.config/agent-wechat/token').read().strip()
    uri = 'ws://localhost:6174/api/ws/login'
    headers = {'Authorization': f'Bearer {token}'}
    for attempt in range(5):
        try:
            async with websockets.connect(uri, additional_headers=headers, open_timeout=30) as ws:
                print(f'Login WebSocket connected (attempt {attempt+1})', flush=True)
                for i in range(120):
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        data = json.loads(msg)
                        print(f'  {data}', flush=True)
                        if data.get('type') == 'login_success':
                            print('Login successful!', flush=True)
                            return True
                        if data.get('type') in ('error', 'timeout'):
                            print(f'Login failed: {data}', flush=True)
                            break
                    except asyncio.TimeoutError:
                        pass
        except Exception as e:
            print(f'Error: {e}', flush=True)
        print('Retrying in 10s...', flush=True)
        await asyncio.sleep(10)
    return False

success = asyncio.run(login())
sys.exit(0 if success else 1)
PYEOF
