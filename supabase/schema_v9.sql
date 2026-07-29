-- ============================================================================
--  Vigil Exams — migration v9 (run AFTER v8, in the Supabase SQL editor)
--
--  Three-state review. The findings document asks the teacher for a verdict on
--  each moment, and "not sure yet, let's talk to them" is a real answer that
--  Confirm/Dismiss could not express:
--
--      confirmed → Upheld       dismissed → Set aside       discuss → To discuss
--
--  Nothing else changes: 'discuss' scores exactly like an unreviewed flag, and
--  only 'dismissed' still drops a flag out of the score.
--
--  Safe to run anytime, safe to re-run. Existing rows keep their values — the
--  new constraint is a superset of the old one, so nothing can fail validation.
--  Until this is applied the app simply reports that "To discuss" isn't
--  available; Upheld and Set aside keep working as they have since v6.
-- ============================================================================

alter table public.events drop constraint if exists events_review_check;

alter table public.events add constraint events_review_check
  check (review in ('confirmed', 'dismissed', 'discuss'));
