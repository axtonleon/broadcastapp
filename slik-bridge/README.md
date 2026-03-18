# Slik WhatsApp Bridge (Baileys)

Sends WhatsApp messages via WhatsApp Web sessions using Baileys.

## Setup

```bash
npm install
```

## Link a session (one-time QR scan)

From the project root:

```bash
cd slik-bridge
node link.js "../app/slik-session/session_IL_972_he_326"
```

Scan the QR code with WhatsApp (Linked Devices). Auth is saved in that folder.

## Send a message (used by the app)

```bash
node send.js "<session_folder>" "<phone_e164>" "<message>"
```

Example:

```bash
node send.js "../app/slik-session/session_IL_972_he_326" "972501234567" "Hello!"
```

## Session folder

- **From .wses files:** You have `session_IL_972_he_326.wses` etc. Add the account in the app (WhatsApp Accounts → Slik). The app creates folder `session_IL_972_he_326/` for Baileys auth.
- **Link step:** Run `node link.js "../app/slik-session/session_IL_972_he_326"` to pair via QR.
- **Note:** The .wses format is proprietary. This bridge uses Baileys and stores its own auth in the session folder. You must link each session once via QR.
