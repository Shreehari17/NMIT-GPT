from .retriever import retrieve_top_chunks
from .llm_interface import generate_llm_answer
from .query_parser import parse_query

from .sql_queries import (
    query_timetable,
    query_subjects,
    query_calendar,
    query_faculty,
    format_calendar_chunks,
    format_faculty_chunks,
    retrieve_chunks,
    query_lab,
    format_lab_chunks,
    query_lab_embeddings,
    query_lab_availability,
    query_lab_by_keyword,
    get_faculty_direct_field,
    query_class_teacher,
)

import re
import time
from datetime import datetime, timedelta


# ============================================================
# PROMPT BUILDERS
# ============================================================

def _prepare_context(chunks: list, params: dict = None) -> str:
    """
    Convert retrieved chunks into a single context string.
    Shared by SQL and RAG prompt builders.
    """

    context_lines = []

    for c in chunks:
        content = c.get("content")

        if not content:
            continue

        context_lines.append(content)

    
    # Calendar safety net
    if not context_lines and params and params.get("date"):
        context_lines.append(
            f"The academic calendar has no recorded events for {params['date']}."
        )
    if not context_lines and params and params.get("date"):
        context_lines.append(
            f"The academic calendar has no recorded events for {params['date']}."
        )

    context = "\n\n".join(context_lines)

    # SAFETY NET FOR GROQ TOKEN LIMITS
    MAX_CHARS = 15000

    if len(context) > MAX_CHARS:
        context = context[:MAX_CHARS] + "\n...[Context Truncated]"
        return context


