import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { projectName, seedProject } from "./helpers";

// Every page, with data on it, in both themes: no WCAG 2.1 A or AA violation
// that axe can find, and nothing wider than the screen (the phone project
// runs the tests tagged @phone).
const PAGES = ["", "ask", "documents", "search", "assistant", "usage", "widget", "webhooks", "bots"];

let project = "";

test.beforeAll(async ({ request }) => {
  project = projectName("a11y");
  await seedProject(request, project);
});

for (const scheme of ["light", "dark"] as const) {
  for (const path of PAGES) {
    test(`${path || "projects"} (${scheme}) @phone`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto(path ? `/projects/${project}/${path}` : "/");
      await expect(page.locator("main")).toBeVisible();
      await page.waitForLoadState("networkidle");

      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
        // The widget preview is a third-party page's view, checked on its own below.
        .exclude(".preview-host")
        .analyze();
      const found = results.violations.map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
      expect(found).toEqual([]);

      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(0);
    });
  }
}

test("the chat widget is accessible too", async ({ page }) => {
  await page.goto(`/projects/${project}/widget`);
  await page.getByRole("textbox", { name: "Name" }).fill("Help desk");
  await page.getByRole("textbox", { name: "Allowed websites" }).fill("https://shop.example.com");
  await page.getByRole("button", { name: "Add widget" }).click();
  await expect(page.locator(".preview-host [data-ragolex-widget]")).toBeVisible();

  const results = await new AxeBuilder({ page })
    .include(".preview-host")
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
});
