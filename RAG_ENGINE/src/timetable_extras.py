from .db import get_supabase_client
from .sql_queries import TIME_SLOT_MAP, resolve_time_slot

# 1. Full day schedule for a class
def query_full_day_timetable(class_name: str, day: str) -> list:
    supabase = get_supabase_client()

    rows = (
        supabase.table("timetable")
        .select("*")
        .like("class", f"{class_name}%")
        .eq("day_of_week", day)
        .execute()
        .data
    )
    print("RAW ROWS FROM DB:", [(r["class"], r["time_slot"], r["subject_code"]) for r in rows])
    if not rows:
        return []

    # Deduplicate batch rows (6D-D1, 6D-D2, 6D-D3) into one row per time slot
    # For lab batches, keep only one representative row and set class to the base class
    seen_slots = {}
    deduped = []
    for row in rows:
        slot = row["time_slot"]
        is_batch = row["class"] != class_name
        if is_batch:
            if slot not in seen_slots:
                row = {**row, "class": class_name}
                seen_slots[slot] = True
                deduped.append(row)
        else:
            deduped.append(row)
    rows = deduped

    SLOT_ORDER = list(TIME_SLOT_MAP.values())
    rows.sort(key=lambda r: SLOT_ORDER.index(r["time_slot"]) if r["time_slot"] in SLOT_ORDER else 99)

    subject_codes = list({
        r["subject_code"] for r in rows
        if r.get("subject_code") and r["subject_code"].strip()
    })

    subj_map_exact = {}
    subj_map_code = {}
    if subject_codes:
        subj_rows = (
            supabase.table("subjects")
            .select("subject_code, subject_name, class, faculty_id, faculty_biodata(name)")
            .in_("subject_code", subject_codes)
            .execute()
            .data
        )
        for s in subj_rows:
            subj_map_exact[(s["subject_code"], s["class"])] = s
            if s["subject_code"] not in subj_map_code:
                subj_map_code[s["subject_code"]] = s

    for row in rows:
        code = row.get("subject_code") or ""
        cls = row.get("class")
        row["subject_info"] = (
            subj_map_exact.get((code, cls))
            or subj_map_code.get(code)
            or {}
        )
    return rows
# 2. Faculty timetable all periods a faculty teaches
def query_faculty_timetable(faculty_name: str, day: str = None) -> list:
    """
    Return all timetable entries for a specific faculty member,
    optionally filtered by day.

    Joins: timetable ← subjects ← faculty_biodata by ilike name match.

    Usage in answer_query():
        params["intent"] == "timetable"
        AND params.get("faculty_name")
        (the parser should set this when user says "what does Dr. X teach on Monday")
    """
    supabase = get_supabase_client()

    # Step 1: resolve faculty_id(s)
    name_clean = faculty_name.strip()
    for honorific in ["dr.", "dr ", "prof.", "prof ", "mr.", "mr ", "ms.", "ms ", "mrs.", "mrs "]:
        name_clean = name_clean.lower().replace(honorific, "").strip()

    faculty_rows = (
        supabase.table("faculty_biodata")
        .select("faculty_id, name")
        .ilike("name", f"%{name_clean}%")
        .execute()
        .data
    )
    if not faculty_rows:
        return []

    faculty_ids = [f["faculty_id"] for f in faculty_rows]
    faculty_name_resolved = faculty_rows[0]["name"]

    # Step 2: get subject_codes taught by this faculty
    subj_query = (
        supabase.table("subjects")
        .select("subject_code, subject_name, class")
        .in_("faculty_id", faculty_ids)
    )
    subj_rows = subj_query.execute().data
    if not subj_rows:
        return []

    # Step 3: build map and collect unique (subject_code, class) pairs
    subj_map = {(s["subject_code"], s["class"]): s for s in subj_rows}
    subject_codes = list({s["subject_code"] for s in subj_rows})

    # Step 4: query timetable for those codes
    tt_query = (
        supabase.table("timetable")
        .select("*")
        .in_("subject_code", subject_codes)
    )
    if day:
        tt_query = tt_query.eq("day_of_week", day)

    tt_rows = tt_query.execute().data

    # Step 5: merge subject info + faculty name into each row
    for row in tt_rows:
        info = subj_map.get((row.get("subject_code"), row.get("class")), {})
        row["subject_info"] = {**info, "faculty_biodata": {"name": faculty_name_resolved}}

    DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    SLOT_ORDER = list(TIME_SLOT_MAP.values())
    tt_rows.sort(key=lambda r: (
        DAY_ORDER.index(r["day_of_week"]) if r["day_of_week"] in DAY_ORDER else 99,
        SLOT_ORDER.index(r["time_slot"]) if r["time_slot"] in SLOT_ORDER else 99
    ))
    return tt_rows


# 3. Free periods for a class on a day
def query_free_periods(class_name: str, day: str) -> list:
    """
    Return which time slots are FREE (no entry in timetable) for
    a class on a given day.

    Returns a list of dicts: [{"time_slot": "11:00-11:55", "period": 3}, ...]

    Usage in answer_query():
        params["intent"] == "timetable"
        AND params.get("free_period_query") == True  ← new parser flag
        AND params.get("class") AND params.get("day")
    """
    ALL_SLOTS = [
        ("1", "09:00-09:55"),
        ("2", "10:05-11:00"),
        ("3", "11:00-11:55"),
        ("4", "12:35-01:30"),
        ("5", "01:30-02:25"),
        ("6", "02:25-03:20"),
        ("7", "03:20-04:15"),
    ]

    supabase = get_supabase_client()
    rows = (
        supabase.table("timetable")
        .select("time_slot")
        .eq("class", class_name)
        .eq("day_of_week", day)
        .execute()
        .data
    )
    occupied_slots = {r["time_slot"] for r in rows}
    return [
        {"period": period, "time_slot": slot}
        for period, slot in ALL_SLOTS
        if slot not in occupied_slots
    ]