def build_sql_prompt(
    user_query: str,
    chunks: list,
    params: dict = None
) -> str:
    """
    Prompt for structured / SQL-derived data.

    SQL results are already precise and structured, so the LLM should
    mainly format the answer instead of reasoning broadly.
    """

    context = _prepare_context(chunks, params)

    prompt = f"""
You are NMIT-GPT, an academic assistant for NMIT college.

The context below comes from STRUCTURED DATABASE / SQL retrieval.

Your job is to answer the student's question using ONLY this context.

IMPORTANT:
- Do not add information that is not present in the context.
- Do not guess.
- Do not perform calculations that are not explicitly required.
- Do not repeat the entire database record.
- Answer ONLY what the student asked.
- Be concise and direct.
- If the exact answer is present, give it immediately.
- If the required information is missing, say:
  "Information not available."

**Rules for Timetable queries:
- When showing a full day timetable, list ALL periods in time order
- Format each period as: "Period <time>: <subject> by <faculty>"
- If faculty not present then do not mention it in the answer. 
- Never skip any period
- If asked for a specific day, only show that day's periods
- Present as a numbered list when showing full day schedule
FACULTY:
- For a specific question such as "Who is the HOD?", return only the requested information.
- Do NOT provide the faculty's entire profile unless asked.
- Never use gendered pronouns.
- Never infer gender.
- If the faculty name is needed, use the full name from the context.
- Never infer HOD/designation unless explicitly present in the context.

CALENDAR:
- "when does X start" → give ONLY the start date.
- "when does X end" → give ONLY the end date.
- "when is X" → give the date/range present in the context.
- Convert YYYY-MM-DD into readable dates.
- Never swap month and day.
- Never perform your own date arithmetic.
- For gap/duration queries, use the exact number already provided by the context.
- If an exam is ongoing, it overrides the timetable.
- Holiday → college closed.
- Compensatory working day → college open.
- Teaching days / working days → return the number directly when present.

TIMETABLE:
- For a full-day schedule, include all periods in order.
- For a specific period, answer only that period.
- Copy period numbers and time slots EXACTLY from the context.
- Never invent or approximate a time slot.
- Valid time slots are:
  09:00-09:55
  10:05-11:00
  11:00-11:55
  12:35-01:30
  01:30-02:25
  02:25-03:20
  03:20-04:15
- For lab sessions, say "Lab session".
- If no timetable rows exist, say:
  "No timetable entry found for [class] on [day]."

SUBJECTS:
- If asked who teaches a subject, give the faculty name.
- If asked what subjects a faculty teaches, list the subjects present in context.
- If asked how many subjects, count UNIQUE subject names only.
- Do not count duplicate subjects across classes.

LABS:
- Answer only from the context.
- For configuration, report the requested configuration.
- For lab availability:
  - Free → "Yes, [lab] is free on [day] at [time]."
  - Occupied → "No, [lab] is not free on [day] at [time]. It is occupied by class [class] for [subject]."
- Do not provide unnecessary explanations.
- Always mention the lab name.


Rules for Subject queries:
- "how many subjects" with no specific class → count the total number of UNIQUE subject names in the context
- NEVER count per class or per section — count unique subject names only once 
- ALWAYS count your listed items before writing the number
- The answer should be the count first, then list all unique subject names
- Example: "There are 12 subjects in 6th semester: 1. Operating System concepts 2. Cryptography and Network Security ..."
- "how many subjects" or "list all subjects" → count the items in your own answer list and report that number
- NEVER state a count number yourself — always count your listed items and use that number
- The count must ALWAYS match the number of items in your list
- Before writing "There are X subjects", count the items in your list first and then write the count
- Do not group by class when answering count queries about subjects
- "what subjects does X teach" or "which subjects does X take" → list ALL subject names present in the context, do NOT filter or skip any
- The context already contains ONLY the subjects taught by that faculty — trust the context completely, list everything in it
- NEVER say a subject is not taught by the faculty if it appears in the context
- "what subjects does X teach" → list ALL subject names in context, trust context completely, never skip any
- "Is the same faculty teaching X?" → if all chunks show same faculty name → "Yes, [name] teaches [subject] for all classes", if different → "No" and list each class with faculty
- "who teaches X for 6A and 6B" → list faculty for each class separately
- Example: "Dr. X teaches CNS for 6A, Dr. Y teaches CNS for 6B"
- "does X teach any lab?" → scan each chunk's subject name for the word "Lab" — if NONE contain "Lab" → answer "No, [faculty name] does not teach any lab subject" — NEVER say Yes unless a chunk explicitly has "Lab" in the subject name
- When the user asks for a "lab number" or "which lab", extract the Lab name and room number from the chunk, NOT the subject code.
- Example: "Lab: Computer Lab-1 (Room 120) in room 120" → answer "Computer Lab-1 in room 120"
- "who takes [lab] for [class]" → list ALL faculty from context, grouped by batch
- NEVER skip any faculty name — if context has 6 entries, list all 6
- NEVER use "respectively" for lab batch queries
- Format EXACTLY like this:
  6D-D1: [faculty1] and [faculty2] — [Lab Name] (Room X)
  6D-D2: [faculty1] and [faculty2] — [Lab Name] (Room X)
  6D-D3: [faculty1] and [faculty2] — [Lab Name] (Room X)
- Count the chunks before answering — if there are 6 chunks, there are 6 faculty names to include
- NEVER merge or combine faculty across batches
If the answer is not found in the context, say: "Information not available."

[Context]
{context}

[Question]

QUESTION:
{user_query}

CONTEXT:
{context}

ANSWER:
"""

    return prompt.strip()


def build_rag_prompt(
    user_query: str,
    chunks: list,
    params: dict = None
) -> str:
    """
    Prompt for vector / unstructured RAG retrieval.

    Vector chunks may contain pieces of documents, so the LLM is allowed
    to synthesize information from the retrieved context.
    """

    context = _prepare_context(chunks, params)

    prompt = f"""
You are NMIT-GPT, an academic assistant for NMIT college.

The context below comes from VECTOR / RAG RETRIEVAL.

Answer the student's question using ONLY the retrieved context.

RULES:
- Do not use outside knowledge.
- Do not hallucinate.
- Do not invent missing facts.
- You may combine information from multiple retrieved chunks when necessary.
- If the context does not contain enough information, say:
  "Information not available."
- Be concise and natural.
- Answer the question directly.
- Do not repeat irrelevant parts of the context.

If the question asks for a procedure, explain the procedure using only
the retrieved information.

If the question asks for a definition or explanation, explain it clearly
using only the retrieved information.

If multiple chunks contain relevant information, combine them into one
coherent answer.

QUESTION:
{user_query}

RETRIEVED CONTEXT:
{context}

ANSWER:
"""

    return prompt.strip()


