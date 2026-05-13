/**
 * 描述: 记忆数据库封装
 * 主要功能:
 *     - 基于 SQLite (better-sqlite3) 封装记忆存储和查询功能
 *     - 提供 Schema 迁移、会话记录、记忆片段的插入与基于 FTS 的全文搜索能力
 */

import { createHash, randomUUID } from "node:crypto";
import { mkdirSync } from "node:fs";
import path from "node:path";
import Database from "better-sqlite3";
import { LawchersError } from "../../../src/foundation/index.js";

export interface Conversation {
  id: string;
  userId: string;
  userMessage: string;
  assistantMessage: string | null;
  contentHash: string;
  createdAt: string;
}

export interface Memory {
  id: string;
  userId: string;
  type: string;
  content: string;
  contentHash: string;
  confidence: number;
  reason: string | null;
  rawSpanStart: number | null;
  rawSpanEnd: number | null;
  extractorName: string;
  extractorVersion: string;
  sourceConversationId: string | null;
  createdAt: string;
}

export interface InsertMemoryResult {
  id: string;
  contentHash: string;
  createdAt: string;
  status: "written" | "skipped";
}

export interface CreateDatabaseOptions {
  dbPath: string;
}

export interface Database {
  close(): void;
  migrate(): void;
  getSchemaVersion(): number;
  insertConversation(conv: Omit<Conversation, "id" | "createdAt" | "contentHash">): { id: string; contentHash: string; createdAt: string };
  insertMemory(mem: Omit<Memory, "id" | "createdAt" | "contentHash">): InsertMemoryResult;
  findConversationByHash(userId: string, contentHash: string): Conversation | undefined;
  findMemoryByHash(userId: string, contentHash: string): Memory | undefined;
  recallRecent(userId: string, limit: number): Memory[];
  recallFts(userId: string, query: string, limit: number): Memory[];
  listMemories(userId: string, limit: number): Memory[];
  deleteMemories(userId: string): void;
  isFtsAvailable(): boolean;
  diagnose(options: { dbPath: string; home: string }): Record<string, unknown>;
}

function toCamelCase(str: string): string {
  return str.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
}

function mapRow<T>(row: Record<string, unknown>): T {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(row)) {
    result[toCamelCase(key)] = value;
  }
  return result as T;
}

function mapRows<T>(rows: Record<string, unknown>[]): T[] {
  return rows.map((r) => mapRow<T>(r));
}

function computeContentHash(userId: string, userMessage: string, assistantMessage: string | null): string {
  return createHash("sha256")
    .update(userId)
    .update(userMessage)
    .update(assistantMessage ?? "")
    .digest("hex");
}

function computeMemoryContentHash(userId: string, type: string, content: string): string {
  return createHash("sha256").update(userId).update(type).update(content).digest("hex");
}

let lastTimestampMs = 0;

function nowISO(): string {
  const current = Date.now();
  const next = current <= lastTimestampMs ? lastTimestampMs + 1 : current;
  lastTimestampMs = next;
  return new Date(next).toISOString();
}

