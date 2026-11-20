import shutil
from datetime import date, timedelta
from urllib.parse import quote
import auth, db, modes
from modes import e, plural

THEME_COLOR = {"dark": "#0D1612", "light": "#F5F8F4", "cream": "#F4EAD5"}
THEMES = [("cream", "Cream & Green"), ("dark", "Dark"), ("light", "Light")]

def levelup(name):
    if not name:
        return ""
    bits = "".join(f"<i style='--i:{n}'></i>" for n in range(14))
    return (f"<div class='levelup' role='status'>{bits}<b>Level up!</b>"
            f"<span>You're now a {e(name)}. Keep it going.</span></div>")

def layout(body, msg="", active="home"):
    st = db.status()
    theme = db.setting("theme", "cream")
    cls = theme + " " + db.setting("size", "m")
    lvl = db.take_levelup()
    nav = ""
    for k, href, label in (("home", "/", "Home"), ("study", "/study", "Study"),
                           ("progress", "/progress", "Progress"), ("settings", "/settings", "Settings")):
        nav += f"<a class='nl{' on' if k == active else ''}' href='{href}'>{label}</a>"
    pop = f"<div class='pop'>{e(msg)}</div>" if msg else ""
    n = st["streak"]
    flame = (f"<span class='streak' title='{n} day streak'><i class='flame{'' if n else ' off'}'></i>"
             f"<b>{n}</b><span class='sr'> day streak</span></span>")
    return (f"<!doctype html><html class='{cls}'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<meta name='theme-color' content='{THEME_COLOR.get(theme, '#F4EAD5')}'>"
            "<title>StudyQuest</title><link rel='stylesheet' href='/style.css'></head><body>"
            f"{levelup(lvl)}<div class='bar'><span class='brand'>StudyQuest</span>"
            f"<span class='stats'><span>{e(st['level'])}</span><span>{st['xp']} XP</span>{flame}</span></div>"
            f"{pop}{body}<div class='nav'>{nav}</div></body></html>")

def upload_form():
    ocr = bool(shutil.which("tesseract"))   # photos only work when the OCR program is installed
    kinds = "PDF, Word, PowerPoint" + (", photos / screenshots" if ocr else "") + ", or text (up to 5 files)"
    accept = ".txt,.md,.docx,.pptx,.odt,.odp,.pdf" + (",image/*" if ocr else "")
    return ("<form method='post' action='/upload' enctype='multipart/form-data' class='upload'>"
            f"<b>Upload your notes</b><div class='muted'>{kinds}</div>"
            f"<input type='file' name='file' multiple accept='{accept}'>"
            "<div class='muted'>or paste text:</div>"
            "<textarea name='text' rows='4' placeholder='Paste notes here'></textarea>"
            "<button>Read my notes</button></form>")

