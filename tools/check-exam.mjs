#!/usr/bin/env node
// Vigil Exams — the check that `node --check` cannot do.
//
//   node tools/check-exam.mjs
//
// `node --check` only PARSES. It cannot see an undefined identifier, so a file
// that uses `examOver` without importing it parses perfectly and then throws in
// the browser the moment that line runs. That has already happened once: a
// string replacement missed the import line in two pages, leaving examOver,
// msLeft and examWindow used but never imported, and both files passed
// --check twice on the way in.
//
// So this does two things for every page that reads the shared core:
//
//   1. parses each `<script type="module">` body (the --check part), and
//   2. resolves every exam-core.js / sb.js name the page USES against the names
//      it actually IMPORTS.
//
// Only files that already import from exam-core.js are name-checked — a page
// that doesn't use the core can't have missed an import from it, and checking
// them would flag ordinary locals that happen to share a name (`t`, `clock`).
//
// A name is reported only when it is a core export, is not imported, and is not
// declared anywhere in the file. Shadowing is legal and stays silent.

import { readFileSync, readdirSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import vm from "node:vm";

// Parsing a module needs a flag Node won't take from inside the file, so ask for
// it once and hand the run back to ourselves. `node tools/check-exam.mjs` works.
if (!vm.SourceTextModule) {
  const r = spawnSync(process.execPath,
    ["--experimental-vm-modules", "--no-warnings", fileURLToPath(import.meta.url), ...process.argv.slice(2)],
    { stdio: "inherit" });
  process.exit(r.status ?? 1);
}

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const EXAM = join(ROOT, "docs", "exam");
const rel = f => relative(ROOT, f);

// ── a scanner that blanks out comments, strings and regex literals ───────────
// Everything downstream is regex over source, so anything quoted has to stop
// looking like code first — otherwise "examOver" inside an error message reads
// as a use, and `//` inside a URL swallows the rest of the line.
// A template literal is half text and half code, so this walks the source with an
// explicit mode rather than matching quote to quote: inside a template everything
// is blanked until a `${`, at which point we are back in code until its brace
// closes. `stack` remembers the brace depth each open template resumes at, so
// nesting a template inside its own substitution works.
function strip(src) {
  const out = src.split("");
  const blank = (a, b) => { for (let i = a; i < b && i < out.length; i++) if (out[i] !== "\n") out[i] = " "; };
  const stack = [];
  let i = 0, depth = 0, prev = "", inTmpl = false;
  while (i < src.length) {
    const c = src[i], d = src[i + 1];
    if (inTmpl) {
      if (c === "\\") { blank(i, i + 2); i += 2; continue; }
      if (c === "`") { blank(i, i + 1); stack.pop(); inTmpl = false; prev = "x"; i++; continue; }
      if (c === "$" && d === "{") { blank(i, i + 2); inTmpl = false; depth++; prev = "{"; i += 2; continue; }
      blank(i, i + 1); i++; continue;
    }
    if (c === "/" && d === "/") { let j = src.indexOf("\n", i); if (j < 0) j = src.length; blank(i, j); i = j; continue; }
    if (c === "/" && d === "*") { let j = src.indexOf("*/", i + 2); j = j < 0 ? src.length : j + 2; blank(i, j); i = j; continue; }
    if (c === '"' || c === "'") {
      let j = i + 1;
      while (j < src.length) {
        if (src[j] === "\\") { j += 2; continue; }
        if (src[j] === c || src[j] === "\n") break;
        j++;
      }
      blank(i, Math.min(j + 1, src.length)); i = j + 1; prev = "x"; continue;
    }
    if (c === "`") { blank(i, i + 1); stack.push(depth); inTmpl = true; i++; continue; }
    if (c === "{") { depth++; prev = "{"; i++; continue; }
    if (c === "}") {
      depth--; prev = "}"; i++;
      if (stack.length && depth === stack[stack.length - 1]) inTmpl = true;   // back into the template
      continue;
    }
    // a regex literal, but only where a value can start (so `a / b` survives)
    if (c === "/" && !/[\w$)\]]/.test(prev)) {
      let j = i + 1, cls = false, ok = false;
      while (j < src.length && src[j] !== "\n") {
        if (src[j] === "\\") { j += 2; continue; }
        if (src[j] === "[") cls = true;
        else if (src[j] === "]") cls = false;
        else if (src[j] === "/" && !cls) { ok = true; break; }
        j++;
      }
      if (ok) { blank(i, j + 1); i = j + 1; prev = "x"; continue; }
    }
    if (!/\s/.test(c)) prev = c;
    i++;
  }
  return out.join("");
}

