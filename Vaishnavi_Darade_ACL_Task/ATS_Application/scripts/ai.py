import base64
import json
import os
import re
import time
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"
PROVIDERS = {
    "gemini": {
        "key": "GEMINI_API_KEY",
        "model": "GEMINI_MODEL",
        "default": "gemini-3.5-flash-lite",
        "fallbacks": ["gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash"],
    },
    "openai": {
        "key": "OPENAI_API_KEY",
        "model": "OPENAI_MODEL",
        "default": "gpt-5-mini",
        "fallbacks": ["gpt-5-nano", "gpt-4.1-mini", "gpt-4o-mini"],
    },
}
SKIP_TO_NEXT_MODEL = (404, 429, 500, 502, 503, 504)
_clients = {}
_working_models = {}


class AIError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def chosen_provider():
    value = os.getenv("AI_PROVIDER", "gemini").strip().lower()
    return value if value in PROVIDERS else "gemini"


def api_key(provider):
    return os.getenv(PROVIDERS[provider]["key"], "").strip()


def has_key(provider):
    key = api_key(provider)
    return bool(key) and not key.startswith("your-")


def is_configured():
    return any(has_key(p) for p in PROVIDERS)


def providers_to_try():
    primary = chosen_provider()
    order = [primary] + [p for p in PROVIDERS if p != primary]
    return [p for p in order if has_key(p)]


def candidate_models(provider):
    settings = PROVIDERS[provider]
    configured = os.getenv(settings["model"], "").strip() or settings["default"]
    models = [_working_models.get(provider), configured, settings["default"]] + settings["fallbacks"]
    return list(dict.fromkeys(m for m in models if m))


def get_client(provider):
    if provider not in _clients:
        if provider == "gemini":
            from google import genai
            _clients[provider] = genai.Client(api_key=api_key(provider))
        else:
            from openai import OpenAI
            _clients[provider] = OpenAI(api_key=api_key(provider), max_retries=0, timeout=120)
    return _clients[provider]


def load_prompt(name, **values):
    text = (PROMPT_DIR / f"{name}.txt").read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def parse_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            return json.loads(match.group(0))
        raise


def error_code(error):
    return getattr(error, "code", None) if isinstance(getattr(error, "code", None), int) else getattr(error, "status_code", None)


def friendly_error(provider, error, code):
    name = provider.title() if provider == "gemini" else "OpenAI"
    message = str(error)
    if code in (401, 403) or (code == 400 and ("API key" in message or "API_KEY" in message)):
        return f"{name} rejected the API key. Check {PROVIDERS[provider]['key']} in env_app.py."
    if code == 404:
        return f"No {name} model is available for this key. Check {PROVIDERS[provider]['model']} in env_app.py."
    if code == 429 and "quota" in message.lower():
        return f"{name} quota is used up for this key. Check billing or use the other provider."
    if code == 429:
        return f"{name} rate limit reached. Please try again in a minute."
    if code in (500, 502, 503, 504):
        return f"{name} is overloaded right now. Please try again in a minute."
    if code is None:
        return f"Could not reach {name}. Check your internet connection."
    return f"{name} request failed: {message[:200]}"


def call_gemini(model, prompt, file_bytes, mime_type, as_json):
    from google.genai import types

    contents = [prompt]
    if file_bytes:
        contents.append(types.Part.from_bytes(data=file_bytes, mime_type=mime_type))
    config = types.GenerateContentConfig(
        temperature=0.2,
        response_mime_type="application/json" if as_json else "text/plain",
    )
    response = get_client("gemini").models.generate_content(model=model, contents=contents, config=config)
    return response.text


def call_openai(model, prompt, file_bytes, mime_type, as_json):
    content = [{"type": "text", "text": prompt}]
    if file_bytes:
        data_url = f"data:{mime_type};base64,{base64.b64encode(file_bytes).decode()}"
        if mime_type.startswith("image/"):
            content.append({"type": "image_url", "image_url": {"url": data_url}})
        else:
            content.append({"type": "file", "file": {"filename": "resume.pdf", "file_data": data_url}})
    options = {"response_format": {"type": "json_object"}} if as_json else {}
    response = get_client("openai").chat.completions.create(
        model=model, messages=[{"role": "user", "content": content}], **options
    )
    return response.choices[0].message.content


def generate(provider, model, prompt, file_bytes, mime_type, as_json, retries):
    call = call_gemini if provider == "gemini" else call_openai
    last_error = None
    for attempt in range(retries):
        try:
            text = call(model, prompt, file_bytes, mime_type, as_json)
            if text:
                return text
            last_error = AIError("The AI returned an empty response.")
        except Exception as error:
            code = error_code(error)
            print(f"AI error ({provider}/{model}): {code} {str(error)[:300]}")
            last_error = AIError(friendly_error(provider, error, code), code)
            if provider == "openai" and code == 429 and "quota" in str(error).lower():
                last_error.code = "quota"
                break
            if code in (400, 401, 403, 404):
                break
        if attempt < retries - 1:
            time.sleep(3 * (attempt + 1))
    raise last_error


def ask(prompt, file_bytes=None, mime_type=None, as_json=True, retries=2):
    providers = providers_to_try()
    if not providers:
        raise AIError("No AI key is configured. Set GEMINI_API_KEY or OPENAI_API_KEY in env_app.py and restart.")
    errors = []
    for provider in providers:
        for model in candidate_models(provider):
            try:
                text = generate(provider, model, prompt, file_bytes, mime_type, as_json, retries)
            except AIError as error:
                errors.append(error)
                if error.code in SKIP_TO_NEXT_MODEL:
                    continue
                break
            _working_models[provider] = model
            if not as_json:
                return text
            try:
                return parse_json(text)
            except ValueError:
                raise AIError("The AI returned invalid JSON. Please retry.")
    raise errors[0]


def check():
    if not is_configured():
        return False, "No AI key is set. Fill GEMINI_API_KEY or OPENAI_API_KEY in env_app.py."
    try:
        result = ask('Reply with this JSON: {"ok": true}', retries=1)
        used = ", ".join(f"{p}/{m}" for p, m in _working_models.items())
        return True, f"AI is working (provider setting: {chosen_provider()}, used: {used}). Response: {result}"
    except AIError as error:
        return False, str(error)


def as_list(value, limit=20):
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        if isinstance(item, (str, int, float)) and str(item).strip():
            items.append(str(item).strip())
        elif isinstance(item, dict):
            items.append(item)
    return items[:limit]


def as_score(value):
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
