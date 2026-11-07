import { callWorker, respondVoiceError, validateVoiceRequest } from '../_shared/worker.js';
export default async function handler(req, res) {
  if (!validateVoiceRequest(req, res, ['POST'])) return;
  const { text, mode = 'friend', language = 'en' } = req.body || {};
  if (typeof text !== 'string' || text.length < 1 || text.length > 700 || !['friend', 'mentor'].includes(mode) || !['en', 'hi'].includes(language))
    return res.status(400).json({ error: 'Provide a short message, supported language and Mini mode.' });
  try {
    const data = await callWorker('chat', { body: { text, mode, language } });
    return res.status(200).json(data);
  } catch (error) { return respondVoiceError(res, error); }
}
