#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
# SPDX-License-Identifier: MIT

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -z "${METRIPLANE_WS_AUTH_TOKEN:-}" ]]; then
  METRIPLANE_WS_AUTH_TOKEN="$(openssl rand -hex 32)"
  export METRIPLANE_WS_AUTH_TOKEN
fi
if [[ -z "${METRIPLANE_METRICS_AUTH_TOKEN:-}" ]]; then
  METRIPLANE_METRICS_AUTH_TOKEN="$(openssl rand -hex 32)"
  export METRIPLANE_METRICS_AUTH_TOKEN
fi

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

echo "[smoke] verifying nonroot confinement..."
container_id="$(docker compose --profile demo ps -q metriplane_demo)"
[[ -n "$container_id" ]] || fail "demo container identity missing"
[[ "$(docker inspect --format '{{.Config.User}}' "$container_id")" == "10001:10001" ]] \
  || fail "container user is not 10001:10001"
[[ "$(docker inspect --format '{{.HostConfig.ReadonlyRootfs}}' "$container_id")" == "true" ]] \
  || fail "root filesystem is not read-only"
docker inspect --format '{{json .HostConfig.CapDrop}}' "$container_id" | grep -q '"ALL"' \
  || fail "all Linux capabilities are not dropped"
docker inspect --format '{{json .HostConfig.SecurityOpt}}' "$container_id" \
  | grep -q 'no-new-privileges:true' || fail "no-new-privileges is absent"
[[ "$(docker exec "$container_id" id -u)" == "10001" ]] || fail "runtime process is root"

# wait for metrics
echo "[smoke] waiting for metrics..."
ok=0
for i in $(seq 1 120); do
  if curl -fsS -H "Authorization: Bearer ${METRIPLANE_METRICS_AUTH_TOKEN}" \
    http://localhost:8000/metrics >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 0.2
done
[[ "$ok" -eq 1 ]] || fail "metrics never became ready on :8000"
[[ "$(curl -sS -o /dev/null -w '%{http_code}' http://localhost:8000/metrics)" == "401" ]] \
  || fail "metrics endpoint accepted an unauthenticated request"

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
import asyncio, os, websockets
from websockets.exceptions import InvalidStatus
async def main():
    try:
        async with websockets.connect("ws://localhost:8765"):
            raise AssertionError("websocket accepted an unauthenticated client")
    except InvalidStatus as exc:
        assert exc.response.status_code == 401
    headers = {"Authorization": f"Bearer {os.environ['METRIPLANE_WS_AUTH_TOKEN']}"}
    async with websockets.connect("ws://localhost:8765", additional_headers=headers) as ws:
        msg = await ws.recv()
        assert msg and len(msg) > 10
        print(msg[:200])
asyncio.run(main())
PY

echo "[smoke] PASS"

./tools/docker_clean.sh
