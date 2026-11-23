import json
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def now():
    return datetime.utcnow()


class JsonMixin:
    def load(self, field):
        value = getattr(self, field)
        if not value:
            return {}
        try:
            return json.loads(value)
        except ValueError:
            return {}


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    headline = db.Column(db.String(200), default="")
    phone = db.Column(db.String(40), default="")
    location = db.Column(db.String(120), default="")
    company = db.Column(db.String(160), default="")
    about = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=now)

    resumes = db.relationship("Resume", backref="candidate", lazy=True, order_by="Resume.version.desc()")
    jobs = db.relationship("Job", backref="hirer", lazy=True, order_by="Job.created_at.desc()")
    applications = db.relationship("Application", backref="candidate", lazy=True, order_by="Application.created_at.desc()")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def latest_resume(self):
        return self.resumes[0] if self.resumes else None


class Job(db.Model, JsonMixin):
    id = db.Column(db.Integer, primary_key=True)
    hirer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    required_skills = db.Column(db.Text, default="")
    preferred_skills = db.Column(db.Text, default="")
    experience = db.Column(db.String(200), default="")
    languages = db.Column(db.Text, default="")
    frameworks = db.Column(db.Text, default="")
    algorithms = db.Column(db.Text, default="")
    databases = db.Column(db.Text, default="")
    cloud = db.Column(db.Text, default="")
    project_requirements = db.Column(db.Text, default="")
    qualifications = db.Column(db.Text, default="")
    is_open = db.Column(db.Boolean, default=True)
    analysis = db.Column(db.Text)
    analysis_status = db.Column(db.String(20), default="pending")
    created_at = db.Column(db.DateTime, default=now)

    applications = db.relationship("Application", backref="job", lazy=True, cascade="all, delete-orphan")

    FORM_FIELDS = ["title", "description", "required_skills", "preferred_skills", "experience", "languages",
                   "frameworks", "algorithms", "databases", "cloud", "project_requirements", "qualifications"]

    def as_text(self):
        labels = {f: f.replace("_", " ").title() for f in self.FORM_FIELDS}
        return "\n".join(f"{labels[f]}: {getattr(self, f)}" for f in self.FORM_FIELDS if getattr(self, f))


class Resume(db.Model, JsonMixin):
    id = db.Column(db.Integer, primary_key=True)
    candidate_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    version = db.Column(db.Integer, nullable=False, default=1)
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(10), nullable=False)
    extracted_text = db.Column(db.Text, default="")
    extraction_method = db.Column(db.String(40), default="")
    extraction_status = db.Column(db.String(20), default="pending")
    analysis = db.Column(db.Text)
    analysis_status = db.Column(db.String(20), default="pending")
    created_at = db.Column(db.DateTime, default=now)


class Application(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    candidate_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    job_id = db.Column(db.Integer, db.ForeignKey("job.id"), nullable=False)
    resume_id = db.Column(db.Integer, db.ForeignKey("resume.id"), nullable=False)
    status = db.Column(db.String(20), default="pending")
    error = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=now)

    resume = db.relationship("Resume")
    evaluations = db.relationship("Evaluation", backref="application", lazy=True,
                                  cascade="all, delete-orphan", order_by="Evaluation.created_at.desc()")
    __table_args__ = (db.UniqueConstraint("candidate_id", "job_id"),)

    @property
    def latest(self):
        return self.evaluations[0] if self.evaluations else None


class Evaluation(db.Model, JsonMixin):
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey("application.id"), nullable=False)
    resume_id = db.Column(db.Integer, db.ForeignKey("resume.id"), nullable=False)
    deepness = db.Column(db.Float, default=0)
    spread = db.Column(db.Float, default=0)
    evidence = db.Column(db.Float, default=0)
    overall = db.Column(db.Float, default=0)
    result = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=now)

    resume = db.relationship("Resume")
