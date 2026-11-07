/**
 * Mini realtime transport contract v1.
 * Vercel is only the browser/gateway surface; actual VAD/STT/LLM/TTS lives on NFC.
 * Binary client -> gateway: mono signed PCM16 LE, 16 kHz, 20ms (640 bytes).
 * Binary gateway -> client: mono signed PCM16 LE, 24 kHz, up to 80ms.
 * Text is JSON. Binary downlink MUST be preceded by response.audio.start with
 * a response_id and followed by response.audio.end; no interleaved responses.
 * User-bound JWT is sent only as the first WSS frame, never in a URL/query.
 */
export const MINI_REALTIME_PROTOCOL = 'mini.realtime.v1';
export const MINI_INPUT_RATE = 16000;
export const MINI_OUTPUT_RATE = 24000;
export const MINI_FRAME_MS = 20;
export const MINI_FRAME_SAMPLES = MINI_INPUT_RATE * MINI_FRAME_MS / 1000;
export const MINI_FRAME_BYTES = MINI_FRAME_SAMPLES * 2;
export const MINI_MAX_IN_FLIGHT_BYTES = 128000;
export const MINI_MAX_OUTPUT_FRAME_BYTES = 3840; // 80ms PCM16 24kHz
export const MINI_WS_PATH = '/api/voice/realtime';

export function miniSameOriginWs(locationLike) {
  const { protocol, host, hostname } = locationLike || {};
  if ((protocol !== 'https:' && protocol !== 'http:') || !host || !hostname)
    throw new Error('A supported page origin is required for private Mini streaming.');
  if (protocol !== 'https:' && hostname !== 'localhost' && hostname !== '127.0.0.1')
    throw new Error('Mini voice needs HTTPS outside localhost.');
  return (protocol === 'https:' ? 'wss://' : 'ws://') + host + MINI_WS_PATH;
}

export function miniTextEvent(data) {
  const event = JSON.parse(String(data));
  if (!event || typeof event !== 'object' || Array.isArray(event) ||
      typeof event.type !== 'string' || event.type.length > 80)
    throw new Error('Invalid Mini realtime event');
  return event;
}

export function miniPcm16FromFloat(input) {
  const result = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const v = Math.max(-1, Math.min(1, input[i]));
    result[i] = v < 0 ? Math.round(v * 32768) : Math.round(v * 32767);
  }
  return result;
}

export function miniPcm16FrameBytes(input) {
  if (!(input instanceof Int16Array) || input.length !== MINI_FRAME_SAMPLES)
    throw new Error('Mini expects exactly 20ms of 16kHz mono PCM16');
  return input.buffer.slice(input.byteOffset, input.byteOffset + input.byteLength);
}


// Gateway-to-browser frames carry a one-byte type (2=output PCM), four-byte
// LE stream id, then raw PCM16. Old packets cannot replay after barge-in.
export function miniParseAudioPacket(binary) {
  if (!(binary instanceof ArrayBuffer) || binary.byteLength < 7 ||
      binary.byteLength > MINI_MAX_OUTPUT_FRAME_BYTES + 5)
    throw new Error('Invalid Mini output audio frame');
  const header = new DataView(binary);
  if (header.getUint8(0) !== 2 || (binary.byteLength - 5) % 2 !== 0)
    throw new Error('Invalid Mini output PCM packet');
  const streamId = header.getUint32(1, true);
  return { streamId, pcm: new Int16Array(binary.slice(5)) };
}

export function miniBuildAudioPacket(streamId, pcm) {
  if (!Number.isInteger(streamId) || streamId < 1 || streamId > 0xffffffff ||
      !(pcm instanceof Int16Array) || pcm.byteLength > MINI_MAX_OUTPUT_FRAME_BYTES ||
      pcm.byteLength < 2)
    throw new Error('Invalid Mini output audio');
  const binary = new ArrayBuffer(5 + pcm.byteLength);
  const view = new DataView(binary);
  view.setUint8(0, 2);
  view.setUint32(1, streamId, true);
  new Uint8Array(binary, 5).set(new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength));
  return binary;
}
