# LinkedIn Daily Job Agent

This agent checks fresh LinkedIn jobs daily around **10:00 AM**, finds roles for:

- Performance Marketing
- Google Ads
- Meta Ads
- AI Specialist
- AI Video
- AI Image

Then it:
1. Builds a daily job digest.
2. Optimizes your resume for top-matching roles.
3. Generates tailored cover letters.
4. Emails the application package.

## 1) Setup

```bash
cd linkedin_job_agent
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

Add your latest resume as `resume.md` (or update `RESUME_FILE` in `.env`).

## 2) Configure `.env`

Required:
- `OPENAI_API_KEY`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `TARGET_EMAIL`

Optional:
- `MY_EMAIL` (you receive daily digest)
- `OPENAI_MODEL`
- `RUN_MODE=once|schedule`

## 3) Run now

```bash
python job_agent.py
```

## 4) Run every day at 10:00 AM

Use built-in scheduler:

```bash
RUN_MODE=schedule python job_agent.py
```

Or use cron (recommended for server deployments):

```bash
0 10 * * * cd /workspace/shine-plumber/linkedin_job_agent && /usr/bin/python3 job_agent.py >> agent.log 2>&1
```

## Output

Generated files are saved under `output/`:
- `jobs-YYYY-MM-DD.json`
- `cover-letter-*.txt`

## Notes

- LinkedIn can change page structure and anti-bot behavior; if selectors break, update `.base-card` selectors in `job_agent.py`.
- For best control, set `TARGET_EMAIL` to your own inbox first, review each packet, then forward manually.
- Ensure you comply with job board terms and applicable laws when automating application workflows.
