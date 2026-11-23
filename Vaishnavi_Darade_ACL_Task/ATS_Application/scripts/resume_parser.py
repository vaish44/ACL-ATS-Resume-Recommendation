import json
import re
from pathlib import Path

from scripts import ai, ocr

ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "html", "htm", "jpg", "jpeg", "png"}
AI_MIME_TYPES = {"pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}
FILE_SIGNATURES = {
    "pdf": [b"%PDF"],
    "docx": [b"PK\x03\x04"],
    "doc": [b"\xd0\xcf\x11\xe0", b"PK\x03\x04", b"{\\rtf"],
    "png": [b"\x89PNG"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
}
MAX_TEXT_FOR_AI = 30000


def file_extension(filename):
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def looks_valid(data, ext):
    signatures = FILE_SIGNATURES.get(ext)
    if not signatures:
        return b"<" in data[:4096] or data[:4096].decode("utf-8", "ignore").strip() != ""
    return any(data.startswith(sig) for sig in signatures)


def is_sufficient(text):
    return len(re.findall(r"[A-Za-z]{2,}", text or "")) >= 40


def clean_text(text):
    text = (text or "").replace("\x00", "").replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def read_pdf(path):
    try:
        import fitz
    except ImportError:
        from pypdf import PdfReader

        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages), "pdf-text"

    with fitz.open(path) as document:
        text = "\n".join(page.get_text("text") for page in document)
        if is_sufficient(text):
            return text, "pdf-text"
        if ocr.tesseract_available():
            ocr_text = ocr.ocr_pdf(document)
            if is_sufficient(ocr_text):
                return ocr_text, "pdf-ocr"
            text = ocr_text if len(ocr_text) > len(text) else text
    return text, ""


def read_docx(path):
    from docx import Document

    document = Document(path)
    lines = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = list(dict.fromkeys(c.text.strip() for c in row.cells if c.text.strip()))
            if cells:
                lines.append(" | ".join(cells))
    return "\n".join(lines), "docx"


def read_doc(path):
    data = Path(path).read_bytes()
    if data.startswith(b"PK"):
        return read_docx(path)
    if data.startswith(b"{\\rtf"):
        text = re.sub(r"\\[a-z]+-?\d* ?|[{}]", "", data.decode("latin-1"))
        return text, "doc-rtf"
    try:
        import olefile

        with olefile.OleFileIO(path) as ole:
            data = ole.openstream("WordDocument").read()
    except Exception:
        pass
    candidates = [
        " ".join(re.findall(r"[\x20-\x7e\u00a0-\u024f\n\r\t]{4,}", data.decode("utf-16le", "ignore"))),
        " ".join(re.findall(r"[\x20-\x7e\n\r\t]{4,}", data.decode("latin-1", "ignore"))),
    ]
    best = max(candidates, key=lambda t: len(re.findall(r"[A-Za-z]{3,}", t)))
    return best.replace("\r", "\n"), "doc-binary"


def read_html(path):
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(Path(path).read_bytes(), "html.parser")
    for tag in soup(["script", "style", "noscript", "head"]):
        tag.decompose()
    for tag in soup.find_all(["br", "p", "div", "li", "h1", "h2", "h3", "h4", "tr"]):
        tag.insert_before("\n")
    return soup.get_text(" "), "html"


def read_image(path):
    if not ocr.tesseract_available():
        return "", ""
    return ocr.ocr_image_bytes(Path(path).read_bytes()), "image-ocr"


def extract_text(path, ext):
    readers = {"pdf": read_pdf, "docx": read_docx, "doc": read_doc, "html": read_html, "htm": read_html,
               "jpg": read_image, "jpeg": read_image, "png": read_image}
    note = ""
    try:
        text, method = readers[ext](path)
    except Exception as error:
        text, method, note = "", "", f"Local extraction error: {error}"
    text = clean_text(text)
    if is_sufficient(text):
        return text, method, "success", note

    if ext in AI_MIME_TYPES and ai.is_configured():
        try:
            ai_text = clean_text(ocr.ai_extract(Path(path).read_bytes(), AI_MIME_TYPES[ext]))
            if is_sufficient(ai_text):
                return ai_text, "ai", "success", note
        except ai.AIError as error:
            note = str(error)

    if not note:
        if ext in ("jpg", "jpeg", "png") and not ocr.tesseract_available() and not ai.is_configured():
            note = "Tesseract OCR is not installed and no AI key is configured, so images cannot be read."
        elif ext == "pdf" and not ai.is_configured():
            note = "This looks like a scanned PDF. Install Tesseract or add an AI key to read it."
        else:
            note = "Very little text could be extracted from this file."
    status = "partial" if text else "failed"
    return text, method or "none", status, note


def save_extracted(folder, stored_name, text):
    Path(folder).mkdir(parents=True, exist_ok=True)
    (Path(folder) / f"{stored_name}.txt").write_text(text, encoding="utf-8")


def clean_analysis(data):
    if not isinstance(data, dict):
        raise ai.AIError("Resume analysis was not valid JSON.")
    projects = []
    for project in ai.as_list(data.get("projects"), 15):
        if isinstance(project, dict) and project.get("name"):
            projects.append({
                "name": str(project.get("name"))[:150],
                "type": str(project.get("type", "")),
                "description": str(project.get("description", ""))[:800],
                "technologies": ai.as_list(project.get("technologies"), 15),
                "dataset": str(project.get("dataset", "")),
                "implementation_details": ai.as_list(project.get("implementation_details"), 10),
                "results": str(project.get("results", "")),
            })
    return {
        "name": str(data.get("name", "")),
        "summary": str(data.get("summary", ""))[:1000],
        "total_experience_years": data.get("total_experience_years"),
        "skills": ai.as_list(data.get("skills"), 60),
        "experience": [e for e in ai.as_list(data.get("experience"), 10) if isinstance(e, dict)],
        "projects": projects,
        "education": ai.as_list(data.get("education"), 6),
        "certifications": ai.as_list(data.get("certifications"), 15),
        "achievements": ai.as_list(data.get("achievements"), 15),
    }


def analyze_resume(resume):
    if resume.analysis_status == "done" and resume.analysis:
        return json.loads(resume.analysis)
    if not resume.extracted_text:
        raise ai.AIError("No text could be extracted from this resume, so it cannot be analysed.")
    prompt = ai.load_prompt("resume_analysis", RESUME=resume.extracted_text[:MAX_TEXT_FOR_AI])
    analysis = clean_analysis(ai.ask(prompt))
    resume.analysis = json.dumps(analysis)
    resume.analysis_status = "done"
    return analysis
