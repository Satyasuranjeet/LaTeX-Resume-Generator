# LaTeX Resume Generator

An interactive, AI-powered resume builder that produces publication-ready LaTeX source. Fill out structured forms, preview the live A4 layout, get your resume scored and tailored against any job description by Gemini AI, and export a `.tex` file ready to compile in Overleaf — all in one place.

---

## Features

- **Live LaTeX Preview** — Instant A4 / Letter rendering as you type, with margin and font controls
- **AI ATS Scorer** — Paste any job description and Gemini 2.0 Flash scores your resume, identifies gaps, and injects metric-driven bullet suggestions directly into the editor
- **Career Vault** — Archive past projects, roles, and certifications; the AI pulls from it automatically when tailoring
- **Cloud Sync** — Resume data and settings auto-save to MongoDB Atlas (Ctrl+S / ⌘S)
- **Clerk Auth** — Secure sign-up / sign-in with Google OAuth fallback
- **One-click Export** — Download `.tex`, open directly in Overleaf, or export/import the full JSON backup
- **Undo / Redo** — Full history stack for all resume edits

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Tailwind CSS v4, Framer Motion |
| Backend | Node.js, Express, tsx (dev) / esbuild (prod) |
| AI | Google Gemini 2.0 Flash via `@google/genai` |
| Auth | Clerk (`@clerk/clerk-react`) + Google OAuth 2.0 |
| Database | MongoDB Atlas via Mongoose |
| Build | Vite 6 |

---

## Prerequisites

- **Node.js** ≥ 18
- A **MongoDB Atlas** cluster (free tier works)
- A **Clerk** account — [clerk.com](https://clerk.com)
- A **Google Gemini API key** — [aistudio.google.com](https://aistudio.google.com)
- *(Optional)* A **Google OAuth 2.0** client for Google sign-in

---

## Local Development

**1. Clone and install**

```bash
git clone <your-repo-url>
cd latex-resume-generator
npm install
```

**2. Configure environment variables**

Copy the example below into a `.env` file at the project root:

```env
# Required — Gemini AI
GEMINI_API_KEY=your_gemini_api_key_here

# Required — MongoDB Atlas connection string
MONGODB_URI=mongodb+srv://<user>:<password>@cluster0.xxxxx.mongodb.net/resume-builder

# Required — Clerk publishable key (exposed to the browser via Vite)
VITE_CLERK_PUBLISHABLE_KEY=pk_test_xxxxxxxxxxxxxxxxxxxx

# Optional — Google OAuth (only needed if enabling Google sign-in)
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret

# Optional — Public URL for OAuth redirect URIs (set in production)
APP_URL=https://your-app-domain.com
```

**3. Run the dev server**

```bash
npm run dev
```

The Express + Vite server starts at [http://localhost:3000](http://localhost:3000).

---

## Production Deployment

**1. Build**

```bash
npm run build
```

This outputs:
- `dist/` — compiled React frontend (served as static files)
- `dist/server.cjs` — bundled Express server

**2. Set environment variables on your host**

Set the same variables from the `.env` section above as platform secrets / environment config. Make sure `NODE_ENV=production` is set so the server serves the static build instead of starting Vite.

**3. Start**

```bash
node dist/server.cjs
```

The server listens on port `3000` by default. Put a reverse proxy (nginx, Caddy, or your cloud provider's load balancer) in front of it.

### Deploy to Cloud Run / Railway / Render

- Set all env vars in the platform's secrets panel
- Build command: `npm install && npm run build`
- Start command: `node dist/server.cjs`
- Port: `3000`

> **Clerk redirect URLs** — Add your production domain to the allowed redirect origins in the Clerk dashboard under *Paths → Redirect URLs*.

> **MongoDB Atlas network access** — Whitelist your server's outbound IP (or `0.0.0.0/0` for dynamic IPs) in Atlas → Network Access.

---

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | ✅ | Google AI Studio API key for resume scoring |
| `MONGODB_URI` | ✅ | MongoDB Atlas SRV connection string |
| `VITE_CLERK_PUBLISHABLE_KEY` | ✅ | Clerk publishable key (prefix `VITE_` exposes it to the browser) |
| `GOOGLE_CLIENT_ID` | Optional | Google OAuth 2.0 client ID |
| `GOOGLE_CLIENT_SECRET` | Optional | Google OAuth 2.0 client secret |
| `APP_URL` | Optional | Canonical app URL used in OAuth redirect URIs |
| `NODE_ENV` | Optional | Set to `production` to serve the Vite build instead of running Vite middleware |
| `MONGODB_DNS_SERVERS` | Optional | Comma-separated DNS servers for Atlas SRV lookup (default: `1.1.1.1,8.8.8.8`) |

---

## Scripts

| Command | Description |
|---|---|
| `npm run dev` | Start dev server (Express + Vite HMR) |
| `npm run build` | Build frontend and bundle server for production |
| `npm run lint` | TypeScript type-check |
| `npm run clean` | Remove `dist/` |

---

## Project Structure

```
├── server.ts           # Express API + Vite dev middleware
├── server/
│   └── mongodb.ts      # Mongoose connection + User model
├── src/
│   ├── App.tsx         # Main editor, AI scorer, auth flow
│   ├── latexGenerator.ts # Resume → LaTeX compiler
│   ├── types.ts        # Shared TypeScript types
│   ├── initialState.ts # Default resume template
│   └── components/
│       └── LandingPage.tsx  # Auth / sign-in page
├── vite.config.ts
├── tsconfig.json
└── .env                # Local secrets (never commit)
```

---

## License

MIT
