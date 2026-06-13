"""
LaTeX Resume Generator — FastAPI Backend
Ported from server.ts (Express/Node.js).

Run locally:
    uvicorn main:app --reload --port 8000
"""

import asyncio
import json
import os
import secrets
from typing import Optional

import httpx
import google.generativeai as genai
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from database import connect_db, users_col

load_dotenv()

GEMINI_TIMEOUT_SECS = 60

# ── App ────────────────────────────────────────────────────────────────────────

app = FastAPI(title="LaTeX Resume Generator API", version="1.0.0")

# CORS — allow any origin (credentials=False is required with allow_origins=["*"])
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


# ── Pydantic request models ────────────────────────────────────────────────────

class VerifyClerkRequest(BaseModel):
    clerkId: str
    email: str = ""
    name: str = ""
    picture: str = ""
    action: str = "login"


class SaveResumeRequest(BaseModel):
    resumeData: dict
    settings: dict


class ScoreRequest(BaseModel):
    resumeData: dict
    jd: str


# ── Helpers — compact resume context ──────────────────────────────────────────

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


# ── Auth helpers ───────────────────────────────────────────────────────────────

def _get_redirect_uri(request: Request) -> str:
    host = request.headers.get("host", "localhost:8000")
    is_local = "localhost" in host or "127.0.0.1" in host
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    protocol = "https" if (not is_local and (request.url.scheme == "https" or forwarded_proto == "https")) else "http"
    return f"{protocol}://{host}/api/auth/google/callback"


async def get_current_user(
    authorization: Optional[str] = Header(None),
    x_clerk_email: Optional[str] = Header(None),
    x_clerk_name: Optional[str] = Header(None),
    x_clerk_picture: Optional[str] = Header(None),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized session credentials.")

    token = authorization.split(" ", 1)[1]
    users = users_col()
    user = None

    if token.startswith("user_") or x_clerk_email:
        email = (x_clerk_email or "").lower()
        name = x_clerk_name or ""
        picture = x_clerk_picture or ""

        user = await users.find_one({"clerkId": token})
        if not user and email:
            user = await users.find_one({"email": email})
            if user:
                update: dict = {"clerkId": token}
                if name and not user.get("name"):
                    update["name"] = name
                if picture and not user.get("picture"):
                    update["picture"] = picture
                await users.update_one({"_id": user["_id"]}, {"$set": update})
                user = await users.find_one({"_id": user["_id"]})

        if not user and email:
            doc = {
                "clerkId": token,
                "email": email,
                "name": name or email.split("@")[0],
                "picture": picture or f"https://api.dicebear.com/7.x/identicon/svg?seed={email}",
                "resumeData": None,
                "settings": None,
            }
            result = await users.insert_one(doc)
            user = await users.find_one({"_id": result.inserted_id})

    if not user:
        raise HTTPException(status_code=401, detail="Expired or invalid session token.")

    return user


# ── Endpoint 1 — Google OAuth URL ─────────────────────────────────────────────

@app.get("/api/auth/google/url")
async def google_auth_url(request: Request):
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    if not client_id:
        raise HTTPException(status_code=404, detail="Google Client ID is not configured.")

    params = {
        "client_id": client_id,
        "redirect_uri": _get_redirect_uri(request),
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/userinfo.profile https://www.googleapis.com/auth/userinfo.email",
        "access_type": "offline",
        "prompt": "consent",
    }
    from urllib.parse import urlencode
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    return {"url": url}


# ── Endpoint 2 — Google OAuth callback ────────────────────────────────────────

@app.get("/api/auth/google/callback", response_class=HTMLResponse)
async def google_auth_callback(request: Request, code: Optional[str] = None):
    if not code:
        return HTMLResponse(content="""<html><body><script>
            window.opener.postMessage({type:"OAUTH_AUTH_FAILURE",error:"No authorization code returned."},"*");
            window.close();
        </script></body></html>""")

    try:
        client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")

        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": _get_redirect_uri(request),
                    "grant_type": "authorization_code",
                },
            )
        token_data = token_resp.json()
        if not token_resp.is_success:
            raise ValueError(token_data.get("error_description") or token_data.get("error") or "Token exchange failed.")

        async with httpx.AsyncClient() as client:
            user_resp = await client.get(
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {token_data['access_token']}"},
            )
        profile = user_resp.json()
        if not user_resp.is_success:
            raise ValueError("Failed to retrieve Google userinfo.")

        email = profile["email"].lower()
        session_token = f"session-{secrets.token_hex(16)}"
        users = users_col()

        user = await users.find_one({"email": email})
        if not user:
            doc = {
                "email": email,
                "googleId": profile.get("sub"),
                "name": profile.get("name") or email.split("@")[0],
                "picture": profile.get("picture", ""),
                "sessionToken": session_token,
                "resumeData": None,
                "settings": None,
            }
            result = await users.insert_one(doc)
            user = await users.find_one({"_id": result.inserted_id})
        else:
            await users.update_one(
                {"_id": user["_id"]},
                {"$set": {
                    "name": profile.get("name") or user.get("name"),
                    "picture": profile.get("picture") or user.get("picture"),
                    "googleId": profile.get("sub") or user.get("googleId"),
                    "sessionToken": session_token,
                }},
            )

        name_escaped = (user.get("name") or "").replace('"', '\\"')
        return HTMLResponse(content=f"""<html><body><script>
            if(window.opener){{
                window.opener.postMessage({{
                    type:"OAUTH_AUTH_SUCCESS",
                    data:{{
                        token:"{session_token}",
                        user:{{email:"{email}",name:"{name_escaped}",picture:"{user.get('picture','')}"}}
                    }}
                }},"*");
                window.close();
            }} else {{ window.location.href="/"; }}
        </script><p style="font-family:sans-serif;text-align:center;margin-top:50px;">Verified! This window will close.</p></body></html>""")

    except Exception as exc:
        msg = str(exc).replace('"', '\\"')
        return HTMLResponse(content=f"""<html><body><script>
            window.opener.postMessage({{type:"OAUTH_AUTH_FAILURE",error:"{msg}"}},"*");
            window.close();
        </script></body></html>""")


