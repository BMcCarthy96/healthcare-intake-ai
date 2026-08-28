import { expect, test } from "@playwright/test";

const publicMeta = {
  app_version: "0.2.0",
  api_commit_sha: "e2e",
  frontend_commit_sha: "e2e",
  build_time: "2026-08-26T12:00:00Z",
  schema_version: "intake-record/2",
  mode: "synthetic-only",
  demo_scenario_version: "v2",
  custom_uploads_enabled: false,
  live_model_compare_enabled: false,
  evaluation_runs_enabled: false,
};

test("dashboard presents the synthetic-data boundary and an empty workflow queue", async ({ page }) => {
  await page.route("**/v1/cases", (route) =>
    route.fulfill({ contentType: "application/json", body: "[]" }),
  );
  await page.route("**/v1/meta", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(publicMeta) }),
  );
  await page.goto("/");

  await expect(page.getByText("Synthetic data only · Not for clinical use")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Make every intake decision traceable and reviewable." })).toBeVisible();
  await expect(page.getByText("Your queue is clear.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Launch isolated walkthrough →" })).toBeVisible();
  await expect(page.getByText("Public evaluation writes are disabled.")).toBeVisible();
});

test("public walkthrough entry provisions an isolated workspace", async ({ page }) => {
  await page.route("**/v1/cases", (route) =>
    route.fulfill({ contentType: "application/json", body: "[]" }),
  );
  await page.route("**/v1/meta", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(publicMeta) }),
  );
  await page.route("**/v1/demo/sessions", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        session_id: "workspace-dashboard-e2e",
        token: "token-dashboard-e2e",
        expires_at: "2099-01-01T00:00:00Z",
        scenario_version: "v2",
        scenarios: [],
        tour: [],
      }),
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Start 90-second walkthrough →" }).click();
  await expect(page).toHaveURL("/demo");
});
