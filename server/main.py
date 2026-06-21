"""FastAPI backend for the LaTeX resume generator."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import json
import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from google import genai
from google.genai import types
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
import jwt
from jwt import PyJWKClient
from pydantic import BaseModel

from database import connect_db, users_col

load_dotenv()

GEMINI_TIMEOUT_SECS = 60


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    yield


app = FastAPI(title="LaTeX Resume Generator API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SuggestedModificationDetails(BaseModel):
    title: Optional[str] = None
    subtitle: Optional[str] = None
    dates: Optional[str] = None
    technologies: Optional[str] = None
    bullets: Optional[list[str]] = None
    description: Optional[str] = None


class SuggestedModification(BaseModel):
    section: str
    itemId: str
    action: str
    bulletIndex: Optional[int] = None
    explanation: str
    originalContent: Optional[str] = None
    suggestedContent: str
    archiveItemSource: str
    itemDetails: Optional[SuggestedModificationDetails] = None


class ATSScoringResponse(BaseModel):
    score: int
    summary: str
    missingSkills: list[str]
    missingKeywords: list[str]
    suggestedModifications: list[SuggestedModification]


class GeneratedProject(BaseModel):
    title: str
    description: str
    technologies: str
    bullets: list[str]
    dates: str

class GeneratedExperience(BaseModel):
    role: str
    company: str
    locationType: str
    dates: str
    bullets: list[str]

class GeneratedSkills(BaseModel):
    category: str
    skills: str

class AIHelperResponse(BaseModel):
    section: str
    project: Optional[GeneratedProject] = None
    experience: Optional[GeneratedExperience] = None
    skills: Optional[GeneratedSkills] = None

class AIHelperRequest(BaseModel):
    prompt: str
    section: str

class ScoreRequest(BaseModel):
    resumeData: dict
    jd: str


class ProfileSaveRequest(BaseModel):
    resumeData: dict
    settings: dict


security = HTTPBearer()

CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "sk_test_TWPWnvnIN8vu42aGuNcpDLQ3LxX6f6KyW4DkseZlTV")
CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL", "https://worthy-magpie-21.clerk.accounts.dev/.well-known/jwks.json")

jwks_client = PyJWKClient(CLERK_JWKS_URL)


async def get_current_user_id(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    token = credentials.credentials
    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            options={"verify_aud": False}
        )
        return payload["sub"]
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Unauthorized: {e}")


async def fetch_clerk_profile(clerk_id: str) -> dict:
    try:
        async with httpx.AsyncClient() as client:
            headers = {"Authorization": f"Bearer {CLERK_SECRET_KEY}"}
            res = await client.get(f"https://api.clerk.com/v1/users/{clerk_id}", headers=headers)
            if res.status_code == 200:
                data = res.json()
                email = data.get("email_addresses", [{}])[0].get("email_address", "")
                name = f"{data.get('first_name', '')} {data.get('last_name', '')}".strip()
                picture = data.get("image_url", "")
                return {"email": email, "name": name, "picture": picture}
    except Exception as err:
        print("Clerk profile fetch warning:", err)
    return {"email": "", "name": "", "picture": ""}


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
                "id": str(e.get("id", "")),
                "degree": _trim(e.get("degree"), 120),
                "institution": _trim(e.get("institution"), 120),
                "score": _trim(e.get("score"), 80),
                "dates": _trim(e.get("dates"), 40),
            }
            for e in (resume.get("education") or [])[:4]
        ],
        "experience": [
            {
                "id": str(e.get("id", "")),
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
                "id": str(e.get("id", "")),
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
                "id": str(e.get("id", "")),
                "category": _trim(e.get("category"), 80),
                "skills": _trim(e.get("skills"), 180),
            }
            for e in (resume.get("skills") or [])[:10]
        ],
        "careerVault": [
            {
                "id": str(e.get("id", "")),
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

    system_prompt = """You are an expert AI Resume Maker and Strategic Career Advisor.
