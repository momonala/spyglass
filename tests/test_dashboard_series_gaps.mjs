import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const libPath = new URL("../src/spyglass/static/dashboard/js/dashboard-lib.js", import.meta.url);
const sandbox = { console, document: { getElementById: () => null }, Chart: undefined, globalThis: {} };
vm.createContext(sandbox);
vm.runInContext(
  readFileSync(libPath, "utf8") +
    "\nglobalThis._mapPointsToBuckets = _mapPointsToBuckets;" +
    "\nglobalThis._shouldZeroFillMissing = _shouldZeroFillMissing;",
  sandbox,
  { timeout: 1000 },
);

const { _mapPointsToBuckets, _shouldZeroFillMissing } = sandbox;

test("counter and set metrics zero-fill by default", () => {
  assert.equal(_shouldZeroFillMissing("counter", undefined), true);
  assert.equal(_shouldZeroFillMissing("set", undefined), true);
  assert.equal(_shouldZeroFillMissing("timing", undefined), false);
  assert.equal(_shouldZeroFillMissing("gauge", undefined), false);
});

test("zeroFill override wins over metric type", () => {
  assert.equal(_shouldZeroFillMissing("timing", true), true);
  assert.equal(_shouldZeroFillMissing("counter", false), false);
});

test("empty counter buckets become zero instead of null gaps", () => {
  const sortedTs = [
    "2026-07-18T10:00:00.000Z",
    "2026-07-18T10:01:00.000Z",
    "2026-07-18T10:02:00.000Z",
  ];
  const points = [
    { timestamp: "2026-07-18T10:00:00.000Z", value: 5 },
    { timestamp: "2026-07-18T10:02:00.000Z", value: 3 },
  ];
  const bucketMs = 60_000;

  assert.deepEqual(_mapPointsToBuckets(points, sortedTs, bucketMs, null), [5, null, 3]);
  assert.deepEqual(_mapPointsToBuckets(points, sortedTs, bucketMs, 0), [5, 0, 3]);
});
