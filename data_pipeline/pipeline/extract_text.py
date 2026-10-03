import pandas as pd
from pipeline.utils import (
    clean_date,
    to_array,
    normalize_columns,
    extract_room_number,
    clean_text,
    clean_nan
)
def extract_faculty_from_excel(filepath):
    df = pd.read_excel(filepath)
    rows = []

    for _, row in df.iterrows():
        rows.append({
            "name": clean_nan(row.get("name")),
            "designation": clean_nan(row.get("designation")),
            "department": clean_nan(row.get("department")),

            "email": to_array(row.get("email")),
            "educational_qualifications": to_array(row.get("qualification")),
            "past_experience": to_array(row.get("experience")),
            "areas_of_interest": to_array(row.get("interests")),
            "subjects_taught": to_array(row.get("subjects_taught")),
            "achievements": to_array(row.get("achievements")),

            "scholar_id": to_array(row.get("scholar_id")),
            "orcid_id": to_array(row.get("orcid_id")),
            "linkedin_id": to_array(row.get("linkedIn_id")),

            "research": clean_nan(row.get("research")),
            "joining_date": clean_date(row.get("joining_date"))
        })

    return rows
def extract_labs_from_excel(filepath):
    df = pd.read_excel(filepath)
    df = normalize_columns(df)

    labs = {}

    for _, row in df.iterrows():
        lab_name = row["lab name"]
        room_number = extract_room_number(lab_name)

        brand = str(row.get("computer brand", "")).strip()
        count = int(row.get("no of computers", 0))
        config = clean_text(row.get("total details"))

        if lab_name not in labs:
            labs[lab_name] = {
                "lab_name": lab_name,
                "room_number": room_number,
                "no_of_computers": 0,
                "brand_computer_counts": {},
                "configuration_summary": []
            }

        if brand:
            labs[lab_name]["brand_computer_counts"][brand] = (
                labs[lab_name]["brand_computer_counts"].get(brand, 0) + count
            )

        labs[lab_name]["no_of_computers"] += count

        if config:
            labs[lab_name]["configuration_summary"].append(config)

    from pipeline.utils import clean_lab_configuration

    final_labs = []

    for lab in labs.values():
        clean_config, extracted_count = clean_lab_configuration(
            lab["configuration_summary"]
        )

        if extracted_count:
            lab["no_of_computers"] = extracted_count

        lab["configuration_summary"] = clean_config
        final_labs.append(lab)

    return final_labs
from pipeline.utils import parse_batches

def extract_subjects(filepath):

    df = pd.read_excel(filepath)
    df = df.ffill()
    rows = []
    for _, r in df.iterrows():
        faculty_raw = str(r["Faculty Name"]).strip()
        if "(" in faculty_raw and ")" in faculty_raw:
            faculty_shortform = faculty_raw.split("(")[-1].replace(")", "").strip()
        else:
            faculty_shortform = faculty_raw.strip()

        rows.append({
            "subject_code": str(r["Subject Code"]).strip(),
            "class": str(r["Class"]).strip(),
            "subject_name": str(r["Subject Name"]).strip(),
            "subject_initials": str(r["Initials"]).strip(),
            "faculty_shortform": faculty_shortform.upper(),
            "room": str(r["Classroom/Lab"]).strip()
        })

    return rows

from pipeline.utils import extract_subject_code, is_lab, get_activity, parse_batches

def extract_timetable(filepath):
    import pandas as pd
    df = pd.read_excel(filepath)
    rows = []
    for _, r in df.iterrows():
        day = str(r.iloc[0]).strip()
        class_name = str(r.iloc[1]).strip()
        for col in df.columns[2:]:
            value = r[col]
            if pd.isna(value):
                continue
            value = str(value).strip()
            subject = extract_subject_code(value)
            if is_lab(value) and "-" in value:
                for batch, fac in parse_batches(value):
                    rows.append({
                        "class": class_name,
                        "day_of_week": day,
                        "time_slot": col,
                        "subject_code": subject,
                        "activity": None,
                        "is_lab": True,
                        "batch": batch,
                        "faculty_shortform": fac
                    })
            else:
                rows.append({
                    "class": class_name,
                    "day_of_week": day,
                    "time_slot": col,
                    "subject_code": subject,
                    "activity": get_activity(value),
                    "is_lab": is_lab(value),
                    "batch": None,
                    "faculty_shortform": None
                })

    return rows
from google import genai
import json, os

def extract_academic_calendar(pdf_path: str) -> list[dict]:
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    
    uploaded_file = client.files.upload(
        file=pdf_path,
        config={"mime_type": "application/pdf", "display_name": "Academic Calendar"}
    )
    
    prompt = """Extract ALL events from this academic calendar PDF.
    Return ONLY a valid JSON array. No markdown, no explanation, no code blocks.

    Each object must follow this exact structure:
    {
    "event_date": "YYYY-MM-DD",
    "event_name": "string",
    "event_type": "holiday | exam | academic | co_curricular | registration | vacation",
    "description": "string or null"
    }

    Rules:
    - Year is 2026 for July-Jan dates in this Odd Semester calendar
    - Include all holidays, exams (MSE-1, MSE-2, SEE), co-curricular days,
    compensatory working days, and important deadlines
    - event_type must be one of the 6 values listed above
    - if holiday and exam clashes mark it as holiday
    - Extract all Sundays (column name: sun) from the academic calendar and store them as event_type "holiday"
    """


    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[uploaded_file, prompt]
    )
    
    client.files.delete(name=uploaded_file.name)
    return _parse_json(response.text)

