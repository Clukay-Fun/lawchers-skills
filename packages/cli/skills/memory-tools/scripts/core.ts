/**
 * 描述: 核心方法导出
 * 主要功能:
 *     - 聚合导出记忆核心模块 (config, db, extractor) 的相关接口与工厂函数
 */

import { createMemoryConfig, type ResolvedMemoryConfig, type MemoryConfig } from "./config.js";
import { createDatabase, type Database, type Conversation, type Memory } from "./db.js";
import { createExtractor, type MemoryExtractor } from "./extractor.js";

export { createMemoryConfig, type ResolvedMemoryConfig, type MemoryConfig };
export { createDatabase, type Database, type Conversation, type Memory };
export { createExtractor, type MemoryExtractor };
