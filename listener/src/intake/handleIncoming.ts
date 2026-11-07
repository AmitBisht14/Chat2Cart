import type { WAMessage } from "@whiskeysockets/baileys";
import type Database from "better-sqlite3";
import type { Logger } from "pino";
import { saveToInbox, toInboxRow } from "./inbox.js";
import { applyIntakeRules } from "./rules.js";
import type { IntakeResult } from "./rules.js";
import { senderFilter } from "./senderFilter.js";

export type IntakeDeps = {
  readonly db: Database.Database;
  readonly logger: Logger;
  readonly allowedPn: string;
};

export function handleIncoming(message: WAMessage, deps: IntakeDeps): void {
  const intake = applyIntakeRules(message);
  if (!intake.accept) {
    logIgnored(deps.logger, intake, message.key.id);
    return;
  }
  const sender = senderFilter(deps, message);
  if (!sender.accepted) return;
  const row = toInboxRow(message, intake.text, sender);
  if (row === undefined) {
    deps.logger.warn({ messageId: message.key.id }, "inbound_missing_fields");
    return;
  }
  if (saveToInbox(deps, row)) deps.logger.info({ messageId: row.id }, "message_received");
}

// Media and edits are worth an info line; the rest is routine noise. Never log the message text.
function logIgnored(
  logger: Logger,
  intake: Extract<IntakeResult, { accept: false }>,
  messageId: string | null | undefined,
): void {
  const level = intake.reason === "media" || intake.reason === "edit_or_delete" ? "info" : "debug";
  logger[level]({ reason: intake.reason, detail: intake.detail, messageId }, "intake_ignored");
}
