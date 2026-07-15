---
name: legal-assistant
version: 0.1.0
description: "Law-office daily-ops automation: inbound invoice filing, outbound invoice booking, contract registration, scan archiving, and scheduled summary push (Feishu Bitable via lark-cli). Use when the user needs to process invoice zips, register contracts, organize scanned files, generate the summary report, or review pending invoice items."
metadata:
  requires:
    bins: ["legal-assistant", "lark-cli"]
---

# legal-assistant

> **Prerequisite:** For Feishu auth/permission issues, read the `lark-shared` skill (`~/.claude/skills/lark-shared/SKILL.md`) first.

## Core Principle

**Scripts do the work; the agent assists.** The `legal-assistant` CLI is the sole capability core. Every deterministic batch job (invoice parsing, classification/archiving, aggregation, push) is done by the CLI, invoked by Windows Task Scheduler. The agent does exactly three things:

1. **Fuzzy steps**: contract registration confirmation, and outbound-invoice review (resolve).
2. **Exception handling**: diagnose CLI failures (run `doctor` first), trace via journal.
3. **Ad-hoc requests**: one-off operations the user explicitly asks for.

The agent must **not**: bypass the CLI to write the three business tables directly (sole exception: see Confirmation Protocol); commit contracts or pending items before the user confirms; guess contract numbers or alter OCR-extracted values.

## On Every Wake-Up

1. Read recent activity: `legal-assistant journal --config <config.yaml>` (last 3 days of operations, including leftover todos).
2. If pending items need handling: `legal-assistant pending --config <config.yaml>`.

## Agent Decision Table

| User intent | Command | Notes |
|---|---|---|
| Diagnose environment/config | `legal-assistant doctor --config config.yaml` | Run this first on any error; every finding comes with a fix |
| Process invoice zip (inbound filing) | `legal-assistant invoice-once --config config.yaml` | Fully automatic: extract → classify → write ledger → archive; safe to rerun (invoice-number idempotent) |
| Organize scanned files | `legal-assistant scan-once --config config.yaml` | Fully automatic 7-category filing; locked files skipped |
| Generate/push the scheduled summary | `legal-assistant weekly-summary --config config.yaml [--dry-run]` | `--dry-run` writes a local snapshot only; preview for the user first |
| Book outbound invoices | `legal-assistant output-invoice-once --config config.yaml` | Writes only on a unique contract match; ambiguity auto-pends |
| List pending items | `legal-assistant pending --config config.yaml` | JSON: extracted fields + candidate contract numbers + pend reason |
| Complete a pending item (user must confirm) | `legal-assistant resolve <key> --contract-no <no> [--member <name>] [--amount …]` | See Confirmation Protocol |
| Register a contract | `legal-assistant contract-draft <contract.pdf>` → confirm → `legal-assistant contract-commit --draft <draft.json>` | See Confirmation Protocol |
| Check operation history | `legal-assistant journal --days 7` | Trace what happened on a given day |

All batch commands support `--dry-run` (no Feishu writes, no file moves). When unsure of consequences, dry-run first and show the user.

## Confirmation Protocol

**Outbound-invoice pending items (resolve)** — never guess a contract number:

1. Read pending items via `pending`: show the extracted fields (invoice no / date / amount / payer), the pend reason, and the candidate contract list.
2. If there are zero or multiple candidates, present the candidate list verbatim and let the user pick. You may use the lark-base skill to query the contract ledger to help the user decide, but **the decision is the user's**.
3. Only run `resolve` after the user names the contract number. If OCR fields are wrong, correct them via `--invoice-no/--amount/--payer/--date` exactly as the user dictates — never invent values.
4. `resolve` has the same semantics as the automatic path: write the stats table + **write back to the contract ledger** + archive the PDF. For items pended with "main record written but ledger write-back failed", simply rerun `resolve` as instructed — it will not create a duplicate main record.

**Contract registration (draft → commit)** — no business data lands before confirmation:

1. `contract-draft <pdf>` produces a draft JSON (only reliable fields prefilled: credit code / amount / date; everything else left empty).
2. Present the draft field by field; collect the user's additions (contract number and client name are required; business fields like payment milestones or handling lawyer are written into the draft as dictated — extra draft keys must use the Feishu table's real field names).
3. Run `contract-commit --draft <json>` only after the user says "confirm". A duplicate contract number is rejected — verify with the user whether it's a duplicate registration; do **not** retry with a different number.

## Output & State Conventions

```text
发票整理/YYYY-MM-DD/<invoice type>/*.pdf     inbound-invoice classified output (for printing)
发票收件箱/已处理/*.zip                       inbound-invoice archived source zips
state/<domain>.json                          Status ledger (discovered/processing/succeeded/pending_review/failed/skipped_locked)
state/contract_drafts/*.draft.json           contract-registration drafts
journal/YYYY-MM-DD.md                        Operation log (agent memory; never synced to Feishu)
```

Exit codes: `0` success; `1` some items failed (read stderr and the journal); `2` config error (run doctor).

## Safety Boundaries

- All writes to the three business tables (reimbursement ledger / contract ledger / invoicing stats) go through the CLI, guaranteeing idempotency and journal traceability.
- `团队成员` (team member) and `贴票时间` (filing time) are filled by the user in Feishu; no flow may fill them (sole exception: an explicit `--member` given by the user to resolve).
- Never paste ID numbers, phone numbers, or other sensitive fields into the journal or chat.
- Invoice numbers and contract numbers are idempotency keys: when a duplicate write is rejected, report it honestly — do not tweak the number to get around it.
- Before an official summary push, run `--dry-run` for the user to preview if they are present.

## Feishu Permissions

Authentication and credentials are managed by lark-cli (`lark-cli config init` / `auth login`); this project stores no secrets. Typical scopes (when one is missing, grant incrementally per the error's `permission_violations` / `hint`; see lark-shared):

| Operation | Typical scope |
|---|---|
| Read/write Bitable records | `bitable:app` |
| Upload contract attachments | `bitable:app` + `drive:drive` |
| Summary DM push | `im:message.send_as_user` (user) or `im:message:send_as_bot` (bot) |

## Install & Self-Test

```bash
pip install -e ".[dev,pdf]"        # from project root; pdf extra = pymupdf (PDF text layer, needed by invoice booking & scans)
cp config.example.yaml config.yaml # adjust to local paths; config.yaml stays out of git
legal-assistant doctor --config config.yaml
```

Windows scheduling: `deploy/register-tasks.ps1` (Task Scheduler: inbox polling + weekly summary; day/time customizable via `-WeeklyDay`/`-WeeklyTime`, default Friday 16:00). Project layout: the Python code lives flat in `scripts/`, mapped to the `legal_assistant` package (see pyproject).
