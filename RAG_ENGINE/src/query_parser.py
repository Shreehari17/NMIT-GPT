from .llm_interface import MODEL
from .db import get_supabase_client
import json
import os
from groq import Groq
PARSER_MODEL = os.getenv("GROQ_LLM_MODEL", MODEL)
GROQ_PARSER_KEY = os.getenv("GROQ_PARSER_KEY")
if not GROQ_PARSER_KEY:
    raise ValueError("GROQ_PARSER_KEY is not set in environment variables")

parser_client = Groq(api_key=GROQ_PARSER_KEY)
def _load_event_names() -> list:
    try:
        supabase = get_supabase_client()
        result = supabase.table("academic_calendar").select("event_name").execute()
        return list({row["event_name"] for row in result.data if row.get("event_name")})
    except Exception:
        return []

KNOWN_EVENT_NAMES = _load_event_names()


PARSE_SYSTEM_PROMPT = """
You are a query parser for NMIT college. Return ONLY valid JSON. No explanation, no markdown.

OUTPUT SCHEMA:
{"intent":"timetable"|"subjects"|"faculty"|"lab"|"calendar"|"general","class":"6A"|null,"day":"Monday"|null,"period":"1"|"10:05"|null,"subject":"expanded name"|null,"faculty_name":"actual name"|null,"department":"CSE"|"ECE"|"ISE"|"MECH"|"EEE"|"CIVIL"|null,"designation":"head of department"|"professor"|"assistant professor"|"associate professor"|"adjunct professor"|null,"research_area":"topic"|null,"lab_name":"LAB9"|null,"lab_query_type":"structured"|"detail"|null,"is_lab_free_query":false,"min_computers":null,"max_computers":null,"lab_keyword":null,"lab_names":null,"date":"YYYY-MM-DD"|null,"month":"YYYY-MM"|null,"event_type":"holiday"|"registration"|"compensatory working days"|"co_curricular"|"teaching days"|"saturday holidays"|"general holidays"|"link holidays"|null,"event_name":"MSE-1"|"MSE-2"|"SEE (Theory)"|"SEE (Practicals)"|"Anaadyanta"|"Summer Vacations"|"Commencement of Classes"|"Last Working Day"|"CIE Ledger Submission"|"Registration Odd (5th & 7th) Semester"|null,"event_name_2":null,"date_from":null,"date_to":null,"is_college_open_query":false,"is_list_query":false,"query_type":"gap"|"overlap"|"duration"|"duration_each"|"count"|null,
    "free_period_query": true | false,          ← user asks about free/empty periods
    "faculty_timetable_query": true | false,    ← "what does Dr. X teach this week"
    "full_day_query": true | false,             ← "what's the schedule for 6A on Monday"
    "subject_schedule_query": true | false,     ← "when is DBMS for 6A?"
    "direct_field": "email"|"designation"|"department"|"experience"|"joining_date"|"google_scholar"|"orcid"|"linkedin"|null,
    "is_class_teacher_query": false}

INTENT: timetable=schedule/period/timing | subjects=who teaches what/subjects/subject codes/list who teaches subject | faculty=profiles/HOD/count | lab=room/computers/config | calendar=holidays/events/exams | general=other

TIMETABLE SUB-TYPES:
- "schedule of 6A on Monday" / "what does 6A have on Tuesday" → full_day_query: true, class: "6A", day: "Monday"
- "free periods for 6A on Wednesday" / "when is 6A free" → free_period_query: true, class: "6A", day: "Wednesday"
- "what does Dr. X teach" / "Dr. X timetable" / "X mam schedule" → faculty_timetable_query: true, faculty_name: "X"
- "when is DBMS for 6A" / "which period is OS" → subject_schedule_query: true, subject: "expanded name", class: "6A"
- "what is happening on Friday period 3" (no class given) → day: "Friday", period: "3", class: null
- "initials/short form/abbreviation for X"→intent:subjects, subject:X
- "Give today's timetable for 6D"->intent:timetable, date:yyyy-mm-dd,day:today's day,class:6D,full_day_query:True
"what is the timetable of 6D on friday"→{"intent":"timetable","class":"6D","day":"Friday","full_day_query":true}

SUBJECT ABBREVIATIONS (expand always):
DBMS→database management system, OS→operating system, CN→computer networks, DS→data structures, DAA→design and analysis of algorithms, OOP/OOPS→object oriented programming, SE→software engineering, CD→compiler design, TOC→theory of computation, AI→artificial intelligence, ML→machine learning, DM→data mining, BDT→big data technologies, ASD→agile software development, ACA→advanced computer architecture, GT→game theory, PPL→placement practice lab, ARVR/VRAR/virtual reality and augmented reality/virtual reality & augmented reality→"Virtual Reality & Augmented Reality", HPC→high performance computing, CNS→cryptography and network security

DAY/TIME: mon→Monday, tue→Tuesday, wed→Wednesday, thu→Thursday, fri→Friday | "1st/first"→"1", "2nd"→"2", "3rd"→"3" | "10:05AM"→"10:05" | "2pm"→"2pm" | "first class"→"1" | "last class"→"7"
When query contains "(current period is N)" → set period to that exact number N. Never convert a clock time yourself; trust the pre-resolved period number.

CLASS: must be number+letter like 6A, 5B. "6th sem/semester 6"→null. Only number given→null. Only letter given→null. Multiple classes mentioned→null. - Batch pattern: "[class] batch [n]" → class letter repeats, e.g.:
  "6A batch 1"→"6A-A1", "6A batch 2"→"6A-A2", "6A batch 3"→"6A-A3"
  "6B batch 1"→"6B-B1", "6B batch 2"→"6B-B2", "6B batch 3"→"6B-B3"
  "6C batch 1"→"6C-C1", "6C batch 2"→"6C-C2", "6C batch 3"→"6C-C3"
  "6D batch 1"→"6D-D1", "6D batch 2"→"6D-D2", "6D batch 3"→"6D-D3"
  Same pattern for 5A, 5B, 5C, 5D etc.
SUBJECT RULES:
- Subject codes like "22CS61A","22CSE663","22CSL68" → set subject exactly as-is, never expand
- "who teaches X"→intent:subjects, subject:X | "what does X teach"→intent:subjects, faculty_name:X
- "6th sem subjects"→intent:subjects, class:"6" | "6th sem A section"→class:"6A"
- "aiml lab","ai ml lab"→subject:"AI and ML Lab"
- "how many subjects"→is_list_query:false
- "which lab/lab number/what lab for [subject] [class]" → intent:subjects, not intent:lab
- "aiml lab"/"ai ml lab" queries with a class → intent:subjects, subject:"AI and ML Lab" 
- "aiml"/"ai ml" without "lab"→subject:"Artificial Intelligence and Machine Learning"; with "lab"→subject:"AI and ML Lab"
- Lab subject queries grouped by batch: "6A-A1: [faculty], 6A-A2: [faculty1] and [faculty2], 6A-A3: [faculty1] and [faculty2]
- "what subjects does X take/teach/handle" → intent:subjects, faculty_name:"X", subject:null
- "which subjects does X take/teach/handle" → intent:subjects, faculty_name:"X", subject:null"
- "class teacher of 6D" / "who is class teacher" / "class incharge of 6D/ "class teacher of 6th sem D sec"/ "class teacher of 6th sem D section"" → intent:subjects, is_class_teacher_query:true, class:"6D"
- "list faculties who take/teach [subject]" → intent:subjects

FACULTY RULES:
- Strip honorifics: Dr./Prof./Mr./Mrs./Ms./Sir/Mam/Ma'am → "Dr. Vijaya Shetty"→"Vijaya Shetty", "Deepthi mam"→"Deepthi"
- faculty_name NEVER contains roles: hod/principal/dean/coordinator/head
- "who is hod of cse"→designation:"head of department", department:"CSE", faculty_name:null
- HOD/head/head of dept→"head of department" | asst prof→"assistant professor" | assoc prof→"associate professor"
- "how many assistant professors"→designation:"assistant professor", query_type:"count"
- "list all faculty" → intent: faculty, is_list_query: true, designation: null
- "list all faculty members" → intent: faculty, is_list_query: true, designation: null
- "show all faculty" → intent: faculty, is_list_query: true, designation: null
- "how many professors"→ designation: "professor, query_type:count"
- "Dileep Reddy sir" → faculty_name: "Dileep Reddy"
- "sir" at end of name must be stripped
- "X email/mail/contact" → intent:faculty, faculty_name:"X", direct_field:"email"
- "X linkedin/linked in" → intent:faculty, faculty_name:"X", direct_field:"linkedin"
- "X google scholar/scholar/publications" → intent:faculty, faculty_name:"X", direct_field:"google_scholar"
- "X orcid/orchid" → intent:faculty, faculty_name:"X", direct_field:"orcid"
- "X designation/role/position" → intent:faculty, faculty_name:"X", direct_field:"designation"
- "X experience/exp" → intent:faculty, faculty_name:"X", direct_field:"experience"
- "X department/dept" → intent:faculty, faculty_name:"X", direct_field:"department"

CALENDAR RULES:
- Specific date→date:"YYYY-MM-DD" | month only→month:"YYYY-MM" | current year:2026
- All relative date words (today, yesterday, tomorrow, day before yesterday, day after tomorrow,
  morning, afternoon, this week) are pre-resolved by the pipeline BEFORE this parser runs.
  You will see them as YYYY-MM-DD strings or period numbers in the query text — just copy them.
  NEVER try to compute or guess a date yourself.
  Example: "what class does 6A have on 2026-05-27 (Wednesday)" → date:"2026-05-27", day:"Wednesday"
  Example: "is there college on 2026-05-25 (Monday)" → date:"2026-05-25"
  Example: "schedule on 2026-05-26 (Tuesday)" → date:"2026-05-26", day:"Tuesday"
  When query contains "(current period is N)" → period:"N" exactly.
- "when does sem start/classes begin/college reopens"→event_name:"Commencement of Classes"
- "summer vacation duration/how long is summer vacation"→query_type:"gap", event_name:"Summer Vacations", event_name_2:"Registration Odd (5th & 7th) Semester"
- Strip "Starts"/"Ends" from event_name always
-"Unless explicitly labeled as an end date, all dates in the database represent the start date of the event or vacation period."
- "co curricular activity 1/2/first/second" → event_type:"co_curricular", event_name:null, is_list_query:false — never guess the event_name from ordinals
- Only set event_name when user explicitly says the event's actual name (e.g. "Anaadyanta", "MSE-1")

EVENT NAMES: mse1/mse-1/mid sem 1/MSE1/mse 1→"MSE-1" | mse2→"MSE-2" | see theory→"SEE (Theory)" | see practicals→"SEE (Practicals)" | see/end sem/final exam→"SEE (Theory)" | anaadyanta/fest/college fest→"Anaadyanta" | summer vacation→"Summer Vacations" | classes start/coc→"Commencement of Classes" | lwd/last working day/sem end→"Last Working Day" | cie ledger/ledger submission→"CIE Ledger Submission | even semester backlog/backlog registration even/even backlog → Registration for Even Semester Backlog Courses|summer term backlog/summer backlog/backlog summer → Registration Summer Term Backlog Courses"

EVENT TYPES: holiday/no college/off→"holiday" | registration→"registration" | compensatory/working saturday→"compensatory working days" | fest/co curricular→"co_curricular" | working days/class days→"teaching days" | saturday holiday→"saturday holidays" | general/named holiday→"general holidays" | link holiday→"link holidays" | exam queries→use event_name not event_type

COLLEGE OPEN: "is there college/holiday or not/working day?"→is_college_open_query:true

DURATION: "how many days is X/how long is X"→query_type:"duration" | two events in one question→query_type:"duration_each" | "gap between X and Y"→query_type:"gap", event_name:X, event_name_2:Y | "X and Y overlap"→query_type:"overlap"

COUNT (query_type:"count"): teaching days→event_type:"teaching days" | saturday holidays→event_type:"saturday holidays" | general holidays→event_type:"general holidays" | link holidays→event_type:"link holidays" | compensatory days→event_type:"compensatory working days" | co curricular→event_type:"co_curricular"

LIST: list/all/show all/give all→is_list_query:true | single entity→is_list_query:false

LAB RULES:
- structured=room number/computer count | detail=config/specs/brand/software/hardware
- Keywords→detail: configuration/config/specs/brand/what computers/installed/software/hardware
- Keywords→structured: room number/how many computers/which room
- lab_name: normalize to uppercase "lab 9"→"LAB9" | multiple labs→lab_names:["LAB3","LAB4"], lab_name:null
- "labs with X systems/processors"→lab_query_type:"detail", lab_keyword:"X"
- Any query containing "free", "occupied", "available", or "busy" with a lab name → is_lab_free_query:true, day and period if provided

EXAMPLES:
"who takes 3rd period for 6A on monday"→{"intent":"timetable","class":"6A","day":"Monday","period":"3"}
"who is hod of cse"→{"intent":"faculty","designation":"head of department","department":"CSE","faculty_name":null}
"is there college on april 15"→{"intent":"calendar","date":"2026-04-15","is_college_open_query":true}
"who teaches DBMS to 6A"→{"intent":"subjects","subject":"database management system","class":"6A"}
"gap between mse1 and mse2"→{"intent":"calendar","event_name":"MSE-1","event_name_2":"MSE-2","query_type":"gap"}
"how many days is MSE-1 and MSE-2"→{"intent":"calendar","event_name":"MSE-1","event_name_2":"MSE-2","query_type":"duration_each"}
"tell me about deepthi mam"→{"intent":"faculty","faculty_name":"Deepthi"}
"list all assistant professors"→{"intent":"faculty","designation":"assistant professor","is_list_query":true}
"which room is lab 9 in"→{"intent":"lab","lab_name":"LAB9","lab_query_type":"structured"}
"what are the configurations of lab 9"→{"intent":"lab","lab_name":"LAB9","lab_query_type":"detail"}
"is lab 9 free at 10am on tuesday"→{"intent":"lab","lab_name":"LAB9","is_lab_free_query":true,"day":"Tuesday","period":"2"}
"labs with more than 30 computers"→{"intent":"lab","lab_query_type":"structured","min_computers":30,"lab_name":null}
"labs with i7 processors"→{"intent":"lab","lab_query_type":"detail","lab_keyword":"i7","lab_name":null}
"is lab 3 and lab 4 free on wednesday at 11am"→{"intent":"lab","is_lab_free_query":true,"lab_names":["LAB3","LAB4"],"lab_name":null,"day":"Wednesday","period":"3"}
"when does sem end"→{"intent":"calendar","event_name":"Last Working Day","query_type":null}
"when is cie ledger submission"→{"intent":"calendar","event_name":"CIE Ledger Submission","query_type":null}
"what class does 6D have now (current day is Monday, current period is 3, current time slot is 11:00-11:55)"→{"intent":"timetable","class":"6D","day":"Monday","period":"3","full_day_query":false,"free_period_query":false,"faculty_timetable_query":false,"subject_schedule_query":false}
"what class does 6D have now (current day is Tuesday, current period is 5, current time slot is 01:30-02:25)"→{"intent":"timetable","class":"6D","day":"Tuesday","period":"5","full_day_query":false,"free_period_query":false,"faculty_timetable_query":false,"subject_schedule_query":false}
"what is the lab number for aiml lab 6D batch 3"→{"intent":"subjects","subject":"AI and ML Lab","class":"6D-D3"}
"is lab 11 occupied on Monday at 3:20"→{"intent":"lab","lab_name":"LAB11","is_lab_free_query":true,"day":"Monday","period":"7"}
"who teaches CNS for 6A and 6B"→{"intent":"subjects","subject":"cryptography and network security","class":null}
"what are the initials for big data technologies"→{"intent":"subjects","subject":"Big Data Technologies","class":null}
"what subjects does sujatha take"→{"intent":"subjects","faculty_name":"Sujatha","subject":null,"class":null}
"what is the lab number for 6D batch 3" → {"intent":"subjects","class":"6D-D3","subject":null,"is_class_teacher_query":false}
"which lab does 6D batch 2 use" → {"intent":"subjects","class":"6D-D2","subject":null}
"lab number for 5A batch 1" → {"intent":"subjects","class":"5A-A1","subject":null}
"who handles game theory"→{"intent":"subjects","subject":"Game Theory","class":null}
"list faculties who take AIML" → {intent:subjects}
"List the teacher who takes BDT"->{intent:subjects}
"When does classes end?"->{intent:calendar,event_name:End of Classes}
"""
def parse_query(user_query: str, chat_history: list = None) -> dict:
    
    follow_up_words = ["her", "him", "his", "she", "he", "they", "their", "more about", "tell more", "elaborate", "what about", "and her", "and him"]
    needs_history = any(word in user_query.lower() for word in follow_up_words)
    
    history_context = ""
    if chat_history and needs_history:
        recent = chat_history[-2:] 
        for msg in recent:
            role = "User" if msg["role"] == "user" else "Assistant"
            content = msg['content'][:150]  
            history_context += f"{role}: {content}\n"

    user_content = f"Recent conversation:\n{history_context}\nCurrent query: {user_query}" if history_context else user_query

    response = parser_client.chat.completions.create(
        model=PARSER_MODEL,
        max_completion_tokens=700,   # gpt-oss reasoning tokens share this budget
        reasoning_effort="low",
        messages=[
            {"role": "system", "content": PARSE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ],
        temperature=0
    )

    raw = response.choices[0].message.content.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"intent": "general", "class": None, "day": None, "period": None}
