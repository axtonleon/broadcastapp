import { resolve } from 'path';
import { pino } from 'pino';
import makeWASocket, { useMultiFileAuthState, fetchLatestBaileysVersion, DisconnectReason } from '@whiskeysockets/baileys';
import QRCode from 'qrcode';
import pg from 'pg';
import AdmZip from 'adm-zip';
import fs from 'fs';
import { tmpdir } from 'os';

const { Pool } = pg;
const logger = pino({ level: process.env.DEBUG_BAILEYS ? 'debug' : 'warn' });

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: { rejectUnauthorized: false }
});

async function uploadSession(accountId, sourceDir) {
  const zip = new AdmZip();
  zip.addLocalFolder(sourceDir);
  const buffer = zip.toBuffer();
  await pool.query('UPDATE slikaccount SET session_zip = $1, updated_at = NOW() WHERE id = $2', [buffer, accountId]);
}

export default async function handler(req, res) {
  const { session_id } = req.query;
  if (!session_id) {
    return res.status(400).json({ error: 'session_id is required' });
  }

  // Setup SSE
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');
  res.flushHeaders();

  const keepAlive = setInterval(() => {
    try { res.write(': keep-alive\n\n'); } catch (_) {}
  }, 5000);

  const emit = (data) => {
    try {
      console.log('[SSE] Emitting:', data.event, data.message || '');
      res.write(`data: ${JSON.stringify(data)}\n\n`);
    } catch (_) {}
  };

  let sock = null;
  let done = false;

  const cleanup = () => {
    if (done) return;
    done = true;
    console.log('[Baileys] Cleanup called');
    clearInterval(keepAlive);
    if (sock) {
      try {
        sock.ev.removeAllListeners('connection.update');
        sock.ev.removeAllListeners('creds.update');
        sock.end();
      } catch (_) {}
      sock = null;
    }
  };

  req.on('close', () => {
    console.log('[SSE] Client disconnected');
    cleanup();
  });

  const sessionPath = resolve(tmpdir(), 'slik-sessions', session_id);
  // Always start fresh for linking — clear any stale session
  if (fs.existsSync(sessionPath)) {
    fs.rmSync(sessionPath, { recursive: true, force: true });
  }
  fs.mkdirSync(sessionPath, { recursive: true });

  const accRes = await pool.query('SELECT id FROM slikaccount WHERE session_id = $1', [session_id]);
  let accountId = accRes.rows.length > 0 ? accRes.rows[0].id : null;
  console.log(`[Baileys] session_id=${session_id}, accountId=${accountId}`);

  emit({ event: 'connecting', message: 'Starting WhatsApp connection...' });

  // Fetch version once
  let version;
  try {
    const versionResult = await Promise.race([
      fetchLatestBaileysVersion(),
      new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), 5000))
    ]);
    version = versionResult.version;
    console.log('[Baileys] Using version:', version);
  } catch (e) {
    version = [2, 3000, 1015901307];
    console.log('[Baileys] Version fetch failed, using fallback');
  }

  let qrCount = 0;

  async function startSocket() {
    if (done) return;

    try {
      const { state, saveCreds } = await useMultiFileAuthState(sessionPath);

      sock = makeWASocket({
        auth: state,
        logger,
        version,
        printQRInTerminal: false,
        browser: ["BroadcastApp", "Chrome", "1.0.0"],
        connectTimeoutMs: 60000,
        defaultQueryTimeoutMs: 60000,
      });

      sock.ev.on('creds.update', saveCreds);

      sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;
        console.log(`[Baileys] connection=${connection}, qr=${!!qr}, lastDisconnect=${lastDisconnect?.error?.output?.statusCode}`);

        if (done) return;

        if (qr) {
          qrCount++;
          console.log(`[Baileys] QR #${qrCount} generated`);
          try {
            const dataUrl = await QRCode.toDataURL(qr, { margin: 2 });
            const base64 = dataUrl.replace(/^data:image\/png;base64,/, '');
            emit({ event: 'qr', data: base64 });
          } catch (e) {
            console.error('[Baileys] QR generation error:', e);
          }
        }

        if (connection === 'connecting') {
          emit({ event: 'connecting', message: 'Connecting to WhatsApp...' });
        }

        if (connection === 'open') {
          console.log('[Baileys] Connected!');
          emit({ event: 'connected', message: 'Linked successfully! Saving session...' });

          await new Promise(r => setTimeout(r, 2000));

          if (accountId) {
            try {
              await uploadSession(accountId, sessionPath);
              console.log('[Baileys] Session uploaded');
              emit({ event: 'connected', message: 'Session saved successfully!' });
            } catch (e) {
              console.error('[Baileys] Upload error:', e);
              emit({ event: 'error', message: 'Connected but failed to save: ' + e.message });
            }
          } else {
            emit({ event: 'error', message: 'No account in database for this session_id' });
          }
          cleanup();
        }

        if (connection === 'close') {
          const statusCode = lastDisconnect?.error?.output?.statusCode;
          console.log(`[Baileys] Closed. code=${statusCode}`);

          if (statusCode === DisconnectReason.loggedOut || statusCode === 401) {
            if (fs.existsSync(sessionPath)) {
              fs.rmSync(sessionPath, { recursive: true, force: true });
              fs.mkdirSync(sessionPath, { recursive: true });
            }
            emit({ event: 'error', message: 'Session expired. Please try again.' });
            cleanup();
          } else if (statusCode === DisconnectReason.restartRequired || statusCode === 515) {
            emit({ event: 'connecting', message: 'Reconnecting...' });
            sock = null;
            setTimeout(() => startSocket(), 1000);
          } else if (statusCode === DisconnectReason.timedOut || statusCode === 408) {
            emit({ event: 'connecting', message: 'Connection timed out, retrying...' });
            sock = null;
            setTimeout(() => startSocket(), 1000);
          } else if (qrCount > 0 && !done) {
            // QR expired or connection dropped after showing QR — reconnect for new QR
            emit({ event: 'connecting', message: 'QR expired, generating new one...' });
            sock = null;
            setTimeout(() => startSocket(), 1000);
          } else {
            emit({ event: 'error', message: `Connection failed (code ${statusCode}). Try again.` });
            cleanup();
          }
        }
      });
    } catch (err) {
      console.error('[Baileys] Socket creation error:', err);
      emit({ event: 'error', message: `Error: ${err.message}` });
      cleanup();
    }
  }

  await startSocket();

  // On Render there's no function timeout, so we can wait much longer
  // 3 minutes should be plenty of time to scan a QR
  await new Promise((resolve) => {
    const maxTimeout = setTimeout(() => {
      if (!done) {
        emit({ event: 'error', message: 'Timed out (3 min). Please try again.' });
        cleanup();
      }
      resolve();
    }, 180000); // 3 minutes

    const checkDone = setInterval(() => {
      if (done) {
        clearTimeout(maxTimeout);
        clearInterval(checkDone);
        resolve();
      }
    }, 500);
  });
}
