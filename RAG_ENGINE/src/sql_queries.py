from .db import get_supabase_client
import calendar as cal_module
from collections import defaultdict
import re
TIME_SLOT_MAP = {
    "1": "09:00-09:55",
    "2": "10:05-11:00",
    "3": "11:00-11:55",
    "4": "12:35-01:30",
    "5": "01:30-02:25",
    "6": "02:25-03:20",
    "7": "03:20-04:15",

    "9am": "09:00-09:55",
    "9:00": "09:00-09:55",
    "10am": "10:05-11:00",
    "10:05": "10:05-11:00",
    "11am": "11:00-11:55",
    "11:00": "11:00-11:55",
    "12pm": "12:35-01:30",
    "12:35": "12:35-01:30",
    "1pm": "01:30-02:25",
    "1:30": "01:30-02:25",
    "2pm": "02:25-03:20",
    "2:25": "02:25-03:20",
    "3pm": "03:20-04:15",
    "3:20": "03:20-04:15",
    "2:30": "02:25-03:20",
    "2:30pm": "02:25-03:20",
    "14:30": "02:25-03:20",
    "3:30": "03:20-04:15",
    "3:30pm": "03:20-04:15",
    "11:30": "11:00-11:55",
    "12:30": "12:35-01:30",
    "1:30": "01:30-02:25",
    "1:30pm": "01:30-02:25",
    "11:35": "11:00-11:55",
    "11:40": "11:00-11:55",
    "11:45": "11:00-11:55",
    "11:50": "11:00-11:55",
    "11:15": "11:00-11:55",
    "11:20": "11:00-11:55",
    "12:00": "11:00-11:55",
    "12:05": "11:00-11:55",
    "12:10": "11:00-11:55",
    "12:15": "11:00-11:55",
    "12:20": "11:00-11:55",
    "12:25": "11:00-11:55",
    "9:05":  "09:00-09:55",
    "9:10":  "09:00-09:55",
    "9:15":  "09:00-09:55",
    "9:20":  "09:00-09:55",
    "9:30":  "09:00-09:55",
    "9:40":  "09:00-09:55",
    "9:45":  "09:00-09:55",
    "9:50":  "09:00-09:55",
    "10:10": "10:05-11:00",
    "10:15": "10:05-11:00",
    "10:20": "10:05-11:00",
    "10:30": "10:05-11:00",
    "10:40": "10:05-11:00",
    "10:45": "10:05-11:00",
    "10:50": "10:05-11:00",
    "10:55": "10:05-11:00",
    "12:40": "12:35-01:30",
    "12:45": "12:35-01:30",
    "12:50": "12:35-01:30",
    "12:55": "12:35-01:30",
    "1:00":  "12:35-01:30",
    "1:05":  "12:35-01:30",
    "1:10":  "12:35-01:30",
    "1:15":  "12:35-01:30",
    "1:20":  "12:35-01:30",
    "1:35":  "01:30-02:25",
    "1:40":  "01:30-02:25",
    "1:45":  "01:30-02:25",
    "1:50":  "01:30-02:25",
    "2:00":  "01:30-02:25",
    "2:05":  "01:30-02:25",
    "2:10":  "01:30-02:25",
    "2:15":  "01:30-02:25",
    "2:20":  "01:30-02:25",
    "2:30":  "02:25-03:20",
    "2:35":  "02:25-03:20",
    "2:40":  "02:25-03:20",
    "2:45":  "02:25-03:20",
    "2:50":  "02:25-03:20",
    "2:55":  "02:25-03:20",
    "3:00":  "02:25-03:20",
    "3:05":  "02:25-03:20",
    "3:10":  "02:25-03:20",
    "3:15":  "02:25-03:20",
    "3:25":  "03:20-04:15",
    "3:30":  "03:20-04:15",
    "3:35":  "03:20-04:15",
    "3:40":  "03:20-04:15",
    "3:45":  "03:20-04:15",
    "3:50":  "03:20-04:15",
    "3:55":  "03:20-04:15",
    "4:00":  "03:20-04:15",
    "4:05":  "03:20-04:15",
    "4:10":  "03:20-04:15",
}
EVENT_TYPE_MAP = {
    "semester end": "exam",
    "sem end": "exam",
    "see": "exam",
    "mid sem": "exam",
    "midsem": "exam",
    "mse": "exam",
    "midterm": "exam",
    "final exam": "exam",
    "backlog": "registration",
    "sem registration": "registration",
    "compensatory": "compensatory working day",
    "extra working": "compensatory working day",
    "co_curricular": "co_curricular",
    "fest": "co_curricular",
    "cultural": "co_curricular",
}
def normalize_event_type(event_type: str) -> str:
    if not event_type:
        return None
    lower = event_type.lower().strip()
    for key, val in EVENT_TYPE_MAP.items():
        if key in lower:
            return val
    return lower

def query_timetable(params: dict) -> list:
    supabase = get_supabase_client()

    query = supabase.table("timetable").select("*")

    if params.get("class"):
        query = query.eq("class", params["class"])
    if params.get("day"):
        query = query.eq("day_of_week", params["day"])
    if params.get("period"):
        raw = str(params["period"]).lower().strip()
        time_slot = TIME_SLOT_MAP.get(raw)
        if time_slot:
            query = query.eq("time_slot", time_slot)

    timetable_rows = query.execute().data
    
    if not timetable_rows:
        return []

    # STEP 2: get all subject codes from results
    subject_codes = list({row["subject_code"] for row in timetable_rows if row.get("subject_code")})

    # STEP 3: fetch matching subjects + faculty
    subjects_rows = supabase.table("subjects") \
        .select("subject_code, subject_name, class, faculty_id, faculty_biodata(name)") \
        .in_("subject_code", subject_codes) \
        .execute().data

    # STEP 4: build lookup keyed by (subject_code, class) so that the same
    subject_map = {(row["subject_code"], row["class"]): row for row in subjects_rows}

    # STEP 5: merge timetable + subject info
    for row in timetable_rows:
        key = (row.get("subject_code"), row.get("class"))
        row["subject_info"] = subject_map.get(key, {})

    return timetable_rows


