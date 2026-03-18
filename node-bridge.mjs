/**
 * Standalone Node.js HTTP server for Baileys WhatsApp bridge.
 * Serves /api/slik_link (SSE) and /api/slik_send (POST).
 * Runs alongside FastAPI in the same Docker container.
 */
import http from 'http';
import { URL } from 'url';

// Dynamic imports for the handlers
const linkModule = await import('./api/slik_link.js');
const sendModule = await import('./api/slik_send.js');

const linkHandler = linkModule.default;
const sendHandler = sendModule.default;

const PORT = process.env.NODE_PORT || 3000;

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);

  // Parse query params into req.query (Vercel compat)
  req.query = Object.fromEntries(url.searchParams);

  // Parse JSON body for POST requests
  if (req.method === 'POST') {
    try {
      const chunks = [];
      for await (const chunk of req) chunks.push(chunk);
      const raw = Buffer.concat(chunks).toString();
      req.body = raw ? JSON.parse(raw) : {};
    } catch {
      req.body = {};
    }
  }

  // Add res.flushHeaders if not present (Node http already has it)
  // Add res.status() helper for Vercel compat
  res.status = (code) => { res.statusCode = code; return res; };
  const origEnd = res.end.bind(res);
  res.json = (data) => {
    res.setHeader('Content-Type', 'application/json');
    origEnd(JSON.stringify(data));
  };

  // Route
  if (url.pathname === '/api/slik_link') {
    await linkHandler(req, res);
  } else if (url.pathname === '/api/slik_send') {
    await sendHandler(req, res);
  } else {
    res.statusCode = 404;
    res.end('Not found');
  }
});

server.listen(PORT, () => {
  console.log(`[node-bridge] WhatsApp bridge running on port ${PORT}`);
});
