import { isLidUser, isPnUser, jidDecode } from "@whiskeysockets/baileys";
import type { WAMessage } from "@whiskeysockets/baileys";
import type Database from "better-sqlite3";
import type { Logger } from "pino";
import { z } from "zod";

const UPSERT_LID = `
  INSERT INTO lid_map (lid, pn, learned_at) VALUES (?, ?, ?)
  ON CONFLICT(lid) DO UPDATE SET pn = excluded.pn, learned_at = excluded.learned_at`;

const messageKey = z.object({
  remoteJid: z.string().nullish(),
  participant: z.string().nullish(),
  remoteJidAlt: z.string().nullish(),
  participantAlt: z.string().nullish(),
});
const mappedRow = z.object({ pn: z.string() });

type MessageKey = z.infer<typeof messageKey>;

export type SenderFilterDeps = {
  readonly db: Database.Database;
  readonly logger: Logger;
  readonly allowedPn: string;
  readonly clock?: () => Date;
};

export type SenderDecision = {
  readonly accepted: boolean;
  readonly senderPn: string | undefined;
  readonly senderJid: string | undefined;
};

export function senderFilter(deps: SenderFilterDeps, message: WAMessage): SenderDecision {
  const parsed = messageKey.safeParse(message.key);
  if (!parsed.success) return reject(deps, undefined, undefined);
  const senderJid = senderJidOf(parsed.data);
  const senderPn = resolvePhoneNumber(deps, parsed.data, senderJid);
  if (senderPn !== deps.allowedPn) return reject(deps, senderJid, senderPn);
  return { accepted: true, senderPn, senderJid };
}

function senderJidOf(key: MessageKey): string | undefined {
  return key.participant ?? key.remoteJid ?? undefined;
}

function resolvePhoneNumber(
  deps: SenderFilterDeps,
  key: MessageKey,
  senderJid: string | undefined,
): string | undefined {
  if (senderJid === undefined) return undefined;
  if (isPnUser(senderJid)) return jidDecode(senderJid)?.user;
  if (!isLidUser(senderJid)) return undefined;
  const lid = jidDecode(senderJid)?.user;
  if (lid === undefined) return undefined;
  const learned = phoneNumberFromAlternate(alternateJidOf(key));
  if (learned === undefined) return lookUpLid(deps.db, lid);
  rememberLid(deps, lid, learned);
  return learned;
}

// For a message sent in a chat, Baileys puts the alternate of the chat id in remoteJidAlt; for a
// sender inside a group it is the alternate of the participant.
function alternateJidOf(key: MessageKey): string | undefined {
  const alternate = key.participant ? key.participantAlt : key.remoteJidAlt;
  return alternate ?? undefined;
}

function phoneNumberFromAlternate(alternate: string | undefined): string | undefined {
  return isPnUser(alternate) ? jidDecode(alternate)?.user : undefined;
}

function lookUpLid(db: Database.Database, lid: string): string | undefined {
  const row = db.prepare("SELECT pn FROM lid_map WHERE lid = ?").get(lid);
  return row === undefined ? undefined : mappedRow.parse(row).pn;
}

function rememberLid(deps: SenderFilterDeps, lid: string, pn: string): void {
  const learnedAt = (deps.clock ?? (() => new Date()))().toISOString();
  deps.db.prepare(UPSERT_LID).run(lid, pn, learnedAt);
}

function reject(
  deps: SenderFilterDeps,
  senderJid: string | undefined,
  senderPn: string | undefined,
): SenderDecision {
  deps.logger.debug({ senderJid }, "message_ignored_unknown_sender");
  return { accepted: false, senderPn, senderJid };
}