def query_subjects(params: dict) -> list:
    """Fetch subject/faculty data using exact SQL filters."""
    supabase = get_supabase_client()
    if params.get("batch"):
        # Step 1: get subject_code from subjects table
        subj = supabase.table("subjects") \
            .select("subject_code, subject_name") \
            .ilike("subject_name", f"%{params['subject']}%") \
            .limit(1).execute().data
        
        if not subj:
            return []
        
        subject_code = subj[0]["subject_code"]
        subject_name = subj[0]["subject_name"]

        # Step 2: get lab from timetable using batch (stored as class) + subject_code
        result = supabase.table("timetable") \
            .select("class, subject_code, lab_infrastructure(lab_name, room_number)") \
            .eq("class", params["batch"]) \
            .eq("subject_code", subject_code) \
            .execute().data
        
        if not result:
            return []

        lab = result[0].get("lab_infrastructure") or {}
        lab_name = lab.get("lab_name", "unknown")
        room = lab.get("room_number", "unknown")

        # Return a pre-formatted chunk so LLM answers correctly
        return [{
            "__direct_chunk__": True,
            "content": f"The lab for {subject_name} ({subject_code}) for batch {params['batch']} is {lab_name}, located in room {room}.",
            "metadata": {"source_type": "subjects"},
            "similarity": 1.0
        }]

    query = supabase.table("subjects") \
        .select("""
            subject_name,
            subject_code,
            class,
            faculty_biodata(name),
            lab_infrastructure(lab_name, room_number)
        """)

    if params.get("subject"):
        subject = params["subject"]
        if any(char.isdigit() for char in subject):
            query = query.ilike("subject_code", f"%{subject}%")
        else:
            query = query.ilike("subject_name", f"%{subject}%")

    if params.get("class"):
        if params["class"] == "6":
            query = query.like("class", "6%")
        elif params.get("subject") and "lab" in params.get("subject", "").lower():
            query = query.like("class", f"{params['class']}%")
        else:
            query = query.eq("class", params["class"])

    if params.get("faculty_name"):
        supabase2 = get_supabase_client()
        faculty_rows = supabase2.table("faculty_biodata") \
            .select("faculty_id") \
            .ilike("name", f"%{params['faculty_name']}%") \
            .execute().data
        if faculty_rows:
            faculty_ids = [r["faculty_id"] for r in faculty_rows]
            query = query.in_("faculty_id", faculty_ids)

    result = query.execute()
    if not params.get("subject") and not params.get("faculty_name"):
        if not params.get("class") or params.get("class") == "6":
            seen = set()
            deduped = []
            for row in result.data:
                if row["subject_name"] not in seen:
                    seen.add(row["subject_name"])
                    deduped.append(row)
            return deduped
    
    return result.data

def query_calendar(params: dict) -> list:
    supabase = get_supabase_client()

    query = supabase.table("academic_calendar").select("*")

    if params.get("event_name"):
        query = query.ilike("event_name", f"%{params['event_name']}%")
        query = query.order("event_date", desc=False)
        return query.execute().data

    if params.get("date"):
        target_date = params["date"]

        exact_rows = supabase.table("academic_calendar").select("*") \
            .eq("event_date", target_date).execute().data

        all_rows = supabase.table("academic_calendar").select("*") \
            .lte("event_date", target_date).execute().data

        started = {}
        for row in all_rows:
            name = row.get("event_name", "")
            if re.search(r'\bStarts?\b', name, re.IGNORECASE):
                base = re.sub(r'\s*(Starts?)$', '', name, flags=re.IGNORECASE).strip()
                started[base] = row

        spanning_rows = []
        if started:
            end_rows = supabase.table("academic_calendar").select("*") \
                .gte("event_date", target_date).execute().data

            ended_names = {}
            for row in end_rows:
                name = row.get("event_name", "")
                if re.search(r'\bEnds?\b', name, re.IGNORECASE):
                    base = re.sub(r'\s*(Ends?)$', '', name, flags=re.IGNORECASE).strip()
                    ended_names[base] = row 

            for base_name, start_row in started.items():
                if base_name in ended_names:
                    spanning_rows.append(start_row)
                    spanning_rows.append(ended_names[base_name])  

        seen = set()
        combined = []
        for row in exact_rows + spanning_rows:
            if row["event_name"] not in seen:
                seen.add(row["event_name"])
                combined.append(row)

        return combined

    elif params.get("month"):
        month = params["month"]
        year, mon = month.split("-")
        last_day = cal_module.monthrange(int(year), int(mon))[1]
        query = query.gte("event_date", f"{month}-01").lte("event_date", f"{month}-{last_day:02d}")
        if params.get("event_type"):
            normalized = normalize_event_type(params["event_type"])
            if normalized:
                query = query.ilike("event_type", f"%{normalized}%")

    elif params.get("date_from") and params.get("date_to"):
        query = query.gte("event_date", params["date_from"]).lte("event_date", params["date_to"])
        if params.get("event_type"):
            normalized = normalize_event_type(params["event_type"])
            if normalized:
                query = query.ilike("event_type", f"%{normalized}%")

    query = query.order("event_date", desc=False)
    return query.execute().data

