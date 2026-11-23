# ATS_Application — Evidence-Based Resume Recommendation

**ATS_Application** ranks candidates by what they have actually built rather than simple keyword matching. Candidates upload resumes and apply to jobs; hirers post job descriptions and receive ranked, evidence-backed evaluation scores for every applicant.

> **Repository Structure:** The full application source code, prompts, and launcher scripts are located inside `Vaishnavi_Darade_ACL_Task/ATS_Application/` (and also documented in `START HERE.txt`).

---

## Before the First Start (One-Time Setup)

1. **Python 3.10+** must be installed on the system:
   - **Windows:** Download from [python.org/downloads](https://www.python.org/downloads/). On the first installer screen, tick **"Add python.exe to PATH"**.
   - **macOS / Linux:** Install Python 3 via [python.org](https://www.python.org/downloads/) or your system package manager.
2. **API Key Configuration:** Add your Google Gemini API key in `Vaishnavi_Darade_ACL_Task/ATS_Application/env_app.py` (or set `GEMINI_API_KEY` in your environment) before starting.
3. **Internet Connection:** Required on first launch to create the virtual environment and install dependencies (~2–5 minutes). Subsequent launches take a few seconds.

---

## How to Start

Navigate into `Vaishnavi_Darade_ACL_Task/ATS_Application/` and launch using the script for your OS:

- **Windows:** Double-click `run.bat` (or run `.\run.ps1` in PowerShell)
- **macOS:** Open Terminal, drag `run.sh` into the window, and press **Enter**
- **Linux:** Run `./run.sh` in a terminal

Your browser will open automatically at **`http://127.0.0.1:1114`**. Keep the terminal window open while using the application.

---

## Walkthrough: First Steps in the App

1. Click **"Create an account"** and choose **"Hirer"**.
2. Click **"Post a job"** and paste a full job description.
3. Create a **"Candidate"** account, upload a PDF resume, and apply to the job.
4. Open the job as a Hirer and click **"Rankings"** to view candidates sorted by match score:
   - Click **"View evaluation"** for the full skill-evidence breakdown and gap analysis.
   - Select **2–4 candidates** and click **"Compare"** to evaluate them side by side.

---

## Troubleshooting

- **"Python was not found":** Reinstall Python and ensure **"Add to PATH"** is checked.
- **"AI is overloaded, try again in a minute":** Upstream Gemini capacity spike (`503`). Wait a few seconds and click **"Run AI analysis"** or **"Re-evaluate"**—your submission is already saved.
- **First start interrupted:** Delete the generated `venv` folder inside `ATS_Application/` and re-run `run.bat` / `run.sh`.
- **Browser did not open automatically:** Ensure the terminal window is still running, then open `http://127.0.0.1:1114` manually.
