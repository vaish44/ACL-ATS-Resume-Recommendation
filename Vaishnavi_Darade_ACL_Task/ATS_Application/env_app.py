# App settings. Edit the values below and restart the app.

# Which AI to use: "gemini" or "openai".
# If both keys are filled in, the other provider is used automatically when the chosen one is down.
AI_PROVIDER = "gemini"

GEMINI_API_KEY = ""
GEMINI_MODEL = "gemini-3.5-flash-lite"

OPENAI_API_KEY = ""
OPENAI_MODEL = "gpt-5-mini"

SECRET_KEY = ""
DATABASE_URL = "sqlite:///data/recruitment.db"
UPLOAD_FOLDER = "data/resumes"
MAX_CONTENT_LENGTH = "10485760"
TESSERACT_CMD = ""
