import os
import re
import secrets
import sys
import time
import uuid
from datetime import timedelta
from functools import wraps
from pathlib import Path

from flask import (Flask, abort, flash, g, redirect, render_template, request, send_from_directory, session,
                   url_for)
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent


def load_settings():
    try:
        import env_app
    except ImportError:
        print("NOTE: env_app.py not found. Using default settings.")
        return
    except SyntaxError as error:
        print(f"WARNING: env_app.py has a syntax error (line {error.lineno}). Using default settings.")
        return
    for name, value in vars(env_app).items():
        if name.isupper() and isinstance(value, (str, int, float)):
            os.environ.setdefault(name, str(value).strip())


def persistent_secret_key():
    key_file = BASE_DIR / "data" / "secret_key.txt"
    if key_file.exists() and key_file.read_text().strip():
        return key_file.read_text().strip()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    key_file.write_text(key)
    return key


load_settings()

from scripts import ai, jd_manager, ocr, resume_parser, scoring_engine  # noqa: E402
from scripts.database import Application, Job, Resume, User, db  # noqa: E402


def resolve_path(value, default):
    path = Path(value or default)
    return path if path.is_absolute() else BASE_DIR / path


def database_url():
    url = os.getenv("DATABASE_URL", "").strip() or "sqlite:///data/recruitment.db"
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////") and ":" not in url[10:12]:
        db_path = resolve_path(url[10:], "data/recruitment.db")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{db_path.as_posix()}"
    return url


def max_upload_size():
    try:
        return int(os.getenv("MAX_CONTENT_LENGTH", "") or 10 * 1024 * 1024)
    except ValueError:
        return 10 * 1024 * 1024


app = Flask(__name__)
secret_key = os.getenv("SECRET_KEY", "").strip()
if not secret_key:
    secret_key = persistent_secret_key()
app.config.update(
    SECRET_KEY=secret_key,
    SQLALCHEMY_DATABASE_URI=database_url(),
    MAX_CONTENT_LENGTH=max_upload_size(),
    UPLOAD_FOLDER=str(resolve_path(os.getenv("UPLOAD_FOLDER"), "data/resumes")),
    EXTRACTED_FOLDER=str(BASE_DIR / "data" / "extracted"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)
Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
db.init_app(app)
with app.app_context():
    db.create_all()

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SORT_FIELDS = ("overall", "deepness", "spread", "evidence")
failed_logins = {}


# ---------- security helpers ----------

def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]


@app.before_request
def load_user_and_check_csrf():
    g.user = db.session.get(User, session["user_id"]) if "user_id" in session else None
    if "user_id" in session and g.user is None:
        session.clear()
    if request.method == "POST":
        token = request.form.get("csrf_token", "")
        if not token or not secrets.compare_digest(token, session.get("csrf_token", "")):
            flash("Your session expired. Please try again.", "warning")
            return redirect(request.referrer or url_for("index"))


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


@app.context_processor
def template_globals():
    return {"current_user": g.get("user"), "ai_ready": ai.is_configured()}


app.jinja_env.globals["csrf_token"] = csrf_token


@app.template_filter("score_class")
def score_class(score):
    score = score or 0
    return "success" if score >= 70 else "warning" if score >= 45 else "danger"


def login_required(role=None):
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if g.user is None:
                flash("Please log in to continue.", "info")
                return redirect(url_for("login", next=request.path))
            if role and g.user.role != role:
                abort(403)
            return view(*args, **kwargs)
        return wrapper
    return decorator


def password_problem(password):
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Password must contain at least one letter and one number."
    return None


def too_many_attempts(key):
    attempts = [t for t in failed_logins.get(key, []) if time.time() - t < 300]
    failed_logins[key] = attempts
    return len(attempts) >= 5


def get_own_job(job_id):
    job = db.session.get(Job, job_id) or abort(404)
    if job.hirer_id != g.user.id:
        abort(403)
    return job


