import { expect, test } from "@playwright/test";

import { projectName, seedProject, watchForErrors } from "./helpers";

test("a question is answered from the documents, with its source, and can be rated", async ({ page, request }) => {
  const errors = watchForErrors(page);
  const name = projectName("ask");
  await seedProject(request, name);

  await page.goto(`/projects/${name}/ask`);
  const question = page.getByRole("textbox", { name: "Question" });
  await question.fill("How many days of paid leave do employees get?");
  await question.press("Enter");

  // The answer streams in, then lists the source it cites.
  const answer = page.locator(".answer").first();
  await expect(answer.getByText("Employees get 25 days of paid leave each year").first()).toBeVisible();
  await expect(answer.getByRole("heading", { name: "Sources" })).toBeVisible();
  await expect(page.getByText("handbook.txt").first()).toBeVisible();

  // The conversation is kept, at its own address, and listed.
  await expect(page).toHaveURL(new RegExp(`/projects/${name}/ask/[0-9a-f-]{36}$`));
  await expect(page.getByText("How many days of paid leave do employees get?").last()).toBeVisible();

  await page.getByRole("button", { name: "Good answer" }).click();
  await expect(page.getByRole("button", { name: "Good answer" })).toHaveAttribute("aria-pressed", "true");

  // A follow-up in the same conversation.
  await question.fill("When does the office close on Fridays?");
  await question.press("Enter");
  await expect(page.locator(".answer").nth(1).getByText("The office closes at 18:00 on Fridays").first()).toBeVisible();
  expect(errors).toEqual([]);
});

test("a question the documents do not answer says so", async ({ page, request }) => {
  const name = projectName("ask-none");
  await seedProject(request, name);

  await page.goto(`/projects/${name}/ask`);
  const question = page.getByRole("textbox", { name: "Question" });
  await question.fill("Which planets have rings?");
  await question.press("Enter");

  await expect(page.getByRole("heading", { name: "The documents don't answer this" })).toBeVisible();
});
