import { defineConfig } from "@playwright/test";

// Web runs on :3100, not Next.js's usual :3000 — this is a shared dev
// machine and :3000 is already occupied by an unrelated project (found the
// hard way: reuseExistingServer silently ran a test suite against someone
// else's app). The API's default :8000 was confirmed free. reuseExistingServer
// is off so a future collision fails loudly instead of repeating that mistake.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  // One at a time: every test drives 2-5 "devices" polling a single
  // `next dev` server, and in parallel the first-visit route compiles and
  // polling pile up until multi-device flows time out. Serial is ~3 min.
  workers: 1,
  // A four-device game with 1.5s polling legitimately takes 20-40s.
  timeout: 90_000,
  retries: 0,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3100",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      // `python -m uvicorn`, not a bare `uvicorn` — resolves via whichever
      // Python is active in the shell that runs `npx playwright test`
      // (the repo's .venv locally; the CI runner's own install in CI).
      // Activate .venv before running this locally — see web/README.md.
      command: "cd ../api && python -m uvicorn app.main:app --port 8000",
      // The API refuses to start without an auth mode; the suite signs in
      // through dev-login. Merged over the inherited environment.
      env: { TAIDI_AUTH_MODE: "dev" },
      url: "http://localhost:8000/healthz",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: "npm run dev -- --port 3100",
      url: "http://localhost:3100",
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
