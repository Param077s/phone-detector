// Shared Supabase client for the Vigil Exams web app.
// The anon key is public by design (RLS enforces all access rules).
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

export const SUPABASE_URL = "https://czvxhfbwpmqafpeehayd.supabase.co";
export const SUPABASE_ANON = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImN6dnhoZmJ3cG1xYWZwZWVoYXlkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODUxNjg2MTcsImV4cCI6MjEwMDc0NDYxN30.yCMKuG2rfCihhGJe6Jy7tTnitYPlls8qeK67NstmDGg";

export const sb = createClient(SUPABASE_URL, SUPABASE_ANON, {
  auth: { persistSession: true, autoRefreshToken: true },
});

// helpers -------------------------------------------------------------------
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
