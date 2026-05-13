/**
 * 描述: lawchers CLI 内置底座公共 API 导出入口
 * 主要功能:
 *     - 统一导出配置、错误、日志、JSON result 和 registry 契约
 *     - 汇总本地存储与 embedding provider 基础能力
 */

export * from "./config.js";
export * from "./cli-types.js";
export * from "./errors.js";
export * from "./logger.js";
export * from "./result.js";
export * from "./embedding-provider/index.js";
