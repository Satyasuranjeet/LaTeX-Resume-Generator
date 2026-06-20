# LaTeX Resume Generator

An interactive, AI-powered resume builder that produces publication-ready LaTeX source. Fill out structured forms, preview the live A4 layout, get your resume scored and tailored against any job description by Gemini AI, and export a `.tex` file ready to compile in Overleaf — all in one place.

---

## Features

- **Live LaTeX Preview** — Instant A4 / Letter rendering as you type, with margin and font controls
- **AI ATS Scorer** — Paste any job description and Gemini 2.5 Flash scores your resume, identifies gaps, and injects metric-driven bullet suggestions directly into the editor
- **Career Vault** — Archive past projects, roles, and certifications; the AI pulls from it automatically when tailoring
- **Cloud Sync** — Resume data and settings auto-save to MongoDB Atlas (Ctrl+S / ⌘S)
- **Clerk Auth** — Secure sign-up / sign-in with Google OAuth fallback
- **One-click Export** — Download `.tex`, open directly in Overleaf, or export/import the full JSON backup
- **Undo / Redo** — Full history stack for all resume edits

---

## Project Structure

```text
├── client/              # React Frontend (Vite, TypeScript, TailwindCSS v4)
├── server/              # FastAPI Backend (Python, Motor, Google-GenAI SDK)
├── vercel.json          # Root-level Vercel configuration for unified monorepo deployment
└── README.md            # Project documentation
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Tailwind CSS v4, Framer Motion, Clerk Auth Client |
| Backend | Python 3.10+, FastAPI, Motor (Async MongoDB), PyJWT (Clerk JWT Auth verification) |
| AI | Google Gemini 2.5 Flash via `google-genai` Python SDK |
| Auth | Clerk JWT validation + User profile synchronization |
| Database | MongoDB Atlas via Motor |
| Build | Vite 6 |

---

## Prerequisites

- **Node.js** ≥ 18 (for the client)
- **Python** ≥ 3.10 (for the server)
- A **MongoDB Atlas** cluster (free tier works)
- A **Clerk** developer account — [clerk.com](https://clerk.com)
- A **Google Gemini API key** — [aistudio.google.com](https://aistudio.google.com)

---

## Local Development

### 1. Backend (FastAPI Server)

1. Navigate to the `server/` directory:
   ```bash
   cd server
   ```
2. Create and activate a Python virtual environment:
   ```bash
   python -m venv venv
   # On Windows:
   .\venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Copy the environment variables example and configure your variables:
   ```bash
   copy .env.example .env   # Windows
   cp .env.example .env     # macOS/Linux
   ```
5. Run the FastAPI development server:
   ```bash
   uvicorn main:app --reload --port 8000
   ```
   The backend API will be available at [http://localhost:8000](http://localhost:8000).

### 2. Frontend (React Client)

1. Open a new terminal and navigate to the `client/` directory:
   ```bash
   cd client
   ```
2. Install npm packages:
   ```bash
   npm install
   ```
3. Run the Vite development server:
   ```bash
   npm run dev
   ```
   The frontend will be running at [http://localhost:5173](http://localhost:5173).

---

## Environment Variables Reference

### Backend (`server/.env`)

| Variable | Required | Description | Default / Example |
|---|---|---|---|
| `GEMINI_API_KEY` | ✅ | Google AI Studio API key for resume evaluation | `AIzaSy...` |
| `MONGODB_URI` | ✅ | MongoDB Atlas connection string | `mongodb+srv://...` |
| `CLERK_SECRET_KEY` | ✅ | Clerk Secret Key for REST API operations | `sk_test_...` |
| `CLERK_JWKS_URL` | Optional | Clerk JWKS Endpoint URL for decoding JWT tokens | `https://<your-instance>.clerk.accounts.dev/.well-known/jwks.json` |

### Frontend (`client/.env`)

| Variable | Required | Description | Default / Example |
|---|---|---|---|
| `VITE_CLERK_PUBLISHABLE_KEY` | ✅ | Clerk Publishable Key (exposed to the browser) | `pk_test_...` |
| `VITE_BACKEND_URL` | Optional | Custom backend API URL. Defaults to local server or relative path in production | `http://localhost:8000` |

---

## Production Deployment to Vercel

The application is fully pre-configured to deploy on Vercel. You have two options:

### Option A: Unified Monorepo Deployment (Recommended)
Deploying both frontend and backend as a single Vercel project:

1. Import the root repository in the Vercel Dashboard.
2. Vercel will automatically read the root-level [vercel.json](file:///d:/Projects/latex-resume-generator/vercel.json) to build:
   - The React frontend at `client/` (static build outputting to `/`)
   - The FastAPI backend at `server/` (compiled as `@vercel/python` serverless functions)
3. Set your production Environment Variables on Vercel:
   - `GEMINI_API_KEY`
   - `MONGODB_URI`
   - `CLERK_SECRET_KEY`
   - `CLERK_JWKS_URL`
   - `VITE_CLERK_PUBLISHABLE_KEY`
4. Deploy. Vercel routes `/api/*` to the FastAPI backend and everything else to the frontend.

### Option B: Separate Backend Deployment
If you want to deploy the FastAPI server as a standalone backend service on Vercel:

1. Create a new project in the Vercel Dashboard and point it to the repository.
2. In the Project Settings, set the **Root Directory** to `server`.
3. Set the Environment Variables (`GEMINI_API_KEY`, `MONGODB_URI`, `CLERK_SECRET_KEY`, `CLERK_JWKS_URL`).
4. Vercel will parse [server/vercel.json](file:///d:/Projects/latex-resume-generator/server/vercel.json) and serve FastAPI as a Python serverless application.

---

## License

MIT