// ── what a module offers, and what a file asks of it ─────────────────────────
function exportsOf(file) {
  const src = strip(readFileSync(file, "utf8"));
  const names = new Set();
  for (const m of src.matchAll(/^\s*export\s+(?:async\s+)?(?:function|const|let|var|class)\s+([A-Za-z_$][\w$]*)/gm)) names.add(m[1]);
  for (const m of src.matchAll(/^\s*export\s*\{([^}]*)\}/gm))
    for (const part of m[1].split(",")) {
      const n = part.trim().split(/\s+as\s+/).pop();
      if (n) names.add(n.trim());
    }
  return names;
}

// Every `import { … } from "<spec>"`, flattened to the local binding names.
// This one reads the RAW source: the specifier is a string literal, and stripped
// source has had its string contents blanked, so nothing would ever match.
function importsFrom(src, spec) {
  const names = new Set();
  const re = new RegExp('import\\s*\\{([^}]*)\\}\\s*from\\s*["\']' + spec + '["\']', "g");
  for (const m of src.matchAll(re))
    for (const part of m[1].split(",")) {
      const n = part.trim().split(/\s+as\s+/).pop();
      if (n) names.add(n.trim());
    }
  return names;
}

// Declarations, approximately but generously: anything that could bind a name
// counts, because a false "declared" only costs us a missed warning, while a
// false "undeclared" cries wolf on legal shadowing.
function declared(src) {
  const names = new Set();
  const add = s => { for (const m of s.matchAll(/[A-Za-z_$][\w$]*/g)) names.add(m[0]); };
  // `let cls = "ok", label = "…";` binds BOTH names, so a declaration is read to
  // its end and split at top-level commas. Only the part before each `=` is a
  // binding: taking the initialiser too would mark `const w = examWindow(e)` as
  // declaring examWindow, which is precisely the mistake this tool exists to catch.
  for (const m of src.matchAll(/\b(?:const|let|var)\s+/g)) {
    let i = m.index + m[0].length, depth = 0, out = "";
    while (i < src.length) {
      const c = src[i];
      if ("([{".includes(c)) depth++;
      else if (")]}".includes(c)) { if (depth === 0) break; depth--; }   // `for (const x of ys)`
      else if (c === ";" && depth === 0) break;
      out += c; i++;
    }
    let piece = "", d = 0;
    for (const c of out + ",") {
      if ("([{".includes(c)) d++;
      else if (")]}".includes(c)) d--;
      if (c === "," && d === 0) { add(piece.split("=")[0]); piece = ""; continue; }
      piece += c;
    }
  }
  for (const m of src.matchAll(/\b(?:function|class)\s*\*?\s*([A-Za-z_$][\w$]*)/g)) names.add(m[1]);
  for (const m of src.matchAll(/\bcatch\s*\(([^)]*)\)/g)) add(m[1]);
  // parameters: `function f(a, b)`, `(a, b) =>`, `a =>`
  for (const m of src.matchAll(/\bfunction\s*\*?\s*[A-Za-z_$][\w$]*?\s*\(([^)]*)\)/g)) add(m[1]);
  for (const m of src.matchAll(/\(([^()]*)\)\s*=>/g)) add(m[1]);
  for (const m of src.matchAll(/(^|[^\w$.])([A-Za-z_$][\w$]*)\s*=>/g)) names.add(m[2]);
  // object methods and shorthand: `foo(a) {`, `foo,` in a literal
  for (const m of src.matchAll(/([A-Za-z_$][\w$]*)\s*\(([^)]*)\)\s*\{/g)) add(m[2]);
  return names;
}

