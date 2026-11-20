import re
import extract

JUNK = re.compile(r"^(?:(?:chapter|section|unit|module|part|lesson|week|day|figure|fig|table|page|appendix)"
                  r"\s+(?:\d+|[ivxlc]+)\b|exam\b|objectives?\b|outline\b|contents\b|agenda\b|"
                  r"references?\b|table of contents)", re.I)
CHOICES = re.compile(r"\bA[.)]\s.*\bB[.)]\s")
QUESTION = re.compile(r"^(?:which|what|how|why|who|when|where|find|identify|choose|select|solve|compute|"
                      r"true or false)\b|\?", re.I)

def count(term, text):
    return len(re.findall(re.escape(term), text, re.I))

def clean(items, text):
    out, seen = [], set()
    for it in items:
        t = it["term"].strip()
        k = t.lower()
        body = it["clue"].replace("_____", " ")
        if k in seen or JUNK.match(t) or t.replace(" ", "").isdigit():
            continue
        if "\ufffd" in t + it["clue"] or extract.garbled(t + " " + it["clue"]):
            continue
        if QUESTION.search(t) or CHOICES.search(it["clue"]) or "→" in it["clue"]:
            continue
        if len(body.split()) < 6:
            continue
        seen.add(k)
        it["n"] = count(t, text)
        out.append(it)
    out.sort(key=lambda x: (x["kind"] != "definition", -x["n"]))
    return out
