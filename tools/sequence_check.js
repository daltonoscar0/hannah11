// Runs a built experiment script against Ibex's shuffle.js and checks the
// trial order: usage  node sequence_check.js <shuffle.js> <experiment script>
const fs = require("fs");
const vm = require("vm");
const [shufflePath, scriptPath] = process.argv.slice(2);
const sandbox = {
  $: { map: (a, f) => Array.prototype.map.call(a, (x) => f(x)), isArray: Array.isArray },
  filter: (f, a) => a.filter(f),
  assert: (c, m) => { if (!c) throw new Error(m); },
  Math, Array, console,
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(shufflePath, "utf8"), sandbox);
// Stand-in for the farm's randomizeNoMoreThan module: plain shuffle.
vm.runInContext("function randomizeNoMoreThan(p, n) { return randomize(p); }", sandbox);
vm.runInContext(fs.readFileSync(scriptPath, "utf8") + "\nthis.items = items; this.seqObj = shuffleSequence;", sandbox);

// One condition per latin-square item, as Ibex would pick for a participant.
const seen = new Set();
const master = [];
for (const it of sandbox.items) {
  let type = it[0];
  if (Array.isArray(type)) {
    const group = type[1];
    const fam = type[0].replace(/_(ambig|unamb)/, "");
    const key = fam + ":" + group;
    if (seen.has(key)) continue;
    seen.add(key);
    type = type[0];
  }
  master.push({ type });
}
const order = vm.runInContext("runShuffleSequence", sandbox)(master, sandbox.seqObj).map((x) => x.type);
const isTrial = (t) => /ambig|unamb|filler/.test(t);
const trials = order.filter(isTrial);
const n = trials.length;
const b1 = order.indexOf("break1"), b2 = order.indexOf("break2");
const before = (i) => order.slice(0, i).filter(isTrial).length;
const firstTrain = trials.findIndex((t) => /training/.test(t));
const firstTest = trials.findIndex((t) => !/training/.test(t));
const ok =
  order.filter((t) => t === "break1").length === 1 &&
  order.filter((t) => t === "break2").length === 1 &&
  before(b1) === Math.round(n / 3) && before(b2) === Math.round((2 * n) / 3) &&
  order[b1 - 1] === "sep" && order[b1 + 1] === "sep" &&
  order[b2 - 1] === "sep" && order[b2 + 1] === "sep" &&
  order[order.length - 1] === "nf";
console.log(JSON.stringify({
  script: scriptPath.split("/").slice(-3, -2)[0], trials: n,
  trialsBeforeBreak1: before(b1), trialsBeforeBreak2: before(b2),
  firstBlock: firstTest < firstTrain ? "test" : "training",
  aroundBreak1: order.slice(b1 - 2, b1 + 3), ok,
}));
process.exit(ok ? 0 : 1);
