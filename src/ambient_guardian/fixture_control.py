"""Keep mains switches distinct from open-loop DMX color/effect commands."""
from __future__ import annotations
import re
from typing import Any

ALIASES = {
    'tacho peces': 'tacho_peces', 'fish light': 'tacho_peces',
    'tacho plantas': 'tacho_plantas', 'plant light': 'tacho_plantas',
    'tacho mural': 'tacho_mural', 'wall stage light': 'tacho_mural',
    'tacho central': 'tacho_central', 'central stage light': 'tacho_central',
    'tachos': 'tachos', 'stage lights': 'tachos',
    'pulpos': 'pulpos', 'pulpo': 'pulpos', 'spiders': 'pulpos',
    'esfera led': 'esfera_led', 'esfera disco': 'esfera_disco',
}


def parse_fixture_power(utterance: str) -> dict[str, Any] | None:
    text = ' '.join(utterance.lower().split())
    if re.search(r'\b(?:no|not|never|don\x27t|how|c[oó]mo|puedo|can i)\b', text):
        return None
    # Color/effect requests use the separate DMX path, never energize implicitly.
    if re.search(r'\b(?:dmx|art[ -]?net|color|colores|colors|rainbow|arco\s?iris|blackout|efecto|effect|verde|green|azul|blue|rojo|red|morado|purple)\b', text):
        return None
    on = bool(re.search(r'\b(?:enciende|encender|prende|prender|turn on|switch on)\b', text))
    off = bool(re.search(r'\b(?:apaga|apagar|turn off|switch off)\b', text))
    if on == off:
        return None
    for alias, target in sorted(ALIASES.items(), key=lambda pair:len(pair[0]), reverse=True):
        if re.search(r'\b'+re.escape(alias)+r'\b', text):
            return {'target':target,'turn_on':on,'control_plane':'mains_power'}
    return None


def fixture_power_turn(bridge: Any, request: dict[str, Any], *, english: bool) -> dict[str, Any]:
    target=request['target']
    result=bridge.control_fixture_power(target, turn_on=request['turn_on'])
    verified=result.get('verified',False)
    if verified:
        answer=(f"Power {'on' if request['turn_on'] else 'off'} verified for {target}. DMX colors and effects were not changed." if english
                else f"Alimentación {'encendida' if request['turn_on'] else 'apagada'} y verificada para {target}. No cambié colores ni efectos DMX.")
    else:
        answer=(f"I could not verify power for {target}. {result['reason']}. No DMX command was sent." if english
                else f"No pude verificar la alimentación de {target}. {result['reason']}. No envié ninguna orden DMX.")
    return {'response':{'answer':answer,'status':'all_clear' if verified else 'attention_required',
                        'reasoning_mode':'deterministic-fixture-power'},
            'fixture_power':result,'dmx':None,'prepared_action':None}


def inspect_power_safely(bridge: Any, target: str) -> dict[str, Any]:
    """DMX may operate independently while the HA observation is unavailable."""
    import httpx
    try:
        return bridge.inspect_fixture_power(target)
    except (AttributeError, RuntimeError, ValueError, PermissionError, httpx.HTTPError):
        return {"ok": False, "verified": False, "target": target,
                "reason": "power observation unavailable", "entities": []}
