"use strict";
const $ = id => document.getElementById(id);
const state = {voices:[],selected:null,busy:false,ready:false,result:null,file:null,referenceUrl:null,clipPlaying:false,history:[],editingWork:null,mutating:false,videoFile:null,extracted:null};
let toastTimer, previewSaveTimer;

function toast(message, error=false) {
  clearTimeout(toastTimer);
  $("toast").textContent=message; $("toast").classList.toggle("error",error); $("toast").hidden=false;
  toastTimer=setTimeout(()=>$("toast").hidden=true,5500);
}
async function api(path, options={}) {
  const response=await fetch(path,options);
  const data=await response.json().catch(()=>({}));
  if(!response.ok) throw new Error(typeof data.detail==="string"?data.detail:"操作未完成，请检查输入后重试。");
  return data;
}
function post(path,body){return api(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});}
function patch(path,body){return api(path,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});}
function currentVoice(){return state.voices.find(voice=>voice.id===state.selected);}
function showTab(name){
  const clone=name==="clone";
  $("ttsPanel").hidden=clone; $("clonePanel").hidden=!clone;
  $("ttsTab").classList.toggle("active",!clone); $("cloneTab").classList.toggle("active",clone);
  $("ttsTab").setAttribute("aria-selected",String(!clone)); $("cloneTab").setAttribute("aria-selected",String(clone));
}
$("ttsTab").addEventListener("click",()=>showTab("tts"));
$("cloneTab").addEventListener("click",()=>showTab("clone"));
$("newVoiceButton").addEventListener("click",()=>{showTab("clone");$("voiceName").focus();});

function updateControls(){
  document.querySelectorAll("[data-generate],.voice-preview").forEach(button=>button.disabled=state.busy||!state.ready);
  document.querySelectorAll("[data-manage]").forEach(button=>button.disabled=state.busy||state.mutating);
  $("transcribeButton").disabled=state.busy||!state.file;
  $("extractAudioButton").disabled=state.busy||!state.videoFile;
  $("useExtractedButton").disabled=state.busy;
  $("saveResultButton").disabled=state.busy||state.mutating||!state.result||state.result.saved!==false;
}
function renderVoices(){
  const container=$("voiceList");container.replaceChildren();
  $("voiceCount").textContent=state.voices.length;
  for(const voice of state.voices){
    const row=document.createElement("div"); row.className="voice-card"+(voice.id===state.selected?" selected":"");
    row.tabIndex=0; row.setAttribute("role","button");row.setAttribute("aria-label","选择音色："+voice.name);
    row.setAttribute("aria-pressed",String(voice.id===state.selected));
    const avatar=document.createElement("span");avatar.className="voice-avatar"+(voice.kind==="clone"?" clone":"");avatar.textContent=voice.kind==="clone"?"♧":"≋";
    const info=document.createElement("div");info.className="voice-info";
    const name=document.createElement("strong");name.textContent=voice.name;
    const kind=document.createElement("span");kind.className="voice-kind";kind.textContent=voice.kind==="clone"?"克隆音色 · "+voice.reference_seconds+"s 参考":"设计音色";
    info.append(name,kind);
    const preview=document.createElement("button");preview.className="voice-preview";preview.textContent="▶";preview.title="试听"+voice.name;preview.setAttribute("aria-label","试听"+voice.name);
    preview.addEventListener("click",event=>{event.stopPropagation();generate(previewText(),voice.id,true);});
    const edit=document.createElement("button");edit.className="voice-edit";edit.textContent="编辑";edit.dataset.manage="";edit.setAttribute("aria-label","编辑音色："+voice.name);
    edit.addEventListener("click",event=>{event.stopPropagation();openVoiceEditor(voice);});
    const actions=document.createElement("div");actions.className="voice-actions";actions.append(preview,edit);
    const choose=async()=>{
      const previous=state.selected;state.selected=voice.id;renderVoices();
      try{await post("/api/settings",{voice_id:voice.id});}catch(error){state.selected=previous;renderVoices();toast(error.message,true);}
    };
    row.addEventListener("click",choose);row.addEventListener("keydown",event=>{if(event.target===row&&(event.key==="Enter"||event.key===" ")){event.preventDefault();choose();}});
    row.append(avatar,info,actions);container.append(row);
  }
  $("selectedVoiceTag").textContent="◉ "+(currentVoice()?.name||"选择一个音色");
  updateControls();
}
async function loadVoices(){
  const data=await api("/api/voices");state.voices=data.voices;
  state.selected=data.settings.voice_id;
  if(!currentVoice())state.selected=state.voices[0]?.id||null;
  $("previewText").value=data.settings.preview_text;
  renderVoices();
}
async function health(){
  try{
    const data=await api("/api/health");state.ready=data.engine_ready;
    $("engineBadge").classList.toggle("offline",!state.ready);
    $("engineBadge").querySelector("span").textContent=state.ready?"本地引擎就绪":"引擎未就绪 · 请运行启动脚本";
  }catch(_){state.ready=false;$("engineBadge").classList.add("offline");$("engineBadge").querySelector("span").textContent="本机服务未连接";}
  updateControls();
}
function previewText(){return $("previewText").value.trim()||"你好，这是我的声音。欢迎来到本地语音工作室。";}
async function savePreview(){
  $("previewSaved").textContent="正在保存…";
  try{await post("/api/settings",{preview_text:previewText()});$("previewSaved").textContent="试听文字已保存。左侧所有音色都使用这句话。";}
  catch(error){$("previewSaved").textContent="保存失败，请重试。";toast(error.message,true);}
}
$("previewText").addEventListener("input",()=>{clearTimeout(previewSaveTimer);previewSaveTimer=setTimeout(savePreview,500);});
$("previewText").addEventListener("change",()=>{clearTimeout(previewSaveTimer);savePreview();});
$("speed").addEventListener("input",()=>$("speedValue").textContent=Number($("speed").value).toFixed(2)+"×");
$("speechText").value=localStorage.getItem("voiceStudioText")||"你好，欢迎来到我的语音工作室。今天，也让声音替你传达一点心意吧。";
function updateCount(){$("charCount").textContent=$("speechText").value.length;localStorage.setItem("voiceStudioText",$("speechText").value);}
$("speechText").addEventListener("input",updateCount);updateCount();

