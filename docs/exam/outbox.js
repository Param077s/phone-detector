/* ============================================================================
   Vigil Exams — the outbox
   ============================================================================

   A teacher types a note about a student, presses Enter, and immediately clicks
   back to the console. Before this file, that note's fate depended on how fast
   the network was: the request was fired from a closure that owned a DOM node
   which was about to stop existing, and if it failed there was nobody left to
   tell, nobody left to retry, and no sign anything had gone missing.

   So the writes stop belonging to the page. They are handed here, the UI moves
   on in the same frame, and this keeps trying until the server accepts them. A
   navigation cannot lose a write, because the queue outlives every page in the
   tab — it is module state, and the tab only has one module registry.

   WHAT IS RETRIED, AND WHAT IS NOT

   Only failures that could plausibly succeed on a second attempt: a dropped
   connection, a timeout, a 5xx. A rejected write — bad permissions, a column
   that needs a migration, a constraint — is returned to the caller immediately,
   because retrying it four times just delays telling somebody the truth.

   ORDERING

   Writes with the same key run one at a time, in the order they were queued.
   Two edits to the same note a second apart must not race, or the older text
   can land last and win. Writes with different keys run concurrently — there is
   no reason a note about one student should wait behind a note about another.

   THE LAST RESORT

   If the tab is closed with work still unsent, the browser is asked to confirm.
   That prompt is the only thing standing between a slow network and a note
   somebody believes they wrote, so it appears when — and only when — something
   really is still in the queue.
   ========================================================================= */

const RETRY_MS = [400, 1500, 5000, 15000];

/* A failure worth trying again. Everything supabase-js surfaces from a fetch
   that never reached Postgres looks like one of these; a real answer from
   PostgREST carries a `code`, and that is the server having an opinion rather
   than the connection having a problem. */
function transient(err) {
  if (!err) return false;
  if (err.code && !/^(08|53|57|XX)/.test(err.code)) return false;   // PostgREST/PG said no
  const s = (err.status || 0);
  if (s && s < 500 && s !== 408 && s !== 429) return false;
  return true;
}

const lanes = new Map();     // key -> promise chain, so same-key writes queue
let pending = 0;
const watchers = new Set();

/** Called with the number of writes still in flight, whenever it changes. */
export function onPending(fn) { watchers.add(fn); return () => watchers.delete(fn); }
function bump(d) { pending += d; for (const w of watchers) { try { w(pending); } catch (_) {} } }

export const pendingCount = () => pending;

/**
 * Queue a write. Returns a promise that settles when the write is accepted or
 * has definitively failed — but nothing is expected to await it, and the point
 * is that the UI does not.
 *
 * @param key   writes sharing a key run in order, one at a time
 * @param run   () => Promise<{error} | any>  — a supabase call, usually
 * @returns     Promise<{ok:true} | {ok:false, error}>
 */
export function send(key, run) {
  bump(1);
  const prev = lanes.get(key) || Promise.resolve();
  const mine = prev.then(() => attempt(run)).then(
    (r) => { bump(-1); if (lanes.get(key) === mine) lanes.delete(key); return r; },
    (e) => { bump(-1); if (lanes.get(key) === mine) lanes.delete(key); return { ok: false, error: e }; },
  );
  lanes.set(key, mine);
  return mine;
}

async function attempt(run, tries = 0) {
  let error = null;
  try {
    const r = await run();
    error = r && r.error ? r.error : null;
  } catch (e) {
    error = e;
  }
  if (!error) return { ok: true };
  if (!transient(error) || tries >= RETRY_MS.length) return { ok: false, error };
  await new Promise(r => setTimeout(r, RETRY_MS[tries]));
  return attempt(run, tries + 1);
}

/* The tab is going away and we still owe the server something. This is the one
   case where interrupting somebody is the kind thing to do. */
addEventListener("beforeunload", (e) => {
  if (!pending) return;
  e.preventDefault();
  e.returnValue = "";
});