# ============================================================
# EXISTING TIMETABLE FORMATTERS
# ============================================================

def format_timetable_chunks(data: list) -> list:
    chunks = []

    def time_sort_key(row):
        return row.get("time_slot", "")

    sorted_data = sorted(data, key=time_sort_key)

    for row in sorted_data:

        subject = row.get("subject_info") or {}
        faculty = subject.get("faculty_biodata") or {}

        is_lab = row.get("is_lab", False)

        subject_name = (
            subject.get("subject_name")
            or row.get("subject_code")
        )

        faculty_name = faculty.get("name")

        if not subject_name and not faculty_name:
            continue

        session_type = "Lab session" if is_lab else "Lecture"

        text = (
            f"Period {row.get('time_slot')} ({session_type}): "
            f"{subject_name or 'unknown subject'} "
            f"(Day: {row.get('day_of_week')}, Class: {row.get('class')})."
        )

        if not is_lab and faculty_name:
            text = (
                text.rstrip(".")
                + f", taught by {faculty_name}."
            )

        chunks.append({
            "content": text,
            "metadata": {
                "source_type": "timetable"
            },
            "similarity": 1.0
        })

    return chunks


def format_subject_chunks(data: list) -> list:
    chunks = []

    for row in data:

        faculty = row.get("faculty_biodata") or {}
        lab = row.get("lab_infrastructure") or {}

        text = (
            f"{row.get('subject_name')} "
            f"(code: {row.get('subject_code')}) "
            f"is taught to class {row.get('class')} "
            f"by {faculty.get('name', 'unknown faculty')}."
        )

        if lab:
            text += (
                f" Lab: {lab.get('lab_name')} "
                f"in room {lab.get('room_number')}."
            )

        chunks.append({
            "content": text,
            "metadata": {
                "source_type": "subjects"
            },
            "similarity": 1.0
        })

    return chunks


# ============================================================
# PERIOD / DATE HELPERS
# ============================================================

_DAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday"
]

_SLOT_TO_PERIOD = {
    "09:00-09:55": "1",
    "10:05-11:00": "2",
    "11:00-11:55": "3",
    "12:35-01:30": "4",
    "01:30-02:25": "5",
    "02:25-03:20": "6",
    "03:20-04:15": "7",
}

_MORNING_PERIODS = ["1", "2", "3"]

_AFTERNOON_PERIODS = ["4", "5", "6", "7"]


def _day_name(dt) -> str:
    return _DAYS[dt.weekday()]


def _date_str(dt) -> str:
    return dt.strftime("%Y-%m-%d")


def _resolve_current_period() -> tuple:
    """
    Return:
    (day_name, period_str, time_slot_str)
    """

    from .sql_queries import resolve_time_slot

    now = datetime.now()

    time_slot = resolve_time_slot(
        now.strftime("%H:%M")
    )

    if not time_slot:
        return _day_name(now), None, None

    return (
        _day_name(now),
        _SLOT_TO_PERIOD.get(time_slot),
        time_slot
    )


# ============================================================
# TEMPORAL CONTEXT
# ============================================================

