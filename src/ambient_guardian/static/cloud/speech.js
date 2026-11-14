"use strict";
let voiceRecorder=null,voiceStream=null,voiceTimer=null,voiceCancelled=false,lastSpokenAnswer='';
const MAX_BROWSER_AUDIO=196608;
function voiceControls(){
  el('record-voice').disabled=(!connected||busy)&&!voiceRecorder;
  el('listen-answer').disabled=!lastSpokenAnswer||busy||!('speechSynthesis' in window);
  el('voice-language').disabled=busy||Boolean(voiceRecorder);
  if(voiceRecorder){for(const id of ['ask','site','engine','chat-mode','conversation','new-chat'])el(id).disabled=true;}
}
function releaseMicrophone(){if(voiceStream){for(const track of voiceStream.getTracks())track.stop();voiceStream=null;}clearTimeout(voiceTimer);voiceTimer=null;}
function cancelAudio(){voiceCancelled=true;if(voiceRecorder&&voiceRecorder.state!=='inactive')voiceRecorder.stop();releaseMicrophone();if('speechSynthesis' in window)speechSynthesis.cancel();el('listen-answer').textContent='Escuchar';}
el('cancel-voice').onclick=()=>{cancelAudio();el('voice-status').textContent='Audio cancelado. No se envió una grabación para transcribir.';};
el('record-voice').onclick=async()=>{
  if(voiceRecorder){if(voiceRecorder.state!=='inactive')voiceRecorder.stop();return;}
  if(!connected||busy)return;
  if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder){el('voice-status').textContent='Este navegador no permite grabar audio. Abre os.innerchispa.us en un navegador compatible con micrófono.';return;}
  const epoch=session,site=el('site').value,language=el('voice-language').value;
  voiceCancelled=false;el('record-voice').disabled=true;
  if('speechSynthesis' in window)speechSynthesis.cancel();
  try{
    voiceStream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true}});
    if(epoch!==session||!connected){releaseMicrophone();return;}
    const mime=['audio/webm;codecs=opus','audio/ogg;codecs=opus','audio/mp4'].find(type=>MediaRecorder.isTypeSupported(type));
    const recorder=new MediaRecorder(voiceStream,{...(mime?{mimeType:mime}:{}),audioBitsPerSecond:24000});
    voiceRecorder=recorder;let chunks=[],size=0;
    recorder.ondataavailable=event=>{if(event.data.size){chunks.push(event.data);size+=event.data.size;if(size>MAX_BROWSER_AUDIO){voiceCancelled=true;recorder.stop();el('voice-status').textContent='La grabación superó el límite. Prueba una frase más corta.';}}};
    recorder.onerror=()=>{cancelAudio();el('voice-status').textContent='No se pudo grabar el audio. Comprueba el permiso del micrófono.';};
    recorder.onstop=async()=>{
      releaseMicrophone();voiceRecorder=null;el('record-voice').classList.remove('recording');el('record-voice').textContent='Hablar';el('cancel-voice').hidden=true;
      if(voiceCancelled||epoch!==session||!connected){chunks=[];controls();return;}
      const audio=new Blob(chunks,{type:recorder.mimeType||mime||'audio/webm'});chunks=[];
      if(audio.size<128||audio.size>MAX_BROWSER_AUDIO){el('voice-status').textContent='No se obtuvo un clip válido. Prueba una frase breve.';controls();return;}
      busy=true;controls();el('voice-status').textContent='Transcribiendo con Whisper local. El audio no se guardará en el historial.';
      try{
        const {headers}=context();
        const r=await fetch('/api/sites/'+encodeURIComponent(site)+'/transcribe?language='+language,{method:'POST',headers:{...headers,'Content-Type':audio.type},body:audio,cache:'no-store'});
        const d=await r.json();if(!r.ok)throw Error(errors[d.error]||'No se pudo transcribir. No se usó ningún servicio de pago.');
        if(epoch!==session)return;
        const combined=[el('question').value.trim(),d.text].filter(Boolean).join(' ');
        if(combined.length>4000)throw Error('El texto supera los 4.000 caracteres. Reduce el borrador antes de volver a dictar.');
        el('question').value=combined;el('voice-status').textContent='Whisper local terminó. Revisa el texto y pulsa Consultar cuando quieras enviarlo.';el('question').focus();
      }catch(e){if(epoch===session)el('voice-status').textContent=e.message;}
      finally{busy=false;controls();}
    };
    recorder.start(250);voiceTimer=setTimeout(()=>{if(recorder.state!=='inactive')recorder.stop();},12000);
    el('record-voice').textContent='Detener';el('record-voice').classList.add('recording');el('record-voice').disabled=false;el('cancel-voice').hidden=false;
    el('voice-status').textContent='Escuchando · máximo 12 segundos. Pulsa Detener para transcribir o Cancelar para descartar.';voiceControls();
  }catch(e){releaseMicrophone();voiceRecorder=null;el('voice-status').textContent=e.name==='NotAllowedError'?'Autoriza el micrófono para os.innerchispa.us en el navegador. No se ha enviado audio.':'No se pudo abrir el micrófono. Comprueba que esté disponible.';voiceControls();}
};
el('listen-answer').onclick=()=>{
  if(!lastSpokenAnswer||!('speechSynthesis' in window))return;
  if(speechSynthesis.speaking){speechSynthesis.cancel();el('listen-answer').textContent='Escuchar';return;}
  const language=el('voice-language').value;
  const voice=speechSynthesis.getVoices().find(v=>v.localService&&v.lang.toLowerCase().startsWith(language));
  if(!voice){el('voice-status').textContent='Este navegador no ofrece una voz local para el idioma elegido. No se utilizará una voz de pago.';return;}
  const text=lastSpokenAnswer.replace(/```[\s\S]*?```/g,'Bloque de código disponible en pantalla.').replace(/\*\*/g,'');
  const utterance=new SpeechSynthesisUtterance(text);utterance.voice=voice;utterance.lang=voice.lang;utterance.rate=1;
  utterance.onend=utterance.onerror=()=>el('listen-answer').textContent='Escuchar';
  speechSynthesis.speak(utterance);el('listen-answer').textContent='Detener voz';el('voice-status').textContent='Lectura con voz local del dispositivo: '+voice.name+'.';
};
document.addEventListener('inneros-controls',voiceControls);
document.addEventListener('inneros-answer',event=>{lastSpokenAnswer=event.detail.text||'';voiceControls();});
document.addEventListener('inneros-workspace',()=>{cancelAudio();lastSpokenAnswer='';voiceControls();});
document.addEventListener('visibilitychange',()=>{if(document.hidden)cancelAudio();});
window.addEventListener('beforeunload',cancelAudio);
voiceControls();
