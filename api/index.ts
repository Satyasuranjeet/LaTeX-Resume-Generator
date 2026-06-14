import dotenv from "dotenv";
import express from "express";
import { GoogleGenAI, Type } from "@google/genai";

dotenv.config();

const GEMINI_TIMEOUT_MS = 60000;

function trimText(value: unknown, maxLength: number): string {
  if (typeof value !== "string") return "";
  const normalized = value.trim();
  return normalized.length <= maxLength ? normalized : `${normalized.slice(0, maxLength - 3)}...`;
}

function compactList(items: unknown, maxItems: number, maxLength: number): string[] {
  if (!Array.isArray(items)) return [];
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
    education: (Array.isArray(resumeData?.education) ? resumeData.education : []).slice(0, 4).map((e: any) => ({
      degree: trimText(e?.degree, 120),
      institution: trimText(e?.institution, 120),
      score: trimText(e?.score, 80),
      dates: trimText(e?.dates, 40),
    })),
    experience: (Array.isArray(resumeData?.experience) ? resumeData.experience : []).slice(0, 4).map((e: any) => ({
      role: trimText(e?.role, 120),
      company: trimText(e?.company, 120),
      locationType: trimText(e?.locationType, 60),
      dates: trimText(e?.dates, 40),
      bullets: compactList(e?.bullets, 3, 180),
    })),
    projects: (Array.isArray(resumeData?.projects) ? resumeData.projects : []).slice(0, 5).map((e: any) => ({
      title: trimText(e?.title, 120),
      description: trimText(e?.description, 180),
      technologies: trimText(e?.technologies, 180),
      dates: trimText(e?.dates, 40),
      bullets: compactList(e?.bullets, 3, 180),
    })),
    skills: (Array.isArray(resumeData?.skills) ? resumeData.skills : []).slice(0, 10).map((e: any) => ({
      category: trimText(e?.category, 80),
      skills: trimText(e?.skills, 180),
    })),
    careerVault: (Array.isArray(resumeData?.careerVault) ? resumeData.careerVault : []).slice(0, 10).map((e: any) => ({
      type: trimText(e?.type, 40),
      title: trimText(e?.title, 120),
      subtitle: trimText(e?.subtitle, 120),
      description: trimText(e?.description, 220),
      technologies: trimText(e?.technologies, 180),
      dates: trimText(e?.dates, 40),
    })),
  };
}

const app = express();
app.use(express.json({ limit: "15mb" }));

const scoreHandler = async (req: express.Request, res: express.Response) => {
  try {
    const { resumeData, jd } = req.body;
    if (!jd?.trim()) return res.status(400).json({ error: "Job Description is required." });

    const apiKey = process.env.GEMINI_API_KEY;
    if (!apiKey) return res.status(500).json({ error: "GEMINI_API_KEY environment variable is missing on the server." });

    const ai = new GoogleGenAI({ apiKey, httpOptions: { headers: { "User-Agent": "aistudio-build" } } });
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
  - append_skills -> add to skills section only; add_item -> new project/experience entry.

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
                      bullets: { type: Type.ARRAY, items: { type: Type.STRING } },
                    },
                  },
                  archiveItemSource: { type: Type.STRING },
                },
                required: ["section", "action", "explanation", "suggestedContent", "archiveItemSource"],
              },
            },
          },
          required: ["score", "summary", "missingSkills", "missingKeywords", "suggestedModifications"],
        },
      },
    });

    const response = (await Promise.race([
      responsePromise,
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error(`Gemini request timed out after ${GEMINI_TIMEOUT_MS / 1000} seconds.`)), GEMINI_TIMEOUT_MS)
      ),
    ])) as Awaited<typeof responsePromise>;

    const resultText = response.text;
    if (!resultText) return res.status(500).json({ error: "Empty response received from Gemini." });
    res.json(JSON.parse(resultText));
  } catch (err: any) {
    console.error("Gemini Scoring Error:", err);
    res.status(500).json({ error: err.message || "An unexpected error occurred during resume evaluation." });
  }
};

app.post(["/api/score", "/score"], scoreHandler);

app.get("/api/health", (_req, res) => res.json({ status: "healthy" }));

export default app;
