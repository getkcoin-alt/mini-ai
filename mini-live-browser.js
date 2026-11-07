/**
 * Private experimental Mini Reflex client. Runs ONLY at localhost through a
 * trusted SSH tunnel. It never connects directly to the public Vercel site.
 *
 * Streams MediaRecorder chunks, plays authenticated local-approved Chatterbox
 * phrase WAVs in order, and can mute immediately on interruption.
 * Not native streaming synthesis or end-to-end full-duplex live STT.
 */
export function chooseMiniAudioMime(MediaRecorderClass = MediaRecorder) {
  for (const type of [
    'audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'
  ]) {
    if (MediaRecorderClass.isTypeSupported(type)) return type;
  }
  throw new Error('This browser cannot record a supported audio format.');
}

export function miniLiveLocalUrl(locationObj = window.location) {
  if (!['127.0.0.1','localhost','::1'].includes(locationObj.hostname))
    throw new Error('Mini live preview requires a private localhost SSH tunnel.');
  const scheme = locationObj.protocol === 'https:' ? 'wss:' : 'ws:';
  return scheme + '//' + locationObj.host + '/api/voice/live';
}

export async function startMiniLiveTurn({ mode='friend', onEvent=()=>{}, onFinish=()=>{} }) {
  if (!['friend', 'mentor'].includes(mode)) throw new Error('Unknown companion mode.');
  const endpoint = miniLiveLocalUrl();
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined')
    throw new Error('Microphone recording is not supported in this browser.');
  const mime = chooseMiniAudioMime();
  const media = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation:true, noiseSuppression:true, channelCount:1 }
  });
  const socket = new WebSocket(endpoint);
  const recorder = new MediaRecorder(media, { mimeType: mime });
  let stopped = false;
  let muted = false;
  let audioChain = Promise.resolve();
  let sendChain = Promise.resolve();
  let currentAudio = null;
  const stopTracks = () => media.getTracks().forEach(t => t.stop());
  const safeSend = data => { if (socket.readyState === WebSocket.OPEN) socket.send(data); };
  let finalResolve;
  const finished = new Promise(resolve => { finalResolve = resolve; });

  function queueAudio(item) {
    if (muted || typeof item.audio_base64 !== 'string' || item.audio_base64.length > 6_000_000)
      return;
    audioChain = audioChain.then(async () => {
      if (muted) return;
      let raw;
      try {
        const decoded = atob(item.audio_base64);
        raw = Uint8Array.from(decoded, c => c.charCodeAt(0));
      } catch {
        onEvent({type:'error',message:'A Mini audio phrase was damaged.'});
        return;
      }
      const url = URL.createObjectURL(new Blob([raw], { type:'audio/wav' }));
      await new Promise(resolve => {
        if (muted) { URL.revokeObjectURL(url); return resolve(); }
        const audio = new Audio(url);
        currentAudio = audio;
        const finish = () => {
          currentAudio = null;
          URL.revokeObjectURL(url);
          resolve();
        };
        audio.addEventListener('ended',finish,{once:true});
        audio.addEventListener('error',finish,{once:true});
        audio.play().catch(finish);
      });
    }).catch(() => {});
  }

  socket.addEventListener('message', event => {
    let item;
    try { item=JSON.parse(event.data); } catch { return; }
    if (item.type==='audio') queueAudio(item);
    if (item.type==='error' || item.type==='cancelled') muted=true;
    onEvent(item);
  });
  socket.addEventListener('open', () => {
    safeSend(JSON.stringify({type:'start',mode,mime}));
  });
  socket.addEventListener('message', event => {
    try {
      const item=JSON.parse(event.data);
      if (item.type==='ready' && !stopped && recorder.state==='inactive') {
        recorder.start(250);
        onEvent({type:'recording'});
      }
    } catch {}
  });
  socket.addEventListener('error', () => onEvent({type:'error',message:'Private voice connection failed.'}));
  socket.addEventListener('close', async () => {
    if (recorder.state!=='inactive') recorder.stop();
    stopTracks();
    await audioChain;
    onFinish();
    finalResolve();
  });
  recorder.addEventListener('dataavailable', event => {
    if (!event.data?.size || muted) return;
    sendChain=sendChain.then(async () => {
      const binary=await event.data.arrayBuffer();
      safeSend(binary);
    }).catch(()=>{});
  });
  recorder.addEventListener('stop', async () => {
    stopTracks();
    await sendChain;
    safeSend(JSON.stringify({type:muted?'cancel':'end'}));
  });
  return {
    finished,
    finish() {
      if (stopped) return;
      stopped=true;
      if (recorder.state==='recording') {
        recorder.stop();
        onEvent({type:'waiting',message:'Mini is thinking and preparing spoken phrases…'});
      } else {
        // The user stopped before microphone permission/worker ready.
        safeSend(JSON.stringify({type:'cancel'}));
      }
    },
    cancel() {
      if (muted) return;
      muted=true;stopped=true;
      if (currentAudio) {currentAudio.pause();currentAudio.src='';currentAudio=null;}
      if (recorder.state==='recording') recorder.stop();
      safeSend(JSON.stringify({type:'cancel'}));
      // The worker owns its inference lock until any running phrase completes.
      onEvent({type:'cancelled'});
    }
  };
}
