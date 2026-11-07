"""Loopback Wyoming bridge for existing local Whisper and Piper services.

This is a Home Assistant Assist transport, NOT an offline Echo replacement.
No cloud fallback, device actions, credentials, or retained audio/transcripts.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import logging
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from wyoming.asr import Transcribe, Transcript
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.error import Error
from wyoming.event import Event
from wyoming.info import AsrModel, AsrProgram, Attribution, Describe, Info, TtsProgram, TtsVoice
from wyoming.server import AsyncEventHandler, AsyncServer
from wyoming.tts import Synthesize

LOG = logging.getLogger("atlas.offline_voice")
MAX_AUDIO_SECONDS = 30
MAX_TEXT = 500


@dataclass(frozen=True)
class Settings:
    whisper_url: str = "http://127.0.0.1:9001"
    piper_bin: str = "/home/rlopez/data/piper/piper"
    piper_model: str = "/home/rlopez/data/piper/voices/es_ES-sharvard-medium.onnx"

    def validate(self) -> None:
        url = urlsplit(self.whisper_url)
        if url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1", "localhost"} or url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}:
            raise ValueError("Whisper must be a credential-free loopback HTTP origin")


class AudioBuffer:
    def __init__(self, start: AudioStart):
        if start.rate not in {8000, 16000, 22050, 24000, 44100, 48000} or start.width != 2 or start.channels != 1:
            raise ValueError("Expected mono signed 16-bit PCM at a supported rate")
        self.start = start
        self.data = bytearray()

    def add(self, chunk: AudioChunk) -> None:
        if (chunk.rate, chunk.width, chunk.channels) != (self.start.rate, self.start.width, self.start.channels):
            raise ValueError("Audio format changed mid-stream")
        if len(chunk.audio) % 2 or len(self.data) + len(chunk.audio) > self.start.rate * 2 * MAX_AUDIO_SECONDS:
            raise ValueError("Malformed or oversized audio stream")
        self.data.extend(chunk.audio)

    def wav(self) -> bytes:
        if not self.data:
            raise ValueError("No audio received")
        out = io.BytesIO()
        with wave.open(out, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(self.start.rate)
            wav.writeframes(self.data)
        return out.getvalue()


def describe() -> Info:
    a = Attribution(name="InnerOS local voice", url="https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026")
    common = dict(attribution=a, installed=True, description="Local only; no cloud fallback", version="1")
    return Info(
        asr=[AsrProgram(name="atlas-local-whisper", models=[AsrModel(name="whisper-local", languages=["es", "en"], **common)], **common)],
        tts=[TtsProgram(name="atlas-local-piper", voices=[TtsVoice(name="es_ES-sharvard-medium", languages=["es_ES"], **common)], **common)],
    )


class Engines:
    def __init__(self, settings: Settings):
        settings.validate()
        self.settings = settings
        self.capacity = asyncio.Semaphore(1)

    async def transcribe(self, audio: bytes, language: str) -> str:
        if language not in {"es", "en"}:
            raise ValueError("Supported transcription languages: es, en")
        async with asyncio.timeout(90):
            async with self.capacity:
                async with httpx.AsyncClient(timeout=60, trust_env=False, follow_redirects=False) as client:
                    response = await client.post(self.settings.whisper_url.rstrip("/") + "/asr", params={"task": "transcribe", "language": language, "output": "json", "vad_filter": "true"}, files={"audio_file": ("command.wav", audio, "audio/wav")})
                    response.raise_for_status()
                    data = response.json()
                    text = data.get("text") if isinstance(data, dict) else None
                    if not isinstance(text, str) or len(text) > 4000:
                        raise ValueError("Unexpected local transcription response")
                    return text.strip()

    def _synthesize(self, text: str) -> bytes:
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            raise ValueError("Speech text must contain 1–500 characters")
        with tempfile.TemporaryDirectory(prefix="atlas-local-tts-") as tmp:
            target = Path(tmp) / "speech.wav"
            subprocess.run([self.settings.piper_bin, "--model", self.settings.piper_model, "--output_file", str(target)], input=text.encode("utf-8"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45, check=True, shell=False)
            audio = target.read_bytes()
            if len(audio) > 16_000_000:
                raise ValueError("TTS output exceeded limit")
            return audio

    async def synthesize(self, text: str) -> bytes:
        async with asyncio.timeout(90):
            async with self.capacity:
                return await asyncio.to_thread(self._synthesize, text)


class Handler(AsyncEventHandler):
    def __init__(self, reader, writer, engines: Engines):
        super().__init__(reader, writer)
        self.engines = engines
        self.audio: AudioBuffer | None = None
        self.language = "es"
        self.transcribing = False

    async def handle_event(self, event: Event) -> bool:
        try:
            if Describe.is_type(event.type):
                await self.write_event(describe().event())
            elif Transcribe.is_type(event.type):
                self.language = Transcribe.from_event(event).language or "es"
                if self.language not in {"es", "en"}:
                    raise ValueError("Unsupported language")
                self.audio = None
                self.transcribing = True
            elif AudioStart.is_type(event.type):
                if not self.transcribing:
                    raise ValueError("Transcribe must precede audio")
                self.audio = AudioBuffer(AudioStart.from_event(event))
            elif AudioChunk.is_type(event.type):
                if self.audio is None:
                    raise ValueError("AudioStart required")
                self.audio.add(AudioChunk.from_event(event))
            elif AudioStop.is_type(event.type):
                if self.audio is None:
                    raise ValueError("AudioStart required")
                wav = self.audio.wav()
                self.audio = None
                self.transcribing = False
                transcript = await self.engines.transcribe(wav, self.language)
                await self.write_event(Transcript(text=transcript, language=self.language).event())
            elif Synthesize.is_type(event.type):
                request = Synthesize.from_event(event)
                if request.voice and request.voice.name not in {None, "es_ES-sharvard-medium"}:
                    raise ValueError("Voice unavailable locally")
                wav_data = await self.engines.synthesize(request.text)
                with wave.open(io.BytesIO(wav_data), "rb") as wav:
                    fmt = dict(rate=wav.getframerate(), width=wav.getsampwidth(), channels=wav.getnchannels())
                    await self.write_event(AudioStart(**fmt).event())
                    while chunk := wav.readframes(2048):
                        await self.write_event(AudioChunk(audio=chunk, **fmt).event())
                    await self.write_event(AudioStop().event())
            return True
        except (ValueError, KeyError, TypeError, httpx.HTTPError, TimeoutError, OSError, subprocess.SubprocessError, wave.Error) as exc:
            self.audio = None
            self.transcribing = False
            # Do not log text, audio, credentials, entity names or provider bodies.
            LOG.warning("Local voice operation failed: %s", type(exc).__name__)
            await self.write_event(Error(text="Local voice unavailable; no cloud fallback was used", code="local_voice_unavailable").event())
            return False


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=10250)
    args = parser.parse_args()
    engines = Engines(Settings())
    server = AsyncServer.from_uri(f"tcp://127.0.0.1:{args.port}")
    LOG.info("Starting loopback-only offline voice bridge")
    await server.run(lambda r, w: Handler(r, w, engines))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