def get_visible_application(application_id):
    application = db.session.get(Application, application_id) or abort(404)
    if g.user.role == "candidate" and application.candidate_id != g.user.id:
        abort(403)
    if g.user.role == "hirer" and application.job.hirer_id != g.user.id:
        abort(403)
    return application


def run_evaluation(application):
    try:
        evaluation = scoring_engine.evaluate_application(application)
        db.session.add(evaluation)
        application.status = "evaluated"
        application.error = ""
        db.session.commit()
        return True
    except Exception as error:
        db.session.rollback()
        if not isinstance(error, ai.AIError):
            app.logger.exception("Evaluation failed")
            error = "Unexpected error while processing the AI response. Please retry."
        application.status = "pending"
        application.error = str(error)
        db.session.commit()
        flash(f"AI evaluation could not run: {error}", "warning")
        return False


# ---------- auth ----------

@app.route("/")
def index():
    return redirect(url_for("dashboard") if g.user else url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("dashboard"))
    form = request.form
    if request.method == "POST":
        name = form.get("name", "").strip()
        email = form.get("email", "").strip().lower()
        password = form.get("password", "")
        role = form.get("role", "")
        error = None
        if not name or len(name) > 120:
            error = "Please enter your name."
        elif not EMAIL_PATTERN.match(email) or len(email) > 255:
            error = "Please enter a valid email address."
        elif role not in ("candidate", "hirer"):
            error = "Please choose an account type."
        elif password != form.get("confirm_password", ""):
            error = "Passwords do not match."
        else:
            error = password_problem(password)
        if not error and User.query.filter_by(email=email).first():
            error = "An account with this email already exists."
        if error:
            flash(error, "danger")
        else:
            user = User(name=name, email=email, role=role, company=form.get("company", "").strip()[:160])
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            session.clear()
            session.permanent = True
            session["user_id"] = user.id
            flash(f"Welcome, {user.name}!", "success")
            return redirect(url_for("dashboard"))
    return render_template("register.html", form=form)


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        key = f"{request.remote_addr}:{email}"
        if too_many_attempts(key):
            flash("Too many failed attempts. Please wait 5 minutes and try again.", "danger")
            return render_template("login.html", email=email)
        user = User.query.filter_by(email=email).first()
        if user and user.check_password(request.form.get("password", "")):
            failed_logins.pop(key, None)
            session.clear()
            session.permanent = True
            session["user_id"] = user.id
            next_url = request.args.get("next", "")
            if next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect(url_for("dashboard"))
        failed_logins.setdefault(key, []).append(time.time())
        flash("Invalid email or password.", "danger")
        return render_template("login.html", email=email)
    return render_template("login.html", email="")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/profile", methods=["GET", "POST"])
