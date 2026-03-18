/**
 * Front-facing Node.js HTTP server.
 * - Handles /api/slik_link (SSE) and /api/slik_send (POST) directly via Baileys
 * - Proxies everything else to FastAPI (uvicorn) on an internal port
 */
import http from 'http';
import { URL } from 'url';
import httpProxy from 'http-proxy';

// Dynamic imports for the Baileys handlers
const linkModule = await import('./api/slik_link.js');
const sendModule = await import('./api/slik_send.js');

const linkHandler = linkModule.default;
const sendHandler = sendModule.default;

// Render provides PORT; Node is the front server
const PORT = process.env.PORT || 8000;
// FastAPI runs on this internal port
const FASTAPI_PORT = process.env.FASTAPI_PORT || 8001;

const proxy = httpProxy.createProxyServer({
  target: `http://127.0.0.1:${FASTAPI_PORT}`,
  ws: true,
});

proxy.on('error', (err, req, res) => {
  console.error('[proxy] Error:', err.message);
  if (res.writeHead) {
    res.writeHead(502, { 'Content-Type': 'text/plain' });
    res.end('Backend unavailable');
  }
});

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);

  // Handle WhatsApp bridge routes directly
  if (url.pathname === '/api/slik_link' || url.pathname === '/api/slik_send') {
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

    // Add Vercel-compat helpers
    res.status = (code) => { res.statusCode = code; return res; };
    const origEnd = res.end.bind(res);
    res.json = (data) => {
      res.setHeader('Content-Type', 'application/json');
      origEnd(JSON.stringify(data));
    };

    if (url.pathname === '/api/slik_link') {
      await linkHandler(req, res);
    } else {
      await sendHandler(req, res);
    }
  } else {
    // Proxy everything else to FastAPI
    proxy.web(req, res);
  }
});

server.listen(PORT, () => {
  console.log(`[node-bridge] Listening on port ${PORT}, proxying to FastAPI on ${FASTAPI_PORT}`);
});
