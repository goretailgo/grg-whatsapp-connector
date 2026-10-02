'use strict';

const fs = require('fs');
const path = require('path');
const express = require('express');
const pino = require('pino');
const QRCode = require('qrcode');
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
  Browsers,
} = require('@whiskeysockets/baileys');

const PORT = parseInt(process.env.PORT || '3100', 10);
const HOST = process.env.HOST || '0.0.0.0';
const API_KEY = process.env.API_KEY || '';
const SESSIONS_DIR = process.env.SESSIONS_DIR || path.join(__dirname, 'sessions');
const logger = pino({ level: process.env.LOG_LEVEL || 'warn' });

if (!API_KEY || API_KEY === 'change-me') {
  logger.error('API_KEY is not set. Put a strong value in service/.env');
  process.exit(1);
}
fs.mkdirSync(SESSIONS_DIR, { recursive: true });

const ID_RE = /^[A-Za-z0-9_-]{1,64}$/;
const sessions = new Map(); // id -> { sock, state, qr, me, starting }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function info(id) {
  const s = sessions.get(id);
  if (!s) return { id, state: 'closed', qr: null, me: null };
  return { id, state: s.state, qr: s.qr, me: s.me };
}

async function startSession(id) {
  let s = sessions.get(id);
  if (s && (s.sock || s.starting)) return s;
  if (!s) {
    s = { sock: null, state: 'connecting', qr: null, me: null, starting: false };
    sessions.set(id, s);
  }
  s.starting = true;
  s.state = 'connecting';
  s.qr = null;
  const dir = path.join(SESSIONS_DIR, id);
  try {
    const { state: auth, saveCreds } = await useMultiFileAuthState(dir);
    let version;
    try {
      ({ version } = await fetchLatestBaileysVersion());
    } catch (_) {
      /* fall back to bundled version */
    }
    const sock = makeWASocket({
      version,
      auth,
      logger,
      printQRInTerminal: false,
      browser: Browsers.ubuntu('GoRetailGo POS'),
      markOnlineOnConnect: false,
      syncFullHistory: false,
    });
    s.sock = sock;
    sock.ev.on('creds.update', saveCreds);
    sock.ev.on('connection.update', async (u) => {
      if (s.sock !== sock) return;
      const { connection, lastDisconnect, qr } = u;
      if (qr) {
        s.state = 'qr';
        s.qr = await QRCode.toDataURL(qr, { width: 300, margin: 1 });
      }
      if (connection === 'open') {
        s.state = 'open';
        s.qr = null;
        s.me = (sock.user && sock.user.id) || null;
        logger.warn({ id, me: s.me }, 'WhatsApp connected');
      }
      if (connection === 'close') {
        const code = lastDisconnect && lastDisconnect.error && lastDisconnect.error.output
          ? lastDisconnect.error.output.statusCode
          : undefined;
        s.sock = null;
        s.qr = null;
        if (code === DisconnectReason.loggedOut) {
          s.state = 'logged_out';
          s.me = null;
          fs.rmSync(dir, { recursive: true, force: true });
          logger.warn({ id }, 'WhatsApp logged out, session removed');
        } else if (code === DisconnectReason.restartRequired || auth.creds.me) {
          s.state = 'reconnecting';
          const delay = code === DisconnectReason.restartRequired ? 500 : 5000;
          setTimeout(() => startSession(id).catch((e) => logger.error(e)), delay);
        } else {
          s.state = 'closed'; // QR expired without scan
        }
      }
    });
  } finally {
    s.starting = false;
  }
  return s;
}

async function waitReady(id, ms = 15000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const st = info(id).state;
    if (['qr', 'open', 'closed', 'logged_out'].includes(st)) return;
    await sleep(250);
  }
}

const app = express();
app.use(express.json({ limit: '30mb' }));

app.get('/health', (req, res) => res.json({ ok: true, sessions: sessions.size }));

