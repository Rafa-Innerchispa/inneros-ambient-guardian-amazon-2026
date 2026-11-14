"use strict";
let activeConversation=null;
function chatControls(){
  const saved=connected&&cookieSession;
  for(const id of ['export-chat','archive-chat','reload-chat'])el(id).disabled=!saved||!activeConversation||busy;
  el('new-chat').disabled=!saved||busy;el('show-archived').disabled=!saved||busy;
  if(activeConversation?.archived)el('ask').disabled=true;
}
function modeDescription(){
  const coding=el('chat-mode').value==='coding';
  document.body.classList.toggle('mode-coding',coding);
  el('mode-description').textContent=coding?'Explica, redacta y revisa el código que compartas. Sin terminal, acceso a repositorios ni ejecución de comandos.':'Usa las lecturas seleccionadas. No tiene acceso general a toda la base de datos ni ejecuta cambios.';
}
function downloadFile(text,name,type){
  const url=URL.createObjectURL(new Blob([text],{type}));
  const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function formatMessage(target,text){
  const blocks=String(text).split(/```/);
  blocks.forEach((block,index)=>{
    if(index%2===0){const p=document.createElement('p');p.textContent=block.replace(/\*\*/g,'');target.append(p);return;}
    const newline=block.indexOf('\n');
    const language=newline>=0?block.slice(0,newline).trim().replace(/[^a-z0-9_+-]/gi,''):'';
    const code=newline>=0?block.slice(newline+1):block;
    const pre=document.createElement('pre'),element=document.createElement('code');element.textContent=code;pre.append(element);target.append(pre);
    const actions=document.createElement('div');actions.className='code-actions';
    const copy=document.createElement('button');copy.type='button';copy.textContent='Copiar código';
    copy.onclick=async()=>{try{await navigator.clipboard.writeText(code);copy.textContent='Copiado';}catch{copy.textContent='Selecciona el código para copiar';}};
    const save=document.createElement('button');save.type='button';save.textContent='Descargar borrador';
    save.onclick=()=>downloadFile(code,'ralfi-borrador.'+({python:'py',javascript:'js',typescript:'ts',json:'json',html:'html',css:'css',bash:'sh'}[language]||'txt'),'text/plain;charset=utf-8');
    actions.append(copy,save);target.append(actions);
  });
}
function bubble(role,text,meta){
  const article=document.createElement('article');article.className='chat-message '+role;
  const heading=document.createElement('div');heading.className='message-meta';
  const name=document.createElement('strong');name.textContent=role==='user'?'TÚ':'RALFI IA';
  const detail=document.createElement('span');detail.textContent=meta||'';heading.append(name,detail);
  const body=document.createElement('div');body.className='message-body';formatMessage(body,text);article.append(heading,body);el('chat-messages').append(article);
}
function renderConversation(value){
  el('chat-messages').replaceChildren();let latest='',lastCompleted=null;
  for(const turn of value.turns||[]){
    bubble('user',turn.question,new Date(turn.created*1000).toLocaleString());
    const answer=turn.state==='pending'?'La respuesta está pendiente o no quedó confirmada. Actualiza el historial antes de reenviar.':turn.state==='failed'?(errors[turn.answer]||'La consulta no se completó. No hubo reintento automático.'):turn.answer;
    bubble('assistant',answer,turn.provider==='amd-local'?'AMD local':turn.provider==='vultr-serverless'?'Vultr · pago':turn.state==='pending'?'Pendiente':'Sin respuesta confirmada');
    if(turn.state==='completed'){latest=turn.answer;lastCompleted=turn;}
  }
  if(!(value.turns||[]).length){const p=document.createElement('p');p.className='caption';p.textContent='Esta conversación todavía no tiene mensajes.';el('chat-messages').append(p);}
  el('chat-messages').scrollTop=el('chat-messages').scrollHeight;
  if(lastCompleted){el('provider').textContent=lastCompleted.provider==='amd-local'?'AMD local · sin tokens externos':lastCompleted.provider==='vultr-serverless'?'Vultr · consulta de pago':lastCompleted.provider;el('answer').textContent='Esta respuesta está guardada en tu historial. La evidencia corresponde a ese turno.';el('receipt').textContent=JSON.stringify({provider:lastCompleted.provider,...lastCompleted.usage,recorded_at:new Date(lastCompleted.created*1000).toISOString(),history_saved:true,physical_actions_available:false},null,2);el('receipt-details').hidden=false;}
  document.dispatchEvent(new CustomEvent('inneros-answer',{detail:{text:latest}}));
}
function resetChat(){activeConversation=null;el('conversation').value='';el('chat-messages').replaceChildren();const welcome=document.createElement('div');welcome.className='chat-welcome';const heading=document.createElement('h3');heading.textContent=el('chat-mode').value==='coding'?'¿Qué quieres construir?':'¿Qué quieres saber de tus sistemas?';const note=document.createElement('p');note.textContent='Escribe o dicta un mensaje. Tus conversaciones guardadas están en la lista superior.';welcome.append(heading,note);el('chat-messages').append(welcome);el('question').value='';clearAnswer();chatControls();document.dispatchEvent(new CustomEvent('inneros-answer',{detail:{text:''}}));}
async function loadHistory(){
  if(!connected||!cookieSession){el('conversation').replaceChildren(new Option('Inicia sesión para guardar',''));el('history-status').textContent='Inicia sesión con tu cuenta para guardar conversaciones.';chatControls();return;}
  const epoch=session,selected=activeConversation?.id||'';
  const data=await api('/conversations'+(el('show-archived').checked?'?archived=true':''));if(epoch!==session)return;
  el('conversation').replaceChildren(new Option(el('show-archived').checked?'Elige una conversación archivada':'Nueva conversación',''));
  for(const row of data.conversations){const option=new Option(row.title,row.id);el('conversation').append(option);}
  if(data.conversations.some(row=>row.id===selected))el('conversation').value=selected;
  el('history-status').textContent='Historial privado en tu cuenta de Vultr · se usan los últimos dos turnos como contexto.';chatControls();
}
async function reloadConversation(){
  if(!activeConversation)return;const epoch=session,id=activeConversation.id;
  const d=await api('/conversations/'+id);if(epoch!==session||id!==activeConversation?.id)return;
  activeConversation=d.conversation;el('chat-mode').value=activeConversation.mode;modeDescription();renderConversation(activeConversation);
  el('archive-chat').textContent=activeConversation.archived?'Restaurar':'Archivar';chatControls();
}
el('conversation').onchange=async()=>{
  const id=el('conversation').value;if(!id){resetChat();return;}
  activeConversation={id};try{await reloadConversation();}catch(e){el('history-status').textContent=e.message;}
};
el('new-chat').onclick=()=>{resetChat();el('show-archived').checked=false;loadHistory().catch(e=>el('history-status').textContent=e.message);el('question').focus();};
el('chat-mode').onchange=()=>{const draft=el('question').value;resetChat();el('question').value=draft;modeDescription();};
el('show-archived').onchange=()=>{resetChat();loadHistory().catch(e=>el('history-status').textContent=e.message);};
el('reload-chat').onclick=()=>reloadConversation().catch(e=>el('history-status').textContent=e.message);
el('export-chat').onclick=()=>{if(activeConversation)downloadFile(JSON.stringify(activeConversation,null,2),'ralfi-conversacion-'+activeConversation.id.slice(0,8)+'.json','application/json');};
el('archive-chat').onclick=async()=>{if(!activeConversation)return;try{await api('/conversations/'+activeConversation.id,{method:'PATCH',body:JSON.stringify({archived:!activeConversation.archived})});resetChat();await loadHistory();}catch(e){el('history-status').textContent=e.message;}};
document.addEventListener('inneros-controls',chatControls);
document.addEventListener('inneros-workspace',()=>{resetChat();modeDescription();loadHistory().catch(e=>el('history-status').textContent=e.message);});
el('question-form').onsubmit=async event=>{
  event.preventDefault();if(busy||!connected||activeConversation?.archived)return;
  const question=el('question').value.trim(),engine=el('engine').value,mode=el('chat-mode').value,epoch=session;
  if(!question){el('question').focus();return;}
  if(engine==='vultr'&&!el('paid-confirm').checked){el('answer').textContent='Confirma explícitamente esta consulta de pago o utiliza AMD local.';return;}
  const paid=engine==='vultr'&&el('paid-confirm').checked;
  busy=true;controls();el('response').setAttribute('aria-busy','true');el('provider').textContent=engine==='local'?'Conectando a AMD…':'Consultando Vultr…';el('answer').textContent='Procesando tu mensaje. No se ejecutan comandos ni cambios sobre equipos.';el('receipt-details').hidden=true;
  try{
    if(cookieSession&&!activeConversation){const d=await api('/conversations',{method:'POST',body:JSON.stringify({title:question.replace(/\s+/g,' ').slice(0,70),mode})});if(epoch!==session)return;activeConversation=d.conversation;}
    const requestId=crypto.randomUUID().replace(/-/g,'');
    const d=await api('/ask',{method:'POST',body:JSON.stringify({question,engine,mode,confirm_paid:paid,...(activeConversation?{conversation_id:activeConversation.id,client_request_id:requestId}:{})})});
    if(epoch!==session)return;
    if(d.observations&&mode==='infrastructure')showObservations(d.observations);
    el('answer').textContent=d.history_saved===false?'Recibí la respuesta, pero no pude confirmar su guardado. Copia lo importante antes de salir.':'Respuesta recibida. Puedes ver el modelo y su uso en la evidencia.';
    el('provider').textContent=d.provider==='amd-local'?'AMD local · sin tokens externos':d.provider==='vultr-serverless'?'Vultr · consulta de pago':'Sin inferencia';
    el('receipt').textContent=JSON.stringify({provider:d.provider,model:d.usage?.model,latency_ms:d.usage?.latency_ms,tokens:d.usage?.total_tokens,history_saved:d.history_saved,physical_actions_available:false},null,2);el('receipt-details').hidden=false;
    if(activeConversation&&d.history_saved!==false){await reloadConversation();await loadHistory();}else{bubble('user',question);bubble('assistant',d.answer||'Sin respuesta.',d.provider||'');document.dispatchEvent(new CustomEvent('inneros-answer',{detail:{text:d.answer||''}}));}
    el('question').value='';
  }catch(e){if(epoch===session){el('answer').textContent=e.message;el('provider').textContent='Consulta no completada';if(activeConversation){try{await reloadConversation();await loadHistory();}catch{el('history-status').textContent='No se pudo actualizar el historial. No repitas una consulta de pago sin comprobar su estado.';}}}}
  finally{busy=false;el('paid-confirm').checked=false;el('response').setAttribute('aria-busy','false');controls();}
};
modeDescription();chatControls();