def format_calendar_chunks(data: list, params: dict = None) -> list:
    if not data:
        return []

    chunks = []

    if params and params.get("is_college_open_query") and params.get("date"):
        date = params["date"]
        holidays = [r for r in data if "holiday" in r.get("event_type", "").lower()]
        comp_days = [r for r in data if "compensatory" in r.get("event_type", "").lower()]

        if holidays:
            names = ", ".join(r.get("event_name", "") for r in holidays)
            text = f"On {date}, college is CLOSED. It is a holiday: {names}."
        elif comp_days:
            names = ", ".join(r.get("event_name", "") for r in comp_days)
            text = f"On {date}, college is OPEN. It is a compensatory working day: {names}."
        else:
            names = ", ".join(r.get("event_name", "") for r in data)
            text = f"On {date}, there is an event: {names}. College is open"

        chunks.append({
            "content": text,
            "metadata": {"source_type": "calendar"},
            "similarity": 1.0
        })
        return chunks

    def normalize_event_group(name: str) -> str:
        cleaned = re.sub(r'\s*(Starts?)$', '', name, flags=re.IGNORECASE).strip()
        return cleaned

    grouped = defaultdict(list)
    for row in data:
        key = normalize_event_group(row.get("event_name", "Unknown"))
        grouped[key].append(row)

    for event_name, rows in grouped.items():
        rows_sorted = sorted(rows, key=lambda r: r.get("event_date", ""))
        dates = [r.get("event_date") for r in rows_sorted]
        event_type = rows_sorted[0].get("event_type", "")
        description = rows_sorted[0].get("description", "")

        original_names = [r.get("event_name", "") for r in rows_sorted]
        has_start = any(re.search(r'\bStarts?\b', n, re.IGNORECASE) for n in original_names)
        has_end = any(re.search(r'\bEnds?\b', n, re.IGNORECASE) for n in original_names)

        if len(dates) == 1:
            if has_end:
                text = f"'{event_name}' ({event_type}) ends on {dates[0]}."
            elif event_type == "vacation" or has_start:
                text = f"'{event_name}' ({event_type}) starts on {dates[0]}."
            else:
                text = f"'{event_name}' ({event_type}) is on {dates[0]}."
        else:
            if "holiday" in event_type.lower():
                for date in dates:
                    individual_text = f"'{event_name}' ({event_type}) is on {date}. College is CLOSED on these days."
                    chunks.append({
                        "content": individual_text,
                        "metadata": {"source_type": "calendar"},
                        "similarity": 1.0
                    })
                continue  
            else:
                text = f"'{event_name}' ({event_type}) starts on {dates[0]} and ends on {dates[-1]}."

        if description:
            text += f" Details: {description}."

        if "holiday" in event_type.lower():
            text += " College is CLOSED on these days."
        elif "compensatory" in event_type.lower():
            text += " College is OPEN on these days."
        elif "exam" in event_type.lower():
            text += " Exams are scheduled during this period."
        elif "registration" in event_type.lower():
            text += " Registration is scheduled during this period."

        chunks.append({
            "content": text,
            "metadata": {"source_type": "calendar"},
            "similarity": 1.0
        })

    return chunks


from datetime import date, timedelta
import re


def retrieve_chunks(params: dict) -> list:
    supabase    = get_supabase_client()
    query_type  = params.get("query_type")
    event_name  = (params.get("event_name")  or "").strip()
    event_name2 = (params.get("event_name_2") or "").strip()

    # LOW-LEVEL HELPERS
    def make_chunk(content: str) -> dict:
        return {"content": content, "metadata": {"source_type": "calendar"}, "similarity": 1.0}

    def iter_dates(start_str: str, end_str: str):
        """Yield every date from start to end inclusive."""
        cur = date.fromisoformat(start_str)
        end = date.fromisoformat(end_str)
        while cur <= end:
            yield cur
            cur += timedelta(days=1)

    def fetch_all_rows() -> list:
        return (
            supabase.table("academic_calendar")
            .select("*")
            .order("event_date", desc=False)
            .execute()
            .data
        )

    def fetch_by_name(name: str) -> list:
        return (
            supabase.table("academic_calendar")
            .select("*")
            .ilike("event_name", f"%{name}%")
            .order("event_date", desc=False)
            .execute()
            .data
        )

    def fetch_by_type(event_type: str, date_from: str = None, date_to: str = None) -> list:
        q = supabase.table("academic_calendar").select("*").eq("event_type", event_type)
        if date_from:
            q = q.gte("event_date", date_from)
        if date_to:
            q = q.lte("event_date", date_to)
        return q.order("event_date", desc=False).execute().data

    def fetch_in_range(date_from: str, date_to: str) -> list:
        return (
            supabase.table("academic_calendar")
            .select("*")
            .gte("event_date", date_from)
            .lte("event_date", date_to)
            .order("event_date", desc=False)
            .execute()
            .data
        )

    def boundary_dates(rows: list) -> tuple:
        """
        Return (start_date, end_date) for a list of rows.
        Prefers explicit 'Starts'/'Ends' marker rows; falls back to first/last date.
        """
        if not rows:
            return None, None
        start_rows = [r for r in rows if re.search(r"\bStarts?\b", r.get("event_name", ""), re.IGNORECASE)]
        end_rows   = [r for r in rows if re.search(r"\bEnds?\b",   r.get("event_name", ""), re.IGNORECASE)]
        start = start_rows[0]["event_date"] if start_rows else rows[0]["event_date"]
        end   = end_rows[-1]["event_date"]  if end_rows   else rows[-1]["event_date"]
        return start, end

    def non_teaching_dates_in_range(date_from: str, date_to: str) -> set:
        """
        Return set of ISO date strings that are non-teaching within [date_from, date_to].
        Excludes: holidays, co_curricular days, vacation, registration, exam days.
        Does NOT include Sundays (handled separately via weekday check).
        Does NOT exclude 'academic' rows (compensatory working days count as teaching).
        """
        rows = fetch_in_range(date_from, date_to)
        return {
    r["event_date"] for r in rows
    if r["event_type"] in ("holiday", "exam", "vacation", "co_curricular")
}

    def count_working_days(start_str: str, end_str: str) -> int:
        """
        Count days in [start, end] that are NOT Sundays and NOT non-teaching days.
        Non-teaching = holiday, co_curricular, vacation, registration, exam.
        """
        print(non_teaching_dates_in_range(start_str, end_str))
        excluded = non_teaching_dates_in_range(start_str, end_str)
        count = 0
        for d in iter_dates(start_str, end_str):
            if d.weekday() != 6 and d.isoformat() not in excluded:
                count += 1
        
        return count
    def count_exam_days(start_str: str, end_str: str) -> int:
        """For exam duration: exclude Sundays and holidays only."""
        rows = fetch_in_range(start_str, end_str)
        holiday_dates = {
            r["event_date"] for r in rows
            if r["event_type"] == "holiday"
        }
        return sum(
            1 for d in iter_dates(start_str, end_str)
            if d.weekday() != 6 and d.isoformat() not in holiday_dates
        )
    def exam_actual_rows(rows: list) -> list:
        """Remove Start/End marker rows — keep only actual exam day rows."""
        return [
            r for r in rows
            if not re.search(r"\b(Starts?|Ends?)\b", r.get("event_name", ""), re.IGNORECASE)
        ]

    def infer_end_from_next_event(start_date: str, current_event_type: str = None) -> str:
        """
        Infer the end date of an event that has no 'Ends' marker.
        Looks for the next event in the DB that is a DIFFERENT event (not same name/type),
        and returns the day before it as the inferred end date.

        For SEE Practicals (exam type): end = day before SEE Theory Starts.
        For Summer Vacations (vacation type): end = day before next registration/academic event.
        """
        all_rows = fetch_all_rows()
        later_rows = [r for r in all_rows if r["event_date"] > start_date]

        if current_event_type == "exam":
            for r in later_rows:
                if r["event_type"] == "exam" and re.search(r"\bStarts?\b", r.get("event_name", ""), re.IGNORECASE):
                    return (date.fromisoformat(r["event_date"]) - timedelta(days=1)).isoformat()

        if current_event_type == "vacation":
            skip_types = {"holiday"}
            for r in later_rows:
                if r["event_type"] not in skip_types:
                    return (date.fromisoformat(r["event_date"]) - timedelta(days=1)).isoformat()

        later_dates = sorted({r["event_date"] for r in later_rows})
        if not later_dates:
            return start_date
        return (date.fromisoformat(later_dates[0]) - timedelta(days=1)).isoformat()
        
