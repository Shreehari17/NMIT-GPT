import os
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

ANSWER_PROVIDER = os.getenv("ANSWER_PROVIDER", "groq").lower()

if ANSWER_PROVIDER == "ollama":
    from openai import OpenAI

    MODEL = os.getenv("ANSWER_MODEL", "qwen3:8b")

    client = OpenAI(
        base_url=os.getenv(
            "OLLAMA_BASE_URL",
            "http://127.0.0.1:11434/v1"
        ),
        api_key=os.getenv("OLLAMA_API_KEY", "ollama"),
        timeout=float(os.getenv("OLLAMA_TIMEOUT", "120")),
        max_retries=0,
    )

elif ANSWER_PROVIDER == "groq":
    from groq import Groq

    MODEL = os.getenv(
        "GROQ_LLM_MODEL",
        "openai/gpt-oss-120b"
    )

    api_key = os.getenv("GROQ_API_KEY_ANSWER")

    if not api_key:
        raise ValueError(
            "GROQ_API_KEY_ANSWER is required "
            "when ANSWER_PROVIDER=groq"
        )

    client = Groq(api_key=api_key)

else:
    raise ValueError(
        f"Unsupported ANSWER_PROVIDER: {ANSWER_PROVIDER}"
    )


def generate_llm_answer(
    prompt: str,
    chat_history: list = None
) -> str:

    today = datetime.now().strftime("%A, %B %d, %Y")

    messages = [
        {
            "role": "system",
            "content": (
                "You are NMIT-GPT, an academic assistant "
                "for students of NMIT college.\n"
                "Answer questions using only the supplied "
                "college context.\n"
                "Do not invent facts.\n"
                f"Today's date is {today}.\n"
                "Maintain conversational context.\n"
                "Be concise and direct."
            ),
        }
    ]

    if chat_history:
        for message in chat_history[-4:]:
            if message.get("role") not in (
                "user", "assistant"
            ):
                continue

            messages.append({
                "role": message["role"],
                "content": str(
                    message.get("content", "")
                )[:500],
            })

    messages.append({
        "role": "user",
        "content": prompt,
    })

    if ANSWER_PROVIDER == "ollama":
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=900,
            temperature=0,
            extra_body={
                "think": False,
            },
        )

    else:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_completion_tokens=1200,
            reasoning_effort="low",
        )

    answer = response.choices[0].message.content

    if not answer:
        raise RuntimeError(
            "LLM returned an empty answer."
        )

    return answer.strip()
