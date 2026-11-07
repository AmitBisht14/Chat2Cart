import type { WAMessage } from "@whiskeysockets/baileys";
import type Database from "better-sqlite3";
import type { Logger } from "pino";
import { z } from "zod";
import type { SenderDecision } from "./senderFilter.js";

const INSERT_MESSAGE = `
  INSERT OR IGNORE INTO inbound_messages
    (id, chat_jid, sender_jid, sender_pn, text, received_at, status)
  VALUES (?, ?, ?, ?, ?, ?, 'pending')`;

const nonEmpty = z.string().min(1);
const inboxRow = z.object({
  id: nonEmpty,
  chatJid: nonEmpty,
  senderJid: nonEmpty,
  senderPn: nonEmpty,
  text: nonEmpty,
});

export type InboxRow = z.infer<typeof inboxRow>;

export type InboxDeps = {
  readonly db: Database.Database;
  readonly logger: Logger;
  readonly clock?: () => Date;
};

export function toInboxRow(
  message: WAMessage,
  text: string,
  sender: SenderDecision,
): InboxRow | undefined {
  const parsed = inboxRow.safeParse({
    id: message.key.id,
    chatJid: message.key.remoteJid,
    senderJid: sender.senderJid,
    senderPn: sender.senderPn,
    text,
  });
  return parsed.success ? parsed.data : undefined;
}

// Returns true when the message is new. The WhatsApp message id is the key, so a message
// WhatsApp delivers again (for example after a reconnect) is skipped.
export function saveToInbox(deps: InboxDeps, row: InboxRow): boolean {
  const receivedAt = (deps.clock ?? (() => new Date()))().toISOString();
  const result = deps.db
    .prepare(INSERT_MESSAGE)
    .run(row.id, row.chatJid, row.senderJid, row.senderPn, row.text, receivedAt);
  if (result.changes > 0) return true;
  deps.logger.info({ messageId: row.id }, "inbound_duplicate");
  return false;
}
