#!/usr/bin/env node
/**
 * Test sending a WhatsApp message via Slik/Baileys.
 * Usage: node test-send.js <sessionFolder> <toPhone> [messageText]
 *
 * Example:
 *   node test-send.js "../app/slik-session/session_IL_972_he_329" 2347031090186
 *   node test-send.js "../app/slik-session/session_IL_972_he_329" 2347031090186 "Hello!"
 */
import { resolve } from 'path';
import { existsSync } from 'fs';
import makeWASocket, { useMultiFileAuthState, fetchLatestBaileysVersion } from '@whiskeysockets/baileys';
import pino from 'pino';

const args = process.argv.slice(2);
const debugMode = args.includes('--debug');
const cleanArgs = args.filter((a) => a !== '--debug');
if (cleanArgs.length < 2) {
  console.error('Usage: node test-send.js [--debug] <sessionFolder> <toPhone> [messageText]');
  console.error('  --debug  Enable Baileys logging (to see why it hangs)');
  console.error('  toPhone: E.164 format, e.g. 2347031090186 or +2347031090186');
  process.exit(2);
}

const [sessionFolder, toPhone, messageText = 'Test from Slik bridge'] = cleanArgs;
const sessionPath = resolve(sessionFolder);

function log(step, msg) {
  const ts = new Date().toISOString().slice(11, 23);
  console.log(`[${ts}] ${step}: ${msg}`);
}

function formatJid(phone) {
  const digits = String(phone).replace(/\D/g, '');
  return digits + '@s.whatsapp.net';
}

async function run() {
  log('1', `Session: ${sessionPath}`);
  log('2', `To: ${toPhone} (JID: ${formatJid(toPhone)})`);
  log('3', `Message: "${messageText}"`);

  if (!existsSync(sessionPath)) {
    console.error('\nERROR: Session folder does not exist');
    process.exit(1);
  }
  const credsPath = resolve(sessionPath, 'creds.json');
  if (!existsSync(credsPath)) {
    console.error('\nERROR: No creds.json - session not linked. Run: node link.js <sessionFolder>');
    process.exit(1);
  }

  log('4', 'Fetching WhatsApp version...');
  let version = [2, 3000, 1035162453];
  try {
    const { version: v } = await fetchLatestBaileysVersion();
    if (v) version = v;
  } catch (_) {}

  log('5', 'Loading auth state...');
  const { state, saveCreds } = await useMultiFileAuthState(sessionPath);
  const logger = pino({ level: debugMode ? 'debug' : 'silent' });

  log('6', 'Creating socket...');
  const sock = makeWASocket({
    auth: state,
    logger,
    printQRInTerminal: false,
    version,
  });
  sock.ev.on('creds.update', saveCreds);

  log('7', 'Connecting to WhatsApp (may take 30-90s)...');
  const connectStart = Date.now();
  const progressInterval = setInterval(() => {
    const elapsed = Math.floor((Date.now() - connectStart) / 1000);
    process.stderr.write(`\r  ... still connecting (${elapsed}s)    `);
  }, 5000);
  await new Promise((resolvePromise, reject) => {
    const timeout = setTimeout(() => {
      clearInterval(progressInterval);
      reject(new Error('Connection timeout (90s)'));
    }, 90000);
    sock.ev.on('connection.update', (update) => {
      if (update.connection === 'open') {
        clearInterval(progressInterval);
        clearTimeout(timeout);
        resolvePromise();
      }
      if (update.connection === 'close') {
        clearInterval(progressInterval);
        const reason = update.lastDisconnect?.error?.message || 'Connection closed';
        clearTimeout(timeout);
        reject(new Error(reason));
      }
    });
  });
  log('7', `Connected in ${((Date.now() - connectStart) / 1000).toFixed(1)}s`);

  log('8', 'Sending message...');
  const jid = formatJid(toPhone);
  await sock.sendMessage(jid, { text: messageText });

  log('9', 'Message sent successfully');
  sock.end(undefined);

  console.log('\n--- PASS: Message delivered ---\n');
  process.exit(0);
}

run().catch((err) => {
  console.error('\n--- FAIL:', err?.message || String(err), '---\n');
  process.exit(1);
});