// Bare identifier uses — not `x.name`, not `{ name: … }`.
// The "not preceded by" test has to be a LOOKBEHIND: consuming the character
// before an identifier eats the separator the next identifier needs, so
// `await sb.from(…)` would find `await` and then never see `sb` at all.
function usedNames(src) {
  const names = new Set();
  // SPREAD IS NOT PROPERTY ACCESS. The lookbehind below rejects a name preceded
  // by a dot, which is right for `obj.name` and wrong for `[...NAME]` — the last
  // dot of the spread looks exactly like an accessor. That cost a real false
  // positive: console.html was reported as importing ALERT_KINDS and never using
  // it, while using it on the next screenful as `.in("kind", [...ALERT_KINDS])`.
  // A checker that cries wolf is a checker nobody runs, so the spread is removed
  // before scanning. Only names are collected here, so the shifted offsets that
  // costs us are not offsets anybody reads.
  src = src.replace(/\.\.\./g, " ");
  for (const m of src.matchAll(/(?<![\w$.])([A-Za-z_$][\w$]*)(:?)/g)) {
    if (m[2] === ":") continue;                     // an object key, not a use
    names.add(m[1]);
  }
  return names;
}

// ── the module bodies a file contributes ─────────────────────────────────────
function bodiesOf(file) {
  const src = readFileSync(file, "utf8");
  if (file.endsWith(".js")) return [{ file, body: src, line: 1 }];
  const out = [];
  for (const m of src.matchAll(/<script[^>]*type=["']module["'][^>]*>([\s\S]*?)<\/script>/g))
    out.push({ file, body: m[1], line: src.slice(0, m.index).split("\n").length });
  return out;
}

// ── run ──────────────────────────────────────────────────────────────────────
const CORE = { spec: "/exam/exam-core\\.js", names: exportsOf(join(EXAM, "exam-core.js")), what: "exam-core.js" };
const SBJS = { spec: "/exam/sb\\.js", names: exportsOf(join(EXAM, "sb.js")), what: "sb.js" };

const files = readdirSync(EXAM)
  .filter(f => f.endsWith(".html") || f.endsWith(".js"))
  .sort()
  .map(f => join(EXAM, f));

let problems = 0;
const say = (f, msg) => { problems++; console.error("  ✗ " + rel(f) + " — " + msg); };

for (const file of files) {
  for (const { body, line } of bodiesOf(file)) {
    // 1) does it parse? (this is the `node --check` half)
    try {
      new vm.SourceTextModule(body, { identifier: rel(file) });
    } catch (e) {
      say(file, "does not parse near line " + line + ": " + e.message);
      continue;
    }
    // 2) does every core name it uses come from somewhere?
    // The import list itself mentions every name it binds, so it has to go before
    // "is this name used?" means anything at all.
    const clean = strip(body).replace(/\bimport\s*\{[^}]*\}\s*from\s*[^\n;]*/g, "");
    const local = declared(clean), used = usedNames(clean);
    // Satisfied by ANY import, not per-module: `esc` is exported by both files,
    // and a page that took it from one is not missing it from the other.
    const have = new Set([...importsFrom(body, CORE.spec), ...importsFrom(body, SBJS.spec)]);
    for (const mod of [CORE, SBJS]) {
      const imported = importsFrom(body, mod.spec);
      if (!imported.size) continue;                      // this file doesn't read that module
      const missing = [...mod.names]
        .filter(n => used.has(n) && !have.has(n) && !local.has(n))
        .sort();
      if (missing.length)
        say(file, "uses " + missing.join(", ") + " from " + mod.what + " without importing " +
          (missing.length === 1 ? "it" : "them"));
      // The other half of the same invariant. A name left in the import list after
      // its last use is how you end up believing a page still reads the shared core
      // when it has quietly stopped.
      const dead = [...imported].filter(n => !used.has(n)).sort();
      if (dead.length)
        say(file, "imports " + dead.join(", ") + " from " + mod.what + " and never uses " +
          (dead.length === 1 ? "it" : "them"));
    }
  }
}

if (problems) {
  console.error("\n" + problems + (problems === 1 ? " problem" : " problems") + " found.");
  process.exit(1);
}
console.log("✓ " + files.length + " files parse, and every exam-core/sb name they use is imported.");