export function createDatabase(options: CreateDatabaseOptions): Database {
  const dbDir = path.dirname(options.dbPath);
  mkdirSync(dbDir, { recursive: true });

  const db = new Database(options.dbPath);

  db.pragma("journal_mode = WAL");
  db.pragma("foreign_keys = ON");
  db.pragma("busy_timeout = 5000");

  function migrate(): void {
    const currentVersion = getSchemaVersion();

    if (currentVersion === 0) {
      db.exec(`
        CREATE TABLE IF NOT EXISTS meta (
          key   TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS conversations (
          id                TEXT PRIMARY KEY,
          user_id           TEXT NOT NULL,
          user_message      TEXT NOT NULL,
          assistant_message TEXT,
          content_hash      TEXT NOT NULL,
          created_at        TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS memories (
          id                     TEXT PRIMARY KEY,
          user_id                TEXT NOT NULL,
          type                   TEXT NOT NULL,
          content                TEXT NOT NULL,
          content_hash           TEXT NOT NULL,
          confidence             REAL NOT NULL,
          reason                 TEXT,
          raw_span_start         INTEGER,
          raw_span_end           INTEGER,
          extractor_name         TEXT NOT NULL,
          extractor_version      TEXT NOT NULL,
          source_conversation_id TEXT,
          created_at             TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_user_hash ON memories(user_id, content_hash);
        CREATE INDEX IF NOT EXISTS idx_memories_user_created ON memories(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_conversations_user_hash ON conversations(user_id, content_hash);

        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(content);

        INSERT INTO meta (key, value) VALUES ('schema_version', '1');
      `);
    }
  }

  function getSchemaVersion(): number {
    const tableExists = db.prepare(
      "SELECT name FROM sqlite_master WHERE type='table' AND name='meta'"
    ).get() as { name: string } | undefined;

    if (!tableExists) return 0;

    const row = db.prepare("SELECT value FROM meta WHERE key = 'schema_version'").get() as { value: string } | undefined;
    return row ? parseInt(row.value, 10) : 0;
  }

  function insertConversation(
    conv: Omit<Conversation, "id" | "createdAt" | "contentHash">
  ): { id: string; contentHash: string; createdAt: string } {
    const contentHash = computeContentHash(conv.userId, conv.userMessage, conv.assistantMessage);
    const existing = findConversationByHash(conv.userId, contentHash);
    if (existing) {
      return { id: existing.id, contentHash: existing.contentHash, createdAt: existing.createdAt };
    }

    const id = randomUUID();
    const createdAt = nowISO();

    db.prepare(
      `INSERT INTO conversations (id, user_id, user_message, assistant_message, content_hash, created_at)
       VALUES (?, ?, ?, ?, ?, ?)`
    ).run(id, conv.userId, conv.userMessage, conv.assistantMessage, contentHash, createdAt);

    return { id, contentHash, createdAt };
  }

  function insertMemory(
    mem: Omit<Memory, "id" | "createdAt" | "contentHash">
  ): InsertMemoryResult {
    const contentHash = computeMemoryContentHash(mem.userId, mem.type, mem.content);
    const existing = findMemoryByHash(mem.userId, contentHash);
    if (existing) {
      return { id: existing.id, contentHash: existing.contentHash, createdAt: existing.createdAt, status: "skipped" };
    }

    const id = randomUUID();
    const createdAt = nowISO();

    const insertResult = db.prepare(
      `INSERT INTO memories (id, user_id, type, content, content_hash, confidence, reason,
        raw_span_start, raw_span_end, extractor_name, extractor_version, source_conversation_id, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    ).run(
      id, mem.userId, mem.type, mem.content, contentHash, mem.confidence,
      mem.reason, mem.rawSpanStart, mem.rawSpanEnd, mem.extractorName,
      mem.extractorVersion, mem.sourceConversationId, createdAt
    );

    db.prepare("INSERT INTO memory_fts (rowid, content) VALUES (?, ?)")
      .run(insertResult.lastInsertRowid, mem.content);

    return { id, contentHash, createdAt, status: "written" };
  }

  function findConversationByHash(userId: string, contentHash: string): Conversation | undefined {
    const row = db.prepare(
      "SELECT * FROM conversations WHERE user_id = ? AND content_hash = ?"
    ).get(userId, contentHash) as Record<string, unknown> | undefined;
    return row ? mapRow<Conversation>(row) : undefined;
  }

  function findMemoryByHash(userId: string, contentHash: string): Memory | undefined {
    const row = db.prepare(
      "SELECT * FROM memories WHERE user_id = ? AND content_hash = ?"
    ).get(userId, contentHash) as Record<string, unknown> | undefined;
    return row ? mapRow<Memory>(row) : undefined;
  }

  function recallRecent(userId: string, limit: number): Memory[] {
    const rows = db.prepare(
      "SELECT * FROM memories WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT ?"
    ).all(userId, limit) as Record<string, unknown>[];
    return mapRows<Memory>(rows);
  }

  function recallFts(userId: string, query: string, limit: number): Memory[] {
    try {
      const rows = db.prepare(
        `SELECT m.* FROM memories m
         INNER JOIN memory_fts fts ON m.rowid = fts.rowid
         WHERE m.user_id = ? AND memory_fts MATCH ?
         ORDER BY rank
         LIMIT ?`
      ).all(userId, query, limit) as Record<string, unknown>[];
      return mapRows<Memory>(rows);
    } catch {
      return [];
    }
  }

  function listMemories(userId: string, limit: number): Memory[] {
    const rows = db.prepare(
      "SELECT * FROM memories WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT ?"
    ).all(userId, limit) as Record<string, unknown>[];
    return mapRows<Memory>(rows);
  }

  function deleteMemories(userId: string): void {
    const rowIds = db.prepare("SELECT rowid FROM memories WHERE user_id = ?").all(userId) as { rowid: number }[];
    db.prepare("DELETE FROM memories WHERE user_id = ?").run(userId);
    for (const { rowid } of rowIds) {
      db.prepare("DELETE FROM memory_fts WHERE rowid = ?").run(rowid);
    }
  }

  function isFtsAvailable(): boolean {
    try {
      db.prepare("SELECT * FROM memory_fts LIMIT 0").run();
      return true;
    } catch {
      return false;
    }
  }

  function diagnose(opts: { dbPath: string; home: string }): Record<string, unknown> {
    const info: Record<string, unknown> = {};
    info.dbPath = opts.dbPath;
    info.homePath = opts.home;

    try {
      const dbSize = db.pragma("page_count") as unknown as number;
      const pageSize = db.pragma("page_size") as unknown as number;
      info.dbFileSize = dbSize * pageSize;
    } catch {
      info.dbFileSize = 0;
    }

    info.schemaVersion = getSchemaVersion();
    info.ftsAvailable = isFtsAvailable();
    info.walMode = db.pragma("journal_mode") === "wal";

    return info;
  }

  return {
    close() { db.close(); },
    migrate,
    getSchemaVersion,
    insertConversation,
    insertMemory,
    findConversationByHash,
    findMemoryByHash,
    recallRecent,
    recallFts,
    listMemories,
    deleteMemories,
    isFtsAvailable,
    diagnose,
  };
}
