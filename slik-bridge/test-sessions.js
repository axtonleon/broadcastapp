#!/usr/bin/env node
/**
 * Test Slik session(s) - verify Baileys auth works and connection opens.
 * Does not send any messages.
 *
 * Usage:
 *   node test-sessions.js <sessionFolder> [sessionFolder2 ...]
 *   node test-sessions.js --json <sessionFolder> [sessionFolder2 ...]
 *
 * Options:
 *   --json   Output results as JSON for programmatic use
 *
 * Exit codes:
 *   0  All sessions passed
 *   1  One or more sessions failed
 */
import { existsSync } from 'fs';
import { resolve } from 'path';
import makeWASocket, { useMultiFileAuthState } from '@whiskeysockets/baileys';
import pino from 'pino';

/** WhatsApp version - override when Baileys default gets 405 from WhatsApp. See wppconnect.io/whatsapp-versions */
const WA_VERSION = [2, 3000, 1035162453];

const args = process.argv.slice(2);
const jsonMode = args.includes('--json');
const sessionFolders = args.filter((a) => !a.startsWith('--'));

if (sessionFolders.length === 0) {
  process.stderr.write(
    'Usage: node test-sessions.js [--json] <sessionFolder> [sessionFolder2 ...]\n'
  );
  process.exit(2);
}

const CONNECTION_TIMEOUT_MS = 60000;
const logger = pino({ level: 'silent' });

/**
 * Check if a session folder exists and appears to have Baileys auth.
 * Baileys multi-file auth uses creds.json as the main credential store.
 */
function sessionFolderExists(sessionFolder) {
  const resolved = resolve(sessionFolder);
  if (!existsSync(resolved)) return false;
  const credsPath = resolve(resolved, 'creds.json');
  return existsSync(credsPath);
}

/**
 * Test a single session: connect and wait for 'open' connection.
 * @returns {Promise<{ok: boolean, session: string, message?: string}>}
 */
async function testSession(sessionFolder) {
  const resolved = resolve(sessionFolder);
  const sessionName = sessionFolder.split(/[/\\]/).pop() || resolved;

  if (!sessionFolderExists(sessionFolder)) {
    return {
      ok: false,
      session: sessionName,
      message: 'Session folder missing or no creds.json (not linked)',
    };
  }

  try {
    const { state } = await useMultiFileAuthState(resolved);
    const sock = makeWASocket({
      auth: state,
      logger,
      printQRInTerminal: false,
      version: WA_VERSION,
    });

    const result = await new Promise((resolvePromise) => {
      const timeout = setTimeout(() => {
        sock.end(undefined);
        resolvePromise({
          ok: false,
          session: sessionName,
          message: `Connection timeout (${CONNECTION_TIMEOUT_MS / 1000}s)`,
        });
      }, CONNECTION_TIMEOUT_MS);

      sock.ev.on('connection.update', (update) => {
        if (update.connection === 'open') {
          clearTimeout(timeout);
          sock.end(undefined);
          resolvePromise({ ok: true, session: sessionName });
        }
        if (update.connection === 'close') {
          clearTimeout(timeout);
          const reason =
            update.lastDisconnect?.error?.message || 'Connection closed';
          sock.end(undefined);
          resolvePromise({ ok: false, session: sessionName, message: reason });
        }
      });
    });

    return result;
  } catch (err) {
    return {
      ok: false,
      session: sessionName,
      message: err?.message || String(err),
    };
  }
}

async function run() {
  const results = [];

  for (const folder of sessionFolders) {
    const result = await testSession(folder);
    results.push(result);

    if (!jsonMode) {
      const status = result.ok ? 'PASS' : 'FAIL';
      const msg = result.message ? `: ${result.message}` : '';
      process.stdout.write(`${status} ${result.session}${msg}\n`);
    }
  }

  if (jsonMode) {
    const summary = {
      passed: results.filter((r) => r.ok).length,
      failed: results.filter((r) => !r.ok).length,
      results,
    };
    process.stdout.write(JSON.stringify(summary, null, 2) + '\n');
  }

  const allPassed = results.every((r) => r.ok);
  process.exit(allPassed ? 0 : 1);
}

run().catch((err) => {
  process.stderr.write('ERROR: ' + (err?.message || String(err)) + '\n');
  process.exit(1);
});
