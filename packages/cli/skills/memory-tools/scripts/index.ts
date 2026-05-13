/**
 * 描述: 模块公开导出入口
 * 主要功能:
 *     - 暴露本包向外部提供的所有类型定义与可用 API
 */

export type { ResolvedMemoryConfig } from "./config.js";
export { createMemoryConfig } from "./config.js";
export type { Database, Conversation, Memory, InsertMemoryResult } from "./db.js";
export { createDatabase } from "./db.js";
export type { ProviderStatus } from "./provider-status.js";
export { checkEmbeddingProviderStatus, embeddingStatusWarning } from "./provider-status.js";
export { memoryFeature } from "./feature.js";
