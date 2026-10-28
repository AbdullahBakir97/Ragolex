import { afterEach, describe, expect, it, vi } from "vitest";

import { apiKey, safeNext, setApiKey, signInNeeded, signInReason } from "@/api/auth";
import { api } from "@/api/client";

afterEach(() => {
  vi.unstubAllGlobals();
  setApiKey(null);
  signInNeeded.value = false;
  signInReason.value = null;
});

const refusing = (signal: string, status = 401) =>
  vi.fn().mockImplementation(() => Promise.resolve(Response.json({ signal }, { status })));

describe("API keys", () => {
  it("are sent with every request once set, and remembered", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(Response.json({ items: [] })));
    vi.stubGlobal("fetch", fetch);

    await api.projects();
    setApiKey("ragolex_secret");
    await api.projects();

    expect(fetch.mock.calls[0]![1].headers).toEqual({});
    expect(fetch.mock.calls[1]![1].headers).toEqual({ Authorization: "Bearer ragolex_secret" });
    expect(localStorage.getItem("ragolex.api-key")).toBe("ragolex_secret");
  });

  it("are forgotten once refused, and the app signs in again", async () => {
    setApiKey("ragolex_revoked");
    vi.stubGlobal("fetch", refusing("api_key_invalid"));

    await expect(api.projects()).rejects.toMatchObject({ signal: "api_key_invalid" });
    expect(signInNeeded.value).toBe(true);
    expect(signInReason.value).toBe("The saved API key no longer works.");
    expect(apiKey.value).toBeNull();
  });
});

describe("Signing in", () => {
  it("is needed when the server wants a key or a session", async () => {
    vi.stubGlobal("fetch", refusing("api_key_required"));
    await expect(api.projects()).rejects.toMatchObject({ signal: "api_key_required" });
    expect(signInNeeded.value).toBe(true);
    expect(signInReason.value).toBeNull();

    signInNeeded.value = false;
    vi.stubGlobal("fetch", refusing("session_required"));
    await expect(api.projects()).rejects.toMatchObject({ signal: "session_required" });
    expect(signInNeeded.value).toBe(true);
    expect(signInReason.value).toBe("Your session has ended. Sign in again.");
  });

  it("is not needed when only a scope is missing", async () => {
    vi.stubGlobal("fetch", refusing("api_key_scope_missing", 403));

    await expect(api.projects()).rejects.toMatchObject({ signal: "api_key_scope_missing" });
    expect(signInNeeded.value).toBe(false);
  });

  it("is not asked for by looking up the session or an invitation", async () => {
    vi.stubGlobal("fetch", refusing("session_required"));

    await expect(api.session()).rejects.toMatchObject({ signal: "session_required" });
    await expect(api.acceptInvitation("token")).rejects.toMatchObject({ signal: "session_required" });
    expect(signInNeeded.value).toBe(false);
  });

  it("goes back only to pages of this app", () => {
    expect(safeNext("/projects/docs/ask?x=1")).toBe("/projects/docs/ask?x=1");
    for (const next of ["https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)", undefined, ["/a"]]) {
      expect(safeNext(next)).toBe("/");
    }
  });
});

describe("Account requests", () => {
  it("send what the API expects, and the session cookie by itself", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(null, { status: 204 })));
    vi.stubGlobal("fetch", fetch);

    await api.changePassword("old secret", "new secret!");
    await api.requestPasswordReset("ada@example.com");
    await api.resetPassword("tok", "new secret!");

    type Call = [string, RequestInit & { body: string }];
    const [[path, init], [resetPath, resetInit], [confirmPath, confirmInit]] = fetch.mock.calls as unknown as [Call, Call, Call];
    expect([path, init.method, JSON.parse(init.body)]).toEqual([
      "/api/v1/auth/password",
      "PUT",
      { current_password: "old secret", new_password: "new secret!" },
    ]);
    expect([resetPath, JSON.parse(resetInit.body)]).toEqual(["/api/v1/auth/password-reset", { email: "ada@example.com" }]);
    expect([confirmPath, JSON.parse(confirmInit.body)]).toEqual([
      "/api/v1/auth/password-reset/confirm",
      { token: "tok", password: "new secret!" },
    ]);
    // No Authorization header: the browser sends the HttpOnly cookie.
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
  });
});