def _parse_json(raw: str) -> list[dict]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


# ============================================================
# CIRCULARS  (PDF -> Gemini -> structured dict)
# ============================================================
import re
from pipeline.utils import CIRCULAR_CATEGORIES, normalize_date

CIRCULAR_PROMPT = """You are reading an official college circular. It may be a scanned or photographed PDF
with a letterhead, a rubber stamp, handwriting and a signature.

Return ONLY one valid JSON object (no markdown, no code fences, no commentary) with exactly these keys:

{
  "circular_no": "reference number printed at the top, e.g. NMIT/Circular/2026-27/14343 (include handwritten serial parts). null if absent",
  "circular_date": "date of the circular as YYYY-MM-DD, e.g. 17th September 2026 -> 2026-09-17. null if absent",
  "title": "the subject line, without the word 'Sub:'",
  "category": "exactly one of: __CATEGORIES__",
  "issued_by": "name and designation of the signatory, e.g. Dr. H C Nagaraj, Principal. null if absent",
  "applies_to": "who must follow it, e.g. Hostellers / All students / Faculty / Final year students",
  "summary": "2-3 plain sentences describing what the circular says",
  "full_text": "the complete body text, following the rules below"
}

Rules for full_text:
- Copy the body word for word. Never paraphrase, shorten, translate or add anything.
  Keep every number, length, time, date, amount and name exactly as printed.
- Exclude: letterhead, reference number, date line, the 'Sub:' line, signature, stamp,
  the 'CC to' list, and the phone / fax / email / website footer.
- Begin with the opening paragraph (if there is one) as plain text, with no heading.
- Every heading or sub-heading in the body (for example 'General Guidelines (Applicable to All)',
  'For Girl Hostellers') becomes its own line starting with '## ' followed by the text under it.
  Remove the asterisks and trailing colons used for emphasis in headings.
- Keep numbered points on separate lines with their numbers (1., 2., ...).
  Join lines that were only wrapped by the page width.
- Put a closing sentence such as a request to cooperate under the heading '## Note'.
- If the circular has no sub-headings, write the body as plain paragraphs with no '## ' lines.
- If there is a table, write each row as one line with cells separated by ' | '.
""".replace("__CATEGORIES__", " | ".join(CIRCULAR_CATEGORIES))


def _parse_json_object(raw: str) -> dict:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw.strip())
    if isinstance(data, list):
        data = data[0] if data else {}
    return data


def extract_circular(pdf_path: str) -> dict:
    """Upload the circular PDF to Gemini and return the raw dict it produced."""
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    uploaded_file = client.files.upload(
        file=pdf_path,
        config={"mime_type": "application/pdf", "display_name": "Circular"}
    )
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[uploaded_file, CIRCULAR_PROMPT],
            config={"response_mime_type": "application/json", "temperature": 0},
        )
    finally:
        try:
            client.files.delete(name=uploaded_file.name)
        except Exception:
            pass
    return _parse_json_object(response.text)


def normalize_circular(raw: dict, file_name: str = ""):
    """Clean Gemini's output into the row the admin reviews. Returns (row, warnings)."""
    warnings = []
    title = re.sub(r"^\s*sub\s*[:\-]\s*", "", str(raw.get("title") or ""), flags=re.I).strip()
    category = str(raw.get("category") or "general").strip().lower().replace(" ", "_")
    if category not in CIRCULAR_CATEGORIES:
        warnings.append(f"Category '{category}' is not in the standard list; set to 'general'.")
        category = "general"

    circular_date = normalize_date(raw.get("circular_date"))
    if not circular_date:
        warnings.append("Circular date was not found or unreadable - enter it as YYYY-MM-DD.")
    if not str(raw.get("circular_no") or "").strip():
        warnings.append("Circular number not found. A re-upload will be matched by title + date instead.")
    if not title:
        warnings.append("Title was not found - please enter it.")

    full_text = (raw.get("full_text") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    full_text = re.sub(r"\n{3,}", "\n\n", full_text)
    if not full_text:
        warnings.append("Body text is empty - the chatbot cannot answer from this circular until it is filled in.")

    row = {
        "circular_no": str(raw.get("circular_no") or "").strip(),
        "title": title,
        "category": category,
        "circular_date": circular_date or "",
        "issued_by": str(raw.get("issued_by") or "").strip(),
        "applies_to": str(raw.get("applies_to") or "").strip(),
        "summary": str(raw.get("summary") or "").strip(),
        "full_text": full_text,
        "file_name": file_name,
    }
    return row, warnings