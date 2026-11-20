import html, re
from urllib.parse import quote

def e(s):
    return html.escape(str(s))

def body_text(i):
    t = re.sub(r"^(?:(?:the|an?)\s+)?_____\s*(?::|[-–—]|(?:is defined as|is known as|is called|refers to|means|is|are)\b)\s*",
               "", i[2], flags=re.I)
    t = e(t).replace("_____", "<b>" + e(i[1]) + "</b>")
    return t[:1].upper() + t[1:]

def dots(box):
    return "".join("<i class='dot on'></i>" if n < box else "<i class='dot'></i>" for n in range(5))

def reviewer(did, d, items, q="", f="all"):
    n = len(items)
    mastery = int(sum(i[4] for i in items) * 100 / (5 * n)) if n else 0
    if f == "def":
        shown = [i for i in items if i[3] == "definition"]
    elif f == "cloze":
        shown = [i for i in items if i[3] != "definition"]
    else:
        shown = items
    if q:
        ql = q.lower()
        shown = [i for i in shown if ql in i[1].lower() or ql in i[2].lower()]
    key_ids = {i[0] for i in items[:10] if i[3] == "definition"}
    kw = "".join(f"<span class='badge'>{e(k)}</span>" for k in d[2].split("|") if k)
    facts = "".join(f"<li>{e(s)}</li>" for s in d[3].split("\n") if s)
    chips = ""
    for k, label in (("all", "All"), ("def", "Definitions"), ("cloze", "Fill-in")):
        on = " on" if f == k else ""
        chips += f"<a class='chip{on}' href='/deck?id={did}&m=review&f={k}&q={quote(q)}'>{label}</a>"
    rows = ""
    for i in shown[:60]:
        tag = "<span class='key'>Key</span>" if i[0] in key_ids else ""
        rows += (f"<details class='term'><summary><span>{e(i[1])}{tag}</span>"
                 f"<span class='dots'>{dots(i[4])}</span></summary><p>{body_text(i)}</p></details>")
    if not shown:
        rows = "<p class='muted'>No matches.</p>"
    more = f"<p class='muted'>Showing 60 of {len(shown)}. Use search to narrow down.</p>" if len(shown) > 60 else ""
    return (f"<div class='panel'><div class='row'><b>{n} terms</b><span class='muted'>Mastery {mastery}%</span></div>"
            f"<div class='track'><div class='fill' style='width:{mastery}%'></div></div></div>"
            f"<h3>Keywords</h3><div>{kw}</div>"
            f"<details class='panel'><summary>Key facts</summary><ul>{facts or '<li>None found</li>'}</ul></details>"
            f"<form method='get' action='/deck' class='add'><input type='hidden' name='id' value='{did}'>"
            f"<input type='hidden' name='m' value='review'><input type='hidden' name='f' value='{f}'>"
            f"<input name='q' value='{e(q)}' placeholder='Search terms'><button>Go</button></form>"
            f"<div class='chips'>{chips}</div>{rows}{more}")
