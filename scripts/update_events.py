#!/usr/bin/env python3
"""
Weekly volunteer-event updater for the Bay Area environmental volunteering map.

What this does, at a high level:
  1. For each source organization, fetch its calendar/event page(s) over plain HTTP
     (no headless browser needed -- see notes per-org below).
  2. Hand the raw text/HTML to Claude with a forced-JSON tool call to pull out
     structured events (name, date, day, start/end time, location, and a
     registration link when one is actually present in the source text).
  3. Geocode any event location that doesn't already have coordinates, using the
     free OpenStreetMap Nominatim API (rate-limited to 1 request/sec per their
     usage policy).
  4. Filter to events between today and LOOKAHEAD_DAYS from now, merge everything
     into events.json in the schema the map already expects, and write the file.

Design notes / honesty about limitations:
  - This was written by Claude based on manually inspecting each org's site once
    (Sept 2026). Run #1 surfaced real bugs (see CHANGELOG at the bottom of this
    docstring) which are now fixed as best as they could be verified from a
    sandbox with no direct network access to these sites -- Claude validated the
    underlying fixes using a separate interactive browser tool, but could not run
    THIS script live end-to-end. Treat every manual "Run workflow" as a real test,
    not a formality: read the log, read the diff.
  - Several of these sites render their calendar/event links via client-side
    JavaScript, so a plain HTTP GET sometimes returns HTML that doesn't yet
    contain the data (no headless browser executes the page's JS). Each such
    fetch has a Playwright-rendered fallback that only kicks in when the cheap
    plain-HTTP path finds nothing -- see render_with_playwright().
  - If an org redesigns their page, extraction for that org may silently return
    fewer/no events. Each org is wrapped in its own try/except so one broken
    source doesn't take down the whole run -- check the logs periodically.
  - Never invents registration links: if nothing event-specific is found, the
    event is written without a bookingUrl (falls back to the org's orgUrl, if any).
    Every bookingUrl is also verified with a real HTTP request before being kept
    (see verify_url()) -- a link that 404s/times out is dropped, not published.

CHANGELOG:
  2026-10-24  Second Harvest is now read directly too ("mmvfs_feed", next 3 weeks,
              Sort Food and Distribute Food shifts with open slots): the site's
              calendar loads one JSON feed with times, slots, addresses and exact
              coordinates, and each shift links to its own page. Events that
              already carry coordinates skip the geocoder.
  2026-10-23  Three organizations are now read directly, with no AI calls (so
              they cost nothing to run): SF-Marin Food Bank ("galaxy_calendar",
              next 3 weeks), St. Anthony's ("v4s_listing") and Project Open Hand
              ("openhand_hotspots"). They skip shifts with 0 open slots, link each
              shift to its own page where the site has one, and set their own tags.
              Added a hard cap on Claude calls per run (MAX_CLAUDE_CALLS, default
              150) and a usage/cost line at the end of every run, ONLY_ORGS and
              DRY_RUN switches for testing one org without touching the others,
              a per-run cache for link checks, and "keep the previous events if
              reading an org fails" for every org kind. Dropped Baykeeper, HandsOn
              Bay Area and City of San Mateo; FOPAL and Second Harvest read new
              pages. Parsers were checked against copies of the live pages, not
              yet run from the GitHub runner.
  2026-10-21  Added organizations for other causes (disaster preparedness, youth,
              civic, arts, seniors, food, and a multi-cause aggregator). New org
              kinds: "text_page" (read a page's text, for pages with no per-event
              links) and "weekly_recurring" (a fixed weekly event written as a
              rule). Orgs now carry a "cause"; the Claude tagging step only uses
              the level/setting/goodfor tags for non-environmental causes.
              html_listing's no-link fallback now sends page TEXT instead of the
              first 20,000 characters of raw HTML, and "max_details" raises the
              15-page cap for aggregators. NOT yet run against the live sites.
  2026-09-09  Initial version.
  2026-09-16  After run #1 came back with Pacific Beach Coalition and Grassroots
              Ecology both finding 0 events, and Save The Bay's 2 events failing
              to geocode:
                - Added a Playwright-rendered fallback for both the Google
                  Calendar embed lookup and the HTML-listing detail-link scan,
                  used only when the plain-HTTP pass finds nothing. (Confirmed
                  via an interactive browser session that Pacific Beach
                  Coalition's calendar iframe -- and presumably Grassroots
                  Ecology's event links -- exist in the rendered DOM; a plain
                  fetch alone wasn't enough for at least one of these two.)
                - Added LOCATION_OVERRIDES for known recurring sites plus a
                  looser retry query, to fix Nominatim geocoding failures on
                  full venue names like "MLK Regional Shoreline, Oakland".
                - Added verify_url() to check every extracted bookingUrl
                  actually resolves (< 400 status after redirects) before it's
                  written to events.json.
  2026-09-10  The Playwright fallback landed but Pacific Beach Coalition was
              STILL coming back with 0 events. Root-caused for real this time
              via an interactive browser session against the live pages:
                - extract_google_calendar_id()'s regex required `src=` to be
                  the literal first query parameter right after
                  `calendar/embed?`. Pacific Beach Coalition's embed code puts
                  it 8th (after height/wkst/bgcolor/ctz/showCalendars/
                  showTitle/showNav), so the id was never found, on either the
                  plain fetch OR the Playwright-rendered fetch -- this was
                  never actually a JS-rendering problem for this org. Rewrote
                  it to parse the full query string with urllib.parse so
                  parameter order doesn't matter.
                - Separately, even with the id correctly extracted, Pacific
                  Beach Coalition's calendar has public *embedding* enabled
                  but not the public *iCal export* -- its
                  /public/basic.ics URL 404s even though the embed itself
                  shows real events (confirmed by loading both directly).
                  Added render_google_calendar_agenda() as a fallback: when
                  the ICS fetch fails, render the same public calendar's own
                  agenda-mode view (?mode=AGENDA) with Playwright and hand its
                  plain-text event listing to Claude instead. Confirmed this
                  view lists every upcoming Pacific Beach Coalition event out
                  past our 56-day lookahead window.
                - Grassroots Ecology is still returning 0 events and was NOT
                  resolved this round -- its listing page renders as plain
                  server HTML with matching detail links when spot-checked,
                  so the cause isn't obvious yet. Added explicit logging of
                  the fetched HTML size and the number of detail links found
                  in process_html_listing_org() so the next real run's logs
                  pin down whether the regex is finding 0 detail URLs, or
                  finding them but Claude still isn't extracting events from
                  the combined text.
  2026-09-10b The above logging paid off immediately -- run #3's log showed
              exactly what was still wrong for both orgs:
                - Grassroots Ecology: the plain fetch pulled down 488KB of
                  real HTML and STILL matched 0 detail links, on both the
                  plain and Playwright-rendered fetch (489KB, same 0). Not a
                  JS problem after all -- confirmed via the live page's actual
                  href attributes that this site's event links are relative
                  paths ("/event-calendar/2026/09/09/..."), never prefixed
                  with the domain, so a pattern anchored to
                  "https://www.grassrootsecology.org/..." could never match.
                  Changed the pattern to match the relative form and added
                  _find_detail_urls(), which resolves whatever the pattern
                  finds against the listing page's own URL (urljoin) -- a
                  no-op for an org with absolute links like Save The Bay, but
                  required for one with relative links like this.
                - Pacific Beach Coalition: the iCal-unavailable fallback DID
                  trigger correctly and rendered the agenda view, but Claude
                  extracted 0 events from whatever text came back -- with no
                  visibility into what that text actually was. Added logging
                  of the rendered text's length and first 200 characters, plus
                  a defensive click-past-the-consent-dialog step (a completely
                  fresh, cookie-less Playwright browser -- which is what every
                  CI run is -- can get served Google's "Before you continue"
                  interstitial instead of the calendar itself; this wasn't
                  reproducible by hand since an already-logged-in interactive
                  browser doesn't see it). Next run's log will show directly
                  whether this was the cause.
  2026-09-10c The site owner asked for thoroughness over speed after round 2 still came
              back with both orgs empty. Run #4's actual log (now readable
              thanks to the logging added in round 2) explained both:
                - Pacific Beach Coalition: the agenda view DID render real
                  content (confirmed: no consent wall, correct page) but only
                  5390 characters of it -- the header plus one event -- because
                  a fixed 2-second pause after "networkidle" wasn't enough for
                  Google Calendar's agenda list to finish populating via its
                  own follow-up JS/XHR calls. Replaced the fixed pause with
                  polling page.inner_text("body") until its length stops
                  growing (checked every second, up to ~20s), and switched to
                  a normal desktop Chrome user-agent + viewport for this
                  specific fetch (the generic bot UA is fine for plain HTML
                  fetches elsewhere, but there's no reason to risk Google's JS
                  treating an unrecognized UA differently for its own app).
                - Grassroots Ecology: the link-matching fix from round 2
                  worked (15 matches, 15 detail pages fetched, Claude
                  extracted 7 real events) -- but all 7 were silently dropped
                  by main()'s date-range filter with no log line, because that
                  check was a bare `continue` with no logging. Root cause:
                  sorted(set(urls))[:15] sorts URLs alphabetically, which for
                  this org's date-stamped URLs is also chronological, and the
                  listing page mixes past and future events together -- so the
                  "first 15" were mostly already-past events, not the next 15
                  upcoming ones. Fixed _find_detail_urls() to parse the date
                  embedded in each URL, drop anything already in the past, and
                  sort what's left soonest-first before capping to 15. Also
                  made the date-range skip in main() always log the event name
                  and why it was dropped, so this class of "everything silently
                  vanished" never has to be re-diagnosed blind again.
  2026-09-11  Run #6 (the first run with all of the above fixes applied)
              crashed the whole script: `Claude extracted 1071 raw event(s)`
              for Grassroots Ecology, then a TypeError ("string indices must
              be integers") once the cleaning loop hit one of them, because
              those 1071 "events" were plain strings, not the objects
              record_events' schema requires -- and that loop only caught
              ValueError/KeyError, not TypeError, so it went unhandled and
              killed main() before events.json was ever written. That threw
              away Surfrider's and Save The Bay's perfectly good results for
              the run too, not just Grassroots Ecology's bad ones -- a single
              malformed record from one org shouldn't be able to do that.
              Added two layers of defense: claude_extract_events() now drops
              any non-object entries right at the source (logging how many),
              and the cleaning loop in main() now skips a non-dict event
              outright and wraps the rest of the per-event work in a broad
              try/except, so nothing short of the whole process dying can
              stop events.json from being written with whatever good data was
              actually collected.
  2026-09-11b The site owner re-ran before this fix had actually been pasted in, so run
              #7 hit the identical crash again on the identical line -- but
              its log was still useful: with the earlier UA/stabilize fix,
              Pacific Beach Coalition's agenda view now genuinely works
              (30 raw events extracted, 13 kept), which resolves the "PBC
              extracts nothing" thread from before. What's left is a
              geocoding gap: 8 of those PBC events failed to geocode, and
              looking at the failing addresses, several are subtly corrupted
              by the extraction step -- e.g. "Pacifica State Beach, 1416 9th
              St, California 95814, United States" carries a Sacramento zip
              code that has nothing to do with Pacifica. The single "last 2
              comma-separated segments" fallback couldn't recover from that
              (it produced "California 95814, United States", dropping the
              city entirely). Verified live against Nominatim's real API
              (not simulated) that every one of these failing addresses'
              *venue name alone* -- "Sharp Park Beach, CA", "Pacifica State
              Beach, CA", "Montara Beach, CA", "Thornton State Beach, CA" --
              resolves correctly to the real place, since named parks/beaches
              are already in OpenStreetMap under their own name regardless of
              what's wrong with the rest of the address. Rewrote geocode()
              around a general, ordered list of fallback query shapes (full
              address -> venue name alone -> last 3 segments -> last 2
              segments) instead of a single hardcoded loosening, verified the
              exact addresses from run #7's log now resolve to their real,
              live-checked coordinates, and re-ran a full mocked dry run of
              main() end to end (every known bad-data shape from every past
              run, all at once) confirming nothing crashes and every
              previously-working path (LOCATION_OVERRIDES, already-good
              addresses) is unaffected.
  2026-09-17  The site owner reported three things after a week of runs (#8 manual,
              #9 scheduled) had gone by since the last fix: Pacific Beach
              Coalition empty again, "dates aren't right on a lot of the
              links", and a Save The Bay Hayward event dated Oct 3rd linking
              to the same page as the MLK Coastal Cleanup event. Read run
              #9's actual log (not a guess) to root-cause each:
                - Pacific Beach Coalition: the agenda-view render is now
                  failing with "Page.goto: Timeout 45000ms exceeded" while
                  waiting for "networkidle" -- it worked in run #7 (30 raw
                  events) with the exact same code, so this isn't broken
                  logic, it's an unreliable wait condition: Google
                  Calendar's agenda view apparently keeps some background
                  connection open, so "no network activity for 500ms" can
                  simply never happen even once the page has fully loaded.
                  Switched render_google_calendar_agenda()'s page.goto() to
                  wait_until="domcontentloaded" instead (the existing
                  poll-until-the-text-stops-growing loop right after it
                  already handles waiting for the JS-rendered list itself,
                  so it doesn't depend on networkidle at all), bumped the
                  timeout to 60s for margin, and added one retry with a
                  fresh page before giving up.
                - "Dates aren't right" / the Save The Bay Oct 3rd + duplicate
                  link report: does NOT match what's actually in the live
                  events.json (2 Save The Bay events, both 9/19, two
                  different bookingUrls) or what run #9's log shows it wrote.
                  index.html's fetch('events.json') had no cache-busting at
                  all, so a browser (or the GitHub Pages CDN) serving a
                  stale copy is the far more likely explanation than a data
                  bug -- added a timestamp query param and cache: 'no-store'
                  so a visitor always gets the current file.
                - Also found, independently, while reading run #9's log: a
                  genuinely wrong pin. "1400 Broadway St, Redwood City, CA
                  94063" (a real Grassroots Ecology event) geocoded to
                  (34.0228, -118.4839) -- Los Angeles, not Redwood City. The
                  log showed why: the full address returns zero Nominatim
                  results (live-verified, even with ", USA" appended), so it
                  fell through to the "venue name only" fallback, which for
                  THIS address is just the bare street number+name with no
                  city ("1400 Broadway St, CA, USA") -- and that resolves,
                  successfully but wrongly, to a different Broadway St in
                  Santa Monica. A wrong-but-successful geocode is worse than
                  a failed one, since nothing downstream flags it. Live
                  Nominatim checks confirmed "Redwood City, CA 94063, USA"
                  (the last-2-segments fallback) resolves correctly.
                  Reordered _build_geocode_attempts() so the
                  city-preserving fallbacks (last 3 / last 2 segments) are
                  tried before "venue name only", and skip "venue name only"
                  entirely whenever the first comma-segment starts with a
                  digit -- a real venue name never does, and a bare street
                  number+name is too ambiguous to geocode without its city.
                  Re-verified this doesn't regress the run #7 PBC addresses
                  (their venue names don't start with digits, so they still
                  get tried, just after the now-earlier fallbacks that would
                  fail for them anyway) and re-ran a full mocked dry run of
                  main() end to end before shipping.
  2026-09-18  The site owner re-ran with the above fixes applied and reported three
              more things: Grassroots Ecology events still have no
              "I will help!" link at all (they pointed at
              grassrootsecology.org/calendar -> click a date -> click an
              event -> lands on a page like .../event-calendar/2026/09/19/
              coastal-cleanup-day-redwood-city, and asked for exactly that);
              the Save The Bay Hayward event's date/link still looked wrong;
              and some Sept 19 events seemed to be missing from the map
              entirely.
                - Checked the live map data directly: as of this run, all 5
                  of Grassroots Ecology's actual Sept 19 events (and both
                  Sept 20 ones) ARE present and correctly geocoded -- the
                  "missing events" report was almost certainly from an
                  earlier state (before this run, or before a browser
                  refresh); nothing further to fix there.
                - Root-caused the missing Grassroots Ecology bookingUrls:
                  process_html_listing_org() fetched each event's own detail
                  page but blended ALL of them into one combined block of
                  text and asked Claude to extract every event AND match
                  each one back to the right source URL in a single call.
                  That inference apparently works for Save The Bay but
                  wasn't landing for Grassroots Ecology. Rewrote it to call
                  Claude once PER detail page instead (confirmed live: each
                  event has its own page, e.g. exactly the Redwood City URL
                  the site owner linked, with its own "Register Here" button), then
                  set that event's bookingUrl to the page's own URL
                  programmatically afterward -- not inferred by the model at
                  all, so it can't be wrong. This is also just what the site owner
                  described wanting: the button now goes to that same
                  "volunteer tab" they click through to by hand. Applies to
                  both html_listing orgs (Save The Bay too), so both are now
                  equally reliable instead of one working by luck.
                - Investigated the Hayward date claim directly: the map's
                  data (from a run several days earlier) says Sept 19; the
                  live savesfbay.org page for that same event now says
                  October 3. Checked the OTHER Save The Bay event (MLK
                  Regional Shoreline) as a control -- it still correctly
                  says Sept 19, unchanged -- so this isn't a systemic
                  scraping bug or a caching issue, it's that Save The Bay
                  itself changed/rescheduled specifically the Hayward
                  event's date sometime after our last scrape ran. Nothing
                  in our pipeline was wrong at the time it ran; the fix is
                  just to re-run and pick up their current listing (which
                  this changelog's other fixes make worth doing anyway).
                  The "brings me to the same page as the coastal MLK one"
                  part: both event pages legitimately list each other as
                  related events in their own footer ("Invasive Plant Pull
                  at Ravenswood...", "Habitat Restoration at Eden Landing...")
                  -- that's savesfbay.org's own related-events nav, not a
                  bug in our bookingUrl.
                - Re-ran a full mocked dry run of main() end to end
                  (including the new per-detail-page extraction path) before
                  sending, confirming bookingUrl is set correctly per event
                  and nothing crashes.
  2026-09-18b The site owner clarified the "missing Sept 19 events" from earlier the
              same day were about Pacific Beach Coalition specifically, not
              Grassroots Ecology -- and indeed, run #10 (the first real run
              with the domcontentloaded fix from earlier today) still came
              back with 0 PBC events. Read that run's actual log: this time
              there was no timeout at all -- "agenda view rendered 4841
              chars of text after waiting for it to stabilize", the exact
              same char count as run #7's log, which is confirmed (from
              that same run's own log) to have extracted 30 real events from
              what was the same real calendar content. Live-reloaded the
              actual PBC agenda URL directly in a browser just now and
              confirmed it currently renders ~4900 chars of real event text
              (Calera Creek, Esplanade, Foster City, Montara Beach, Mussel
              Rock, ...), not an empty/header-only page. So the page was
              almost certainly rendered correctly both times, and Claude's
              own extraction call came back with 0 events on this one run
              for no code-level reason -- nothing in claude_extract_events()
              or its caller changed between run #7 and run #10. Rather than
              chase a single non-reproducible bad response further, added a
              pragmatic safety net: claude_extract_events() now retries once
              (a fresh, independent API call) whenever the FIRST attempt
              returns 0 events from a substantial amount of source text
              (>=800 chars -- short/empty pages still correctly return 0
              without wasting a retry), and logs 500 chars of the source
              text (not just 200) whenever that happens, so if this ever
              turns out to be a *repeatable* content/prompt problem rather
              than a one-off miss, the next log has enough in it to diagnose
              without this much run-archaeology. Verified with dedicated
              unit tests (recovers on a one-off miss, doesn't retry for
              short text, retries exactly once and gives up on a persistent
              failure) plus a full mocked dry run of main() end to end.
  2026-09-18c The 09-18b retry fix shipped, but run #11 showed Pacific Beach
              Coalition STILL returning 0 events -- and this time the log
              (with the new 500-char preview) proved the retry ALSO failed
              on the exact same real content: a real time, "Calera Creek
              Habitat Restoration", and a real maps.app.goo.gl link were all
              plainly present in the source text handed to Claude on both
              calls. That ruled out "one-off stochastic miss" for good.
              Pacific Beach Coalition turned out to be the ONLY org
              configured with has_site_form_table -- which appended up to
              60,000 characters of the calendar page's raw, unrendered HTML
              (mostly nav/footer/script boilerplate) as extra_context, so
              Claude could try to match each event to its own sign-up form
              link straight from the whole page. That was the one
              structural difference between this org and every other org in
              the same run, all of which extracted correctly. Removed the
              feature entirely (the agenda text alone already carries a
              per-event link when the source page has one). Verified with a
              unit test confirming extra_context is now always empty for
              this org, plus a full mocked dry run. Checked GitHub Actions
              directly afterward: run #12 (with this fix) succeeded with 25
              real, correctly-geocoded Pacific Beach Coalition events, live
              on the map (screenshot-verified).
  2026-09-18d The site owner asked for Pacific Beach Coalition's per-site direct
              Google Form links specifically, since that's what makes this
              org's data special. Re-added the site->form matching, but
              entirely in code this time, AFTER extraction, instead of
              handing Claude the raw page (which is what broke extraction
              in 09-18c): _extract_site_form_links() pulls (site name, form
              URL) pairs straight out of the calendar page's own small HTML
              table (confirmed live: a plain, un-rendered <table> with one
              row per site -- 11 rows on a real fetch, all 11 containing a
              form link), and _match_site_form_link() scores each extracted
              event against those rows by shared, inverse-document-
              frequency-weighted words (so a word nearly every row has, like
              "cleanup" or "beach", barely counts, while a rare place name
              like "foster" or "mussel" counts heavily), refusing to guess
              when the top two candidates are within a hair of each other.
              A first version still produced one false positive under
              testing against real data: "Pacifica State Beach Cleanup" (a
              real event with no table row) won a clear, non-tied match
              against "Linda Mar State Beach Cleanup" purely off generic
              shared words ("pacifica", "state", "beach", "cleanup") that
              most of the table's rows share. Fixed with a second "anchor
              gate" check: even a non-tied winner must also share at least
              one genuinely RARE word (appearing in only a couple of the
              table's own rows) with the event, using a stricter stopword
              set that also strips those generic descriptive words --
              rejecting outright (never falling back to a lower-ranked
              candidate) when it doesn't. Verified against the real 11-row
              table plus real event names/locations pulled from a live
              events.json: 16 test cases covering every real site (including
              disambiguating "Linda Mar State Beach Cleanup" from the
              separate "Linda Mar Habitat Restoration" at the same spot) and
              five real non-matching events that must return None (Pacifica
              State Beach Cleanup, Thornton Vista Cleanup and Habitat
              Restoration, Calera Creek Habitat Restoration, CA Coastal
              Cleanup Day, PBC General Meeting) -- all pass. Also re-verified
              the underlying table parser against the real, live PBC
              calendar page HTML (not just a reconstruction), confirming 11
              real rows with the exact same site names used in testing.
              Finished with a full mocked dry run of process_google_calendar_org()
              confirming: extra_context stays empty (doesn't regress
              09-18c), exactly one Claude call is made, real events get
              matched to their real form links, and events with no table row
              are correctly left without one rather than guessing.
  2026-09-18e The site owner walked through the Pacific Beach Coalition calendar by
              hand (main page -> click a date -> click an event -> "Register
              online to volunteer") and gave a real, working form URL --
              which immediately showed the whole 09-18d approach above,
              while real and thoroughly tested against the data it was
              built on, was solving the wrong problem. That real link
              turned out to belong to "Calera Creek Habitat Restoration",
              an event that was NEVER in the 11-row site->form table on the
              calendar page (confirmed: the table-matching tests correctly
              returned None for it) -- because the real registration link
              was never in that table at all. It's embedded directly in
              each individual Google Calendar EVENT's own description,
              which only becomes visible by clicking that specific event.
              Investigated live (Chrome DevTools-style, via the browser
              tools) what actually powers that per-event popup: the
              calendar's own embed widget calls Google's public Calendar
              API v3 (`events.list`) directly from the browser, using an
              API key baked into Google's own client-side JS -- the exact
              same request anyone can make with their own free API key (no
              OAuth, no billing required -- confirmed against Google's
              current docs). That response contains the FULL event data
              already, including each event's own description with its
              real registration link, and confirmed the same is true for
              Surfrider's calendar too (the site owner asked whether this would help
              there as well -- it does, same mechanism, same fix).
                Replaced the whole site-form-table/word-matching approach
              (_extract_site_form_links, _match_site_form_link, and the two
              stopword sets around it -- all now deleted) with a direct
              call to that same official API
              (fetch_google_calendar_events_via_api(), using a new optional
              GOOGLE_CALENDAR_API_KEY secret), which gives exact structured
              data straight from Google for both "google_calendar" orgs: no
              more AI extraction, no more guessing at dates/times/locations
              from scraped text, and each event's own real registration
              link pulled directly out of its description
              (_extract_registration_link_from_description) rather than
              approximated after the fact. Along the way, confirmed live
              that the register link inside a real description is
              sometimes wrapped in Google's own "https://www.google.com/
              url?q=..." redirect shim (even in the raw API response, not
              just the rendered widget) -- decoded directly
              (_decode_google_url_shim) rather than depending on that
              redirect service behaving the same way for a plain
              server-side request. Also confirmed live that the register
              link's visible text is sometimes wrapped in a NESTED tag
              (e.g. "<a ...><b>REGISTER HERE</b></a>", even triple-nested
              for one Surfrider event) -- a naive "no nested tags" regex
              would silently miss these entirely, so
              _extract_registration_link_from_description() captures
              everything up to the closing </a> and strips inner tags from
              the captured text afterward instead. Separately confirmed
              live that a few PBC events (Foster City Cleanup, Mussel Rock
              Beach Cleanup, Linda Mar Habitat Restoration, CA Coastal
              Cleanup Day) have no location field and no "Where to Meet:"
              text in their description either -- previously they still
              showed up on the map because Claude's own extraction
              inferred a reasonable location from the event name; the pure
              structured-API path has no such inference, so without a
              fallback these would have silently disappeared from the map,
              a real regression. Added a small named-site fallback list
              (_PBC_EVENT_NAME_LOCATION_FALLBACKS) for exactly these
              already-known recurring events, which still goes through the
              normal geocode() fallback chain rather than a hardcoded
              coordinate.
                Kept the whole older ICS/agenda-view/AI-extraction pipeline
              in place as an automatic fallback -- both when
              GOOGLE_CALENDAR_API_KEY isn't set yet and when the API call
              itself fails for any reason (bad key, quota, network) -- so
              this can't leave either org silently empty. Verified with 15
              unit tests covering the link-decoding, nested-tag extraction,
              location fallback chain, and event-shape conversion against
              real structures confirmed live for both orgs, plus a full
              mocked dry run of process_google_calendar_org() (API path for
              both orgs, including the exact Thornton Vista event the old
              table-matching approach could never link) and of main()
              end-to-end, and a fallback test confirming the older pipeline
              still kicks in correctly both when the key is unset and when
              the API call itself errors.
2026-09-19  GOOGLE_CALENDAR_API_KEY got set up and this pipeline finally got
              a real production run -- confirming Surfrider worked exactly as
              designed (5 events fetched straight from the API, real
              registration links, no AI extraction), but Pacific Beach
              Coalition was STILL falling back to the older pipeline every
              time, now failing differently: not "key missing" but a genuine
              "404 Client Error: Not Found" from
              www.googleapis.com/calendar/v3/calendars/.../events, using the
              exact calendar id extract_google_calendar_id() had pulled from
              the page.
                Root-caused live rather than guessed: pulled Pacific Beach
              Coalition's actual calendar page HTML directly and confirmed
              its embed iframe's `src` value is NOT a plain calendar id like
              Surfrider's -- it's base64 ("cGlja2l0dXBwYWNpZmljYUBnbWFpbC5j
              b20"). extract_google_calendar_id() was using that raw base64
              string AS the calendar id, which is why every fetch 404'd: no
              calendar is literally named that string. Decoded it
              (base64 -> "pickituppacifica@gmail.com") and verified LIVE, in
              a real browser, that a direct call to this exact same
              production endpoint --
              https://www.googleapis.com/calendar/v3/calendars/pickituppacifica%40gmail.com/events
              -- returns a real 200 with real event data for that decoded
              id, proving definitively that the calendar's public sharing
              was never the problem; the raw, un-decoded src value was.
                Added _resolve_calendar_id(): if the embed's `src` doesn't
              already contain "@" (a real calendar id always does), try
              base64-decoding it (padding it back out first, since it's
              routinely stored unpadded in HTML/URLs -- confirmed true for
              this exact id, 35 chars, not a multiple of 4) and use the
              decoded value only if THAT contains "@" too -- otherwise the
              original string is kept untouched, so a future org with a
              plain but coincidentally base64-charset-safe id can't get
              mangled by this. extract_google_calendar_id() now runs every
              extracted id through this before returning it, so both the
              plain-id case (Surfrider) and the base64 case (Pacific Beach
              Coalition) resolve to the correct real id automatically, with
              no per-org configuration needed.
                Also used this same production run's log to confirm two
              Surfrider events (both recurring "Monthly Chapter Meeting"
              instances) get correctly dropped for having no location data
              anywhere -- no location field, no "Where to Meet:" text, and
              (checked directly against the real API response) nothing
              location-like anywhere in the description either. This is not
              a regression from the API path: the older AI-extraction
              pipeline hit the exact same wall on this org's own page text
              in the past (its earlier log line literally read "could not
              geocode 'Meeting location provided in registration link'" --
              i.e. even Claude could only find a placeholder saying the
              location was inside the registration form, not an actual
              address). Nothing to fix here -- a real event with no
              discoverable location correctly gets skipped rather than
              plotted with a guessed or wrong pin, on both pipelines alike.
                Verified with 4 new unit tests covering _resolve_calendar_id
              directly (decodes the real confirmed PBC id, leaves a plain id
              alone, leaves non-calendar-shaped base64 alone rather than
              guessing, and handles the padding-stripped form same as the
              real HTML has it) -- 19 unit tests total now, all passing --
              plus a full mocked dry run of main() end-to-end confirming
              nothing else regressed.
2026-10-14  The site owner reported Pacific Beach Coalition back at 0 events
              again. Investigated live rather than guessing: the Google
              Calendar API call now 404s (same endpoint that worked on
              2026-09-19), the iCal export also 404s, AND loading the
              calendar embed directly in a real browser showed "Oops, we
              couldn't load your events, please try again in a few minutes"
              -- reproduced on PBC's OWN website
              (pacificbeachcoalition.org/calendar-2026/), for both October
              and November 2026, not just in this script. All three existing
              fallbacks share that one Google Calendar dependency, so none of
              them could route around an outage on Google/PBC's side.
                Replaced PBC's data source entirely rather than add a fourth
              Google Calendar fallback on top of three failing ones: PBC's
              own site separately publishes a static table (confirmed by
              hand: 11 rows, kind="pbc_site_table" + listing_page in ORGS)
              listing every cleanup site with (a) a "More info" page giving
              that site's recurring schedule in plain text and (b) that
              site's own direct Google Form sign-up link right there in the
              table -- real per-site registration links with no
              description-matching guesswork needed, unlike the September
              9-18 site-table attempts that were abandoned for exactly that
              reason (this time the link comes straight from the table, not
              inferred).
                Most site pages (confirmed: Esplanade, San Pedro Creek) list
              every upcoming date for the year explicitly, which the existing
              claude_extract_events() already handles as-is -- tried first
              for every site (process_pbc_site_table_org()). A few pages
              (confirmed: Rockaway Beach) give only a recurrence rule in
              prose ("First Saturday of the month from 9am-11am") with no
              literal dates on the page -- for those,
              _extract_site_recurrence_rule() asks Claude to read off the
              rule as plain text/enum fields only (ordinal, weekday, time,
              location -- no date arithmetic asked of the model), and the new
              _dates_for_recurrence() computes the actual calendar dates in
              plain Python, checked against real confirmed dates (San Pedro
              Creek's page independently listed "1st Saturday" -> Oct 3,
              2026 and Esplanade's "3rd Saturday" -> Oct 17, 2026; both match
              what _dates_for_recurrence() computes for those rules).
                Verified PBC_ROW_RE against the real table's exact DOM
              structure (confirmed live via browser: <tr><td><strong>NAME
              <a href=detail>More info...</a></strong></td><td><a
              href=form>VOLUNTEER &gt;</a></td></tr>, same shape for all 11
              rows including the one habitat-restoration row with different
              anchor text) and unit-tested _dates_for_recurrence() against
              both real dates above before sending. Surfrider is untouched
              and still uses the Google Calendar API path; only PBC's "kind"
              changed.
2026-10-15  The first run of the above (run #23) fetched PBC's table page fine
              (67,914 chars) but logged "site-table regex found 0 row(s)", so
              PBC stayed empty. Root cause: PBC_ROW_RE was written from the
              browser's parsed DOM view, which showed the "More info" link
              nested inside <strong>; the raw HTML the server actually sends
              has ONLY the site name inside <strong> and the link directly in
              the cell. Fixed by fetching the live page's real source and
              rewriting the pattern to match it -- confirmed it matches all 11
              real rows (including "Surfer&#8217;s Beach", whose HTML entity
              is now decoded by process_pbc_site_table_org()). The earlier
              mocked dry run passed because its sample HTML was written in the
              same wrong shape as the pattern; the sample is now the real
              shape.
2026-10-20  Added descriptive event TAGS for the new Search tab (search.html).
              After each organization's events are cleaned, tag_events() makes
              one Claude call (forced record_tags tool, fixed vocabulary in
              TAG_VOCAB -- kind / level / setting / place / goodfor) and
              attaches a "tags" list to every event in events.json. Tags are
              sanitized (unknown tags dropped, exactly one level and one
              setting kept), events that are still listed from the previous
              run keep their old tags (load_previous_tags(), so no
              flip-flopping and no repeat cost), and any failure is non-fatal:
              the event is just written without "tags" and search.html infers
              its own from the title/location. Set TAGGING_ENABLED=0 to switch
              it off. Nothing else in events.json changed, so the map and
              dashboard are unaffected.
              Also changed Pacific Beach Coalition's map/dashboard color from
              orange to brick red to fit the site's new, more professional
              palette.
"""

