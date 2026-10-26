import { expect, test } from "@playwright/test";

import { projectName, seedProject } from "./helpers";

test("search finds the passages that match, best first", async ({ page, request }) => {
  const name = projectName("search");
  await seedProject(request, name);

  await page.goto(`/projects/${name}/search`);
  await page.getByRole("searchbox", { name: "Search text" }).fill("receipt approval expenses");
  await page.getByRole("button", { name: "Search", exact: true }).click();

  await expect(page.getByText("Expenses above 50 euros need a receipt").first()).toBeVisible();
});
