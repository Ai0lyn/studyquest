import difflib, html, math, random, re
from datetime import date
from urllib.parse import quote
import db

def e(s):
    return html.escape(str(s))

def plural(n, w):
    return f"{n} {w}" + ("" if n == 1 else "s")

def when(day):
    d = (date.fromisoformat(day) - date.today()).days
    return "tomorrow" if d <= 1 else f"in {d} days"

def body_text(i):
    t = re.sub(r"^(?:(?:the|an?)\s+)?_____\s*(?::|[-–—]|(?:is defined as|is known as|is called|refers to|means|is|are)\b)\s*",
               "", i[2], flags=re.I)
    t = e(t).replace("_____", "<b>" + e(i[1]) + "</b>")
    return t[:1].upper() + t[1:]

def dots(box):
    return "".join("<i class='dot on'></i>" if n < box else "<i class='dot'></i>" for n in range(5))

def tabs(did, mode):
    names = [("review", "Reviewer"), ("flash", "Flashcards"), ("quiz", "Quiz"), ("ident", "Identify")]
    t = ""
    for k, n in names:
        on = " on" if k == mode else ""
        t += f"<a class='tab{on}' href='/deck?id={did}&m={k}'>{n}</a>"
    return "<div class='tabs'>" + t + "</div>"

def hidden(did, iid, mode):
    return (f"<input type='hidden' name='d' value='{did}'><input type='hidden' name='i' value='{iid}'>"
            f"<input type='hidden' name='m' value='{mode}'>")

def link(did, mode, f="all", q="", cover=False):
    return f"/deck?id={did}&m={mode}&f={f}&q={quote(q)}" + ("&c=1" if cover else "")

# ---- smarter quiz choices: wrong answers that look and sound like the right one
STOP = set("the an and or to in is are was were be by for with on as at from that this which it its their his her "
           "has have had not can into than then also such".split())

def words(s):
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2 and w not in STOP}

def overlap(a, b):
    return len(a & b) / max(1, len(a | b))

def closeness(a, b):
    """How tempting card b's term is as a wrong answer for card a (higher = more tempting)."""
    ta, tb = a[1].lower(), b[1].lower()
    score = difflib.SequenceMatcher(None, ta, tb).ratio()            # similar spelling
    score += 0.5 * overlap(words(a[1]), words(b[1]))                 # shares words with the term
    score += 1.0 * overlap(words(a[2]), words(b[2]))                 # talks about the same topic
    score += 0.2 if a[3] == b[3] else 0                              # same kind of card
    score -= 0.1 * abs(len(ta.split()) - len(tb.split())) + 0.002 * abs(len(ta) - len(tb))  # similar length
    return score

def shown_as(t):
    """Same capital-letter style on every option, so the answer can't be spotted by its casing (display only)."""
    return t[0].upper() + t[1:] if t[:1].islower() and t[1:] == t[1:].lower() else t

def distractors(i, items, k=3):
    ta = i[1].lower()
    seen, cands = {ta}, []
    for x in items:
        tx = x[1].lower()
        if tx in seen:
            continue
        seen.add(tx)
        # skip singular/plural twins: they would make two answers look right
        if tx.rstrip("s") == ta.rstrip("s") or difflib.SequenceMatcher(None, ta, tx).ratio() >= 0.92:
            continue
        cands.append((closeness(i, x), x[1]))
    cands.sort(key=lambda c: -c[0])
    cands, picks = cands[:12], []
    for _ in range(min(k, len(cands))):      # weighted draw: look-alikes are far more likely, but not guaranteed
        n = random.choices(range(len(cands)), weights=[math.exp(3 * sc) for sc, _ in cands])[0]
        picks.append(cands.pop(n)[1])
    return picks

def feedback(fb):
    if not fb:
        return ""
    head = f"Correct! +{fb['xp']} XP" if fb["ok"] else "Not quite"
    return (f"<div class='fb {'good' if fb['ok'] else 'bad'}'><b>{head}</b>"
            f"<div>Answer: <b>{e(fb['term'])}</b></div><p>{fb['text']}</p></div>")

def orig_text(i):
    return e(i[2]).replace("_____", "<b>" + e(i[1]) + "</b>")

