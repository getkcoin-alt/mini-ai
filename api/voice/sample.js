import { callWorker, respondVoiceError, validateVoiceRequest } from '../_shared/worker.js';
export const config = { api: { bodyParser: { sizeLimit: '4mb' } } };

export default async function handler(req, res) {
  if (!validateVoiceRequest(req, res, ['POST', 'DELETE'])) return;
  if (req.method === 'POST') {
    const body = req.body || {};
    if (!['friend', 'mentor'].includes(body.mode || 'friend')) return res.status(400).json({ error: 'Invalid voice style.' });
    if (body.consent !== true || typeof body.audio_base64 !== 'string' || body.audio_base64.length < 1000 || body.audio_base64.length > 4100000)
      return res.status(400).json({ error: 'An authorized reference recording (up to 3MB) and explicit consent are required.' });
    if (!['audio/wav', 'audio/x-wav', 'audio/mpeg', 'audio/mp3', 'audio/mp4', 'audio/x-m4a', 'audio/webm', 'video/webm', 'audio/ogg', 'application/octet-stream'].includes(body.mime))
      return res.status(400).json({ error: 'Unsupported audio type.' });
  }
  try {
    const mode = req.method === 'DELETE' ? req.query?.mode || 'friend' : req.body?.mode || 'friend';
    if (!['friend', 'mentor'].includes(mode)) return res.status(400).json({ error: 'Invalid voice style.' });
    const result = await callWorker('reference' + (req.method === 'DELETE' ? '?mode=' + mode : ''), {
      method: req.method === 'DELETE' ? 'DELETE' : 'POST',
      ...(req.method === 'POST' ? { body: req.body, timeoutMs: 30000 } : {})
    });
    return res.status(200).json(result);
  } catch (error) { return respondVoiceError(res, error); }
}
