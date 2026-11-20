import json, os, sqlite3, subprocess, shutil, threading
from datetime import date, datetime, timedelta
import extract, polish

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("STUDYQUEST_DB") or os.path.join(HERE, "studyquest.db")
MAX_DECKS = int(os.environ.get("MAX_DECKS", "100"))
MAX_CARDS = int(os.environ.get("MAX_CARDS", "5000"))

_t = threading.local()   # the logged-in user for the request running on this thread
_ready = False

def set_user(uid):
    _t.uid = uid

def uid():
    return getattr(_t, "uid", 0)

def con():
    global _ready
    c = sqlite3.connect(DB, timeout=15)
    if not _ready:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT UNIQUE COLLATE NOCASE, pw TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER, expires TEXT);
        CREATE TABLE IF NOT EXISTS decks(id INTEGER PRIMARY KEY, name TEXT, keywords TEXT, key_sentences TEXT);
        CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY, deck_id INTEGER, term TEXT, clue TEXT,
            kind TEXT, box INTEGER DEFAULT 0, due TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS stats(k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS log(day TEXT PRIMARY KEY, n INTEGER);
        CREATE TABLE IF NOT EXISTS ustats(user_id INTEGER, k TEXT, v TEXT, PRIMARY KEY(user_id, k));
        CREATE TABLE IF NOT EXISTS ulog(user_id INTEGER, day TEXT, n INTEGER, PRIMARY KEY(user_id, day));
        CREATE TABLE IF NOT EXISTS flash(user_id INTEGER PRIMARY KEY, msg TEXT, fb TEXT);
        CREATE TABLE IF NOT EXISTS pending(token TEXT PRIMARY KEY, user_id INTEGER, data TEXT, created TEXT);
        """)
        for sql in ("ALTER TABLE items ADD COLUMN misses INTEGER DEFAULT 0",
                    "ALTER TABLE items ADD COLUMN user_id INTEGER DEFAULT 0",
                    "ALTER TABLE decks ADD COLUMN user_id INTEGER DEFAULT 0"):
            try:
                c.execute(sql)
            except sqlite3.OperationalError:
                pass
        c.executescript("""
        CREATE INDEX IF NOT EXISTS i_items ON items(user_id, deck_id);
        CREATE INDEX IF NOT EXISTS i_decks ON decks(user_id);
        """)
        c.commit()
        _ready = True
    return c

def claim_legacy(c, u):
    """Adopt rows from the old single-user database (user_id 0) for the first account."""
    c.execute("UPDATE decks SET user_id=? WHERE user_id=0", (u,))
    c.execute("UPDATE items SET user_id=? WHERE user_id=0", (u,))
    c.execute("INSERT OR IGNORE INTO ustats SELECT ?, k, v FROM stats", (u,))
    c.execute("INSERT OR IGNORE INTO ulog SELECT ?, day, n FROM log", (u,))

def lua(*args):
    exe = shutil.which("lua5.4") or shutil.which("lua")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, os.path.join(HERE, "rules.lua"), *map(str, args)],
                           capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    return r.stdout.strip().split("\n") if r.returncode == 0 and r.stdout.strip() else None

LEVELS = [(0, "Rookie"), (50, "Learner"), (150, "Scholar"), (300, "Expert"), (600, "Master")]  # mirrors rules.lua
DAYS = [0, 1, 2, 4, 7, 14]

def level_of(xp):
    out = lua("level", xp)
    if out:
        return out[0], int(out[1]) if len(out) > 1 else 0
    name, nxt = LEVELS[0][1], 0
    for n, (t, label) in enumerate(LEVELS):
        if xp >= t:
            name, nxt = label, LEVELS[n + 1][0] if n + 1 < len(LEVELS) else t
    return name, nxt

def get(c, k, d=0):
    r = c.execute("SELECT v FROM ustats WHERE user_id=? AND k=?", (uid(), k)).fetchone()
    return r[0] if r else d

def put(c, k, v):
    c.execute("INSERT OR REPLACE INTO ustats VALUES (?,?,?)", (uid(), k, str(v)))

def setting(k, d="", v=None):
    c = con()
    if v is not None:
        put(c, "set_" + k, v)
        c.commit()
    r = get(c, "set_" + k, d)
    c.close()
    return str(r)

# ---- one-time messages and uploads waiting for review (kept in the DB so they work across processes)

def flash_msg(msg):
    c = con()
    c.execute("INSERT INTO flash(user_id, msg, fb) VALUES (?,?,NULL) ON CONFLICT(user_id) DO UPDATE SET msg=excluded.msg",
              (uid(), msg))
    c.commit()
    c.close()

def flash_fb(fb):
    c = con()
    c.execute("INSERT INTO flash(user_id, msg, fb) VALUES (?,'',?) ON CONFLICT(user_id) DO UPDATE SET fb=excluded.fb",
              (uid(), json.dumps(fb)))
    c.commit()
    c.close()

def flash_take(want_fb=False):
    c = con()
    row = c.execute("SELECT msg, fb FROM flash WHERE user_id=?", (uid(),)).fetchone()
    msg, fb = (row[0] or "", json.loads(row[1]) if row[1] and want_fb else None) if row else ("", None)
    if row:
        c.execute("UPDATE flash SET msg='', fb=CASE WHEN ? THEN NULL ELSE fb END WHERE user_id=?", (int(want_fb), uid()))
        c.commit()
    c.close()
    return msg, fb

def pending_put(data, token):
    c = con()
    cutoff = (datetime.utcnow() - timedelta(hours=2)).isoformat(timespec="seconds")
    c.execute("DELETE FROM pending WHERE created < ?", (cutoff,))
    c.execute("INSERT INTO pending VALUES (?,?,?,?)", (token, uid(), json.dumps(data), datetime.utcnow().isoformat(timespec="seconds")))
    c.execute("""DELETE FROM pending WHERE user_id=? AND token NOT IN
                 (SELECT token FROM pending WHERE user_id=? ORDER BY created DESC LIMIT 5)""", (uid(), uid()))
    c.commit()
    c.close()

def pending_get(token):
    c = con()
    r = c.execute("SELECT data FROM pending WHERE token=? AND user_id=?", (token, uid())).fetchone()
    c.close()
    return json.loads(r[0]) if r else None

def pending_pop(token):
    c = con()
    c.execute("DELETE FROM pending WHERE token=? AND user_id=?", (token, uid()))
    c.commit()
    c.close()

# ---- study data (always filtered by the current user)

def analyze(text):
    res = extract.analyze(text)
    res["items"] = polish.clean(res["items"], text)
    return res

def create_deck(name, items, keywords, sents, target=None):
    c, today, u = con(), date.today().isoformat(), uid()
    row = c.execute("SELECT keywords, key_sentences FROM decks WHERE id=? AND user_id=?", (target, u)).fetchone() if target else None
    if row:
        did = target
        kws = list(dict.fromkeys([k for k in row[0].split("|") if k] + keywords))[:20]
        ss = list(dict.fromkeys([s for s in row[1].split("\n") if s] + sents))[:30]
        c.execute("UPDATE decks SET keywords=?, key_sentences=? WHERE id=? AND user_id=?", ("|".join(kws), "\n".join(ss), did, u))
    else:
        if c.execute("SELECT COUNT(*) FROM decks WHERE user_id=?", (u,)).fetchone()[0] >= MAX_DECKS:
            c.close()
            return None, 0
        cur = c.execute("INSERT INTO decks(name, keywords, key_sentences, user_id) VALUES (?,?,?,?)",
                        ((name.strip() or "Untitled")[:60], "|".join(keywords), "\n".join(sents), u))
        did = cur.lastrowid
    have = {r[0].lower() for r in c.execute("SELECT term FROM items WHERE deck_id=? AND user_id=?", (did, u))}
    room = MAX_CARDS - c.execute("SELECT COUNT(*) FROM items WHERE user_id=?", (u,)).fetchone()[0]
    rows = [(did, i["term"], i["clue"], i["kind"], today, u) for i in items if i["term"].lower() not in have]
    rows = rows[:max(0, room)]
    c.executemany("INSERT INTO items(deck_id, term, clue, kind, due, user_id) VALUES (?,?,?,?,?,?)", rows)
    c.commit()
    c.close()
    return did, len(rows)

def list_decks():
    c, today = con(), date.today().isoformat()
    rows = c.execute("""SELECT d.id, d.name, COUNT(i.id), SUM(i.due <= ?) FROM decks d
        LEFT JOIN items i ON i.deck_id = d.id AND i.user_id = d.user_id
        WHERE d.user_id=? GROUP BY d.id ORDER BY d.id DESC""", (today, uid())).fetchall()
    c.close()
    return [(a, b, n or 0, due or 0) for a, b, n, due in rows]

def best_deck():
    decks = [d for d in list_decks() if d[3] > 0]
    return max(decks, key=lambda d: d[3])[0] if decks else None

def get_deck(did):
    c, u = con(), uid()
    d = c.execute("SELECT id, name, keywords, key_sentences FROM decks WHERE id=? AND user_id=?", (did, u)).fetchone()
    items = c.execute("SELECT id, term, clue, kind, box, due, misses FROM items WHERE deck_id=? AND user_id=? ORDER BY id",
                      (did, u)).fetchall() if d else []
    c.close()
    return d, items

def get_item(iid):
    c = con()
    r = c.execute("SELECT id, deck_id, term, clue FROM items WHERE id=? AND user_id=?", (iid, uid())).fetchone()
    c.close()
    return r

def delete_deck(did):
    c, u = con(), uid()
    c.execute("DELETE FROM items WHERE deck_id=? AND user_id=?", (did, u))
    c.execute("DELETE FROM decks WHERE id=? AND user_id=?", (did, u))
    c.commit()
    c.close()

def delete_item(iid):
    c = con()
    c.execute("DELETE FROM items WHERE id=? AND user_id=?", (iid, uid()))
    c.commit()
    c.close()

def update_item(iid, term, clue):
    c = con()
    c.execute("UPDATE items SET term=?, clue=? WHERE id=? AND user_id=?", (term, clue, iid, uid()))
    c.commit()
    c.close()

def delete_user(u):
    c = con()
    for t in ("items", "decks", "ustats", "ulog", "flash", "pending", "sessions"):
        c.execute(f"DELETE FROM {t} WHERE user_id=?", (u,))
    c.execute("DELETE FROM users WHERE id=?", (u,))
    c.commit()
    c.close()

def answer(item_id, ok):
    c = con()
    row = c.execute("SELECT box, term FROM items WHERE id=? AND user_id=?", (item_id, uid())).fetchone()
    if not row:
        c.close()
        return 0
    combo = int(get(c, "combo")) + 1 if ok else 0
    out = lua("schedule", row[0], int(ok))
    box = int(out[0]) if out else (min(row[0] + 1, 5) if ok else 1)
    days = int(out[1]) if out else DAYS[box]
    today = date.today()
    iso = today.isoformat()
    c.execute("UPDATE items SET box=?, due=?, misses=COALESCE(misses,0)+? WHERE id=? AND user_id=?",
              (box, (today + timedelta(days=days)).isoformat(), 0 if ok else 1, item_id, uid()))
    out = lua("award", int(ok), combo)
    xp = int(out[0]) if out else (10 + min(combo, 5) * 2 if ok else 0)
    old_xp = int(get(c, "xp"))
    put(c, "xp", old_xp + xp)
    if xp and level_of(old_xp + xp)[0] != level_of(old_xp)[0]:
        put(c, "levelup", level_of(old_xp + xp)[0])   # shown once as a celebration banner
    put(c, "combo", combo)
    last = get(c, "last_day", "")
    if last != iso:
        yest = (today - timedelta(days=1)).isoformat()
        put(c, "streak", int(get(c, "streak")) + 1 if last == yest else 1)
        put(c, "last_day", iso)
    c.execute("INSERT INTO ulog VALUES (?,?,1) ON CONFLICT(user_id, day) DO UPDATE SET n=n+1", (uid(), iso))
    put(c, "s_n", int(get(c, "s_n")) + 1)
    put(c, "s_ok", int(get(c, "s_ok")) + int(ok))
    put(c, "s_xp", int(get(c, "s_xp")) + xp)
    if not ok:
        miss = [m for m in str(get(c, "s_miss", "")).split("|") if m]
        if row[1] not in miss:
            miss.append(row[1])
        put(c, "s_miss", "|".join(miss))
    c.commit()
    c.close()
    return xp

def session(reset=False):
    c = con()
    s = {"n": int(get(c, "s_n")), "ok": int(get(c, "s_ok")), "xp": int(get(c, "s_xp")),
         "miss": [m for m in str(get(c, "s_miss", "")).split("|") if m]}
    if reset:
        for k in ("s_n", "s_ok", "s_xp"):
            put(c, k, 0)
        put(c, "s_miss", "")
        c.commit()
    c.close()
    return s

def status():
    c, today = con(), date.today()
    xp, combo, goal = int(get(c, "xp")), int(get(c, "combo")), int(get(c, "set_goal", 20))
    streak, last = int(get(c, "streak")), get(c, "last_day", "")
    if last not in (today.isoformat(), (today - timedelta(days=1)).isoformat()):
        streak = 0
    r = c.execute("SELECT n FROM ulog WHERE user_id=? AND day=?", (uid(), today.isoformat())).fetchone()
    c.close()
    level, nxt = level_of(xp)
    return {"xp": xp, "streak": streak, "combo": combo, "goal": goal, "today": r[0] if r else 0,
            "level": level, "next": nxt}

def take_levelup():
    """Returns the new level name once after a level-up, then forgets it."""
    c = con()
    v = str(get(c, "levelup", ""))
    if v:
        put(c, "levelup", "")
        c.commit()
    c.close()
    return v

def progress():
    c, today, u = con(), date.today(), uid()
    weak = c.execute("SELECT term, deck_id, misses FROM items WHERE user_id=? AND misses>0 ORDER BY misses DESC, box ASC LIMIT 8", (u,)).fetchall()
    total, mast = c.execute("SELECT COUNT(*), SUM(box>=4) FROM items WHERE user_id=?", (u,)).fetchone()
    start = (today - timedelta(days=34)).isoformat()
    log = dict(c.execute("SELECT day, n FROM ulog WHERE user_id=? AND day>=?", (u, start)).fetchall())
    c.close()
    return {"weak": weak, "total": total or 0, "mastered": mast or 0, "log": log}
