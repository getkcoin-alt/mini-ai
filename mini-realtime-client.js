import { miniIdentity, currentMiniUser } from './mini-supabase.js';
import {
  MINI_REALTIME_PROTOCOL, MINI_INPUT_RATE, MINI_OUTPUT_RATE, MINI_FRAME_BYTES,
  MINI_MAX_IN_FLIGHT_BYTES, MINI_WS_PATH, miniLiveWsUrl,
  miniParseAudioPacket, miniTextEvent
} from './mini-realtime-protocol.js';

/**
 * Browser side of the modular, self-hosted Mini realtime pipeline.
 *
 * The gateway MUST authenticate the FIRST message against Supabase before
 * accepting audio. NFC owns Silero VAD, streaming STT, Ollama and Kyutai TTS.
 * A separate protected WSS relay must be deployed before enabling this UI.
 * No service-role / worker master tokens are included in the browser bundle.
 */
export class MiniRealtimeSession {
  constructor({onEvent = () => {}, onClose = () => {}} = {}) {
    this.onEvent = onEvent;
    this.onClose = onClose;
    this.status = 'idle';
    this.socket = null;
    this.accessToken = null;
    this.media = null;
    this.inputContext = null;
    this.outputContext = null;
    this.inputNode = null;
    this.outputNode = null;
    this.inputSource = null;
    this.inputSink = null;
    this.streamId = null;
    this.responseId = null;
    this.cancelledStreamIds = new Set();
    this.lastPlayedMs = 0;
    this.audioStartedAt = null;
    this.responseFinished = false;
    this.speechStoppedAt = null;
    this.closed = false;
    this.hasStartedSpeech = false;
    this.micFrames = 0;
  }

  emit(event) { try { this.onEvent(event); } catch { /* UI exception must not corrupt audio session */ } }
  setState(value, detail = '') { this.status = value; this.emit({type:'ui.state', status:value, detail}); }

  send(event) {
    if (this.socket?.readyState === WebSocket.OPEN && !this.closed)
      this.socket.send(JSON.stringify(event));
  }

  async start(mode = 'friend') {
    if (this.status !== 'idle' || this.closed) throw new Error('Mini session already started.');
    if (!['friend', 'mentor'].includes(mode)) throw new Error('Choose Friend or Mentor.');
    this.setState('checking');
    const client = miniIdentity();
    const user = await currentMiniUser();
    if (!client || !user) throw new Error('Sign in with a verified Mini account first.');
    const {data, error} = await client.auth.getSession();
    const token = data?.session?.access_token;
    if (error || !token || data.session.user?.id !== user.id)
      throw new Error('Mini session expired. Sign in again.');
    // Authorization header is sent ONLY to our origin. Token never appears in a URL.
    const response = await fetch('/api/voice/realtime-config', {
      method:'GET', headers:{Authorization:'Bearer ' + token},
      credentials:'same-origin', cache:'no-store'
    });
    if (response.status === 401) throw new Error('Your session must be refreshed.');
    if (!response.ok) throw new Error('Mini voice service readiness could not be checked.');
    const settings = await response.json();
    if (settings.enabled !== true || settings.protocol !== MINI_REALTIME_PROTOCOL ||
        settings.wsPath !== MINI_WS_PATH || !miniLiveWsUrl(settings.wsUrl) || typeof settings.ticket !== 'string')
      throw new Error('Streaming Mini voice is not connected yet. Existing voice mode remains available.');
    this.ticket = settings.ticket;

    this.accessToken = token;
    this.setState('connecting');
    // Unlock output sound from an explicit user gesture before any response.
    // Play at Mini's native 24 kHz when the device allows it (no resampling).
    try { this.outputContext = new AudioContext({latencyHint:'interactive',sampleRate:MINI_OUTPUT_RATE}); }
    catch { this.outputContext = new AudioContext({latencyHint:'interactive'}); }
    await this.outputContext.audioWorklet.addModule('/mini-playback.worklet.js');
    this.outputNode = new AudioWorkletNode(this.outputContext,'mini-playback',{
      numberOfInputs:0,numberOfOutputs:1,outputChannelCount:[1],
      processorOptions:{sourceRate:MINI_OUTPUT_RATE}
    });
    this.outputNode.connect(this.outputContext.destination);
    this.outputNode.port.onmessage = e => this.playbackEvent(e.data);
    await this.outputContext.resume();
    const ws = new WebSocket(miniLiveWsUrl(settings.wsUrl));
    this.socket = ws;
    ws.binaryType = 'arraybuffer';
    const connected = new Promise((resolve,reject) => {
      const timeout = setTimeout(() => reject(new Error('Mini gateway connection timed out.')),12000);
      ws.addEventListener('open',()=>{clearTimeout(timeout);resolve();},{once:true});
      ws.addEventListener('error',()=>{clearTimeout(timeout);reject(new Error('Mini secure gateway is unreachable.'));},{once:true});
    });
    ws.addEventListener('message',e => { void this.handleMessage(e).catch(err=>this.fail(err)); });
    ws.addEventListener('close',e => this.cleanup(e.code === 1000 ? 'ended' : 'disconnected'));
    ws.addEventListener('error',()=>this.emit({type:'ui.error',message:'Realtime connection interrupted.'}));
    try { await connected; }
    catch (e) { this.cleanup('disconnected'); throw e; }
    if (this.closed) throw new Error('Mini connection closed unexpectedly.');
    this.send({
      type:'session.start', protocol:MINI_REALTIME_PROTOCOL,
      access_token:this.accessToken, ticket:this.ticket, mode,
      audio_input:{format:'pcm16',channels:1,sample_rate:MINI_INPUT_RATE,frame_ms:20},
      audio_output:{format:'pcm16',channels:1,sample_rate:MINI_OUTPUT_RATE},
      playback_ack:true
    });
    this.accessToken = null; // token is not retained as a long-lived field.
    this.ticket = null; // single-use pass
    this.setState('authenticating');
    this.authTimeout = setTimeout(()=>{
      if (this.status === 'authenticating') this.fail(new Error('Mini did not verify your voice session.'));
    },10000);
  }

