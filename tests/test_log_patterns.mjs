import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const libPath = new URL("../src/spyglass/static/dashboard/js/dashboard-lib.js", import.meta.url);
const sandbox = { console, document: { getElementById: () => null }, Chart: undefined, globalThis: {} };
vm.createContext(sandbox);
vm.runInContext(
  readFileSync(libPath, "utf8") + "\nglobalThis._tokenizeMessage = _tokenizeMessage;",
  sandbox,
  { timeout: 1000 },
);
const tokenize = sandbox._tokenizeMessage;

test("sensor readings collapse across power values", () => {
  const a = tokenize(
    "[on_message] __main__ [mqtt] received SENSOR: meter_id=0649534b010bcb2986eb power=48W E_in=1234.5 E_out=0.0",
  );
  const b = tokenize(
    "[on_message] __main__ [mqtt] received SENSOR: meter_id=0649534b010bcb2986eb power=134W E_in=999 E_out=1.2",
  );
  const expected = "[on_message] __main__ [mqtt] received SENSOR: meter_id=* power=* E_in=* E_out=*";
  assert.equal(a, expected);
  assert.equal(b, expected);
});

test("db paths collapse timestamps and queue wait", () => {
  assert.equal(
    tokenize(
      "[db_worker] __main__ Saving energy reading to DB (queue wait 12ms): meter_id=0649534b010bcb2986eb power=49W E_in=1 E_out=0",
    ),
    "[db_worker] __main__ Saving energy reading to DB (queue wait *): meter_id=* power=* E_in=* E_out=*",
  );
  assert.equal(
    tokenize(
      "[save_energy_reading] src.database Saved energy reading: meter_id=0649534b010bcb2986eb power=40W E_in=2 E_out=None timestamp=2025-07-07T07:12:34+00:00",
    ),
    "[save_energy_reading] src.database Saved energy reading: meter_id=* power=* E_in=* E_out=* timestamp=*",
  );
});

test("tasmota STATE payloads collapse", () => {
  const a = tokenize("[on_message] __main__ [msg] tele/tasmota/STATE: {'Time': '2025-07-07T08:00:00', 'Signal': -55}");
  const b = tokenize("[on_message] __main__ [msg] tele/tasmota/STATE: {'Time': '2025-07-07T09:00:00', 'Uptime': 99999}");
  assert.equal(a, "[on_message] __main__ [msg] tele/tasmota/STATE: *");
  assert.equal(b, a);
});
