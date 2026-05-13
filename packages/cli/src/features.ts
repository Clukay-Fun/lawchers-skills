/**
 * 描述: lawchers 静态 feature 注册表
 * 主要功能:
 *     - 注册当前可用的业务功能模块
 *     - 提供 domain 到 feature 的查找能力
 */

import { memoryFeature } from "../skills/memory-tools/scripts/index.js";
import type { CommandFeature } from "./foundation/index.js";

export const features: CommandFeature[] = [
  memoryFeature,
];

export function getFeature(domain: string): CommandFeature | undefined {
  return features.find((feature) => feature.domain === domain);
}

export function availableDomains(): string[] {
  return features.map((feature) => feature.domain);
}
