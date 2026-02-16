from __future__ import annotations

import json
import logging
import os
import re
import smtplib
import ssl
import time
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable

import schedule
from dotenv import load_dotenv
from openai import OpenAI
from playwright.sync_api import sync_playwright

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("job-agent")

ROLE_KEYWORDS = [
    "performance marketing",
    "google ads",
    "meta ads",
    "ai specialist",
    "ai video",
    "ai image",
]


@dataclass
class Job:
    title: str
    company: str
    location: str
    link: str


def _slugify(value: str) -> str:
    return re.sub(r"\W+", "-", value.strip().lower()).strip("-")


def build_search_urls() -> list[str]:
    base = "https://www.linkedin.com/jobs/search"
    urls = []
    for keyword in ROLE_KEYWORDS:
        params = f"keywords={keyword.replace(' ', '%20')}&location=Worldwide&f_TPR=r86400"
        urls.append(f"{base}?{params}")
    return urls


def collect_jobs(limit_per_keyword: int = 12) -> list[Job]:
    """Scrape public LinkedIn job cards from search result pages."""
    results: list[Job] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for url in build_search_urls():
            logger.info("Checking %s", url)
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2_000)

            cards = page.locator(".base-card").all()[:limit_per_keyword]
            for card in cards:
                try:
                    title = card.locator("h3").inner_text().strip()
                    company = card.locator("h4").inner_text().strip()
                    location = card.locator(".job-search-card__location").inner_text().strip()
                    link = card.locator("a.base-card__full-link").first.get_attribute("href") or ""
                    if link and title:
                        results.append(Job(title=title, company=company, location=location, link=link))
                except Exception:
                    continue

        browser.close()

    deduped: dict[str, Job] = {}
    for job in results:
        key = f"{job.title}|{job.company}|{job.location}"
        deduped[key] = job

    sorted_jobs = sorted(deduped.values(), key=lambda j: (j.company.lower(), j.title.lower()))
    logger.info("Collected %s unique jobs", len(sorted_jobs))
    return sorted_jobs


def build_job_digest(jobs: Iterable[Job]) -> str:
    lines = ["Fresh LinkedIn jobs found in the last 24 hours:", ""]
    for idx, job in enumerate(jobs, start=1):
        lines.append(f"{idx}. {job.title} — {job.company} ({job.location})")
        lines.append(f"   {job.link}")
    return "\n".join(lines)


def generate_cover_letter(client: OpenAI, resume_text: str, job: Job) -> str:
    prompt = f"""
Write a concise, specific cover letter for this role.

Job title: {job.title}
Company: {job.company}
Location: {job.location}
Job link: {job.link}

Candidate resume:
{resume_text}

Requirements:
- 180-250 words
- Mention measurable marketing outcomes when relevant.
- Highlight Google Ads, Meta Ads, and AI tooling experience.
- Keep tone confident and human.
"""
    response = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        input=prompt,
    )
    return response.output_text.strip()


def optimize_resume(client: OpenAI, resume_text: str, jobs: list[Job]) -> str:
    focus_roles = "\n".join(f"- {job.title} at {job.company}" for job in jobs[:8])
    prompt = f"""
Improve the following resume for these role targets:
{focus_roles}

Resume:
{resume_text}

Return:
- A rewritten ATS-friendly resume in markdown.
- Strong bullet points with action + metric format.
- Include a short 'Core Skills' section aligned to performance marketing + AI creative workflows.
"""

    response = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        input=prompt,
    )
    return response.output_text.strip()


def send_email(subject: str, body: str, recipient: str, attachments: dict[str, str] | None = None) -> None:
    smtp_user = os.environ["SMTP_USER"]
    smtp_password = os.environ["SMTP_PASSWORD"]
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "465"))

    msg = EmailMessage()
    msg["From"] = smtp_user
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body)

    for filename, content in (attachments or {}).items():
        msg.add_attachment(content.encode("utf-8"), maintype="text", subtype="plain", filename=filename)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context) as server:
        server.login(smtp_user, smtp_password)
        server.send_message(msg)


def run_once() -> None:
    load_dotenv()

    resume_path = Path(os.getenv("RESUME_FILE", "resume.md"))
    recruiter_email = os.environ["TARGET_EMAIL"]
    cc_email = os.getenv("MY_EMAIL", recruiter_email)

    if not resume_path.exists():
        raise FileNotFoundError(f"Resume file not found: {resume_path}")

    resume_text = resume_path.read_text(encoding="utf-8")
    jobs = collect_jobs()
    if not jobs:
        logger.warning("No jobs collected today.")
        return

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    optimized_resume = optimize_resume(client, resume_text, jobs)
    top_jobs = jobs[:5]

    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    date_key = datetime.now().strftime("%Y-%m-%d")

    (output_dir / f"jobs-{date_key}.json").write_text(
        json.dumps([job.__dict__ for job in jobs], indent=2),
        encoding="utf-8",
    )

    digest = build_job_digest(top_jobs)

    for job in top_jobs:
        letter = generate_cover_letter(client, optimized_resume, job)
        safe_name = _slugify(f"{job.company}-{job.title}")
        letter_file = output_dir / f"cover-letter-{safe_name}.txt"
        letter_file.write_text(letter, encoding="utf-8")

        email_body = (
            f"Hello Hiring Team,\n\n"
            f"Please find my tailored cover letter and optimized resume for the {job.title} role.\n\n"
            f"Job listing: {job.link}\n\n"
            f"Best regards"
        )

        send_email(
            subject=f"Application: {job.title} | {job.company}",
            body=email_body,
            recipient=recruiter_email,
            attachments={
                "cover-letter.txt": letter,
                "optimized-resume.md": optimized_resume,
            },
        )

        logger.info("Application email sent for %s at %s", job.title, job.company)
        time.sleep(2)

    send_email(
        subject=f"Daily LinkedIn Job Digest - {date_key}",
        body=digest,
        recipient=cc_email,
    )
    logger.info("Daily digest sent to %s", cc_email)


def run_scheduler() -> None:
    logger.info("Scheduler started. Daily run at 10:00.")
    schedule.every().day.at("10:00").do(run_once)

    while True:
        schedule.run_pending()
        time.sleep(20)


if __name__ == "__main__":
    mode = os.getenv("RUN_MODE", "once")
    if mode == "schedule":
        run_scheduler()
    else:
        run_once()