def home(msg=""):
    st, decks = db.status(), db.list_decks()
    pct = min(100, int(st["xp"] * 100 / st["next"])) if st["next"] else 100
    gp = min(100, st["today"] * 100 // st["goal"]) if st["goal"] else 0
    out = (f"<div class='panel row'><div><div class='level'>Level: {e(st['level'])}</div>"
           f"<div class='muted'>{st['xp']} / {st['next']} XP</div>"
           f"<div class='track'><div class='fill' style='width:{pct}%'></div></div></div>"
           f"<div class='ring' style='--p:{gp * 3.6}deg' title='Daily goal'><span>{st['today']}/{st['goal']}</span></div></div>")
    if decks:
        due = sum(d[3] for d in decks)
        out += (f"<a class='btn' href='/now'>Study now ({due} due)</a>" if due else "<div class='btn off'>All caught up</div>")
        out += "<h2>Your reviewers</h2>"
        for did, name, n, dd in decks:
            out += (f"<div class='card row'><div><b>{e(name)}</b><span class='muted'>{plural(n, 'card')}, {dd} due</span></div>"
                    f"<a class='btn' href='/deck?id={did}&m=flash'>Study</a></div>")
        out += f"<details class='panel'><summary>+ New reviewer</summary>{upload_form()}</details>"
    else:
        out += "<h2>Start here</h2>" + upload_form()
    return layout(out, msg, "home")

def study_page(msg=""):
    decks = db.list_decks()
    out = "<h2>Study</h2>"
    for did, name, n, dd in decks:
        out += (f"<div class='card'><b>{e(name)}</b><div class='muted'>{plural(n, 'card')}, {dd} due</div>"
                f"<div class='row2 gap'><a class='btn' href='/deck?id={did}&m=flash'>Flashcards</a>"
                f"<a class='btn ghost' href='/deck?id={did}&m=quiz'>Quiz</a>"
                f"<a class='btn ghost' href='/deck?id={did}&m=ident'>Identify</a></div></div>")
    if not decks:
        out += "<p class='muted'>No reviewers yet. Upload notes on the Home tab.</p>"
    return layout(out, msg, "study")

def progress_page():
    p, st = db.progress(), db.status()
    pct = p["mastered"] * 100 // p["total"] if p["total"] else 0
    cells = ""
    for i in range(34, -1, -1):
        d = (date.today() - timedelta(days=i)).isoformat()
        n = p["log"].get(d, 0)
        c = 0 if n == 0 else 1 if n < 5 else 2 if n < 15 else 3
        cells += f"<div class='cell c{c}' title='{d}: {n}'></div>"
    weak = "".join(f"<a class='card row' href='/deck?id={did}&m=review&q={quote(t)}'><b>{e(t)}</b>"
                   f"<span class='muted'>missed {m}x</span></a>" for t, did, m in p["weak"])
    return layout(f"<h2>Progress</h2><div class='panel'><div class='level'>{e(st['level'])}</div>"
                  f"<div class='muted'>{st['xp']} XP | {st['streak']} day streak</div></div>"
                  f"<div class='panel'><b>Mastered: {p['mastered']} of {plural(p['total'], 'card')}</b>"
                  f"<div class='track'><div class='fill' style='width:{pct}%'></div></div></div>"
                  f"<h3>Last 5 weeks (darker = more cards)</h3><div class='heat'>{cells}</div>"
                  f"<h3>Terms to practice</h3>{weak or '<p class=muted>Nothing missed yet. Nice.</p>'}",
                  "", "progress")

def opts(name, choices, cur):
    o = "".join(f"<option value='{v}'{' selected' if v == cur else ''}>{e(l)}</option>" for v, l in choices)
    return f"<select name='{name}'>{o}</select>"

def settings_page(msg=""):
    body = ("<h2>Settings</h2><form method='post' action='/settings' class='panel stack'>"
            "<label>Theme" + opts("theme", THEMES, db.setting("theme", "cream")) + "</label>"
            "<label>Text size" + opts("size", [("s", "Small"), ("m", "Normal"), ("l", "Large")], db.setting("size", "m")) + "</label>"
            "<label>Daily goal (cards)" + opts("goal", [(g, g) for g in (10, 20, 30, 50)], db.setting("goal", "20")) + "</label>"
            "<button>Save</button></form>"
            f"<div class='panel stack'><div class='muted'>Signed in as <b>{e(auth.username(db.uid()))}</b></div>"
            "<form method='post' action='/logout'><button class='ghost'>Log out</button></form>"
            "<a class='btn ghost' href='/account'>Delete account</a></div>")
    return layout(body, msg, "settings")

def summary_page(s):
    if not s["n"]:
        return layout("<h2>Session</h2><div class='panel'>No cards answered yet.</div>"
                      "<a class='btn' href='/now'>Start studying</a>", "", "study")
    pct = s["ok"] * 100 // s["n"]
    note = "Great work!" if pct >= 80 else "Good progress." if pct >= 50 else "Keep going, it gets easier."
    miss = "".join(f"<span class='badge'>{e(m)}</span>" for m in s["miss"])
    return layout(f"<h2>Session complete</h2><div class='panel'><div class='level'>{s['ok']} / {s['n']} correct</div>"
                  f"<div class='track'><div class='fill' style='width:{pct}%'></div></div>"
                  f"<div class='muted'>{pct}% accuracy | +{s['xp']} XP. {note}</div></div>"
                  f"<h3>Terms to review</h3><div>{miss or '<span class=muted>None. Perfect run.</span>'}</div>"
                  "<a class='btn' href='/now' style='margin-top:16px'>Study again</a>"
                  "<a class='btn ghost' href='/' style='margin-top:8px'>Home</a>", "", "study")

def confirm_page(did):
    d, items = db.get_deck(did)
    if not d:
        return layout("<p class='muted'>Reviewer not found.</p>")
    return layout(f"<h2>Delete this reviewer?</h2><div class='panel'><b>{e(d[1])}</b>"
                  f"<div class='muted'>This removes {plural(len(items), 'card')} and can't be undone.</div></div>"
                  f"<form method='post' action='/delete'><input type='hidden' name='d' value='{did}'>"
                  "<button class='danger'>Yes, delete it</button></form>"
                  f"<a class='btn ghost' href='/deck?id={did}&m=review' style='margin-top:8px'>Cancel</a>", "", "study")

def edit_page(item):
    return layout(f"<h2>Edit card</h2><form method='post' action='/edit' class='stack'>"
                  f"<input type='hidden' name='i' value='{item[0]}'><input type='hidden' name='d' value='{item[1]}'>"
                  f"<label>Answer (term)<input name='term' value='{e(item[2])}' required maxlength='80'></label>"
                  f"<label>Clue<textarea name='clue' rows='6' required>{e(item[3])}</textarea></label>"
                  "<div class='muted'>Write _____ where the answer goes.</div><button>Save changes</button></form>"
                  f"<form method='post' action='/rmcard' style='margin-top:12px'>"
                  f"<input type='hidden' name='i' value='{item[0]}'><input type='hidden' name='d' value='{item[1]}'>"
                  f"<button class='danger'>Remove this card</button></form>"
                  f"<a class='btn ghost' href='/deck?id={item[1]}&m=review' style='margin-top:8px'>Back</a>", "", "study")

def preview_page(token, p):
    items = p["items"]
    nd = sum(1 for i in items if i["kind"] == "definition")
    picks = "".join(f"<label class='pick'><input type='checkbox' name='k' value='{n}' checked>"
                    f"<span><b>{e(i['term'])}</b><br><small>{e(i['clue'][:140])}</small></span></label>"
                    for n, i in enumerate(items))
    dopts = "<option value=''>New reviewer</option>" + "".join(
        f"<option value='{d[0]}'>Add to: {e(d[1])}</option>" for d in db.list_decks())
    return layout(f"<h2>Review before saving</h2><div class='panel'>Found <b>{nd}</b> definitions, "
                  f"<b>{len(items) - nd}</b> fill-in cards and <b>{len(p['keywords'])}</b> keywords. "
                  "Untick any cards you don't want.</div>"
                  f"<form method='post' action='/create'><input type='hidden' name='t' value='{token}'>"
                  f"<label>Name<input name='name' value='{e(p['name'])}' maxlength='60'></label>"
                  f"<label>Save to<select name='target'>{dopts}</select></label>"
                  f"<h3>Cards</h3>{picks}<button style='margin-top:12px'>Create reviewer</button></form>", "", "home")

def deck_page(did, mode, msg="", q="", f="all", fb=None, cover=False):
    d, items = db.get_deck(did)
    if not d:
        return layout("<p class='muted'>Reviewer not found.</p>", msg, "study")
    mode, body = modes.deck_body(did, mode, d, items, q, f, fb, db.status()["combo"], cover)
    foot = (f"<div class='foot'><a class='btn ghost small' href='/summary'>Finish session</a>"
            f"<a class='btn ghost small' href='/confirm?d={did}'>Delete reviewer</a></div>")
    return layout(f"<h2>{e(d[1])}</h2>" + modes.tabs(did, mode) + body + foot, msg, "study")


def auth_page(kind, err="", name="", code_needed=False):
    login = kind == "login"
    page = (f"<!doctype html><html class='cream m'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<meta name='theme-color' content='#F4EAD5'>"
            "<title>StudyQuest</title><link rel='stylesheet' href='/style.css'></head><body>"
            "<div class='bar'><span class='brand'>StudyQuest</span></div>")
    if err:
        page += f"<div class='pop err'>{e(err)}</div>"
    code = "<label>Invite code<input name='code' autocomplete='off' required></label>" if code_needed and not login else ""
    page += (f"<h2>{'Log in' if login else 'Create account'}</h2>"
             f"<form method='post' action='/{kind}' class='panel stack'>"
             f"<label>Username<input name='name' value='{e(name)}' maxlength='30' required autocapitalize='none' "
             "autocomplete='username'></label>"
             f"<label>Password<input type='password' name='pw' maxlength='200' required "
             f"autocomplete='{'current-password' if login else 'new-password'}'></label>"
             + ("" if login else "<div class='muted'>At least 8 characters.</div>") + code +
             f"<button>{'Log in' if login else 'Sign up'}</button></form>"
             + ("<a class='btn ghost' href='/signup'>Create an account</a>" if login
                else "<a class='btn ghost' href='/login'>I already have an account</a>")
             + "</body></html>")
    return page

def account_page(msg=""):
    return layout("<h2>Delete account</h2><div class='panel'><b>This permanently deletes your login, all reviewers, "
                  "cards and progress.</b><div class='muted'>It can't be undone.</div></div>"
                  "<form method='post' action='/account/delete' class='stack'>"
                  "<label>Enter your password to confirm<input type='password' name='pw' required "
                  "autocomplete='current-password'></label><button class='danger'>Delete my account</button></form>"
                  "<a class='btn ghost' href='/settings' style='margin-top:8px'>Cancel</a>", msg, "settings")
