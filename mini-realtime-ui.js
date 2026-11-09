import { miniIdentity } from './mini-supabase.js';
import { MiniRealtimeSession } from './mini-realtime-client.js';
import { MINI_REALTIME_PROTOCOL, MINI_WS_PATH, miniLiveWsUrl } from './mini-realtime-protocol.js';

const stageMap = Object.freeze({
  vad:'vad', stt:'stt', llm:'llm', tts:'tts',
  silero:'vad', transcribing:'stt', thinking:'llm', synthesizing:'tts'
});

/** Integrates an opt-in streaming module with Mini's existing Friend/Mentor UI.
 * Never displays a green "Live" badge until the gateway proves readiness.
 */
export function createMiniRealtimeUI({getMode, onNotice=()=>{}}) {
  const $ = selector => document.querySelector(selector);
  const toggle = $('#mini-realtime-toggle');
  const interrupt = $('#mini-realtime-interrupt');
  const availability = $('#mini-realtime-availability');
  const badge = $('#mini-realtime-badge');
  const meter = $('#mini-realtime-meter');
  const latency = $('#mini-realtime-latency');
  if (!toggle || !interrupt || !availability) throw new Error('Mini realtime panel is missing.');

  let session = null;
  let authorizedUser = null;
  let ready = false;
  let checking = false;
  let startedAt = 0;

  const explain = text => { availability.textContent = text; };
  const setBadge = (value,state='offline') => {
    badge.textContent=value;
    badge.dataset.state=state;
  };
  const lightStage = name => {
    document.querySelectorAll('[data-mini-stage]').forEach(node=>{
      node.dataset.active=String(node.dataset.miniStage === name);
    });
  };
  const idleButton = () => {
    toggle.disabled=!ready || !authorizedUser;
    toggle.textContent='Start natural conversation';
    interrupt.disabled=true;
    meter.style.width='0%';
    lightStage('');
  };

  async function refresh() {
    if(!authorizedUser) {
      ready=false;idleButton();setBadge('Sign in required');
      explain('Sign in with Google or verified email to check the private streaming gateway.');
      return;
    }
    if(checking || session) return;
    checking=true;
    toggle.disabled=true;
    explain('Checking secure Mini voice gateway…');
    try {
      const client=miniIdentity();
      if(!client) throw new Error('Supabase identity has not been configured.');
      const {data,error}=await client.auth.getSession();
      const token=data?.session?.access_token;
      if(error || !token || data.session.user?.id!==authorizedUser.id)
        throw new Error('Your account session needs verification.');
      const res=await fetch('/api/voice/realtime-config',{
        headers:{Authorization:'Bearer '+token},cache:'no-store',credentials:'same-origin'
      });
      if(res.status===404) {
        ready=false;
        setBadge('Gateway pending');
        explain('Live streaming is being connected to NFC. Your current voice mode remains available.');
        return;
      }
      if(!res.ok) throw new Error(res.status===401
        ? 'Your account session expired.' : 'Mini gateway status is unavailable.');
      const dataReady=await res.json();
      ready=dataReady.enabled===true &&
        dataReady.protocol===MINI_REALTIME_PROTOCOL && dataReady.wsPath===MINI_WS_PATH &&
        Boolean(miniLiveWsUrl(dataReady.wsUrl));
      if(ready) {
        setBadge('Secure gateway ready','live');
        explain('Tap Start and just talk. Mini listens, answers in its own voice, and you can interrupt it anytime.');
      } else if(dataReady.reason==='email_unconfirmed') {
        setBadge('Confirm email');
        explain('Confirm your email address to talk with Mini.');
      } else if(dataReady.reason==='age_confirmation_required') {
        setBadge('18+ only');
        explain('Mini is for adults. Confirm you are 18 or older in your profile to talk.');
      } else if(dataReady.reason==='owner_only') {
        setBadge('Owner only');
        explain('Live conversation is limited to the owner account for now.');
      } else {
        setBadge('Gateway pending');
        explain('NFC streaming gateway and approved Friend/Mentor voice must pass tests before live calls are enabled.');
      }
    } catch(error) {
      ready=false;setBadge('Unavailable');
      explain(String(error.message||error).slice(0,180));
    } finally {
      checking=false;
      if(!session) idleButton();
    }
  }

  function eventHandler(event) {
    switch(event.type) {
      case 'ui.state':
        if(event.status==='listening') {
          toggle.textContent='End conversation'; toggle.disabled=false;
          interrupt.disabled=true;setBadge('Listening','live');
          explain('Mini is listening. You can speak normally and interrupt its answer.');
          lightStage('vad');
        } else if(event.status==='thinking') {
          setBadge('Thinking','busy');lightStage('llm');interrupt.disabled=false;
        } else if(event.status==='speaking') {
          setBadge('Speaking','live');lightStage('tts');interrupt.disabled=false;
        } else if(['connecting','authenticating','checking'].includes(event.status)) {
          setBadge('Connecting','busy');toggle.disabled=true;
        }
        break;
      case 'ui.mic.level':
        meter.style.width=Math.max(0,Math.min(100,Math.round((event.level||0)*100)))+'%';
        break;
      case 'ui.first.meaningful.audio':
        latency.textContent=event.milliseconds===null
          ? 'First spoken audio reached device (turn timing unavailable)'
          : 'First meaningful audio after speech: '+event.milliseconds+' ms';
        break;
      case 'input.vad.speech_started':
        setBadge('Your turn','live');lightStage('vad');break;
      case 'input.vad.speech_ended':
        setBadge('Recognizing','busy');lightStage('stt');break;
      case 'input.transcript.final':
        if($('#user-transcript')) $('#user-transcript').textContent=event.text;break;
      case 'response.started':
        if($('#mini-transcript')) $('#mini-transcript').textContent='';break;
      case 'response.text.delta':
        if($('#mini-transcript')) $('#mini-transcript').textContent+=event.text;break;
      case 'pipeline.stage':
        lightStage(stageMap[event.stage]||'');break;
      case 'ui.interrupted':
        setBadge('Interrupted','busy');
        explain('Playback stopped. Mini is dropping unheard audio and updating context.');
        break;
      case 'ui.queued':
        setBadge(event.position>1?'In line #'+event.position:'You\'re next','busy');
        explain(event.message||'Mini is talking with someone else. You\'ll be connected automatically.');
        break;
      case 'ui.ending':
        explain(event.message||'Conversation ended.');
        if(event.message) onNotice(event.message);
        break;
      case 'ui.error':
        explain(event.message);
        onNotice(event.message);setBadge('Voice unavailable');
        break;
      default: break;
    }
  }

  toggle.addEventListener('click',()=>{
    if(session) { session.stop(); return; }
    if(!ready || !authorizedUser) return onNotice('The private Mini gateway is not ready yet.');
    session=new MiniRealtimeSession({
      onEvent:eventHandler,
      onClose:()=>{
        session=null;startedAt=0;
        setBadge(ready?'Gateway ready':'Gateway pending',ready?'live':'offline');
        explain('Session ended. Your microphone is off.');
        idleButton();
      }
    });
    startedAt=performance.now();
    toggle.disabled=true;
    latency.textContent='First meaningful audio: measuring a real voice turn';
    void session.start(getMode()).catch(error=>{
      onNotice(String(error.message).slice(0,160));
      session?.fail(error);
    });
  });
  interrupt.addEventListener('click',()=>session?.interrupt('user'));
  window.addEventListener('pagehide',()=>session?.stop());
  document.addEventListener('visibilitychange',()=>{
    // Do not keep an unattended microphone session after navigating away.
    if(document.visibilityState==='hidden' && session) session.stop();
  });

  return {
    async setUser(user) {
      const previous=authorizedUser?.id;
      authorizedUser=user?.id?user:null;
      if(previous && previous!==authorizedUser?.id) session?.stop();
      await refresh();
    },
    interrupt() {session?.interrupt('user');},
    stop() {session?.stop();},
    refresh,
    get isActive() {return Boolean(session)}
  };
}
