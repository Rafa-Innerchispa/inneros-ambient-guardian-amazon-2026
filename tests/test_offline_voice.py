import io
import wave
from unittest.mock import AsyncMock

import pytest
pytest.importorskip("wyoming")
from wyoming.audio import AudioStart, AudioChunk
from wyoming.asr import Transcribe
from wyoming.event import Event
from ambient_guardian.offline_voice import AudioBuffer, Settings, Handler, describe


def test_local_origins_only():
    Settings().validate()
    for url in ("https://example.com", "http://192.168.1.5", "http://localhost@evil.example", "http://localhost:9001/asr", "http://localhost?proxy=evil", "http://localhost#evil"):
        with pytest.raises(ValueError): Settings(whisper_url=url).validate()


def test_audio_roundtrip_and_limits():
    b = AudioBuffer(AudioStart(rate=16000, width=2, channels=1))
    b.add(AudioChunk(rate=16000, width=2, channels=1, audio=b"\0\0" * 160))
    with wave.open(io.BytesIO(b.wav()), "rb") as wav:
        assert (wav.getframerate(), wav.getnframes()) == (16000, 160)
    for chunk in (AudioChunk(rate=8000, width=2, channels=1, audio=b"\0\0"), AudioChunk(rate=16000, width=2, channels=1, audio=b"\0"), AudioChunk(rate=16000, width=2, channels=1, audio=b"\0" * 960002)):
        with pytest.raises(ValueError): b.add(chunk)


def test_empty_audio_and_stereo_fail():
    with pytest.raises(ValueError): AudioBuffer(AudioStart(rate=16000, width=2, channels=2))
    with pytest.raises(ValueError): AudioBuffer(AudioStart(rate=16000, width=2, channels=1)).wav()


def test_info_exposes_only_installed_local_models():
    info = describe()
    assert info.asr[0].models[0].languages == ["es", "en"]
    assert info.tts[0].voices[0].name == "es_ES-sharvard-medium"
    assert not info.handle and not info.intent


def test_protocol_rejects_audio_without_transcribe():
    import asyncio
    handler = Handler(None, None, None)
    handler.write_event = AsyncMock()
    assert asyncio.run(handler.handle_event(AudioStart(rate=16000, width=2, channels=1).event())) is False
    assert handler.write_event.call_args.args[0].type == "error"


def test_protocol_resets_and_describes():
    import asyncio
    handler = Handler(None, None, None)
    handler.write_event = AsyncMock()
    assert asyncio.run(handler.handle_event(Transcribe(language="es").event()))
    assert handler.transcribing
    assert asyncio.run(handler.handle_event(Event(type="describe")))
    assert handler.write_event.call_args.args[0].type == "info"
