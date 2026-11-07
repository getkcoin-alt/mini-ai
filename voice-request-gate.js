/**
 * Small browser-side coordinator for single-inference Mini voice workers.
 *
 * A browser abort stops waiting for a result but does not reliably cancel
 * model inference already running on the server. Keep the local slot reserved
 * until the actual HTTP request finishes; never launch duplicate turns.
 */
export class VoiceBusyError extends Error {
  constructor(message = 'Mini is finishing another voice response. Try again when it is ready.') {
    super(message);
    this.name = 'VoiceBusyError';
    this.status = 429;
  }
}

export function createVoiceRequestGate() {
  let active = false;
  return {
    isBusy: () => active,
    async run(work) {
      if (active) throw new VoiceBusyError();
      active = true;
      try {
        return await work();
      } finally {
        active = false;
      }
    }
  };
}

export function voiceResponseError(status, body = {}) {
  if (status === 429) return new VoiceBusyError();
  const detail = typeof body.error === 'string' ? body.error :
    typeof body.detail === 'string' ? body.detail : 'Voice worker unavailable.';
  const error = new Error(detail.slice(0, 200));
  error.status = status;
  return error;
}