import base64
import json
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta
import html as _htmlmod
from html.parser import HTMLParser as _HTMLParser
from urllib.parse import urljoin

import requests

try:
    import anthropic
except ImportError:
    print("Missing dependency 'anthropic'. pip install -r requirements.txt", file=sys.stderr)
    raise

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
LOOKAHEAD_DAYS = int(os.environ.get("LOOKAHEAD_DAYS", "56"))  # ~8 weeks
# Cost safety. MAX_CLAUDE_CALLS is a hard stop: after that many Claude API
# calls in one run, further calls are refused (the org just keeps its previous
# events). A normal run makes well under 100. The prices (dollars per million
# tokens) only feed the estimate printed at the end of the run.
MAX_CLAUDE_CALLS = int(os.environ.get("MAX_CLAUDE_CALLS", "150"))
PRICE_PER_MTOK_IN = float(os.environ.get("PRICE_PER_MTOK_IN", "2.0"))
PRICE_PER_MTOK_OUT = float(os.environ.get("PRICE_PER_MTOK_OUT", "10.0"))
# Test one organization without touching the others: ONLY_ORGS="food bank" (a
# comma-separated list of name fragments). Every other org keeps what is already
# in events.json. DRY_RUN=1 prints the results and does not write events.json.
ONLY_ORGS = [x.strip().lower() for x in os.environ.get("ONLY_ORGS", "").split(",") if x.strip()]
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes", "on")
EVENTS_JSON_PATH = os.environ.get("EVENTS_JSON_PATH", "events.json")
# Optional: a free Google Cloud API key with the Calendar API enabled (no
# billing required -- see the CHANGELOG entry below dated 2026-09-18e, and
# the repo secret GOOGLE_CALENDAR_API_KEY it's read from in the workflow).
# When set, Surfrider's and
# Pacific Beach Coalition's calendars (both "google_calendar" orgs) are read
# straight from Google's own official Calendar API instead of the older
# ICS/agenda-view + AI-extraction pipeline -- exact structured data and each
# event's own real registration link, no guessing. When unset, those two
# orgs silently fall back to the older pipeline so the script still works.
GOOGLE_CALENDAR_API_KEY = os.environ.get("GOOGLE_CALENDAR_API_KEY")
USER_AGENT = "VolunteerMapBot/1.0 (+https://github.com/chenfamilysanfranciscoai-ctrl/Volunteer-Map; contact: chenfamilysanfranciscoai-ctrl)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