def _inject_temporal_context(query: str) -> str:
    """
    Resolve relative date/time words BEFORE the parser sees them.

    Examples:
        today
        tomorrow
        yesterday
        now
        current period
        morning
        afternoon
        this week
    """

    from .sql_queries import resolve_time_slot

    q = query
    ql = query.lower()

    now = datetime.now()
    today = now.date()

    def _fmt(d):
        return d.strftime("%Y-%m-%d")

    def _dname(d):
        return _DAYS[d.weekday()]

    # --------------------------------------------------------
    # NOW / CURRENT
    # --------------------------------------------------------

    NOW_WORDS = [
        "now",
        "current period",
        "currently",
        "ongoing",
        "right now",
        "current class"
    ]

    if any(w in ql for w in NOW_WORDS):

        day, period, slot = _resolve_current_period()

        if period:

            q += (
                f" (current day is {day}, "
                f"current period is {period}, "
                f"current time slot is {slot})"
            )

        else:

            q += (
                f" (current day is {day}, "
                f"no class in progress)"
            )

        return q

    # --------------------------------------------------------
    # MORNING
    # --------------------------------------------------------

    if (
        "this morning" in ql
        or (
            ql.count("morning") > 0
            and "yesterday" not in ql
            and "tomorrow" not in ql
        )
    ):

        periods = ", ".join(
            _MORNING_PERIODS
        )

        q += (
            f" (current day is {_dname(today)}, "
            f"morning = periods {periods})"
        )

        return q

    # --------------------------------------------------------
    # AFTERNOON
    # --------------------------------------------------------

    if (
        "this afternoon" in ql
        or (
            ql.count("afternoon") > 0
            and "yesterday" not in ql
            and "tomorrow" not in ql
        )
    ):

        periods = ", ".join(
            _AFTERNOON_PERIODS
        )

        q += (
            f" (current day is {_dname(today)}, "
            f"afternoon = periods {periods})"
        )

        return q

    # --------------------------------------------------------
    # DAY BEFORE YESTERDAY
    # --------------------------------------------------------


    # day before yesterday 
    if "day before yesterday" in ql:

        d = today - timedelta(days=2)

        q = q.replace(
            "day before yesterday",
            f"{_fmt(d)} ({_dname(d)})"
        )

        q = q.replace(
            "Day before yesterday",
            f"{_fmt(d)} ({_dname(d)})"
        )

        return q

    # --------------------------------------------------------
    # YESTERDAY
    # --------------------------------------------------------

    if "yesterday" in ql:

        d = today - timedelta(days=1)

        q = q.replace(
            "yesterday",
            f"{_fmt(d)} ({_dname(d)})"
        )

        q = q.replace(
            "Yesterday",
            f"{_fmt(d)} ({_dname(d)})"
        )

        return q

    # --------------------------------------------------------
    # DAY AFTER TOMORROW
    # --------------------------------------------------------

    if "day after tomorrow" in ql:

        d = today + timedelta(days=2)

        q = q.replace(
            "day after tomorrow",
            f"{_fmt(d)} ({_dname(d)})"
        )

        q = q.replace(
            "Day after tomorrow",
            f"{_fmt(d)} ({_dname(d)})"
        )

        return q

    # --------------------------------------------------------
    # TOMORROW
    # --------------------------------------------------------

    if (
        "tomorrow" in ql
        or "next day" in ql
    ):

        d = today + timedelta(days=1)

        q = q.replace(
            "tomorrow",
            f"{_fmt(d)} ({_dname(d)})"
        )

        q = q.replace(
            "Tomorrow",
            f"{_fmt(d)} ({_dname(d)})"
        )

        q = q.replace(
            "next day",
            f"{_fmt(d)} ({_dname(d)})"
        )

        q = q.replace(
            "Next day",
            f"{_fmt(d)} ({_dname(d)})"
        )

        return q

    # --------------------------------------------------------
    # TODAY
    # --------------------------------------------------------

    if "today" in ql:

        q = q.replace(
            "today",
            f"{_fmt(today)} ({_dname(today)})"
        )

        q = q.replace(
            "Today",
            f"{_fmt(today)} ({_dname(today)})"
        )

        return q

    # --------------------------------------------------------
    # THIS WEEK
    # --------------------------------------------------------

    if "this week" in ql:

        week_start = (
            today
            - timedelta(days=today.weekday())
        )

        week_end = (
            week_start
            + timedelta(days=4)
        )

        q += (
            f" (this week = "
            f"{_fmt(week_start)} to "
            f"{_fmt(week_end)})"
        )

        return q

    return q


