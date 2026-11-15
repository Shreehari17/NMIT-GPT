from pipeline.extract_text import (
    extract_faculty_from_excel,
    extract_labs_from_excel
)
from pipeline.load_to_db import (
    insert_faculty,
    insert_labs,
    fetch_faculty_ids
)
from pipeline.chunk_and_embed import (
    embed_faculty,
    embed_labs
)

def get_next_faculty_number(existing_ids):
    nums = [
        int(fid.replace("FAC", ""))
        for fid in existing_ids
        if fid.startswith("FAC") and fid.replace("FAC", "").isdigit()
    ]
    return max(nums) + 1 if nums else 1


if __name__ == "__main__":

    faculty_rows = extract_faculty_from_excel("data/Faculty_updated.xlsx")
    existing_ids = fetch_faculty_ids()
    next_id = get_next_faculty_number(existing_ids)

    for row in faculty_rows:
        row["faculty_id"] = f"FAC{next_id}"
        next_id += 1

    insert_faculty(faculty_rows)
    embed_faculty()


    lab_rows = extract_labs_from_excel("data/Lab_infrastructure.xlsx")

    for i, lab in enumerate(lab_rows, start=1):
        lab["lab_id"] = f"LAB{i}"

    insert_labs(lab_rows)
    embed_labs()
from pipeline.load_to_db import update_faculty_shortforms_from_subjects

update_faculty_shortforms_from_subjects(r"data\Subjects_table.xlsx")


from pipeline.extract_text import extract_subjects, extract_timetable
from pipeline.load_to_db import insert_subjects, insert_timetable

subjects = extract_subjects(r"data/Subjects_table.xlsx")
insert_subjects(subjects)

tt = extract_timetable(r"data/timetable.xlsx")
insert_timetable(tt)

from pipeline.utils import load_env
from pipeline.extract_text import extract_academic_calendar
from pipeline.load_to_db import load_calendar_to_supabase

load_env()
events = extract_academic_calendar(r"C:\Shini\Nmit GPT Project\NMIT-GPT1\data_pipeline\Academic Calendar AY 2026-27 5th & 7th Semester (UG Program BE).pdf")
print(f"✓ Extracted {len(events)} events")

load_calendar_to_supabase(events)
print("Data Loaded Successfully ✅")


# ---------------- Circulars (bulk load from a folder; the admin page does the same one at a time) ----------------
# Put circular PDFs in data_pipeline/data/circulars/ and run:  python main.py
import glob
import os
from pipeline.extract_text import extract_circular, normalize_circular
from pipeline.chunk_and_embed import embed_circular

for pdf in glob.glob("data/circulars/*.pdf"):
    row, warnings = normalize_circular(extract_circular(pdf), file_name=os.path.basename(pdf))
    for w in warnings:
        print("  WARNING:", w)
    if row["title"] and row["full_text"]:
        embed_circular(row)