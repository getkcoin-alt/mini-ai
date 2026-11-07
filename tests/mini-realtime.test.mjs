import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  MINI_REALTIME_PROTOCOL, MINI_FRAME_BYTES, MINI_FRAME_SAMPLES,
  miniSameOriginWs, miniPcm16FromFloat, miniPcm16FrameBytes,
  miniBuildAudioPacket, miniParseAudioPacket, miniTextEvent
} from '../mini-realtime-protocol.js';

test('protocol has explicit timing/format with no invented latency guarantee',()=>{
  assert.equal(MINI_REALTIME_PROTOCOL,'mini.realtime.v1');
  assert.equal(MINI_FRAME_SAMPLES,320);
  assert.equal(MINI_FRAME_BYTES,640);
});

test('voice socket stays same-origin secure outside localhost',()=>{
  assert.equal(miniSameOriginWs({protocol:'https:',host:'mini.example.com',hostname:'mini.example.com'}),
    'wss://mini.example.com/api/voice/realtime');
  assert.equal(miniSameOriginWs({protocol:'http:',host:'localhost:8765',hostname:'localhost'}),
    'ws://localhost:8765/api/voice/realtime');
  assert.throws(()=>miniSameOriginWs({protocol:'http:',host:'mini.example.com',hostname:'mini.example.com'}),/HTTPS/);
  assert.throws(()=>miniSameOriginWs({protocol:'file:',host:'',hostname:''}),/page origin/);
});

test('20ms microphone PCM frames are always exact and bounded',()=>{
  const frame=miniPcm16FromFloat(new Float32Array(320).fill(0.25));
  assert.equal(frame.length,320);
  assert.equal(miniPcm16FrameBytes(frame).byteLength,640);
  assert.throws(()=>miniPcm16FrameBytes(new Int16Array(319)),/exactly 20ms/);
  assert.equal(miniPcm16FromFloat(new Float32Array([-2, 2]))[0],-32768);
  assert.equal(miniPcm16FromFloat(new Float32Array([-2, 2]))[1],32767);
});

test('outbound audio is associated with response stream id so cancellation drops stale packets',()=>{
  const pcm=new Int16Array([0,-2500,32000,-32768]);
  const packet=miniBuildAudioPacket(17,pcm);
  const parsed=miniParseAudioPacket(packet);
  assert.equal(parsed.streamId,17);
  assert.deepEqual([...parsed.pcm],[...pcm]);
  assert.throws(()=>miniParseAudioPacket(packet.slice(0,6)),/Invalid/);
  const tampered=packet.slice(0);
  new DataView(tampered).setUint8(0,3);
  assert.throws(()=>miniParseAudioPacket(tampered),/Invalid/);
});

test('invalid control messages never execute as dynamic code',()=>{
  assert.equal(miniTextEvent('{"type":"response.started"}').type,'response.started');
  assert.throws(()=>miniTextEvent('[]'),/Invalid/);
  assert.throws(()=>miniTextEvent('{"type":null}'),/Invalid/);
});

test('client never contains a token in URL or exposes master worker credential',()=>{
  const source=readFileSync(new URL('../mini-realtime-client.js',import.meta.url),'utf8');
  assert.match(source,/access_token:this\.accessToken/);
  assert.match(source,/miniSameOriginWs\(window\.location\)/);
  assert.doesNotMatch(source,/MINI_WORKER_TOKEN|service_role|[?&]token=/);
  assert.match(source,/response\.cancel/);
  assert.match(source,/heard_ms/);
  assert.match(source,/echoCancellation:true/);
});

test('capture and playback worklets are ready for 20ms frames, flush and heard receipts',()=>{
  const capture=readFileSync(new URL('../public/mini-capture.worklet.js',import.meta.url),'utf8');
  const play=readFileSync(new URL('../public/mini-playback.worklet.js',import.meta.url),'utf8');
  assert.match(capture,/registerProcessor\('mini-capture'/);
  assert.match(capture,/new Int16Array\(320\)/);
  assert.match(play,/registerProcessor\('mini-playback'/);
  assert.match(play,/playback\.progress/);
  assert.match(play,/playback\.drain/);
  assert.match(play,/data\.type === 'flush'/);
});

test('realtime is fail closed by default and exposes no private configuration',async()=>{
  const {default:handle}=await import('../api/voice/realtime-config.js');
  let response, status;
  const headers={};
  const res={setHeader(k,v){headers[k]=v;return this},status(v){status=v;return this},json(v){response=v;return this}};
  handle({method:'GET',headers:{}},res);
  assert.equal(status,401);
  assert.equal(response.enabled,false);
  assert.equal(headers['Cache-Control'],'no-store');
  assert.doesNotMatch(JSON.stringify(response),/worker|secret|service_role/i);
});