  async handleMessage(message) {
    if (this.closed) return;
    if (message.data instanceof ArrayBuffer) {
      if (message.data.byteLength > 5000) throw new Error('Voice server sent an oversized packet.');
      const audio = miniParseAudioPacket(message.data);
      if (audio.streamId !== this.streamId || this.cancelledStreamIds.has(audio.streamId)) return;
      this.outputNode?.port.postMessage({type:'chunk',pcm:audio.pcm},[audio.pcm.buffer]);
      return;
    }
    if (typeof message.data !== 'string' || message.data.length > 16000)
      throw new Error('Invalid Mini realtime event size.');
    const event = miniTextEvent(message.data);
    switch(event.type) {
      case 'session.ready':
        if (this.status !== 'authenticating') return;
        clearTimeout(this.authTimeout);
        this.setState('listening');
        await this.startMicrophone();
        break;
      case 'input.vad.speech_started':
        this.hasStartedSpeech = true;
        if (this.responseId) this.interrupt('barge-in');
        this.emit({type:event.type});
        break;
      case 'input.vad.speech_ended':
        this.speechStoppedAt = performance.now();
        this.emit({type:event.type});
        break;
      case 'input.transcript.final':
        this.emit({type:event.type,text:String(event.text||'').slice(0,2000)});
        break;
      case 'response.started':
        if (typeof event.response_id !== 'string') throw new Error('Missing response ID');
        this.responseId = event.response_id.slice(0,90);
        this.streamId = null;
        this.lastPlayedMs = 0;
        this.audioStartedAt = null;
        this.responseFinished = false;
        this.setState('thinking');
        break;
      case 'response.text.delta':
        this.emit({type:event.type,text:String(event.text||'').slice(0,400),response_id:this.responseId});
        break;
      case 'response.audio.start':
        if (event.response_id !== this.responseId ||
            !Number.isInteger(event.stream_id) || event.stream_id < 1 ||
            this.cancelledStreamIds.has(event.stream_id)) return;
        this.streamId = event.stream_id;
        this.lastPlayedMs = 0;
        this.outputNode?.port.postMessage({type:'flush'});
        this.setState('speaking');
        break;
      case 'response.audio.end':
        if(event.response_id===this.responseId) this.outputNode?.port.postMessage({type:'end'});
        this.emit({type:event.type,response_id:event.response_id});
        break;
      case 'response.finished':
        if(event.response_id!==this.responseId) break;
        this.responseFinished=true;
        this.emit({type:event.type,response_id:event.response_id});
        // Audio may still be inside the browser jitter buffer. Keep its
        // response ID live so user interruption can cancel unheard context.
        if(this.streamId===null) this.finishHeardResponse();
        break;
      case 'response.cancelled':
        if(event.response_id && event.response_id!==this.responseId) break;
        this.outputNode?.port.postMessage({type:'flush'});
        this.finishHeardResponse();
        break;
      case 'session.queued':
        // Mini is in another conversation; keep waiting (up to 15 minutes).
        if (this.status !== 'authenticating') return;
        clearTimeout(this.authTimeout);
        this.authTimeout = setTimeout(()=>{
          if (this.status === 'authenticating') this.fail(new Error('Mini is still busy. Please try again later.'));
        },15*60*1000);
        this.emit({type:'ui.queued',position:Number(event.position)||0,message:String(event.message||'').slice(0,200)});
        break;
      case 'session.ending':
        this.emit({type:'ui.ending',reason:String(event.reason||'').slice(0,40),message:String(event.message||'').slice(0,200)});
        this.stop();
        break;
      case 'session.error':
        this.fail(new Error(String(event.message||'Voice session failed').slice(0,180)));
        break;
      default:
        if (event.type.startsWith('pipeline.')) this.emit(event);
        // Unknown extension events are ignored, not executed.
    }
  }

