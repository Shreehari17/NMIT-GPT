-- Users table backing real authentication (replaces the old hardcoded
-- admin/admin login). Passwords are stored as bcrypt hashes, never plaintext.

CREATE TABLE users (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('student', 'faculty', 'admin')),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_users_username ON users (username);

-- Seed an initial admin account so you're not locked out.
-- Replace the password_hash below by generating your own:
--   python3 -c "import bcrypt; print(bcrypt.hashpw(b'yourpassword', bcrypt.gensalt()).decode())"
-- Then paste the resulting hash here before running this insert.
--Admin@123
-- INSERT INTO users (name, username, password_hash, role)
-- VALUES ('Admin', 'admin', '<paste-bcrypt-hash-here>', 'admin');