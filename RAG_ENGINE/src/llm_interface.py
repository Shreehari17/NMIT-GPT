from groq import Groq
from dotenv import load_dotenv
import os

load_dotenv()


MODEL = os.getenv("GROQ_LLM_MODEL", "llama-3.1-8b-instant")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY is not set in environment variables")

client = Groq(api_key=GROQ_API_KEY)


def generate_llm_answer(prompt: str, chat_history: list = None) -> str:
    from datetime import datetime
    today = datetime.now().strftime("%A, %B %d, %Y")

    messages = [
        {
            "role": "system",
            "content": f"""You are NMIT-GPT, an academic assistant for students of NMIT college.
Your job is to answer questions about timetables, subjects, faculty, exams, and college calendar.
Always reason carefully from the provided context.
Today's date is {today}.
'Who takes', 'who teaches', 'who handles' all mean the same — find the faculty name from the context and return it.
Never refuse to answer if the context contains relevant information.
Maintain context from the conversation history — pronouns like "he", "she", "they", "her", "him" refer to people mentioned earlier.
Be concise and direct."""
        }
    ]

    if chat_history:
        chat_history = chat_history[-4:]
        chat_history = [
            {"role": m["role"], "content": m["content"][:500]}
            for m in chat_history
        ]
        messages.extend(chat_history)

    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(  # uses GROQ_API_KEY_ANSWER
        model=MODEL,
        max_completion_tokens=1200,  
        reasoning_effort="low",       
        messages=messages,
    )
    return response.choices[0].message.content