# ============================================================
# MAIN PIPELINE
# ============================================================

def answer_query(
    user_query: str,
    top_k: int = 5,
    chat_history: list = None
) -> dict:

    start = time.time()

    # --------------------------------------------------------
    # STEP 1: PRE-RESOLVE TIME / DATE
    # --------------------------------------------------------

    user_query = _inject_temporal_context(
        user_query
    )

    # --------------------------------------------------------
    # STEP 2: PARSE QUERY
    # --------------------------------------------------------

    parsed = parse_query(
        user_query,
        chat_history=chat_history
    )

    from RAG_ENGINE.src.query_parser import PARSER_MODEL

    print("PARSER MODEL:", PARSER_MODEL)

    print(
        "PARSED:",
        parsed
    )

    print(
        f"PARSE TIME: "
        f"{time.time() - start:.2f}s"
    )

    intent = parsed.get(
        "intent",
        "general"
    )

    t2 = time.time()

    # ========================================================
    # TIMETABLE
    # ========================================================

    if intent == "timetable":

        from .timetable_extras import (
            query_full_day_timetable,
            query_faculty_timetable,
            query_free_periods,
            query_subject_schedule,
            query_class_at_period,
            format_timetable_chunks_v2,
            format_free_period_chunks,
        )

        # ----------------------------------------------------
        # DATE + EXAM CHECK
        # ----------------------------------------------------

        if parsed.get("date"):

            exam_chunks = retrieve_chunks({
                "intent": "calendar",
                "date": parsed["date"]
            })

            exam_chunks = [
                c
                for c in exam_chunks
                if "exam" in c.get(
                    "content",
                    ""
                ).lower()
            ]

            if exam_chunks:

                prompt = build_sql_prompt(
                    user_query,
                    exam_chunks,
                    params=parsed
                )

                answer = generate_llm_answer(
                    prompt,
                    chat_history=chat_history
                )

                return {
                    "query": user_query,
                    "answer": answer,
                    "chunks_used": exam_chunks
                }

        # ----------------------------------------------------
        # FREE PERIOD
        # ----------------------------------------------------

        if (
            parsed.get("free_period_query")
            and parsed.get("class")
            and parsed.get("day")
        ):

            free_slots = query_free_periods(
                parsed["class"],
                parsed["day"]
            )

            chunks = format_free_period_chunks(
                free_slots,
                parsed["class"],
                parsed["day"]
            )

        # ----------------------------------------------------
        # FACULTY TIMETABLE
        # ----------------------------------------------------

        elif (
            parsed.get("faculty_timetable_query")
            and parsed.get("faculty_name")
        ):

            raw_data = query_faculty_timetable(
                parsed["faculty_name"],
                parsed.get("day")
            )

            chunks = format_timetable_chunks_v2(
                raw_data
            )

        # ----------------------------------------------------
        # FULL DAY
        # ----------------------------------------------------

        elif (
            parsed.get("full_day_query")
            and parsed.get("class")
            and parsed.get("day")
        ):

            raw_data = query_full_day_timetable(
                parsed["class"],
                parsed["day"]
            )

            chunks = format_timetable_chunks_v2(
                raw_data
            )

        # ----------------------------------------------------
        # SUBJECT SCHEDULE
        # ----------------------------------------------------

        elif (
            parsed.get("subject_schedule_query")
            and parsed.get("subject")
        ):

            raw_data = query_subject_schedule(
                parsed["subject"],
                parsed.get("class")
            )

            chunks = format_timetable_chunks_v2(
                raw_data
            )

        # ----------------------------------------------------
        # CROSS CLASS
        # ----------------------------------------------------

        elif (
            parsed.get("day")
            and parsed.get("period")
            and not parsed.get("class")
        ):

            raw_data = query_class_at_period(
                parsed["day"],
                parsed["period"]
            )

            chunks = format_timetable_chunks_v2(
                raw_data
            )

        # ----------------------------------------------------
        # NORMAL TIMETABLE
        # ----------------------------------------------------

        else:

            raw_data = query_timetable(
                parsed
            )

            chunks = format_timetable_chunks_v2(
                raw_data
            )

    # ========================================================
    # SUBJECTS
    # ========================================================

    elif intent == "subjects":

        # ----------------------------------------------------
        # CLASS TEACHER
        # ----------------------------------------------------

        if parsed.get(
            "is_class_teacher_query"
        ):

            chunks = query_class_teacher(
                parsed
            )

            if not chunks:

                cls = parsed.get(
                    "class",
                    "this class"
                )

                return {
                    "query": user_query,
                    "answer": (
                        f"No class teacher has "
                        f"been assigned for {cls} yet."
                    ),
                    "chunks_used": []
                }

            teach_keywords = [
                "teach",
                "take",
                "handle",
                "subject",
                "which subject",
                "what subject"
            ]

            if any(
                kw in user_query.lower()
                for kw in teach_keywords
            ):

                ct_chunk = chunks[0]["content"]

                faculty_name = (
                    ct_chunk
                    .split(" is ")[-1]
                    .rstrip(".")
                )

                subject_params = {
                    **parsed,
                    "faculty_name": faculty_name,
                    "class": None
                }

                raw_data = query_subjects(
                    subject_params
                )

                chunks = format_subject_chunks(
                    raw_data
                )

                if not chunks:

                    return {
                        "query": user_query,
                        "answer": (
                            f"{faculty_name} does not "
                            f"teach any subjects in "
                            f"the current semester."
                        ),
                        "chunks_used": []
                    }

        # ----------------------------------------------------
        # NORMAL SUBJECT QUERY
        # ----------------------------------------------------

        else:

            raw_data = query_subjects(
                parsed
            )

            chunks = format_subject_chunks(
                raw_data
            )

            if (
                not chunks
                and parsed.get("faculty_name")
            ):

                return {
                    "query": user_query,
                    "answer": (
                        f"{parsed['faculty_name']} "
                        f"do not teach any subjects "
                        f"in the current semester."
                    ),
                    "chunks_used": []
                }

            # ------------------------------------------------
            # ANY LAB
            # ------------------------------------------------

            if "any lab" in user_query.lower():

                chunks = [
                    c
                    for c in chunks
                    if "lab"
                    in c["content"]
                    .lower()
                    .split("(code:")[0]
                ]

                if not chunks:

                    return {
                        "query": user_query,
                        "answer": (
                            f"No, "
                            f"{parsed.get('faculty_name', 'this faculty')} "
                            f"does not teach any lab."
                        ),
                        "chunks_used": []
                    }

    # ========================================================
    # CALENDAR
    # ========================================================

    elif intent == "faculty":

        print(
            "PARAMS SENT TO QUERY_FACULTY:",
            parsed
        )

    # ----------------------------------------------------
    # DIRECT FIELD
    # ----------------------------------------------------

        if (
            parsed.get("direct_field")
            and parsed.get("faculty_name")
        ):

            direct_answer = get_faculty_direct_field(
            faculty_name=parsed["faculty_name"],
            field=parsed["direct_field"]
            )

            if direct_answer:
                return {
                    "query": user_query,
                    "answer": direct_answer,
                    "chunks_used": []
                }

    # ----------------------------------------------------
    # FACULTY SQL
    # ----------------------------------------------------

        raw_data = query_faculty(
            parsed
        )

    # ----------------------------------------------------
    # FORMAT FACULTY RESULTS
    # ----------------------------------------------------

        is_minimal = (
            bool(parsed.get("designation"))
            or bool(parsed.get("direct_field"))
        )

        is_compact = (
            parsed.get("is_list_query", False)
            or parsed.get("query_type") == "count"
        )

        chunks = format_faculty_chunks(
            raw_data,
            compact=is_compact,
            minimal=is_minimal
        )

    # ----------------------------------------------------
    # COUNT
    # ----------------------------------------------------

        # COUNT query: count directly from SQL, never let LLM count 
        if parsed.get("query_type") == "count":

            exact_count = len(raw_data)

            designation = (
            parsed.get("designation") or "").strip()

            department = (
                parsed.get("department") or ""
            ).strip()

            if designation:
                label = (
                    designation
                    if exact_count == 1
                    else designation + "s"
                )
            else:
                label = (
                    "faculty member"
                    if exact_count == 1
                    else "faculty members"
                )

            dept_suffix = (
                f" in the "
                f"{department.upper() if len(department) <= 4 else department.title()}"
                f" department"
                if department
                else ""
            )

            return {
                "query": user_query,
                "answer": (
                    f"There are "
                    f"{exact_count} "
                    f"{label}"
                    f"{dept_suffix}."
                ),
                "chunks_used": chunks
            }

        # LIST query: build answer in Python, never let LLM count
        if parsed.get("is_list_query"):

            exact_count = len(raw_data)

            designation = (
                parsed.get("designation") or ""
            ).strip()

            department = (
                parsed.get("department") or ""
            ).strip()

            label = (
                designation + "s"
                if designation
                else "faculty members"
            )

            dept_suffix = (
                f" in the "
                f"{department.upper() if len(department) <= 4 else department.title()}"
                f" department"
                if department
                else ""
            )

            names = "\n".join(
                f"{i + 1}. {r['name']}"
                for i, r in enumerate(raw_data)
            )

            answer = (
                f"There are "
                f"{exact_count} "
                f"{label}"
                f"{dept_suffix}:\n"
                f"{names}"
            )

            return {
                "query": user_query,
                "answer": answer,
                "chunks_used": chunks
            }
    # ========================================================
    # LAB
    # ========================================================

    elif intent == "lab":

        lab_query_type = parsed.get(
            "lab_query_type"
        )

        free_keywords = [
            "free",
            "occupied",
            "available",
            "busy"
        ]

        if any(
            w in user_query.lower()
            for w in free_keywords
        ):

            parsed[
                "is_lab_free_query"
            ] = True

        is_lab_free = parsed.get(
            "is_lab_free_query",
            False
        )

        # ----------------------------------------------------
        # LAB AVAILABILITY
        # ----------------------------------------------------

        if is_lab_free:

            lab_names = parsed.get(
                "lab_names"
            )

            if lab_names:

                chunks = []

                for lab in lab_names:

                    parsed_copy = {
                        **parsed,
                        "lab_name": lab
                    }

                    chunks.extend(
                        query_lab_availability(
                            parsed_copy
                        )
                    )

            else:

                chunks = query_lab_availability(
                    parsed
                )

        # ----------------------------------------------------
        # LAB DETAILS
        # ----------------------------------------------------

        elif lab_query_type == "detail":

            if parsed.get(
                "lab_keyword"
            ):

                chunks = query_lab_by_keyword(
                    parsed["lab_keyword"]
                )

            else:

                chunks = query_lab_embeddings(
                    parsed
                )

            if not chunks:

                chunks = retrieve_top_chunks(
                    user_query,
                    top_k
                )

        # ----------------------------------------------------
        # STRUCTURED LAB QUERY
        # ----------------------------------------------------

        else:

            raw_data = query_lab(
                parsed
            )

            # ------------------------------------------------
            # LIST LABS
            # ------------------------------------------------

            if (
                parsed.get("is_list_query")
                and not parsed.get("min_computers")
                and not parsed.get("max_computers")
            ):

                chunks = [
                    {
                        "content": (
                            f"{row.get('lab_name')} "
                            f"— Room "
                            f"{row.get('room_number')}"
                        ),
                        "metadata": {},
                        "similarity": 1.0
                    }
                    for row in raw_data
                ]

            # ------------------------------------------------
            # COMPUTER COUNT
            # ------------------------------------------------

            elif (
                parsed.get("min_computers")
                or parsed.get("max_computers")
            ):

                chunks = [
                    {
                        "content": (
                            f"{row.get('lab_name')} "
                            f"— Room "
                            f"{row.get('room_number')} "
                            f"— "
                            f"{row.get('no_of_computers')} "
                            f"computers"
                        ),
                        "metadata": {},
                        "similarity": 1.0
                    }
                    for row in raw_data
                ]

            # ------------------------------------------------
            # NORMAL LAB
            # ------------------------------------------------

            else:

                chunks = format_lab_chunks(
                    raw_data
                )

    # ========================================================
    # VECTOR / RAG
    # ========================================================

    else:

        chunks = retrieve_top_chunks(
            user_query,
            top_k
        )

    # ========================================================
    # RETRIEVAL DEBUG
    # ========================================================

    print(
        f"SQL TIME: "
        f"{time.time() - t2:.2f}s"
    )

    # --------------------------------------------------------
    # NO RESULTS
    # --------------------------------------------------------

    if not chunks and intent != "calendar":
        return {
            "query": user_query,
            "answer": (
                "No relevant information "
                "found in the knowledge base."
            ),
            "chunks_used": []
        }

    # --------------------------------------------------------
    # PRINT CHUNKS
    # --------------------------------------------------------

    print(
        "CHUNKS COUNT:",
        len(chunks)
    )

    for c in chunks:

        print(
            "CHUNK:",
            c["content"]
        )

    # ========================================================
    # CHOOSE PROMPT
    # ========================================================

    #
    # Everything except the `else` branch above is structured
    # retrieval.
    #
    # Therefore:
    #
    # timetable -> SQL prompt
    # subjects  -> SQL prompt
    # calendar  -> SQL prompt
    # faculty   -> SQL prompt
    # lab       -> SQL prompt
    #
    # general   -> RAG/vector prompt
    #

    if intent in {
        "timetable",
        "subjects",
        "calendar",
        "faculty",
        "lab"
    }:

        prompt = build_sql_prompt(
            user_query,
            chunks,
            params=parsed
        )

        prompt_type = "SQL"

    else:

        prompt = build_rag_prompt(
            user_query,
            chunks,
            params=parsed
        )

        prompt_type = "VECTOR/RAG"

    # ========================================================
    # LLM
    # ========================================================

    print(
        "PROMPT TYPE:",
        prompt_type
    )

    print(
        "LLM PROMPT LENGTH:",
        len(prompt)
    )

    t3 = time.time()
    answer = generate_llm_answer(prompt, chat_history=chat_history)
    print(f"LLM TIME: {time.time() - t3:.2f}s")
    print(f"TOTAL TIME: {time.time() - start:.2f}s")
    import re
    
    answer = re.sub(r'(\d)\n(\d)', r'\1\2', answer)

    answer = generate_llm_answer(
        prompt,
        chat_history=chat_history
    )

    print(
        f"LLM TIME: "
        f"{time.time() - t3:.2f}s"
    )

    print(
        f"TOTAL TIME: "
        f"{time.time() - start:.2f}s"
    )

    # ========================================================
    # FINAL CLEANUP
    # ========================================================

    # Fix numbers split across newlines
    # Example:
    # 3
    # 8
    # ->
    # 38

    answer = re.sub(
        r'(\d)\n(\d)',
        r'\1\2',
        answer
    )

    answer = answer.replace(
        "\n- ",
        ", "
    )

    answer = answer.replace(
        "\n",
        " "
    )

    answer = " ".join(
        answer.split()
    )

    # ========================================================
    # RETURN
    # ========================================================

    return {
        "query": user_query,
        "answer": answer,
        "chunks_used": chunks,
    }
