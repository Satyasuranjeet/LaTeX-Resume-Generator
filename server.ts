import express from "express";
import path from "path";
import { createServer as createViteServer } from "vite";
import { GoogleGenAI, Type } from "@google/genai";
import dotenv from "dotenv";
import crypto from "crypto";
import { connectDB, User } from "./server/mongodb";

dotenv.config();

const PORT = 3000;
const GEMINI_TIMEOUT_MS = 60000;

function trimText(value: unknown, maxLength: number) {
  if (typeof value !== "string") {
    return "";
  }

  const normalized = value.trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }

  return `${normalized.slice(0, maxLength - 3)}...`;
}

function compactList(items: unknown, maxItems: number, maxLength: number) {
  if (!Array.isArray(items)) {
    return [];
  }

  return items.slice(0, maxItems).map((item) => trimText(item, maxLength)).filter(Boolean);
}

function buildCompactResumeContext(resumeData: any) {
  return {
    personalInfo: {
      name: trimText(resumeData?.personalInfo?.name, 120),
      course: trimText(resumeData?.personalInfo?.course, 120),
      github: trimText(resumeData?.personalInfo?.github, 120),
      linkedin: trimText(resumeData?.personalInfo?.linkedin, 120),
    },
    education: (Array.isArray(resumeData?.education) ? resumeData.education : []).slice(0, 4).map((entry: any) => ({
      degree: trimText(entry?.degree, 120),
      institution: trimText(entry?.institution, 120),
      score: trimText(entry?.score, 80),
      dates: trimText(entry?.dates, 40),
    })),
    experience: (Array.isArray(resumeData?.experience) ? resumeData.experience : []).slice(0, 4).map((entry: any) => ({
      role: trimText(entry?.role, 120),
      company: trimText(entry?.company, 120),
      locationType: trimText(entry?.locationType, 60),
      dates: trimText(entry?.dates, 40),
      bullets: compactList(entry?.bullets, 3, 180),
    })),
    projects: (Array.isArray(resumeData?.projects) ? resumeData.projects : []).slice(0, 5).map((entry: any) => ({
      title: trimText(entry?.title, 120),
      description: trimText(entry?.description, 180),
      technologies: trimText(entry?.technologies, 180),
      dates: trimText(entry?.dates, 40),
      bullets: compactList(entry?.bullets, 3, 180),
    })),
    skills: (Array.isArray(resumeData?.skills) ? resumeData.skills : []).slice(0, 10).map((entry: any) => ({
      category: trimText(entry?.category, 80),
      skills: trimText(entry?.skills, 180),
    })),
    careerVault: (Array.isArray(resumeData?.careerVault) ? resumeData.careerVault : []).slice(0, 10).map((entry: any) => ({
      type: trimText(entry?.type, 40),
      title: trimText(entry?.title, 120),
      subtitle: trimText(entry?.subtitle, 120),
      description: trimText(entry?.description, 220),
      technologies: trimText(entry?.technologies, 180),
      dates: trimText(entry?.dates, 40),
    })),
  };
}

