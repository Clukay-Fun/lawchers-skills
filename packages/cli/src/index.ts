/**
 * 描述: @lawchers/cli 公共 API 导出入口
 * 主要功能:
 *     - 导出 CLI 执行内核供本地测试调用
 *     - 重新导出 feature registry 相关公共类型
 */

export { runCli, exitCodeForResult, type RunCliOptions, type RunCliResult } from "./run.js";
export { parseCliInput, type ParsedCliInput } from "./parser.js";
export type {
  CommandFeature,
  CommandHandler,
  CliContext,
  DoctorSection,
  GlobalFlags,
  ParsedArgs,
} from "./foundation/index.js";
export * from "./foundation/index.js";
