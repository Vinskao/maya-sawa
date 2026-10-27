# Telegram channels as a report source (analysis, 2026-10-27)

Status: **not implemented.** The views-to-target-timeline link it depends on is done (below). Channels the owner
named: `t.me/Gooaye` and `t.me/ieobserve`.

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
