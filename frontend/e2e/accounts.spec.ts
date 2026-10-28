import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

import { ACCOUNTS_URL } from "../playwright.config";
import { watchForErrors } from "./helpers";

// Against the API with authentication on: people sign up, sign in, invite
// each other and manage members, as a browser does, with the session cookie.
test.use({ baseURL: ACCOUNTS_URL });

const PASSWORD = "correct horse battery";

/** An email and a workspace name no other test uses. */
function someone(prefix: string) {
  const id = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
  return { email: `${prefix}-${id}@example.com`, workspace: `${prefix}-${id}` };
}

async function signUp(page: Page, name: string, email: string, workspace: string) {
  await page.goto("/signup");
  await page.getByLabel("Your name").fill(name);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Workspace").fill(workspace);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(`${ACCOUNTS_URL}/`);
}

test("a page that needs signing in sends you to sign in, and back", async ({ page }) => {
  const errors = watchForErrors(page);
  const ada = someone("ada");
  await signUp(page, "Ada Lovelace", ada.email, ada.workspace);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/signin$/);

  await page.goto("/admin");
  await expect(page).toHaveURL(/\/signin\?next=(%2F|\/)admin$/);
  await page.getByLabel("Email").fill(ada.email);
  await page.getByLabel("Password").fill("not the password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText("The email or the password is wrong.");

  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(/\/admin$/);
  await expect(page.getByText(`Signed in as Ada Lovelace (${ada.email}), owner of this workspace.`)).toBeVisible();
  // The browser's own failed-sign-in line is the only error.
  expect(errors.filter((e) => !e.includes("401"))).toEqual([]);
});

test("an owner invites someone, who joins with a new account", async ({ page, browser }) => {
  const ada = someone("owner");
  const grace = someone("grace");
  await signUp(page, "Ada Lovelace", ada.email, ada.workspace);

  await page.goto("/admin");
  const members = page.getByRole("region", { name: "Members" });
  await members.getByRole("textbox", { name: "Email" }).fill(grace.email);
  await members.getByRole("combobox", { name: "Role", exact: true }).selectOption("editor");
  await members.getByRole("button", { name: "Invite" }).click();
  const link = await page.getByTestId("invitation-link").textContent();
  expect(link).toMatch(new RegExp(`^${ACCOUNTS_URL}/invite#`));
  await expect(members.getByRole("cell", { name: grace.email, exact: true })).toBeVisible();

  // Grace opens the link in her own browser.
  const context = await browser.newContext();
  const visitor = await context.newPage();
  await visitor.goto(link!);
  await expect(visitor.getByText(`Ada Lovelace invited you to ${ada.workspace}.`)).toBeVisible();
  await expect(visitor).toHaveURL(`${ACCOUNTS_URL}/invite`); // The token left the address bar.
  await visitor.getByLabel("Your name").fill("Grace Hopper");
  await visitor.getByLabel("Password").fill(PASSWORD);
  await visitor.getByRole("button", { name: "Create account and join" }).click();
  await expect(visitor).toHaveURL(`${ACCOUNTS_URL}/`);
  await expect(visitor.getByRole("link", { name: /Grace Hopper/ })).toBeVisible();
  // An editor does not manage members.
  await visitor.goto("/admin");
  await expect(visitor.getByText("need the admin scope")).toBeVisible();
  await context.close();

  // Ada sees her, makes her a viewer, then removes her.
  await page.reload();
  await expect(members.getByText("Grace Hopper")).toBeVisible();
  await members.getByRole("combobox", { name: "Role of Grace Hopper" }).selectOption("viewer");
  await expect(page.getByText("Grace Hopper is now viewer.")).toBeVisible();
  page.once("dialog", (dialog) => void dialog.accept());
  await members.getByRole("button", { name: "Remove Grace Hopper" }).click();
  await expect(members.getByText("Grace Hopper")).toHaveCount(0);
});

test("a signed-in user changes their password", async ({ page }) => {
  const ada = someone("pw");
  await signUp(page, "Ada Lovelace", ada.email, ada.workspace);

  await page.getByRole("link", { name: /Ada Lovelace/ }).click();
  await expect(page).toHaveURL(/\/account$/);
  await page.getByLabel("Current password").fill(PASSWORD);
  await page.getByLabel("New password", { exact: true }).fill("a brand new passphrase");
  await page.getByLabel("New password again").fill("a brand new passphrase");
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByText("Password changed")).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).first().click();
  await page.getByLabel("Email").fill(ada.email);
  await page.getByLabel("Password").fill("a brand new passphrase");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(`${ACCOUNTS_URL}/`);
});

test("forgetting a password never says whether an account exists", async ({ page }) => {
  await page.goto("/signin");
  await page.getByRole("link", { name: "Forgot your password?" }).click();
  await expect(page.getByRole("heading", { name: "Reset your password" })).toBeVisible();
  await page.getByLabel("Email").fill("nobody@example.com");
  await page.getByRole("button", { name: "Email me a link" }).click();
  await expect(page.getByRole("status")).toContainText("If an account has nobody@example.com, a link is on its way.");
});

for (const scheme of ["light", "dark"] as const) {
  for (const path of ["/signin", "/signup", "/forgot-password", "/account"]) {
    test(`${path} is accessible (${scheme}) @phone`, async ({ page }) => {
      if (path === "/account") {
        const user = someone("a11y");
        await signUp(page, "Ada Lovelace", user.email, user.workspace);
      }
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto(path);
      await expect(page.locator("main")).toBeVisible();
      await page.waitForLoadState("networkidle");

      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
      const found = results.violations.map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
      expect(found).toEqual([]);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(0);
    });
  }
}
