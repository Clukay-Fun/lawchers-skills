import { describe, expect, it, vi } from "vitest";
import { LawchersError } from "@lawchers/shared-core";
import { createOpenAICompatibleEmbeddingProvider } from "../src/index.js";

describe("openai-compatible embedding provider", () => {
  it("sends embedding requests and parses embeddings", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      new Response(JSON.stringify({ data: [{ embedding: [1, 2] }, { embedding: [3, 4] }] }), {
        status: 200
      })
    );
    const provider = createOpenAICompatibleEmbeddingProvider({
      config: {
        type: "openai-compatible",
        baseUrl: "https://example.test/v1/",
        model: "embed",
        apiKeyEnv: "API_KEY"
      },
      env: { API_KEY: "secret" },
      fetch: fetchMock
    });

    await expect(provider.embedTexts(["a", "b"])).resolves.toEqual([
      [1, 2],
      [3, 4]
    ]);

    expect(fetchMock).toHaveBeenCalledWith(
      "https://example.test/v1/embeddings",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          authorization: "Bearer secret",
          "content-type": "application/json"
        }),
        body: JSON.stringify({ model: "embed", input: ["a", "b"] })
      })
    );
  });

  it("fails when the API key env var is missing", async () => {
    const provider = createOpenAICompatibleEmbeddingProvider({
      config: {
        type: "openai-compatible",
        baseUrl: "https://example.test/v1",
        model: "embed",
        apiKeyEnv: "API_KEY"
      },
      env: {}
    });

    await expect(provider.embedText("a")).rejects.toMatchObject<Partial<LawchersError>>({
      code: "PROVIDER_UNAVAILABLE"
    });
  });

  it("fails when provider is disabled", async () => {
    const provider = createOpenAICompatibleEmbeddingProvider({
      config: { type: "disabled" },
      env: {}
    });

    await expect(provider.embedText("a")).rejects.toMatchObject<Partial<LawchersError>>({
      code: "PROVIDER_DISABLED"
    });
  });

  it("fails with provider unavailable for HTTP failures", async () => {
    const provider = createOpenAICompatibleEmbeddingProvider({
      config: {
        type: "openai-compatible",
        baseUrl: "https://example.test/v1",
        model: "embed",
        apiKeyEnv: "API_KEY"
      },
      env: { API_KEY: "secret" },
      fetch: async () => new Response("nope", { status: 500 })
    });

    await expect(provider.embedText("a")).rejects.toMatchObject<Partial<LawchersError>>({
      code: "PROVIDER_UNAVAILABLE"
    });
  });
});