# SUMMER VACATION DURATION special case
    if query_type == "duration" and event_name == "Summer Vacations":
        vacation_rows = fetch_by_name("Summer Vacations")
        reg_rows = fetch_by_name("Registration Odd (5th & 7th) Semester")

        if not vacation_rows:
            return [make_chunk("No data found for Summer Vacations.")]
        if not reg_rows:
            return [make_chunk("No data found for Odd Semester Registration.")]

        start_date = vacation_rows[0]["event_date"]
        end_date = (date.fromisoformat(reg_rows[0]["event_date"]) - timedelta(days=1)).isoformat()

        start_d = date.fromisoformat(start_date)
        end_d = date.fromisoformat(end_date)
        duration = (end_d - start_d).days + 1

        return [make_chunk(
            f"Summer Vacations start on {start_date} and end on {end_date}, "
            f"spanning {duration} days."
        )]
    # DURATION of a single event
    if query_type == "duration" and event_name:
        clean = re.sub(r"\s*(Starts?|Ends?)$", "", event_name, flags=re.IGNORECASE).strip()
        rows  = fetch_by_name(clean)

        if not rows:
            return [make_chunk(f"No calendar data found for '{clean}'.")]

        start_date, end_date = boundary_dates(rows)
        actual_rows = exam_actual_rows(rows)

        if actual_rows:
            duration = len(actual_rows)
            return [make_chunk(
                f"'{clean}' runs from {start_date} to {end_date}, spanning {duration} days."
            )]

        row_event_type = rows[0].get("event_type") if rows else None
        is_vacation    = any(r.get("event_type") == "vacation" for r in rows)

        if start_date == end_date:
            end_date = infer_end_from_next_event(start_date, current_event_type=row_event_type)

        if is_vacation:
            start_d  = date.fromisoformat(start_date)
            end_d    = date.fromisoformat(end_date)
            duration = (end_d - start_d).days + 1
        elif row_event_type == "exam":
            duration = count_exam_days(start_date, end_date)
        else:
            duration = count_working_days(start_date, end_date)

        return [make_chunk(
            f"'{clean}' runs from {start_date} to {end_date}, spanning {duration} days."
        )]

    # DURATION_EACH "how many days is MSE-1 and MSE-2?"
    if query_type == "duration_each" and event_name and event_name2:
        chunks = []
        for name in (event_name, event_name2):
            clean = re.sub(r"\s*(Starts?|Ends?)$", "", name, flags=re.IGNORECASE).strip()
            rows  = fetch_by_name(clean)
            if not rows:
                chunks.append(make_chunk(f"No data found for '{clean}'."))
                continue
            start_date, end_date = boundary_dates(rows)
            actual_rows = exam_actual_rows(rows)
            if actual_rows:
                duration = len(actual_rows)
            else:
                row_event_type = rows[0].get("event_type") if rows else None
                if start_date == end_date:
                    end_date = infer_end_from_next_event(start_date, current_event_type=row_event_type)
                is_vac = any(r.get("event_type") == "vacation" for r in rows)
                if is_vac:
                    duration = (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days + 1
                elif row_event_type == "exam":
                    duration = count_exam_days(start_date, end_date)
                else:
                    duration = count_working_days(start_date, end_date)
            chunks.append(make_chunk(
                f"'{clean}' runs from {start_date} to {end_date}, spanning {duration} days."
            ))
        return chunks

    # GAP / OVERLAP between two events
    if query_type in ("gap", "overlap") and event_name and event_name2:
        rows1 = fetch_by_name(event_name)
        rows2 = fetch_by_name(event_name2)

        if not rows1:
            return [make_chunk(f"No calendar data found for '{event_name}'. Cannot compute gap.")]
        if not rows2:
            return [make_chunk(f"No calendar data found for '{event_name2}'. Cannot compute gap.")]

        _,      end1   = boundary_dates(rows1)
        start2, _      = boundary_dates(rows2)

        chunks = [
            make_chunk(f"'{event_name}' ends on {end1}."),
            make_chunk(f"'{event_name2}' starts on {start2}."),
        ]

        gap_start = (date.fromisoformat(end1) + timedelta(days=1)).isoformat()
        gap_end   = (date.fromisoformat(start2) - timedelta(days=1)).isoformat()

        if gap_start > gap_end:
            chunks.append(make_chunk(
                f"'{event_name}' and '{event_name2}' overlap or are back-to-back — gap is 0 days."
            ))
        else:
            gap_days = count_working_days(gap_start, gap_end)
            chunks.append(make_chunk(
                f"The gap between '{event_name}' and '{event_name2}' is {gap_days} working days "
                f"(excluding Sundays and holidays)."
            ))
        return chunks

    # COUNT queries all derived from DB
    if query_type == "count":
        event_type_param = (params.get("event_type") or "").lower().strip()

        if "teaching" in event_type_param:
            coc_rows = fetch_by_name("Commencement of Classes")
            lwd_rows = fetch_by_name("Last Working Day")

            if not coc_rows or not lwd_rows:
                return [make_chunk(
                    "Cannot determine teaching days: 'Commencement of Classes' "
                    "or 'Last Working Day' not found in the calendar."
                )]

            sem_start = coc_rows[0]["event_date"]
            sem_end   = lwd_rows[-1]["event_date"]

            all_in_range = fetch_in_range(sem_start, sem_end)
            non_teaching_dates = {
                r["event_date"] for r in all_in_range
                if r["event_type"] in ("holiday", "exam", "vacation","co_curricular")
            }

            count = sum(
                1 for d in iter_dates(sem_start, sem_end)
                if d.isoformat() not in non_teaching_dates
            )
            return [make_chunk(
                f"There are {count} teaching days in the even semester "
                f"(from {sem_start} to {sem_end}, inclusive)."
            )]

        # Saturday holidays
        if "saturday" in event_type_param:
            rows  = fetch_by_name("saturday")
            count = len(rows)
            dates = ", ".join(r["event_date"] for r in rows)
            return [make_chunk(
                f"There are {count} Saturday holidays: {dates}."
            )]

        #  General / named holidays (non-Sunday, non-Saturday)
        if "general" in event_type_param:
            all_holidays = fetch_by_type("holiday")
            general = [
                r for r in all_holidays
                if not re.search(r"\b(sunday|saturday)\b", r.get("event_name", ""), re.IGNORECASE)
            ]
            count = len(general)
            names = ", ".join(
                f"{r['event_name']} ({r['event_date']})" for r in general
            )
            return [make_chunk(
                f"There are {count} general/named holidays: {names}."
            )]

        # Link holidays 
        if "link" in event_type_param:
            rows  = fetch_by_name("link holiday")
            count = len(rows)
            dates = ", ".join(
                f"{r['event_name']} ({r['event_date']})" for r in rows
            )
            return [make_chunk(
                f"There are {count} link holidays: {dates}."
            )]

        # Compensatory working days
        if "compensatory" in event_type_param:
            rows  = fetch_by_name("compensatory working day")
            count = len(rows)
            dates = ", ".join(
                f"{r['event_name']} ({r['event_date']})" for r in rows
            )
            return [make_chunk(
                f"There are {count} compensatory working days: {dates}."
            )]

        # Co-curricular days
        if "co_curricular" in event_type_param or "co curricular" in event_type_param:
            rows  = fetch_by_type("co_curricular")
            count = len(rows)
            dates = ", ".join(
                f"{r['event_name']} ({r['event_date']})" for r in rows
            )
            return [make_chunk(
                f"There are {count} co-curricular activity days: {dates}."
            )]
 
    # COUNT HOLIDAYS IN A MONTH count in Python, never let LLM count
    if (params.get("month") and 
        params.get("event_type") and 
        "holiday" in params.get("event_type", "").lower() and
        query_type == "count"):
        
        month = params["month"]
        year, mon = month.split("-")
        last_day = cal_module.monthrange(int(year), int(mon))[1]
        
        rows = (
            supabase.table("academic_calendar")
            .select("*")
            .eq("event_type", "holiday")
            .gte("event_date", f"{month}-01")
            .lte("event_date", f"{month}-{last_day:02d}")
            .order("event_date", desc=False)
            .execute()
            .data
        )
        
        count = len(rows)
        names = ", ".join(f"{r['event_name']} ({r['event_date']})" for r in rows)
        month_name = date(int(year), int(mon), 1).strftime("%B %Y")
        
        return [make_chunk(
            f"There are exactly {count} holidays in {month_name}: {names}."
        )]
   
    data = query_calendar(params)
    
    if not data and params.get("is_college_open_query") and params.get("date"):
        return [make_chunk(
            f"There are no holidays or events recorded for {params['date']}. "
            f"College is open as usual on this day."
        )]
    return format_calendar_chunks(data, params=params)


def format_faculty_chunks(data: list, compact: bool = False, minimal: bool = False) -> list:
    """Convert faculty_biodata rows into clean text chunks for the LLM."""
    chunks = []
    for f in data:
        if compact:
            text = (
                f"Name: {f.get('name')} | "
                f"Designation: {f.get('designation')} | "
                f"Department: {f.get('department')}"
            )
        elif minimal:
            lines = []
            if f.get("name"): lines.append(f"Name: {f['name']}")
            if f.get("faculty_shortform"): lines.append(f"Initials: {f['faculty_shortform']}")
            if f.get("designation"): lines.append(f"Designation: {f['designation']}")
            if f.get("department"): lines.append(f"Department: {f['department']}")
            if f.get("email"):
                email = f["email"]
                if isinstance(email, list): email = ", ".join(email)
                lines.append(f"Email: {email}")
            if f.get("past_experience"): lines.append(f"Past Experience: {f['past_experience']}")
            if f.get("areas_of_interest"): lines.append(f"Interests: {f['areas_of_interest']}")
            text = "\n".join(lines)
        else:
            lines = []
            if f.get("name"):
                lines.append(f"Name: {f['name']}")
            if f.get("faculty_shortform"):
                lines.append(f"Short name / initials: {f['faculty_shortform']}")
            if f.get("designation"):
                lines.append(f"Designation: {f['designation']}")
            if f.get("department"):
                lines.append(f"Department: {f['department']}")
            if f.get("email"):
                email = f["email"]
                if isinstance(email, list):
                    email = ", ".join(email)
                lines.append(f"Email: {email}")
            if f.get("joining_date"):
                lines.append(f"Joining Date: {f['joining_date']}")
            if f.get("past_experience"):
                lines.append(f"Past Experience: {f['past_experience']}")
            if f.get("educational_qualifications"):
                lines.append(f"Education: {f['educational_qualifications']}")
            if f.get("areas_of_interest"):
                lines.append(f"General Topics of Interest: {f['areas_of_interest']}")
            if f.get("research"):
                lines.append(f"Funded Research Projects & Grants: {f['research']}")
            if f.get("achievements"):
                lines.append(f"Achievements: {f['achievements']}")
            if f.get("subjects_taught"):
                subjects = f["subjects_taught"]
                if isinstance(subjects, list):
                    subjects = ", ".join(subjects)
                lines.append(f"Subjects Taught: {subjects}")
            if f.get("scholar_id"):
                lines.append(f"Google Scholar ID: {f['scholar_id']}")
            if f.get("orcid_id"):
                lines.append(f"ORCID ID: {f['orcid_id']}")
            if f.get("linkedin_id"):
                lines.append(f"LinkedIn: {f['linkedin_id']}")
            text = "\n".join(lines)

        chunks.append({
            "content": text,
            "metadata": {"source_type": "faculty_biodata", "name": f.get("name")},
            "similarity": 1.0
        })
    return chunks

def query_faculty(params: dict) -> list:
    """
    Bulletproof faculty query — handles any twisted query about faculty_biodata.
    """
    supabase = get_supabase_client()

    query = supabase.table("faculty_biodata").select("""
        faculty_id,
        name,
        designation,
        department,
        email,
        joining_date,
        past_experience,
        educational_qualifications,
        areas_of_interest,
        achievements,
        subjects_taught,
        scholar_id,
        orcid_id,
        linkedin_id,
        research,
        faculty_shortform
    """)

    filters_applied = False

   
    if params.get("faculty_name"):
        name = params["faculty_name"].strip().lower()
    
        strips = [
            "dr.", "dr ", "prof.", "prof ", "mr.", "mr ", "ms.", "ms ",
            "mrs.", "mrs ", "sri ", "shri ",
            "sir", "mam", "ma'am", "madam", "miss",
            "professor", "associate professor", "assistant professor",
            "adjunct professor", "hod", "head", "principal", "dean",
            "coordinator", "lecturer", "faculty", "teacher", "mentor",
            "respected", "dear", "our", "the",
        ]
        
        for s in strips:
            name = name.replace(s, "").strip()
        
        name = " ".join(name.split())
        
        if name:
            query = query.ilike("name", f"%{name}%")
            filters_applied = True
    if params.get("department"):
        dept = params["department"].lower()
        if "cse" in dept or "cs" in dept:
            dept_search = "computer"
        else:
            dept_search = dept
        query = query.ilike("department", f"%{dept_search}%")
        filters_applied = True

    # Filter by designation
    if params.get("designation"):
        desig = params["designation"].lower()
        if "hod" in desig or "head" in desig:
            query = query.ilike("designation", f"%head%")
        elif "assistant" in desig or "asst" in desig:
            query = query.ilike("designation", f"%assistant professor%")
        elif "associate" in desig:
            query = query.ilike("designation", f"%associate professor%")
        elif "adjunct" in desig:
            query = query.ilike("designation", f"%adjunct%")
        elif "prof" in desig:
            query = query.ilike("designation", f"professor%") 
        else:
            query = query.ilike("designation", f"%{desig}%")
        filters_applied = True
        print("DESIGNATION FILTER USED:", desig)

    # Filter by subject
    if params.get("subject"):
        query = query.contains("subjects_taught", [params["subject"]])
        filters_applied = True

    # Filter by research area
    if params.get("research_area"):
        query = query.ilike("areas_of_interest", f"%{params['research_area']}%")
        filters_applied = True
    result = query.execute().data
    print("RESULT COUNT:", len(result))
    # FALLBACK
    if not result:
        result = supabase.table("faculty_biodata").select("""
            faculty_id,
            name,
            designation,
            department,
            email,
            joining_date,
            past_experience,
            educational_qualifications,
            areas_of_interest,
            achievements,
            subjects_taught,
            scholar_id,
            orcid_id,
            linkedin_id,
            research,
            faculty_shortform
        """).limit(5).execute().data

    return result
def query_lab(params: dict) -> list:
    supabase = get_supabase_client()
    query = supabase.table("lab_infrastructure").select("*")

    if params.get("lab_name"):
        import re
        match = re.search(r'\d+', params["lab_name"])
        lab_number = match.group() if match else params["lab_name"]
        query = query.ilike("lab_name", f"%Lab-{lab_number}%")

    if params.get("min_computers"):
        query = query.gt("no_of_computers", params["min_computers"])

    if params.get("max_computers"):
        query = query.lt("no_of_computers", params["max_computers"])

    return query.execute().data


def format_lab_chunks(data: list) -> list:
    chunks = []
    for row in data:
        text = (
            f"{row.get('lab_name')} is located in room {row.get('room_number')} "
            f"and has {row.get('no_of_computers', 'unknown')} computers."
        )
        chunks.append({
            "content": text,
            "metadata": {"source_type": "lab"},
            "similarity": 1.0
        })
    return chunks

def query_lab_embeddings(params: dict) -> list:
    supabase = get_supabase_client()

    lab_name = params.get("lab_name", "") 

    result = supabase.table("unified_embeddings").select("*") \
        .eq("source_type", "lab") \
        .eq("source_id", lab_name) \
        .in_("chunk_type", ["02_brands", "03_configuration"]) \
        .execute()

    if not result.data:
        return []

    return [
        {
            "content": f"[{row.get('metadata', {}).get('lab_name', row.get('source_id', ''))}] {row.get('raw_text')}",
            "metadata": row.get("metadata") or {},
            "similarity": 1.0
        }
        for row in result.data
        if row.get("raw_text")
    ]

def query_lab_availability(params: dict) -> list:
    supabase = get_supabase_client()

    lab_name = params.get("lab_name", "")
    import re
    match = re.search(r'\d+', lab_name)
    lab_number = match.group() if match else lab_name

    # Step 1: get lab_id from lab_infrastructure
    lab_result = supabase.table("lab_infrastructure") \
        .select("lab_id, lab_name, room_number") \
        .ilike("lab_name", f"%Lab-{lab_number}%") \
        .execute()

    if not lab_result.data:
        return [{"content": f"Lab {lab_number} not found.", "metadata": {}, "similarity": 1.0}]

    lab = lab_result.data[0]
    lab_id = lab["lab_id"]
    lab_display = lab["lab_name"]

    # Step 2: get time_slot from period
    time_slot = None
    if params.get("period"):
        raw = str(params["period"]).lower().strip()
        time_slot = resolve_time_slot(raw)
        if not time_slot:
            return [{"content": f"'{params['period']}' is outside college hours (9:00 AM - 4:15 PM).", "metadata": {}, "similarity": 1.0}]
    day = params.get("day", "")

    # Step 3: fetch timetable rows where is_lab=true for given day/time
    query = supabase.table("timetable").select("subject_code, class, day_of_week, time_slot") \
        .eq("is_lab", True)

    if day:
        query = query.eq("day_of_week", day)
    if time_slot:
        query = query.eq("time_slot", time_slot)

    tt_rows = query.execute().data

    if not tt_rows:
        return [{"content": f"{lab_display} is FREE on {day} during {time_slot}.", "metadata": {}, "similarity": 1.0}]

    # Step 4: for each timetable row, check subjects table for matching lab_id
    occupied_rows = []
    for row in tt_rows:
        subj_result = supabase.table("subjects").select("subject_name, lab_id") \
            .eq("subject_code", row["subject_code"]) \
            .eq("class", row["class"]) \
            .eq("lab_id", lab_id) \
            .execute()

        if subj_result.data:
            subject_name = subj_result.data[0].get("subject_name", "a class")
            occupied_rows.append({
                "day": row["day_of_week"],
                "time_slot": row["time_slot"],
                "class": row["class"],
                "subject": subject_name
            })

    if not occupied_rows:
        return [{"content": f"{lab_display} is FREE on {day} during {time_slot}.", "metadata": {}, "similarity": 1.0}]

    chunks = []
    for r in occupied_rows:
        chunks.append({
            "content": f"{lab_display} is OCCUPIED on {r['day']} during {r['time_slot']} by class {r['class']} for {r['subject']}.",
            "metadata": {},
            "similarity": 1.0
        })
    return chunks

def resolve_time_slot(raw: str) -> str:
    """Resolve any time string to the nearest timetable slot."""

    slot = TIME_SLOT_MAP.get(raw.lower().strip())
    if slot:
        return slot

    import re
    match = re.search(r'(\d{1,2}):?(\d{0,2})\s*(am|pm)?', raw.lower())
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2)) if match.group(2) else 0
    meridiem = match.group(3)

    if meridiem == "pm" and hour != 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0

    total_minutes = hour * 60 + minute

    slots = [
        (9*60,      "09:00-09:55"),
        (10*60+5,   "10:05-11:00"),
        (11*60,     "11:00-11:55"),
        (12*60+35,  "12:35-01:30"),
        (13*60+30,  "01:30-02:25"),
        (14*60+25,  "02:25-03:20"),
        (15*60+20,  "03:20-04:15"),
    ]

    slot_ranges = [
        (9*60,      9*60+55,    "09:00-09:55"),
        (10*60+5,   11*60,      "10:05-11:00"),
        (11*60,     11*60+55,   "11:00-11:55"),
        (12*60+35,  13*60+30,   "12:35-01:30"),
        (13*60+30,  14*60+25,   "01:30-02:25"),
        (14*60+25,  15*60+20,   "02:25-03:20"),
        (15*60+20,  16*60+15,   "03:20-04:15"),
    ]

    for start, end, slot in slot_ranges:
        if start <= total_minutes <= end:
            return slot

    return None

