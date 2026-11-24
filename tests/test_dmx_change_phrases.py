import pytest
from ambient_guardian.orchestration import parse_dmx_command
from test_alexa_dmx_bridge import _state


@pytest.mark.parametrize('phrase',[
    'cambia todo el DMX a verde',
    'cambiar los tachos a verde',
    'change the DMX lights to green',
])
def test_owner_change_color_requests_reach_dmx(phrase):
    command=parse_dmx_command(phrase,_state())
    assert command['kind']=='color' and command['color']=='verde'


@pytest.mark.parametrize('phrase',[
    'cambia el efecto de todo el DMX a rainbow',
    'change the lighting effect to rainbow',
])
def test_owner_change_effect_requests_reach_dmx(phrase):
    assert parse_dmx_command(phrase,_state())=={'kind':'scene','scene':'rainbow'}


@pytest.mark.parametrize('phrase',[
    'cómo puedo cambiar los tachos a verde',
    'qué puedo cambiar del DMX a verde',
    'how can I change the DMX lights to green',
])
def test_instructions_question_is_not_a_physical_command(phrase):
    assert parse_dmx_command(phrase,_state()) is None
