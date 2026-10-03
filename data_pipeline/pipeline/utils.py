import pandas as pd
import re
import os
def clean_date(value):
    if pd.isna(value) or value == "":
        return None
    try:
        return pd.to_datetime(value).date().isoformat()
    except Exception:
        return None


def to_array(value):
    if pd.isna(value) or value == "":
        return []
    return [v.strip() for v in str(value).split(",") if v.strip()]


def normalize_columns(df):
    df.columns = (
        df.columns.str.strip()
        .str.lower()
        .str.replace(".", "", regex=False)
    )
    return df


def extract_room_number(text):
    match = re.search(r"room\s*(\d+)", str(text).lower())
    return match.group(1) if match else None


def clean_text(text):
    if pd.isna(text):
        return ""
    text = str(text)
    replacements = {
        ";": ". ",
        ":": " ",
        "@": " at ",
        "\n": " "
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return re.sub(r"\s+", " ", text).strip()
def clean_nan(value):
    try:
        import pandas as pd
        if pd.isna(value):
            return None
    except Exception:
        pass
    return value
import re

def clean_lab_configuration(config_list):
    if not config_list:
        return None, None

    unique = list(dict.fromkeys(config_list))
    text = " ".join(unique)

    match = re.search(r"no of computers\s*(\d+)", text.lower())
    computer_count = int(match.group(1)) if match else None

    text = re.sub(r"no of computers\s*\d+\.?", "", text, flags=re.IGNORECASE)

    text = " ".join(text.split())

    return text.strip(), computer_count
def extract_faculty_name_and_shortform(text):
    if not text:
        return None, None
    match = re.search(r"\((.*?)\)", text)
    shortform = match.group(1).strip() if match else None
    name = re.sub(r"\(.*?\)", "", text).strip()
    return name, shortform
def normalize_name(name):
    if not name:
        return None
    name = name.lower()
    name = re.sub(r"[.\s]+", " ", name)  
    return name.strip()
import re

def extract_subject_code(text):
    if not text:
        return None
    m = re.search(r'\d{2}[A-Z]{2}[A-Z0-9]+', str(text))
    return m.group(0) if m else None

def is_lab(text):
    return "lab" in str(text).lower()

def get_activity(text):
    if extract_subject_code(text):
        return None
    return str(text).strip()

def parse_batches(text):
    if not text:
        return []

    text = str(text).upper()
    text = text.replace(" ", "")
    text = text.replace("|", "/")
    parts = text.split("/")
    results = []
    for part in parts:
        if "-" not in part:
            continue
        batch, values = part.split("-", 1)
        items = values.split("+")
        for item in items:
            if item:
                results.append((batch.strip(), item.strip()))
    return results
from dotenv import load_dotenv

def load_env():
    load_dotenv()
    required = ["GEMINI_API_KEY", "SUPABASE_URL", "SUPABASE_KEY"]
    for key in required:
        if not os.getenv(key):
            raise ValueError(f"Missing env variable: {key}")

def clean_json_response(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()



# ---------------- Circulars ----------------
import hashlib
from datetime import datetime

CIRCULAR_CATEGORIES = [
    "dress_code", "hostel", "exam", "academic", "fees", "event",
    "holiday", "placement", "transport", "library", "discipline", "general",
]

def normalize_date(value):
    """Return YYYY-MM-DD or None."""
    if not value:
        return None
    s = str(value).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s, flags=re.I)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %B %Y", "%d %b %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None

def readable_date(iso):
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d %B %Y").lstrip("0")
    except (TypeError, ValueError):
        return ""

def make_circular_id(circular_no, title, circular_date):
    """Deterministic id (goes in unified_embeddings.source_id, max 50 chars).
    Uploading the same circular again therefore REPLACES the old vectors."""
    key = (circular_no or "").strip().lower()
    if not key:
        key = f"{(title or '').strip().lower()}|{circular_date or ''}"
    key = re.sub(r"\s+", "", key)
    return "CIR-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]