SLOT_TO_PERIOD = {
    "09:00-09:55": "1",
    "10:05-11:00": "2",
    "11:00-11:55": "3",
    "12:35-01:30": "4",
    "01:30-02:25": "5",
    "02:25-03:20": "6",
    "03:20-04:15": "7",
}

def format_timetable_chunks_v2(data: list) -> list:
    chunks = []
    for row in data:
        subject = row.get("subject_info") or {}
        faculty = subject.get("faculty_biodata") or {}
        session_type = "Lab session" if row.get("is_lab") else "Lecture"
        activity = row.get("activity", "")
        time_slot = row.get("time_slot", "")
        period_num = SLOT_TO_PERIOD.get(time_slot, "?")

        text = (
            f"On {row.get('day_of_week')}, "
            f"class {row.get('class')} has a {session_type} — "
            f"{subject.get('subject_name', row.get('subject_code', 'unknown subject'))} "
            f"during Period {period_num} (time slot: {time_slot}), "
            f"taught by {faculty.get('name', 'unknown faculty')}."
        )
        if activity:
            text += f" Activity: {activity}."
        if row.get("is_lab") and row.get("lab_id"):
            text += f" Lab ID: {row['lab_id']}."

        chunks.append({
            "content": text,
            "metadata": {"source_type": "timetable"},
            "similarity": 1.0,
        })
    return chunks


