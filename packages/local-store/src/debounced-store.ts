import { readJsonFile, writeJsonFileAtomic } from "./json-store.js";
import { withFileLock } from "./file-lock.js";
import { LawchersError } from "@lawchers/shared-core";

export interface DebouncedJsonStoreOptions<T> {
  filePath: string;
  fallback: T;
  debounceMs?: number;
  lockPath?: string;
}

export class DebouncedJsonStore<T> {
  private readonly filePath: string;
  private readonly fallback: T;
  private readonly debounceMs: number;
  private readonly lockPath: string;
  private value: T | undefined;
  private timer: NodeJS.Timeout | undefined;
  private pendingFlush: Promise<void> | undefined;
  private disposed = false;

  constructor(options: DebouncedJsonStoreOptions<T>) {
    this.filePath = options.filePath;
    this.fallback = options.fallback;
    this.debounceMs = options.debounceMs ?? 100;
    this.lockPath = options.lockPath ?? `${options.filePath}.lock`;
  }

  async load(): Promise<T> {
    this.value = await readJsonFile(this.filePath, this.fallback);
    return this.value;
  }

  async update(updater: (current: T) => T | Promise<T>): Promise<T> {
    if (this.disposed) {
      throw new LawchersError("INVALID_INPUT", "store disposed");
    }

    const current = this.value ?? (await this.load());
    this.value = await updater(current);
    this.scheduleFlush();
    return this.value;
  }

  async flush(): Promise<void> {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }

    if (this.pendingFlush) {
      await this.pendingFlush;
      return;
    }

    const value = this.value ?? (await this.load());
    this.pendingFlush = withFileLock(this.lockPath, () => writeJsonFileAtomic(this.filePath, value));

    try {
      await this.pendingFlush;
    } finally {
      this.pendingFlush = undefined;
    }
  }

  async dispose(): Promise<void> {
    await this.flush();
    this.disposed = true;
  }

  private scheduleFlush(): void {
    if (this.timer) {
      clearTimeout(this.timer);
    }

    this.timer = setTimeout(() => {
      this.flush().catch(() => undefined);
    }, this.debounceMs);
  }
}
