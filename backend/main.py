"""FastAPI backend for the LaTeX resume generator."""

import asyncio
import json
import os

import google.generativeai as genai
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from database import connect_db

load_dotenv()

GEMINI_TIMEOUT_SECS = 60

app = FastAPI(title="LaTeX Resume Generator API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event() -> None:
    await connect_db()


class ScoreRequest(BaseModel):
    resumeData: dict
    jd: str


def _trim(value, max_len: int) -> str:
    if not isinstance(value, str):
        return ""
    v = value.strip()
    return v if len(v) <= max_len else v[: max_len - 3] + "..."


def _compact_list(items, max_items: int, max_len: int) -> list[str]:
    if not isinstance(items, list):
        return []
    return [s for s in (_trim(i, max_len) for i in items[:max_items]) if s]


def build_compact_resume(resume: dict) -> dict:
    return {
        "personalInfo": {
            "name": _trim(resume.get("personalInfo", {}).get("name"), 120),
            "course": _trim(resume.get("personalInfo", {}).get("course"), 120),
            "github": _trim(resume.get("personalInfo", {}).get("github"), 120),
            "linkedin": _trim(resume.get("personalInfo", {}).get("linkedin"), 120),
        },
        "education": [
            {
                "degree": _trim(e.get("degree"), 120),
                "institution": _trim(e.get("institution"), 120),
                "score": _trim(e.get("score"), 80),
                "dates": _trim(e.get("dates"), 40),
            }
            for e in (resume.get("education") or [])[:4]
        ],
        "experience": [
            {
                "role": _trim(e.get("role"), 120),
                "company": _trim(e.get("company"), 120),
                "locationType": _trim(e.get("locationType"), 60),
                "dates": _trim(e.get("dates"), 40),
                "bullets": _compact_list(e.get("bullets"), 3, 180),
            }
            for e in (resume.get("experience") or [])[:4]
        ],
        "projects": [
            {
                "title": _trim(e.get("title"), 120),
                "description": _trim(e.get("description"), 180),
                "technologies": _trim(e.get("technologies"), 180),
                "dates": _trim(e.get("dates"), 40),
                "bullets": _compact_list(e.get("bullets"), 3, 180),
            }
            for e in (resume.get("projects") or [])[:5]
        ],
        "skills": [
            {
                "category": _trim(e.get("category"), 80),
                "skills": _trim(e.get("skills"), 180),
            }
            for e in (resume.get("skills") or [])[:10]
        ],
        "careerVault": [
            {
                "type": _trim(e.get("type"), 40),
                "title": _trim(e.get("title"), 120),
                "subtitle": _trim(e.get("subtitle"), 120),
                "description": _trim(e.get("description"), 220),
                "technologies": _trim(e.get("technologies"), 180),
                "dates": _trim(e.get("dates"), 40),
            }
            for e in (resume.get("careerVault") or [])[:10]
        ],
    }


@app.post("/api/score")
async def score_resume(body: ScoreRequest):
    if not body.jd.strip():
        raise HTTPException(status_code=400, detail="Job Description is required.")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not configured on the server.")

    compact = build_compact_resume(body.resumeData)
    active_resume_text = json.dumps(
        {k: compact[k] for k in ("personalInfo", "education", "experience", "projects", "skills")},
        indent=2,
    )
    vault_text = json.dumps(compact["careerVault"], indent=2)

    prompt = f"""ATS Resume Optimizer. Output JSON only. No preamble.

RULES:
- score: 0-100 ATS match. Be strict.
- missingSkills: tools/frameworks in JD absent from resume (max 8).
- missingKeywords: action verbs/methodologies missing (max 8).
- summary: 2 sentences max.
- suggestedModifications: max 6 targeted changes.
  - actions: append_skills | insert_bullet | replace_bullet | add_item | modify_item
  - ALL bullet suggestedContent MUST include a % / $ / hrs / x metric.
  - Prefer vault items over AI crafting. Mark AI-crafted ones in archiveItemSource.
  - append_skills -> add to skills section only; add_item -> new project/experience entry.

RESUME:
{active_resume_text}

JD:
{body.jd[:3000]}

VAULT:
{vault_text}
"""

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        "gemini-2.0-flash",
        generation_config=genai.types.GenerationConfig(
            response_mime_type="application/json",
            max_output_tokens=2048,
        ),
    )

    loop = asyncio.get_event_loop()
    try:
        response = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: model.generate_content(prompt)),
            timeout=GEMINI_TIMEOUT_SECS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=f"Gemini request timed out after {GEMINI_TIMEOUT_SECS} seconds.")

    if not response.text:
        raise HTTPException(status_code=500, detail="Empty response received from Gemini.")

    try:
        return json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to parse Gemini response: {exc}")


@app.get("/api/health")
async def health():
    return {"status": "healthy"}


@app.exception_handler(Exception)
async def global_exception_handler(_, exc):
    print("Unhandled backend error:", exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})
