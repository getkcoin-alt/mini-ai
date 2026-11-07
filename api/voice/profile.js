import { callWorker, respondVoiceError, validateVoiceRequest } from '../_shared/worker.js';

export default async function handler(req, res) {
  if (!validateVoiceRequest(req, res, ['GET', 'POST', 'DELETE'])) return;
  if (req.method === 'POST') {
    const body = req.body || {};
    if (body.consent !== true || !body.profile || typeof body.profile !== 'object' ||
        Array.isArray(body.profile) || JSON.stringify(body.profile).length > 2200) {
      return res.status(400).json({ error: 'Explicit permission and a small profile are required.' });
    }
  }
  try {
    const result = await callWorker('profile', {
      method: req.method,
      ...(req.method === 'POST' ? { body: req.body } : {}),
      timeoutMs: 10000
    });
    return res.status(200).json(result);
  } catch (error) {
    return respondVoiceError(res, error);
  }
}
