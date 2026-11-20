# StudyQuest

Notes in, flashcards/quizzes out. Python + Lua + CSS + shell, standard library only
(`pypdf` is optional, for PDF uploads; `tesseract` is optional, for reading photos).

Accounts: sign up / log in, every user has their own reviewers, cards, XP and settings.
If you are upgrading from the old single-user version, the **first account created
adopts the old data**.

## What's inside

- **Study modes:** Reviewer, Flashcards, Quiz (wrong options are look-alike terms, not random ones), Identify.
- **Themes (Settings):** Cream & Green (default, 60% butter cream / 30% forest green / 10% honey gold), Dark and Light.
  All three share the same layout and the forest-green / gold accents.
- **Progress feel:** a level-up banner (pure CSS animation) and a streak flame on the top bar.
- Works without Lua too: if `lua` isn't installed the same scoring/level rules run in Python.

## Uploading notes

Up to 5 files at once (20 MB total), or pasted text:

| Type | Needs |
|---|---|
| Word `.docx`, PowerPoint `.pptx` (slide text + speaker notes), OpenDocument `.odt` / `.odp`, `.txt` / `.md` / `.csv` | nothing extra |
| PDF | `pip install pypdf` |
| Photos and screenshots (`.jpg .png .webp .bmp .gif .tif`) | the `tesseract` OCR program |
| Scanned PDFs | `tesseract` + `pdftoppm` (poppler); first 12 pages |

Old `.ppt` / `.doc` and iPhone `.heic` aren't readable: re-save as `.pptx` / `.docx`, or share the photo as JPG/PNG.
Optional: `pip install pillow` straightens, greys and enlarges photos before OCR (better accuracy). Set `OCR_LANG`
(default `eng`) for other languages.

Install OCR: Termux `pkg install tesseract poppler`; Ubuntu/VPS `sudo apt install tesseract-ocr poppler-utils`.
PythonAnywhere may not offer tesseract. If it isn't there, the app says so and people can paste text instead.
Some PDFs (certain slide/design exports) have no readable text layer; the app says so instead of making junk cards.

## Run locally (or on Termux)

    python3 app.py            # http://localhost:8000   (Termux: ./run.sh)

## Put it on GitHub

1. On github.com: **New repository**, name it `studyquest`, leave it empty (no README), and note your **username**.
2. In the project folder (Termux: `cd ~/studyquest`), tell git who you are once:

       git config --global user.name "Your Name"
       git config --global user.email "you@example.com"

3. Commit **first**, then push (replace `USERNAME` with your real GitHub username):

       git init
       git add .
       git commit -m "StudyQuest"
       git branch -M main
       git remote add origin https://github.com/USERNAME/studyquest.git
       git push -u origin main

   Typing the commit message on one line with both quotes closed matters: a missing closing `"` makes the shell wait.
   If `origin` already exists with a wrong address: `git remote set-url origin https://github.com/USERNAME/studyquest.git`.
4. When git asks for a password, paste a **personal access token** (GitHub > Settings > Developer settings >
   Personal access tokens, with permission to write repository contents). Your account password won't work.

`*.db` is in `.gitignore`, so user data never goes to GitHub. To update later: `git add . && git commit -m "update" && git push`.

## Free hosting on PythonAnywhere

1. Make a free "Beginner" account at pythonanywhere.com.
2. **Consoles > Bash**:

       git clone https://github.com/YOU/studyquest.git
       mkdir studyquest-data
       pip install --user pypdf        # optional (PDF uploads)

3. **Web > Add a new web app > Manual configuration** > pick Python 3.x.
4. Open the **WSGI configuration file** and replace everything with
   (swap `YOURUSER`):

       import sys, os
       path = "/home/YOURUSER/studyquest"
       if path not in sys.path:
           sys.path.insert(0, path)
       os.environ["TRUST_PROXY"] = "1"
       os.environ["STUDYQUEST_DB"] = "/home/YOURUSER/studyquest-data/studyquest.db"
       # os.environ["SIGNUP_CODE"] = "choose-a-code"   # optional: invite-only sign-up
       from app import application

5. On the Web tab switch **Force HTTPS** on, then press **Reload**.
6. Open `https://YOURUSER.pythonanywhere.com` and create your account.

The database lives outside the repo (`studyquest-data`), so `git pull` never touches it.
To update later: Bash console `cd studyquest && git pull`, then Reload on the Web tab.
Free accounts expire if you don't log in to PythonAnywhere for a while, so check their current rules.

## Any other server (VPS, Oracle free VM, home PC)

    HOST=0.0.0.0 PORT=8000 python3 app.py

Put Caddy or nginx in front for HTTPS and set `TRUST_PROXY=1`. Keep the DB on a persistent disk.

## Settings (environment variables)

| Variable | Default | What it does |
|---|---|---|
| `HOST`, `PORT` | `127.0.0.1`, `8000` | Built-in server address |
| `STUDYQUEST_DB` | `./studyquest.db` | Database file location |
| `TRUST_PROXY` | off | `1` when behind a proxy (login throttling uses the real client IP) |
| `SIGNUP_CODE` | none | If set, sign-up needs this invite code |
| `OCR_LANG` | `eng` | Tesseract language code(s), e.g. `eng+fil` |
| `MAX_USERS` | 500 | Sign-up cap (protects free-tier disk) |
| `MAX_DECKS`, `MAX_CARDS` | 100, 5000 | Per-user limits |

## Security notes

Passwords are hashed with scrypt; sessions are random tokens (only their hash is stored)
in HttpOnly, SameSite cookies; login is rate-limited; cross-site POSTs are rejected;
every query is filtered by user. Run it over HTTPS when public.
