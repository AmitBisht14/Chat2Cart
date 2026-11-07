import {
  getContentType,
  isJidBroadcast,
  isJidGroup,
  isJidNewsletter,
  isJidStatusBroadcast,
  normalizeMessageContent,
} from "@whiskeysockets/baileys";
import type { WAMessage } from "@whiskeysockets/baileys";

export type IgnoreReason =
  "from_me" | "group" | "status" | "broadcast" | "newsletter" | "edit_or_delete" | "media";

export type IntakeResult =
  | { readonly accept: true; readonly text: string }
  | { readonly accept: false; readonly reason: IgnoreReason; readonly detail?: string };

const CHAT_KINDS = [
  { reason: "status", matches: isJidStatusBroadcast },
  { reason: "group", matches: isJidGroup },
  { reason: "broadcast", matches: isJidBroadcast },
  { reason: "newsletter", matches: isJidNewsletter },
] as const;

export function applyIntakeRules(message: WAMessage): IntakeResult {
  if (message.key.fromMe === true) return ignore("from_me");
  const chatKind = CHAT_KINDS.find(({ matches }) => matches(message.key.remoteJid ?? ""));
  if (chatKind !== undefined) return ignore(chatKind.reason);
  if (isEditOrDelete(message)) return ignore("edit_or_delete");
  return acceptText(message) ?? ignore("media", firstContentKey(message));
}

// Baileys' normalizeMessageContent unwraps editedMessage, so an edit has to be spotted before it.
function isEditOrDelete(message: WAMessage): boolean {
  const raw = message.message;
  const content = normalizeMessageContent(raw);
  return Boolean(raw?.editedMessage ?? raw?.protocolMessage ?? content?.protocolMessage);
}

function acceptText(message: WAMessage): IntakeResult | undefined {
  const content = normalizeMessageContent(message.message);
  const text = (content?.conversation ?? content?.extendedTextMessage?.text ?? "").trim();
  return text === "" ? undefined : { accept: true, text };
}

function firstContentKey(message: WAMessage): string | undefined {
  return getContentType(normalizeMessageContent(message.message));
}

function ignore(reason: IgnoreReason, detail?: string): IntakeResult {
  return detail === undefined ? { accept: false, reason } : { accept: false, reason, detail };
}
