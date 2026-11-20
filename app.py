import os, re, difflib, secrets, sys, traceback
from email.parser import BytesParser
from email.policy import default
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse
import auth, db, extract, pages, modes

HERE = os.path.dirname(os.path.abspath(__file__))
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))
TRUST_PROXY = os.environ.get("TRUST_PROXY") == "1"   # set when behind a reverse proxy / PythonAnywhere
MAXB = 20 * 1024 * 1024
MAX_FILES = 5
COOKIE = "sq_session"
SECURITY = [
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "same-origin"),
    ("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'none'; "
                                "form-action 'self'; frame-ancestors 'none'"),
]

def parse_multipart(ctype, body):
    raw = b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body
    msg = BytesParser(policy=default).parsebytes(raw)
    fields, files = {}, []
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        item = (part.get_filename(), part.get_payload(decode=True) or b"")
        fields[name] = item
        if name == "file" and item[0] and item[1]:
            files.append(item)   # the file box accepts several files
    return fields, files

def norm(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()

def same(a, b):
    a, b = norm(a), norm(b)
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= 0.85

def to_int(v, d=0):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return d
    return n if abs(n) < 2 ** 62 else d   # SQLite integers are 64-bit

class Resp:
    def __init__(self, body=b"", status=200, ctype="text/html; charset=utf-8", headers=None):
        self.body = body.encode() if isinstance(body, str) else body
        self.status, self.ctype, self.extra = status, ctype, list(headers or [])

    def headers(self):
        cache = [] if any(k == "Cache-Control" for k, _ in self.extra) else [("Cache-Control", "no-store")]
        return [("Content-Type", self.ctype), ("Content-Length", str(len(self.body)))] + SECURITY + cache + self.extra

def redirect(to, extra=None):
    return Resp(b"", 303, headers=[("Location", to)] + (extra or []))

def cookie(token, secure, max_age):
    c = f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={max_age}"
    return ("Set-Cookie", c + ("; Secure" if secure else ""))

def client_ip(remote, headers):
    if TRUST_PROXY and headers.get("x-forwarded-for"):
        return headers["x-forwarded-for"].split(",")[-1].strip()   # last hop = added by our proxy
    return remote

def handle(method, target, headers, body, remote, secure):
    """Framework-free request handler. body is None when the upload was over the size limit."""
    u = urlparse(target)
    p = u.path
    if method == "GET" and p == "/style.css":
        with open(os.path.join(HERE, "style.css"), "rb") as f:
            return Resp(f.read(), ctype="text/css", headers=[("Cache-Control", "public, max-age=300")])
    if p == "/healthz":
        return Resp("ok", ctype="text/plain")
    ck = SimpleCookie()
    try:
        ck.load(headers.get("cookie", ""))
    except Exception:
        pass
    token = ck[COOKIE].value if COOKIE in ck else ""
    uid = auth.user_for(token) if token else 0
    db.set_user(uid)
    try:
        if method == "POST":
            origin = headers.get("origin")
            if origin and urlparse(origin).netloc not in (headers.get("host", ""), headers.get("x-forwarded-host", "")):
                return Resp("Bad origin", 403, "text/plain")
        if not uid:
            return public(method, p, u, headers, body, client_ip(remote, headers), secure)
        return private(method, p, u, headers, body, token, secure)
    except Exception:
        traceback.print_exc(file=sys.stderr)   # shows in the Termux console / PythonAnywhere error log
        return Resp("<!doctype html><meta name='viewport' content='width=device-width, initial-scale=1'>"
                    "<link rel='stylesheet' href='/style.css'><body class='cream m'><h2>Something went wrong</h2>"
                    "<p class='muted'>That didn't work, but your data is safe.</p><a class='btn' href='/'>Back home</a>",
                    500)
    finally:
        db.set_user(0)

def public(method, p, u, headers, body, ip, secure):
    if p not in ("/login", "/signup"):
        return redirect("/login")
    kind = p[1:]
    need_code = bool(auth.SIGNUP_CODE)
    if method == "GET":
        return Resp(pages.auth_page(kind, code_needed=need_code))
    if body is None or len(body) > 10_000:
        return Resp("Too large", 413, "text/plain")
    form = parse_qs(body.decode("utf8", "ignore"), keep_blank_values=True)
    g = lambda k: form.get(k, [""])[0]
    name = g("name").strip()
    keys = (("ip", ip), ("name", name.lower()))
    if auth.throttled(*keys):
        return Resp(pages.auth_page(kind, "Too many attempts. Wait a few minutes and try again.", name, need_code), 429)
    if kind == "login":
        uid = auth.login(name, g("pw"))
        err = "" if uid else "Wrong username or password."
    else:
        uid, err = auth.register(name, g("pw"), g("code"))
    if not uid:
        auth.record_fail(*keys)
        return Resp(pages.auth_page(kind, err, name, need_code), 400)
    return redirect("/", [cookie(auth.new_session(uid), secure, auth.SESSION_DAYS * 86400)])

def private(method, p, u, headers, body, token, secure):
    if method == "POST":
        return post(p, headers, body, token, secure)
    q = parse_qs(u.query)
    one = lambda k, d="": q.get(k, [d])[0]
    if p == "/now":
        did = db.best_deck()
        if did:
            return redirect(f"/deck?id={did}&m=flash")
        db.flash_msg("You're all caught up!")
        return redirect("/")
    msg, fb = db.flash_take(want_fb=(p == "/deck"))
    if p == "/deck":
        return Resp(pages.deck_page(to_int(one("id")), one("m", "flash"), msg, one("q"), one("f", "all"), fb, one("c") == "1"))
    if p == "/study":
        return Resp(pages.study_page(msg))
    if p == "/progress":
        return Resp(pages.progress_page())
    if p == "/settings":
        return Resp(pages.settings_page(msg))
    if p == "/account":
        return Resp(pages.account_page(msg))
    if p == "/summary":
        return Resp(pages.summary_page(db.session(True)))
    if p == "/confirm":
        return Resp(pages.confirm_page(to_int(one("d"))))
    if p == "/edit":
        item = db.get_item(to_int(one("i")))
        if item:
            return Resp(pages.edit_page(item))
    if p == "/preview":
        pend = db.pending_get(one("t"))
        if pend:
            return Resp(pages.preview_page(one("t"), pend))
        db.flash_msg("That upload expired. Please upload again.")
        return redirect("/")
    return Resp(pages.home(msg))

def upload(body, ctype):
    try:
        f, files = parse_multipart(ctype, body)
        if files:
            parts = []
            for fn, data in files[:MAX_FILES]:
                try:
                    parts.append(extract.read_file(fn, data))
                except extract.ReadError as err:
                    raise extract.ReadError(f"{fn}: {err}" if len(files) > 1 else str(err))
            text = "\n\n".join(parts)[:extract.MAX_CHARS]
            name = os.path.splitext(files[0][0])[0] + (f" +{len(files) - 1} more" if len(files) > 1 else "")
        else:
            text, name = f.get("text", (None, b""))[1].decode("utf8", "ignore")[:extract.MAX_CHARS], "Pasted notes"
        res = db.analyze(text) if text.strip() else {"items": []}
    except extract.ReadError as err:
        db.flash_msg(str(err))
        return redirect("/")
    except Exception:
        traceback.print_exc(file=sys.stderr)
        db.flash_msg("Something went wrong reading that. Try pasting the text instead.")
        return redirect("/")
    if not res["items"]:
        db.flash_msg("No study items found. Notes with sentences like 'X is ...' or 'X: ...' work best.")
        return redirect("/")
    token = secrets.token_hex(6)
    db.pending_put({"name": name, "items": res["items"], "keywords": res["keywords"], "sents": res["key_sentences"]}, token)
    return redirect(f"/preview?t={token}")

def post(path, headers, body, token, secure):
    if body is None:
        db.flash_msg(f"Upload too big ({MAXB // 1048576} MB max in total). Try fewer or smaller files.")
        return redirect("/")
    if path == "/upload":
        return upload(body, headers.get("content-type", ""))
    form = parse_qs(body.decode("utf8", "ignore"), keep_blank_values=True)
    g = lambda k: form.get(k, [""])[0]
    did, iid, mode = to_int(g("d")), to_int(g("i")), g("m")
    if path == "/logout":
        auth.end_session(token)
        return redirect("/login", [cookie("", secure, 0)])
    if path == "/account/delete":
        if not auth.verify_password(db.uid(), g("pw")):
            db.flash_msg("That password isn't right.")
            return redirect("/account")
        db.delete_user(db.uid())
        return redirect("/login", [cookie("", secure, 0)])
    if path == "/create":
        pend = db.pending_get(g("t"))
        if not pend:
            db.flash_msg("That upload expired. Please upload again.")
            return redirect("/")
        pick = [pend["items"][k] for k in (to_int(x, -1) for x in form.get("k", [])) if 0 <= k < len(pend["items"])]
        if not pick:
            db.flash_msg("Tick at least one card.")
            return redirect(f"/preview?t={g('t')}")
        did, added = db.create_deck(g("name"), pick, pend["keywords"], pend["sents"], to_int(g("target")) or None)
        if did is None:
            db.flash_msg("You've reached the reviewer limit. Delete one first.")
            return redirect("/")
        db.pending_pop(g("t"))
        db.flash_msg(f"Added {added} cards.")
        return redirect(f"/deck?id={did}&m=review")
    if path == "/delete":
        db.delete_deck(did)
        db.flash_msg("Reviewer deleted.")
        return redirect("/")
    if path == "/edit":
        term, clue = g("term").strip()[:80], g("clue").strip()[:600]
        if term and clue:
            db.update_item(iid, term, clue)
            db.flash_msg("Card saved.")
        return redirect(f"/deck?id={did}&m=review")
    if path == "/rmcard":
        db.delete_item(iid)
        db.flash_msg("Card removed.")
        return redirect(f"/deck?id={did}&m=review")
    if path == "/settings":
        db.setting("theme", v=g("theme") if g("theme") in ("cream", "dark", "light") else "cream")
        db.setting("size", v=g("size") if g("size") in ("s", "m", "l") else "m")
        db.setting("goal", v=max(5, min(200, to_int(g("goal"), 20))))
        db.flash_msg("Settings saved.")
        return redirect("/settings")
    if path == "/answer":
        item = next((x for x in db.get_deck(did)[1] if x[0] == iid), None)
        if item:
            if mode == "quiz":
                ok = g("c") == item[1]
            elif mode == "ident":
                ok = same(g("t"), item[1])
            else:
                ok = g("ok") == "1"
            xp = db.answer(iid, ok)
            if mode in ("quiz", "ident"):
                db.flash_fb({"ok": ok, "xp": xp, "term": item[1], "text": modes.body_text(item), })
            else:
                db.flash_msg(f"+{xp} XP" if ok else "No problem, we'll show it again soon.")
            if db.session()["n"] >= 10:
                return redirect("/summary")
        return redirect(f"/deck?id={did}&m={mode}")
    return redirect("/")

# ---- adapter 1: built-in server (local, phone, or a VPS behind Caddy/nginx)

class H(BaseHTTPRequestHandler):
    def run(self, method):
        n = to_int(self.headers.get("Content-Length"))
        body = b""
        if method == "POST":
            body = self.rfile.read(n) if 0 <= n <= MAXB else None
        headers = {k.lower(): v for k, v in self.headers.items()}
        secure = headers.get("x-forwarded-proto") == "https"
        r = handle(method, self.path, headers, body, self.client_address[0], secure)
        self.send_response(r.status)
        for k, v in r.headers():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(r.body)

    def do_GET(self):
        self.run("GET")

    def do_POST(self):
        self.run("POST")

# ---- adapter 2: WSGI (PythonAnywhere, gunicorn, uwsgi)

def application(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET")
    n = to_int(environ.get("CONTENT_LENGTH"))
    body = b""
    if method == "POST":
        body = environ["wsgi.input"].read(n) if 0 <= n <= MAXB else None
    headers = {k[5:].replace("_", "-").lower(): v for k, v in environ.items() if k.startswith("HTTP_")}
    headers["content-type"] = environ.get("CONTENT_TYPE", "")
    target = environ.get("PATH_INFO", "/") + ("?" + environ["QUERY_STRING"] if environ.get("QUERY_STRING") else "")
    secure = environ.get("wsgi.url_scheme") == "https" or headers.get("x-forwarded-proto") == "https"
    if method not in ("GET", "POST"):
        r = Resp("Method not allowed", 405, "text/plain")
    else:
        r = handle(method, target, headers, body, environ.get("REMOTE_ADDR", ""), secure)
    start_response(f"{r.status} {HTTPStatus(r.status).phrase}", r.headers())
    return [r.body]

if __name__ == "__main__":
    print(f"StudyQuest running: http://localhost:{PORT}")
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
