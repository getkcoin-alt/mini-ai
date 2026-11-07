import { readSession, sessionConfigured, noStore } from '../_shared/auth.js';
import { workerConfigured, callWorker } from '../_shared/worker.js';

export default async function handler(req, res) {
  noStore(res);
  if (req.method !== 'GET') { res.setHeader('Allow', 'GET'); return res.status(405).json({ error: 'Method not allowed' }); }
  const owner = readSession(req);
  const configured = workerConfigured();
  const result = {
    authReady: Boolean(process.env.GOOGLE_CLIENT_ID && sessionConfigured()),
    googleClientId: process.env.GOOGLE_CLIENT_ID || '',
    ownerSignedIn: Boolean(owner),
    ownerEmail: owner ? owner.email : '',
    workerConfigured: configured,
    workerReady: false,
    referenceReady: false,
    referenceModes: { friend: false, mentor: false },
    voiceReady: false,
    voiceProvider: 'self-hosted-chatterbox',
    localStandalone: false,
    modelDescription: 'Chatterbox voice cloning + faster-whisper + Ollama',
  };
  if (owner && configured) {
    try {
      const status = await callWorker('status', { method: 'GET', timeoutMs: 2500 });
      result.workerReady = Boolean(status.workerReady);
      result.referenceReady = Boolean(status.referenceReady);
      result.referenceModes = { friend: Boolean(status.referenceModes?.friend), mentor: Boolean(status.referenceModes?.mentor) };
      result.voiceReady = result.workerReady && result.referenceReady;
    } catch { /* do not disclose internal network details in public readiness checks */ }
  }
  return res.status(200).json(result);
}
