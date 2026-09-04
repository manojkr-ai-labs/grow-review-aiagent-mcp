import { expect, test } from "@playwright/test";
import { jobLogUrl } from "../lib/api";

test("ungated /health returns ok", async ({ request }) => {
  const response = await request.get("/health");
  expect(response.ok()).toBeTruthy();
  expect(await response.json()).toEqual({ ok: true, name: "reviewpulse-console" });
});

test("pipeline SSE URL is same-origin by default", () => {
  expect(jobLogUrl("job-1")).toBe("/api/v1/pipeline/jobs/job-1/log");
  expect(jobLogUrl("job-1", "http://127.0.0.1:8000")).toBe(
    "http://127.0.0.1:8000/api/v1/pipeline/jobs/job-1/log",
  );
});

test("weekly pulse binds pipeline data, not Stitch placeholders", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Weekly Review Pulse" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Console" })).toBeVisible();
  await expect(page.getByText("14,820")).toHaveCount(0);
  await expect(page.getByText("DuckDB")).toHaveCount(0);
  await expect(page.getByText("Llama-3-70b")).toHaveCount(0);
  const body = await page.locator("main").innerText();
  expect(body.includes("Top themes this week") || body.includes("No pulse yet") || body.includes("Console API unreachable")).toBeTruthy();
});

test("reviews explorer has no author column", async ({ page }) => {
  await page.goto("/reviews");
  await expect(page.getByRole("heading", { name: "Reviews" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Author" })).toHaveCount(0);
  const table = page.locator("table");
  if (await table.isVisible()) {
    await expect(page.getByRole("columnheader", { name: "Text" })).toBeVisible();
  }
});