# ── Endpoint 3 — Verify Clerk user ────────────────────────────────────────────

@app.post("/api/auth/verify-clerk")
async def verify_clerk(body: VerifyClerkRequest):
    if not body.clerkId:
        raise HTTPException(status_code=400, detail="Missing Clerk User Identifier.")

    users = users_col()
    clean_email = body.email.strip().lower()

    user = await users.find_one({"clerkId": body.clerkId})
    if not user and clean_email:
        user = await users.find_one({"email": clean_email})

    if body.action == "login":
        if not user:
            raise HTTPException(status_code=400, detail="Account does not exist. Please register first.")
        update: dict = {}
        if not user.get("clerkId"):
            update["clerkId"] = body.clerkId
        if body.name and not user.get("name"):
            update["name"] = body.name
        if body.picture and not user.get("picture"):
            update["picture"] = body.picture
        if update:
            await users.update_one({"_id": user["_id"]}, {"$set": update})
            user = await users.find_one({"_id": user["_id"]})

    elif body.action == "register":
        if user:
            raise HTTPException(status_code=400, detail="Account already exists. Please sign in instead.")
        doc = {
            "clerkId": body.clerkId,
            "email": clean_email,
            "name": body.name.strip() if body.name else clean_email.split("@")[0],
            "picture": body.picture or f"https://api.dicebear.com/7.x/identicon/svg?seed={clean_email}",
            "resumeData": None,
            "settings": None,
        }
        result = await users.insert_one(doc)
        user = await users.find_one({"_id": result.inserted_id})

    return {"success": True, "user": {"email": user["email"], "name": user.get("name"), "picture": user.get("picture")}}


# ── Endpoint 4 — GET resume ────────────────────────────────────────────────────

@app.get("/api/resume")
async def get_resume(current_user: dict = Depends(get_current_user)):
    return {
        "resumeData": current_user.get("resumeData"),
        "settings": current_user.get("settings"),
    }


# ── Endpoint 5 — POST resume (save) ───────────────────────────────────────────

@app.post("/api/resume")
async def save_resume(body: SaveResumeRequest, current_user: dict = Depends(get_current_user)):
    await users_col().update_one(
        {"_id": current_user["_id"]},
        {"$set": {"resumeData": body.resumeData, "settings": body.settings}},
    )
    return {"success": True, "message": "Resume saved to MongoDB successfully."}


# ── Endpoint 6 — POST score (Gemini AI) ───────────────────────────────────────

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
  - append_skills → add to skills section only; add_item → new project/experience entry.

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


# ── Healthcheck ────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "healthy"}
