import hashlib, hmac, os, re, secrets, time
from datetime import datetime, timedelta
import db

MAX_USERS = int(os.environ.get("MAX_USERS", "500"))
SIGNUP_CODE = os.environ.get("SIGNUP_CODE", "")  # set to make sign-up invite-only
SESSION_DAYS = 30
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")

_fails = {}  # throttle key -> [timestamps]; in-memory is enough for light protection

def _now():
    return datetime.utcnow().isoformat(timespec="seconds")

def _kdf(pw, salt, scheme):
    pw = pw.encode()
    if scheme == "scrypt":
        return hashlib.scrypt(pw, salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return hashlib.pbkdf2_hmac("sha256", pw, salt, 600_000, dklen=32)

def hash_pw(pw):
    scheme = "scrypt" if hasattr(hashlib, "scrypt") else "pbkdf2"
    try:
        salt = secrets.token_bytes(16)
        return f"{scheme}${salt.hex()}${_kdf(pw, salt, scheme).hex()}"
    except (ValueError, MemoryError):  # scrypt unavailable at runtime
        salt = secrets.token_bytes(16)
        return f"pbkdf2${salt.hex()}${_kdf(pw, salt, 'pbkdf2').hex()}"

def check_pw(pw, stored):
    try:
        scheme, salt, want = stored.split("$")
        got = _kdf(pw, bytes.fromhex(salt), scheme)
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(got.hex(), want)

def throttled(*keys):
    cutoff = time.time() - 600
    for k in keys:
        _fails[k] = [t for t in _fails.get(k, []) if t > cutoff]
        if len(_fails[k]) >= 10:
            return True
    return False

def record_fail(*keys):
    for k in keys:
        _fails.setdefault(k, []).append(time.time())
    if len(_fails) > 5000:  # keep memory bounded
        _fails.clear()

def register(name, pw, code=""):
    """Returns (user_id, error)."""
    name = name.strip()
    if SIGNUP_CODE and not hmac.compare_digest(code.encode(), SIGNUP_CODE.encode()):
        return None, "That invite code isn't right."
    if not NAME_RE.match(name):
        return None, "Username: 3-30 letters, numbers, dot, dash or underscore."
    if not 8 <= len(pw) <= 200:
        return None, "Password must be 8 to 200 characters."
    c = db.con()
    try:
        total = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if total >= MAX_USERS:
            return None, "Sign-ups are closed right now."
        try:
            cur = c.execute("INSERT INTO users(name, pw, created) VALUES (?,?,?)", (name, hash_pw(pw), _now()))
        except db.sqlite3.IntegrityError:
            return None, "That username is taken."
        uid = cur.lastrowid
        if total == 0:  # first account adopts data from the old single-user version
            db.claim_legacy(c, uid)
        c.commit()
        return uid, ""
    finally:
        c.close()

def login(name, pw):
    c = db.con()
    row = c.execute("SELECT id, pw FROM users WHERE name=?", (name.strip(),)).fetchone()
    c.close()
    if not row:
        hash_pw(pw)  # keep timing similar for unknown users
        return None
    return row[0] if check_pw(pw, row[1]) else None

def verify_password(uid, pw):
    c = db.con()
    row = c.execute("SELECT pw FROM users WHERE id=?", (uid,)).fetchone()
    c.close()
    return bool(row) and check_pw(pw, row[0])

def _th(token):
    return hashlib.sha256(token.encode()).hexdigest()  # only hashes are stored

def new_session(uid):
    token = secrets.token_urlsafe(32)
    c = db.con()
    c.execute("DELETE FROM sessions WHERE expires < ?", (_now(),))
    exp = (datetime.utcnow() + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
    c.execute("INSERT INTO sessions VALUES (?,?,?)", (_th(token), uid, exp))
    c.commit()
    c.close()
    return token

def user_for(token):
    c = db.con()
    row = c.execute("SELECT user_id FROM sessions WHERE token=? AND expires>=?", (_th(token), _now())).fetchone()
    c.close()
    return row[0] if row else 0

def end_session(token):
    c = db.con()
    c.execute("DELETE FROM sessions WHERE token=?", (_th(token),))
    c.commit()
    c.close()

def username(uid):
    c = db.con()
    row = c.execute("SELECT name FROM users WHERE id=?", (uid,)).fetchone()
    c.close()
    return row[0] if row else ""
