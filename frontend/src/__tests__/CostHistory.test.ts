import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import CostHistory from "@/components/CostHistory.vue";

const zero = { answers: 0, input_tokens: 0, output_tokens: 0, cost_usd: 0 };
const HISTORY = {
  start: "2026-10-16T00:00:00Z",
  days: [
    { day: "2026-10-16", ...zero },
    { day: "2026-10-17", answers: 3, input_tokens: 3000, output_tokens: 90, cost_usd: 1.5 },
    { day: "2026-10-18", answers: 2, input_tokens: 1000, output_tokens: 30, cost_usd: 0.5 },
  ],
  projects: [
    { project: "handbook", answers: 3, input_tokens: 3000, output_tokens: 90, cost_usd: 1.5 },
    { project: "demo", answers: 1, input_tokens: 1000, output_tokens: 30, cost_usd: 0.5 },
  ],
  models: [
    { model: "gpt-4o-mini", answers: 3, input_tokens: 4000, output_tokens: 120, cost_usd: 2 },
    { model: null, ...zero, answers: 1 },
  ],
};

afterEach(() => vi.unstubAllGlobals());

describe("CostHistory", () => {
  it("charts each day and shows what each project and model cost", async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json(HISTORY));
    vi.stubGlobal("fetch", fetch);
    const wrapper = mount(CostHistory, { props: { project: "demo" } });
    await flushPromises();

    expect(String(fetch.mock.calls[0]![0])).toContain("/usage/history?days=30");
    expect(wrapper.findAll(".figure").map((figure) => figure.text())).toEqual(["$2.00", "5", "$0.6667"]);
    const bars = wrapper.findAll("rect");
    expect(bars).toHaveLength(3);
    expect(bars.map((bar) => Number(bar.attributes("height")))).toEqual([0, 120, 40]);
    expect(bars[1]!.find("title").text()).toBe("Oct 17: $1.50, 3 answers");
    expect(wrapper.find("svg").attributes("aria-label")).toBe(
      "Cost per day over the last 30 days: $2.00 spent in all.",
    );
    const [projects, models] = wrapper.findAll("tbody");
    expect(projects!.findAll("tr").map((row) => row.text())).toEqual(["handbook3$1.50", "demo1$0.5000"]);
    expect(projects!.find("tr.current").text()).toContain("demo");
    expect(models!.findAll("tr").map((row) => row.text())).toEqual(["gpt-4o-mini4,120$2.00", "No model called0$0.00"]);
  });

  it("charts answers instead, and loads another period", async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json(HISTORY));
    vi.stubGlobal("fetch", fetch);
    const wrapper = mount(CostHistory);
    await flushPromises();

    await wrapper.findAll(".segmented button")[1]!.trigger("click");
    expect(wrapper.findAll("rect").map((bar) => Number(bar.attributes("height")))).toEqual([0, 120, 80]);
    expect(wrapper.find("svg").attributes("aria-label")).toBe(
      "Answers per day over the last 30 days: 5 answers in all.",
    );

    await wrapper.find("select").setValue("7");
    await flushPromises();
    expect(String(fetch.mock.calls[1]![0])).toContain("/usage/history?days=7");
  });

  it("says when there were no answers", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(Response.json({ ...HISTORY, days: [{ day: "2026-10-18", ...zero }], projects: [], models: [] })),
    );
    const wrapper = mount(CostHistory);
    await flushPromises();

    expect(wrapper.text()).toContain("No answers in this period.");
    expect(wrapper.find("rect").attributes("height")).toBe("0");
  });
});
