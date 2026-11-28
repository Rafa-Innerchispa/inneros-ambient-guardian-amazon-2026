# Visual fixtures through the existing compact MCP

The public catalog remains 25 tools. Use `capability_search` to find lighting,
then `capability_invoke` with `lighting.status.v1`, `lighting.power.v1`,
`lighting.dmx.color.v1` or `lighting.dmx.scene.v1`. These retain server-side
owner OAuth checks and the durable request-id execution ledger.

Status now includes an explicit fixture catalog. `power_mapped` and
`power_available` distinguish a configured outlet from a requested but
unlinked device. Never treat an owner-supplied name as a verified HA entity.
Only exact approved entity mappings may actuate, and unknown targets do not
fall back to a master strip, every outlet, or another similarly named device.

Kasa exposes Peces, Plantas, Mural, Central, Esfera Disco and Esfera LED.
The owner identifies Holo Fan01's independent power outlet as Toma TV 01,
and Holo Fan02's as Toma TV 02, in Nexxt Home. Pulpos, black stage lights and
mini lasers use Nexxt's Regleta Luces; their child outlets must be identified
before binding. Nexxt devices are integration_pending until an authenticated
provider supplies real control entities. Their names alone never enable power.

Power commands turn on/off outlets only. DMX color/effect commands do not
energize outlets. A fixture without a verified DMX profile does not inherit
the all-fixtures profile. DMX acknowledgement remains distinct from a human
or sensor verifying the visible output.

Examples: `enciende esfera disco`, `apaga esfera led`, `enciende Fan01`,
`apaga Toma TV 02`; then separately `pon tacho Peces verde por DMX`.
Pending Nexxt bindings must return an explicit unavailable result.

On 27 November the AMD compact profile had lost its three Atlas-owned
startup drop-ins. The immutable extension was restored from its previously
verified release; no managed gateway source or other profile was changed.
Public MCP calls then discovered all four lighting capabilities, read live
states via Intel, and verified both sphere outlets off without actuation.
Use the versioned installer in scripts/install_mcp_lighting_extension.py to
preserve the extension when rebuilding profile configuration; verify the
managed gateway hash first. Do not edit the managed gateway to register it.
