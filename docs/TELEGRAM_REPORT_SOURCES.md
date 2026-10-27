# Telegram and YouTube as view sources (analysis, 2026-10-27)

Status (2026-10-27): **implemented without a login, for `t.me/ieobserve` and `t.me/Gooaye`** (`services/telegram_posts.py`,
tests `tests/test_telegram_posts.py`). The MTProto analysis below stays as the fallback if the public preview ever stops
working or a private channel is needed.

## What is recorded (implemented)

- **Source:** the public preview `https://t.me/s/<channel>` needs no account, no API key and no session secret. It lists
  about 20 posts per page with the exact UTC time, and `?before=<id>` pages back through older posts. A trimmed real page of
  each channel is the test fixture.
- **What the channels contain:** neither posts broker PDFs. `ieobserve` writes short earnings commentary (Micron, SpaceX,
  Tesla) with a chart image and Patreon links; `Gooaye` announces podcast episodes and sells products. So each post with
  at least 15 characters of text is recorded; photo-only posts are skipped, and images are not downloaded.
- **How:** one **private** library report per post (no PDF), `publisher` = the channel's display name, `published_at` =
  the post's Taipei date, `source_url` = `https://t.me/<channel>/<id>`, deduplicated by channel and post id. The
  claim-extraction routine (20:30 daily) tags stocks in them, and those claims reach the target timeline as views.
- **When:** the backend reads both channels 2 minutes after it starts, then every 30 minutes. The first run walks back
  2 pages (about 40 posts per channel) so the extraction routine is not flooded; later runs stop at the first page that
  already has recorded posts. `BACKFILL_PAGES` raises the first-run depth (5 pages reached 2025-07 for ieobserve).
- **Dates:** every report and view shows the day it was recorded in the database; a report without a publication date is
  marked as such ("發布日未填 · 入庫 <date>"), and timeline views fall back to the recording day (`dateKind: recorded`).
- **Still open:** claims of private reports are not public. Showing them needs the decision below (public claims in our
  own words with a timestamped link, or a flag for claims from private sources). Expect few claims from Gooaye.

## Which Telegram API

| | Bot API | Telegram API (MTProto, a user-account client) |
|---|---|---|
| Read someone else's channel | No: a bot only gets a channel's posts after the channel adds it as an admin | Yes: history of any public channel the account can see |
| Download attached PDFs | Only in channels the bot is in | Yes |
| Needs | Bot token | `api_id`/`api_hash` from my.telegram.org and a one-time login with a phone code, which yields a session |
| Libraries | HTTP | Telethon / Pyrogram (Python), TDLib |

For channels we do not run, only MTProto works. `t.me/s/<channel>` (public web preview, no login) shows recent text
posts as HTML but not reliably the files; usable for text-only posts.

## Risks

- **Account:** Telegram's API terms forbid abuse such as flooding; fast polling triggers `FLOOD_WAIT` and heavy
  automated use can restrict the account. Use a secondary account and poll each channel every 15–30 minutes.
- **The session is a credential:** it logs in as the account. It lives only in a Jenkins credential / k8s Secret, never
  in the repo or logs (same rule as the IB login and the agent key). The first login needs a phone code, done locally.
- **Copyright:** broker reports are licensed to the broker's clients; channels often forward them without permission.
  Telegram PDFs are stored **private**; only facts (broker, date, rating, target) and a short reasoning in our own words
  are public, with attribution. Public analyses still use public reports only. Owner decision pending.
- **Not every channel posts broker reports.** Gooaye is a commentator's channel (opinions, not broker research); its
  posts would be "views" with the channel as publisher, not broker targets. Check each channel's content first.

## Design (when implemented)

1. Collector `services/telegram_reports.py` (Telethon): allow-listed channels, the last message id read per channel,
   read-only.
2. PDFs go to the report library (`market_reports`, private by default; sha256 drops reposts), with a new
   `source_kind`/`source_url` (`https://t.me/<channel>/<id>`). The claim-extraction routine extracts claims.
3. Text posts with an explicit broker, number and date become target rows (`source=telegram`).
4. Fixtures: a text post, a PDF post, the same PDF in two channels, a post without numbers, UTC timestamps,
   `FLOOD_WAIT`.

## Already done: views on the target timeline (2026-10-27)

- Target rows (`maya_sawa_market_price_target`) gained `thesis` (the broker's reasoning, max 300 characters) and
  `report_id` (the library report it came from). The Taiwan routine writes `thesis` for every news-sourced target.
- `GET /market/dashboard/targets/{code}` returns `views`: public report claims about the stock (codes `2330`, or
  `LITE-US` and `LITE` overseas), dated by publication or the claim's data date, newest first. Private reports never
  appear. If the report library is down, targets still load with `views: []`.
- The Targets tab draws views as diamonds under the chart (red tailwind, green headwind). Clicking a broker's dot or
  table row shows that call's reasoning, its source, and the claims from the same report (by `reportId`, else the same
  publisher on the same day). All views are listed below the broker table.
- Tests: `tests/test_market_price_targets.py`; frontend `tests/market/priceTargets.test.ts`.

## YouTube transcripts (analysis, 2026-10-27; not implemented)

Asked for: Bloomberg Technology (youtube.com/c/BloombergTech) interviews as dated views.

- **Listing videos is easy:** each channel has an RSS feed, `https://www.youtube.com/feeds/videos.xml?channel_id=<id>`
  (no key, latest ~15 uploads). Alternatively the YouTube Data API v3 (`playlistItems` of the uploads playlist) with an
  API key and the free daily quota.
- **Transcripts are the hard part:** the official `captions.download` only works for videos you are allowed to edit,
  so it cannot read a third party's captions. Libraries such as `youtube-transcript-api` read the captions the web
  player loads; they are unofficial, can break, and YouTube often blocks requests from cloud-provider IPs (our OKE
  nodes), so a collector may have to run from the owner's machine like the IB gateway. Not yet tested here.
- **Fallback:** download the audio and transcribe it (Whisper). This needs the OpenAI quota, which is currently used up,
  and downloading may conflict with YouTube's terms. Not recommended.
- **Copyright:** transcripts are the publisher's text. Store them private; publish only short claims in our own words
  with the speaker, date and a timestamped link (`watch?v=<id>&t=<seconds>s`).
- **Fit with what exists:** a video becomes a private library "report" (`source_kind=youtube`, publisher = channel,
  speaker in the claim, `published_at` = upload date), with transcript minutes in place of pages. The claim-extraction
  routine tags codes (`LITE-US`, `2330`), and the views then appear on the target timeline with no new UI. One gap:
  `list_claims` serves public reports only, so private-source views need a decision (publish the extracted claims,
  or add a "public claim from a private source" flag).

## Status of the target timeline (2026-10-27 check)

- Yahoo collection works for US per-broker actions (LITE 352, META 526) and consensus (3081, 6857, ...).
- Bug fixed 2026-10-27: stocks held only as stock futures (2330 via QFFK6, 3008, 3017, 3105, 3324) were skipped, so they
  had no consensus. The collector now follows `underlyingCode`.
- The Taiwan routine's run on 2026-10-26 searched only the two Japanese stocks and wrote no targets, because it skipped
  §7 together with §3 for stocks without a new trading day. Its prompt now runs §7 for every TW/JP/KR stock.
