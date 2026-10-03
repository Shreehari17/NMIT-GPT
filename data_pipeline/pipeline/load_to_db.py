import os
from supabase import create_client
from dotenv import load_dotenv
import pandas as pd
from pipeline.utils import (
    extract_faculty_name_and_shortform,
    normalize_name
)

load_dotenv()

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)


def insert_faculty(rows):
    if rows:
        supabase.table("faculty_biodata").insert(rows).execute()


def fetch_all_faculty():
    return supabase.table("faculty_biodata").select("*").execute().data


def fetch_faculty_ids():
    data = (
        supabase
        .table("faculty_biodata")
        .select("faculty_id")
        .execute()
        .data
    )
    return {row["faculty_id"] for row in data}


def fetch_embedded_faculty_ids():
    data = (
        supabase
        .table("unified_embeddings")
        .select("source_id")
        .eq("source_type", "faculty_biodata")
        .execute()
        .data
    )
    return {row["source_id"] for row in data}

def insert_labs(rows):
    if rows:
        supabase.table("lab_infrastructure").insert(rows).execute()

def fetch_all_labs():
    return supabase.table("lab_infrastructure").select("*").execute().data

def fetch_embedded_lab_ids():
    data = (
        supabase
        .table("unified_embeddings")
        .select("source_id")
        .eq("source_type", "lab")
        .execute()
        .data
    )
    return {row["source_id"] for row in data}

def insert_embeddings(rows, batch_size=100):
    for i in range(0, len(rows), batch_size):
        supabase.table("unified_embeddings").insert(
            rows[i:i + batch_size]
        ).execute()

def update_faculty_shortforms_from_subjects(filepath):
    import re
    import pandas as pd

    df = pd.read_excel(filepath)
    faculty_rows = fetch_all_faculty()

    def normalize_compact(text):
        if not text:
            return ""
        text = text.lower()
        text = re.sub(r"\b(dr|ms|mr|mrs|prof)\.?\b", "", text)
        text = re.sub(r"\(.*?\)", "", text)
        text = text.replace(".", "")
        text = re.sub(r"\s+", "", text)
        return text.strip()
    db_name_map = {
        normalize_compact(f["name"]): f["faculty_id"]
        for f in faculty_rows
    }

    for _, row in df.iterrows():
        raw_name = row.get("Faculty Name")

        if not raw_name:
            continue

        raw_name = str(raw_name).strip()

        if raw_name.lower() == "all faculty":
            continue
        match = re.search(r"\((.*?)\)", raw_name)
        shortform = match.group(1).strip() if match else None

        compact_excel_name = normalize_compact(raw_name)

        if compact_excel_name in db_name_map and shortform:
            supabase.table("faculty_biodata") \
                .update({"faculty_shortform": shortform.upper()}) \
                .eq("faculty_id", db_name_map[compact_excel_name]) \
                .execute()
        else:
            print("Not matched:", raw_name)

