import io, os, re, html, shutil, subprocess, tempfile, zipfile, collections, unicodedata

STOP = set("""the a an and or of to in on at for with by from is are was were be been it its this
that these those as but not can will would may has have had which who whom into than then also
such their there they them he she you we our your i more most some any each other about over
under after before while when where what how why do does did so if only very just""".split())
GENERIC = {"game", "app", "application"}
BADWORDS = {"and", "or", "began", "which", "that", "who", "because", "when", "has", "have", "had", "can", "will", "also"}
PRON = r"(?:it|this|that|they|these|those)"
SIGNAL = re.compile(r"\b(important|key|main|must|major|first|primary|essential|known as|"
                    r"defined|released|founded|established|\d{3,4})\b", re.I)

class ReadError(Exception):
    """A problem with the uploaded file that we can explain to the person."""

MAX_CHARS = 300_000   # keeps big uploads from hogging a small server
MAX_PAGES = 250
TEXT_EXT = (".txt", ".md", ".markdown", ".text", ".csv")
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff")
MAX_UNZIPPED = 30 * 1024 * 1024   # zip-bomb guard for .docx / .pptx / .odt / .odp
OCR_LANG = os.environ.get("OCR_LANG", "eng")
OCR_PDF_PAGES = 12
SUPPORTED = "PDF, Word (.docx), PowerPoint (.pptx), a photo or screenshot, or a text file"
NICE = set("\u2019\u2018\u201c\u201d\u2013\u2014\u2026\u2022\u00b0")   # curly quotes, dashes, bullets
SYMS = set("#$&*+<=>@[\\]^_`{|}~")

def garbled(text):
    """True when text is junk: a PDF font the reader can't decode, a binary file saved as text, etc."""
    t = re.sub(r"\s+", " ", text).strip()
    n = len(t)
    if n < 30:
        return False
    if t.count("\ufffd") / n > 0.005:
        return True
    if sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\r\t\x0c") / len(text) > 0.01:   # binary junk
        return True
    weird = sum(1 for ch in t if not (ch.isascii() or ch in NICE or "LATIN" in unicodedata.name(ch, "")))
    if weird / n > 0.04:
        return True
    toks = [w for w in t.split() if len(w) >= 3]
    if len(toks) < 8:
        return False
    plain = sum(1 for w in toks if re.sub(r"['\u2019-]", "", w.strip(".,;:!?()[]\"'\u201c\u201d\u2018\u2019")).isalpha())
    odd = sum(1 for w in toks if re.search(r"[a-z][A-Z]|[A-Za-z]\d|\d[A-Za-z]", w) or any(c in SYMS for c in w))
    return odd / len(toks) > 0.4 and plain / len(toks) < 0.4

def pdftotext(data):
    exe = shutil.which("pdftotext")   # optional extra reader (Termux: pkg install poppler)
    if not exe:
        return ""
    try:
        r = subprocess.run([exe, "-enc", "UTF-8", "-", "-"], input=data, capture_output=True, timeout=30)
        return r.stdout.decode("utf8", "ignore") if r.returncode == 0 else ""
    except Exception:
        return ""

def zread(z, name):
    """Read one member of a zip as text, refusing absurdly large ones."""
    with z.open(name) as f:
        raw = f.read(MAX_UNZIPPED + 1)
    if len(raw) > MAX_UNZIPPED:
        raise ReadError("That file is too large to read safely.")
    return raw.decode("utf8", "ignore")

def xml_text(x, para_end, breaks=()):
    for b in breaks:
        x = re.sub(b, " ", x)
    x = re.sub(para_end, "\n", x)
    return html.unescape(re.sub(r"<[^>]+>", "", x))

def open_zip(data, what):
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ReadError(f"Couldn't read that {what} file. It may be damaged or in an old format.")

def read_docx(data):
    z = open_zip(data, "Word")
    try:
        x = zread(z, "word/document.xml")
    except KeyError:
        raise ReadError("Couldn't read that Word file. Save it as .docx (not .doc) and try again.")
    return xml_text(x, r"</w:p>", (r"<w:tab/>", r"<w:br/>"))

