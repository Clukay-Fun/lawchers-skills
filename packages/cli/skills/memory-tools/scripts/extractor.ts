/**
 * 描述: 文本意图与记忆提取器
 * 主要功能:
 *     - 基于正则表达式分析用户输入
 *     - 自动提取用户输入中的偏好 (preference)、事实 (fact) 和目标 (goal) 并输出置信度
 */

import { LawchersError } from "../../../src/foundation/index.js";

export interface MemoryCandidate {
  type: string;
  content: string;
  confidence: number;
  reason: string;
  rawSpanStart?: number;
  rawSpanEnd?: number;
}

export interface MemoryExtractor {
  readonly name: string;
  readonly version: string;
  extract(userMessage: string, assistantMessage: string | null): MemoryCandidate[];
}

export interface ExtractorConfig {
  type: "rule" | "noop";
  confidenceThreshold: number;
}

export function createExtractor(config: ExtractorConfig): MemoryExtractor {
  switch (config.type) {
    case "rule":
      return createRuleExtractor(config.confidenceThreshold);
    case "noop":
      return createNoopExtractor();
    default:
      throw new LawchersError("CONFIG_INVALID", `Unknown extractor type: ${config.type}`, {
        extractorType: config.type,
      });
  }
}

function createRuleExtractor(confidenceThreshold: number): MemoryExtractor {
  return {
    name: "rule",
    version: "1.0.0",
    extract(userMessage: string, assistantMessage: string | null): MemoryCandidate[] {
      const candidates: MemoryCandidate[] = [];
      const text = userMessage + (assistantMessage ? "\n" + assistantMessage : "");

      const preferenceMatch = text.match(/(?:我喜欢|我讨厌|我倾向于|我希望|我不喜欢|我爱|我恨)([^。！？\n]+)/g);
      if (preferenceMatch) {
        for (const match of preferenceMatch) {
          candidates.push({
            type: "preference",
            content: match.trim(),
            confidence: 0.7,
            reason: "Expression of preference detected",
            rawSpanStart: text.indexOf(match),
            rawSpanEnd: text.indexOf(match) + match.length,
          });
        }
      }

      const factMatch = text.match(/(?:我是[^，。！？\n]+|我的[^，。！？\n]+是[^，。！？\n]+|我(?:在|住在)[^，。！？\n]+|我有\s*[^，。！？\n]+经验|我会\s*[^，。！？\n]+)/g);
      if (factMatch) {
        for (const match of factMatch) {
          candidates.push({
            type: "fact",
            content: match.trim(),
            confidence: 0.6,
            reason: "Personal fact stated",
            rawSpanStart: text.indexOf(match),
            rawSpanEnd: text.indexOf(match) + match.length,
          });
        }
      }

      const goalMatch = text.match(/(?:我想要|我计划|我打算|我的目标|我希望(?!\S)|我决定|我要|我需要)([^。！？\n]+)/g);
      if (goalMatch) {
        for (const match of goalMatch) {
          candidates.push({
            type: "goal",
            content: match.trim(),
            confidence: 0.6,
            reason: "Goal or intention expressed",
            rawSpanStart: text.indexOf(match),
            rawSpanEnd: text.indexOf(match) + match.length,
          });
        }
      }

      return candidates.filter((c) => c.confidence >= confidenceThreshold);
    },
  };
}

function createNoopExtractor(): MemoryExtractor {
  return {
    name: "noop",
    version: "1.0.0",
    extract(_userMessage: string, _assistantMessage: string | null): MemoryCandidate[] {
      return [];
    },
  };
}