@login_required()
def profile():
    user = g.user
    if request.method == "POST":
        if request.form.get("action") == "password":
            new_password = request.form.get("new_password", "")
            if not user.check_password(request.form.get("current_password", "")):
                flash("Current password is incorrect.", "danger")
            elif new_password != request.form.get("confirm_password", ""):
                flash("New passwords do not match.", "danger")
            elif password_problem(new_password):
                flash(password_problem(new_password), "danger")
            else:
                user.set_password(new_password)
                db.session.commit()
                flash("Password updated.", "success")
        else:
            name = request.form.get("name", "").strip()
            if not name:
                flash("Name cannot be empty.", "danger")
            else:
                user.name = name[:120]
                for field, limit in (("headline", 200), ("phone", 40), ("location", 120), ("company", 160), ("about", 3000)):
                    setattr(user, field, request.form.get(field, "").strip()[:limit])
                db.session.commit()
                flash("Profile saved.", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html", user=user)


@app.route("/dashboard")
@login_required()
def dashboard():
    if g.user.role == "hirer":
        jobs = g.user.jobs
        stats = {
            "jobs": len(jobs),
            "open": sum(1 for j in jobs if j.is_open),
            "applications": sum(len(j.applications) for j in jobs),
        }
        return render_template("hirer_dashboard.html", jobs=jobs, stats=stats)
    return render_template("candidate_dashboard.html", resume=g.user.latest_resume,
                           applications=g.user.applications, tesseract=ocr.tesseract_available())


# ---------- resumes ----------

@app.route("/resume/upload", methods=["POST"])
@login_required("candidate")
def upload_resume():
    file = request.files.get("resume")
    if not file or not file.filename:
        flash("Please choose a resume file.", "danger")
        return redirect(url_for("dashboard"))
    original_name = secure_filename(file.filename) or "resume"
    ext = resume_parser.file_extension(file.filename)
    if ext not in resume_parser.ALLOWED_EXTENSIONS:
        flash("Unsupported file type. Use PDF, DOC, DOCX, HTML, JPG, JPEG or PNG.", "danger")
        return redirect(url_for("dashboard"))
    data = file.read()
    if not data:
        flash("The uploaded file is empty.", "danger")
        return redirect(url_for("dashboard"))
    if not resume_parser.looks_valid(data, ext):
        flash("The file content does not match its extension.", "danger")
        return redirect(url_for("dashboard"))

    stored_name = f"{uuid.uuid4().hex}.{ext}"
    path = Path(app.config["UPLOAD_FOLDER"]) / stored_name
    path.write_bytes(data)
    text, method, status, note = resume_parser.extract_text(str(path), ext)
    resume_parser.save_extracted(app.config["EXTRACTED_FOLDER"], stored_name, text)
    version = (g.user.latest_resume.version + 1) if g.user.latest_resume else 1
    resume = Resume(candidate_id=g.user.id, version=version, original_name=original_name, stored_name=stored_name,
                    file_type=ext, extracted_text=text, extraction_method=method, extraction_status=status)
    db.session.add(resume)
    db.session.commit()
    if status == "success":
        flash(f"Resume v{version} uploaded and read successfully ({method}).", "success")
    elif status == "partial":
        flash(f"Resume v{version} uploaded, but only partial text was extracted. {note}", "warning")
    else:
        flash(f"Resume v{version} uploaded, but no text could be extracted. {note}", "danger")
    return redirect(url_for("dashboard"))


@app.route("/resume/<int:resume_id>/file")
@login_required()
def resume_file(resume_id):
    resume = db.session.get(Resume, resume_id) or abort(404)
    allowed = resume.candidate_id == g.user.id
    if g.user.role == "hirer":
        allowed = any(
            a.job.hirer_id == g.user.id and (a.resume_id == resume.id or any(e.resume_id == resume.id for e in a.evaluations))
            for a in resume.candidate.applications
        )
    if not allowed:
        abort(403)
    inline = resume.file_type in ("pdf", "png", "jpg", "jpeg")
    return send_from_directory(app.config["UPLOAD_FOLDER"], resume.stored_name, as_attachment=not inline,
                               download_name=resume.original_name)


@app.route("/resume/<int:resume_id>/text")
@login_required("candidate")
def resume_text(resume_id):
    resume = db.session.get(Resume, resume_id) or abort(404)
    if resume.candidate_id != g.user.id:
        abort(403)
    return render_template("resume_text.html", resume=resume)


# ---------- jobs ----------

@app.route("/jobs")
@login_required()
def jobs():
    query = request.args.get("q", "").strip()
    job_query = Job.query.filter_by(is_open=True)
    if query:
        like = f"%{query}%"
        job_query = job_query.filter(Job.title.ilike(like) | Job.description.ilike(like) | Job.required_skills.ilike(like))
    applied = {a.job_id for a in g.user.applications} if g.user.role == "candidate" else set()
    return render_template("jobs.html", jobs=job_query.order_by(Job.created_at.desc()).all(), query=query, applied=applied)


@app.route("/jobs/<int:job_id>")
@login_required()
def job_details(job_id):
    job = db.session.get(Job, job_id) or abort(404)
    if not job.is_open and job.hirer_id != g.user.id and g.user.role == "hirer":
        abort(404)
    application = None
    if g.user.role == "candidate":
        application = Application.query.filter_by(candidate_id=g.user.id, job_id=job.id).first()
        if not job.is_open and not application:
            abort(404)
    return render_template("job_details.html", job=job, requirements=jd_manager.job_requirements(job),
                           application=application, resume=g.user.latest_resume if g.user.role == "candidate" else None)


@app.route("/jobs/new", methods=["GET", "POST"])
@login_required("hirer")
def create_job():
    job = Job(hirer_id=g.user.id)
    if request.method == "POST":
        errors = jd_manager.fill_job_from_form(job, request.form)
        if errors:
            for error in errors:
                flash(error, "danger")
            return render_template("create_job.html", job=job, editing=False)
        ai_error = jd_manager.analyze_job(job) if ai.is_configured() else "No AI key is configured."
        db.session.add(job)
        db.session.commit()
        if ai_error:
            flash(f"Job published. AI requirement analysis skipped: {ai_error} Your entered skills are used instead.", "warning")
        else:
            flash("Job published and analysed by AI.", "success")
        return redirect(url_for("job_details", job_id=job.id))
    return render_template("create_job.html", job=job, editing=False)


@app.route("/jobs/<int:job_id>/edit", methods=["GET", "POST"])
@login_required("hirer")
def edit_job(job_id):
    job = get_own_job(job_id)
    if request.method == "POST":
        before = job.as_text()
        errors = jd_manager.fill_job_from_form(job, request.form)
        if errors:
            db.session.rollback()
            for error in errors:
                flash(error, "danger")
            return render_template("create_job.html", job=job, editing=True)
        ai_error = None
        if job.as_text() != before or job.analysis_status != "done":
            ai_error = jd_manager.analyze_job(job) if ai.is_configured() else "No AI key is configured."
        db.session.commit()
        flash("Job updated." + (f" AI analysis skipped: {ai_error}" if ai_error else ""), "warning" if ai_error else "success")
        return redirect(url_for("job_details", job_id=job.id))
    return render_template("create_job.html", job=job, editing=True)


@app.route("/jobs/<int:job_id>/delete", methods=["POST"])
@login_required("hirer")
def delete_job(job_id):
    job = get_own_job(job_id)
    db.session.delete(job)
    db.session.commit()
    flash("Job deleted.", "info")
    return redirect(url_for("dashboard"))


@app.route("/jobs/<int:job_id>/toggle", methods=["POST"])
@login_required("hirer")
def toggle_job(job_id):
    job = get_own_job(job_id)
    job.is_open = not job.is_open
    db.session.commit()
    flash("Job is now " + ("open." if job.is_open else "closed."), "info")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/jobs/<int:job_id>/reanalyze", methods=["POST"])
@login_required("hirer")
def reanalyze_job(job_id):
    job = get_own_job(job_id)
    error = jd_manager.analyze_job(job)
    db.session.commit()
    flash(f"AI analysis failed: {error}" if error else "Job requirements re-analysed.", "warning" if error else "success")
    return redirect(url_for("job_details", job_id=job.id))


# ---------- applications ----------

@app.route("/jobs/<int:job_id>/apply", methods=["POST"])
@login_required("candidate")
def apply(job_id):
    job = db.session.get(Job, job_id) or abort(404)
    if not job.is_open:
        flash("This job is no longer accepting applications.", "warning")
        return redirect(url_for("jobs"))
    resume = g.user.latest_resume
    if not resume or resume.extraction_status == "failed":
        flash("Please upload a readable resume before applying.", "warning")
        return redirect(url_for("dashboard"))
    if Application.query.filter_by(candidate_id=g.user.id, job_id=job.id).first():
        flash("You have already applied to this job.", "info")
        return redirect(url_for("job_details", job_id=job.id))
    application = Application(candidate_id=g.user.id, job_id=job.id, resume_id=resume.id)
    db.session.add(application)
    db.session.commit()
    if run_evaluation(application):
        flash("Application submitted and evaluated.", "success")
    else:
        flash("Application submitted. The evaluation can be retried from the application page.", "info")
    return redirect(url_for("view_application", application_id=application.id))


@app.route("/applications/<int:application_id>")
@login_required()
def view_application(application_id):
    application = get_visible_application(application_id)
    evaluation = application.latest
    return render_template("candidate_evaluation.html", application=application, evaluation=evaluation,
                           result=evaluation.load("result") if evaluation else {},
                           analysis=application.resume.load("analysis"), levels=scoring_engine.EVIDENCE_LEVELS)


@app.route("/applications/<int:application_id>/evaluate", methods=["POST"])
@login_required()
def evaluate(application_id):
    application = get_visible_application(application_id)
    if g.user.role == "candidate":
        latest = g.user.latest_resume
        if latest and latest.extraction_status != "failed":
            application.resume_id = latest.id
            db.session.commit()
            db.session.refresh(application)
    if run_evaluation(application):
        flash("Evaluation completed.", "success")
    return redirect(url_for("view_application", application_id=application.id))


def matches_skill(application, skill):
    skill = skill.lower()
    evaluation = application.latest
    if evaluation:
        result = evaluation.load("result")
        if any(skill in m.lower() for m in result.get("matching_requirements", [])):
            return True
        if any(skill in s["skill"].lower() and s["level"] >= 2 for s in result.get("skill_evidence", [])):
            return True
    return skill in (application.resume.extracted_text or "").lower()


@app.route("/jobs/<int:job_id>/applications")
@login_required("hirer")
def job_applications(job_id):
    job = get_own_job(job_id)
    sort = request.args.get("sort", "overall")
    sort = sort if sort in SORT_FIELDS else "overall"
    skill = request.args.get("skill", "").strip()
    applications = [a for a in job.applications if not skill or matches_skill(a, skill)]
    applications.sort(key=lambda a: getattr(a.latest, sort, -1) if a.latest else -1, reverse=True)
    requirements = jd_manager.job_requirements(job)
    skill_options = requirements.get("mandatory_skills", []) + requirements.get("preferred_skills", [])
    return render_template("applications.html", job=job, applications=applications, sort=sort, skill=skill,
                           skill_options=skill_options)


@app.route("/jobs/<int:job_id>/compare")
@login_required("hirer")
def compare(job_id):
    job = get_own_job(job_id)
    ids = {int(i) for i in request.args.getlist("ids") if i.isdigit()}
    applications = [a for a in job.applications if a.id in ids and a.latest]
    if len(applications) < 2:
        flash("Select at least two evaluated candidates to compare.", "warning")
        return redirect(url_for("job_applications", job_id=job.id))
    applications.sort(key=lambda a: a.latest.overall, reverse=True)
    return render_template("compare.html", job=job, rows=[(a, a.latest.load("result")) for a in applications[:4]])


# ---------- errors ----------

@app.errorhandler(413)
def too_large(error):
    flash(f"File is too large. Maximum size is {app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)} MB.", "danger")
    return redirect(url_for("dashboard"))


@app.errorhandler(403)
@app.errorhandler(404)
def not_allowed(error):
    return render_template("error.html", code=error.code, message="You do not have access to this page."
                           if error.code == 403 else "The page you are looking for does not exist."), error.code


@app.errorhandler(500)
def server_error(error):
    db.session.rollback()
    return render_template("error.html", code=500, message="Something went wrong. Please try again."), 500


if __name__ == "__main__":
    if "--check-ai" in sys.argv:
        working, message = ai.check()
        print(("OK: " if working else "FAILED: ") + message)
        sys.exit(0 if working else 1)
    if not ai.is_configured():
        print("NOTE: No AI key is set in env_app.py. The app runs, but AI analysis and evaluations are disabled.")
    if not ocr.tesseract_available():
        print("NOTE: Tesseract OCR not found. Scanned files will use the AI fallback when a key is configured.")
    port = int(os.getenv("PORT", "1114"))
    app.run(host="127.0.0.1", port=port, debug=os.getenv("FLASK_DEBUG") == "1")