function setBusy(busy,title="正在生成声音…",description="文字越长，需要的时间越多，请稍等。"){
  state.busy=busy;$("busyResult").hidden=!busy;
  $("busyTitle").textContent=title;$("busyDescription").textContent=description;
  $("generatedResult").hidden=busy||!state.result;$("emptyResult").hidden=busy||!!state.result;
  $("resultBadge").textContent=busy?"处理中":state.result?(state.result.saved===false?"试听 · 未保存":"已保存"):"等待生成";
  $("resultBadge").classList.toggle("done",!busy&&!!state.result);updateControls();
}
function showResult(item,autoplay=true){
  const previous=state.result;
  if(state.previewSocket){state.previewSocket.close();state.previewSocket=null;}
  if(previous?.saved===false&&previous.id!==item.id)post("/api/previews/"+previous.id+"/discard",{}).catch(()=>{});
  state.result=item;$("resultVoice").textContent=item.voice_name;$("resultDuration").textContent=item.duration.toFixed(1)+" 秒";
  $("resultTitle").textContent=item.title||item.text.slice(0,24);
  const saved=item.saved!==false;
  if(!saved){
    state.previewSocket=new WebSocket((location.protocol==="https:"?"wss://":"ws://")+location.host+"/api/previews/"+item.id+"/session");
  }
  $("saveResultButton").hidden=saved;$("editResultButton").hidden=!saved;$("deleteResultButton").hidden=!saved;
  $("resultText").textContent=item.text;
  const player=$("resultPlayer");player.pause();player.src=item.url;player.load();
  $("downloadWav").href=item.url+"?download=true";
  $("downloadMp3").href="/api/audio/"+item.id+".mp3?download=true";
  setBusy(false);
  if(autoplay)player.play().catch(()=>toast("声音已生成，点击播放器即可收听。"));
}
async function generate(text,voiceId=state.selected,isPreview=false){
  if(state.busy)return;
  if(!state.ready){toast("请先运行“启动语音工作室.cmd”，等待本地引擎就绪。",true);return;}
  if(!voiceId){toast("请先选择一个音色。",true);return;}
  if(!text.trim()){toast("请先输入要说的文字。",true);$("speechText").focus();return;}
  $("resultPlayer").pause();setBusy(true,isPreview?"正在试听这个声音…":"正在生成声音…");
  try{
    const item=await post("/api/generate",{voice_id:voiceId,text:text.trim(),speed:Number($("speed").value),steps:Number($("quality").value),title:!isPreview&&state.editingWork?state.editingWork.title:null});
    if(!isPreview)cancelWorkEdit();
    showResult(item);
  }catch(error){setBusy(false);toast(error.message,true);}
}
$("generateButton").addEventListener("click",()=>generate($("speechText").value));
$("previewButton").addEventListener("click",()=>generate(previewText(),state.selected,true));

