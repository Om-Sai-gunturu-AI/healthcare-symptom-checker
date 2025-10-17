# backend/app.py
import os
import json
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import google.generativeai as genai

# -------------------------------------------------------------------
# ✅ Load environment variables
# -------------------------------------------------------------------
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "models/gemini-2.5-flash")

if not GOOGLE_API_KEY:
    raise ValueError("❌ Missing GOOGLE_API_KEY in .env file")

print(f"✅ Loaded model: {GOOGLE_MODEL}")

# -------------------------------------------------------------------
# ✅ Configure Gemini
# -------------------------------------------------------------------
genai.configure(api_key=GOOGLE_API_KEY)

# -------------------------------------------------------------------
# ✅ FastAPI setup
# -------------------------------------------------------------------
app = FastAPI(title="Healthcare Symptom Checker (Educational Use)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------------------------------------------
# ✅ Input model
# -------------------------------------------------------------------
class SymptomInput(BaseModel):
    symptoms: str
    age: int | None = None
    duration: str | None = None

# -------------------------------------------------------------------
# ✅ Gemini query function
# -------------------------------------------------------------------
def get_health_response(symptoms: str, age: int = None, duration: str = None):
    model = genai.GenerativeModel(GOOGLE_MODEL)

    prompt = f"""
    You are a healthcare assistant bot for educational purposes only.
    Analyze the patient information and respond strictly in valid JSON.

    Patient Details:
    - Symptoms: {symptoms}
    - Age: {age}
    - Duration: {duration}

    Respond ONLY with this JSON object (compact, no new lines):
    {{
      "conditions": [list of 3 likely conditions],
      "next_steps": [list of 3 concise care steps],
      "urgency": one of ["self-care", "see GP", "urgent care", "ER now"],
      "disclaimer": "This is not a medical diagnosis. For educational purposes only."
    }}
    """

    try:
        result = model.generate_content(
            contents=[{"role": "user", "parts": [prompt]}],
            generation_config=genai.types.GenerationConfig(
                temperature=0.4,
                top_p=0.9,
                max_output_tokens=1024,  # 🔼 prevents truncation
                response_mime_type="application/json"
            ),
            safety_settings={
                "HARM_CATEGORY_SEXUAL": "BLOCK_NONE",
                "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
                "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
                "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
            },
        )

        # Extract text safely
        text = None
        if hasattr(result, "text") and result.text:
            text = result.text
        elif hasattr(result, "candidates") and result.candidates:
            candidate = result.candidates[0]
            if hasattr(candidate, "content") and candidate.content.parts:
                parts = [p.text for p in candidate.content.parts if hasattr(p, "text")]
                text = "".join(parts).strip() if parts else None

        if not text:
            return {"error": "⚠️ No text returned (possibly filtered). Try rephrasing."}

        return text

    except Exception as e:
        return {"error": f"⚠️ Gemini API Error: {str(e)}"}

# -------------------------------------------------------------------
# ✅ JSON repair helper
# -------------------------------------------------------------------
def fix_truncated_json(s: str):
    s = s.strip()
    # Add missing braces/brackets/quotes if truncated
    while s.count("{") > s.count("}"):
        s += "}"
    while s.count("[") > s.count("]"):
        s += "]"
    if s.count('"') % 2 == 1:
        s += '"'
    return s

# -------------------------------------------------------------------
# ✅ Routes
# -------------------------------------------------------------------
@app.get("/")
def home():
    return {"status": "ok", "message": "Use POST /check to analyze symptoms."}

@app.post("/check")
def check_symptoms(data: SymptomInput):
    try:
        raw_result = get_health_response(data.symptoms, data.age, data.duration)

        # Handle cases where get_health_response returns dict or string
        if isinstance(raw_result, dict):
            parsed = raw_result
        else:
            text = fix_truncated_json(raw_result)

            def attempt_parse(s: str):
                start = s.find("{")
                end = s.rfind("}")
                if start == -1:
                    return {"raw_text": s}
                s = s[start : (end + 1) if end != -1 else len(s)]
                try:
                    return json.loads(s)
                except json.JSONDecodeError:
                    s = fix_truncated_json(s)
                    try:
                        return json.loads(s)
                    except Exception:
                        return {"raw_text": s}

            parsed = attempt_parse(text)

        return JSONResponse(
            content={
                "input": data.dict(),
                "result": parsed,
            },
            status_code=200,
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Server Error: {str(e)}"},
        )
