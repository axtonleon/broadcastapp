#!/usr/bin/env node
/**
 * Send a single WhatsApp message via Baileys.
 * Usage: node send.js <sessionFolder> <toPhone> <messageText>
 * toPhone: E.164 format, e.g. 972501234567
 * Output: OK or ERROR: <message>
 */
import { writeSync } from 'fs';
import { resolve } from 'path';
import makeWASocket, { useMultiFileAuthState, fetchLatestBaileysVersion } from '@whiskeysockets/baileys';
import pino from 'pino';

/** Fallback version when fetch fails. See wppconnect.io/whatsapp-versions */
const FALLBACK_VERSION = [2, 3000, 1035162453];

const args = process.argv.slice(2);
if (args.length < 3) {
  process.stderr.write('Usage: node send.js <sessionFolder> <toPhone> <messageText>\n');
  process.exit(1);
}

const [sessionFolder, toPhone, messageText] = args;
const sessionPath = resolve(sessionFolder);
const verbose = process.env.SLIK_VERBOSE === '1' || process.env.SLIK_VERBOSE === 'true';

function logStep(step, msg) {
  if (verbose) writeSync(2, `[Slik] ${step}: ${msg}\n`);
}

function exitWith(err) {
  process.stderr.write('ERROR: ' + (err?.message || String(err)) + '\n');
  process.exit(1);
}

function formatJid(phone) {
  const digits = phone.replace(/\D/g, '');
  return digits + '@s.whatsapp.net';
}

async function run() {
  logStep('1', `Session: ${sessionPath}`);
  logStep('2', `To: ${toPhone}`);

  let version = FALLBACK_VERSION;
  try {
    const { version: v } = await fetchLatestBaileysVersion();
    if (v) version = v;
  } catch (_) {}
  logStep('3', 'Auth + socket...');

  const logger = pino({ level: 'silent' });
  const { state, saveCreds } = await useMultiFileAuthState(sessionPath);
  const sock = makeWASocket({
    auth: state,
    logger,
    printQRInTerminal: false,
    version,
  });

  sock.ev.on('creds.update', saveCreds);

  logStep('4', 'Connecting (30-60s)...');
  const connectStart = Date.now();
  await new Promise((resolvePromise, reject) => {
    const timeout = setTimeout(() => reject(new Error('Connection timeout (60s)')), 60000);
    sock.ev.on('connection.update', (update) => {
      if (update.connection === 'open') {
        clearTimeout(timeout);
        logStep('4', `Connected in ${((Date.now() - connectStart) / 1000).toFixed(1)}s`);
        resolvePromise();
      }
      if (update.connection === 'close') {
        const reason = update.lastDisconnect?.error?.message || 'Connection closed';
        clearTimeout(timeout);
        reject(new Error(reason));
      }
    });
  });

  logStep('5', 'Sending...');
  const jid = formatJid(toPhone);
  await sock.sendMessage(jid, { text: messageText });
  logStep('6', 'Sent OK');
  process.stdout.write('OK\n');
  sock.end(undefined);
  process.exit(0);
}

run().catch(exitWith);