def format_free_period_chunks(free_slots: list, class_name: str, day: str) -> list:
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


def query_full_day_timetable(class_name: str, day: str) -> list:
    supabase = get_supabase_client()
    rows = (
        supabase.table("timetable")
        .select("*")
        .eq("class", class_name)
        .eq("day_of_week", day)
        .execute()
        .data
    )
    if not rows:
        return []

    SLOT_ORDER = list(TIME_SLOT_MAP.values())
    rows.sort(key=lambda r: SLOT_ORDER.index(r["time_slot"]) if r["time_slot"] in SLOT_ORDER else 99)

    subject_codes = list({r["subject_code"] for r in rows if r.get("subject_code")})
    subj_map = {}
    if subject_codes:
        subj_rows = (
            supabase.table("subjects")
            .select("subject_code, subject_name, class, faculty_id, faculty_biodata(name)")
            .in_("subject_code", subject_codes)
            .execute()
            .data
        )
        for s in subj_rows:
            subj_map[(s["subject_code"], s["class"])] = s

    for row in rows:
        row["subject_info"] = subj_map.get((row.get("subject_code"), row.get("class")), {})
    return rows


def query_faculty_timetable(faculty_name: str, day: str = None) -> list:
    supabase = get_supabase_client()

    name_clean = faculty_name.strip().lower()
    for honorific in ["dr.", "dr ", "prof.", "prof ", "mr.", "mr ", "ms.", "ms ", "mrs.", "mrs "]:
        name_clean = name_clean.replace(honorific, "").strip()

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

    subj_rows = (
        supabase.table("subjects")
        .select("subject_code, subject_name, class")
        .in_("faculty_id", faculty_ids)
        .execute()
        .data
    )
    if not subj_rows:
        return []

    subj_map = {(s["subject_code"], s["class"]): s for s in subj_rows}
    subject_codes = list({s["subject_code"] for s in subj_rows})

    tt_query = (
        supabase.table("timetable")
        .select("*")
        .in_("subject_code", subject_codes)
    )
    if day:
        tt_query = tt_query.eq("day_of_week", day)

    tt_rows = tt_query.execute().data

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