HTTP_HEADERS = {"User-Agent": USER_AGENT}

# A few recurring sites where free-text geocoding of the venue name alone is
# known to fail or land on the wrong spot (e.g. Nominatim doesn't know "MLK" as
# an abbreviation). Add to this as new mismatches show up in the logs -- match
# is a case-insensitive substring check against the extracted location text.
LOCATION_OVERRIDES = {
    "mlk": (37.7433, -122.1975),  # MLK Jr. Regional Shoreline, Oakland
    "eden landing": (37.6155, -122.1085),  # Eden Landing Ecological Reserve, Hayward
    "ravenswood": (37.4784, -122.1997),  # Ravenswood / Cooley Landing, East Palo Alto
    "radio road": (37.6262, -122.1114),  # Radio Road Marsh, Redwood City
}

ORGS = [
    {
        "org": "Surfrider Foundation (SF Chapter)",
        "cause": "environment",
        "color": "#4a7856",
        "kind": "google_calendar",
        "calendar_page": "https://sf.surfrider.org/calendar",
    },
    {
        "org": "Pacific Beach Coalition",
        "cause": "environment",
        "color": "#a8433f",
        "kind": "pbc_site_table",
        "listing_page": "https://www.pacificbeachcoalition.org/calendar-2026/",
    },
    {
        "org": "Save The Bay",
        "cause": "environment",
        "color": "#3b6ea5",
        "kind": "html_listing",
        "listing_page": "https://savesfbay.org/calendar/",
        "detail_link_pattern": r'https://savesfbay\.org/event/[a-z0-9\-]+/?',
    },
    {
        "org": "Grassroots Ecology",
        "cause": "environment",
        "color": "#8a6d1f",
        "kind": "html_listing",
        "listing_page": "https://www.grassrootsecology.org/event-calendar",
        # This site's own event links are relative (e.g.
        # href="/event-calendar/2026/09/09/volunteer-at-russian-ridge"), never
        # prefixed with the domain -- confirmed by inspecting the real page's
        # raw href attributes. A pattern anchored to "https://www..." never
        # matched anything, which is why this org always came back with 0
        # events regardless of Playwright. process_html_listing_org() resolves
        # whatever this matches against listing_page, so a relative pattern
        # here is enough (and still works fine for an org whose links happen
        # to be absolute, like Save The Bay below).
        "detail_link_pattern": r'/event-calendar/\d{4}/\d{2}/\d{2}/[a-z0-9\-]+',
    },
    # ------------------------------------------------------------------
    # Added 2026-10-21: organizations for other causes. "cause" is one of
    # environment, disaster, youth, seniors, civic, arts, food, animals,
    # housing, various; it is written into events.json as an extra field
    # (the map and dashboard ignore it) so a cause filter can be added later.
    #
    # NONE of these has been run live yet -- they were set up from reading each
    # site's pages. The first run of each is a test: read the log lines under
    # its "== name ==" heading ("detail-link regex found N match(es)", "kept N
    # upcoming event(s)") and fix the pattern or listing_page if N is 0.
    # ------------------------------------------------------------------
    {
        # Confident: server-rendered list, one page per event, dated.
        "org": "SF Neighborhood Emergency Response Team (NERT)",
        "cause": "disaster",
        "color": "#b4532a",
        "kind": "html_listing",
        "listing_page": "https://sf-fire.org/nert-calendar",
        "org_url": "https://sf-fire.org/NERT",
        # Hrefs may be relative (/calendar/nert-...) or absolute.
        "detail_link_pattern": r'(?:https://sf-fire\.org)?/calendar/nert-[a-z0-9\-]+',
    },
    {
        # Confident: plain "Upcoming Events" list, one page per event. The
        # online-only info sessions have no street address and will be skipped
        # at the geocoding step (the log says so).
        "org": "Mentor Tutor Connection",
        "cause": "youth",
        "color": "#6b4c9a",
        "kind": "html_listing",
        "listing_page": "https://www.mentortutorconnection.org/news-events/",
        "org_url": "https://www.mentortutorconnection.org/news-events/",
        "detail_link_pattern": r'https://www\.mentortutorconnection\.org/mc-events/[a-z0-9\-]+/?',
    },
    {
        # Recurring weekly cleanup; there is no listing page to read, so the
        # rule is written here. The sf.gov page says "every Saturday", 10-11am.
        # If the cleanups stop, delete this entry (or the events keep showing).
        "org": "Civic Joy Fund Bayview Cleanup",
        "cause": "civic",
        "color": "#7a5a2a",
        "kind": "weekly_recurring",
        "org_url": "https://www.mobilize.us/civicjoyfund/",
        "event_name": "Bayview 3rd Street Community Cleanup",
        "weekday": "Saturday",
        "start": "10:00 AM",
        "end": "11:00 AM",
        "location": "1605 Jerrold Ave, San Francisco, CA 94124",
        "booking_url": "https://www.mobilize.us/civicjoyfund/",
    },
    {
        # The home page shows the next used-book sale dates and venue. Volunteers
        # staff the sale, so the sale days are published as volunteer days.
        "org": "Friends of the Palo Alto Library (FOPAL)",
        "cause": "arts",
        "color": "#8c3f5d",
        "kind": "text_page",
        "source_page": "https://www.fopal.org/",
        "org_url": "https://www.fopal.org/volunteer",
        "booking_url": "https://www.fopal.org/volunteer",
        "extra_context": (
            "This home page announces the monthly used-book sale, which volunteers help run. Report each "
            "upcoming sale day (the Saturday and the Sunday separately) as its own event named "
            "'Used Book Sale (volunteers help run it)'. Use ONLY dates stated on the page; do not "
            "work out later months. Use the venue address on the page as the location."
        ),
    },
    # ---- Read directly, no AI (free to run). Each skips shifts with 0 open slots. ----
    {
        # "Get Connected" calendar: the month view's per-day lists come from
        # /calendar/ajaxGetDay. Only the next 3 weeks are read (there are ~280 open
        # shifts in 3 weeks); raise lookahead_days to show more.
        "org": "San Francisco-Marin Food Bank",
        "cause": "food",
        "color": "#b5651d",
        "kind": "galaxy_calendar",
        "base_url": "https://volunteering.sfmfoodbank.org",
        "org_url": "https://volunteering.sfmfoodbank.org/need",
        "lookahead_days": 21,
        "verify_links": False,     # the links come straight from the site's own list
        "default_tags": ["moderate"],
        "tag_rules": [(r"warehouse|kitchen", ["indoors"])],
    },
    {
        # Salesforce "Hot Spots" page: two embedded shift lists, each under a
        # 'Location:' line. Slots marked full are skipped. Sign-up happens in a
        # pop-up on the Hot Spots page, so that page is the link.
        "org": "Project Open Hand",
        "cause": "food",
        "color": "#c0392b",
        "kind": "openhand_hotspots",
        "source_page": "https://www.openhand.org/hotspots",
        "org_url": "https://www.openhand.org/volunteer/volunteer-hot-spots",
        "default_city": "San Francisco, CA",
        "verify_links": False,
        "default_tags": ["moderate", "indoors"],
        # Used only when openhand.org refuses the request (it answered 403 to the
        # GitHub runner). Copied from the live Hot Spots page on 2026-10-23.
        "fallback_frames": [
            {"program": "Prepare Medically-Tailored Meals", "location": "730 Polk Street, 1st Floor",
             "src": "https://openhand.my.salesforce-sites.com/volunteer/GW_Volunteers__VolunteersJobListingFS?CampaignID=701Vv00000rQXRd&ShowNumberAvailable=1&nDaysToShow=15"},
            {"program": "Assemble Medically-Tailored Groceries and Meals", "location": "730 Polk Street, 2nd Floor",
             "src": "https://openhand.my.salesforce-sites.com/volunteer/GW_Volunteers__VolunteersJobListingFS?CampaignID=701Vv00000q6pUv&ShowNumberAvailable=1&nDaysToShow=15"},
        ],
    },
    {
        # Salesforce job listing page; each shift links to its own page, built
        # the same way the St. Anthony's calendar builds it.
        "org": "St. Anthony's Foundation",
        "cause": "housing",
        "color": "#1f5f8b",
        "kind": "v4s_listing",
        "listing_base": "https://stanthonysf.my.salesforce-sites.com/volunteer/GW_Volunteers__VolunteersJobListingFS",
        "org_url": "https://www.stanthonysf.org/volunteer/sign-up-now/",
        "default_city": "San Francisco, CA",
        "verify_links": False,
        "default_tags": ["moderate"],
        "tag_rules": [(r"breakfast|dining|clothing", ["indoors"])],
    },
    # ---- Needs testing: JavaScript-rendered volunteer portals. The script
    # falls back to a headless browser automatically when the first plain fetch
    # shows no event links. ----
    {
        "org": "Meals on Wheels San Francisco",
        "cause": "seniors",
        "color": "#9a4a6b",
        "kind": "html_listing",
        "listing_page": "https://volunteer.mowsf.org/calendar",
        "org_url": "https://volunteer.mowsf.org/",
        # Galaxy Digital opportunity pages: /need/detail/?need_id=<number>
        "detail_link_pattern": r'(?:https://volunteer\.mowsf\.org)?/need/detail/\?need_id=\d+',
    },
    {
        # The volunteer calendar on shfb.org loads ONE JSON feed (WordPress ajax
        # action "mmvfs_get_data"): every shift with its date, clock times, open
        # slots, address and coordinates. Shifts on the same day and place are
        # nested inside one another, so the reader flattens them. Each shift has
        # its own page: <calendar page>?shift_id=<id>. No AI calls.
        "org": "Second Harvest Food Bank of Silicon Valley",
        "cause": "food",
        "color": "#a0731a",
        "kind": "mmvfs_feed",
        "feed_url": "https://www.shfb.org/wp-admin/admin-ajax.php?action=mmvfs_get_data",
        "shift_page": "https://www.shfb.org/give-help/volunteer/volcalendar-general/",
        "job_types": ["Sort Food", "Distribute Food"],
        "lookahead_days": 21,
        "org_url": "https://www.shfb.org/give-help/volunteer/individual-volunteering/",
        "verify_links": False,
        "default_tags": ["moderate"],
        "tag_rules": [(r"^sort food", ["indoors"])],
    },
]

RECORD_EVENTS_TOOL = {
    "name": "record_events",
    "description": "Record the volunteer events extracted from the source text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Short event name/title"},
                        "date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                        "start": {"type": "string", "description": "Start time, e.g. '9:00 AM'"},
                        "end": {"type": ["string", "null"], "description": "End time, e.g. '12:00 PM', or null if not stated"},
                        "location": {"type": "string", "description": "Best available location text: venue name and/or street address"},
                        "bookingUrl": {
                            "type": ["string", "null"],
                            "description": (
                                "The direct sign-up/registration URL for THIS SPECIFIC event, if one is "
                                "actually present in the source text (an org's own registration page, an "
                                "Eventbrite/Google Form/SignUpGenius link, etc). Null if no event-specific "
                                "link is present -- never invent or guess one."
                            ),
                        },
                    },
                    "required": ["name", "date", "start", "location"],
                },
            }
        },
        "required": ["events"],
    },
}

EXTRACTION_SYSTEM_PROMPT = """You extract upcoming volunteer event listings from messy website text/HTML/ICS \
content for a Bay Area volunteering map (all causes: environment, food, seniors, youth, \
disaster preparedness, civic and more). Rules:
- Only include events dated today ({today}) or later. Ignore past events.
- One event per calendar entry. If a single day lists many separate sites/locations \
(e.g. a coastal cleanup day with multiple named sites), output each site as its own event, \
all sharing that date.
- For "location", give the most specific address or place name available in the text. \
Do not invent an address if none is given -- use whatever place name is present.
- For "bookingUrl", only use a URL that literally appears in the provided text and is specific \
to that event (not the org's generic homepage). If the text includes a table mapping site names \
to sign-up form links, match each event to the right link by site name. If nothing event-specific \
exists, leave bookingUrl null.
- A training course that meets on several dates: if each session date is listed, output one event per \
session; if only the first and last dates are given, output ONE event on the first session date.
- Normalize times to a "H:MM AM/PM" style string. If no end time is stated, use null.
- Call the record_events tool exactly once with everything you found."""


# --------------------------------------------------------------------------
# Event tags (descriptive adjectives for the Search page)
# --------------------------------------------------------------------------
# The Search tab (search.html) filters on these. The SAME vocabulary lives in
# search.html's TAG_GROUPS -- if you add or rename a tag here, change it there
# too. search.html also works out tags for itself from each event's title and
# location, so events.json "tags" are an upgrade (Claude can judge things like
# how strenuous a workday is), never a requirement: if tagging fails for any
# reason the events are still written, just without a "tags" list.
TAGGING_ENABLED = os.environ.get("TAGGING_ENABLED", "1").lower() not in ("0", "false", "no", "off")

TAG_VOCAB = {
    "kind": ["cleanup", "planting", "restoration", "invasive-removal", "gardening",
             "nature-walk", "community-event", "monitoring"],
    "level": ["relaxed", "moderate", "active"],          # exactly one per event
    "setting": ["outdoors", "indoors"],                  # exactly one per event
    "place": ["beach", "dunes", "creek", "wetland", "woodland", "garden"],
    "goodfor": ["beginner-friendly", "family-friendly", "educational", "social"],
}
TAG_GROUP_OF = {tag: grp for grp, tags in TAG_VOCAB.items() for tag in tags}
ALL_TAGS = [tag for tags in TAG_VOCAB.values() for tag in tags]
_TAG_MAX_PER_GROUP = {"kind": 3, "level": 1, "setting": 1, "place": 2, "goodfor": 3}

RECORD_TAGS_TOOL = {
    "name": "record_tags",
    "description": "Record descriptive tags for each volunteer event, by its index number.",
    "input_schema": {
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer", "description": "The event's index number from the list"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string", "enum": ALL_TAGS},
                            "description": "Tags from the fixed vocabulary only",
                        },
                    },
                    "required": ["index", "tags"],
                },
            }
        },
        "required": ["events"],
    },
}

TAGGING_SYSTEM_PROMPT = """You label Bay Area environmental volunteer events with short descriptive tags for a \
search page. You will get a numbered list of events (name, date, time, location) from one organization. \
Choose tags ONLY from this fixed vocabulary:

- kind (what volunteers will actually do; pick 1-3): cleanup (picking up trash/debris), planting (putting \
native plants in the ground, nursery/potting work, revegetation), restoration (habitat or dune \
restoration work), invasive-removal (pulling weeds/invasive plants), gardening (garden or pollinator-garden \
upkeep), nature-walk (hikes, walks, guided outings), community-event (festivals, celebrations, plant \
sales, social gatherings), monitoring (water-quality testing, surveys, citizen science)
- level (how physically demanding; pick EXACTLY ONE): relaxed (low effort: festivals, talks, easy walks, \
monitoring), moderate (a couple of hours of walking, bending and light lifting: beach cleanups, gardening, \
planting), active (sustained digging, hauling, or uphill work: dune planting, habitat restoration, \
invasive removal)
- setting (pick EXACTLY ONE): outdoors, indoors
- place (the environment, pick 0-2): beach, dunes, creek (creek or stream), wetland (marsh, baylands, bay \
shoreline), woodland (forest, preserve, hills), garden (garden or nursery)
- goodfor (pick 0-3, only if plausible from the listing): beginner-friendly (no experience needed), \
family-friendly (reasonable for kids), educational (volunteers will learn something), social (community / \
meet-people feel)

Rules: judge only from the information given -- do not invent details. Use the event name and location, \
not the organization's name, to decide place tags (an organization called "Beach ..." does not make \
every event a beach event). If a title is just a place name and the organization only runs one kind of \
event (e.g. a cleanup-site list), use that kind. Night-time events are not family-friendly. Call \
record_tags exactly once, including every index."""