  async startMicrophone() {
    if (this.closed || this.media) return;
    // User must grant microphone access. AEC/NS are requests, not guarantees.
    this.media = await navigator.mediaDevices.getUserMedia({
      audio:{echoCancellation:true, noiseSuppression:true, autoGainControl:true,
        channelCount:1, sampleRate:{ideal:MINI_INPUT_RATE}}
    });
    if (this.closed) {this.media.getTracks().forEach(t=>t.stop());return;}
    this.inputContext = new AudioContext({latencyHint:'interactive'});
    await this.inputContext.audioWorklet.addModule('/mini-capture.worklet.js');
    this.inputSource = this.inputContext.createMediaStreamSource(this.media);
    this.inputNode = new AudioWorkletNode(this.inputContext,'mini-capture',{
      numberOfInputs:1,numberOfOutputs:1,outputChannelCount:[1]
    });
    // Muted monitor keeps the worklet active without playing the mic aloud.
    this.inputSink = this.inputContext.createGain();
    this.inputSink.gain.value=0;
    this.inputSource.connect(this.inputNode);
    this.inputNode.connect(this.inputSink);
    this.inputSink.connect(this.inputContext.destination);
    this.inputNode.port.onmessage=e=>{
      if (this.closed || this.socket?.readyState!==WebSocket.OPEN) return;
      const data=e.data;
      if(data.type==='meter') {this.emit({type:'ui.mic.level',level:Math.min(1,Number(data.rms||0)*6)});return;}
      if(data.type!=='pcm'||!(data.pcm instanceof ArrayBuffer)||data.pcm.byteLength!==MINI_FRAME_BYTES) return;
      if(this.socket.bufferedAmount>MINI_MAX_IN_FLIGHT_BYTES) {
        this.fail(new Error('Network cannot keep up with realtime audio.'));return;
      }
      this.socket.send(data.pcm);
      this.micFrames++;
    };
    await this.inputContext.resume();
    this.emit({type:'ui.mic.ready'});
  }

  finishHeardResponse() {
    this.responseId=null;
    this.streamId=null;
    this.responseFinished=false;
    this.audioStartedAt=null;
    this.setState('listening');
  }

  playbackEvent(event) {
    if(this.closed) return;
    if(event.type==='overflow') {
      this.fail(new Error('Mini audio buffer overloaded; ending unsafe playback.'));
    } else if(event.type==='playback.started') {
      if(this.audioStartedAt===null) {
        this.audioStartedAt=performance.now();
        const meaningfulAudioMs=this.speechStoppedAt===null?null:
          Math.max(0,Math.round(this.audioStartedAt-this.speechStoppedAt));
        this.emit({type:'ui.first.meaningful.audio',milliseconds:meaningfulAudioMs});
      }
    } else if(event.type==='playback.drain' && this.responseId) {
      this.lastPlayedMs=Math.max(this.lastPlayedMs,Number(event.milliseconds)||0);
      this.send({type:'playback.progress',response_id:this.responseId,
        heard_ms:Math.floor(this.lastPlayedMs),final:true});
      if(this.responseFinished) this.finishHeardResponse();
    } else if(event.type==='playback.progress' && this.responseId) {
      this.lastPlayedMs=Math.max(this.lastPlayedMs,Number(event.milliseconds)||0);
      this.send({type:'playback.progress',response_id:this.responseId,
        heard_ms:Math.floor(this.lastPlayedMs)});
    }
  }

  interrupt(reason='user') {
    if(!this.responseId) return;
    if(this.streamId) this.cancelledStreamIds.add(this.streamId);
    this.outputNode?.port.postMessage({type:'flush'});
    this.send({type:'response.cancel',response_id:this.responseId,
      heard_ms:Math.floor(this.lastPlayedMs), reason});
    this.emit({type:'ui.interrupted',reason,heard_ms:this.lastPlayedMs});
    this.responseId=null;this.streamId=null;this.audioStartedAt=null;this.responseFinished=false;
    this.setState('listening');
  }

  stop() {
    if(this.closed) return;
    this.interrupt('user-ended');
    this.send({type:'session.end'});
    this.socket?.close(1000,'User ended session');
    this.cleanup('ended');
  }

  fail(error) {
    if(this.closed) return;
    this.emit({type:'ui.error',message:String(error?.message||'Realtime connection failed').slice(0,180)});
    this.socket?.close(1011,'Mini client error');
    this.cleanup('error');
  }

  cleanup(state) {
    if(this.closed) return;
    this.closed=true;
    clearTimeout(this.authTimeout);
    this.accessToken=null;
    this.inputNode?.port.postMessage({type:'stop'});
    this.outputNode?.port.postMessage({type:'flush'});
    this.media?.getTracks().forEach(track=>track.stop());
    void this.inputContext?.close().catch(()=>{});
    void this.outputContext?.close().catch(()=>{});
    this.socket?.close();
    this.setState(state);
    this.onClose();
  }
}
