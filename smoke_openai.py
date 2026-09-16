from dotenv import load_dotenv
import os
from openai import OpenAI

load_dotenv()

key = os.getenv("OPENAI_API_KEY")

print("Key loaded:", bool(key))
print("Key length:", len(key) if key else 0)

client = OpenAI(api_key=key)

response = client.responses.create(
    model="gpt-5.6-luna",
    input="Reply with exactly: OPENAI API OK",
)

print("Model:", response.model)
print("Response:", response.output_text)