def query_free_periods(class_name: str, day: str) -> list:
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


def query_subject_schedule(subject: str, class_name: str = None) -> list:
    supabase = get_supabase_client()

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

    tt_query = supabase.table("timetable").select("*").in_("subject_code", subject_codes)
    if class_name:
        tt_query = tt_query.eq("class", class_name)
    tt_rows = tt_query.execute().data

    for row in tt_rows:
        row["subject_info"] = subj_map.get((row["subject_code"], row["class"]), {})

    DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    SLOT_ORDER = list(TIME_SLOT_MAP.values())
    tt_rows.sort(key=lambda r: (
        DAY_ORDER.index(r["day_of_week"]) if r["day_of_week"] in DAY_ORDER else 99,
        SLOT_ORDER.index(r["time_slot"]) if r["time_slot"] in SLOT_ORDER else 99
    ))
    return tt_rows


def query_class_at_period(day: str, period: str) -> list:
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

def query_lab_by_keyword(keyword: str) -> list:
    supabase = get_supabase_client()

    result = supabase.table("unified_embeddings").select("*") \
        .eq("source_type", "lab") \
        .eq("chunk_type", "02_brands") \
        .ilike("raw_text", f"%{keyword}%") \
        .execute()

    return [
        {
            "content": f"[{row.get('metadata', {}).get('lab_name', row.get('source_id', ''))}] {row.get('raw_text')}",
            "metadata": row.get("metadata") or {},
            "similarity": 1.0
        }
        for row in result.data
        if row.get("raw_text")
    ]
