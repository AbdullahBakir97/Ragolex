import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { DEFAULT_PROCESS_OPTIONS } from "@/api/types";

describe("DEFAULT_PROCESS_OPTIONS", () => {
  it("are the API's defaults, so files split the same from the app as from the API", () => {
    const schema = JSON.parse(readFileSync(resolve(process.cwd(), "../sdk/openapi.json"), "utf-8"));
    const properties = schema.components.schemas.ProcessRequest.properties;

    expect(DEFAULT_PROCESS_OPTIONS).toEqual({
      chunk_size: properties.chunk_size.default,
      overlap_size: properties.overlap_size.default,
    });
  });
});
