import { afterEach, describe, expect, it, vi } from "vitest";

import { apiKey, keyNeeded, setApiKey } from "@/api/auth";
import { api } from "@/api/client";

afterEach(() => {
  vi.unstubAllGlobals();
  setApiKey(null);
  keyNeeded.value = false;
});

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

  it("are asked for when the server refuses a request", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ signal: "api_key_required" }, { status: 401 })));

    await expect(api.projects()).rejects.toMatchObject({ signal: "api_key_required" });
    expect(keyNeeded.value).toBe(true);
    expect(apiKey.value).toBeNull();
  });

  it("are not asked for when only a scope is missing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(Response.json({ signal: "api_key_scope_missing" }, { status: 403 })),
    );

    await expect(api.projects()).rejects.toMatchObject({ signal: "api_key_scope_missing" });
    expect(keyNeeded.value).toBe(false);
  });
});