RESPONSE_TEMPLATES = {
    "email":          "{name}'s email is {value}.",
    "designation":    "{name} is a {value}.",
    "department":     "{name} is in the {value} department.",
    "experience":     "{name} has {value} of experience.",
    "joining_date":   "{name} joined on {value}.",
    "google_scholar": "{name}'s Google Scholar profile: {value}",
    "orcid":          "{name}'s ORCID profile: {value}",
    "linkedin":       "{name}'s LinkedIn profile: {value}",
}

def get_faculty_direct_field(faculty_name: str, field: str) -> str | None:
    """Directly fetch a single field for a faculty — no LLM needed."""
    try:
        supabase = get_supabase_client()
        result = supabase.table("faculty_biodata") \
            .select(field) \
            .ilike("name", f"%{faculty_name}%") \
            .limit(1) \
            .execute()

        if not result.data:
            return None

        row = result.data[0]
        value = row.get(field)

        if isinstance(value, list):
            value = value[0] if value else None

        if not value:
            return f"Sorry, {field.replace('_', ' ')} is not available for this faculty."

        full_name = row.get("name", faculty_name)
        template = RESPONSE_TEMPLATES.get(field, "{name}: {value}")
        return template.format(name=full_name, value=value)

    except Exception as e:
        return None
def query_class_teacher(params: dict) -> list:
    supabase = get_supabase_client()

    query = supabase.table("subjects") \
        .select("subject_name, class, faculty_biodata(name, designation)") \
        .eq("is_class_teacher", True)

    if params.get("class"):
        query = query.eq("class", params["class"])

    rows = query.execute().data

    chunks = []
    for row in rows:
        faculty = row.get("faculty_biodata") or {}
        name = faculty.get("name", "Unknown")
        cls = row.get("class", "")
        chunks.append({
            "content": f"The class teacher of {cls} is {name}.",
            "metadata": {"source_type": "subjects"},
            "similarity": 1.0
        })
    return chunks