# Causes other than "environment" only use these groups: the "kind" and "place"
# tags (cleanup, planting, beach, dunes ...) describe environmental work and
# would be wrong for, say, a food-bank shift or a CERT training.
NON_ENV_TAG_GROUPS = ("level", "setting", "goodfor")

NON_ENV_TAGGING_NOTE = """

IMPORTANT: this organization is NOT an environmental group. Use ONLY the level, setting and goodfor \
groups; never use kind or place tags. For level, judge physical effort: relaxed (trainings, talks, info \
sessions, phone or desk work, light tasks), moderate (serving, packing, sorting, tutoring, a few hours on \
your feet), active (heavy lifting, construction or repair, sustained physical work)."""


def _tags_tool(allowed_tags):
    """record_tags tool definition restricted to the given tags."""
    tool = json.loads(json.dumps(RECORD_TAGS_TOOL))
    tool["input_schema"]["properties"]["events"]["items"]["properties"]["tags"]["items"]["enum"] = list(allowed_tags)
    return tool


def sanitize_tags(tags, allowed_groups=None):
    """Keep only known tags, drop duplicates, and enforce the per-group limits
    (exactly one level and one setting, at most N of the others). Anything
    unknown -- or a non-list -- is discarded, never published."""
    if not isinstance(tags, (list, tuple)):
        return []
    seen_per_group = {}
    out = []
    for raw in tags:
        if not isinstance(raw, str):
            continue
        tag = raw.strip().lower()
        grp = TAG_GROUP_OF.get(tag)
        if grp is None or tag in out:
            continue
        if allowed_groups is not None and grp not in allowed_groups:
            continue
        if seen_per_group.get(grp, 0) >= _TAG_MAX_PER_GROUP[grp]:
            continue
        seen_per_group[grp] = seen_per_group.get(grp, 0) + 1
        out.append(tag)
    # stable, readable order: group order from TAG_VOCAB, then vocabulary order
    out.sort(key=lambda t: ALL_TAGS.index(t))
    return out


def _tag_cache_key(org_name, ev):
    return (org_name.strip().lower(), str(ev.get("name", "")).strip().lower(),
            str(ev.get("location", "")).strip().lower())


def load_previous_tags(path=None):
    """Tags from the events.json written by the previous run, so an event that
    is still listed keeps the exact same tags (no flip-flopping between runs,
    and no repeat API cost). Any problem reading the file just means 'no cache'."""
    path = path or EVENTS_JSON_PATH
    cache = {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for org in data:
            for ev in org.get("events", []):
                tags = sanitize_tags(ev.get("tags"))
                if tags:
                    cache[_tag_cache_key(org.get("org", ""), ev)] = tags
    except Exception:
        return {}
    return cache


def tag_events(client, org_name, cleaned_events, previous_tags=None, cause="environment"):
    """Attach a "tags" list to each cleaned event, in place. One Claude call per
    organization covers all of its not-yet-tagged events. Never raises: on any
    failure the affected events simply keep no "tags" (search.html infers its
    own), and the rest of the run carries on."""
    if not TAGGING_ENABLED or not cleaned_events:
        return
    allowed_groups = None if cause == "environment" else NON_ENV_TAG_GROUPS
    allowed_tags = ALL_TAGS if allowed_groups is None else [t for t in ALL_TAGS if TAG_GROUP_OF[t] in allowed_groups]
    system_prompt = TAGGING_SYSTEM_PROMPT + ("" if allowed_groups is None else NON_ENV_TAGGING_NOTE)
    previous_tags = previous_tags or {}
    todo = []
    reused = 0
    for ev in cleaned_events:
        if ev.get("tags"):
            continue          # already tagged by the org's own reader (no Claude call needed)
        cached = sanitize_tags(previous_tags.get(_tag_cache_key(org_name, ev)), allowed_groups)
        if cached:
            ev["tags"] = list(cached)
            reused += 1
        else:
            todo.append(ev)
    if reused:
        log(f"  tags: reused {reused} from the previous run")
    if not todo:
        return
    try:
        lines = []
        for i, ev in enumerate(todo):
            lines.append(f"{i}. {ev.get('name', '')} | {ev.get('date', '')} {ev.get('start', '')}"
                         f"{' - ' + ev['end'] if ev.get('end') else ''} | {ev.get('location', '')}")
        user_content = f"Organization: {org_name}\n\nEvents:\n" + "\n".join(lines)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system_prompt,
            tools=[_tags_tool(allowed_tags)],
            tool_choice={"type": "tool", "name": "record_tags"},
            messages=[{"role": "user", "content": user_content}],
        )
        tagged = 0
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "record_tags":
                items = block.input.get("events", []) if isinstance(block.input, dict) else []
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    idx = item.get("index")
                    if not isinstance(idx, int) or isinstance(idx, bool) or not (0 <= idx < len(todo)):
                        continue
                    tags = sanitize_tags(item.get("tags"), allowed_groups)
                    if tags:
                        todo[idx]["tags"] = tags
                        tagged += 1
        log(f"  tags: Claude tagged {tagged} of {len(todo)} new event(s)")
    except Exception as e:
        log(f"  ! tagging failed for {org_name} (events kept without tags; the Search page "
            f"will infer its own): {e}")


def log(msg):
    print(msg, flush=True)


# Claude usage this run (see MAX_CLAUDE_CALLS above).
CLAUDE_CALLS = 0
CLAUDE_IN_TOKENS = 0
CLAUDE_OUT_TOKENS = 0


def install_cost_guard(client):
    """Wrap client.messages.create so every call is counted and the hard cap is
    enforced. A refused call raises, which the callers already treat like any
    other API failure (the org keeps its previous events)."""
    original = client.messages.create

    def guarded(*args, **kwargs):
        global CLAUDE_CALLS, CLAUDE_IN_TOKENS, CLAUDE_OUT_TOKENS
        if CLAUDE_CALLS >= MAX_CLAUDE_CALLS:
            raise RuntimeError(f"cost guard: refusing Claude call #{CLAUDE_CALLS + 1} "
                               f"(MAX_CLAUDE_CALLS={MAX_CLAUDE_CALLS})")
        CLAUDE_CALLS += 1
        resp = original(*args, **kwargs)
        usage = getattr(resp, "usage", None)
        CLAUDE_IN_TOKENS += int(getattr(usage, "input_tokens", 0) or 0)
        CLAUDE_OUT_TOKENS += int(getattr(usage, "output_tokens", 0) or 0)
        return resp

    client.messages.create = guarded


def log_claude_usage():
    cost = CLAUDE_IN_TOKENS / 1e6 * PRICE_PER_MTOK_IN + CLAUDE_OUT_TOKENS / 1e6 * PRICE_PER_MTOK_OUT
    log(f"Claude usage this run: {CLAUDE_CALLS} call(s), {CLAUDE_IN_TOKENS:,} input + "
        f"{CLAUDE_OUT_TOKENS:,} output tokens, about ${cost:.2f} (cap: {MAX_CLAUDE_CALLS} calls)")


# Number of failed Claude API calls so far this run. main() compares it before
# and after each organization: if calls failed AND the org came back empty, the
# problem is the API (no credit, outage, rate limit), not the org's calendar, so
# the org's previous events are kept instead of being wiped.
API_ERROR_COUNT = 0


def load_previous_events(path=None):
    """{org name: [event, ...]} from the events.json written by the previous run."""
    path = path or EVENTS_JSON_PATH
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {o.get("org", ""): [e for e in o.get("events", []) if isinstance(e, dict)]
                for o in data if isinstance(o, dict)}
    except Exception:
        return {}


def http_get(url, **kwargs):
    resp = requests.get(url, headers=HTTP_HEADERS, timeout=30, **kwargs)
    resp.raise_for_status()
    return resp.text


class _TextExtractor(__import__("html.parser", fromlist=["HTMLParser"]).HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "head"}
    _BREAK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BREAK:
            self.parts.append("\n")
        elif tag == "a":
            href = dict(attrs).get("href")
            if href and not href.startswith(("#", "javascript:")):
                self.parts.append(f" [link: {href}] ")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(page_html):
    """Visible text of a page (scripts/styles dropped), with each link's href kept
    inline as "[link: ...]" so Claude can still match a sign-up URL to its event.
    Raw HTML is mostly markup, so truncating it at N characters often cut off
    the actual content; text is far more compact."""
    parser = _TextExtractor()
    try:
        parser.feed(page_html)
        parser.close()
    except Exception:
        pass
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def render_with_playwright(url):
    """Fallback for pages that build their calendar/event links with client-side
    JavaScript, so a plain requests.get() sees an empty shell. Only called when
    the cheap plain-HTTP path finds nothing -- this is slower (spins up a real
    headless Chromium) and isn't needed for every org."""
    from playwright.sync_api import sync_playwright

    log(f"  (falling back to a rendered browser fetch for {url})")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(user_agent=USER_AGENT)
            page.goto(url, timeout=45000, wait_until="networkidle")
            # Give any late-loading widgets (e.g. a Google Calendar iframe) a
            # moment past "networkidle" to finish painting.
            page.wait_for_timeout(2000)
            return page.content()
        finally:
            browser.close()


_verify_cache = {}


def verify_url(url, timeout=10):
    """Confirm a booking link actually resolves before we publish it. A 2xx/3xx
    (after redirects) counts as good; anything else, or a request that errors
    out entirely, means we drop the link rather than publish something dead.
    Results are remembered for the run, so a link shared by many events is
    only checked once."""
    if url in _verify_cache:
        return _verify_cache[url]
    ok = _verify_url_uncached(url, timeout)
    _verify_cache[url] = ok
    return ok


def _verify_url_uncached(url, timeout=10):
    try:
        resp = requests.head(
            url, headers=HTTP_HEADERS, timeout=timeout, allow_redirects=True
        )
        if resp.status_code >= 400:
            # Some servers don't implement HEAD properly -- retry with GET
            # before giving up on an otherwise-plausible link.
            resp = requests.get(
                url, headers=HTTP_HEADERS, timeout=timeout, allow_redirects=True, stream=True
            )
            resp.close()
        return resp.status_code < 400
    except requests.RequestException as e:
        log(f"  ! bookingUrl failed verification, dropping it: {url} ({e})")
        return False


def extract_google_calendar_id(page_html):
    """Google Calendar embeds are plain <iframe src="https://calendar.google.com/calendar/embed?...">
    tags present in the server-rendered HTML -- no JS execution needed to find them.

    Don't assume `src` is any particular parameter in the query string -- Google's
    own embed code doesn't put it first for every org (confirmed: Pacific Beach
    Coalition's embed URL is `...embed?height=...&wkst=...&bgcolor=...&ctz=...&
    showCalendars=...&showTitle=...&showNav=...&src=<id>&color=...`, with `src`
    8th). Grab the whole query string after `embed?` and parse it properly
    instead of anchoring a regex to `?src=`."""
    m = re.search(r'calendar\.google\.com/calendar/embed\?([^"\'<>\s]+)', page_html)
    if not m:
        return None
    import html
    from urllib.parse import parse_qs, unquote

    # Server-rendered HTML represents the "&" between query params as the
    # entity "&amp;" inside an attribute value -- unescape that (and
    # unquote() any %-encoding) before splitting into individual params, or
    # everything after the first param gets swallowed into one bogus key.
    query_string = html.unescape(unquote(m.group(1)))
    qs = parse_qs(query_string)
    src_values = qs.get("src")
    if not src_values:
        return None
    return _resolve_calendar_id(src_values[0])


def _resolve_calendar_id(raw_id):
    """The `src` value from a Google Calendar embed is usually already the
    real calendar id (e.g. "xxxx@group.calendar.google.com" -- confirmed
    this is exactly what Surfrider's embed uses, and it works as-is).

    2026-09-19: root-caused, with a real live test, why Pacific Beach
    Coalition's API fetch was 404ing on every run even after
    GOOGLE_CALENDAR_API_KEY was correctly set: its embed's `src` isn't a
    plain id at all, it's base64 -- "cGlja2l0dXBwYWNpZmljYUBnbWFpbC5jb20",
    confirmed live to be exactly the base64 encoding of
    "pickituppacifica@gmail.com". Our fetch was asking the API for a
    calendar literally NAMED that base64 string, which of course doesn't
    exist (404) -- meanwhile the calendar IS genuinely public: a direct
    call to this script's own endpoint,
    https://www.googleapis.com/calendar/v3/calendars/pickituppacifica%40gmail.com/events,
    was verified live (in a browser, using a real key) to return 200 with
    real event data, proving the base64 id -- not the calendar's public
    sharing settings -- was the entire problem.

    A plain id always contains "@" already, so only attempt to decode when
    it doesn't, and only trust the decoded result if IT contains "@" too
    (a real calendar id always does) -- otherwise silently keep the
    original string. This avoids mangling some future org's plain id that
    happens to only use base64-safe characters (unlikely, but cheap to
    guard against) while still recovering the real id for orgs like this
    one."""
    if "@" in raw_id:
        return raw_id
    try:
        padded = raw_id + "=" * (-len(raw_id) % 4)
        decoded = base64.b64decode(padded).decode("utf-8")
    except Exception:
        return raw_id
    if "@" in decoded:
        log(f"  (this calendar's embed uses a base64-encoded id -- decoded it to the real calendar id)")
        return decoded
    return raw_id


def fetch_google_calendar_ics(calendar_id):
    from urllib.parse import quote

    ics_url = f"https://calendar.google.com/calendar/ical/{quote(calendar_id)}/public/basic.ics"
    return http_get(ics_url)


def render_google_calendar_agenda(calendar_id):
    """Fallback for calendars where public *embedding* is enabled but public
    *iCal export* isn't -- their /public/basic.ics 404s even though the embed
    itself shows real events. Confirmed to be the case for Pacific Beach
    Coalition's calendar specifically (loaded both URLs directly: the embed
    shows a full month of real events, the .ics URL 404s).

    Google's own agenda-mode view of the same public embed lists every event
    as plain text -- date, time, title, location -- which Claude can parse
    just as well as an ICS feed, and it's driven by the same public sharing
    setting the embed already relies on, so it works anywhere the embed does."""
    from urllib.parse import quote
    from playwright.sync_api import sync_playwright

    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    url = f"https://calendar.google.com/calendar/embed?src={quote(calendar_id)}&mode=AGENDA"
    log("  (this calendar's public iCal export is unavailable -- rendering its agenda view instead)")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            # Run #9's log showed this failing outright with "Page.goto:
            # Timeout 45000ms exceeded" waiting for "networkidle" -- Google
            # Calendar's agenda view keeps some background connection alive
            # (long-poll/analytics/etc.), so "networkidle" (no network
            # activity for 500ms) can simply never be reached, even though
            # the page itself has fully rendered. Run #7's own log proves the
            # page loads fine well within 45s when it isn't waiting on that:
            # it captured 4841 stable chars of agenda text. Switch to
            # "domcontentloaded" (fires as soon as the DOM itself is parsed,
            # regardless of any lingering background network activity) and
            # lean on the polling-until-stable loop below -- which already
            # exists specifically to wait for the JS-rendered agenda list to
            # finish filling in -- to determine when the page is actually
            # ready, instead of an unreliable network-idle signal.
            #
            # Belt-and-suspenders: also retry the whole load once (fresh
            # page) if it still times out, since a CI runner's network can
            # just be having a bad moment -- one retry is cheap next to a
            # whole org silently coming back empty for a week.
            last_error = None
            for attempt in (1, 2):
                page = browser.new_page(
                    # A generic bot user-agent is fine for a plain HTML
                    # fetch, but Google Calendar's own front end is a full
                    # JS app that reads the user-agent -- give it a normal
                    # desktop Chrome UA and viewport so it renders the same
                    # rich agenda list a real visitor would get, not a
                    # degraded/minimal fallback.
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1400, "height": 1000},
                )
                try:
                    page.goto(url, timeout=60000, wait_until="domcontentloaded")
                except PlaywrightTimeoutError as e:
                    last_error = e
                    log(f"  ! agenda view load attempt {attempt} timed out: {e}")
                    page.close()
                    if attempt == 2:
                        raise
                    continue
                # A completely fresh, cookie-less browser (which is what a
                # CI runner always is) sometimes gets Google's "Before you
                # continue" consent interstitial instead of the calendar
                # itself. Click past it if present -- harmless no-op when
                # it isn't.
                for label in ["Accept all", "I agree", "Accept"]:
                    try:
                        btn = page.get_by_role("button", name=label, exact=False)
                        if btn.count() > 0:
                            btn.first.click(timeout=3000)
                            page.wait_for_timeout(1500)
                            break
                    except Exception:
                        pass
                # The agenda list itself renders progressively via JS/XHR
                # after the page loads -- run #4 confirmed this is real: the
                # page loaded (no consent wall, no error), but a single
                # fixed 2s pause after load only ever captured the header
                # plus the very first entry (5390 chars) instead of the
                # multi-week list a human sees. Poll until the visible text
                # stops growing instead of guessing a fixed delay.
                previous_len = -1
                stable_checks = 0
                for _ in range(20):  # up to ~20s total
                    page.wait_for_timeout(1000)
                    current_text = page.inner_text("body")
                    if len(current_text) == previous_len:
                        stable_checks += 1
                        if stable_checks >= 2:
                            break
                    else:
                        stable_checks = 0
                    previous_len = len(current_text)
                body_text = page.inner_text("body")
                log(f"  agenda view rendered {len(body_text)} chars of text after waiting for it to "
                    f"stabilize (first 200: {body_text[:200]!r})")
                return body_text
            # Unreachable (the loop above always returns or raises), but
            # keeps this function's control flow obviously exhaustive.
            raise last_error
        finally:
            browser.close()