async function loadHistory(){
  const history=await api("/api/history");const list=$("historyList");list.replaceChildren();
  state.history=history;
  $("historyCount").textContent=history.length?"共 "+history.length+" 段 · 已保存在本机":"手动保存的作品会出现在这里";
  if(!history.length){const empty=document.createElement("div");empty.className="history-empty";empty.textContent="还没有作品，先生成一段试试吧。";list.append(empty);return;}
  for(const item of history){
    const row=document.createElement("div");row.className="history-row";
    const play=document.createElement("button");play.className="history-play";play.textContent="▶";play.setAttribute("aria-label","播放："+item.text.slice(0,15));play.addEventListener("click",()=>{if(!state.busy)showResult(item);});
    const info=document.createElement("div");info.className="history-info";
    const title=document.createElement("strong");title.textContent=item.title||item.text.slice(0,24);
    const text=document.createElement("p");text.textContent=item.text;
    const meta=document.createElement("small");meta.textContent=item.voice_name+" · "+new Date(item.created_at).toLocaleString("zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"});info.append(title,text,meta);
    const duration=document.createElement("span");duration.className="history-duration";duration.textContent=item.duration.toFixed(1)+"s";
    const download=document.createElement("a");download.href=item.url+"?download=true";download.className="history-download";download.textContent="↓ WAV";download.setAttribute("download","");
    const mp3=document.createElement("a");mp3.href="/api/audio/"+item.id+".mp3?download=true";mp3.className="history-download";mp3.textContent="↓ MP3";mp3.setAttribute("download","");mp3.setAttribute("aria-label","下载MP3："+(item.title||item.text.slice(0,24)));
    const edit=document.createElement("button");edit.className="history-action";edit.textContent="编辑";edit.dataset.manage="";edit.setAttribute("aria-label","编辑作品："+(item.title||item.text.slice(0,24)));edit.addEventListener("click",()=>openWorkEditor(item));
    const remove=document.createElement("button");remove.className="history-action danger-text";remove.textContent="删除";remove.dataset.manage="";remove.setAttribute("aria-label","删除作品："+(item.title||item.text.slice(0,24)));remove.addEventListener("click",()=>askDelete("work",item));
    const actions=document.createElement("div");actions.className="history-actions";actions.append(download,mp3,edit,remove);
    row.append(play,info,duration,actions);list.append(row);
  }
  updateControls();
}

