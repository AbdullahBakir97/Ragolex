import { expect, test } from "@playwright/test";

import { projectName, seedProject } from "./helpers";

test("a chat widget is added, and its live preview answers", async ({ page, request }) => {
  const name = projectName("widget");
  await seedProject(request, name);

  await page.goto(`/projects/${name}/widget`);
  await page.getByRole("textbox", { name: "Name" }).fill("Help desk");
  await page.getByRole("textbox", { name: "Allowed websites" }).fill("https://shop.example.com");
  await page.getByRole("button", { name: "Add widget" }).click();
  await expect(page.getByText("Widget added")).toBeVisible();

  // The preview is the real widget, in its own shadow DOM, asking this project.
  const widget = page.locator(".preview-host [data-ragolex-widget]");
  const input = widget.locator("textarea");
  await input.fill("How many days of paid leave do employees get?");
  await input.press("Enter");
  // The answer first; the widget may also show the source it quotes.
  await expect(widget.getByText("Employees get 25 days of paid leave each year").first()).toBeVisible();
});
