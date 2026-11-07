import { callWorker, respondVoiceError, validateVoiceRequest } from '../_shared/worker.js';
export const config = { api: { bodyParser: { sizeLimit: '4mb' } } };
export default async function handler(req, res) {
  if (!validateVoiceRequest(req, res, ['POST'])) return;
  const { audio_base64, mime = 'audio/webm', mode = 'friend' } = req.body || {};
  if (typeof audio_base64 !== 'string' || audio_base64.length < 1000 || audio_base64.length > 4100000 || !['friend', 'mentor'].includes(mode)
    || typeof mime !== 'string' || mime.length > 70)
    return res.status(400).json({ error: 'Invalid voice clip or Mini mode. Maximum audio: 3MB.' });
  try {
    const result = await callWorker('turn', { body: { audio_base64, mime, mode } });
    return res.status(200).json(result);
  } catch (error) { return respondVoiceError(res, error); }
}
