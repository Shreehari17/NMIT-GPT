import os
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

from pipeline.load_to_db import (
    fetch_all_faculty,
    fetch_all_labs,
    insert_embeddings,
    fetch_embedded_faculty_ids,
    fetch_embedded_lab_ids,
    delete_circular_embeddings
)
from pipeline.utils import make_circular_id, readable_date

load_dotenv()
model = SentenceTransformer(os.getenv("EMBEDDING_MODEL"))
def build_lab_chunks(row):
    def has_value(val):
        return val is not None and str(val).strip() != ""

    chunks = []

    lab_name = row.get("lab_name", "The lab")
    room = row.get("room_number")
    total = row.get("no_of_computers")
    brands = row.get("brand_computer_counts")
    config = row.get("configuration_summary")
    overview_parts = []

    if has_value(lab_name):
        overview_parts.append(f"The {lab_name}")

    if has_value(room):
        overview_parts.append(f"is located in Room {room}")
    else:
        overview_parts.append("is located within the institute")

    if has_value(total):
        overview_parts.append(f"and is equipped with {total} computers")

    if overview_parts:
        chunks.append((
            "01_overview",
            " ".join(overview_parts) + "."
        ))
    if isinstance(brands, dict) and brands:
        brand_text = ", ".join(
            f"{brand} systems ({count})"
            for brand, count in brands.items()
            if has_value(brand) and count
        )

        if has_value(brand_text):
            if has_value(total):
                chunks.append((
                    "02_brands",
                    f"Out of {total} computers, the lab has {brand_text}."
                ))
            else:
                chunks.append((
                    "02_brands",
                    f"The lab has a brand-wise distribution of {brand_text}."
                ))

    if has_value(config) and has_value(total):
        chunks.append((
            "03_configuration",
            f"The lab is equipped with {total} computers featuring {config}."
        ))

    return chunks


def build_faculty_chunks(row):
    def join_list(val):
        if isinstance(val, list):
            return ", ".join(v for v in val if v)
        return ""

    def has_value(val):
        return val is not None and str(val).strip() != ""

    chunks = []
    profile_parts = []

    if has_value(row.get("name")):
        profile_parts.append(row["name"])

    if has_value(row.get("designation")):
        profile_parts.append(f"is working as {row['designation']}")

    if has_value(row.get("department")):
        profile_parts.append(f"in the Department of {row['department']}")

    qualifications = join_list(row.get("educational_qualifications"))
    if has_value(qualifications):
        profile_parts.append(f"with qualifications in {qualifications}")

    experience = join_list(row.get("past_experience"))
    if has_value(experience):
        profile_parts.append(f"with professional experience in {experience}")

    if profile_parts:
        chunks.append((
            "01_profile",
            " ".join(profile_parts) + "."
        ))
    interests = join_list(row.get("areas_of_interest"))
    if has_value(interests):
        chunks.append((
            "02_interests",
            f"Areas of academic and research interest include {interests}."
        ))
    subjects = join_list(row.get("subjects_taught"))
    if has_value(subjects):
        chunks.append((
            "03_subjects",
            f"Subjects taught include {subjects}."
        ))
    achievements = join_list(row.get("achievements"))
    if has_value(achievements):
        chunks.append((
            "04_achievements",
            f"Notable achievements include {achievements}."
        ))
    research = row.get("research")
    if has_value(research):
        chunks.append((
            "05_research",
            f"Research work focuses on {research.strip()}."
        ))

    return chunks

def embed_faculty():
    faculty_rows = fetch_all_faculty()
    already_embedded = fetch_embedded_faculty_ids()
    records = []

    for row in faculty_rows:
        faculty_id = row["faculty_id"]

        if faculty_id in already_embedded:
            continue

        for idx, (chunk_type, text) in enumerate(build_faculty_chunks(row)):
            vec = model.encode(text).tolist()

            records.append({
                "source_type": "faculty_biodata",
                "source_id": faculty_id,
                "chunk_type": chunk_type,
                "chunk_index": idx,
                "raw_text": text,
                "metadata": {
                    "entity": "faculty",
                    "name": row.get("name"),
                    "department": row.get("department")
                },
                "embedding": vec
            })

    if records:
        insert_embeddings(records)
        print(f"Embedded {len(records)} faculty chunks")
    else:
        print("ℹNo new faculty chunks to embed")


