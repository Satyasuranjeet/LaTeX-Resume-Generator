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

    client = genai.Client(api_key=api_key)
    try:
        response = await asyncio.wait_for(
            client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ATSScoringResponse,
                    max_output_tokens=8192,
                ),
            ),
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
