import { callWorker, respondVoiceError, validateVoiceRequest } from '../_shared/worker.js';
export default async function handler(req, res) {
  if (!validateVoiceRequest(req, res, ['POST'])) return;
  const { text, language = 'en' } = req.body || {};
  if (typeof text !== 'string' || text.trim().length < 1 || text.length > 700 || !['en', 'hi'].includes(language))
    return res.status(400).json({ error: 'Provide up to 700 characters and a supported language.' });
  try {
    const data = await callWorker('speak', { body: { text, language } });
    return res.status(200).json(data);
  } catch (error) { return respondVoiceError(res, error); }
}
