import { expect, test } from "@playwright/test";

import { HANDBOOK, projectName, watchForErrors } from "./helpers";

test("a new project is created, and a document uploaded, split and indexed", async ({ page }) => {
  const errors = watchForErrors(page);
  const name = projectName("docs");

  await page.goto("/");
  await page.getByRole("button", { name: "New project" }).first().click();
  const dialog = page.getByRole("dialog", { name: "New project" });
  await dialog.getByRole("textbox", { name: "Name" }).fill(name);
  await dialog.getByRole("button", { name: "Create project" }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${name}/documents$`));

  await page.locator('input[type="file"]').setInputFiles({
    name: "handbook.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(HANDBOOK),
  });
  // The upload is processed and indexed by a background job on the server.
  await expect(page.getByText("Ready").first()).toBeVisible({ timeout: 20_000 });
  const row = page.getByRole("row", { name: /handbook\.txt/ });
  await expect(row).toBeVisible();

  await row.getByRole("button", { name: "View chunks" }).click();
  await expect(page.getByText("Employees get 25 days of paid leave each year.").first()).toBeVisible();
  expect(errors).toEqual([]);
});
