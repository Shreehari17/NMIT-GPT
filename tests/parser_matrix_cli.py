"""Run: python test_parser_matrix.py [old_prompt_module]  (needs Ollama + qwen3:8b running)
Compares only the keys listed in `expect`; missing key == null/false.
Run once with the OLD prompt and once with the NEW one, diff the PASS/FAIL columns."""
import sys, json, time, importlib, argparse
from openai import OpenAI

ap = argparse.ArgumentParser()
ap.add_argument("module", nargs="?", default="parser_prompt")
ap.add_argument("--case", type=int, default=None, help="run only this 1-based test number")
ap.add_argument("--reasoning-effort", default=None,
                help="if set (e.g. none), sent as top-level reasoning_effort in the request body, in addition to think:false")
args = ap.parse_args()
EXTRA = {"think": False}
if args.reasoning_effort:
    EXTRA["reasoning_effort"] = args.reasoning_effort  # extra_body keys are merged into the top-level JSON body
mod = importlib.import_module(args.module)
client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
HOD = "Recent conversation:\nUser: Who is the HOD of CSE department?\nAssistant: The HOD of CSE is Dr. Vijaya Shetty S.\n\nCurrent query:\n"
NOW = " (current day is Monday, current period is 3, current time slot is 11:00-11:55)"

T = [  # (query, expected-subset)
 # TIMETABLE
 ("who takes 3rd period for 6A on monday", dict(intent="timetable", **{"class": "6A"}, day="Monday", period="3")),
 ("schedule of 6A on Monday", dict(intent="timetable", **{"class": "6A"}, day="Monday", full_day_query=True)),
 ("free periods for 6A on Wednesday", dict(intent="timetable", **{"class": "6A"}, day="Wednesday", free_period_query=True)),
 ("what does 6D have now" + NOW, dict(intent="timetable", **{"class": "6D"}, day="Monday", period="3", full_day_query=False)),
 ("what does Dr. Sujatha teach this week", dict(intent="timetable", faculty_name="Sujatha", faculty_timetable_query=True)),
 ("when is DBMS for 6A", dict(intent="timetable", subject="database management system", **{"class": "6A"}, subject_schedule_query=True)),
 ("what is happening on Friday period 3", dict(day="Friday", period="3", **{"class": None})),
 # SUBJECTS
 ("who teaches DBMS to 6A", dict(intent="subjects", subject="database management system", **{"class": "6A"})),
 ("what subjects does sujatha take", dict(intent="subjects", faculty_name="Sujatha", subject=None)),
 ("what are the initials for big data technologies", dict(intent="subjects", subject="Big Data Technologies")),
 ("who handles game theory", dict(intent="subjects", subject="Game Theory")),
 ("who teaches aiml lab for 6A", dict(intent="subjects", subject="AI and ML Lab", **{"class": "6A"})),
 ("who teaches aiml", dict(intent="subjects", subject="Artificial Intelligence and Machine Learning")),
 ("what is the lab number for aiml lab 6D batch 3", dict(intent="subjects", subject="AI and ML Lab", **{"class": "6D-D3"})),
 ("which lab does 6D batch 2 use", dict(intent="subjects", **{"class": "6D-D2"})),
 ("class teacher of 6D", dict(intent="subjects", is_class_teacher_query=True, **{"class": "6D"})),
 ("6th sem subjects", dict(intent="subjects", **{"class": "6"})),
 ("who teaches 22CS61A", dict(intent="subjects", subject="22CS61A")),
 # FACULTY
 ("who is hod of cse", dict(intent="faculty", designation="head of department", department="CSE", faculty_name=None)),
 ("tell me more about deepthi mam", dict(intent="faculty", faculty_name="Deepthi")),
 ("Tell me more about her", dict(intent="faculty", faculty_name="Vijaya Shetty")),
 ("Deepthi email", dict(intent="faculty", faculty_name="Deepthi", direct_field="email")),
 ("Deepthi linkedin", dict(intent="faculty", faculty_name="Deepthi", direct_field="linkedin")),
 ("Deepthi google scholar", dict(intent="faculty", faculty_name="Deepthi", direct_field="google_scholar")),
 ("Deepthi orcid", dict(intent="faculty", faculty_name="Deepthi", direct_field="orcid")),
 ("Deepthi designation", dict(intent="faculty", faculty_name="Deepthi", direct_field="designation")),
 ("Deepthi experience", dict(intent="faculty", faculty_name="Deepthi", direct_field="experience")),
 ("list all faculty", dict(intent="faculty", is_list_query=True, designation=None)),
 ("list all assistant professors", dict(intent="faculty", designation="assistant professor", is_list_query=True)),
 ("how many professors", dict(intent="faculty", designation="professor", query_type="count")),
 ("Dileep Reddy sir", dict(faculty_name="Dileep Reddy")),
 # LAB
 ("which room is lab 9 in", dict(intent="lab", lab_name="LAB9", lab_query_type="structured")),
 ("what are the configurations of lab 9", dict(intent="lab", lab_name="LAB9", lab_query_type="detail")),
 ("how many computers does lab 5 have", dict(intent="lab", lab_name="LAB5", lab_query_type="structured")),
 ("labs with more than 30 computers", dict(intent="lab", lab_query_type="structured", min_computers=30, lab_name=None)),
 ("labs with i7 processors", dict(intent="lab", lab_query_type="detail", lab_keyword="i7", lab_name=None)),
 ("is lab 9 free at 10am on tuesday", dict(intent="lab", lab_name="LAB9", is_lab_free_query=True, day="Tuesday", period="2")),
 ("is lab 3 and lab 4 free on wednesday at 11am", dict(intent="lab", is_lab_free_query=True, lab_names=["LAB3", "LAB4"], lab_name=None, day="Wednesday", period="3")),
 ("is lab 11 occupied on Monday at 3:20", dict(intent="lab", lab_name="LAB11", is_lab_free_query=True, day="Monday", period="7")),
 # CALENDAR
 ("when is MSE-1", dict(intent="calendar", event_name="MSE-1")),
 ("When does MSE 2 start?", dict(intent="calendar", event_name="MSE-2")),
 ("when does sem end", dict(intent="calendar", event_name="Last Working Day")),
 ("when is cie ledger submission", dict(intent="calendar", event_name="CIE Ledger Submission")),
 ("gap between mse1 and mse2", dict(intent="calendar", event_name="MSE-1", event_name_2="MSE-2", query_type="gap")),
 ("how many days is MSE-1 and MSE-2", dict(intent="calendar", event_name="MSE-1", event_name_2="MSE-2", query_type="duration_each")),
 ("summer vacation duration", dict(intent="calendar", query_type="gap", event_name="Summer Vacations", event_name_2="Registration Odd (5th & 7th) Semester")),
 ("is there college on 2026-05-25 (Monday)", dict(intent="calendar", date="2026-05-25", is_college_open_query=True)),
 ("is there college on 2026-10-04 (Sunday)", dict(date="2026-10-04", is_college_open_query=True)),
 ("co curricular activity 2", dict(event_type="co_curricular", event_name=None, is_list_query=False)),
 # CIRCULAR
 ("dress code for girls in hostel", dict(intent="circular")),
 ("is there any circular about hostel timings", dict(intent="circular")),
 ("can boys wear shorts on campus", dict(intent="circular")),
 # EDGE
 ("who teaches CNS for 6A and 6B", dict(intent="subjects", subject="cryptography and network security", **{"class": None})),
 ("what class does 6A have on 2026-05-27 (Wednesday)", dict(date="2026-05-27", day="Wednesday", **{"class": "6A"})),
]
HIST_Q = {"Tell me more about her"}

