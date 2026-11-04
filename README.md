# Shoremark

Find the wild places that need you. Shoremark gathers beach cleanups, native plantings and habitat restoration days from trusted conservation groups around San Francisco Bay and puts them on one map, organized by habitat.

Shoremark is environmental-only. It grew out of Civic Snap, a general local-volunteering site by the same maker, and uses the same approach: read each group's own public calendar, link back to the group's sign-up page, and never take sign-ups ourselves.

## Sources today

Surfrider Foundation (SF Chapter), Pacific Beach Coalition, Save The Bay, Grassroots Ecology.

## How it works

- `events.json` holds the events. The pages read it in the browser.
- `scripts/update_events.py` rebuilds `events.json`. `.github/workflows/update-events.yml` runs it every Monday and can be run by hand from the Actions tab.
- The pages also ignore any group in `events.json` whose `cause` is not `environment`, as a second safety net.

## Spot a Need

People can report places that need help (photos, cause, description, location). Reports are reviewed by an admin, then appear on the Needs Board, where organizations can offer to host an event. Setup and moderation: `SPOT_A_NEED_SETUP.md`. Database and security rules: `supabase/schema.sql`.

## Status

Early project, Bay Area only. California, Oregon and Washington are planned.
