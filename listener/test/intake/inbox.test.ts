import Database from "better-sqlite3";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { Writable } from "node:stream";
import pino from "pino";
import type { WAMessage } from "@whiskeysockets/baileys";
import { afterEach, beforeEach, expect, it } from "vitest";
import { createSchemaDatabase } from "../fakes/database.js";
import { saveToInbox, toInboxRow } from "../../src/intake/inbox.js";
import type { InboxRow } from "../../src/intake/inbox.js";

const RECEIVED_AT = new Date("2026-11-07T10:00:00.000Z");
const ROW: InboxRow = {
  id: "3EB0A1",
  chatJid: "919876543210@s.whatsapp.net",
  senderJid: "919876543210@s.whatsapp.net",
  senderPn: "919876543210",
  text: "2 litres milk",
};

let folder: string;
let dbPath: string;
let logLines: string[];

beforeEach(() => {
  folder = mkdtempSync(path.join(tmpdir(), "chat2cart-inbox-"));
  dbPath = path.join(folder, "chat2cart.sqlite");
  createSchemaDatabase(dbPath, 1);
  logLines = [];
});

afterEach(() => {
  rmSync(folder, { recursive: true, force: true });
});

function deps(db: Database.Database): Parameters<typeof saveToInbox>[0] {
  const sink = new Writable({
    write(chunk: Buffer, _encoding, done): void {
      logLines.push(chunk.toString());
      done();
    },
  });
  return { db, logger: pino({ level: "info" }, sink), clock: () => RECEIVED_AT };
}

function storedRows(db: Database.Database): unknown[] {
  return db.prepare("SELECT id, sender_pn, text, received_at, status FROM inbound_messages").all();
}

it("stores_an_accepted_message_as_pending_with_its_whatsapp_id", () => {
  const db = new Database(dbPath);

  const isNew = saveToInbox(deps(db), ROW);

  expect(isNew).toBe(true);
  expect(storedRows(db)).toEqual([
    {
      id: ROW.id,
      sender_pn: ROW.senderPn,
      text: ROW.text,
      received_at: RECEIVED_AT.toISOString(),
      status: "pending",
    },
  ]);
  db.close();
});

it("keeps_one_row_and_logs_inbound_duplicate_when_the_same_id_arrives_twice", () => {
  const db = new Database(dbPath);
  saveToInbox(deps(db), ROW);

  const isNew = saveToInbox(deps(db), ROW);

  expect(isNew).toBe(false);
  expect(storedRows(db)).toHaveLength(1);
  const entry = JSON.parse(logLines.join("")) as Record<string, unknown>;
  expect(entry).toMatchObject({ msg: "inbound_duplicate", messageId: ROW.id });
  expect(JSON.stringify(entry)).not.toContain(ROW.text);
  db.close();
});

it("keeps_one_row_when_the_message_is_redelivered_after_a_listener_restart", () => {
  const first = new Database(dbPath);
  saveToInbox(deps(first), ROW);
  first.close();

  const restarted = new Database(dbPath);
  const isNew = saveToInbox(deps(restarted), ROW);

  expect(isNew).toBe(false);
  expect(storedRows(restarted)).toHaveLength(1);
  restarted.close();
});

it("builds_a_row_from_a_message_and_its_accepted_sender", () => {
  const message = { key: { id: ROW.id, remoteJid: ROW.chatJid } } as WAMessage;
  const sender = { accepted: true, senderPn: ROW.senderPn, senderJid: ROW.senderJid };

  expect(toInboxRow(message, ROW.text, sender)).toEqual(ROW);
});

it("builds_no_row_for_a_message_without_an_id", () => {
  const message = { key: { remoteJid: ROW.chatJid } } as WAMessage;
  const sender = { accepted: true, senderPn: ROW.senderPn, senderJid: ROW.senderJid };

  expect(toInboxRow(message, ROW.text, sender)).toBeUndefined();
});