Your goal is to deeply analyze the candidate's RESUME against the JOB DESCRIPTION (JD) and provide ACTIONABLE, highly tailored recommendations.
Do not just act as a passive ATS grader. Act as a proactive resume builder and advisor.
Even if the candidate seems like a strong fit, you MUST identify areas for optimization, suggest new content, and tailor existing bullet points to perfectly align with the JD's specific keywords and priorities.

CRITICAL DIRECTIVES:
1. "summary": Provide a strategic "Gap Analysis" explaining exactly what the candidate needs to change to perfectly match the role. Do not just summarize what they already have. Focus on the missing links. (Max 3 sentences).

2. "missingSkills" & "missingKeywords": ALWAYS identify at least 3-5 specific skills and keywords from the JD that are not explicitly present or prominent in the resume. Never say "No gaps found" or "Fully saturated". There is always room for keyword alignment.

3. "suggestedModifications": You MUST provide 3-5 high-quality suggestions to improve the resume.
   - ALWAYS suggest exactly 1 brand-new, highly relevant project (action: "add_item", section: "projects") to bridge the biggest experience gap.
     - Fully populate "itemDetails": "title" (max 50 chars), "technologies" (comma-separated list from JD), "description" (1-sentence high-level), "bullets" (2-3 metric-driven bullets containing %/$/hrs/x), "dates" (e.g. "2024").
     - "itemId" must be "new-project-suggestion".
     - "archiveItemSource" must be "AI-Crafted".
     - "suggestedContent" must summarize the project.
   - ALWAYS suggest adding the identified missing skills (action: "append_skills", section: "skills").
     - "itemId" must be an existing skill category name.
     - "suggestedContent" must be a comma-separated list of the missing skills.
   - ALWAYS suggest 1-3 target modifications to existing bullets or sections (actions: "replace_bullet", "insert_bullet", "modify_item") to integrate JD keywords.
     - For "replace_bullet", you MUST provide "bulletIndex" (0-indexed integer of the bullet being replaced), "originalContent" (the exact original text), and "suggestedContent" (the new, keyword-embedded line meaning the same but with higher weightage).
     - "itemId" MUST match the exact "id" string of the corresponding item from the RESUME input data.
     - Ensure every new or modified bullet contains a concrete numeric metric and directly uses terminology from the JD.

4. Maximize token efficiency. Be concise, direct, and avoid verbose explanations.
"""

    prompt = f"""RESUME:
{active_resume_text}

JD:
{body.jd[:2500]}

CAREER VAULT (Use these if relevant):
{vault_text}
"""

    client = genai.Client(api_key=api_key)
    try:
        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    response_schema=ATSScoringResponse,
                    max_output_tokens=2048,
                ),
            ),
            timeout=GEMINI_TIMEOUT_SECS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=f"Gemini request timed out after {GEMINI_TIMEOUT_SECS} seconds.")

    # Check for generation finish status (e.g. truncation due to max tokens or safety filters)
    candidate = response.candidates[0] if (response.candidates and len(response.candidates) > 0) else None
    finish_reason = candidate.finish_reason if candidate else None
    
    if not response.text:
        raise HTTPException(
            status_code=500,
            detail=f"Empty response received from Gemini. Finish Reason: {finish_reason}"
        )

    # Attempt to parse
    raw_text = response.text.strip()
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as exc:
        # If the output was truncated (MAX_TOKENS), try a simple heuristic to close dangling brackets/quotes
        # to see if we can recover the partial JSON structure safely.
        if finish_reason == "MAX_TOKENS" or "MAX_TOKENS" in str(finish_reason):
            # Attempt to fix typical JSON truncation by closing braces
            repaired_text = raw_text
            # Close unclosed string
            if repaired_text.count('"') % 2 != 0:
                repaired_text += '"'
            
            # Count opening vs closing braces
            open_braces = repaired_text.count('{')
            close_braces = repaired_text.count('}')
            if open_braces > close_braces:
                # remove trailing comma if present before closing
                repaired_text = repaired_text.rstrip().rstrip(',')
                repaired_text += '}' * (open_braces - close_braces)
                
            try:
                parsed_data = json.loads(repaired_text)
                # Ensure structure is minimally sound
                if isinstance(parsed_data, dict) and "score" in parsed_data:
                    if "missingSkills" not in parsed_data:
                        parsed_data["missingSkills"] = []
                    if "missingKeywords" not in parsed_data:
                        parsed_data["missingKeywords"] = []
                    if "suggestedModifications" not in parsed_data:
                        parsed_data["suggestedModifications"] = []
                    if "summary" not in parsed_data:
                        parsed_data["summary"] = "Evaluation output was partially truncated due to length constraints."
                    return parsed_data
            except Exception:
                pass

        raise HTTPException(
            status_code=502,
            detail=f"Failed to parse Gemini response (Finish Reason: {finish_reason}): {exc}. Raw text: {raw_text[:200]}..."
        )


@app.post("/api/generate_item")
async def generate_item(body: AIHelperRequest):
    if not body.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt is required.")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not configured on the server.")

    system_instruction = f"""You are an expert AI Resume Maker and Writer.
