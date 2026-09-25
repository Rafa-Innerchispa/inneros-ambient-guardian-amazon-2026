from ambient_guardian.core import GuardianReasoner, GuardianState
from ambient_guardian.dmx import DMXBridge
from ambient_guardian.orchestration import parse_dmx_command, simulated_alexa_turn


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_dmx_bridge_requires_loopback_and_allowlist(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_DMX_URL", "http://127.0.0.1:18796")
    monkeypatch.setenv("AMBIENT_GUARDIAN_DMX_CONTROL_ENABLED", "1")
    monkeypatch.setenv("AMBIENT_GUARDIAN_DMX_SCENE_ALLOWLIST", "rainbow,chill_lounge")
    monkeypatch.setenv("AMBIENT_GUARDIAN_DMX_TARGET_ALLOWLIST", "todas,tachos")

    posts = []

    def fake_post(url, json, timeout):
        posts.append((url, json, timeout))
        return FakeResponse({"ok": True, "color": json.get("color"), "target": json.get("target")})

    def fake_get(url, timeout):
        return FakeResponse({"ok": True, "status": "online", "fixture_count": 9})

    monkeypatch.setattr("ambient_guardian.dmx.httpx.post", fake_post)
    monkeypatch.setattr("ambient_guardian.dmx.httpx.get", fake_get)

    bridge = DMXBridge()
    result = bridge.apply_color("morado", target="tachos", brightness=180)
    assert result["engine_accepted"] is True
    assert result["physical_verification"] is False
    assert posts[0][1] == {"color": "morado", "target": "tachos", "brightness": 180}

    try:
        bridge.apply_scene("police")
    except PermissionError as exc:
        assert "allowlisted" in str(exc)
    else:
        raise AssertionError("non-allowlisted DMX scene was accepted")


class StubHA:
    light_control_enabled = False
    light_allowlist = set()

    def home_context(self):
        return {"configured": True, "reachable": True, "alarm": None, "detail": "stub"}

    def ensure_dmx_power(self, target):
        return {
            "ok": True,
            "enabled": False,
            "target": target,
            "status": "preflight_disabled",
            "entities": [],
        }


class StubDMX:
    enabled = True
    scene_allowlist = {"rainbow", "chill_lounge", "morado_uv", "blackout"}
    target_allowlist = {"todas", "tachos", "beams", "pulpos", "bola_disco"}

    def apply_scene(self, scene, speed=1.0):
        return {
            "status": "command_accepted",
            "scene": scene,
            "engine_accepted": True,
            "physical_verification": False,
        }

    def apply_color(self, color, target="todas", brightness=255):
        return {
            "status": "command_accepted",
            "color": color,
            "target": target,
            "brightness": brightness,
            "engine_accepted": True,
            "physical_verification": False,
        }


def _state():
    state = GuardianState()
    state.home_assistant = StubHA()
    state.dmx = StubDMX()
    return state


def test_parse_dmx_color_and_target():
    request = parse_dmx_command("pon los tachos morados al 60 percent", _state())
    assert request == {
        "kind": "color",
        "color": "morado",
        "target": "tachos",
        "brightness": 153,
    }


def test_parse_dmx_safe_scene():
    request = parse_dmx_command("activa modo chill lounge", _state())
    assert request == {"kind": "scene", "scene": "chill_lounge"}


def test_alexa_turn_executes_dmx_without_claiming_physical_verification():
    result = simulated_alexa_turn("pon los beams azules", _state(), GuardianReasoner())
    assert result["prepared_action"] is None
    assert result["dmx"]["engine_accepted"] is True
    assert result["dmx"]["physical_verification"] is False
    assert result["dmx_power"]["target"] == "beams"
    assert "accepted" in result["response"]["answer"].lower()


def test_dmx_power_preflight_blocks_artnet_when_power_unverified():
    class FailingHA(StubHA):
        def ensure_dmx_power(self, target):
            raise RuntimeError("fixture power unavailable")

    state = _state()
    state.home_assistant = FailingHA()
    result = simulated_alexa_turn("pon los tachos rojos", state, GuardianReasoner())
    assert result["dmx"] is None
    assert result["dmx_error"] == "RuntimeError"
    assert "did not send" in result["response"]["answer"].lower()


def test_blackout_does_not_power_on_fixtures():
    class NoPowerHA(StubHA):
        def ensure_dmx_power(self, target):
            raise AssertionError("blackout must not energize fixture power")

    state = _state()
    state.home_assistant = NoPowerHA()
    result = simulated_alexa_turn("activa blackout", state, GuardianReasoner())
    assert result["dmx"]["scene"] == "blackout"
    assert result["dmx_power"] is None
