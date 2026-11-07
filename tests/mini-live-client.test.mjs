import test from 'node:test';
import assert from 'node:assert/strict';
import { chooseMiniAudioMime, miniLiveLocalUrl } from '../mini-live-browser.js';

test('Mini live conversation is localhost-only', () => {
  assert.equal(miniLiveLocalUrl({hostname:'localhost',host:'localhost:8765',protocol:'http:'}),
    'ws://localhost:8765/api/voice/live');
  assert.equal(miniLiveLocalUrl({hostname:'127.0.0.1',host:'127.0.0.1:8765',protocol:'https:'}),
    'wss://127.0.0.1:8765/api/voice/live');
  assert.throws(() => miniLiveLocalUrl({hostname:'mini-ai-gitkcoin.vercel.app',host:'mini-ai-gitkcoin.vercel.app',protocol:'https:'}),
    /private localhost/);
});
test('recorder format is chosen only from browser-supported types', () => {
  assert.equal(chooseMiniAudioMime({isTypeSupported: t=>t==='audio/mp4'}),'audio/mp4');
  assert.throws(()=>chooseMiniAudioMime({isTypeSupported:()=>false}), /supported audio format/);
});
