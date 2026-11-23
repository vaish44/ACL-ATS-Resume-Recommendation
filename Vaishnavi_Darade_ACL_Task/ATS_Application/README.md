# RR (Resume Recommendation) — AI Recruitment & Evidence-Based Resume Matching

A Flask app where candidates upload resumes and apply to jobs. Hirers post jobs and get ranked, explainable evaluations. Candidates are scored on what they actually built, not on which keywords appear.

## Quick start

**Windows:** double-click `run.bat`
**Linux / macOS:** `./run.sh`

Either script:
1. creates a `venv` if it doesn't exist
2. installs any missing libraries from `requirements.txt`
3. reminds you if `GEMINI_API_KEY` is empty in `env_app.py`
4. starts the app and opens http://127.0.0.1:1114

Manual alternative:
```bash
python -m venv venv
venv\Scripts\activate        # Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
python app.py
```

## Configuration (`env_app.py`)

All settings are plain Python strings in `env_app.py`. Real OS environment variables with the same name take priority. If `SECRET_KEY` is empty, a random key is created once and saved to `data/secret_key.txt`.

| Variable | Purpose |
|---|---|
| `AI_PROVIDER` | `"gemini"` or `"openai"`. If both keys are set, the other provider is used automatically when the chosen one is down. |
| `GEMINI_API_KEY` | Google Gemini key. With no AI key at all, the app still works, but AI analysis and evaluations are disabled and can be run later. |
| `GEMINI_MODEL` | Defaults to `gemini-3.5-flash-lite` (lightweight). If a model is unavailable or overloaded, the app falls back to `gemini-3.1-flash-lite` → `gemini-3.5-flash` → `gemini-3.8-flash`. |
| `OPENAI_API_KEY` | OpenAI key |
| `OPENAI_MODEL` | Defaults to `gpt-5-mini`, with fallbacks `gpt-5-nano` → `gpt-4.1-mini` → `gpt-4o-mini`. |
| `SECRET_KEY` | Session signing key |
| `DATABASE_URL` | Defaults to `sqlite:///data/recruitment.db` |
| `UPLOAD_FOLDER` | Where original resumes are stored |
| `MAX_CONTENT_LENGTH` | Upload limit in bytes (default 10 MB) |

Optional: install [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) so scanned PDFs and images are read locally. If it isn't found, those files go to Gemini instead (only when a key is set). You can set `TESSERACT_CMD` to point at a custom install.

## How it works

**Resume extraction.** Local tools are always tried first:
- PDF text with PyMuPDF; scanned pages are rendered and OCR'd with Tesseract
- DOCX with python-docx; legacy DOC via OLE stream decoding (RTF also handled)
- HTML with BeautifulSoup; images with Tesseract

Gemini is used only when local extraction produces too little text. The extraction method and status are saved for every resume version.

**Gemini usage.** Each call is made at most once and the result is cached:
1. Job analysis: once when a job is created or its content changes.
2. Resume analysis: once per resume version, done lazily at the first application.
3. Candidate evaluation: once per application or re-evaluation.

All responses are requested as JSON and validated: scores are clamped, lists cleaned, duplicate skills removed. Gemini calls are retried, but not when the key or model is invalid.

**Scoring.** The weights live in `scripts/scoring_engine.py`, separate from the prompts:
- Overall = Deepness × 0.40 + Spread × 0.25 + Evidence × 0.35
- Evidence = Real-world × 0.45 + Dataset & implementation × 0.35 + Basic projects × 0.20
- Skill evidence matrix: every job-relevant skill gets an evidence level (0–5), a 0–100 score based on evidence quality, the projects or roles where it was used, and the cited evidence. A skill that is only listed is capped at 20.

**Roles and security**
- Passwords are hashed (Werkzeug) and need at least 8 characters with a letter and a number.
- Every form has CSRF protection.
- Failed logins are rate-limited: 5 attempts per 5 minutes.
- Access is role-based: hirers see only applicants to their own jobs, and candidates see only their own data.
- Uploads are checked by extension and file signature. Untrusted HTML and DOC files are downloaded, never rendered in the browser.

**History.** Uploading a new resume creates a new version. Re-evaluating adds a new evaluation, and earlier ones are kept in the evaluation history.

## Project layout

```
app.py                  Flask routes, auth, access control
scripts/database.py     SQLAlchemy models
scripts/resume_parser.py  extraction pipeline + resume analysis
scripts/ocr.py          Tesseract OCR + Gemini transcription fallback
scripts/jd_manager.py   job form handling + job analysis
scripts/scoring_engine.py  weights, validation, evaluation
scripts/ai.py           Gemini + OpenAI clients, model fallback, retries, JSON parsing
prompts/                prompt templates
templates/, static/     Bootstrap UI with light/dark theme
```

## Check the AI connection

Run `venv/bin/python app.py --check-ai` (Windows: `venv\Scripts\python app.py --check-ai`). It makes one tiny call and prints the model in use, or the exact problem.

## Troubleshooting installs

The run scripts install from ready-made wheels (`--prefer-binary`) and never compile PyMuPDF from source. If a single package still fails, the scripts install the rest one at a time and the app keeps running. Without PyMuPDF, PDFs are read with `pypdf` and scanned PDFs need Gemini.

| Problem | Fix |
|---|---|
| `CERTIFICATE_VERIFY_FAILED` on macOS | `run.sh` handles this automatically. For other tools, run `/Applications/Python 3.x/Install Certificates.command` once. |
| A package tries to build from source or fails to compile | Usually a very new Python with no wheels yet. Python 3.11–3.13 is the safest choice. |
| Install got stuck or broke partway | Delete the `venv` folder and run the script again. |
| Behind a corporate proxy | Set `HTTPS_PROXY=http://proxy:port` before running the script. |
| `python3 -m venv` fails on Ubuntu/Debian | `sudo apt install python3-venv` |
| Port 1114 already in use | The script opens the running app instead. To use another port, set the `PORT` environment variable. |