def _claude_extract_events_once(client, org_name, source_text, extra_context=""):
    """A single extraction attempt -- see claude_extract_events() for the
    retry wrapper around this."""
    today_str = date.today().isoformat()
    system = EXTRACTION_SYSTEM_PROMPT.format(today=today_str)
    # Keep prompts within a sane size; truncate very long source dumps.
    max_chars = 60000
    if len(source_text) > max_chars:
        source_text = source_text[:max_chars]

    user_content = f"Organization: {org_name}\n"
    if extra_context:
        user_content += f"\n{extra_context}\n"
    user_content += f"\n--- SOURCE TEXT ---\n{source_text}\n--- END SOURCE TEXT ---"

    global API_ERROR_COUNT
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system,
            tools=[RECORD_EVENTS_TOOL],
            tool_choice={"type": "tool", "name": "record_events"},
            messages=[{"role": "user", "content": user_content}],
        )
    except Exception:
        API_ERROR_COUNT += 1
        raise
    for block in resp.content:
        if block.type == "tool_use" and block.name == "record_events":
            raw = block.input.get("events", [])
            if not isinstance(raw, list):
                log(f"  ! record_events tool call's 'events' field wasn't a list (got "
                    f"{type(raw).__name__}) -- treating as no events extracted")
                return []
            # Run #6: for Grassroots Ecology specifically, this came back as
            # 1071 plain strings instead of event objects -- the schema
            # requires objects, but a forced tool call isn't a hard
            # guarantee Claude always honors every field's declared type.
            # Filter those out here, at the source, rather than letting bad
            # entries travel downstream into date-parsing/geocoding.
            valid = [ev for ev in raw if isinstance(ev, dict)]
            if len(valid) != len(raw):
                log(f"  ! record_events returned {len(raw) - len(valid)} non-object entr"
                    f"{'y' if len(raw) - len(valid) == 1 else 'ies'} out of {len(raw)} -- dropped, kept {len(valid)}")
            return valid
    return []


# Source text shorter than this is plausibly just a header/empty-state with
# genuinely nothing to extract -- not worth a retry. Above it, a 0-event
# result is suspicious enough to be worth a second, independent attempt.
_EXTRACTION_RETRY_MIN_SOURCE_CHARS = 800


def claude_extract_events(client, org_name, source_text, extra_context=""):
    """One (or, if it looks suspicious, two) Claude call(s), forced through
    the record_events tool, returning a list of raw event dicts
    (name/date/start/end/location/bookingUrl) -- no lat/lng yet.

    2026-09-18: run #10's log showed Pacific Beach Coalition's agenda view
    rendering fine -- 4841 chars, the exact same size as run #7's, which DID
    extract 30 events from what was confirmed to be the same real calendar
    content -- yet this run's extraction came back with 0 raw events. Since
    nothing in this function or its caller changed between those two runs,
    and the source text was substantively the same real content both times,
    the most likely explanation is a one-off miss in the model's own
    response for that call, not a structural bug -- these are inherently a
    little stochastic, and a forced tool call can occasionally come back
    genuinely (if incorrectly) empty. Rather than trying to root-cause a
    single non-reproducible bad response further, treat "0 events from a
    substantial amount of source text" as suspicious enough to retry once,
    the same way the PBC page-load timeout gets one retry -- cheap
    insurance against a whole org silently coming back empty for a week
    over what was probably just a bad roll. Also log more than the previous
    200-char preview when this happens, so a *repeat* failure (a real
    content/prompt problem, not a fluke) is diagnosable from the log alone
    next time instead of requiring this level of run-log archaeology again.
    """
    events = _claude_extract_events_once(client, org_name, source_text, extra_context)
    if not events and len(source_text) >= _EXTRACTION_RETRY_MIN_SOURCE_CHARS:
        log(f"  ! extraction returned 0 events from {len(source_text)} chars of source text "
            f"for {org_name} -- retrying once in case that was a one-off miss "
            f"(source text starts: {source_text[:500]!r})")
        events = _claude_extract_events_once(client, org_name, source_text, extra_context)
        if not events:
            log(f"  ! retry also returned 0 events for {org_name} -- likely a real "
                f"content/prompt issue this time, not a fluke")
    return events


