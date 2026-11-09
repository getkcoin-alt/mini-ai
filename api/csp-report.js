// Collects Content-Security-Policy violation reports while the policy runs in
// report-only mode, so it can be tightened and then enforced safely.
// Logs only the directive and the blocked origin, never full URLs or paths.
export const config = { api: { bodyParser: { sizeLimit: '16kb' } } };

function origin(value) {
  try { return new URL(String(value)).origin; } catch { return String(value || '').slice(0, 40); }
}

export default function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'POST') { res.setHeader('Allow', 'POST'); return res.status(405).end(); }
  let body = req.body;
  if (typeof body === 'string') { try { body = JSON.parse(body); } catch { body = {}; } }
  const reports = Array.isArray(body) ? body.map((r) => r?.body || r) : [body?.['csp-report'] || body?.body || body];
  for (const r of reports.slice(0, 5)) {
    if (!r || typeof r !== 'object') continue;
    const directive = String(r['effective-directive'] || r.effectiveDirective || r['violated-directive'] || '').slice(0, 40);
    const blocked = origin(r['blocked-uri'] || r.blockedURL);
    console.warn('csp-violation', JSON.stringify({ directive, blocked }));
  }
  return res.status(204).end();
}
