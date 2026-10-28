import { flushPromises, mount, RouterLinkStub } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";

import { signInNeeded, signInReason } from "@/api/auth";
import type { Session } from "@/api/types";
import AdminMembers from "@/components/AdminMembers.vue";
import AdminDomains from "@/components/AdminDomains.vue";
import { useSession } from "@/composables/useSession";
import { useSite } from "@/composables/useSite";
import { reloadAt } from "@/lib/navigate";
import AccountView from "@/views/AccountView.vue";
import AdminView from "@/views/AdminView.vue";
import InviteView from "@/views/auth/InviteView.vue";
import ResetPasswordView from "@/views/auth/ResetPasswordView.vue";
import SignInView from "@/views/auth/SignInView.vue";
import SignUpView from "@/views/auth/SignUpView.vue";

vi.mock("@/lib/navigate", () => ({ reloadAt: vi.fn() }));

beforeEach(() => {
  vi.mocked(reloadAt).mockClear();
  useSession().session.value = null;
  useSession().loaded.value = false;
  useSite().forget();
  sessionStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  history.replaceState(null, "", "/");
});

type Handler = (body: Record<string, unknown> | null, url: URL) => Response;

/** Answers each request by its method and API path, keeping what was sent. */
function serve(routes: Record<string, Handler>) {
  const fetch = vi.fn((input: string, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const handler = routes[`${init?.method ?? "GET"} ${url.pathname.replace("/api/v1", "")}`];
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
    return Promise.resolve(handler ? handler(body, url) : Response.json({ signal: "not_mocked" }, { status: 500 }));
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

const refuse = (signal: string, status: number) => () => Response.json({ signal }, { status });
const ADA = { id: 1, email: "ada@example.com", name: "Ada Lovelace" };
const SESSION: Session = {
  user: ADA,
  workspace: { name: "acme", role: "owner" },
  workspaces: [
    { name: "acme", role: "owner" },
    { name: "zenith", role: "viewer" },
  ],
  expires_at: "2026-11-27T10:00:00Z",
};

function routerAt(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/:path(.*)*", component: { template: "<div />" } }],
  });
  void router.push(path);
  return router;
}

async function fill(wrapper: ReturnType<typeof mount>, values: Record<string, string>) {
  for (const [selector, value] of Object.entries(values)) await wrapper.find(selector).setValue(value);
}

describe("SignInView", () => {
  it("signs in and goes back where the app was", async () => {
    const fetch = serve({
      "POST /auth/login": () => Response.json(SESSION),
      "GET /site": () => Response.json({ workspace: null, accounts_enabled: true, signup_enabled: true }),
    });
    signInReason.value = "Your session has ended. Sign in again.";
    const router = routerAt("/signin?next=/projects/docs/ask");
    await router.isReady();
    const wrapper = mount(SignInView, { global: { plugins: [router] } });

    expect(wrapper.text()).toContain("Your session has ended.");
    await fill(wrapper, { 'input[type="email"]': " ada@example.com ", 'input[type="password"]': "correct horse" });
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    const login = fetch.mock.calls.find(([url]) => String(url).endsWith("/auth/login"))!;
    expect(JSON.parse(String(login[1]!.body))).toEqual({ email: "ada@example.com", password: "correct horse" });
    expect(reloadAt).toHaveBeenCalledWith("/projects/docs/ask");
    expect(wrapper.text()).toContain("Create an account");
  });

  it("names the workspace on its own domain, where nobody signs up", async () => {
    serve({ "GET /site": () => Response.json({ workspace: "acme", accounts_enabled: true, signup_enabled: false }) });
    const router = routerAt("/signin");
    await router.isReady();
    const wrapper = mount(SignInView, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.find("h1").text()).toBe("Sign in to acme");
    expect(wrapper.text()).not.toContain("Create an account");
  });

  it("says why signing in failed, and never goes to another site", async () => {
    serve({ "POST /auth/login": refuse("login_failed", 401) });
    const router = routerAt("/signin?next=https://evil.example");
    await router.isReady();
    const wrapper = mount(SignInView, { global: { plugins: [router] } });

    await fill(wrapper, { 'input[type="email"]': "ada@example.com", 'input[type="password"]': "wrong" });
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(wrapper.find('[role="alert"]').text()).toBe("The email or the password is wrong.");
    expect(reloadAt).not.toHaveBeenCalled();
    expect(wrapper.findComponent({ name: "ApiKeyDialog" }).props("next")).toBe("/");
    expect(signInNeeded.value).toBe(false);
  });

  it("signs in with single sign-on, found by the email's domain", async () => {
    const fetch = serve({
      "POST /auth/sso/discover": () => Response.json({ workspace: "acme", start_url: "/api/v1/auth/sso/start?workspace=acme" }),
    });
    const router = routerAt("/signin?next=/projects/docs");
    await router.isReady();
    const wrapper = mount(SignInView, { global: { plugins: [router] } });

    await wrapper.findAll("button").find((b) => b.text() === "Sign in with single sign-on")!.trigger("click");
    expect(wrapper.find(".password").exists()).toBe(false);
    await fill(wrapper, { 'input[type="email"]': " grace@acme.com " });
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    const discover = fetch.mock.calls.find(([url]) => String(url).endsWith("/auth/sso/discover"))!;
    expect(JSON.parse(String(discover[1]!.body))).toEqual({ email: "grace@acme.com" });
    expect(reloadAt).toHaveBeenCalledWith("/api/v1/auth/sso/start?workspace=acme&next=%2Fprojects%2Fdocs");
  });

  it("says why single sign-on did not work", async () => {
    serve({ "POST /auth/sso/discover": refuse("sso_not_configured", 404) });
    const router = routerAt("/signin?sso_error=sso_email_not_allowed");
    await router.isReady();
    const wrapper = mount(SignInView, { global: { plugins: [router] } });

    expect(wrapper.find(".alert-danger").text()).toContain("vouched for an email this workspace does not sign in");
    await fill(wrapper, { 'input[type="email"]': "x@unknown.example" });
    await wrapper.find("form").trigger("submit");
    await flushPromises();
    expect(wrapper.find('p[role="alert"]').text()).toContain("not set up for this email's domain");
    expect(reloadAt).not.toHaveBeenCalled();
  });
});

describe("SignUpView", () => {
  it("says people are invited where nobody signs up", async () => {
    serve({ "GET /site": () => Response.json({ workspace: "acme", accounts_enabled: true, signup_enabled: false }) });
    const wrapper = mount(SignUpView, { global: { stubs: { RouterLink: RouterLinkStub } } });
    await flushPromises();

    expect(wrapper.text()).toContain("People join acme by invitation.");
    expect(wrapper.find("form").exists()).toBe(false);
  });

  it("names the workspace after the email until it is edited", async () => {
    const fetch = serve({
      "POST /auth/signup": () => Response.json(SESSION, { status: 201 }),
      "GET /site": () => Response.json({ workspace: null, accounts_enabled: true, signup_enabled: true }),
    });
    const wrapper = mount(SignUpView, { global: { stubs: { RouterLink: RouterLinkStub } } });
    const workspace = wrapper.findAll("input")[2]!;

    await fill(wrapper, { 'input[autocomplete="name"]': "Ada", 'input[type="email"]': "ada@Acme.Example.com" });
    expect((workspace.element as HTMLInputElement).value).toBe("acme");
    await workspace.setValue("analytical-engines");
    await workspace.trigger("input");
    await wrapper.find('input[type="email"]').setValue("ada@other.com");
    expect((workspace.element as HTMLInputElement).value).toBe("analytical-engines");

    await wrapper.find('input[type="password"]').setValue("a long passphrase");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    const signup = fetch.mock.calls.find(([url]) => String(url).endsWith("/auth/signup"))!;
    expect(JSON.parse(String(signup[1]!.body))).toEqual({
      name: "Ada",
      email: "ada@other.com",
      workspace: "analytical-engines",
      password: "a long passphrase",
    });
    expect(reloadAt).toHaveBeenCalledWith("/");
  });
});

describe("ResetPasswordView", () => {
  it("takes the token out of the address and sets the new password with it", async () => {
    const fetch = serve({ "POST /auth/password-reset/confirm": () => new Response(null, { status: 204 }) });
    history.replaceState(null, "", "/reset-password#secret-token");
    const wrapper = mount(ResetPasswordView, { global: { stubs: { RouterLink: RouterLinkStub } } });

    expect(window.location.hash).toBe("");
    const [password, repeat] = wrapper.findAll('input[type="password"]');
    await password!.setValue("a new passphrase");
    await repeat!.setValue("a different one");
    await wrapper.find("form").trigger("submit");
    expect(wrapper.find('[role="alert"]').text()).toBe("The two passwords differ.");
    expect(fetch).not.toHaveBeenCalled();

    await repeat!.setValue("a new passphrase");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    expect(JSON.parse(String(fetch.mock.calls[0]![1]!.body))).toEqual({ token: "secret-token", password: "a new passphrase" });
    expect(wrapper.text()).toContain("Your password is changed.");
    expect(sessionStorage.getItem("ragolex.password-reset")).toBeNull();
  });

  it("needs the link from the email", () => {
    const wrapper = mount(ResetPasswordView, { global: { stubs: { RouterLink: RouterLinkStub } } });

    expect(wrapper.text()).toContain("This page needs the link from the email.");
    expect(wrapper.find('button[type="submit"]').attributes("disabled")).toBeDefined();
  });
});

describe("InviteView", () => {
  const PREVIEW = {
    workspace: "acme",
    email: "grace@example.com",
    role: "editor",
    invited_by: "Ada Lovelace",
    expires_at: "2026-11-04T10:00:00Z",
    has_account: false,
  };

  function openLink() {
    history.replaceState(null, "", "/invite#invite-token");
    return mount(InviteView, { global: { stubs: { RouterLink: RouterLinkStub } } });
  }

  it("makes the account and joins", async () => {
    const fetch = serve({
      "POST /auth/invitation": () => Response.json(PREVIEW),
      "GET /auth/session": refuse("session_required", 401),
      "POST /auth/invitation/accept": () => Response.json(SESSION),
    });
    const wrapper = openLink();
    await flushPromises();

    expect(wrapper.text()).toContain("Ada Lovelace invited you to acme.");
    expect(wrapper.text()).toContain("as an editor");
    await fill(wrapper, { 'input[autocomplete="name"]': "Grace Hopper", 'input[type="password"]': "a long passphrase" });
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    const accept = fetch.mock.calls.find(([url]) => String(url).endsWith("/accept"))!;
    expect(JSON.parse(String(accept[1]!.body))).toEqual({
      token: "invite-token",
      name: "Grace Hopper",
      password: "a long passphrase",
    });
    expect(reloadAt).toHaveBeenCalledWith("/");
    expect(sessionStorage.getItem("ragolex.invitation")).toBeNull();
  });

  it("sends an account that exists to sign in first, keeping the link for afterwards", async () => {
    serve({
      "POST /auth/invitation": () => Response.json({ ...PREVIEW, has_account: true }),
      "GET /auth/session": refuse("session_required", 401),
    });
    const wrapper = openLink();
    await flushPromises();

    const links = wrapper.findAllComponents(RouterLinkStub).map((link) => link.props("to"));
    expect(links).toContainEqual({ path: "/signin", query: { next: "/invite" } });
    expect(sessionStorage.getItem("ragolex.invitation")).toBe("invite-token");
    expect(signInNeeded.value).toBe(false);
  });

  it("joins as the signed-in user, or says the invitation is someone else's", async () => {
    serve({
      "POST /auth/invitation": () => Response.json({ ...PREVIEW, email: "ada@example.com" }),
      "GET /auth/session": () => Response.json(SESSION),
      "POST /auth/invitation/accept": () => Response.json(SESSION),
    });
    const mine = openLink();
    await flushPromises();
    await mine.find("button").trigger("click");
    await flushPromises();
    expect(reloadAt).toHaveBeenCalledWith("/");

    serve({
      "POST /auth/invitation": () => Response.json(PREVIEW),
      "GET /auth/session": () => Response.json(SESSION),
    });
    const theirs = openLink();
    await flushPromises();
    expect(theirs.text()).toContain("You are signed in as ada@example.com, but this invitation is for grace@example.com.");
  });

  it("says when the link does not work", async () => {
    serve({
      "POST /auth/invitation": refuse("invitation_invalid", 404),
      "GET /auth/session": refuse("session_required", 401),
    });
    const wrapper = openLink();
    await flushPromises();

    expect(wrapper.find('[role="alert"]').text()).toContain("This invitation link does not work");
  });
});

describe("AccountView", () => {
  it("changes the password and switches workspace", async () => {
    const fetch = serve({
      "GET /auth/session": () => Response.json(SESSION),
      "PUT /auth/password": () => new Response(null, { status: 204 }),
      "PUT /auth/session/workspace": () => Response.json({ ...SESSION, workspace: SESSION.workspaces[1] }),
    });
    const wrapper = mount(AccountView);
    await flushPromises();

    expect(wrapper.text()).toContain("Ada Lovelace");
    const [current, next, repeat] = wrapper.findAll('input[type="password"]');
    await current!.setValue("old passphrase");
    await next!.setValue("new passphrase!");
    await repeat!.setValue("new passphrase!");
    await wrapper.find("form").trigger("submit");
    await flushPromises();
    const change = fetch.mock.calls.find(([url]) => String(url).endsWith("/auth/password"))!;
    expect(JSON.parse(String(change[1]!.body))).toEqual({ current_password: "old passphrase", new_password: "new passphrase!" });

    await wrapper.findAll(".workspaces button")[0]!.trigger("click");
    await flushPromises();
    expect(reloadAt).toHaveBeenCalledWith("/");
  });

  it("explains an API key has no account", async () => {
    serve({ "GET /auth/session": refuse("session_required", 401) });
    localStorage.setItem("ragolex.api-key", "ragolex_x");
    const { apiKey } = await import("@/api/auth");
    apiKey.value = "ragolex_x";
    const wrapper = mount(AccountView);
    await flushPromises();

    expect(wrapper.text()).toContain("This browser uses an API key, not an account.");
    apiKey.value = null;
    localStorage.clear();
  });
});

const MEMBERS = [
  { ...ADA, role: "owner", joined_at: "2026-10-01T10:00:00Z", last_login_at: "2026-10-28T10:00:00Z" },
  { id: 2, email: "grace@example.com", name: "Grace Hopper", role: "editor", joined_at: "2026-10-02T10:00:00Z", last_login_at: null },
];
const INVITATION = {
  id: "inv-1",
  email: "alan@example.com",
  role: "viewer",
  invited_by: ADA,
  created_at: "2026-10-28T10:00:00Z",
  expires_at: "2099-11-04T10:00:00Z",
};

describe("AdminMembers", () => {
  it("lists members and open invitations; only owners touch owners", async () => {
    serve({ "GET /members": () => Response.json(MEMBERS), "GET /invitations": () => Response.json([INVITATION]) });
    const wrapper = mount(AdminMembers, { props: { myRole: "admin", myUserId: 2 } });
    await flushPromises();

    const rows = wrapper.findAll("tbody tr");
    expect(rows[0]!.text()).toContain("Ada Lovelace");
    expect(rows[0]!.find("select").attributes("disabled")).toBeDefined();
    expect(rows[0]!.find("button").exists()).toBe(false);
    expect(rows[1]!.text()).toContain("You");
    expect(rows[1]!.find("select").attributes("disabled")).toBeUndefined();
    expect(rows[2]!.text()).toContain("alan@example.com");
    // An admin cannot invite owners.
    expect(wrapper.findAll(".invite option").map((o) => o.attributes("value"))).toEqual(["admin", "editor", "viewer"]);
  });

  it("invites and shows the link once, changes roles and removes members", async () => {
    let invited = false;
    const fetch = serve({
      "GET /members": () => Response.json(MEMBERS),
      "GET /invitations": () => Response.json(invited ? [INVITATION] : []),
      "POST /invitations": () => {
        invited = true;
        return Response.json(
          { ...INVITATION, link: "http://localhost:3000/invite#abc", emailed: false },
          { status: 201 },
        );
      },
      "PUT /members/2": () => Response.json({ ...MEMBERS[1], role: "viewer" }),
      "DELETE /members/2": () => new Response(null, { status: 204 }),
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const wrapper = mount(AdminMembers, { props: { myRole: "owner", myUserId: 1 } });
    await flushPromises();

    await wrapper.find('.invite input[type="email"]').setValue("alan@example.com");
    await wrapper.find(".invite select").setValue("viewer");
    await wrapper.find(".invite").trigger("submit");
    await flushPromises();
    expect(wrapper.find('[data-testid="invitation-link"]').text()).toBe("http://localhost:3000/invite#abc");
    expect(wrapper.text()).toContain("Send them this link: it is not shown again.");
    expect(wrapper.emitted("changed")).toHaveLength(1);

    await wrapper.find('select[aria-label="Role of Grace Hopper"]').setValue("viewer");
    await flushPromises();
    await wrapper.find('button[aria-label="Remove Grace Hopper"]').trigger("click");
    await flushPromises();

    const sent = fetch.mock.calls.map(([url, init]) => `${init?.method ?? "GET"} ${String(url)}`);
    expect(sent).toContain("PUT /api/v1/members/2");
    expect(sent).toContain("DELETE /api/v1/members/2");
    expect(JSON.parse(String(fetch.mock.calls.find(([url]) => String(url).endsWith("/members/2"))![1]!.body))).toEqual({
      role: "viewer",
    });
  });

  it("puts a refused role back", async () => {
    serve({
      "GET /members": () => Response.json(MEMBERS),
      "GET /invitations": () => Response.json([]),
      "PUT /members/1": refuse("last_owner", 409),
    });
    const wrapper = mount(AdminMembers, { props: { myRole: "owner", myUserId: 1 } });
    await flushPromises();

    const select = wrapper.find('select[aria-label="Role of Ada Lovelace"]');
    await select.setValue("admin");
    await flushPromises();

    expect((select.element as HTMLSelectElement).value).toBe("owner");
  });
});

describe("AdminView", () => {
  it("shows the members to a signed-in admin, and who is signed in", async () => {
    serve({
      "GET /me": () =>
        Response.json({ tenant: "acme", scopes: ["admin", "ask", "read", "write"], key_id: null, auth_enabled: true, user: ADA, role: "owner" }),
      "GET /usage": () =>
        Response.json({
          tenant: "acme",
          period_start: "2026-10-01",
          requests_per_minute: null,
          answers: { used: 0, limit: null },
          storage_bytes: { used: 0, limit: null },
          input_tokens: 0,
          output_tokens: 0,
          cost_usd: 0,
          budget_usd: null,
        }),
    });
    const wrapper = mount(AdminView, {
      global: { stubs: { AdminMembers: true, AdminConnections: true, AdminSso: true, AdminKeys: true, AdminEvaluations: true, AdminAudit: true } },
    });
    await flushPromises();

    expect(wrapper.text()).toContain("Signed in as Ada Lovelace (ada@example.com), owner of this workspace.");
    expect(wrapper.findComponent({ name: "AdminMembers" }).props()).toEqual({ myRole: "owner", myUserId: 1 });
  });
});

const DOMAIN = {
  id: "d-1",
  domain: "help.acme.com",
  verified: false,
  created_at: "2026-10-28T10:00:00Z",
  verified_at: null,
  checked_at: null,
  records: [
    { type: "TXT", name: "_ragolex.help.acme.com", value: "ragolex-verification=abc" },
    { type: "CNAME", name: "help.acme.com", value: "rag.example.com" },
  ],
};

describe("AdminDomains", () => {
  it("adds a pasted address as its host name, shows its records and checks it", async () => {
    let state = "none";
    const fetch = serve({
      "GET /domains": () =>
        Response.json(state === "none" ? [] : [{ ...DOMAIN, verified: state === "verified", verified_at: state === "verified" ? DOMAIN.created_at : null }]),
      "POST /domains": () => {
        state = "added";
        return Response.json(DOMAIN, { status: 201 });
      },
      "POST /domains/d-1/verify": () => {
        state = "verified";
        return Response.json({ ...DOMAIN, verified: true });
      },
    });
    const wrapper = mount(AdminDomains);
    await flushPromises();
    expect(wrapper.text()).toContain("No domains yet");

    await wrapper.find("input").setValue("https://help.acme.com/support?x=1");
    await wrapper.find("form").trigger("submit");
    await flushPromises();

    const added = fetch.mock.calls.find(([url, init]) => String(url).endsWith("/domains") && init?.method === "POST")!;
    expect(JSON.parse(String(added[1]!.body))).toEqual({ domain: "help.acme.com" });
    expect(wrapper.text()).toContain("Waiting for its TXT record");
    expect(wrapper.text()).toContain("_ragolex.help.acme.com");
    expect(wrapper.text()).toContain("ragolex-verification=abc");

    await wrapper.findAll("button").find((b) => b.text().includes("Check now"))!.trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("Verified");
    expect(wrapper.emitted("changed")).toHaveLength(2);
  });

  it("says when the record is not there yet", async () => {
    serve({
      "GET /domains": () => Response.json([DOMAIN]),
      "POST /domains/d-1/verify": () => Response.json({ signal: "domain_not_verified" }, { status: 409 }),
    });
    const { useToasts } = await import("@/composables/useToasts");
    const wrapper = mount(AdminDomains);
    await flushPromises();

    await wrapper.findAll("button").find((b) => b.text().includes("Check now"))!.trigger("click");
    await flushPromises();

    const toast = useToasts().toasts.value.at(-1)!;
    expect([toast.kind, toast.title]).toEqual(["error", "help.acme.com is not verified yet"]);
    expect(toast.message).toContain("TXT record was not found");
  });
});
