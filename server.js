const express = require('express');
const cookieParser = require('cookie-parser');
const crypto = require('crypto');
const path = require('path');
const { initializeDb, saveDb } = require('./db');
const unityRoutes = require('./routes_unity');

const app = express();
const PORT = process.env.PORT || 3000;
const BOT_SECRET = process.env.BOT_SECRET || 'your-secret-here';
const COOKIE_SECRET = process.env.COOKIE_SECRET || 'venom-modz-secret';

let db;

app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.use(cookieParser(COOKIE_SECRET));

// --- Middlewares ---

const authenticateBot = (req, res, next) => {
  const secret = req.headers['x-bot-secret'];
  if (secret !== BOT_SECRET) {
    return res.status(401).json({ error: 'Unauthorized' });
  }
  next();
};

const checkSession = async (req, res, next) => {
  const token = req.signedCookies.session_token;
  
  const handleUnauthorized = (status) => {
    if (req.path === '/Home/Index') {
      return res.redirect(`/Home/Login${status ? '?error=' + status : ''}`);
    }
    return res.status(401).send(status || 'unauthorized');
  };

  if (!token) return handleUnauthorized();

  let session;
  try {
    const stmt = db.prepare(`
      SELECT s.*, k.status, k.expires_at, k.key_text 
      FROM sessions s 
      JOIN keys k ON s.key_id = k.id 
      WHERE s.session_token = ?
    `);
    stmt.bind([token]);
    if (stmt.step()) {
      session = stmt.getAsObject();
    }
    stmt.free();
  } catch (err) {
    console.error('Error fetching session:', err);
    return handleUnauthorized();
  }

  if (!session) return handleUnauthorized();

  // Check if key is revoked
  if (session.status === 'revoked') {
    return handleUnauthorized('revoked');
  }

  // Check if key is expired
  if (session.expires_at && new Date(session.expires_at) < new Date()) {
    db.run("UPDATE keys SET status = 'expired' WHERE id = ?", [session.key_id]);
    saveDb();
    return handleUnauthorized('expired');
  }

  // Update last active
  db.run("UPDATE sessions SET last_active = CURRENT_TIMESTAMP WHERE id = ?", [session.id]);
  saveDb();
  
  req.session = session;
  next();
};

// --- Bot Endpoints ---

app.post('/api/keys/register', authenticateBot, (req, res) => {
  const { key, duration_days } = req.body;
  if (!key || !duration_days) {
    return res.status(400).json({ error: 'Missing key or duration' });
  }

  try {
    db.run('INSERT INTO keys (key_text, duration_days) VALUES (?, ?)', [key, duration_days]);
    saveDb();
    res.status(201).json({ message: 'Key registered successfully' });
  } catch (err) {
    console.error('Error registering key:', err);
    res.status(400).json({ error: 'Key already exists or invalid data' });
  }
});

app.post('/api/keys/revoke', authenticateBot, (req, res) => {
  const { key } = req.body;
  db.run("UPDATE keys SET status = 'revoked' WHERE key_text = ?", [key]);
  const changes = db.getRowsModified();
  saveDb();
  if (changes > 0) {
    res.json({ message: 'Key revoked' });
  } else {
    res.status(404).json({ error: 'Key not found' });
  }
});

app.get('/api/keys/info', authenticateBot, (req, res) => {
  const { key } = req.query;
  let keyInfo;
  try {
    const stmt = db.prepare('SELECT * FROM keys WHERE key_text = ?');
    stmt.bind([key]);
    if (stmt.step()) {
      keyInfo = stmt.getAsObject();
    }
    stmt.free();
  } catch (err) {
    console.error('Error fetching key info:', err);
    return res.status(500).json({ error: 'Internal server error' });
  }

  if (keyInfo) {
    res.json(keyInfo);
  } else {
    res.status(404).json({ error: 'Key not found' });
  }
});

// --- Web Endpoints ---

