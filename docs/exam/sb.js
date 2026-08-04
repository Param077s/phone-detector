// Shared Supabase client for the Vigil Exams web app.
// The anon key is public by design (RLS enforces all access rules).
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import { readExam, bandCounts } from "/exam/exam-core.js";

export const SUPABASE_URL = "https://czvxhfbwpmqafpeehayd.supabase.co";
export const SUPABASE_ANON = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImN6dnhoZmJ3cG1xYWZwZWVoYXlkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODUxNjg2MTcsImV4cCI6MjEwMDc0NDYxN30.yCMKuG2rfCihhGJe6Jy7tTnitYPlls8qeK67NstmDGg";

export const sb = createClient(SUPABASE_URL, SUPABASE_ANON, {
  auth: { persistSession: true, autoRefreshToken: true },
});

// helpers -------------------------------------------------------------------
// Read one exam, asking for the columns a migration adds and coping when it
// hasn't been run yet. Postgres rejects the WHOLE select for one unknown column,
// so a page that simply listed `timezone` would go blank everywhere until the SQL
// was pasted in — and migrations here are applied by hand, deliberately.
export const OPTIONAL_EXAM_COLS = ["timezone"];   // v13
// What the live room needs to draw itself. Named because the console PREFETCHES
// this exact read when the pointer reaches a "Live room" link — a warmer that
// asked for a different set of columns would be a wasted request followed by
// the real one, and the two drifting apart is the kind of thing nothing tells
// you about until the room is slow again.
export const EXAM_COLS = "title,code,status,owner,created_at,closed_at,starts_at,ends_at,duration_min";
export async function fetchExam(id, cols) {
  const get = c => sb.from("exams").select(c).eq("id", id).maybeSingle();
  let r = await get([cols, ...OPTIONAL_EXAM_COLS].join(","));
  if (r.error) r = await get(cols);                // the migration isn't in yet
  return r.data || null;
}

// ── the risk shape of one exam, for a list ───────────────────────────────────
// The exam lists want the four numbers the report shows, and "the same numbers"
// has to mean it — so this reads the exam the way the report reads it, through
// readExam, rather than estimating from participants.status. A list that
// disagreed with the report it links to would be worse than a list with no
// numbers on it at all.
//
// It PAGES. PostgREST caps a select at its max-rows setting, and a silently
// truncated event list yields confident, wrong counts. Asking three times is
// cheap; being quietly wrong about who cheated is not.
// `build` must return a query with a TOTAL order — one no two rows can tie on.
// Paging is offset-based, so a tie is not a cosmetic detail: rows that sort
// arbitrarily can land on both sides of a page boundary, and the reader then
// sees one event twice and another not at all. Every caller here orders by
// `at` and then by the primary key, which no two rows share.
const PAGE = 1000;
export async function allRows(build) {
  const out = [];
  for (let from = 0; ; from += PAGE) {
    const { data, error } = await build().range(from, from + PAGE - 1);
    if (error) throw error;
    out.push(...(data || []));
    if (!data || data.length < PAGE) return out;
  }
}
// The {data, error} shape a single select returns, so a caller that already
// branches on `error` (to detect a migration that hasn't been run) keeps doing
// exactly that and only the fetching underneath it changes.
export async function selectAll(build) {
  try { return { data: await allRows(build), error: null }; }
  catch (error) { return { data: null, error }; }
}
export const orderedEvents = q => q.order("at", { ascending: true }).order("id", { ascending: true });
export async function fetchExamBands(exam) {
  const ev = cols => orderedEvents(sb.from("events").select(cols).eq("exam_id", exam.id));
  const events = await allRows(() => ev("id,participant_id,kind,severity,at,meta,review"))
    // pre-v6 has no `review` column, and Postgres rejects the whole select for it
    .catch(() => allRows(() => ev("id,participant_id,kind,severity,at,meta")));
  const parts = await allRows(() => sb.from("participants")
    .select("id,name,status,joined_at,last_seen").eq("exam_id", exam.id).order("id", { ascending: true }));
  const read = readExam(parts, events, { startsAt: exam.starts_at, endsAt: exam.ends_at });
  return { counts: bandCounts(read.students), total: read.students.length };
}

export async function currentUser() {
  const { data } = await sb.auth.getUser();
  return data.user || null;
}
export function isAnon(user) {
  return !!user && (user.is_anonymous === true || (!user.email && !user.phone));
}
export function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
