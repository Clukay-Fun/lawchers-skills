import { promises as fs } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { LawchersError } from "@lawchers/shared-core";

export async function readJsonFile<T>(filePath: string, fallback: T): Promise<T> {
  try {
    const raw = await fs.readFile(filePath, "utf8");
    return JSON.parse(raw) as T;
  } catch (error) {
    if (isNodeError(error) && error.code === "ENOENT") {
      return fallback;
    }

    if (error instanceof SyntaxError) {
      throw new LawchersError("INVALID_INPUT", `JSON file is not valid: ${filePath}`, {
        path: filePath
      }, error);
    }

    throw new LawchersError("IO_ERROR", `Failed to read JSON file: ${filePath}`, {
      path: filePath
    }, error);
  }
}

export async function writeJsonFileAtomic(filePath: string, value: unknown): Promise<void> {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  const tempPath = path.join(path.dirname(filePath), `.${path.basename(filePath)}.${process.pid}.${randomUUID()}.tmp`);
  const body = `${JSON.stringify(value, null, 2)}\n`;

  try {
    await fs.writeFile(tempPath, body, "utf8");
    await renameReplacingExisting(tempPath, filePath);
  } catch (error) {
    await fs.rm(tempPath, { force: true }).catch(() => undefined);
    throw new LawchersError("IO_ERROR", `Failed to write JSON file: ${filePath}`, {
      path: filePath,
      reason: error instanceof Error ? error.message : "unknown"
    }, error);
  }
}

async function renameReplacingExisting(tempPath: string, filePath: string): Promise<void> {
  try {
    await fs.rename(tempPath, filePath);
  } catch (error) {
    if (!isNodeError(error) || (error.code !== "EEXIST" && error.code !== "EPERM")) {
      throw error;
    }

    await fs.rm(filePath, { force: true });
    await fs.rename(tempPath, filePath);
  }
}

function isNodeError(error: unknown): error is NodeJS.ErrnoException {
  return error instanceof Error && "code" in error;
}