def insert_subjects(rows):

    faculty_data = supabase.table("faculty_biodata") \
        .select("faculty_id, faculty_shortform") \
        .execute().data

    faculty_map = {
        f["faculty_shortform"].strip().upper(): f["faculty_id"]
        for f in faculty_data
        if f.get("faculty_shortform")  
    }

    from pipeline.utils import parse_batches

    final_rows = []

    for r in rows:

        subject_name = r["subject_name"].upper()
        faculty_text = (r["faculty_shortform"] or "").upper()
        room_text = (r["room"] or "").upper()
        if "AI AND ML LAB" in subject_name:
            faculty_batches = parse_batches(faculty_text)
            lab_batches = parse_batches(room_text)
            batch_faculties = {}
            for batch, fac in faculty_batches:
                batch_faculties.setdefault(batch, []).append(fac)
            batch_labs = {}
            for batch, lab in lab_batches:
                if lab.isdigit():
                    lab = "L" + lab
                batch_labs[batch] = lab

            for batch in batch_faculties:

                lab_alias = batch_labs.get(batch)
                lab_id = None

                if lab_alias and lab_alias.startswith("L"):
                    number = lab_alias[1:]
                    if number.isdigit():
                        lab_id = "LAB" + number

                for fac in batch_faculties[batch]:

                    faculty_id = faculty_map.get(fac)
                    if not faculty_id:
                        continue

                    final_rows.append({
                        "subject_code": r["subject_code"],
                        "class": f"{r['class']}-{batch}",
                        "subject_name": r["subject_name"],
                        "subject_initials": r["subject_initials"],
                        "faculty_id": faculty_id,
                        "lab_id": lab_id,
                        "classroom": lab_alias
                    })
        else:
            faculty_text = faculty_text.replace("/", "+")
            faculty_text = faculty_text.replace(" ", "")
            faculty_list = faculty_text.split("+")
            labs_list = []

            if "L" in room_text or "LAB" in room_text:

                temp = room_text.replace("LAB", "")
                temp = temp.replace("&", "/")
                temp = temp.replace(",", "/")

                parts = [x.strip() for x in temp.split("/")]

                for p in parts:
                    if p.isdigit():
                        p = "L" + p

                    if p.startswith("L") and p[1:].isdigit():
                        labs_list.append(p)

            for i, fac in enumerate(faculty_list):

                faculty_id = faculty_map.get(fac)
                if not faculty_id:
                    continue

                lab_alias = None
                lab_id = None

                if labs_list:
                    if i < len(labs_list):
                        lab_alias = labs_list[i]
                    else:
                        lab_alias = labs_list[-1]

                    lab_id = "LAB" + lab_alias[1:]

                final_rows.append({
                    "subject_code": r["subject_code"],
                    "class": r["class"],
                    "subject_name": r["subject_name"],
                    "subject_initials": r["subject_initials"],
                    "faculty_id": faculty_id,
                    "lab_id": lab_id,
                    "classroom": lab_alias if lab_alias else room_text
                })

    unique = {}
    for row in final_rows:
        key = (row["subject_code"], row["class"], row["faculty_id"])
        unique[key] = row

    supabase.table("subjects").upsert(list(unique.values())).execute()

def insert_timetable(rows):
    final_rows = []
    for r in rows:
        class_name = r["class"]
        subject_code = r["subject_code"]
        if not r["is_lab"]:
            final_rows.append({
                "class": class_name,
                "day_of_week": r["day_of_week"],
                "time_slot": r["time_slot"],
                "subject_code": subject_code,
                "activity": r["activity"],
                "is_lab": False,
                "lab_id": None
            })

        else:
            subject_batches = supabase.table("subjects") \
                .select("class, lab_id") \
                .eq("subject_code", subject_code) \
                .like("class", f"{class_name}-%") \
                .execute().data
            unique_batches = {}

            for row in subject_batches:
                key = (row["class"], row["lab_id"])
                unique_batches[key] = row

            for batch in unique_batches.values():
                final_rows.append({
                    "class": batch["class"],  # 6A-A1
                    "day_of_week": r["day_of_week"],
                    "time_slot": r["time_slot"],
                    "subject_code": subject_code,
                    "activity": r["activity"],
                    "is_lab": True,
                    "lab_id": batch["lab_id"]
                })

    supabase.table("timetable").upsert(final_rows).execute()

from supabase import create_client
import os

def load_calendar_to_supabase(events: list[dict]):
    supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    supabase.table("academic_calendar").insert(events).execute()
    print(f"✓ Inserted {len(events)} events into Supabase")



# ============================================================
# CIRCULARS  (stored ONLY in unified_embeddings, source_type='circular')
# ============================================================
def delete_circular_embeddings(circular_id):
    supabase.table("unified_embeddings") \
        .delete() \
        .eq("source_type", "circular") \
        .eq("source_id", circular_id) \
        .execute()


def fetch_circular_summaries():
    """One entry per stored circular (chunk_index 0 carries the circular's metadata)."""
    return (
        supabase.table("unified_embeddings")
        .select("source_id, metadata, created_at")
        .eq("source_type", "circular")
        .eq("chunk_index", 0)
        .execute()
        .data
    )