def embed_labs():
    lab_rows = fetch_all_labs()
    already_embedded = fetch_embedded_lab_ids()
    records = []

    for row in lab_rows:
        if row["lab_id"] in already_embedded:
            continue

        for idx, (chunk_type, text) in enumerate(build_lab_chunks(row)):
            vec = model.encode(text).tolist()

            records.append({
                "source_type": "lab",
                "source_id": row["lab_id"],
                "chunk_type": chunk_type,
                "chunk_index": idx,
                "raw_text": text,
                "metadata": {
                    "entity": "lab",
                    "lab_name": row["lab_name"],
                    "room_number": row["room_number"]
                },
                "embedding": vec
            })

    if records:
        insert_embeddings(records)
        print(f"Embedded {len(records)} lab chunks")
    else:
        print("No new lab chunks to embed")


# ============================================================
# CIRCULARS
# ============================================================
import re

def _split_sections(full_text):
    """'## Heading' lines start a new section -> [(heading, body), ...]"""
    sections, heading, buf = [], "Overview", []

    def flush():
        body = "\n".join(buf).strip()
        if body:
            sections.append((heading, body))

    for line in full_text.splitlines():
        m = re.match(r"^\s*#{1,3}\s*(.+?)\s*$", line)
        if m:
            flush()
            heading, buf[:] = m.group(1), []
        else:
            buf.append(line)
    flush()
    return sections


def _split_long(body, limit=1200):
    if len(body) <= limit:
        return [body]
    parts, cur = [], ""
    for line in body.splitlines():
        if cur and len(cur) + len(line) + 1 > limit:
            parts.append(cur.strip())
            cur = ""
        cur += line + "\n"
    if cur.strip():
        parts.append(cur.strip())
    return parts


def build_circular_chunks(row):
    """[(chunk_type, text, section_heading), ...]

    Every chunk starts with the circular's title / number / date / audience so a line
    such as "Shorts above knee are not allowed" is embedded together with WHO it
    applies to (e.g. 'For Boy Hostellers')."""
    head = f"Circular: {row['title']}"
    if row.get("circular_no"):
        head += f" (No. {row['circular_no']})"
    if row.get("circular_date"):
        head += f", dated {readable_date(row['circular_date'])}"
    if row.get("applies_to"):
        head += f". Applies to: {row['applies_to']}"

    chunks = []
    if row.get("summary"):
        chunks.append(("00_summary", f"{head}. Summary: {row['summary']}", "Summary"))

    n = 1
    for heading, body in _split_sections(row["full_text"]):
        for piece in _split_long(body):
            slug = re.sub(r"[^a-z0-9]+", "_", heading.lower()).strip("_")[:30] or "section"
            chunks.append((f"{n:02d}_{slug}", f"{head}. Section: {heading}.\n{piece}", heading))
            n += 1
    return chunks


def embed_circular(row):
    """Chunk + embed one admin-approved circular into unified_embeddings.
    Re-uploading the same circular replaces its old vectors."""
    circular_id = make_circular_id(row.get("circular_no"), row.get("title"), row.get("circular_date"))
    chunks = build_circular_chunks(row)
    if not chunks:
        raise ValueError("Nothing to embed - the circular body is empty.")

    # encode first: if the model fails, the old version is left untouched
    vectors = model.encode([text for _, text, _ in chunks]).tolist()

    records = []
    for idx, ((chunk_type, text, heading), vec) in enumerate(zip(chunks, vectors)):
        records.append({
            "source_type": "circular",
            "source_id": circular_id,
            "chunk_type": chunk_type,
            "chunk_index": idx,
            "raw_text": text,
            "metadata": {
                "entity": "circular",
                "circular_id": circular_id,
                "circular_no": row.get("circular_no") or "",
                "title": row["title"],
                "category": row.get("category") or "general",
                "circular_date": row.get("circular_date") or None,
                "issued_by": row.get("issued_by") or "",
                "applies_to": row.get("applies_to") or "",
                "file_name": row.get("file_name") or "",
                "section": heading,
            },
            "embedding": vec,
        })

    delete_circular_embeddings(circular_id)
    insert_embeddings(records)
    print(f"Embedded {len(records)} circular chunks ({circular_id})")
    return {"circular_id": circular_id, "chunks": len(records)}