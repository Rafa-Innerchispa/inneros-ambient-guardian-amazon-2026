"""Bounded browser audio to the existing private Whisper. No recording persistence."""
from __future__ import annotations

import asyncio
import base64
import io
import subprocess
import wave

import httpx

MAX_AUDIO = 196608
MIMES = {'audio/webm','audio/ogg','audio/mp4','audio/wav'}


def decode_clip(audio: bytes) -> bytes:
    # A file received from the browser cannot introduce URLs or local-file reads.
    decoded = subprocess.run([
        'ffmpeg','-hide_banner','-loglevel','error','-nostdin',
        '-protocol_whitelist','pipe','-max_alloc','16777216',
        '-i','pipe:0','-t','12','-vn','-ac','1','-ar','16000','-f','wav','pipe:1',
    ], input=audio, capture_output=True, timeout=8, check=True, shell=False).stdout
    if len(decoded) > 400000:
        raise ValueError('decoded_audio_too_large')
    with wave.open(io.BytesIO(decoded),'rb') as source:
        if source.getnchannels()!=1 or source.getsampwidth()!=2 or source.getframerate()!=16000:
            raise ValueError('invalid_decoded_audio')
        pcm=source.readframes(12*16000)
    if len(pcm)<3200:
        raise ValueError('audio_too_short')
    output=io.BytesIO()
    with wave.open(output,'wb') as target:
        target.setnchannels(1);target.setsampwidth(2);target.setframerate(16000);target.writeframes(pcm)
    return output.getvalue()


async def local_transcribe(payload: dict, *, transport=None, decoder=decode_clip):
    if not isinstance(payload,dict) or payload.get('mime') not in MIMES or payload.get('language') not in {'es','en'}:
        raise ValueError('invalid_audio_request')
    encoded=payload.get('audio','')
    if not isinstance(encoded,str) or len(encoded)>4*((MAX_AUDIO+2)//3):
        raise ValueError('invalid_audio_size')
    audio=base64.b64decode(encoded,validate=True)
    if not 128<=len(audio)<=MAX_AUDIO:
        raise ValueError('invalid_audio_size')
    wav=await asyncio.to_thread(decoder,audio)
    async with httpx.AsyncClient(timeout=25,trust_env=False,follow_redirects=False,transport=transport) as client:
        response=await client.post('http://127.0.0.1:9001/asr',
            params={'task':'transcribe','output':'json','language':payload['language'],'vad_filter':'true',
                    'initial_prompt':'Ralfi IA, InnerOS, Wi-Fi, UniFi, Bellini, AMD, Python, JavaScript.'},
            files={'audio_file':('browser-utterance.wav',wav,'audio/wav')})
        response.raise_for_status()
        if len(response.content)>65536:
            raise ValueError('oversized_transcript')
        result=response.json()
    segments=result.get('segments') or []
    if segments and all(float(x.get('no_speech_prob',0))>.8 for x in segments):
        raise ValueError('no_speech')
    text=' '.join(str(result.get('text') or '').split())
    if not text or len(text)>4000:
        raise ValueError('empty_or_oversized_transcript')
    return {'ok':True,'text':text,'language':payload['language']}