# 4. Subject schedule when & where a subject is taught
def query_subject_schedule(subject: str, class_name: str = None) -> list:
    """
    Return all timetable slots for a given subject (by name or code),
    across all classes or for a specific class.

    Usage in answer_query():
        params["intent"] == "timetable"
        AND params.get("subject")
        AND NOT params.get("faculty_name")
        (user asks "when is DBMS for 6A?" or "which periods does OS run?")
    """
    supabase = get_supabase_client()

    # Step 1: find matching subject_codes
    subj_query = supabase.table("subjects").select(
        "subject_code, subject_name, class, faculty_id, faculty_biodata(name)"
    )
    if any(c.isdigit() for c in subject):
        subj_query = subj_query.ilike("subject_code", f"%{subject}%")
    else:
        subj_query = subj_query.ilike("subject_name", f"%{subject}%")
    if class_name:
        subj_query = subj_query.eq("class", class_name)

    subj_rows = subj_query.execute().data
    if not subj_rows:
        return []

    subj_map = {(s["subject_code"], s["class"]): s for s in subj_rows}
    subject_codes = list({s["subject_code"] for s in subj_rows})

    # Step 2: get timetable rows
    tt_query = supabase.table("timetable").select("*").in_("subject_code", subject_codes)
    if class_name:
        tt_query = tt_query.eq("class", class_name)
    tt_rows = tt_query.execute().data

    # Step 3: merge
    for row in tt_rows:
        row["subject_info"] = subj_map.get((row["subject_code"], row["class"]), {})

    DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    SLOT_ORDER = list(TIME_SLOT_MAP.values())
    tt_rows.sort(key=lambda r: (
        DAY_ORDER.index(r["day_of_week"]) if r["day_of_week"] in DAY_ORDER else 99,
        SLOT_ORDER.index(r["time_slot"]) if r["time_slot"] in SLOT_ORDER else 99
    ))
    return tt_rows



# 5. What is every class doing at a given day + time?
def query_class_at_period(day: str, period: str) -> list:
    """
    Return what ALL classes are doing at a specific day + time slot.
    Useful for: "what's happening in 6th period on Friday?"

    Usage in answer_query():
        params["intent"] == "timetable"
        AND params.get("day") AND params.get("period")
        AND NOT params.get("class")              ← cross-class query
    """
    supabase = get_supabase_client()

    time_slot = resolve_time_slot(str(period).lower().strip())
    if not time_slot:
        return []

    rows = (
        supabase.table("timetable")
        .select("*")
        .eq("day_of_week", day)
        .eq("time_slot", time_slot)
        .execute()
        .data
    )
    if not rows:
        return []

    subject_codes = list({r["subject_code"] for r in rows if r.get("subject_code")})
    subj_rows = (
        supabase.table("subjects")
        .select("subject_code, subject_name, class, faculty_id, faculty_biodata(name)")
        .in_("subject_code", subject_codes)
        .execute()
        .data
    )
    subj_map = {(s["subject_code"], s["class"]): s for s in subj_rows}
    for row in rows:
        row["subject_info"] = subj_map.get((row["subject_code"], row["class"]), {})

    rows.sort(key=lambda r: r.get("class", ""))
    return rows



# 6. Richer chunk formatter (drop-in replacement for format_timetable_chunks)
def format_timetable_chunks_v2(data: list) -> list:
    chunks = []
    for row in data:
        subject = row.get("subject_info") or {}
        faculty = subject.get("faculty_biodata") or {}
        is_lab = row.get("is_lab", False)
        session_type = "Lab session" if is_lab else "Lecture"
        activity = row.get("activity") or ""

        subject_name = (
            subject.get("subject_name")
            or ((row.get("subject_code") or "").strip() or None)
            or activity
            or "unknown subject"
        )

        text = (
            f"On {row.get('day_of_week')}, "
            f"class {row.get('class')} has a {session_type} — "
            f"{subject_name} "
            f"during {row.get('time_slot')}."
        )

        if not is_lab:
            faculty_name = faculty.get("name")
            if faculty_name:
                text = text.rstrip(".") + f", taught by {faculty_name}."

        if activity and activity != subject_name:
            text = text.rstrip(".") + f" Activity: {activity}."
        if is_lab and row.get("lab_id"):
            text = text.rstrip(".") + f" Lab ID: {row['lab_id']}."

        chunks.append({
            "content": text,
            "metadata": {"source_type": "timetable"},
            "similarity": 1.0,
        })
    return chunks

def format_free_period_chunks(free_slots: list, class_name: str, day: str) -> list:
    """Format free-period results into LLM-readable chunks."""
    if not free_slots:
        return [{
            "content": f"Class {class_name} has no free periods on {day}.",
            "metadata": {"source_type": "timetable"},
            "similarity": 1.0,
        }]
    slot_list = ", ".join(
        f"Period {s['period']} ({s['time_slot']})" for s in free_slots
    )
    return [{
        "content": f"Class {class_name} has {len(free_slots)} free period(s) on {day}: {slot_list}.",
        "metadata": {"source_type": "timetable"},
        "similarity": 1.0,
    }]