app.get('/Home/Login', (req, res) => {
  res.sendFile(path.join(__dirname, 'views', 'login.html'));
});

app.post('/Home/Login', async (req, res) => {
  const key = req.body.key || req.body.license_key;
  
  let keyInfo;
  try {
    const stmt = db.prepare('SELECT * FROM keys WHERE key_text = ?');
    stmt.bind([key]);
    if (stmt.step()) {
      keyInfo = stmt.getAsObject();
    }
    stmt.free();
  } catch (err) {
    console.error('Error fetching key info for login:', err);
    return res.redirect('/Home/Login?error=internal');
  }
  
  if (!keyInfo) {
    return res.redirect('/Home/Login?error=invalid');
  }
  
  if (keyInfo.status === 'revoked') {
    return res.redirect('/Home/Login?error=revoked');
  }
  
  // Check expiration if already redeemed
  if (keyInfo.expires_at && new Date(keyInfo.expires_at) < new Date()) {
    db.run("UPDATE keys SET status = 'expired' WHERE id = ?", [keyInfo.id]);
    saveDb();
    return res.redirect('/Home/Login?error=expired');
  }
  
  // If not redeemed, set expiration now
  if (!keyInfo.expires_at) {
    const expiresAt = new Date();
    expiresAt.setDate(expiresAt.getDate() + keyInfo.duration_days);
    db.run("UPDATE keys SET expires_at = ?, status = 'active' WHERE id = ?", [expiresAt.toISOString(), keyInfo.id]);
    saveDb();
  }
  
  // Create session
  const token = crypto.randomBytes(32).toString('hex');
  db.run('INSERT INTO sessions (session_token, key_id) VALUES (?, ?)', [token, keyInfo.id]);
  saveDb();
  
  res.cookie('session_token', token, { 
    signed: true, 
    httpOnly: true, 
    secure: process.env.NODE_ENV === 'production',
    maxAge: 30 * 24 * 60 * 60 * 1000 // 30 days
  });
  
  res.redirect('/Home/Index');
});

app.get('/Home/Index', checkSession, (req, res) => {
  res.sendFile(path.join(__dirname, 'views', 'index.html'));
});

// Unity routes
app.use('/Home', checkSession, unityRoutes);

app.get('/Home/CheckSession', async (req, res) => {
  const token = req.signedCookies.session_token;
  if (!token) return res.status(401).send('unauthorized');

  let session;
  try {
    const stmt = db.prepare(`
      SELECT s.*, k.status, k.expires_at 
      FROM sessions s 
      JOIN keys k ON s.key_id = k.id 
      WHERE s.session_token = ?
    `);
    stmt.bind([token]);
    if (stmt.step()) {
      session = stmt.getAsObject();
    }
    stmt.free();
  } catch (err) {
    console.error('Error fetching session for check:', err);
    return res.status(500).send('internal error');
  }

  if (!session) return res.status(401).send('unauthorized');
  if (session.status === 'revoked') return res.status(401).send('revoked');
  if (session.expires_at && new Date(session.expires_at) < new Date()) {
    db.run("UPDATE keys SET status = 'expired' WHERE id = ?", [session.key_id]);
    saveDb();
    return res.status(401).send('expired');
  }

  res.status(200).send('ok');
});

app.post('/Home/Logout', (req, res) => {
  const token = req.signedCookies.session_token;
  if (token) {
    db.run('DELETE FROM sessions WHERE session_token = ?', [token]);
    saveDb();
  }
  res.clearCookie('session_token');
  res.redirect('/Home/Login');
});

// Default redirect
app.get('/', (req, res) => {
  res.redirect('/Home/Index');
});

initializeDb().then(initializedDb => {
  db = initializedDb;
  app.listen(PORT, () => {
    console.log(`Server running on port ${PORT}`);
  });
}).catch(err => {
  console.error('Failed to initialize database:', err);
  process.exit(1);
});