def run(q):
    msgs = [{"role": "system", "content": mod.PARSE_SYSTEM_PROMPT}]
    msgs.append({"role": "user", "content": (HOD + q) if q in HIST_Q else q})
    r = client.chat.completions.create(model="qwen3:8b", messages=msgs, temperature=0,
                                       max_tokens=300, extra_body=EXTRA)
    global LAST
    LAST = r
    return r.choices[0].message.content

LAST = None

def dump_response(r):
    if r is None:
        print("DIAG: no response object"); return
    c = r.choices[0]; m = c.message
    print("DIAG model:", repr(getattr(r, "model", None)))
    print("DIAG choices:", repr(r.choices))
    print("DIAG message:", repr(m))
    print("DIAG finish_reason:", repr(c.finish_reason))
    print("DIAG content:", repr(m.content))
    print("DIAG message.model_extra:", repr(getattr(m, "model_extra", None)))
    for f in ("reasoning", "reasoning_content", "thinking", "refusal", "tool_calls"):
        print(f"DIAG message.{f}:", repr(getattr(m, f, "<absent>")))
    print("DIAG usage:", repr(getattr(r, "usage", None)))
    print("DIAG full response:", r.model_dump_json(indent=2) if hasattr(r, "model_dump_json") else repr(r))

cases = list(enumerate(T, 1))
if args.case is not None:
    cases = [c for c in cases if c[0] == args.case]
    if not cases:
        sys.exit(f"--case must be between 1 and {len(T)}")

ok = 0
for n, (q, exp) in cases:
    t0 = time.time()
    raw = None
    try:
        raw = run(q)
        t = (raw or "").strip().strip("`").removeprefix("json").strip()
        out = json.loads(t)
        bad = {k: (v, out.get(k)) for k, v in exp.items() if (out.get(k) or None) != (v if v not in (False,) else None)}
    except json.JSONDecodeError as e:
        out, bad = {}, {"error": str(e)}
        print(f"QUERY: {q}\nRAW MODEL OUTPUT: {raw!r}\nELAPSED: {time.time()-t0:.1f}s")
        dump_response(LAST)
    except Exception as e:
        out, bad = {}, {"error": str(e)}
        print(f"QUERY: {q}\nREQUEST ERROR (raw so far: {raw!r})\nELAPSED: {time.time()-t0:.1f}s")
    if args.reasoning_effort and LAST is not None:
        m = LAST.choices[0].message
        print(f"REQUEST extra_body: {EXTRA!r}")
        print(f"ELAPSED: {time.time()-t0:.1f}s")
        print(f"finish_reason: {LAST.choices[0].finish_reason!r}")
        print(f"content: {m.content!r}")
        print(f"reasoning: {getattr(m, 'reasoning', None)!r}")
        print(f"usage: {LAST.usage!r}")
    ok += not bad
    print(f"#{n}", ("PASS" if not bad else "FAIL"), f"{time.time()-t0:5.1f}s", q, "" if not bad else bad)
print(f"{ok}/{len(cases)} passed")