def compute_day_name(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%A")
    except ValueError:
        return ""


_geocode_cache = {}


def _nominatim_lookup(query):
    resp = requests.get(
        NOMINATIM_URL,
        params={"q": query, "format": "json", "limit": 1, "countrycodes": "us"},
        headers=HTTP_HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    results = resp.json()
    time.sleep(1)  # be a good citizen of a free shared service -- max 1 req/sec
    if results:
        return float(results[0]["lat"]), float(results[0]["lon"])
    return None


def _build_geocode_attempts(location_text):
    """Build an ordered list of (label, query) attempts to try against
    Nominatim for a single location string. Most-specific first, broadest
    last -- stop at the first one that resolves.

    Run #7's log showed exactly why a single "loosen to last 2 segments"
    fallback isn't enough: for
    "Pacifica State Beach, 1416 9th St, California 95814, United States"
    (a genuinely corrupted address -- 95814 is a Sacramento zip code, not
    Pacifica's -- an artifact of how the source text got extracted), the
    last-2-segments fallback produces "California 95814, United States",
    which drops the city entirely and still fails. Verified live against
    Nominatim's own API that the fix isn't a smarter loosening of THIS
    address -- it's using the venue name alone: "Pacifica State Beach, CA"
    resolves immediately to the actual beach. Same result for "Montara State
    Beach, CA" (another of that run's failures). Named parks/beaches are
    already in OpenStreetMap's database under their own name, so when the
    surrounding address text is noisy or wrong, the venue name by itself is
    often *more* reliable than trying to fix the address around it."""
    attempts = []
    full = location_text
    def with_usa(s):
        # Append ", USA" only if the string doesn't already end in something
        # that names the country -- joining segments that already include a
        # trailing "USA" segment (common once the source address is fully
        # qualified) was otherwise producing queries like "...CA 94015, USA,
        # USA". Harmless to Nominatim either way, but noisy and worth doing
        # properly.
        return s if "usa" in s.lower() else f"{s}, USA"

    if not any(tok in full.lower() for tok in ("ca", "california", "usa")):
        full = with_usa(full)
    attempts.append(("full text", full))

    parts = [p.strip() for p in location_text.split(",") if p.strip()]

    if len(parts) > 1:
        # Last 3 segments -- catches "<street>, <city>, <state> <zip>, USA"
        # shapes where the last-2 fallback below would drop the city and
        # keep only the state/zip.
        if len(parts) > 2:
            attempts.append(("last 3 segments", with_usa(", ".join(parts[-3:]))))

        # Last 2 segments -- typically "<city>, <state>". Tried before
        # "venue name only" below: this still keeps the city, which matters
        # a lot -- see the Redwood City incident in the note below.
        attempts.append(("last 2 segments", with_usa(", ".join(parts[-2:]))))

        # Venue name alone (first segment) + state -- catches corrupted or
        # overly-specific addresses where the place name itself is what's
        # actually in the map database (e.g. "Pacifica State Beach, CA").
        # Run #9's log caught why this can't be tried before the
        # city-preserving fallbacks above, and why it must be skipped
        # entirely when the first segment is a numbered street address
        # rather than an actual place name: for "1400 Broadway St, Redwood
        # City, CA 94063", "1400 Broadway St, CA, USA" doesn't fail -- it
        # resolves to a DIFFERENT, wrong Broadway St in Santa Monica/LA
        # (34.0228, -118.4839), silently. A wrong-but-successful geocode is
        # worse than a failed one, since nothing downstream flags it. Live
        # Nominatim checks confirmed: the full address (even with ", USA"
        # appended) returns zero results for that address, but "Redwood
        # City, CA 94063, USA" (the last-2-segments attempt) correctly
        # resolves to Redwood City. So: only offer "venue name only" when
        # the first segment doesn't start with a digit -- a real venue name
        # never does, and a bare street number+name is too ambiguous to
        # geocode without its city.
        if not re.match(r"^\d", parts[0]):
            attempts.append(("venue name only", f"{parts[0]}, CA, USA"))

    # De-duplicate (case-insensitive) while preserving order -- short
    # addresses can make several of the above identical.
    seen = set()
    deduped = []
    for label, q in attempts:
        qkey = q.lower()
        if qkey not in seen:
            seen.add(qkey)
            deduped.append((label, q))
    return deduped


def geocode(location_text):
    """Resolve a location string to (lat, lng). Order of attempts:
      1. LOCATION_OVERRIDES -- known recurring sites we've manually verified.
      2. A series of Nominatim (OpenStreetMap) queries built by
         _build_geocode_attempts(), from most-specific (the full address) to
         broadest (city + state) -- see that function's docstring for why
         more than one fallback shape is needed.
    Returns (None, None) if nothing worked, so the caller can skip the event
    rather than plot a wrong or fabricated pin."""
    if not location_text:
        return None, None
    key = location_text.strip().lower()
    if key in _geocode_cache:
        return _geocode_cache[key]

    for needle, coords in LOCATION_OVERRIDES.items():
        if needle in key:
            _geocode_cache[key] = coords
            return coords

    for label, query in _build_geocode_attempts(location_text):
        try:
            result = _nominatim_lookup(query)
        except Exception as e:
            log(f"  ! geocoding attempt ({label}) failed for '{location_text}': {e}")
            continue
        if result:
            if label != "full text":
                log(f"  (geocoded '{location_text}' via {label}: '{query}')")
            _geocode_cache[key] = result
            return result

    # Don't log the overall failure here -- the caller (main()) already logs
    # "could not geocode '<location>' -- skipping this event" for every
    # event this returns (None, None) for; logging it again here would just
    # duplicate that line.
    _geocode_cache[key] = (None, None)
    return None, None


def slugify_for_log(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


# 2026-09-18e: the site-name -> form-link word-matching approach that used
# to live here (_extract_site_form_links / _match_site_form_link, plus the
# _SITE_FORM_STOPWORDS/_SITE_ANCHOR_STOPWORDS machinery around it) is gone.
# The site owner walked through the calendar by hand and showed that PBC's real
# registration links don't come from the small site->form table on the
# calendar page at all -- they're embedded directly in each individual
# Google Calendar EVENT's own description (click an event, there's a
# "Register online to volunteer" link right there), which the table-matching
# approach never had access to and could only approximate by fuzzy word
# overlap. That approximation was real work (see the CHANGELOG entries this
# replaces) but it was solving the wrong problem: matching against a
# generic ~11-row table of recurring sites, when the actual authoritative,
# per-EVENT link was sitting one click away the whole time -- confirmed
# live for "Calera Creek Habitat Restoration" (an event that was never in
# that table and always correctly came back with no link) and matches the
# exact real form URL the site owner copied out by hand. See
# _extract_registration_link_from_description() and
# fetch_google_calendar_events_via_api() below for the real mechanism.


def _decode_google_url_shim(href):
    """Google Calendar's own rich-text description editor wraps a pasted
    link in its own https://www.google.com/url?q=<real-url>&... redirect
    shim -- confirmed live that this is baked into the raw description text
    Google's API itself returns, not just something the embed widget adds
    at render time. Decode straight to the real target instead of depending
    on that redirect service behaving the same way for a plain server-side
    request with no browser session behind it."""
    from urllib.parse import urlparse, parse_qs

    parsed = urlparse(href)
    if parsed.netloc in ("www.google.com", "google.com") and parsed.path == "/url":
        qs = parse_qs(parsed.query)
        q = qs.get("q")
        if q:
            return q[0]
    return href


_REGISTRATION_LINK_KEYWORDS = re.compile(r"\b(register|registration|sign[\s-]?up|rsvp|volunteer)\b", re.I)
_KNOWN_SIGNUP_DOMAINS = re.compile(
    r"(docs\.google\.com/forms|forms\.gle|eventbrite\.com|signupgenius\.com|surveymonkey\.com)", re.I
)


def _extract_registration_link_from_description(description_html):
    """Find the real, event-specific sign-up link inside a Google Calendar
    event's own description HTML, if one is there.

    Live-confirmed (Pacific Beach Coalition, Surfrider) that every org here
    wraps its registration link in a "friendly" anchor like
    '<a href="...">Register online to volunteer</a>' or
    '<a href="..."><b>REGISTER HERE</b></a>' -- note the second one nests a
    <b> tag INSIDE the <a>, so a naive "<a[^>]*>([^<]*)</a>" pattern (which
    stops at the first '<') never matches it at all; this one captures
    everything up to the closing </a> non-greedily and strips inner tags
    from the captured text afterward instead. Scores each link in the
    description by whether its visible text looks like a registration
    prompt and/or its target is a known sign-up-form domain, and returns
    the best-scoring one -- or None if nothing scores, same "never invent a
    link" principle as the rest of this pipeline."""
    if not description_html:
        return None
    import html as html_module

    candidates = []
    for m in re.finditer(r'<a\s+[^>]*href="([^"]*)"[^>]*>(.*?)</a>', description_html, re.I | re.S):
        href, inner_html = m.group(1), m.group(2)
        text = re.sub(r"<[^>]+>", " ", inner_html)
        text = html_module.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        target = _decode_google_url_shim(html_module.unescape(href))
        score = 0
        if _REGISTRATION_LINK_KEYWORDS.search(text):
            score += 2
        if _KNOWN_SIGNUP_DOMAINS.search(target):
            score += 1
        if score > 0:
            candidates.append((score, target))
    if not candidates:
        return None
    candidates.sort(key=lambda c: -c[0])
    return candidates[0][1]


# A few Pacific Beach Coalition events whose Google Calendar entry has no
# usable location text at all -- confirmed live via the Calendar API: the
# structured `location` field is empty (or, for one event, a bare
# maps.app.goo.gl link with no address text, handled separately below by
# reading the description's own "Where to Meet:" line first), and there's
# no "Where to Meet:" fallback in the description either. These are
# recurring, named sites we already know the general area of from this
# org's own site -- falls back to this ONLY after both the API location
# field and the description's "Where to Meet:" line come up empty, and
# still goes through the normal geocode() fallback chain like any other
# location string (not a hardcoded coordinate), so a bad guess here still
# can't silently plot a wrong pin the way LOCATION_OVERRIDES could.
_PBC_EVENT_NAME_LOCATION_FALLBACKS = [
    (re.compile(r"foster city", re.I), "Foster City, CA"),
    (re.compile(r"mussel rock", re.I), "Mussel Rock, Daly City, CA"),
    (re.compile(r"linda mar", re.I), "Linda Mar, Pacifica, CA"),
    (re.compile(r"coastal cleanup day", re.I), "Pacifica, CA"),
]

_WHERE_TO_MEET_RE = re.compile(r"Where to Meet:\s*([^<\n]+)", re.I)


def _pick_event_location(item):
    """Best available location text for one Calendar API event item.

    Order of attempts:
      1. The structured `location` field, if it's real text (not empty,
         not itself a bare URL -- confirmed live that Pacific Beach
         Coalition sometimes puts a maps.app.goo.gl short link there
         instead of an address, e.g. for "Calera Creek Habitat
         Restoration", which geocode() obviously can't do anything with).
      2. A "Where to Meet: ..." line inside the event's own description,
         if present (confirmed live: that's exactly where Calera Creek's
         real address-like text actually lives, since its `location` field
         is just the maps link above).
      3. A small set of known-recurring-site name fallbacks for the
         handful of events that have neither (see
         _PBC_EVENT_NAME_LOCATION_FALLBACKS above)."""
    loc = (item.get("location") or "").strip()
    if loc and not re.match(r"^https?://", loc):
        return loc

    description = item.get("description") or ""
    m = _WHERE_TO_MEET_RE.search(description)
    if m:
        import html as html_module

        return html_module.unescape(m.group(1)).strip()

    name = item.get("summary") or ""
    for pattern, fallback_loc in _PBC_EVENT_NAME_LOCATION_FALLBACKS:
        if pattern.search(name):
            return fallback_loc

    return loc  # possibly still empty or a bare URL -- geocode() will cleanly skip it, same as any event with no usable location today


def _format_ampm(dt):
    """'9:00 AM' style -- matches the "H:MM AM/PM" convention the rest of
    this pipeline already uses (previously produced by Claude's own
    extraction), so output looks identical whichever path an event came
    through."""
    return dt.strftime("%I:%M %p").lstrip("0")


def _google_calendar_item_to_raw_event(item):
    """Convert one Calendar API v3 event item into this script's normal raw
    event dict shape (the same shape claude_extract_events() produces), so
    everything downstream in main() -- date filtering, geocoding, bookingUrl
    verification -- works unchanged regardless of which path an event came
    through."""
    if item.get("status") == "cancelled":
        return None
    name = (item.get("summary") or "").strip()
    if not name:
        return None

    start = item.get("start") or {}
    end = item.get("end") or {}
    if "date" in start:
        # All-day event (e.g. "CA Coastal Cleanup Day") -- no specific time.
        date_str = start["date"]
        start_str = "All day"
        end_str = None
    elif "dateTime" in start:
        start_dt = datetime.fromisoformat(start["dateTime"])
        date_str = start_dt.strftime("%Y-%m-%d")
        start_str = _format_ampm(start_dt)
        end_str = None
        if "dateTime" in end:
            end_str = _format_ampm(datetime.fromisoformat(end["dateTime"]))
    else:
        return None

    return {
        "name": name,
        "date": date_str,
        "start": start_str,
        "end": end_str,
        "location": _pick_event_location(item),
        "bookingUrl": _extract_registration_link_from_description(item.get("description")),
    }


GOOGLE_CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"


def fetch_google_calendar_events_via_api(calendar_id, time_min, time_max):
    """Pull this calendar's events directly from Google's own public
    Calendar API v3 (read-only, via GOOGLE_CALENDAR_API_KEY) instead of
    scraping the embed widget's rendered HTML or its ICS/agenda-view
    fallbacks. Structured JSON, not text a model has to interpret -- exact
    dates/times/locations, and each event's own real registration link
    straight from its description field (see
    _extract_registration_link_from_description), instead of trying to
    reconstruct it after the fact from a table or free text. This is the
    officially documented public endpoint (developers.google.com/workspace/
    calendar/api/v3/reference/events/list) -- requires the calendar's own
    sharing settings to have "Make available to public" / "See all event
    details" turned on, which both Surfrider's and Pacific Beach
    Coalition's calendars already do (confirmed live: that's the same
    setting that lets their public embed widgets show full event details
    to anonymous visitors today)."""
    from urllib.parse import quote

    url = f"{GOOGLE_CALENDAR_API_BASE}/calendars/{quote(calendar_id, safe='')}/events"
    params = {
        "singleEvents": "true",
        "orderBy": "startTime",
        "timeZone": "America/Los_Angeles",
        "maxResults": 250,
        "timeMin": time_min,
        "timeMax": time_max,
        "key": GOOGLE_CALENDAR_API_KEY,
    }
    resp = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json().get("items", [])


def process_google_calendar_org(client, org_cfg):
    page_html = http_get(org_cfg["calendar_page"])
    cal_id = extract_google_calendar_id(page_html)
    if not cal_id:
        # The iframe is probably injected by client-side JS on this site rather
        # than present in the raw server HTML (confirmed to be the case for at
        # least one org this way) -- render it with a real browser and retry.
        page_html = render_with_playwright(org_cfg["calendar_page"])
        cal_id = extract_google_calendar_id(page_html)
    if not cal_id:
        log(f"  ! could not find a Google Calendar id on {org_cfg['calendar_page']} "
            f"even after a rendered-browser fetch -- the page structure may have "
            f"changed more substantially and needs a human look")
        return []

    if GOOGLE_CALENDAR_API_KEY:
        try:
            today = date.today()
            # Wrapped a day wider on each side than we actually need -- main()
            # re-filters to the exact date range afterward anyway, this just
            # guards against a UTC/Pacific timezone boundary off-by-one.
            time_min = (today - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
            time_max = (today + timedelta(days=LOOKAHEAD_DAYS + 1)).strftime("%Y-%m-%dT00:00:00Z")
            items = fetch_google_calendar_events_via_api(cal_id, time_min, time_max)
            raw_events = [ev for item in items if (ev := _google_calendar_item_to_raw_event(item))]
            with_links = sum(1 for ev in raw_events if ev.get("bookingUrl"))
            log(f"  fetched {len(raw_events)} event(s) directly from the Google Calendar API "
                f"({with_links} with their own real registration link) -- no AI extraction needed")
            return raw_events
        except Exception as e:
            log(f"  ! Google Calendar API fetch failed ({e}) -- falling back to the "
                f"older AI-extraction pipeline for this run")
            # falls through to the pipeline below
    else:
        log("  (GOOGLE_CALENDAR_API_KEY not set -- using the older AI-extraction pipeline; "
            "add that secret for exact structured data straight from Google instead, see the "
            "2026-09-18e CHANGELOG entry above)")
    try:
        source_text = fetch_google_calendar_ics(cal_id)
    except requests.RequestException as e:
        # Some calendars have public *embedding* enabled without public *iCal
        # export* enabled -- those are two separate sharing settings in Google
        # Calendar, and a site owner can easily turn on the first without the
        # second. Confirmed this is exactly what's happening for Pacific Beach
        # Coalition: the embed shows real events, but /public/basic.ics 404s.
        log(f"  ! iCal export failed for this calendar ({e}) -- falling back to its agenda view")
        source_text = render_google_calendar_agenda(cal_id)

    raw_events = claude_extract_events(client, org_cfg["org"], source_text)
    log(f"  Claude extracted {len(raw_events)} raw event(s) (before date filtering/geocoding)")
    return raw_events


_URL_DATE_RE = re.compile(r'/(20\d{2})/(\d{2})/(\d{2})/')


def _find_detail_urls(listing_page, listing_html, pattern, max_details=15):
    """Resolve whatever the pattern matches against the listing page's own URL --
    a no-op for an already-absolute match (e.g. Save The Bay), but required for
    a site like Grassroots Ecology whose event links are relative paths.

    A listing page often keeps past events linked alongside upcoming ones (run
    #4's log showed Grassroots Ecology's 15 matches were the 15
    *chronologically earliest* event pages on the whole page -- since the date
    is embedded in the URL, sorting the raw strings put a bunch of already-past
    events ahead of upcoming ones, and every single one of the 7 events Claude
    did extract got silently dropped by main()'s today<=date<=cutoff check).
    When a URL embeds a YYYY/MM/DD date, drop anything clearly in the past and
    sort what's left soonest-first before capping to 15, so the cap actually
    keeps the *next* 15 events rather than the *earliest-ever-linked* 15. Falls
    back to plain alphabetical sort for URLs with no embeddable date (e.g. Save
    The Bay's slug-only event URLs)."""
    from urllib.parse import urljoin

    matches = re.findall(pattern, listing_html)
    resolved = {urljoin(listing_page, m) for m in matches}

    today_str = date.today().isoformat().replace("-", "")  # e.g. "20260910"

    def sort_key(u):
        m = _URL_DATE_RE.search(u)
        if not m:
            return (1, u)  # no date in the URL -- sort after dated ones, alphabetically
        y, mo, d = m.groups()
        return (0, f"{y}{mo}{d}")

    def is_past(u):
        m = _URL_DATE_RE.search(u)
        if not m:
            return False  # can't tell -- don't drop it
        y, mo, d = m.groups()
        return f"{y}{mo}{d}" < today_str

    future_or_unknown = [u for u in resolved if not is_past(u)]
    dropped = len(resolved) - len(future_or_unknown)
    if dropped:
        log(f"  dropped {dropped} detail link(s) whose URL date is already in the past")
    return sorted(future_or_unknown, key=sort_key)[:max_details]


def process_html_listing_org(client, org_cfg):
    listing_html = http_get(org_cfg["listing_page"])
    log(f"  fetched listing page: {len(listing_html)} chars (plain HTTP)")
    detail_urls = _find_detail_urls(org_cfg["listing_page"], listing_html, org_cfg["detail_link_pattern"], org_cfg.get("max_details", 15))
    log(f"  detail-link regex found {len(detail_urls)} match(es) in the plain fetch")

    if not detail_urls:
        # As with the calendar embeds, this listing may render its event links
        # via client-side JS -- retry with a rendered fetch before giving up.
        listing_html = render_with_playwright(org_cfg["listing_page"])
        log(f"  re-fetched via Playwright: {len(listing_html)} chars")
        detail_urls = _find_detail_urls(org_cfg["listing_page"], listing_html, org_cfg["detail_link_pattern"], org_cfg.get("max_details", 15))
        log(f"  detail-link regex found {len(detail_urls)} match(es) after rendering")

    log(f"  found {len(detail_urls)} detail page(s)")

    if not detail_urls:
        # No detail pages at all -- fall back to extracting straight from the
        # listing page's own text so a broken detail-link pattern degrades to
        # "no bookingUrl" rather than "no events".
        raw_events = claude_extract_events(
            client, org_cfg["org"], f"--- LISTING PAGE ({org_cfg['listing_page']}) ---\n{(html_to_text(listing_html) or listing_html)[:20000]}\n"
        )
        log(f"  Claude extracted {len(raw_events)} raw event(s) from the listing page alone "
            f"(before date filtering/geocoding)")
        return raw_events

    # One Claude call PER detail page rather than one call across all of them
    # combined. The site owner reported (2026-09-18) that Grassroots Ecology's events
    # were coming through with no bookingUrl at all, unlike Save The Bay's --
    # the difference: when every detail page's text is blended into a single
    # blob and Claude is asked to extract every event at once, matching each
    # event back to the one URL among several that it actually came from is
    # an inference Claude has to get right on its own, and evidently wasn't
    # for this org. Processing one page at a time removes that inference
    # entirely: whatever event(s) come out of THIS call can only have come
    # from THIS url, so bookingUrl is set programmatically afterward, not
    # trusted from the model's own output. This also directly delivers what
    # the site owner asked for -- each event's "I will help!" button goes to that
    # event's own page on the org's site (e.g.
    # https://www.grassrootsecology.org/event-calendar/2026/09/19/coastal-
    # cleanup-day-redwood-city), the same "volunteer tab" they described
    # clicking through to by hand.
    raw_events = []
    for url in detail_urls:
        try:
            detail_html = http_get(url)
        except Exception as e:
            log(f"  ! failed to fetch detail page {url}: {e}")
            continue
        source_text = (
            f"--- LISTING PAGE ({org_cfg['listing_page']}), for date/context only ---\n"
            f"{listing_html[:8000]}\n"
            f"\n--- DETAIL PAGE ({url}) -- this describes exactly ONE event ---\n"
            f"{detail_html[:8000]}\n"
        )
        try:
            page_events = claude_extract_events(client, org_cfg["org"], source_text)
        except Exception as e:
            log(f"  ! Claude extraction failed for detail page {url}: {e}")
            continue
        for ev in page_events:
            if isinstance(ev, dict):
                ev["bookingUrl"] = url
        raw_events.extend(page_events)

    log(f"  Claude extracted {len(raw_events)} raw event(s) from {len(detail_urls)} detail page(s), "
        f"one call per page (before date filtering/geocoding)")
    return raw_events


def process_text_page_org(client, org_cfg):
    """For a page that lists dates in its own text and has no per-event links to
    follow (or whose booking platform we can't identify): fetch it, reduce it to
    text, and let Claude extract the events. Tries a plain fetch first and a
    headless browser if the plain page has almost no text (JavaScript calendar).
    org_cfg may carry "extra_context" (instructions for Claude) and
    "booking_url" (used for events that have no event-specific link)."""
    page = org_cfg["source_page"]
    text = ""
    try:
        text = html_to_text(http_get(page))
        log(f"  fetched {page}: {len(text)} chars of text (plain HTTP)")
    except Exception as e:
        log(f"  plain fetch of {page} failed: {e}")
    if len(text) < 500:
        rendered = html_to_text(render_with_playwright(page))
        log(f"  rendered fetch: {len(rendered)} chars of text")
        text = rendered if len(rendered) > len(text) else text
    if not text:
        log("  ! no page text available -- 0 events")
        return []
    raw_events = claude_extract_events(
        client, org_cfg["org"], f"--- PAGE ({page}) ---\n{text[:30000]}\n",
        extra_context=org_cfg.get("extra_context", ""),
    )
    default_url = org_cfg.get("booking_url")
    for ev in raw_events:
        if isinstance(ev, dict) and not ev.get("bookingUrl") and default_url:
            ev["bookingUrl"] = default_url
    log(f"  Claude extracted {len(raw_events)} raw event(s) from the page text")
    return raw_events


def process_weekly_recurring_org(client, org_cfg):
    """A fixed weekly event (same weekday and time every week), written as a rule
    in the config instead of read from a page. Produces one event per week for
    the lookahead window; main() applies the usual date filter."""
    weekday = _WEEKDAY_NAMES.index(org_cfg["weekday"])
    day = date.today()
    day += timedelta(days=(weekday - day.weekday()) % 7)
    events = []
    while day <= date.today() + timedelta(days=LOOKAHEAD_DAYS):
        events.append({
            "name": org_cfg["event_name"],
            "date": day.isoformat(),
            "start": org_cfg["start"],
            "end": org_cfg.get("end"),
            "location": org_cfg["location"],
            "bookingUrl": org_cfg.get("booking_url"),
        })
        day += timedelta(days=7)
    log(f"  weekly rule ({org_cfg['weekday']}s): {len(events)} occurrence(s) in the next {LOOKAHEAD_DAYS} days")
    return events


# Matches the REAL raw markup (confirmed 2026-10-15 by fetching the live page's
# source, after run #23 showed "site-table regex found 0 row(s)"):
#   <tr><td><strong>Rockaway Beach Cleanup</strong>, Pacifica <a href="...">More
#   info about this cleanup</a></td><td><a href="...">VOLUNTEER &gt;</a></td></tr>
# i.e. only the site NAME is bold and the "More info" link sits directly in the
# cell, NOT inside the <strong>. (The first version of this pattern assumed the
# link was inside <strong>, which is how the page looked in the browser's DOM
# view but not how the server actually sends it.) Tested against all 11 real
# rows. The name group is cleaned of tags/entities in process_pbc_site_table_org().
PBC_ROW_RE = re.compile(
    r'<tr>\s*<td>\s*(?P<name>(?:(?!</td>).)*?)\s*<a[^>]*href="(?P<detail_url>[^"]+)"[^>]*>.*?</a>\s*</td>\s*'
    r'<td>\s*<a[^>]*href="(?P<form_url>[^"]+)"[^>]*>.*?</a>\s*</td>\s*</tr>',
    re.S,
)

_ORDINAL_WORDS = {
    "first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3,
    "fourth": 4, "4th": 4, "fifth": 5, "5th": 5, "last": -1,
}
_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

RECORD_SITE_RECURRENCE_TOOL = {
    "name": "record_site_recurrence",
    "description": "Record this cleanup site's recurring schedule rule, since no explicit upcoming dates are listed on the page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ordinal": {
                "type": "string",
                "enum": ["first", "second", "third", "fourth", "fifth", "last"],
                "description": "Which occurrence of the weekday in the month, per the page's 'Time:' sentence.",
            },
            "weekday": {
                "type": "string",
                "enum": _WEEKDAY_NAMES,
                "description": "The day of the week the cleanup recurs on.",
            },
            "start": {"type": "string", "description": "Start time, e.g. '9:00 AM'"},
            "end": {"type": ["string", "null"], "description": "End time, e.g. '11:00 AM', or null if not stated"},
            "location": {"type": "string", "description": "The most specific 'Where to Meet' address/venue text on the page"},
        },
        "required": ["ordinal", "weekday", "start", "location"],
    },
}


def _extract_site_recurrence_rule(client, site_name, detail_html):
    """Used only when claude_extract_events() found no explicit dates on a
    site's page (e.g. the page only says "First Saturday of the month...,
    check our calendar" with no literal upcoming dates to extract) -- asks
    Claude to read off the recurrence rule as plain text/enum fields (no date
    math from the model), which _dates_for_recurrence() below then turns into
    real calendar dates deterministically."""
    system = (
        "You read a Pacific Beach Coalition cleanup site's page and report its recurring "
        "schedule rule exactly as stated near a line starting with 'Time:' (e.g. 'First "
        "Saturday of the month from 9am-11am'), plus the most specific meeting location from "
        "a line starting with 'Where to Meet:'. Call record_site_recurrence exactly once."
    )
    user_content = f"Site: {site_name}\n\n--- PAGE TEXT/HTML ---\n{detail_html[:12000]}\n--- END ---"
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system,
        tools=[RECORD_SITE_RECURRENCE_TOOL],
        tool_choice={"type": "tool", "name": "record_site_recurrence"},
        messages=[{"role": "user", "content": user_content}],
    )
    for block in resp.content:
        if block.type == "tool_use" and block.name == "record_site_recurrence":
            return block.input
    return None


def _dates_for_recurrence(ordinal, weekday, start_date, end_date):
    """Every real calendar date matching 'Nth <weekday> of the month' (or
    'last <weekday>') between start_date and end_date inclusive, computed in
    plain Python -- deliberately NOT asked of the model, which is not
    reliable at date arithmetic."""
    import calendar as _calendar

    weekday_idx = _WEEKDAY_NAMES.index(weekday)  # Monday=0 .. Sunday=6
    ordinal_n = _ORDINAL_WORDS.get(str(ordinal).lower())
    if ordinal_n is None:
        return []

    dates = []
    year, month = start_date.year, start_date.month
    while (year, month) <= (end_date.year, end_date.month):
        month_days = _calendar.monthrange(year, month)[1]
        matches = [d for d in range(1, month_days + 1)
                   if date(year, month, d).weekday() == weekday_idx]
        if matches:
            picked = matches[ordinal_n - 1] if ordinal_n > 0 else matches[-1]
            candidate = date(year, month, picked)
            if start_date <= candidate <= end_date:
                dates.append(candidate)
        month += 1
        if month > 12:
            month = 1
            year += 1
    return dates


def process_pbc_site_table_org(client, org_cfg):
    """2026-10-14: Google Calendar API, iCal export, AND the embed widget
    itself all started returning errors for PBC's calendar
    (pickituppacifica@gmail.com) -- confirmed live, in a real browser, on
    PBC's OWN website (pacificbeachcoalition.org/calendar-2026/), not just
    our scraper: the embed shows "Oops, we couldn't load your events, please
    try again in a few minutes" for both October and November 2026. That's an
    outage on Google/PBC's side, not a bug here -- all three of the old
    "google_calendar" fallbacks share that one underlying dependency, so none
    of them can route around it.

    PBC's own site has a second, independent data source that doesn't touch
    Google Calendar at all: a static table at listing_page with all 11
    cleanup sites, each with (a) a "More info" page describing that site's
    recurring schedule in plain text, and (b) that site's own direct Google
    Form sign-up link, right there in the table -- the real per-site
    registration links confirmed working, no description-matching guesswork
    needed this time.

    Most site pages list every upcoming date for the year explicitly (e.g.
    "October 3rd, 2026 November 7th, 2026 December 5th, 2026"), which the
    existing general-purpose claude_extract_events() already handles as-is
    (that's exactly what it's for) -- tried first, for every site. A few
    pages (confirmed: Rockaway Beach) give only a recurrence rule in prose
    ("First Saturday of the month from 9am-11am") with no literal dates on
    the page -- for those, _extract_site_recurrence_rule() reads the rule and
    _dates_for_recurrence() computes the real calendar dates in Python.
    """
    listing_html = http_get(org_cfg["listing_page"])
    log(f"  fetched site table page: {len(listing_html)} chars (plain HTTP)")

    rows = list(PBC_ROW_RE.finditer(listing_html))
    log(f"  site-table regex found {len(rows)} row(s)")
    if not rows:
        log("  ! no rows matched -- PBC's table markup may have changed, skipping this org for this run")
        return []

    today = date.today()
    cutoff = today + timedelta(days=LOOKAHEAD_DAYS)

    raw_events = []
    for m in rows:
        import html as _html
        site_name = re.sub(r"<[^>]+>", "", m.group("name"))  # drop <strong> etc.
        site_name = re.sub(r"\s+", " ", _html.unescape(site_name)).strip().rstrip(",").strip()
        detail_url = m.group("detail_url")
        form_url = m.group("form_url")

        try:
            detail_html = http_get(detail_url)
        except Exception as e:
            log(f"  ! failed to fetch site page for '{site_name}': {e}")
            continue

        # Tier 1: reuse the existing extractor as-is -- it already pulls
        # every explicit date out of a page's text, which is exactly what
        # most of these pages give it.
        site_events = claude_extract_events(client, f"Pacific Beach Coalition -- {site_name}", detail_html)
        valid_events = [ev for ev in site_events if isinstance(ev, dict)]
        if valid_events:
            for ev in valid_events:
                ev["bookingUrl"] = form_url  # the real per-site form link, not model-guessed
                ev.setdefault("name", site_name)  # the table's site name is already a full label, e.g. "Rockaway Beach Cleanup, Pacifica"
            log(f"  {site_name}: {len(valid_events)} explicit date(s) found on the page")
            raw_events.extend(valid_events)
            continue

        # Tier 2: no explicit dates on the page -- read the recurrence rule
        # instead and compute the actual upcoming dates ourselves.
        try:
            rule = _extract_site_recurrence_rule(client, site_name, detail_html)
        except Exception as e:
            log(f"  ! {site_name}: recurrence-rule extraction failed: {e}")
            continue
        if not rule:
            log(f"  ! {site_name}: no explicit dates and no recurrence rule found -- skipping")
            continue
        try:
            computed_dates = _dates_for_recurrence(rule["ordinal"], rule["weekday"], today, cutoff)
        except Exception as e:
            log(f"  ! {site_name}: failed to compute dates from recurrence rule {rule}: {e}")
            continue
        log(f"  {site_name}: no explicit dates listed -- computed {len(computed_dates)} date(s) "
            f"from '{rule['ordinal']} {rule['weekday']}' rule")
        for d in computed_dates:
            raw_events.append({
                "name": site_name,  # already a full label, e.g. "San Pedro Creek Cleanup, Pacifica"
                "date": d.isoformat(),
                "start": rule.get("start", ""),
                "end": rule.get("end"),
                "location": rule.get("location") or site_name,
                "bookingUrl": form_url,
            })

    log(f"  -> {len(raw_events)} raw event(s) across {len(rows)} site(s) (before date filtering/geocoding)")
    return raw_events


# --------------------------------------------------------------------------
# Direct readers (NO AI, so they cost nothing to run)
#
# Some sign-up systems publish their shifts as structured pages. Reading those
# pages with plain code is cheaper (free), faster and more exact than asking
# Claude to read them, so three kinds below parse the pages directly:
#
#   galaxy_calendar     SF-Marin Food Bank ("Get Connected" platform: a month
#                       calendar whose per-day lists come from /calendar/ajaxGetDay)
#   v4s_listing         St. Anthony's ("Volunteers for Salesforce" job listing page)
#   openhand_hotspots   Project Open Hand (a page of embedded Salesforce listings)
#
# All three skip shifts with 0 open slots, build the link to each shift's own
# page, and set the tags themselves. If a site changes its layout the reader
# raises an error, and main() then keeps that org's previous events rather than
# wiping them.
# --------------------------------------------------------------------------

REQUEST_PAUSE = float(os.environ.get("REQUEST_PAUSE", "0.3"))   # seconds between requests to one site


def _pause():
    if REQUEST_PAUSE > 0:
        time.sleep(REQUEST_PAUSE)


def fetch_text(url, params=None, tries=3):
    """GET a page as text with a polite pause and a couple of retries."""
    last = None
    for attempt in range(tries):
        try:
            text = http_get(url, params=params) if params else http_get(url)
            _pause()
            return text
        except requests.RequestException as e:
            last = e
            if REQUEST_PAUSE > 0:
                time.sleep(min(2 * (attempt + 1), 6))
    raise last


def _strip_tags(s):
    s = re.sub(r"<(script|style|svg)\b.*?</\1>", " ", s or "", flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>", ", ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = _htmlmod.unescape(s).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def _time_12h(s):
    """'9:00am' / '9:00 AM' / '9 am' -> '9:00 AM' (the format the site expects), or ''."""
    m = re.fullmatch(r"\s*(\d{1,2})(?::(\d{2}))?\s*([AaPp])\.?[Mm]\.?\s*", s or "")
    if not m:
        return ""
    return f"{int(m.group(1))}:{m.group(2) or '00'} {m.group(3).upper()}M"


_MONTH_NUM = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def normalize_location(text, default_city=None):
    """Tidy an address for geocoding: collapse spaces, fix ' ,' gaps, drop floor
    and suite parts, and add a default city when the text has no state."""
    s = _htmlmod.unescape(text or "").replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+,", ",", s)
    s = re.sub(r",\s*,", ",", s)
    s = re.sub(r",?\s*\b(?:\d+(?:st|nd|rd|th)\s+floor|floor\s*\d+|suite\s*\w+|ste\.?\s*\w+)\b", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" ,")
    if default_city and s and not re.search(r"\b(CA|California)\b", s):
        s = f"{s}, {default_city}"
    return s


_WEEKDAY_ABBR = r"(?:MON|TUES?|WED|THURS?|FRI|SAT|SUN)"


def clean_shift_name(title):
    """'Marin Warehouse | WED Morning | 2026 Fall' -> 'Marin Warehouse - Morning'.
    Drops weekday tags and season labels, which are noise on the site."""
    parts = [p.strip() for p in re.split(r"\s*\|\s*", title or "") if p.strip()]
    keep = []
    for i, p in enumerate(parts):
        if re.fullmatch(r"(?:19|20)\d\d\s+(?:Spring|Summer|Fall|Autumn|Winter)", p, re.I):
            continue
        if i > 0:
            p = re.sub(rf"^{_WEEKDAY_ABBR}\b\.?\s*", "", p, flags=re.I).strip()
        if p:
            keep.append(p)
    return " - ".join(keep) if keep else (title or "").strip()


def fixed_tags(org_cfg, text):
    """Tags for the no-AI readers: the org's default_tags plus any tag_rules
    whose pattern matches the shift name. Only the vocabulary's own tags survive."""
    tags = list(org_cfg.get("default_tags", []))
    for pattern, extra in org_cfg.get("tag_rules", []):
        if re.search(pattern, text or "", re.I):
            tags += list(extra)
    groups = None if org_cfg.get("cause", "environment") == "environment" else NON_ENV_TAG_GROUPS
    return sanitize_tags(tags, groups)


# ---- SF-Marin Food Bank ("Get Connected" calendar) ------------------------

class _GalaxyRowParser(_HTMLParser):
    """Collects the <tr class="need"> rows of a day's opportunity list."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._row = None
        self._cell = None
        self._skip = 0
        self._in_title = False
        self._in_sub = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "tr" and re.search(r"\bneed\b", cls):
            self._row = {"cells": [], "title": "", "href": "", "subtitle": ""}
            return
        if self._row is None:
            return
        if tag == "td":
            self._cell = {"cls": cls, "text": []}
        elif tag in ("svg", "script", "style"):
            self._skip += 1
        elif tag == "a" and re.search(r"\btitle\b", cls) and not self._row["href"]:
            self._row["href"] = a.get("href") or ""
            self._in_title = True
        elif tag == "div" and "subtitle" in cls:
            self._in_sub = True

    def handle_endtag(self, tag):
        if self._row is None:
            return
        if tag in ("svg", "script", "style"):
            if self._skip:
                self._skip -= 1
        elif tag == "td" and self._cell is not None:
            self._row["cells"].append((self._cell["cls"], " ".join("".join(self._cell["text"]).split())))
            self._cell = None
        elif tag == "a":
            self._in_title = False
        elif tag == "div" and self._in_sub:
            self._in_sub = False
        elif tag == "tr":
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._row is None or self._skip:
            return
        if self._in_title:
            self._row["title"] += data
        elif self._in_sub:
            self._row["subtitle"] += data
        if self._cell is not None:
            self._cell["text"].append(data)


_GAL_DT_RE = re.compile(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),\s*(\d{4})\s*@\s*(\d{1,2}:\d{2}\s*[AaPp][Mm])")


def _parse_galaxy_dt(text):
    """'Nov 4, 2026 @ 9:00am' -> ('2026-11-04', '9:00 AM'), or None."""
    m = _GAL_DT_RE.search(text or "")
    if not m:
        return None
    month = _MONTH_NUM.get(m.group(1)[:3].lower())
    if not month:
        return None
    try:
        iso = date(int(m.group(3)), month, int(m.group(2))).isoformat()
    except ValueError:
        return None
    return iso, _time_12h(m.group(4))


def parse_galaxy_day_rows(entry_html):
    """One page of a day's opportunity list -> (shifts, number_of_rows_on_the_page).
    Each shift: title, subtitle, href, need_id, date, start, end, slots (open slots)."""
    p = _GalaxyRowParser()
    p.feed(entry_html or "")
    p.close()
    shifts = []
    for r in p.rows:
        cells = r["cells"]
        dt_idx = [i for i, (c, _t) in enumerate(cells) if "date-time" in c]
        m = re.search(r"need_id=(\d+)", r["href"])
        if len(dt_idx) < 2 or not m:
            continue
        start = _parse_galaxy_dt(cells[dt_idx[0]][1])
        end = _parse_galaxy_dt(cells[dt_idx[1]][1])
        if not start:
            continue
        slots = None
        for j in range(dt_idx[1] + 1, len(cells)):      # "Teams Allowed" comes first, then the number
            if re.fullmatch(r"\d+", cells[j][1]):
                slots = int(cells[j][1])
                break
        shifts.append({
            "title": " ".join(r["title"].split()),
            "subtitle": " ".join(r["subtitle"].split()),
            "href": r["href"],
            "need_id": m.group(1),
            "date": start[0],
            "start": start[1],
            "end": end[1] if end else "",
            "slots": slots,
        })
    return shifts, len(p.rows)


def fetch_galaxy_day(base, day):
    """Every shift on one calendar day (the list is paged, 10 per page)."""
    params = {"day": f"{day.day:02d}", "display_date": day.strftime("%A %B %d, %Y"), "calendar_type": "need"}
    shifts = []
    n_rows_total = 0
    for page in range(60):
        raw = fetch_text(f"{base}/calendar/ajaxGetDay/{page * 10}/", params=params)
        try:
            data = json.loads(raw)
        except ValueError:
            raise RuntimeError(f"{day} did not return JSON (the site layout may have changed)")
        listing = data.get("entryListHtml") if isinstance(data, dict) else None
        if not listing:
            break
        got, n_rows = parse_galaxy_day_rows(listing)
        shifts += got
        n_rows_total += n_rows
        if n_rows < 10:
            break
    return shifts, n_rows_total


def parse_galaxy_location(detail_html):
    """The address on an opportunity page: <table class="... location-info"> ... </table>."""
    m = re.search(r'<table[^>]*location-info[^>]*>(.*?)</table>', detail_html or "", re.S)
    if not m:
        return ""
    return normalize_location(_strip_tags(m.group(1)))


def process_galaxy_calendar_org(client, org_cfg):
    base = org_cfg["base_url"].rstrip("/")
    days = int(org_cfg.get("lookahead_days", LOOKAHEAD_DAYS))
    min_slots = int(org_cfg.get("min_slots", 1))
    today = date.today()
    seen = set()
    kept = []
    n_rows_all = 0
    n_parsed = 0
    n_no_slots_info = 0
    n_full = 0
    day_failures = 0
    for i in range(days + 1):
        d = today + timedelta(days=i)
        try:
            shifts, n_rows = fetch_galaxy_day(base, d)
        except Exception as e:
            day_failures += 1
            log(f"  ! could not read {d.isoformat()}: {e}")
            continue
        n_rows_all += n_rows
        n_parsed += len(shifts)
        for sh in shifts:
            if sh["slots"] is None:
                n_no_slots_info += 1
                continue
            if sh["slots"] < min_slots:
                n_full += 1
                continue
            key = (sh["need_id"], sh["date"], sh["start"])
            if key in seen:
                continue
            seen.add(key)
            kept.append(sh)
    if day_failures > max(2, (days + 1) // 4):
        raise RuntimeError(f"{day_failures} of {days + 1} days failed to load")
    if n_rows_all and n_parsed == 0:
        raise RuntimeError("rows found but none could be read; the page layout probably changed")
    if n_parsed and n_no_slots_info == n_parsed:
        raise RuntimeError("shifts found but no slot counts; the page layout probably changed")
    log(f"  read {n_rows_all} shift(s) over {days + 1} day(s): {len(kept)} with open slots, "
        f"{n_full} full (skipped), {n_no_slots_info} without a slot count (skipped)")

    locations = {}
    events = []
    for sh in kept:
        nid = sh["need_id"]
        if nid not in locations:
            try:
                locations[nid] = parse_galaxy_location(fetch_text(urljoin(base + "/", sh["href"])))
            except Exception as e:
                log(f"  ! could not read the page for need {nid}: {e}")
                locations[nid] = ""
        loc = locations[nid]
        if not loc:
            continue
        name = clean_shift_name(sh["title"])
        events.append({
            "name": name,
            "date": sh["date"],
            "start": sh["start"],
            "end": sh["end"] or None,
            "location": normalize_location(loc, org_cfg.get("default_city")),
            "bookingUrl": urljoin(base + "/", sh["href"]),
            "tags": fixed_tags(org_cfg, f"{name} {sh['subtitle']}"),
        })
    log(f"  {len(events)} event(s) with an address ({len(locations)} shift page(s) read)")
    return events


# ---- "Volunteers for Salesforce" listing pages (St. Anthony's, Open Hand) ----

_V4S_DATE_RE = re.compile(
    r"'((?:Sun|Mon|Tues|Wednes|Thurs|Fri|Satur)day)\s+(\d{1,2})/(\d{1,2})/(\d{4})\s+"
    r"(\d{1,2}:\d{2}\s*[AP]M)(?:\s*-\s*(\d{1,2}:\d{2}\s*[AP]M))?[^']*'")


def parse_v4s_listing(page_html):
    """A Volunteers-for-Salesforce job listing page -> a list of jobs:
    {name, address, shifts: [{date, start, end, confirmed, available, job_id, shift_id}]}."""
    jobs = []
    chunks = re.split(r'class="cssJobName"[^>]*>', page_html or "")
    for chunk in chunks[1:]:
        name = _strip_tags(chunk.split("</span>", 1)[0])
        am = re.search(r'class="cssJobLocationAddress"[^>]*>(.*?)</p>', chunk, re.S)
        address = normalize_location(_strip_tags(am.group(1))) if am else ""
        shifts = []
        for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", chunk, re.S):
            cm = re.search(r"confirmed:\s*(\d+)\s*-\s*available:\s*(\d+)", row)
            dm = _V4S_DATE_RE.search(row)
            if not cm or not dm:
                continue
            try:
                iso = date(int(dm.group(4)), int(dm.group(2)), int(dm.group(3))).isoformat()
            except ValueError:
                continue
            im = re.search(r"OpenSignUpDlg\('([^']+)',\s*'([^']+)'", row)
            shifts.append({
                "date": iso,
                "start": _time_12h(dm.group(5)),
                "end": _time_12h(dm.group(6)) if dm.group(6) else "",
                "confirmed": int(cm.group(1)),
                "available": int(cm.group(2)),
                "job_id": im.group(1) if im else "",
                "shift_id": im.group(2) if im else "",
            })
        jobs.append({"name": name, "address": address, "shifts": shifts})
    return jobs


def _v4s_shift_link(base, shift):
    """The same link the St. Anthony's calendar uses for one shift."""
    if not (shift["job_id"] and shift["shift_id"]):
        return None
    y, mo, d = shift["date"].split("-")
    m = re.match(r"(\d{1,2}):(\d{2})\s*([AP])M", shift["start"] or "")
    hour, minute = 0, 0
    if m:
        hour = int(m.group(1)) % 12 + (12 if m.group(3) == "P" else 0)
        minute = int(m.group(2))
    return (f"{base}?Calendar=1&volunteerShiftId={shift['shift_id']}&jobId={shift['job_id']}"
            f"&dtMonthFilter={int(y)}-{int(mo)}-{int(d)}%20{hour}:{minute}:0&nDaysToShow=1&ShowNumberAvailable=1")


def process_v4s_listing_org(client, org_cfg):
    base = org_cfg["listing_base"]
    days = int(org_cfg.get("lookahead_days", LOOKAHEAD_DAYS))
    page = fetch_text(f"{base}?nDaysToShow={days}&ShowNumberAvailable=1")
    jobs = parse_v4s_listing(page)
    if not jobs:
        raise RuntimeError("no jobs found on the listing page; the layout probably changed")
    today = date.today()
    events = []
    n_shifts = n_open = 0
    for job in jobs:
        for sh in job["shifts"]:
            n_shifts += 1
            if sh["available"] < 1 or sh["date"] < today.isoformat():
                continue
            n_open += 1
            if not job["address"]:
                continue
            events.append({
                "name": job["name"],
                "date": sh["date"],
                "start": sh["start"],
                "end": sh["end"] or None,
                "location": normalize_location(job["address"], org_cfg.get("default_city")),
                "bookingUrl": _v4s_shift_link(base, sh) or org_cfg.get("org_url"),
                "tags": fixed_tags(org_cfg, job["name"]),
            })
    if n_shifts == 0:
        raise RuntimeError("jobs found but no shifts parsed; the layout probably changed")
    log(f"  {len(jobs)} job(s), {n_shifts} shift(s), {n_open} with open slots -> {len(events)} event(s)")
    return events


# ---- Project Open Hand "Hot Spots" page --------------------------------------

def parse_hotspot_frames(page_html):
    """The Hot Spots page embeds one Salesforce listing per program, each under an
    <h2> heading and a 'Location: ...' line. -> [{program, location, src}]."""
    frames = []
    prev_end = 0
    for m in re.finditer(r'<iframe\b[^>]*\bsrc="([^"]*salesforce-sites\.com[^"]*)"', page_html or "", re.I):
        before = page_html[prev_end:m.start()]
        prev_end = m.end()
        heads = re.findall(r"<h2[^>]*>(.*?)</h2>", before, re.S | re.I)
        locs = re.findall(r"Location:\s*(?:<[^>]+>\s*)*([^<\n]+)", before, re.I)
        frames.append({
            "program": _strip_tags(heads[-1]) if heads else "",
            "location": _strip_tags(locs[-1]) if locs else "",
            "src": _htmlmod.unescape(m.group(1)),
        })
    return frames


def process_openhand_hotspots_org(client, org_cfg):
    frames = []
    try:
        frames = parse_hotspot_frames(fetch_text(org_cfg["source_page"]))
        if not frames:
            log("  ! no embedded listings found on the Hot Spots page; the layout probably changed")
    except requests.RequestException as e:
        # openhand.org answers 403 to the GitHub runner (run #29), although the
        # Salesforce listings it embeds are readable. Fall back to the listing
        # addresses written in the config.
        log(f"  ! could not read the Hot Spots page ({e})")
    if not frames and org_cfg.get("fallback_frames"):
        frames = [dict(f) for f in org_cfg["fallback_frames"]]
        log(f"  using the {len(frames)} listing address(es) saved in the config instead "
            f"(if Open Hand changes its Hot Spots listings, update fallback_frames)")
    if not frames:
        raise RuntimeError("no embedded listings found for Open Hand")
    today = date.today()
    events = []
    n_shifts = n_open = 0
    for fr in frames:
        loc = normalize_location(fr["location"], org_cfg.get("default_city"))
        short = re.sub(r"^(?:Prepare|Assemble)\s+", "", fr["program"]).strip()
        listing = fetch_text(urljoin(org_cfg["source_page"], fr["src"]))
        for job in parse_v4s_listing(listing):
            for sh in job["shifts"]:
                n_shifts += 1
                if sh["available"] < 1 or sh["date"] < today.isoformat():
                    continue
                n_open += 1
                if not loc:
                    continue
                name = f"{job['name']} ({short})" if short else job["name"]
                events.append({
                    "name": name,
                    "date": sh["date"],
                    "start": sh["start"],
                    "end": sh["end"] or None,
                    "location": loc,
                    "bookingUrl": org_cfg["source_page"],
                    "tags": fixed_tags(org_cfg, name),
                })
    if n_shifts == 0:
        raise RuntimeError("listings found but no shifts parsed; the layout probably changed")
    log(f"  {len(frames)} listing(s), {n_shifts} shift(s), {n_open} with open slots -> {len(events)} event(s)")
    return events


# ---- Second Harvest Food Bank of Silicon Valley (volunteer calendar feed) ----

def _clock_12h(s):
    """'09:00:00.000Z' / '13:30' -> '9:00 AM' / '1:30 PM'. The feed writes the
    LOCAL clock time with a trailing Z, so no timezone conversion is done."""
    m = re.match(r"\s*(\d{1,2}):(\d{2})", s or "")
    if not m:
        return ""
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return ""
    return f"{(h % 12) or 12}:{mi:02d} {'AM' if h < 12 else 'PM'}"


def _us_date_iso(s):
    """'10/26/2026' or '10/26/2026, 1:30 PM' -> '2026-10-26', or ''."""
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", s or "")
    if not m:
        return ""
    try:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
    except ValueError:
        return ""


def flatten_mmvfs_shifts(data):
    """Top-level shifts plus the sibling shifts nested inside each one (the
    1:30 pm shift of a day lives inside the 9 am shift), de-duplicated by id."""
    seen, out = set(), []
    for top in (data or {}).get("shifts") or []:
        if not isinstance(top, dict):
            continue
        for sh in [top] + [x for x in (top.get("shifts") or []) if isinstance(x, dict)]:
            sid = sh.get("shift_id")
            if sid and sid not in seen:
                seen.add(sid)
                out.append(sh)
    return out


def mmvfs_events(data, org_cfg, today):
    """Turn the feed into events: wanted job types, open slots, published, in the
    next lookahead_days. Returns (events, n_flattened)."""
    days = int(org_cfg.get("lookahead_days", LOOKAHEAD_DAYS))
    last = (today + timedelta(days=days)).isoformat()
    wanted = set(org_cfg.get("job_types") or [])
    page = org_cfg["shift_page"]
    shifts = flatten_mmvfs_shifts(data)
    events = []
    for sh in shifts:
        if wanted and sh.get("job_type") not in wanted:
            continue
        if not sh.get("published", True) or not sh.get("display_on_website", True):
            continue
        try:
            need = int(sh.get("volunteers_still_needed") or 0)
        except (TypeError, ValueError):
            need = 0
        if need < 1:
            continue
        iso = _us_date_iso(sh.get("start_date_time") or sh.get("date"))
        if not iso or iso < today.isoformat() or iso > last:
            continue
        loc = sh.get("location_data") or {}
        place = (loc.get("name") or "").strip()
        street = (loc.get("address") or "").strip()
        if not street:
            continue
        city = (loc.get("city") or sh.get("city") or "").strip()
        zipc = (loc.get("zip") or "").strip()
        tail = ", ".join(x for x in [city, ("CA " + zipc).strip()] if x)
        location = ", ".join(x for x in [place, street, tail] if x)
        name = (sh.get("job_type") or sh.get("job_name") or "Volunteer shift").strip()
        if place:
            name = f"{name} - {place}"
        ev = {
            "name": name,
            "date": iso,
            "start": _clock_12h(sh.get("start_time")),
            "end": _clock_12h(sh.get("end_time")) or None,
            "location": location,
            "bookingUrl": f"{page}?shift_id={sh['shift_id']}",
            "tags": fixed_tags(org_cfg, name),
        }
        lat, lng = loc.get("lat"), loc.get("lng")
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            ev["lat"], ev["lng"] = float(lat), float(lng)
        events.append(ev)
    return events, len(shifts)


def process_mmvfs_feed_org(client, org_cfg):
    text = fetch_text(org_cfg["feed_url"])
    try:
        data = json.loads(text)
    except ValueError:
        raise RuntimeError("the volunteer feed did not return JSON; the site probably changed")
    if not isinstance(data, dict) or not data.get("shifts"):
        raise RuntimeError("the volunteer feed has no shifts")
    events, n = mmvfs_events(data, org_cfg, date.today())
    log(f"  {n} shift(s) in the feed -> {len(events)} open shift(s) in the next "
        f"{org_cfg.get('lookahead_days', LOOKAHEAD_DAYS)} days")
    return events


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log("ANTHROPIC_API_KEY is not set -- add it as a repo secret (Settings > Secrets and "
            "variables > Actions) so this workflow can call the Claude API.")
        sys.exit(1)
    client = anthropic.Anthropic(api_key=api_key)
    install_cost_guard(client)

    today = date.today()
    cutoff = today + timedelta(days=LOOKAHEAD_DAYS)

    # Read last run's tags BEFORE events.json gets overwritten at the end.
    previous_tags = load_previous_tags() if TAGGING_ENABLED else {}
    previous_events = load_previous_events()

    # With ONLY_ORGS set, organizations that are not being tested keep exactly
    # what is already in events.json.
    previous_entries = {}
    if ONLY_ORGS:
        try:
            with open(EVENTS_JSON_PATH, encoding="utf-8") as f:
                previous_entries = {o.get("org", ""): o for o in json.load(f) if isinstance(o, dict)}
        except Exception:
            previous_entries = {}
        log(f"ONLY_ORGS={ONLY_ORGS}: other organizations keep their current events")

    output = []
    for org_cfg in ORGS:
        org_name = org_cfg["org"]
        if ONLY_ORGS and not any(k in org_name.lower() for k in ONLY_ORGS):
            if org_name in previous_entries:
                output.append(previous_entries[org_name])
            continue
        log(f"== {slugify_for_log(org_name)} ==")
        api_errors_before = API_ERROR_COUNT
        org_failed = False
        events = []
        try:
            if org_cfg["kind"] == "google_calendar":
                events = process_google_calendar_org(client, org_cfg)
            elif org_cfg["kind"] == "html_listing":
                events = process_html_listing_org(client, org_cfg)
            elif org_cfg["kind"] == "pbc_site_table":
                events = process_pbc_site_table_org(client, org_cfg)
            elif org_cfg["kind"] == "text_page":
                events = process_text_page_org(client, org_cfg)
            elif org_cfg["kind"] == "weekly_recurring":
                events = process_weekly_recurring_org(client, org_cfg)
            elif org_cfg["kind"] == "galaxy_calendar":
                events = process_galaxy_calendar_org(client, org_cfg)
            elif org_cfg["kind"] == "v4s_listing":
                events = process_v4s_listing_org(client, org_cfg)
            elif org_cfg["kind"] == "openhand_hotspots":
                events = process_openhand_hotspots_org(client, org_cfg)
            elif org_cfg["kind"] == "mmvfs_feed":
                events = process_mmvfs_feed_org(client, org_cfg)
            elif org_cfg["kind"] == "no_dated_events":
                log("  no dated events by design (self-directed program)")
            else:
                log(f"  ! unknown org kind: {org_cfg['kind']}")
        except Exception as e:
            log(f"  ! failed to process {org_name}: {e}")
            events = []
            org_failed = True

        cleaned_events = []
        for ev in events:
            # Run #6 crashed the ENTIRE script here: Claude's tool response for
            # Grassroots Ecology came back with `events` containing 1071
            # entries that were plain strings, not event objects (some
            # degenerate/repetitive echo of the source text rather than a
            # real extraction -- the *why* wasn't fully diagnosable from the
            # log, but the shape of the bad data was clear: `ev["date"]`
            # threw TypeError, a class this loop didn't catch). Because that
            # was outside any try/except, it killed the whole run before
            # events.json was ever written -- throwing away Surfrider and
            # Save The Bay's perfectly good results along with it, not just
            # Grassroots Ecology's bad ones. Two layers of defense now: skip
            # anything that isn't actually an event object, and never let a
            # single malformed record from one org take down every org.
            if not isinstance(ev, dict):
                log(f"  ! skipping malformed (non-object) event entry: {ev!r:.100}")
                continue
            try:
                try:
                    ev_date = datetime.strptime(ev["date"], "%Y-%m-%d").date()
                except (ValueError, KeyError, TypeError):
                    log(f"  ! skipping event with unparsable date: {ev}")
                    continue
                if not (today <= ev_date <= cutoff):
                    # This used to be a silent `continue` -- when it's every
                    # single extracted event (as happened for Grassroots
                    # Ecology in run #4, all 7 dropped here with zero
                    # explanation in the log), there was no way to tell this
                    # apart from a geocoding problem or Claude finding
                    # nothing at all. Always log why.
                    reason = "before today" if ev_date < today else f"beyond the {LOOKAHEAD_DAYS}-day lookahead"
                    log(f"  ! skipping '{ev.get('name')}' on {ev['date']} -- {reason}")
                    continue

                loc_text = str(ev.get("location") or "")
                if re.search(r"<\s*unknown\s*>|to be (determined|announced)", loc_text, re.I) or not loc_text.strip() \
                        or loc_text.strip().lower() in ("tbd", "tba", "n/a", "none"):
                    # Run 2026-10: "<UNKNOWN>" was geocoded to a spot in Texas and shown on the map.
                    log(f"  ! no real location for '{ev.get('name')}' ({loc_text!r}) -- skipping this event")
                    continue
                for _k in ("start", "end"):
                    _v = ev.get(_k)
                    if _v and not re.fullmatch(r"\d{1,2}(:\d{2})?\s*[AaPp][Mm]", str(_v).strip()):
                        ev[_k] = "" if _k == "start" else None   # e.g. "Earth Day (April) and ..." is not a time

                # Readers that already know exact coordinates (Second Harvest's feed)
                # pass them along; anything outside the Bay Area is ignored and
                # the address is geocoded as usual.
                lat = lng = None
                _la, _ln = ev.get("lat"), ev.get("lng")
                if isinstance(_la, (int, float)) and isinstance(_ln, (int, float)) \
                        and 36.8 <= _la <= 38.7 and -123.4 <= _ln <= -121.0:
                    lat, lng = float(_la), float(_ln)
                else:
                    lat, lng = geocode(ev.get("location", ""))
                if lat is None:
                    log(f"  ! could not geocode '{ev.get('location')}' -- skipping this event")
                    continue

                booking_url = ev.get("bookingUrl")
                if booking_url and org_cfg.get("verify_links", True) and not verify_url(booking_url):
                    booking_url = None  # dropped, not published -- see verify_url()

                cleaned_events.append(
                    {
                        "name": ev["name"],
                        "date": ev["date"],
                        "day": compute_day_name(ev["date"]),
                        "start": ev.get("start", ""),
                        "end": ev.get("end"),
                        "lat": round(lat, 4),
                        "lng": round(lng, 4),
                        "location": ev.get("location", ""),
                        **({"bookingUrl": booking_url} if booking_url else {}),
                        **({"tags": sanitize_tags(ev.get("tags"))} if sanitize_tags(ev.get("tags")) else {}),
                    }
                )
            except Exception as e:
                # Belt-and-suspenders: whatever this is, one bad record must
                # never take the whole run down with it.
                log(f"  ! unexpected error cleaning event {ev!r:.200} -- skipping it: {e}")
                continue

        if not cleaned_events and (API_ERROR_COUNT > api_errors_before or org_failed):
            kept = [e for e in previous_events.get(org_name, []) if str(e.get("date", "")) >= today.isoformat()]
            if kept:
                why = (f"the Claude API failed {API_ERROR_COUNT - api_errors_before} time(s) for this org"
                       if API_ERROR_COUNT > api_errors_before else "reading this org failed")
                log(f"  ! {why}, so "
                    f"keeping its {len(kept)} upcoming event(s) from the previous run instead of wiping them")
                cleaned_events = kept
        cleaned_events.sort(key=lambda e: (e["date"], e.get("start", "")))
        log(f"  -> {len(cleaned_events)} upcoming event(s) kept")
        tag_events(client, org_name, cleaned_events, previous_tags, cause=org_cfg.get("cause", "environment"))

        org_entry = {"org": org_name, "color": org_cfg["color"], "events": cleaned_events}
        if org_cfg.get("cause"):
            org_entry["cause"] = org_cfg["cause"]
        if org_cfg.get("org_url"):
            org_entry["orgUrl"] = org_cfg["org_url"]
        output.append(org_entry)

    log_claude_usage()
    if DRY_RUN:
        for o in output:
            log(f"DRY RUN: {slugify_for_log(o['org'])}: {len(o['events'])} event(s)")
        log("DRY RUN: events.json was NOT written")
        return
    with open(EVENTS_JSON_PATH, "w") as f:
        json.dump(output, f, indent=2)
        f.write("\n")
    log(f"Wrote {EVENTS_JSON_PATH}")


if __name__ == "__main__":
    main()