let voiceBeingEdited, workBeingEdited, pendingDelete;
function openDialog(id){const dialog=$(id);dialog.querySelector(".dialog-error").textContent="";if(!dialog.open)dialog.showModal();}
async function dialogAction(dialog,action){
  if(state.mutating)return;
  state.mutating=true;dialog.querySelector(".dialog-error").textContent="";
  dialog.querySelectorAll("button").forEach(button=>button.disabled=true);updateControls();
  try{await action();}catch(error){dialog.querySelector(".dialog-error").textContent=error.message;}
  finally{state.mutating=false;dialog.querySelectorAll("button").forEach(button=>button.disabled=false);updateControls();}
}
document.querySelectorAll("dialog [data-close]").forEach(button=>button.addEventListener("click",()=>button.closest("dialog").close()));
$("voiceEditDialog").addEventListener("close",()=>$("editReferencePlayer").pause());
function openVoiceEditor(voice){
  if(state.busy)return;
  voiceBeingEdited=voice;$("editVoiceName").value=voice.name;
  const clone=voice.kind==="clone";$("editReferenceGroup").hidden=!clone;$("voiceDesignNote").hidden=clone;
  $("editVoiceReference").required=clone;$("editVoiceReference").value=voice.reference_text||"";
  const player=$("editReferencePlayer");player.pause();player.removeAttribute("src");
  if(clone)player.src="/api/voices/"+voice.id+"/reference";
  openDialog("voiceEditDialog");
}
$("voiceEditForm").addEventListener("submit",event=>{
  event.preventDefault();const dialog=$("voiceEditDialog");
  dialogAction(dialog,async()=>{
    const body={name:$("editVoiceName").value.trim()};
    if(voiceBeingEdited.kind==="clone")body.reference_text=$("editVoiceReference").value.trim();
    await patch("/api/voices/"+voiceBeingEdited.id,body);await loadVoices();dialog.close();toast("音色已更新，下次合成将使用新设置。");
  });
});
$("deleteVoiceButton").addEventListener("click",()=>{const voice=voiceBeingEdited;$("voiceEditDialog").close();askDelete("voice",voice);});
function openWorkEditor(item){
  if(state.busy)return;
  workBeingEdited=item;$("editWorkTitle").value=item.title||item.text.slice(0,24);$("editWorkText").textContent=item.text;openDialog("workEditDialog");
}
$("workEditForm").addEventListener("submit",event=>{
  event.preventDefault();const dialog=$("workEditDialog");
  dialogAction(dialog,async()=>{
    const item=await patch("/api/history/"+workBeingEdited.id,{title:$("editWorkTitle").value.trim()});
    if(state.result?.id===item.id)showResult(item,false);
    await loadHistory();dialog.close();toast("作品名称已保存。");
  });
});
function cancelWorkEdit(){state.editingWork=null;$("editingBanner").hidden=true;}
$("cancelWorkEdit").addEventListener("click",cancelWorkEdit);
$("rewriteWorkButton").addEventListener("click",async()=>{
  const item=workBeingEdited, voice=state.voices.find(voice=>voice.id===item.voice_id);
  const title=($("editWorkTitle").value.trim()||item.title||item.text.slice(0,24)).slice(0,75)+"（修改版）";
  $("workEditDialog").close();state.editingWork={id:item.id,title};
  $("editingLabel").textContent="改写："+title+" · 将另存为新作品";$("editingBanner").hidden=false;
  $("speechText").value=item.text;$("speed").value=item.speed;$("speedValue").textContent=Number(item.speed).toFixed(2)+"×";$("quality").value=item.steps;updateCount();
  if(voice){state.selected=voice.id;renderVoices();try{await post("/api/settings",{voice_id:voice.id});}catch(error){toast(error.message,true);}}
  else toast("原音色已删除，请选择现有音色后再生成。",true);
  showTab("tts");$("speechText").focus();$("ttsPanel").scrollIntoView({block:"start",behavior:"smooth"});
});
function askDelete(kind,item){
  if(state.busy)return;
  pendingDelete={kind,item};const label=kind==="voice"?"音色":"作品",name=item.name||item.title||item.text.slice(0,24);
  $("deleteTitle").textContent="删除"+label;
  $("deleteMessage").textContent="将“"+name+"”移到 Windows 系统回收站？"+(kind==="voice"?"参考录音和音色设置会一并移到系统回收站，已经生成的作品仍保留。":"作品记录和 WAV、MP3 音频会一并移到系统回收站。")+"可在桌面回收站中右键“还原”，回到软件后会自动恢复列表。";
  openDialog("deleteDialog");
}
$("confirmDeleteButton").addEventListener("click",()=>dialogAction($("deleteDialog"),async()=>{
  const {kind,item}=pendingDelete;
  await api((kind==="voice"?"/api/voices/":"/api/history/")+item.id,{method:"DELETE"});
  if(kind==="work"&&state.result?.id===item.id){const player=$("resultPlayer");player.pause();player.removeAttribute("src");player.load();state.result=null;setBusy(false);}
  if(kind==="work"&&state.editingWork?.id===item.id)cancelWorkEdit();
  await Promise.all([loadVoices(),loadHistory()]);$("deleteDialog").close();toast("已移到 Windows 系统回收站。");
}));
$("editResultButton").addEventListener("click",()=>{if(state.result)openWorkEditor(state.result);});
$("deleteResultButton").addEventListener("click",()=>{if(state.result)askDelete("work",state.result);});
$("trashButton").addEventListener("click",async()=>{
  const button=$("trashButton");if(button.disabled)return;
  button.disabled=true;button.textContent="正在打开…";
  try{const result=await post("/api/system-recycle-bin/open",{});toast(result.foreground?"Windows 回收站已打开。":"回收站已启动，请查看任务栏中的资源管理器。");}
  catch(error){toast(error.message,true);}
  finally{button.textContent="系统回收站";updateControls();}
});
window.addEventListener("pagehide",()=>{
  if(state.previewSocket)state.previewSocket.close();
  if(state.result?.saved===false)navigator.sendBeacon("/api/previews/"+state.result.id+"/discard","");
});
window.addEventListener("focus",()=>{if(!state.busy)Promise.all([loadVoices(),loadHistory()]).catch(()=>{});});
$("saveResultButton").addEventListener("click",()=>{if(!state.result||state.result.saved!==false)return;$("newWorkTitle").value=state.result.title||state.result.text.slice(0,24);openDialog("saveWorkDialog");});
$("saveWorkForm").addEventListener("submit",event=>{
  event.preventDefault();dialogAction($("saveWorkDialog"),async()=>{
    const item=await post("/api/history",{audio_id:state.result.id,title:$("newWorkTitle").value.trim()});
    showResult(item,false);await loadHistory();$("saveWorkDialog").close();toast("作品已保存。");
  });
});
$("videoFile").addEventListener("change",event=>{state.videoFile=event.target.files[0]||null;updateControls();});
$("extractAudioButton").addEventListener("click",async()=>{
  if(state.busy||!state.videoFile)return;
  if(state.videoFile.size>512*1024*1024){toast("视频超过512MB，请先截取需要的部分。",true);return;}
  const form=new FormData();form.append("file",state.videoFile);
  setBusy(true,"正在提取视频音轨…","提取完成后，MP3 会直接保存到电脑桌面。");
  $("extractStatus").textContent="正在提取，请稍等…";$("useExtractedButton").hidden=true;
  try{
    const item=await api("/api/extract-audio",{method:"POST",body:form});state.extracted=item;
    $("extractStatus").textContent="已保存到桌面："+item.name;
    $("useExtractedButton").hidden=item.size>32*1024*1024;
    if(item.size>32*1024*1024)$("extractStatus").textContent+="。音频较大，用于克隆前请先截取片段。";
    toast("音频已保存到桌面："+item.name);
  }catch(error){$("extractStatus").textContent=error.message;toast(error.message,true);}
  finally{setBusy(false);}
});
$("useExtractedButton").addEventListener("click",async()=>{
  if(state.busy||!state.extracted)return;
  try{
    const response=await fetch(state.extracted.url);if(!response.ok)throw new Error("找不到提取的音频，请确认桌面文件未移动。");
    selectFile(new File([await response.blob()],state.extracted.name,{type:"audio/mpeg"}));
    toast("已选为参考录音，请选择3–10秒片段并核对文字。");
  }catch(error){toast(error.message,true);}
});

