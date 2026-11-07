import type { WAMessage } from "@whiskeysockets/baileys";
import { expect, it } from "vitest";
import { applyIntakeRules } from "../../src/intake/rules.js";

const DIRECT = "919876543210@s.whatsapp.net";

function message(
  content: Record<string, unknown> | undefined,
  key: Record<string, unknown> = {},
): WAMessage {
  return {
    key: { remoteJid: DIRECT, id: "m1", fromMe: false, ...key },
    message: content,
  } as WAMessage;
}

it.each([
  ["group", "120363000000000000@g.us"],
  ["status", "status@broadcast"],
  ["broadcast", "1234567890@broadcast"],
  ["newsletter", "120363000000000001@newsletter"],
])("ignores_a_%s_message", (reason, remoteJid) => {
  const result = applyIntakeRules(message({ conversation: "milk" }, { remoteJid }));

  expect(result).toEqual({ accept: false, reason });
});

it("ignores_a_message_sent_from_this_account", () => {
  const result = applyIntakeRules(message({ conversation: "milk" }, { fromMe: true }));

  expect(result).toEqual({ accept: false, reason: "from_me" });
});

it.each([
  ["audioMessage", { audioMessage: { ptt: true } }],
  ["imageMessage", { imageMessage: {} }],
  ["documentMessage", { documentMessage: {} }],
  ["stickerMessage", { stickerMessage: {} }],
])("ignores_%s_as_media_and_names_the_content_key", (detail, content) => {
  const result = applyIntakeRules(message(content));

  expect(result).toEqual({ accept: false, reason: "media", detail });
});

it("accepts_a_plain_conversation_message_with_its_text", () => {
  const result = applyIntakeRules(message({ conversation: "  2 litres milk  " }));

  expect(result).toEqual({ accept: true, text: "2 litres milk" });
});

it("accepts_an_extended_text_message_with_its_text", () => {
  const result = applyIntakeRules(message({ extendedTextMessage: { text: "bread and eggs" } }));

  expect(result).toEqual({ accept: true, text: "bread and eggs" });
});

it("ignores_a_revoked_message", () => {
  const result = applyIntakeRules(message({ protocolMessage: { type: 0 } }));

  expect(result).toEqual({ accept: false, reason: "edit_or_delete" });
});

it("ignores_an_edited_message_even_though_it_carries_text", () => {
  const edit = { editedMessage: { message: { conversation: "3 litres milk" } } };

  expect(applyIntakeRules(message(edit))).toEqual({ accept: false, reason: "edit_or_delete" });
});

it("treats_a_message_with_empty_text_as_not_text", () => {
  const result = applyIntakeRules(message({ conversation: "   " }));

  expect(result).toMatchObject({ accept: false, reason: "media" });
});

it("treats_a_message_with_no_content_as_media_without_a_detail", () => {
  const result = applyIntakeRules(message(undefined));

  expect(result).toEqual({ accept: false, reason: "media" });
});
