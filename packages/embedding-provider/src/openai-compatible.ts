import { LawchersError, type ProviderConfig } from "@lawchers/shared-core";

export interface EmbeddingProvider {
  embedText(text: string): Promise<number[]>;
  embedTexts(texts: string[]): Promise<number[][]>;
}

export interface OpenAICompatibleEmbeddingProviderOptions {
  config: ProviderConfig;
  env?: NodeJS.ProcessEnv;
  fetch?: typeof fetch;
}

interface EmbeddingResponse {
  data?: Array<{ embedding?: number[] }>;
}

export function createOpenAICompatibleEmbeddingProvider(
  options: OpenAICompatibleEmbeddingProviderOptions
): EmbeddingProvider {
  const env = options.env ?? process.env;
  const fetchImpl = options.fetch ?? globalThis.fetch;
  const { config } = options;

  return {
    async embedText(text: string): Promise<number[]> {
      const [embedding] = await this.embedTexts([text]);
      return embedding ?? [];
    },

    async embedTexts(texts: string[]): Promise<number[][]> {
      validateConfig(config, env);

      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), config.timeoutMs ?? 30000);

      try {
        const response = await fetchImpl(`${trimTrailingSlash(config.baseUrl ?? "")}/embeddings`, {
          method: "POST",
          headers: {
            authorization: `Bearer ${env[config.apiKeyEnv ?? ""]}`,
            "content-type": "application/json"
          },
          body: JSON.stringify({
            model: config.model,
            input: texts
          }),
          signal: controller.signal
        });

        if (!response.ok) {
          throw new LawchersError("PROVIDER_UNAVAILABLE", "Embedding provider request failed", {
            status: response.status
          });
        }

        const body = (await response.json()) as EmbeddingResponse;
        const embeddings = body.data?.map((item) => item.embedding).filter(isEmbedding) ?? [];

        if (embeddings.length !== texts.length) {
          throw new LawchersError("PROVIDER_UNAVAILABLE", "Embedding provider returned an invalid response");
        }

        return embeddings;
      } catch (error) {
        if (error instanceof LawchersError) {
          throw error;
        }

        if (error instanceof Error && error.name === "AbortError") {
          throw new LawchersError("TIMEOUT", "Embedding provider request timed out", {
            timeoutMs: config.timeoutMs ?? 30000
          });
        }

        throw new LawchersError("PROVIDER_UNAVAILABLE", "Embedding provider is unavailable", {
          reason: error instanceof Error ? error.message : "unknown"
        });
      } finally {
        clearTimeout(timeout);
      }
    }
  };
}

function validateConfig(config: ProviderConfig, env: NodeJS.ProcessEnv): void {
  if (config.type === "disabled") {
    throw new LawchersError("PROVIDER_DISABLED", "Embedding provider is disabled");
  }

  if (config.type !== "openai-compatible") {
    throw new LawchersError("PROVIDER_UNAVAILABLE", `Unsupported embedding provider: ${config.type}`);
  }

  if (!config.baseUrl || !config.model || !config.apiKeyEnv) {
    throw new LawchersError("PROVIDER_UNAVAILABLE", "Embedding provider config is incomplete");
  }

  if (!env[config.apiKeyEnv]) {
    throw new LawchersError("PROVIDER_UNAVAILABLE", `Missing API key environment variable: ${config.apiKeyEnv}`);
  }
}

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function isEmbedding(value: number[] | undefined): value is number[] {
  return Array.isArray(value) && value.every((item) => typeof item === "number");
}
