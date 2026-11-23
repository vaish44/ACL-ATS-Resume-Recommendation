import io
import os
import shutil

from PIL import Image, ImageOps

from scripts import ai

TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/opt/homebrew/bin/tesseract",
]


def find_tesseract():
    custom = os.getenv("TESSERACT_CMD", "")
    if custom and os.path.exists(custom):
        return custom
    return shutil.which("tesseract") or next((p for p in TESSERACT_PATHS if os.path.exists(p)), None)


def tesseract_available():
    return find_tesseract() is not None


def prepare_image(image):
    image = ImageOps.exif_transpose(image).convert("L")
    if image.width < 1500:
        scale = 1500 / image.width
        image = image.resize((int(image.width * scale), int(image.height * scale)))
    image = ImageOps.autocontrast(image)
    return image.point(lambda p: 255 if p > 160 else 0)


def ocr_image(image):
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = find_tesseract()
    return pytesseract.image_to_string(prepare_image(image), config="--psm 6")


def ocr_image_bytes(data):
    return ocr_image(Image.open(io.BytesIO(data)))


def ocr_pdf(document, max_pages=10):
    pages = []
    for page in list(document)[:max_pages]:
        pixmap = page.get_pixmap(dpi=250)
        image = Image.open(io.BytesIO(pixmap.tobytes("png")))
        pages.append(ocr_image(image))
    return "\n\n".join(pages)


def ai_extract(data, mime_type):
    prompt = (
        "Transcribe all text from this resume document exactly as written. Preserve headings, "
        "bullet points, sections (experience, projects, skills, education, certifications, achievements) "
        "and line breaks. Do not summarize, add or invent anything. Return only the plain text."
    )
    return ai.ask(prompt, file_bytes=data, mime_type=mime_type, as_json=False)