def reviewer(did, d, items, q, f, cover=False):
    n = len(items)
    mastery = int(sum(i[4] for i in items) * 100 / (5 * n)) if n else 0
    if f == "def":
        shown = [i for i in items if i[3] == "definition"]
    elif f == "cloze":
        shown = [i for i in items if i[3] != "definition"]
    else:
        shown = items
    if q:
        shown = [i for i in shown if q.lower() in i[1].lower() or q.lower() in i[2].lower()]
    key_ids = {i[0] for i in items[:10] if i[3] == "definition"}
    kw = "".join(f"<span class='badge'>{e(k)}</span>" for k in d[2].split("|") if k)
    facts = "".join(f"<li>{e(s)}</li>" for s in d[3].split("\n") if s)
    chips = ""
    for k, label in (("all", "All"), ("def", "Definitions"), ("cloze", "Fill-in")):
        on = " on" if f == k else ""
        chips += f"<a class='chip{on}' href='{link(did, 'review', k, q, cover)}'>{label}</a>"
    toggle = (f"<a class='btn ghost small' href='{link(did, 'review', f, q, False)}'>Show meanings</a>" if cover else
              f"<a class='btn ghost small' href='{link(did, 'review', f, q, True)}'>Cover meanings</a>")
    rows = ""
    for k, i in enumerate(shown[:60]):
        tag = "<span class='key'>Key</span>" if i[0] in key_ids else ""
        mean = f"<p class='mean'>{body_text(i)}</p>"
        if cover:
            mean = f"<details class='cov'><summary>Tap to reveal meaning</summary>{mean}</details>"
        rows += (f"<div class='tc t{k % 4}'><div class='th'><b>{e(i[1])}</b>"
                 f"<div class='meta'><span class='dots'>{dots(i[4])}</span>{tag}</div></div>{mean}"
                 f"<details class='orig'><summary>Original text</summary><p>{orig_text(i)}</p>"
                 f"<a class='edit' href='/edit?i={i[0]}'>Edit or remove</a></details></div>")
    if not shown:
        rows = "<p class='muted'>No matches.</p>"
    more = f"<p class='muted'>Showing 60 of {len(shown)}. Use search to narrow down.</p>" if len(shown) > 60 else ""
    return (f"<div class='hero'><span class='pill'>{plural(n, 'term')} ready to study</span></div>"
            f"<div class='panel'><div class='row'><b>Mastery</b><span class='muted'>{mastery}%</span></div>"
            f"<div class='track'><div class='fill' style='width:{mastery}%'></div></div></div>"
            f"<h3>Keywords</h3><div>{kw}</div>"
            f"<details class='panel'><summary>Key facts</summary><ul>{facts or '<li>None found</li>'}</ul></details>"
            f"<details class='notes' open><summary>Your notes · {plural(len(shown), 'term')}</summary>"
            f"<div class='paper'><div class='sbar'><form method='get' action='/deck'>"
            f"<input type='hidden' name='id' value='{did}'><input type='hidden' name='m' value='review'>"
            f"<input type='hidden' name='f' value='{f}'>" + ("<input type='hidden' name='c' value='1'>" if cover else "") +
            f"<input name='q' value='{e(q)}' placeholder='Search terms'></form>{toggle}</div>"
            f"<div class='chips'>{chips}</div>"
            "<p class='muted'>Key = appears often in your notes. Dots = how well you know it.</p>"
            f"{rows}{more}</div></details>")

def ans_form(did, iid, ok, label, cls=""):
    return (f"<form method='post' action='/answer'>{hidden(did, iid, 'flash')}"
            f"<input type='hidden' name='ok' value='{ok}'><button class='{cls}'>{label}</button></form>")

def flash(did, items, due):
    if not due:
        today = date.today().isoformat()
        nxt = min((i[5] for i in items if i[5] > today), default=None)
        sub = f"Next review: {when(nxt)}." if nxt else "Try the Quiz or add more notes."
        return f"<div class='panel'><b>All caught up!</b><div class='muted'>{sub}</div></div>"
    i = due[0]
    return (f"<div class='muted'>{len(due)} due of {len(items)}</div>"
            f"<div class='card big'><div class='label'>Definition</div><p>{e(i[2])}</p></div>"
            "<details class='reveal'><summary>Tap to reveal answer</summary>"
            f"<div class='ans'>{e(i[1])}</div><div class='row2'>"
            f"{ans_form(did, i[0], 1, 'Got it')}{ans_form(did, i[0], 0, 'Missed it', 'ghost')}</div></details>")

def quiz(did, items, fb, combo):
    if len(items) < 2:
        return "<p class='muted'>You need at least 2 cards for a quiz.</p>"
    i = random.choice(items)
    opts = distractors(i, items) + [i[1]]
    random.shuffle(opts)
    btns = "".join(f"<form method='post' action='/answer'>{hidden(did, i[0], 'quiz')}"
                   f"<button name='c' value='{e(o)}' class='opt'>{e(shown_as(o))}</button></form>" for o in opts)
    return (feedback(fb) + f"<div class='muted'>Combo x{combo}</div>"
            f"<div class='card big'><div class='label'>Which term fits?</div><p>{e(i[2])}</p></div>{btns}")

def ident(did, items, due, fb, combo):
    cards = due or items
    if not cards:
        return "<p class='muted'>No cards yet.</p>"
    i = random.choice(cards)
    n = len(i[1].split())
    hint = f"Hint: {plural(n, 'word')}, starts with {e(i[1][0])}"
    return (feedback(fb) + f"<div class='muted'>Combo x{combo}</div>"
            f"<div class='card big'><div class='label'>Type the answer</div><p>{e(i[2])}</p></div>"
            f"<div class='muted'>{hint}</div>"
            f"<form method='post' action='/answer' class='add'>{hidden(did, i[0], 'ident')}"
            "<input name='t' placeholder='Your answer' required autocomplete='off' autofocus><button>Check</button></form>")

def deck_body(did, mode, d, items, q, f, fb, combo, cover=False):
    today = date.today().isoformat()
    due = sorted([i for i in items if i[5] <= today], key=lambda i: (i[4], i[0]))
    if mode == "review":
        return mode, reviewer(did, d, items, q, f, cover)
    if mode == "quiz":
        return mode, quiz(did, items, fb, combo)
    if mode == "ident":
        return mode, ident(did, items, due, fb, combo)
    return "flash", flash(did, items, due)
