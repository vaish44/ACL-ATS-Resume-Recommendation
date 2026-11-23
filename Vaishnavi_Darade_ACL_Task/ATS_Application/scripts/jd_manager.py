import json

from scripts import ai
from scripts.database import Job

FIELD_LIMITS = {"title": 200, "experience": 200}


def fill_job_from_form(job, form):
    errors = []
    for field in Job.FORM_FIELDS:
        value = (form.get(field) or "").strip()
        limit = FIELD_LIMITS.get(field, 8000)
        if len(value) > limit:
            errors.append(f"{field.replace('_', ' ').title()} is too long.")
        setattr(job, field, value[:limit])
    if not job.title:
        errors.append("Job title is required.")
    if len(job.description) < 30:
        errors.append("Please write a job description of at least 30 characters.")
    return errors


def split_skills(text):
    return [s.strip() for s in (text or "").replace("\n", ",").split(",") if s.strip()]


def clean_analysis(data):
    if not isinstance(data, dict):
        raise ai.AIError("Job analysis was not valid JSON.")
    return {
        "role_summary": str(data.get("role_summary", ""))[:600],
        "seniority": str(data.get("seniority", "")),
        "min_experience_years": data.get("min_experience_years"),
        "mandatory_skills": ai.as_list(data.get("mandatory_skills"), 30),
        "preferred_skills": ai.as_list(data.get("preferred_skills"), 30),
        "key_responsibilities": ai.as_list(data.get("key_responsibilities"), 12),
        "expected_depth": ai.as_list(data.get("expected_depth"), 12),
        "relevant_technology_areas": ai.as_list(data.get("relevant_technology_areas"), 20),
        "project_expectations": ai.as_list(data.get("project_expectations"), 10),
    }


def fallback_analysis(job):
    return {
        "role_summary": job.description[:300],
        "mandatory_skills": split_skills(job.required_skills),
        "preferred_skills": split_skills(job.preferred_skills),
    }


def analyze_job(job):
    try:
        prompt = ai.load_prompt("job_analysis", JOB=job.as_text())
        job.analysis = json.dumps(clean_analysis(ai.ask(prompt)))
        job.analysis_status = "done"
        return None
    except ai.AIError as error:
        job.analysis = json.dumps(fallback_analysis(job))
        job.analysis_status = "failed"
        return str(error)


def job_requirements(job):
    analysis = job.load("analysis")
    return analysis or fallback_analysis(job)
