import { validateVoiceRequest } from '../_shared/worker.js';

// Mini has exactly one voice, installed on the private worker by the operator.
// Uploading or removing voice samples from the web app is disabled.
export default async function handler(req, res) {
  if (!validateVoiceRequest(req, res, ['POST', 'DELETE'])) return;
  return res.status(403).json({ error: 'Mini has one fixed voice. Uploading or removing voice samples is disabled.' });
}