Generate a high-quality resume entry for the section: '{body.section}' based on the user's request: '{body.prompt}'.
Return a structured JSON response matching the schema.

CRITICAL DIRECTIVES:
- If section is 'projects', populate the 'project' field with a realistic, impressive project. The bullets must be metric-driven (containing %, $, hrs, or x metrics) and technologies should be a comma-separated list of tools.
- If section is 'experience', populate the 'experience' field with a realistic job experience. The bullets must be metric-driven (containing %, $, hrs, or x metrics).
- If section is 'skills', populate the 'skills' field with a categories of skills (e.g. category 'Backend' and skills 'FastAPI, PostgreSQL').
- All generated contents must be professional, resume-ready, and optimize key achievements.
"""

    client = genai.Client(api_key=api_key)
    try:
        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"Generate resume entry for: {body.prompt} in section {body.section}",
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=AIHelperResponse,
                    max_output_tokens=2048,
                ),
            ),
            timeout=GEMINI_TIMEOUT_SECS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Gemini request timed out.")

    if not response.text:
        raise HTTPException(status_code=500, detail="Empty response received from Gemini.")

    try:
        return json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to parse AI response: {exc}")


@app.get("/api/health")
async def health():
    return {"status": "healthy"}


@app.get("/api/user/profile")
async def get_profile(clerk_id: str = Depends(get_current_user_id)):
    col = users_col()
    user_doc = await col.find_one({"clerkId": clerk_id})
    if user_doc:
        return {
            "resumeData": user_doc.get("resumeData"),
            "settings": user_doc.get("settings")
        }
    return {"resumeData": None, "settings": None}


@app.post("/api/user/profile")
async def save_profile(body: ProfileSaveRequest, clerk_id: str = Depends(get_current_user_id)):
    col = users_col()
    profile = await fetch_clerk_profile(clerk_id)
    
    email = profile.get("email") or body.resumeData.get("personalInfo", {}).get("email") or ""
    name = profile.get("name") or body.resumeData.get("personalInfo", {}).get("name") or ""
    picture = profile.get("picture") or ""
    
    await col.update_one(
        {"clerkId": clerk_id},
        {
            "$set": {
                "clerkId": clerk_id,
                "email": email,
                "name": name,
                "picture": picture,
                "resumeData": body.resumeData,
                "settings": body.settings,
                "updatedAt": datetime.utcnow()
            }
        },
        upsert=True
    )
    return {"status": "success"}


@app.exception_handler(Exception)
async def global_exception_handler(_, exc):
    print("Unhandled backend error:", exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})
