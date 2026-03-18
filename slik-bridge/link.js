#!/usr/bin/env node
/**
 * Link a WhatsApp account by scanning QR code.
 * Creates Baileys auth in the session folder.
 * Usage: node link.js <sessionFolder> [--json]
 *   --json  Output QR as base64 PNG to stdout (for UI): {"event":"qr","data":"base64..."}
 */
import { resolve } from 'path';
import makeWASocket, { useMultiFileAuthState, fetchLatestBaileysVersion } from '@whiskeysockets/baileys';
import pino from 'pino';
import QRCode from 'qrcode';

/** Fallback version when fetch fails. Update from wppconnect.io/whatsapp-versions if needed. */
const FALLBACK_VERSION = [2, 3000, 1035162453];

const args = process.argv.slice(2);
const jsonMode = args.includes('--json');
const sessionFolder = args.find((a) => !a.startsWith('--'));

if (!sessionFolder) {
  console.error('Usage: node link.js <sessionFolder> [--json]');
  process.exit(1);
}

const logger = pino({ level: 'silent' });

function emit(ev) {
  if (jsonMode) {
    console.log(JSON.stringify(ev));
  }
}

async function run() {
  let version = FALLBACK_VERSION;
  try {
    const { version: v } = await fetchLatestBaileysVersion();
    if (v) version = v;
  } catch (_) {}

  let attempt = 0;
  const maxAttempts = 2;

  async function connect() {
    attempt++;
    const folder = resolve(sessionFolder);
    const { state, saveCreds } = await useMultiFileAuthState(folder);
    const sock = makeWASocket({
      auth: state,
      logger,
      version,
    });

    sock.ev.on('creds.update', () => saveCreds().catch((e) => console.error('saveCreds error:', e)));

    return new Promise((resolve, reject) => {
      let succeeded = false;
      sock.ev.on('connection.update', async (update) => {
        if (update.qr) {
          if (jsonMode) {
            const dataUrl = await QRCode.toDataURL(update.qr, { margin: 2 });
            const base64 = dataUrl.replace(/^data:image\/png;base64,/, '');
            emit({ event: 'qr', data: base64 });
          } else {
            console.log('\nScan this QR with WhatsApp → Linked Devices:\n');
            const qrStr = await QRCode.toString(update.qr, { type: 'terminal', small: true });
            console.log(qrStr);
          }
        }
        if (update.connection === 'open') {
          succeeded = true;
          if (jsonMode) emit({ event: 'connected' });
          else console.log('\nConnected! Saving credentials...');
          try {
            await saveCreds();
          } catch (e) {
            console.error('saveCreds error:', e);
          }
          if (!jsonMode) console.log('Session saved to', folder);
          sock.end(undefined);
          await new Promise((r) => setTimeout(r, 1500));
          resolve();
        }
        if (update.connection === 'close') {
          if (succeeded) return;
          const reason = update.lastDisconnect?.error?.message || 'Connection closed';
          const isRestartRequired = reason.includes('restart required');

          if (isRestartRequired && attempt < maxAttempts) {
            if (!jsonMode) console.log('\nReconnecting after scan...');
            sock.end(undefined);
            connect().then(resolve).catch(reject);
          } else {
            if (jsonMode) emit({ event: 'error', message: reason });
            else console.error('\nConnection closed:', reason);
            sock.end(undefined);
            reject(new Error(reason));
          }
        }
      });
    });
  }

  await connect();
  await new Promise((r) => setTimeout(r, 2000));
  process.exit(0);
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
