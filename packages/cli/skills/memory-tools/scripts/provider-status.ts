/**
 * 描述: 模型服务提供商状态检测
 * 主要功能:
 *     - 检测 Embedding 模型服务的配置是否完整和可用
 *     - 生成相应的服务状态及可用性警告信息
 */

import { LawchersError, type ProviderConfig } from "../../../src/foundation/index.js";

export interface ProviderStatus {
  status: "ok" | "disabled" | "unavailable";
  detail: Record<string, unknown>;
}

export function checkEmbeddingProviderStatus(
  providerConfig: ProviderConfig,
  env: NodeJS.ProcessEnv = process.env
): ProviderStatus {
  const detail: Record<string, unknown> = { type: providerConfig.type };

  if (providerConfig.type === "disabled") {
    return { status: "disabled", detail };
  }

  try {
    if (providerConfig.type !== "openai-compatible") {
      throw new LawchersError("PROVIDER_UNAVAILABLE", `Unsupported embedding provider: ${providerConfig.type}`);
    }

    if (!providerConfig.baseUrl || !providerConfig.model || !providerConfig.apiKeyEnv) {
      throw new LawchersError("PROVIDER_UNAVAILABLE", "Embedding provider config is incomplete");
    }

    if (!env[providerConfig.apiKeyEnv]) {
      throw new LawchersError(
        "PROVIDER_UNAVAILABLE",
        `Missing API key environment variable: ${providerConfig.apiKeyEnv}`,
        { apiKeyEnv: providerConfig.apiKeyEnv }
      );
    }

    return { status: "ok", detail };
  } catch (error) {
    detail.error = error instanceof Error ? error.message : String(error);
    return { status: "unavailable", detail };
  }
}

export function embeddingStatusWarning(status: ProviderStatus): string | undefined {
  if (status.status === "disabled") {
    return "PROVIDER_DISABLED: Embedding provider is disabled; recall uses FTS + recent only";
  }

  if (status.status === "unavailable") {
    return "PROVIDER_UNAVAILABLE: Embedding provider not available; recall uses FTS + recent only";
  }

  return undefined;
}
