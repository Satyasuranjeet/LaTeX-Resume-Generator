// Frontend-only dev server.
// All API routes have been moved to backend/main.py (FastAPI).
// Set VITE_API_URL in .env to point the frontend at your running FastAPI server.
import { createServer as createViteServer } from "vite";

async function main() {
  const vite = await createViteServer({
    server: { port: 3000 },
  });
  await vite.listen();
  vite.printUrls();
}

main();


