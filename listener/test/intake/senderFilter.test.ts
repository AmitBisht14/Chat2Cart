import Database from "better-sqlite3";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { Writable } from "node:stream";
import pino from "pino";
import type { WAMessage } from "@whiskeysockets/baileys";
import { afterEach, beforeEach, expect, it } from "vitest";
import { createSchemaDatabase } from "../fakes/database.js";
import { senderFilter } from "../../src/intake/senderFilter.js";

const ALLOWED = "919876543210";
const OTHER = "919000000001";
const LID = "123456789012345";
const LEARNED_AT = new Date("2026-11-07T10:00:00.000Z");

let folder: string;
let db: Database.Database;
let logLines: string[];

beforeEach(() => {
  folder = mkdtempSync(path.join(tmpdir(), "chat2cart-sender-"));
  const dbPath = path.join(folder, "chat2cart.sqlite");
  createSchemaDatabase(dbPath, 1);
  db = new Database(dbPath);
  logLines = [];
});

afterEach(() => {
  db.close();
  rmSync(folder, { recursive: true, force: true });
});

function filter(key: Record<string, string>): ReturnType<typeof senderFilter> {
  const sink = new Writable({
    write(chunk: Buffer, _encoding, done): void {
      logLines.push(chunk.toString());
      done();
    },
  });
  const logger = pino({ level: "debug" }, sink);
  const message = { key } as unknown as WAMessage;
  return senderFilter({ db, logger, allowedPn: ALLOWED, clock: () => LEARNED_AT }, message);
}

function storedMappings(): unknown[] {
  return db.prepare("SELECT lid, pn, learned_at FROM lid_map").all();
}

it("accepts_the_allowed_number_as_a_phone_jid", () => {
  const decision = filter({ remoteJid: `${ALLOWED}@s.whatsapp.net` });

  expect(decision).toEqual({
    accepted: true,
    senderPn: ALLOWED,
    senderJid: `${ALLOWED}@s.whatsapp.net`,
  });
});

it("accepts_the_allowed_number_whatever_its_device_suffix", () => {
  const decision = filter({ remoteJid: `${ALLOWED}:12@s.whatsapp.net` });

  expect(decision.accepted).toBe(true);
});

it("accepts_a_lid_with_the_allowed_number_in_the_alternate_field_and_stores_the_pair", () => {
  const decision = filter({
    remoteJid: `${LID}@lid`,
    remoteJidAlt: `${ALLOWED}@s.whatsapp.net`,
  });

  expect(decision).toMatchObject({ accepted: true, senderPn: ALLOWED });
  expect(storedMappings()).toEqual([
    { lid: LID, pn: ALLOWED, learned_at: LEARNED_AT.toISOString() },
  ]);
});

it("accepts_a_later_lid_with_no_alternate_field_using_the_stored_mapping", () => {
  filter({ remoteJid: `${LID}@lid`, remoteJidAlt: `${ALLOWED}@s.whatsapp.net` });

  const decision = filter({ remoteJid: `${LID}@lid` });

  expect(decision).toMatchObject({ accepted: true, senderPn: ALLOWED });
});

it("reads_the_participant_alternate_field_for_a_sender_inside_a_group", () => {
  const decision = filter({
    remoteJid: "120363000000000000@g.us",
    participant: `${LID}@lid`,
    participantAlt: `${ALLOWED}@s.whatsapp.net`,
  });

  expect(decision).toMatchObject({ accepted: true, senderPn: ALLOWED });
});

it("rejects_an_unknown_lid_and_logs_at_debug_level_with_the_jid_only", () => {
  const decision = filter({ remoteJid: `${LID}@lid` });

  expect(decision).toEqual({ accepted: false, senderPn: undefined, senderJid: `${LID}@lid` });
  const entry = JSON.parse(logLines.join("")) as Record<string, unknown>;
  expect(entry).toMatchObject({ level: 20, senderJid: `${LID}@lid` });
});

it("rejects_a_different_phone_number_and_logs_at_debug_level", () => {
  const decision = filter({ remoteJid: `${OTHER}@s.whatsapp.net` });

  expect(decision).toMatchObject({ accepted: false, senderPn: OTHER });
  expect(logLines).toHaveLength(1);
});

it("rejects_a_lid_whose_stored_mapping_is_a_different_number", () => {
  filter({ remoteJid: `${LID}@lid`, remoteJidAlt: `${OTHER}@s.whatsapp.net` });

  const decision = filter({ remoteJid: `${LID}@lid` });

  expect(decision).toMatchObject({ accepted: false, senderPn: OTHER });
});

it("rejects_a_message_with_no_sender", () => {
  expect(filter({}).accepted).toBe(false);
});