def read_pptx(data):
    z = open_zip(data, "PowerPoint")
    names = z.namelist()
    def num(n):
        return int(re.search(r"(\d+)\.xml$", n).group(1))
    slides = sorted((n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=num)
    if not slides:
        raise ReadError("Couldn't read that PowerPoint file. Save it as .pptx (not .ppt) and try again.")
    notes = {num(n): n for n in names if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", n)}
    out = []
    for n in slides[:MAX_PAGES]:
        lines = [l for l in xml_text(zread(z, n), r"</a:p>", (r"<a:br\s*/>",)).split("\n") if l.strip()]
        out.append("\n".join(lines))
        if num(n) in notes:   # speaker notes often hold the real explanation
            nl = [l for l in xml_text(zread(z, notes[num(n)]), r"</a:p>", (r"<a:br\s*/>",)).split("\n")
                  if l.strip() and not l.strip().isdigit()]
            out.append("\n".join(nl))
    return "\n\n".join(t for t in out if t.strip())

def read_odf(data, what):
    z = open_zip(data, what)
    try:
        x = zread(z, "content.xml")
    except KeyError:
        raise ReadError(f"Couldn't read that {what} file.")
    return xml_text(x, r"</text:(?:p|h)>", (r"<text:line-break/>", r"<text:tab/>"))

def reflow(text):
    """OCR breaks lines at the page edge. Join wrapped lines back into sentences, keep bullets and headings."""
    bullet = re.compile(r"^(?:[-*\u2022\u00b7>]\s|\d+[.)]\s|[A-Za-z][.)]\s)")
    out, cur = [], ""
    for para in re.split(r"\n\s*\n", text):
        first = True
        for line in (l.strip() for l in para.split("\n")):
            if not line:
                continue
            wrapped = cur and not bullet.match(line) and not cur.endswith((":", ".", "?", "!")) \
                and (not first or line[0].islower())   # across a blank line, only join when it clearly continues
            if wrapped:
                cur += " " + line
            else:
                if cur:
                    out.append(cur)
                cur = line
            first = False
    if cur:
        out.append(cur)
    return "\n".join(out)

def tesseract(path):
    exe = shutil.which("tesseract")
    r = subprocess.run([exe, path, "stdout", "-l", OCR_LANG], capture_output=True, timeout=90)
    return r.stdout.decode("utf8", "ignore") if r.returncode == 0 else ""

def prep_image(data):
    """Grayscale / upright / bigger-if-small makes OCR much better. Pillow is optional."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return data
    try:
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        im = ImageOps.autocontrast(im.convert("L"))
        side = max(im.size)
        if side < 1500:
            k = 1500 / side
            im = im.resize((int(im.width * k), int(im.height * k)))
        elif side > 3600:
            k = 3600 / side
            im = im.resize((int(im.width * k), int(im.height * k)))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return buf.getvalue()
    except Exception:
        raise ReadError("Couldn't open that image. Try a JPG or PNG.")

def read_image(data):
    if not shutil.which("tesseract"):
        raise ReadError("Reading text from pictures needs the OCR tool, which isn't installed on this server "
                        "(Termux: pkg install tesseract). You can paste the text instead.")
    img = prep_image(data)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "in.png" if img is not data else "in.img")
        with open(p, "wb") as f:
            f.write(img)
        try:
            text = tesseract(p)
        except Exception:
            raise ReadError("Reading that picture took too long or failed. Try a clearer, smaller photo.")
    if len(text.strip()) < 20:
        raise ReadError("I couldn't find readable text in that picture. Try a sharper, well-lit photo of the page.")
    if garbled(text):
        raise ReadError("The text in that picture came out garbled. Try a sharper, straight-on photo.")
    return reflow(text)

def ocr_pdf(data):
    """Last resort for scanned PDFs: needs pdftoppm (poppler) and tesseract."""
    if not (shutil.which("pdftoppm") and shutil.which("tesseract")):
        return ""
    try:
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "in.pdf")
            with open(src, "wb") as f:
                f.write(data)
            subprocess.run(["pdftoppm", "-r", "150", "-l", str(OCR_PDF_PAGES), "-png", src, os.path.join(d, "p")],
                           capture_output=True, timeout=90)
            pages = sorted(x for x in os.listdir(d) if x.startswith("p") and x.endswith(".png"))
            text = "\n\n".join(tesseract(os.path.join(d, x)) for x in pages)
        return reflow(text)
    except Exception:
        return ""

def read_pdf(data):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ReadError("PDF reading isn't installed on this server (pip install pypdf). You can paste the text instead.")
    try:
        r = PdfReader(io.BytesIO(data))
        if r.is_encrypted:
            r.decrypt("")
        pages = [(p.extract_text() or "") for p in r.pages[:MAX_PAGES]]
    except Exception:
        raise ReadError("Couldn't open that PDF. It may be damaged or password-protected.")
    good = [t for t in pages if t.strip() and not garbled(t)]
    if good:
        return "\n".join(good)
    alt = pdftotext(data)
    if alt.strip() and not garbled(alt):
        return alt
    if any(t.strip() for t in pages):
        raise ReadError("That PDF's text can't be read: it uses a font encoding the reader can't decode (common with "
                        "PDFs exported from some slide and design apps). Open it, copy the text and paste it into the "
                        "box, or save the file as Word (.docx) and upload that.")
    scan = ocr_pdf(data)
    if scan.strip() and not garbled(scan):
        return scan
    raise ReadError("That PDF has no selectable text (it looks like a scan or pictures). Upload it as photos/screenshots "
                    "instead, or paste the text.")

def read_file(name, data):
    n = name.lower()
    if n.endswith(".pdf"):
        text = read_pdf(data)
    elif n.endswith(".docx"):
        text = read_docx(data)
    elif n.endswith(".pptx"):
        text = read_pptx(data)
    elif n.endswith(".odt"):
        text = read_odf(data, "OpenDocument")
    elif n.endswith(".odp"):
        text = read_odf(data, "OpenDocument")
    elif n.endswith(IMG_EXT):
        text = read_image(data)
    elif n.endswith((".heic", ".heif")):
        raise ReadError("HEIC photos aren't supported. Take a screenshot of the photo or share it as JPG/PNG.")
    elif n.endswith((".ppt", ".doc")):
        raise ReadError("Old .ppt / .doc files can't be read. Re-save as .pptx / .docx and upload again.")
    else:
        if not n.endswith(TEXT_EXT) and b"\x00" in data[:2048]:
            raise ReadError(f"That file type isn't supported. Use a {SUPPORTED}, or paste your notes.")
        text = data.decode("utf-8-sig", "ignore")
        if garbled(text):
            raise ReadError(f"That file doesn't look like readable text. Use a {SUPPORTED}.")
    if not text.strip():
        raise ReadError("I couldn't find any text in that file.")
    return text[:MAX_CHARS]

def sentences(text):
    out = []
    for para in re.split(r"\n+", text):
        para = re.sub(r"\s+", " ", para).strip()
        if para:
            out += re.split(r"(?<=[.!?])\s+(?=[A-Z\"“(])", para)
    return [s.strip() for s in out if len(s.strip()) > 3]

def clean_term(t):
    t = re.sub(r"^(the|a|an)\s+", "", t.strip(" \"'“”*-•"), flags=re.I)
    w = t.split()
    if w and w[-1].lower() in GENERIC and len(w) > 1:
        t = " ".join(w[:-1])
        w = t.split()
    if not (1 <= len(w) <= 8) or len(t) < 3 or w[0].lower() in STOP:
        return None
    if any(x.lower() in BADWORDS for x in w):
        return None
    return t

DEF = re.compile(r"^(?P<t>[^,;:.]{2,60}?)\s+(?:is defined as|is known as|is called|refers to|"
                 r"means|will be|is|are|was|were)\s+\S", re.I)
COLON = re.compile(r"^(?P<t>[^:]{2,50}?)\s*(?::|\s[-–—]\s)\s*\S.{12,}$")

def blank(s, term):
    return re.sub(re.escape(term) + r"(\s+(?:game|app|application)\b)?", "_____", s, flags=re.I)

def analyze(text):
    sents = sentences(text)
    facts, order, used = {}, [], set()
    last = None
    for i, s in enumerate(sents):
        if re.match(r"^" + PRON + r"\b", s, re.I):
            if last:
                facts[last].append(s)
                used.add(i)
            continue
        m = DEF.match(s) or COLON.match(s)
        term = clean_term(m.group("t")) if m else None
        if term:
            k = term.lower()
            if k not in facts:
                facts[k] = []
                order.append((k, term))
            facts[k].append(s)
            used.add(i)
            last = k
        else:
            last = None
    items = []
    for k, term in order:
        clue = " ".join(blank(s, term) for s in facts[k])
        if len(clue) > 20:
            items.append({"term": term, "clue": clue, "kind": "definition"})
    words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'-]{3,}", text)]
    freq = collections.Counter(w for w in words if w not in STOP)
    keywords = [w for w, _ in freq.most_common(15)]
    have = {x["term"].lower() for x in items}
    key_sents = []
    for i, s in enumerate(sents):
        if i in used or len(s) < 40 or not SIGNAL.search(s):
            continue
        key_sents.append(s)
        cands = [w for w in re.findall(r"[A-Za-z][A-Za-z'-]{3,}", s)
                 if w.lower() in freq and w.lower() not in have]
        if cands:
            w = max(cands, key=lambda c: freq[c.lower()])
            have.add(w.lower())
            items.append({"term": w, "clue": re.sub(r"\b" + re.escape(w) + r"\b", "_____", s, count=1, flags=re.I), "kind": "cloze"})
    for s in sents:
        if len(s) > 40 and s not in key_sents and len(key_sents) < 10 and SIGNAL.search(s):
            key_sents.append(s)
    return {"items": items, "keywords": keywords, "key_sentences": key_sents[:15]}
