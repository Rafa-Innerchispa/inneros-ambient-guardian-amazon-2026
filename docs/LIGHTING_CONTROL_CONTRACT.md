# Lighting controls: power is not DMX

| Request | Control plane | What it does |
|---|---|---|
| Enciende / apaga los tachos | Home Assistant/Kasa mains switches | Changes only the four identified tacho outlets and verifies each switch state |
| Cambia los tachos a verde | Art-Net/DMX engine | Changes color/brightness only; no outlet is energized |
| Activa la escena rainbow | Art-Net/DMX engine | Starts an allowlisted effect only; no power switching |
| Enciende los pulpos | Mains switches | Fails explicitly until their power outlet mapping is physically identified |

The four tacho outlets are Peces, Plantas, Mural and Central. Stair lighting, power
strip master, servers, network and aquarium support outlets are excluded. There
is no fallback from an unknown fixture to all switches. Tacho Mural has a known
power outlet but no verified DMX profile; it must not silently become all tachos.
DMX brightness does not establish mains power. A zero/blackout DMX scene does not
remove electrical power. Art-Net acceptance does not verify emitted light.

Separate operations allow a client to execute explicit multi-step requests in
order: power on, verify switch states, then set color. Color requests alone never
authorize power-on. Read-only power observation failures do not prevent independent
DMX control; they are reported as unverified instead.

## Shared owner API and MCP

The typed API is authenticated by the existing owner/skill bridge and never
exposes credentials. Public unauthenticated lighting requests return 401.

- `GET /api/lighting/status`: actual switch states/mappings and DMX engine status.
- `POST /api/lighting/power`: explicit `target`, boolean `turn_on`, `request_id`.
- `POST /api/lighting/dmx`: explicit target/color/brightness OR scene, `request_id`.

Each mutation requires a unique request ID. The private SQLite ledger stores its
receipt. A repeated ID returns the original receipt; conflicting payloads or
uncertain prior attempts do not execute again.

The versioned MCP Small adapter in `integrations/mcp_small` registers:

- `lighting.status.v1`
- `lighting.power.v1`
- `lighting.dmx.color.v1`
- `lighting.dmx.scene.v1`

Only configured owner usernames with a server-validated OAuth write grant are
accepted. User-supplied context cannot impersonate the owner or grant approval.
The adapter calls a fixed loopback API and reads the existing protected bridge
credential only inside Intel. It does not accept IPs, arbitrary HA services or
credential parameters. Install it into the existing MCP runtime and register its
hook without replacing other capabilities. Restart only the compact profile;
leave Muse/IDE, coordination, approvals and Home Assistant untouched.

## Alexa phrases

Four dedicated intents preserve the action verb, target and color independently
of the broad question slot. Examples, after opening Atlas Control:

- Spanish: «Enciende los tachos»; «Apaga los tachos»; «Cambia los tachos a verde».
- English: “Turn on stage lights”; “Turn off stage lights”; “Change stage lights to green”.
- DMX scene: «Activa la escena rainbow» / “Activate DMX scene rainbow”.

Build and verify the development interaction models before claiming these are
available on a physical Echo. A successful simulator result proves NLU/backend
routing, not that a specific physical fixture is correctly addressed.

Known physical gaps from November 26 remain: Plantas showed purple when green was
requested; Pulpos did not light and their mains supply is unmapped. These must be
reported honestly until physical power, channel mode and start address are checked.
