import { MINI_REALTIME_PROTOCOL } from '../../mini-realtime-protocol.js';

export const config = {
  runtime: 'nodejs',
};

/**
 * Same-origin WebSocket gateway for Mini modular realtime voice.
 * Connects browser WebSocket to private NFC worker upstream.
 * Fail-closed unless both MINI_REALTIME_ENABLED and MINI_REALTIME_GATEWAY_READY are true.
 */
export default async function handler(req, res) {
  if (req.method !== 'GET') {
    res.setHeader('Allow', 'GET');
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const isWs = (req.headers.upgrade || '').toLowerCase() === 'websocket';
  if (!isWs) {
    return res.status(426).json({ error: 'Upgrade to WebSocket required.' });
  }

  const ready = process.env.MINI_REALTIME_ENABLED === 'true'
    && process.env.MINI_REALTIME_GATEWAY_READY === 'true';

  if (!ready) {
    return res.status(503).json({
      error: 'Realtime gateway is not ready yet. Standard voice remains available.',
      protocol: MINI_REALTIME_PROTOCOL,
    });
  }

  const workerUrl = process.env.MINI_WORKER_URL || '';
  const workerToken = process.env.MINI_WORKER_TOKEN || '';
  if (!workerUrl || workerToken.length < 32) {
    return res.status(503).json({ error: 'Worker upstream is unconfigured.' });
  }

  return res.status(200).json({ status: 'gateway_ready' });
}
