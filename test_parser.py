from openai import OpenAI
import time

client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama"
)

start = time.time()

response = client.chat.completions.create(
    model="qwen3:8b",
    messages=[
        {
            "role": "system",
            "content": "Return ONLY valid JSON. No explanation."
        },
        {
            "role": "user",
            "content": 'When is the MSE-1 exam?'
        }
    ],
    temperature=0,
    max_tokens=100,
    extra_body={"think": False}
)

print(response.choices[0].message.content)
print("TIME:", time.time() - start)