import { expect, test } from "@playwright/test";

test("dashboard presents the synthetic-data boundary and an empty workflow queue", async ({ page }) => {
  await page.route("**/v1/cases", (route) =>
    route.fulfill({ contentType: "application/json", body: "[]" }),
  );
  await page.goto("/");

  await expect(page.getByText("Synthetic data only · Not for clinical use")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Make every intake decision traceable and reviewable." })).toBeVisible();
  await expect(page.getByText("Your queue is clear.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Load a complete synthetic demo →" })).toBeVisible();
});

test("synthetic demo entry navigates into the reviewer workspace", async ({ page }) => {
  const caseId = "demo-e2e-case";
  await page.route("**/v1/cases", (route) =>
    route.fulfill({ contentType: "application/json", body: "[]" }),
  );
  await page.route("**/v1/demo/seed", (route) =>
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        id: caseId,
        external_reference: "DEMO-2026-001",
        status: "ready_for_export",
        source: "synthetic-demo",
        document_count: 1,
      }),
    }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Load a complete synthetic demo →" }).click();
  await expect(page).toHaveURL(`/cases/${caseId}`);
});
