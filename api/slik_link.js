import { resolve } from 'path';
import { pino } from 'pino';
import makeWASocket, { useMultiFileAuthState, fetchLatestBaileysVersion } from '@whiskeysockets/baileys';
import QRCode from 'qrcode';
import pg from 'pg';
import AdmZip from 'adm-zip';
import fs from 'fs';
import { tmpdir } from 'os';

const { Pool } = pg;
const logger = pino({ level: 'silent' });

// Supabase connection from Vercel env
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

// Fallback version if fetching latest fails (avoids cold-start network delays)
const FALLBACK_VERSION = [2, 3000, 1015901307];

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

  // Keep-alive every 5s to prevent Vercel from killing the connection
  const keepAlive = setInterval(() => {
    try { res.write(': keep-alive\n\n'); } catch (_) {}
  }, 5000);

  const emit = (data) => {
    try { res.write(`data: ${JSON.stringify(data)}\n\n`); } catch (_) {}
  };

  // Track socket at handler scope so cleanup can access it
  let sock = null;
  let done = false;

  const cleanup = () => {
    if (done) return;
    done = true;
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

  // Clean up when client disconnects
  req.on('close', cleanup);

  const sessionPath = resolve(tmpdir(), 'slik-sessions', session_id);
  if (!fs.existsSync(sessionPath)) fs.mkdirSync(sessionPath, { recursive: true });

  // Look up the account ID (we need it to save the session after linking)
  const accRes = await pool.query('SELECT id FROM slikaccount WHERE session_id = $1', [session_id]);
  let accountId = accRes.rows.length > 0 ? accRes.rows[0].id : null;

  emit({ event: 'connecting', message: 'Starting WhatsApp connection...' });

  try {
    // Fetch version with a short timeout + fallback to avoid cold-start hangs
    let version;
    try {
      const versionResult = await Promise.race([
        fetchLatestBaileysVersion(),
        new Promise((_, reject) => setTimeout(() => reject(new Error('version fetch timeout')), 5000))
      ]);
      version = versionResult.version;
    } catch (e) {
      console.log('[Baileys] Version fetch failed, using fallback:', e.message);
      version = FALLBACK_VERSION;
    }

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
      console.log(`[Baileys] Update: connection=${connection}, qr=${!!qr}`);

      if (done) return; // already cleaned up

      if (connection === 'connecting') {
        emit({ event: 'connecting', message: 'Connecting to WhatsApp...' });
      }

      if (qr) {
        console.log('[Baileys] New QR generated');
        try {
          const dataUrl = await QRCode.toDataURL(qr, { margin: 2 });
          const base64 = dataUrl.replace(/^data:image\/png;base64,/, '');
          emit({ event: 'qr', data: base64 });
        } catch (e) {
          console.error('[Baileys] QR generation failed:', e);
        }
      }

      if (connection === 'open') {
        console.log('[Baileys] Connection opened successfully');
        emit({ event: 'connected', message: 'Linked successfully! Saving session...' });

        // Wait for final creds sync
        await new Promise(r => setTimeout(r, 2500));

        if (accountId) {
          try {
            console.log(`[Baileys] Uploading session for account ${accountId}`);
            await uploadSession(accountId, sessionPath);
            emit({ event: 'connected', message: 'Session saved successfully!' });
          } catch (e) {
            console.error('[Baileys] Session upload failed:', e);
            emit({ event: 'error', message: 'Connected but failed to save session: ' + e.message });
          }
        } else {
          emit({ event: 'error', message: 'Connected but no account found in database for this session_id' });
        }

        console.log('[Baileys] Done. Closing.');
        cleanup();
      }

      if (connection === 'close') {
        const statusCode = (lastDisconnect?.error)?.output?.statusCode;
        console.log(`[Baileys] Connection closed. Status: ${statusCode}`);

        if (statusCode === 401) {
          // Clear stale auth files so next attempt starts fresh
          try {
            fs.rmSync(sessionPath, { recursive: true, force: true });
          } catch (_) {}
          emit({ event: 'error', message: 'Session expired. Please try again.' });
          cleanup();
        } else if (statusCode === 515 || statusCode === 503) {
          // WhatsApp server restart — retry automatically
          emit({ event: 'connecting', message: 'WhatsApp servers restarting, retrying...' });
        } else if (statusCode === 408 || statusCode === 504) {
          emit({ event: 'connecting', message: 'Network slow, retrying...' });
        } else if (statusCode !== undefined) {
          emit({ event: 'error', message: `Connection failed (code ${statusCode}). Try again.` });
          cleanup();
        }
        // If statusCode is undefined, it's a transient close — Baileys may auto-retry
      }
    });

    // Return a promise that resolves when done or after max timeout
    // This keeps the Vercel function alive for the SSE stream
    await new Promise((resolve) => {
      const maxTimeout = setTimeout(() => {
        if (!done) {
          emit({ event: 'error', message: 'Timed out waiting for QR scan. Please try again.' });
          cleanup();
        }
        resolve();
      }, 55000); // 55s — under Vercel's 60s Pro limit

      // Also resolve early if we finish
      const checkDone = setInterval(() => {
        if (done) {
          clearTimeout(maxTimeout);
          clearInterval(checkDone);
          resolve();
        }
      }, 500);
    });

  } catch (err) {
    console.error('[Baileys] Fatal Error:', err);
    emit({ event: 'error', message: `Connection error: ${err.message}` });
    cleanup();
  }
}
