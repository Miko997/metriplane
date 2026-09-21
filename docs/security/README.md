# Security engineering notes

- [Dependency pinning boundary](pinned-dependencies.md)

## Streaming and observability listeners

WebSocket, metrics, and health listeners default to numeric loopback addresses. A
non-loopback address, including `0.0.0.0` or a hostname, fails before listening unless
`METRIPLANE_WS_AUTH_TOKEN` or `METRIPLANE_METRICS_AUTH_TOKEN`, respectively, is a
non-empty environment variable. Clients then send `Authorization: Bearer <token>`. The
token value belongs only in the process environment or an external secret provider.

WebSocket connections also have fixed bounds of 1 MiB per frame, 32 concurrent clients,
eight queued outgoing frames per client, and 60 messages per second per client. A slow
client gets the latest bounded state rather than an unbounded backlog. Oversized frames,
excess clients, invalid credentials, and excess inbound rates fail closed.

The shipped Compose services run as UID/GID `10001:10001`, drop every Linux capability,
set `no-new-privileges`, use a read-only root filesystem, and provide a constrained
temporary filesystem. Live-camera services receive only their declared device mappings
and the configured video group; they do not use privileged mode or root.