async function startServer() {
  const app = express();
  app.use(express.json({ limit: "15mb" }));

  // Establish standard database connection safely without crashing development server
  try {
    await connectDB();
  } catch (err) {
    console.error("Critical warning: Initial MongoDB Atlas connection failed. Server will continue launching.", err);
  }

  // Dynamic redirect URI helper for Google OAuth 2.0
  const getRedirectUri = (req: express.Request) => {
    const host = req.headers.host || "localhost:3000";
    const isLocal = host.includes("localhost") || host.includes("127.0.0.1");
    const protocol = !isLocal && (req.secure || req.headers["x-forwarded-proto"] === "https") ? "https" : "http";
    return `${protocol}://${host}/api/auth/google/callback`;
  };

  // Endpoint 1: Retrieve Google Consent screen URL
  app.get("/api/auth/google/url", (req, res) => {
    const clientId = process.env.GOOGLE_CLIENT_ID;
    if (!clientId) {
      return res.status(404).json({ 
        error: "Google Client ID is not configured. Please add GOOGLE_CLIENT_ID in Settings > Secrets." 
      });
    }

    const redirectUri = getRedirectUri(req);
    const params = new URLSearchParams({
      client_id: clientId,
      redirect_uri: redirectUri,
      response_type: "code",
      scope: "https://www.googleapis.com/auth/userinfo.profile https://www.googleapis.com/auth/userinfo.email",
      access_type: "offline",
      prompt: "consent"
    });

    const googleAuthUrl = `https://accounts.google.com/o/oauth2/v2/auth?${params.toString()}`;
    res.json({ url: googleAuthUrl });
  });

  // Endpoint 2: Google OAuth callback code exchanger
  app.get("/api/auth/google/callback", async (req, res) => {
    const { code } = req.query;
    if (!code) {
      return res.send(`
        <html>
          <body>
            <script>
              window.opener.postMessage({ type: "OAUTH_AUTH_FAILURE", error: "No authorization code returned." }, "*");
              window.close();
            </script>
          </body>
        </html>
      `);
    }

    try {
      const clientId = process.env.GOOGLE_CLIENT_ID;
      const clientSecret = process.env.GOOGLE_CLIENT_SECRET;
      const redirectUri = getRedirectUri(req);

      // Exchange authorize code for token
      const tokenResponse = await fetch("https://oauth2.googleapis.com/token", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          code: code as string,
          client_id: clientId || "",
          client_secret: clientSecret || "",
          redirect_uri: redirectUri,
          grant_type: "authorization_code"
        })
      });

      const tokenData = await tokenResponse.json();
      if (!tokenResponse.ok) {
        throw new Error(tokenData.error_description || tokenData.error || "Failed to exchange token");
      }

      // Fetch user profile from Google Profile APIs
      const userResponse = await fetch("https://www.googleapis.com/oauth2/v3/userinfo", {
        headers: { "Authorization": `Bearer ${tokenData.access_token}` }
      });

      const profileData = await userResponse.json();
      if (!userResponse.ok) {
        throw new Error("Failed to retrieve Google userinfo.");
      }

      // Find or create candidate document in MongoDB Atlas
      const email = profileData.email.toLowerCase();
      const sessionToken = `session-${crypto.randomUUID()}`;

      let userDoc = await User.findOne({ email });
      if (!userDoc) {
        userDoc = new User({
          email,
          googleId: profileData.sub,
          name: profileData.name || email.split("@")[0],
          picture: profileData.picture || ""
        });
      } else {
        userDoc.name = profileData.name || userDoc.name;
        userDoc.picture = profileData.picture || userDoc.picture;
        userDoc.googleId = profileData.sub || userDoc.googleId;
      }

      // Generate/update active authentication token
      userDoc.sessionToken = sessionToken;
      // Also write directly as custom MongoDB field
      userDoc.set("sessionToken", sessionToken);
      await userDoc.save();

      // Return communication page sending success payload directly to the parent preview iframe
      return res.send(`
        <html>
          <body>
            <script>
              if (window.opener) {
                window.opener.postMessage({ 
                  type: "OAUTH_AUTH_SUCCESS", 
                  data: {
                    token: "${sessionToken}",
                    user: {
                      email: "${userDoc.email}",
                      name: "${userDoc.name.replace(/"/g, '\\"')}",
                      picture: "${userDoc.picture}"
                    }
                  } 
                }, "*");
                window.close();
              } else {
                window.location.href = "/";
              }
            </script>
            <p style="font-family: sans-serif; text-align: center; margin-top: 50px;">
              Auth details verified! This browser window will now close dynamically.
            </p>
          </body>
        </html>
      `);

    } catch (err: any) {
      console.error("Google Auth OAuth exchange crash:", err);
      return res.send(`
        <html>
          <body>
            <script>
              window.opener.postMessage({ type: "OAUTH_AUTH_FAILURE", error: "${err.message || 'System verification error.'}" }, "*");
              window.close();
            </script>
            <p style="font-family: sans-serif; color: red; text-align: center;">Error: ${err.message || 'System verification error.'}</p>
          </body>
        </html>
      `);
    }
  });

  // Endpoint 3: Verify Clerk user session database existence prior to granting access
  app.post("/api/auth/verify-clerk", async (req, res) => {
    try {
      const { clerkId, email, name, picture, action } = req.body;
      if (!clerkId) {
        return res.status(400).json({ error: "Missing Clerk User Identifier." });
      }

      const cleanEmail = (email || "").trim().toLowerCase();
      // Look up user by clerkId or by email
      let userDoc = await User.findOne({ clerkId });
      if (!userDoc && cleanEmail) {
        userDoc = await User.findOne({ email: cleanEmail });
      }

      if (action === "login") {
        if (!userDoc) {
          return res.status(400).json({ error: "Account does not exist. Please register first." });
        }
        // If user document was found but Clerk ID is not linked, link it now
        if (!userDoc.clerkId) {
          userDoc.clerkId = clerkId;
        }
        if (name && !userDoc.name) userDoc.name = name;
        if (picture && !userDoc.picture) userDoc.picture = picture;
        await userDoc.save();
      } else if (action === "register") {
        if (userDoc) {
          return res.status(400).json({ error: "Account already exists. Please sign in instead." });
        }
        // If user does not exist, create a new record
        userDoc = new User({
          clerkId,
          email: cleanEmail,
          name: name ? name.trim() : cleanEmail.split("@")[0],
          picture: picture || `https://api.dicebear.com/7.x/identicon/svg?seed=${cleanEmail}`
        });
        await userDoc.save();
      }

      res.json({
        success: true,
        user: {
          email: userDoc.email,
          name: userDoc.name,
          picture: userDoc.picture
        }
      });
    } catch (err: any) {
      console.error("Clerk pre-verification error:", err);
      res.status(500).json({ error: "Failed to verify workspace credentials." });
    }
  });

  // Middleware to fetch user session from Clerk token header
  const authMiddleware = async (req: express.Request, res: express.Response, next: express.NextFunction) => {
    try {
      const authHeader = req.headers.authorization;
      if (!authHeader || !authHeader.startsWith("Bearer ")) {
        return res.status(401).json({ error: "Unauthorized session credentials." });
      }

      const token = authHeader.split(" ")[1];
      let user = null;

      if (token && (token.startsWith("user_") || req.headers["x-clerk-email"])) {
        // Clerk authentication
        const email = (req.headers["x-clerk-email"] as string || "").toLowerCase();
        const name = req.headers["x-clerk-name"] as string || "";
        const picture = req.headers["x-clerk-picture"] as string || "";
        
        // Find by clerkId first
        user = await User.findOne({ clerkId: token });
        if (!user && email) {
          // Fallback to finding by email to link existing account
          user = await User.findOne({ email });
          if (user) {
            user.clerkId = token;
            if (name && !user.name) user.name = name;
            if (picture && !user.picture) user.picture = picture;
            await user.save();
          }
        }

        if (!user && email) {
          // Create new user for Clerk
          user = new User({
            clerkId: token,
            email,
            name: name || email.split("@")[0],
            picture: picture || `https://api.dicebear.com/7.x/identicon/svg?seed=${email}`
          });
          await user.save();
        }
      }

      if (!user) {
        return res.status(401).json({ error: "Expired or invalid session token." });
      }

      // Attach user document directly to the request
      (req as any).user = user;
      next();
    } catch (err) {
      console.error("Auth middleware error:", err);
      res.status(500).json({ error: "Server authentication error." });
    }
  };

  // Endpoint 4: Fetch user's saved resume state from MongoDB Atlas
  app.get("/api/resume", authMiddleware, async (req: any, res) => {
    try {
      // Find specific user from request document
      const userDoc = req.user;
      res.json({
        resumeData: userDoc.resumeData,
        settings: userDoc.settings
      });
    } catch (err) {
      res.status(500).json({ error: "Failed to load backup data from MongoDB Atlas." });
    }
  });

  // Endpoint 5: Save/Write user resume state to MongoDB Atlas
  app.post("/api/resume", authMiddleware, async (req: any, res) => {
    try {
      const { resumeData, settings } = req.body;
      const userDoc = req.user;

      userDoc.resumeData = resumeData;
      userDoc.settings = settings;
      await userDoc.save();

      res.json({ success: true, message: "Resume saved to MongoDB successfully." });
    } catch (err) {
      console.error("Save state error:", err);
      res.status(500).json({ error: "Failed to save data. Please check MongoDB logs." });
    }
  });

  // API Endpoint to check resume matching against a JD (original)
  app.post("/api/score", async (req, res) => {
    try {
      const { resumeData, jd } = req.body;
      if (!jd || !jd.trim()) {
        return res.status(400).json({ error: "Job Description is required." });
      }

      const apiKey = process.env.GEMINI_API_KEY;
      if (!apiKey) {
        return res.status(500).json({ 
          error: "GEMINI_API_KEY environment variable is missing on the server. Please configure it in your Settings > Secrets panel." 
        });
      }

      const ai = new GoogleGenAI({
        apiKey: apiKey,
        httpOptions: {
          headers: {
            'User-Agent': 'aistudio-build',
          }
        }
      });

      // Format only the most relevant, concise resume data to keep Gemini latency lower.
      const compactResume = buildCompactResumeContext(resumeData);
      const activeResumeText = JSON.stringify({
        personalInfo: compactResume.personalInfo,
        education: compactResume.education,
        experience: compactResume.experience,
        projects: compactResume.projects,
        skills: compactResume.skills,
      }, null, 2);

      const careerVaultText = JSON.stringify(compactResume.careerVault, null, 2);

      const prompt = `ATS Resume Optimizer. Output JSON only. No preamble.

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
${activeResumeText}

JD:
${jd.slice(0, 3000)}

VAULT:
${careerVaultText}
`;

      const responsePromise = ai.models.generateContent({
        model: "gemini-2.0-flash",
        contents: prompt,
        config: {
          responseMimeType: "application/json",
          maxOutputTokens: 2048,
          responseSchema: {
            type: Type.OBJECT,
            properties: {
              score: { type: Type.INTEGER },
              summary: { type: Type.STRING },
              missingSkills: { type: Type.ARRAY, items: { type: Type.STRING } },
              missingKeywords: { type: Type.ARRAY, items: { type: Type.STRING } },
              suggestedModifications: {
                type: Type.ARRAY,
                items: {
                  type: Type.OBJECT,
                  properties: {
                    section: { type: Type.STRING },
                    itemId: { type: Type.STRING },
                    action: { type: Type.STRING },
                    bulletIndex: { type: Type.INTEGER },
                    explanation: { type: Type.STRING },
                    originalContent: { type: Type.STRING },
                    suggestedContent: { type: Type.STRING },
                    itemDetails: {
                      type: Type.OBJECT,
                      properties: {
                        title: { type: Type.STRING },
                        subtitle: { type: Type.STRING },
                        dates: { type: Type.STRING },
                        technologies: { type: Type.STRING },
                        bullets: { type: Type.ARRAY, items: { type: Type.STRING } }
                      }
                    },
                    archiveItemSource: { type: Type.STRING }
                  },
                  required: ["section", "action", "explanation", "suggestedContent", "archiveItemSource"]
                }
              }
            },
            required: ["score", "summary", "missingSkills", "missingKeywords", "suggestedModifications"]
          }
        }
      });

      const response = await Promise.race([
        responsePromise,
        new Promise((_, reject) => {
          setTimeout(() => reject(new Error(`Gemini request timed out after ${GEMINI_TIMEOUT_MS / 1000} seconds.`)), GEMINI_TIMEOUT_MS);
        })
      ]) as Awaited<typeof responsePromise>;

      const resultText = response.text;
      if (!resultText) {
        return res.status(500).json({ error: "Empty response received from Gemini" });
      }

      const parsedJSON = JSON.parse(resultText);
      res.json(parsedJSON);

    } catch (err: any) {
      console.error("Gemini Scoring Error:", err);
      res.status(500).json({ error: err.message || "An unexpected error occurred during resume evaluation." });
    }
  });

  // Express API healthcheck
  app.get("/api/health", (req, res) => {
    res.json({ status: "healthy" });
  });

  // Vite Integration
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server launched and listening coordinates: http://localhost:${PORT}`);
  });
}

startServer();
