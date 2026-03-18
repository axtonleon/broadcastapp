import { resolve } from 'path';
import { pino } from 'pino';
import makeWASocket, { useMultiFileAuthState, fetchLatestBaileysVersion } from '@whiskeysockets/baileys';
import pg from 'pg';
import AdmZip from 'adm-zip';
import fs from 'fs';
import { tmpdir } from 'os';

const { Pool } = pg;
const logger = pino({ level: 'silent' });

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
});

async function downloadSession(sessionId, targetDir) {
  const res = await pool.query('SELECT id, session_zip FROM slikaccount WHERE session_id = $1', [sessionId]);
  if (res.rows.length > 0 && res.rows[0].session_zip) {
    const zip = new AdmZip(res.rows[0].session_zip);
    if (!fs.existsSync(targetDir)) fs.mkdirSync(targetDir, { recursive: true });
    zip.extractAllTo(targetDir, true);
    return res.rows[0].id;
  }
  return null;
}

async function uploadSession(accountId, sourceDir) {
  const zip = new AdmZip();
  zip.addLocalFolder(sourceDir);
  const buffer = zip.toBuffer();
  await pool.query('UPDATE slikaccount SET session_zip = $1, updated_at = NOW() WHERE id = $2', [buffer, accountId]);
}

export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { session_id, to, text } = req.body;
  if (!session_id || !to || !text) {
    return res.status(400).json({ error: 'session_id, to, and text are required' });
  }

  const sessionPath = resolve(tmpdir(), 'slik-sessions', session_id);
  if (!fs.existsSync(sessionPath)) fs.mkdirSync(sessionPath, { recursive: true });

  // 1. Sync from DB
  const accountId = await downloadSession(session_id, sessionPath);
  if (!accountId) {
    return res.status(404).json({ error: 'Session not found in database' });
  }

  try {
    const { version } = await fetchLatestBaileysVersion();
    const { state, saveCreds } = await useMultiFileAuthState(sessionPath);
    
    const sock = makeWASocket({
      auth: state,
      logger,
      version,
      printQRInTerminal: false
    });

    sock.ev.on('creds.update', saveCreds);

    return new Promise((resolvePromise) => {
        const timeout = setTimeout(() => {
            sock.end();
            res.status(504).json({ error: 'Timeout waiting for connection' });
            resolvePromise();
        }, 30000);

        sock.ev.on('connection.update', async (update) => {
            const { connection, lastDisconnect } = update;
            if (connection === 'open') {
                clearTimeout(timeout);
                try {
                    const jid = to.includes('@s.whatsapp.net') ? to : `${to}@s.whatsapp.net`;
                    await sock.sendMessage(jid, { text });
                    await uploadSession(accountId, sessionPath);
                    sock.end();
                    res.status(200).json({ status: 'OK' });
                } catch (err) {
                    res.status(500).json({ error: err.message });
                }
                resolvePromise();
            }
            if (connection === 'close') {
                const code = (lastDisconnect?.error)?.output?.statusCode;
                if (code === 401) {
                    clearTimeout(timeout);
                    res.status(401).json({ error: 'Unauthorized/Logged out' });
                    resolvePromise();
                }
            }
        });
    });

  } catch (err) {
    res.status(500).json({ error: err.message });
  }
}
