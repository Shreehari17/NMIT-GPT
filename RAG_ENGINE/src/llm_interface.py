
import os
from dotenv import load_dotenv
from openai import OpenAI
from datetime import datetime

load_dotenv()

MODEL = os.getenv("LOCAL_LLM_MODEL", "qwen3:8b")
OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL",
    "http://localhost:11434/v1"
)

client = OpenAI(
    base_url=OLLAMA_BASE_URL,
    api_key="ollama"
)


def generate_llm_answer(prompt: str, chat_history: list = None) -> str:

    today = datetime.now().strftime("%A, %B %d, %Y")

    messages = [
        {
            "role": "system",
            "content": f"""You are NMIT-GPT, an academic assistant
for students of NMIT college.

Your job is to answer questions about timetables, subjects,
faculty, exams, and college calendar.

Always reason carefully from the provided context.
Today's date is {today}.

'Who takes', 'who teaches', 'who handles' all mean the same.
Find the faculty name from the provided context.

Never invent information.
Never refuse to answer if the context contains relevant information.

Maintain context from conversation history.
Pronouns like he, she, they, her and him refer to people
mentioned earlier.

Be concise and direct."""
        }
    ]

    if chat_history:
        messages.extend([
            {
                "role": m["role"],
                "content": m["content"][:500]
            }
            for m in chat_history[-4:]
            if m["role"] in ("user", "assistant")
        ])

    messages.append({
        "role": "user",
        "content": prompt
    })

    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0,
        max_tokens=1200
    )

    return response.choices[0].message.content or ""
