import json

from scripts import ai, jd_manager, resume_parser
from scripts.database import Evaluation

DIMENSION_WEIGHTS = {"deepness": 0.40, "spread": 0.25, "evidence": 0.35}
EVIDENCE_WEIGHTS = {"real_world": 0.45, "dataset_complexity": 0.35, "basic_projects": 0.20}
EVIDENCE_LEVELS = {
    0: "Not mentioned",
    1: "Mentioned only",
    2: "Basic project",
    3: "Meaningful implementation",
    4: "Complex real-world implementation",
    5: "Strong professional results",
}


def evidence_score(evidence):
    return round(sum(ai.as_score(evidence.get(key, {}).get("score")) * weight
                     for key, weight in EVIDENCE_WEIGHTS.items()), 1)


def overall_score(deepness, spread, evidence):
    scores = {"deepness": deepness, "spread": spread, "evidence": evidence}
    return round(sum(scores[key] * weight for key, weight in DIMENSION_WEIGHTS.items()), 1)


def clean_skill_evidence(items):
    cleaned, seen = [], set()
    for item in items:
        if not isinstance(item, dict) or not item.get("skill"):
            continue
        name = str(item["skill"]).strip()
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        try:
            level = max(0, min(5, int(item.get("level", 0))))
        except (TypeError, ValueError):
            level = 0
        quality = item.get("quality") if item.get("quality") in ("strong", "moderate", "weak", "none") else "weak"
        score = ai.as_score(item.get("score", level * 20))
        if level <= 1:
            score = min(score, 20)
        cleaned.append({
            "skill": name,
            "level": level,
            "level_label": EVIDENCE_LEVELS[level],
            "score": round(score),
            "quality": "none" if level == 0 else quality,
            "used_in": [u for u in ai.as_list(item.get("used_in"), 6) if isinstance(u, str)],
            "required": bool(item.get("required")),
            "evidence": str(item.get("evidence", ""))[:400],
        })
    cleaned.sort(key=lambda s: (not s["required"], -s["score"]))
    return cleaned


def clean_missing(items):
    cleaned = []
    for item in items:
        if isinstance(item, dict) and item.get("skill"):
            kind = item.get("type") if item.get("type") in ("missing", "undocumented") else "missing"
            cleaned.append({"skill": str(item["skill"]), "type": kind,
                            "mandatory": bool(item.get("mandatory")), "note": str(item.get("note", ""))})
        elif isinstance(item, str):
            cleaned.append({"skill": item, "type": "missing", "mandatory": False, "note": ""})
    return cleaned


def clean_dimension(data):
    data = data if isinstance(data, dict) else {}
    return {"score": round(ai.as_score(data.get("score")), 1),
            "reasoning": str(data.get("reasoning", ""))[:1500],
            "evidence": ai.as_list(data.get("evidence"), 10)}


def clean_result(data):
    if not isinstance(data, dict):
        raise ai.AIError("Evaluation response was not valid JSON.")
    evidence_raw = data.get("evidence") if isinstance(data.get("evidence"), dict) else {}
    evidence = {key: clean_dimension(evidence_raw.get(key)) for key in EVIDENCE_WEIGHTS}
    for key in ("projects_reviewed", "datasets_reviewed"):
        evidence[key] = [p for p in ai.as_list(evidence_raw.get(key), 12) if isinstance(p, dict)]
    candidate = data.get("candidate_feedback") if isinstance(data.get("candidate_feedback"), dict) else {}
    hirer = data.get("hirer_assessment") if isinstance(data.get("hirer_assessment"), dict) else {}
    return {
        "deepness": clean_dimension(data.get("deepness")),
        "spread": clean_dimension(data.get("spread")),
        "evidence": evidence,
        "skill_evidence": clean_skill_evidence(ai.as_list(data.get("skill_evidence"), 40)),
        "matching_requirements": [s for s in ai.as_list(data.get("matching_requirements"), 30) if isinstance(s, str)],
        "missing_requirements": clean_missing(ai.as_list(data.get("missing_requirements"), 30)),
        "candidate_feedback": {
            key: [s for s in ai.as_list(candidate.get(key), 10) if isinstance(s, str)]
            for key in ("technologies_to_explain", "project_suggestions", "achievements_to_highlight", "general_suggestions")
        },
        "hirer_assessment": {
            "summary": str(hirer.get("summary", ""))[:2000],
            "strengths": [s for s in ai.as_list(hirer.get("strengths"), 8) if isinstance(s, str)],
            "concerns": [s for s in ai.as_list(hirer.get("concerns"), 8) if isinstance(s, str)],
            "technical_details": [s for s in ai.as_list(hirer.get("technical_details"), 10) if isinstance(s, str)],
            "certifications_achievements": [s for s in ai.as_list(hirer.get("certifications_achievements"), 10) if isinstance(s, str)],
            "recommendation": str(hirer.get("recommendation", "")),
        },
    }


def evaluate_application(application):
    resume = application.resume
    resume_analysis = resume_parser.analyze_resume(resume)
    requirements = jd_manager.job_requirements(application.job)
    prompt = ai.load_prompt(
        "candidate_evaluation",
        JOB=application.job.as_text()[:12000],
        REQUIREMENTS=json.dumps(requirements, indent=1),
        RESUME_ANALYSIS=json.dumps(resume_analysis, indent=1),
        RESUME_TEXT=resume.extracted_text[:15000],
    )
    result = clean_result(ai.ask(prompt))
    deepness = result["deepness"]["score"]
    spread = result["spread"]["score"]
    evidence = evidence_score(result["evidence"])
    result["weights"] = {"dimensions": DIMENSION_WEIGHTS, "evidence": EVIDENCE_WEIGHTS}
    return Evaluation(
        application_id=application.id,
        resume_id=resume.id,
        deepness=deepness,
        spread=spread,
        evidence=evidence,
        overall=overall_score(deepness, spread, evidence),
        result=json.dumps(result),
    )