app.use((req, res, next) => {
  if (req.get('x-api-key') !== API_KEY) return res.status(401).json({ error: 'unauthorized' });
  next();
});

app.param('id', (req, res, next, id) => {
  if (!ID_RE.test(id)) return res.status(400).json({ error: 'invalid session id' });
  next();
});

const wrap = (fn) => (req, res) =>
  fn(req, res).catch((e) => {
    logger.error(e);
    res.status(500).json({ error: e.message || 'internal error' });
  });

app.post('/sessions/:id/connect', wrap(async (req, res) => {
  const { id } = req.params;
  await startSession(id);
  await waitReady(id);
  res.json(info(id));
}));

app.get('/sessions/:id/status', wrap(async (req, res) => {
  res.json(info(req.params.id));
}));

app.post('/sessions/:id/logout', wrap(async (req, res) => {
  const { id } = req.params;
  const s = sessions.get(id);
  if (s && s.sock) {
    const sock = s.sock;
    s.sock = null;
    try {
      await sock.logout();
    } catch (_) {
      /* ignore */
    }
  }
  sessions.delete(id);
  fs.rmSync(path.join(SESSIONS_DIR, id), { recursive: true, force: true });
  res.json({ id, state: 'logged_out' });
}));

app.post('/sessions/:id/send-document', wrap(async (req, res) => {
  const { id } = req.params;
  const s = sessions.get(id);
  if (!s || !s.sock || s.state !== 'open') {
    return res.status(409).json({ error: 'WhatsApp not connected. Scan the QR in Odoo.' });
  }
  const { number, base64, fileName, mimetype, caption } = req.body || {};
  const digits = String(number || '').replace(/\D/g, '');
  if (digits.length < 10) return res.status(400).json({ error: 'invalid number' });
  if (!base64) return res.status(400).json({ error: 'missing document' });

  const found = (await s.sock.onWhatsApp(`${digits}@s.whatsapp.net`)) || [];
  const target = found[0];
  if (!target || !target.exists) {
    return res.status(404).json({ error: `+${digits} is not on WhatsApp` });
  }
  const msg = await s.sock.sendMessage(target.jid, {
    document: Buffer.from(base64, 'base64'),
    mimetype: mimetype || 'application/pdf',
    fileName: fileName || 'invoice.pdf',
    caption: caption || '',
  });
  res.json({ ok: true, to: target.jid, id: msg && msg.key ? msg.key.id : null });
}));

app.post('/sessions/:id/send-image', wrap(async (req, res) => {
  const { id } = req.params;
  const s = sessions.get(id);
  if (!s || !s.sock || s.state !== 'open') {
    return res.status(409).json({ error: 'WhatsApp not connected. Scan the QR in Odoo.' });
  }
  const { number, base64, mimetype, caption } = req.body || {};
  const digits = String(number || '').replace(/\D/g, '');
  if (digits.length < 10) return res.status(400).json({ error: 'invalid number' });
  if (!base64) return res.status(400).json({ error: 'missing image' });

  const found = (await s.sock.onWhatsApp(`${digits}@s.whatsapp.net`)) || [];
  const target = found[0];
  if (!target || !target.exists) {
    return res.status(404).json({ error: `+${digits} is not on WhatsApp` });
  }
  const msg = await s.sock.sendMessage(target.jid, {
    image: Buffer.from(base64, 'base64'),
    mimetype: mimetype || 'image/jpeg',
    caption: caption || '',
  });
  res.json({ ok: true, to: target.jid, id: msg && msg.key ? msg.key.id : null });
}));

// Restore paired sessions on boot
for (const id of fs.readdirSync(SESSIONS_DIR)) {
  if (ID_RE.test(id) && fs.existsSync(path.join(SESSIONS_DIR, id, 'creds.json'))) {
    startSession(id).catch((e) => logger.error(e));
  }
}

process.on('unhandledRejection', (e) => logger.error(e));

app.listen(PORT, HOST, () => logger.warn(`grg-whatsapp service on ${HOST}:${PORT}`));
