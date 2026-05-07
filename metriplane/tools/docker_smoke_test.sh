#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

fail() {
  echo "[smoke] FAIL: $*" >&2
  echo "[smoke] docker compose ps:" >&2
  docker compose --profile demo ps || true
  echo "[smoke] last logs:" >&2
  docker compose --profile demo logs --tail=200 metriplane_demo || true
  ./tools/docker_clean.sh || true
  exit 1
}

./tools/docker_clean.sh

echo "[smoke] starting demo profile..."
docker compose --profile demo up -d --build || fail "compose up failed"

# wait for metrics
echo "[smoke] waiting for metrics..."
ok=0
for i in $(seq 1 120); do
  if curl -fsS http://localhost:8000/metrics >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 0.2
done
[[ "$ok" -eq 1 ]] || fail "metrics never became ready on :8000"

# wait for ws listener (best-effort)
echo "[smoke] waiting for ws port..."
ok=0
for i in $(seq 1 120); do
  if ss -lnt 2>/dev/null | grep -q ':8765'; then
    ok=1
    break
  fi
  sleep 0.2
done
[[ "$ok" -eq 1 ]] || fail "ws port never opened on :8765"

# websocket receive proof
echo "[smoke] websocket receive proof..."
python3 - <<'PY' || exit 2
import asyncio, websockets
async def main():
    async with websockets.connect("ws://localhost:8765") as ws:
        msg = await ws.recv()
        assert msg and len(msg) > 10
        print(msg[:200])
asyncio.run(main())
PY

echo "[smoke] PASS"

./tools/docker_clean.sh
