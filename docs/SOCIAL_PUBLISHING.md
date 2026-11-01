# Social publishing (Facebook Page, Instagram, Threads)

Maya Sawa itself posts every new public AI analysis revision to the Birch Investments Facebook Page, Instagram and
Threads. No ChatGPT task or Metricool is involved: the post text is the analysis verbatim, so no model is needed.
This replaces the ChatGPT/Metricool flow in [BIRCH_THREADS_PUBLISHING.md](BIRCH_THREADS_PUBLISHING.md), whose
Metricool connector could only schedule posts and never return a verified post URL.

## What gets posted, when

- **Schedule:** Wednesday, Friday and Sunday at 21:30 Asia/Taipei (`services/social/runner.py`).
- **Sources:** the current `stock` analyses and `macro:US`, exactly what `/dashboard/analysis/{code}` serves
  publicly (`services/social/sources.py`). Never holdings, costs or private reports.
- **First run:** records a baseline and posts nothing; only revisions updated after it are posted.
- **Text** (`services/social/post_text.py`): the analysis verbatim. Macro gets the title
  「總經評論｜所有個股分析共用」; a stock gets its code in front only if the first line lacks it. Over the limit
  (Threads 500, Instagram 2,200, Facebook none) the front is kept, cut at a sentence or line end, and
  「更多請至我的網站：https://tymultiverse.cc/」 is appended unless the kept text already links the site.
- **Instagram image:** IG has no text-only posts. Each post uses a 1080×1350 text card
  (`services/social/card.py`) served publicly at
  `/maya-sawa/market/publishing/cards/{stock|macro}/{code}/{revision}.png` (current revision only, else 404).
  The image uses Noto Sans TC (two OTF weights downloaded and checksum-verified in the Dockerfile).
- **Order and pacing:** oldest revision first, Facebook → Instagram → Threads, 20 seconds between posts.

## Never posting twice

Table `maya_sawa_social_post` has one row per (revision, platform):

| State | Meaning | Next |
|---|---|---|
| `queued` | waiting | claimed atomically on the next run |
| `publishing` | claimed, request in flight | → `pending_review` if stuck 30 min |
| `published` | live; `post_id` and `url` stored | never touched again |
| `failed` | failed **before** the final publish call, nothing is live | retried, up to 3 attempts |
| `pending_review` | final publish call timed out / 5xx / crashed: the post **may** be live | never resent; Telegram alert; check the platform by hand |
| `superseded` | a newer revision replaced it before it went out | the newer revision is posted instead |

An expired or revoked token (Graph error 190/102) puts the post back in `queued` without spending an attempt, pauses
only that platform for the run, and sends one Telegram alert per episode. Posts resume on the next run after the
credential is fixed.

## Owner endpoints

- `GET /maya-sawa/market/publishing/social/status`: `enabled`, which platforms are configured, the cursor, and every
  row. Requires the `manage-users` role.
- `POST /maya-sawa/market/publishing/social/run`: run once now (only when enabled). Same role.

## Credentials (Jenkins Secret text → K8s Secret `social-publish`, all optional)

| Jenkins credential ID | Value |
|---|---|
| `SOCIAL_PUBLISH_ENABLED` | `true` to start the scheduler |
| `META_PAGE_ACCESS_TOKEN` | long-lived **Page** token (taken from a long-lived user token, so it does not expire); used for Facebook and Instagram |
| `THREADS_ACCESS_TOKEN` | long-lived (60-day) Threads token from the app's Threads *User Token Generator*; used once as the seed |
| `META_PAGE_ID`, `INSTAGRAM_USER_ID`, `THREADS_USER_ID` | optional overrides; by default each run looks them up from the tokens (`/me` with the Page token returns the Page and its linked `instagram_business_account`; Threads `/me` returns the user id) |

Instagram is "configured" only when the Page has a linked Instagram professional account. When a run finds the Page
token but no linked Instagram, it sends one Telegram message (not one per run) saying Instagram is being skipped and how
to link it; the message re-arms once the link exists. Revisions that went out while Instagram was skipped are not
back-filled to Instagram later. A failed Page lookup (expired token, network) is *not* reported as a missing link.
A platform without its ids/token is skipped. Threads tokens are refreshed weekly by the server and the refreshed
token is kept in `maya_sawa_social_state` (Postgres), so the Jenkins value only seeds it. Never put tokens in Git,
prompts or screenshots.

### Getting the ids and tokens (owner, once)

1. developers.facebook.com → Create app (Business). Add the use cases for Pages management, Instagram API with
   Facebook Login, and the Threads API. Development mode is enough because you are the app admin; no App Review is
   needed for your own Page and accounts.
2. Instagram must be a professional (Business/Creator) account linked to the Birch Investments Page.
3. Facebook/Instagram: in Graph API Explorer, get a user token with `pages_show_list`, `pages_read_engagement`,
   `pages_manage_posts`, `instagram_basic`, `instagram_content_publish`; exchange it for a long-lived user token
   (`/oauth/access_token?grant_type=fb_exchange_token`); `GET /me/accounts` returns the Page id and Page token;
   `GET /{page-id}?fields=instagram_business_account` returns the Instagram user id.
4. Threads: add `birch_investments` as a Threads tester and accept the invite in Threads settings; authorize with
   `threads_basic`, `threads_content_publish`; exchange for a long-lived token (`grant_type=th_exchange_token`);
   `GET https://graph.threads.net/v1.0/me?fields=id,username` returns the user id.
5. Save the six values as Jenkins Secret text credentials, then rebuild maya-sawa. Check
   `/social/status`; the first scheduled run (or `POST /social/run`) records the baseline.

## Tests

`poetry run python -m pytest tests/test_social_post_text.py tests/test_social_card.py tests/test_social_meta.py tests/test_social_runner.py tests/test_social_api.py -q`

The Meta responses in `tests/fixtures/meta_responses.json` follow Meta's documentation. Replace them with trimmed live
captures (no tokens) after the first real run.
