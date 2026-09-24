from __future__ import annotations

import json
import os
from typing import Any


class DMXPowerGate:
    """Verify fixture power through Home Assistant before sending Art-Net.

    The target-to-switch map is intentionally configuration, not inference.
    Unknown targets fail closed whenever enforcement is enabled.
    """

    def __init__(self) -> None:
        self.enabled = os.getenv("AMBIENT_GUARDIAN_DMX_POWER_GATE_ENABLED", "0") == "1"
        raw = os.getenv("AMBIENT_GUARDIAN_DMX_POWER_MAP_JSON", "").strip()
        self.mapping: dict[str, list[str]] = {}
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = {}
            if isinstance(parsed, dict):
                for key, value in parsed.items():
                    if isinstance(value, str):
                        entities = [value]
                    elif isinstance(value, list):
                        entities = [str(item) for item in value]
                    else:
                        continue
                    clean = [
                        item.strip()
                        for item in entities
                        if str(item).strip().startswith("switch.")
                    ]
                    if clean:
                        self.mapping[str(key).strip()] = list(dict.fromkeys(clean))

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "mapped_targets": sorted(self.mapping),
            "mapped_switch_count": len(
                {entity for entities in self.mapping.values() for entity in entities}
            ),
            "policy": "verify-power-before-artnet" if self.enabled else "observe-only",
        }

    def _entities_for_target(self, target: str) -> list[str]:
        target = (target or "").strip()
        if target == "todas":
            return list(
                dict.fromkeys(
                    entity
                    for entities in self.mapping.values()
                    for entity in entities
                )
            )
        return list(self.mapping.get(target) or [])

    def ensure_power(self, target: str, bridge: Any) -> dict[str, Any]:
        if not self.enabled:
            return {
                "ready": True,
                "enforced": False,
                "target": target,
                "detail": "power gate disabled; no switch action attempted",
            }

        entities = self._entities_for_target(target)
        if not entities:
            return {
                "ready": False,
                "enforced": True,
                "target": target,
                "error": "power_mapping_missing",
            }

        observations = []
        for entity_id in entities:
            try:
                before = bridge.get_entity_state(entity_id)
            except Exception:
                return {
                    "ready": False,
                    "enforced": True,
                    "target": target,
                    "entity_id": entity_id,
                    "error": "power_state_unreadable",
                }

            before_state = str(before.get("state") or "")
            if before_state == "unavailable":
                return {
                    "ready": False,
                    "enforced": True,
                    "target": target,
                    "entity_id": entity_id,
                    "error": "power_switch_unavailable",
                    "observed": before,
                }

            changed = False
            if before_state != "on":
                try:
                    result = bridge.control_switch(entity_id, turn_on=True)
                except Exception:
                    return {
                        "ready": False,
                        "enforced": True,
                        "target": target,
                        "entity_id": entity_id,
                        "error": "power_switch_turn_on_failed",
                    }
                if not result.get("verified"):
                    return {
                        "ready": False,
                        "enforced": True,
                        "target": target,
                        "entity_id": entity_id,
                        "error": "power_switch_unverified",
                        "result": result,
                    }
                changed = True
                after = result.get("observed") or {}
            else:
                after = before

            observations.append(
                {
                    "entity_id": entity_id,
                    "before": before_state,
                    "after": after.get("state"),
                    "changed": changed,
                }
            )

        return {
            "ready": True,
            "enforced": True,
            "target": target,
            "switches": observations,
        }