function selectFile(file){
  if(!file)return;
  if(file.size>32*1024*1024){toast("文件超过32MB，请先截取一段较短的录音。",true);return;}
  state.file=file;$("fileName").textContent=file.name;$("referencePanel").hidden=false;
  if(state.referenceUrl)URL.revokeObjectURL(state.referenceUrl);
  state.referenceUrl=URL.createObjectURL(file);$("referencePlayer").src=state.referenceUrl;
  $("clipStart").value=0;$("clipSeconds").value=8;$("referenceText").value="";
  if(!$("voiceName").value.trim())$("voiceName").value=file.name.replace(/\.[^.]+$/,"").slice(0,25);
  updateControls();
}
$("referenceFile").addEventListener("change",event=>selectFile(event.target.files[0]));
$("dropZone").addEventListener("dragover",event=>{event.preventDefault();$("dropZone").classList.add("dragging");});
$("dropZone").addEventListener("dragleave",()=>$("dropZone").classList.remove("dragging"));
$("dropZone").addEventListener("drop",event=>{event.preventDefault();$("dropZone").classList.remove("dragging");selectFile(event.dataTransfer.files[0]);});
$("referencePlayer").addEventListener("loadedmetadata",()=>{const duration=$("referencePlayer").duration;if(Number.isFinite(duration)){$("clipSeconds").value=Math.min(8,Math.floor(duration*10)/10);if(duration<3)toast("这段录音不足3秒，建议换一段更长的参考。",true);}});
$("playClip").addEventListener("click",()=>{if(!state.file)return;const player=$("referencePlayer");player.currentTime=Math.max(0,Number($("clipStart").value));state.clipPlaying=true;player.play().catch(()=>toast("请检查这个音频文件是否可以播放。",true));});
$("referencePlayer").addEventListener("timeupdate",()=>{const end=Number($("clipStart").value)+Number($("clipSeconds").value);if(state.clipPlaying&&$("referencePlayer").currentTime>=end){$("referencePlayer").pause();state.clipPlaying=false;}});
function cloneForm(){
  if(!state.file)throw new Error("请先选择一段参考音频。");
  const start=Number($("clipStart").value),seconds=Number($("clipSeconds").value);
  if(!Number.isFinite(start)||start<0||!Number.isFinite(seconds)||seconds<3||seconds>15)throw new Error("请选择3到15秒的参考片段，起点不能小于0。");
  const form=new FormData();form.append("file",state.file);form.append("start",String(start));form.append("seconds",String(seconds));return form;
}
$("transcribeButton").addEventListener("click",async()=>{
  if(state.busy)return;
  let form;try{form=cloneForm();}catch(error){toast(error.message,true);return;}
  setBusy(true,"正在识别参考文字…","在本机识别所选片段，不会上传到外部平台。");
  try{const result=await api("/api/transcribe",{method:"POST",body:form});$("referenceText").value=result.text;toast("已识别，请核对文字与所选录音是否一致。");}
  catch(error){toast(error.message,true);}finally{setBusy(false);}
});
$("saveCloneButton").addEventListener("click",async()=>{
  if(state.busy)return;
  let form;try{form=cloneForm();const name=$("voiceName").value.trim();if(!name)throw new Error("请先给音色取个名字。");form.append("name",name);form.append("text",$("referenceText").value.trim());}catch(error){toast(error.message,true);return;}
  setBusy(true,"正在准备新的声音…","处理参考音频并保存到你的本机音色库。");
  try{
    const voice=await api("/api/voices/clone",{method:"POST",body:form});
    await loadVoices();$("referenceText").value=voice.reference_text;
    toast("“"+voice.name+"”已保存，正在生成试听。");
    setBusy(false);await generate(previewText(),voice.id,true);
  }catch(error){setBusy(false);toast(error.message,true);}
});

Promise.all([loadVoices(),loadHistory(),health()]).catch(error=>toast(error.message,true));
setInterval(health,15000);
