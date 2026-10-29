import assert from "node:assert/strict";
import { test } from "node:test";

import { ago, errorText, initials, inWords, place, project, ruleText, short, titled } from "./format.js";

test("ids and names read as people would write them", () => {
  assert.equal(short("employee_E037"), "E037");
  assert.equal(titled("security_officer"), "Security Officer");
  assert.equal(titled("hr_partner"), "HR Partner");
  assert.equal(project("engineering1"), "Engineering 1");
  assert.equal(initials("Mia Chen"), "MC");
  assert.equal(place("paris", "emea"), "Paris (EMEA)");
  assert.equal(place("", "emea"), "");
});

test("ago counts minutes and hours", () => {
  const now = Date.parse("2026-10-29T12:00:00Z");
  assert.equal(ago("2026-10-29T11:59:30Z", now), "just now");
  assert.equal(ago("2026-10-29T11:45:00Z", now), "15 min ago");
  assert.equal(ago("2026-10-29T09:00:00Z", now), "3 h ago");
  assert.equal(ago(null, now), "");
});

test("a pattern reads as a sentence", () => {
  const predicates = [
    { kind: "shared", relation: "works_in", other: "owned_by" },
    { kind: "user_has", relation: "holds", other: "role_auditor" },
  ];
  assert.equal(inWords(predicates), "Applies when the document belongs to their department, and they are an auditor.");
  assert.equal(inWords([]), "");
});

test("a rule uses Corax's description first", () => {
  const request = { candidates: [{ pattern: "p", description: "A manager may read.", predicates: [] }] };
  assert.equal(ruleText(request, "p"), "A manager may read.");
  assert.equal(ruleText(request, "other"), "A rule for people in the same situation.");
});

test("errors show the status and the detail", () => {
  assert.equal(errorText({ status: 409, data: { detail: "already decided" } }), "409: already decided");
  assert.equal(errorText({ status: 502, data: { detail: { message: "validation failed" } } }), "502: validation failed");
  assert.equal(errorText({ status: 500, data: null }), "The request failed (500).");
});
