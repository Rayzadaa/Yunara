# Changelog

## v2.7.1 — watch list reads short links
- The lightweight HTTP check now **resolves `s.lazada.sg` short links** to the real
  product page before reading stock, so watch-list URLs can be short links (they used
  to come back "unknown"). Verified against real listings.

## v2.7 — watch-list (lightweight concurrent monitor)
- New **Watch list** task: put many product URLs (one per line) and it **HTTP-polls
  them all in parallel** (a thread pool, no browser) for stock. When one looks like
  it dropped, it **opens a single browser, verifies, and checks out** that item — then
  keeps watching the rest. Lets you monitor a big batch cheaply (no browser-per-item)
  and only spend a browser on an actual drop.
- Heuristic, like Fast monitor: stock is read from the page's HTML, which Lazada
  renders with JS, so for must-win items a dedicated browser task is still the most
  reliable. Tick "Alert only" to just get pinged instead of auto-buying.

## v2.6.4 — faster checkout
- Checkout no longer waits out long fixed timeouts (a ~6s new-tab wait + an ~8s
  "network idle" wait that Lazada never satisfies). It now **polls fast and resolves
  the moment** the thank-you / payment / error page appears — noticeably quicker on
  instant (Wallet/card) orders. Trimmed the post-Buy-Now pause too.

## v2.6.3 — click the post-Place-Order confirmation
- Some checkouts show a **confirmation dialog after Place Order** that must be
  confirmed. The bot now clicks that Confirm button (and saves a
  `checkout_<task>_confirm.png` of the dialog for tuning).

## v2.6.2 — ping works for a user OR a role
- The Discord ping field now accepts **either a user ID or a role ID** and pings
  correctly either way (it was only doing role mentions before, so a user ID got
  no ping). Also fixed the @ping on image (QR) alerts.

## v2.6.1 — scope keyword monitor to one shop
- A keyword task can now be **scoped to a single shop**: put the seller's store URL
  in the Product URL field alongside the keyword, and it only scans that shop's
  listings for new matches (instead of all of Lazada). Leave it blank for site-wide.

## v2.6 — keyword (search) monitoring
- **Keyword monitor** — a task can now watch Lazada *search results* for a keyword
  instead of a fixed product URL. Set the **Keyword** field; it scans the search,
  baselines what's already there, and **pings Discord when a NEW listing matching
  the keyword appears** (great for catching fresh drops). Alert-only — it links the
  new product so you can grab it (or point a buy task at it).

## v2.5.5 — expand "View all methods" to find PayNow
- Some accounts only show Credit/Debit Card + Wallet by default, with PayNow hidden
  under **"View all methods"**. The payment selector now **expands that list first**,
  so choosing PayNow Transfer actually works (instead of getting stuck on a card form).

## v2.5.4 — resume right after a CAPTCHA is solved
- When a CAPTCHA appears, the bot now **watches the page and resumes the instant
  it's cleared** (auto-solve or you solving it manually), instead of sleeping a
  backoff and reloading the page (which discarded your solved state).

## v2.5.3 — fix unsolvable CAPTCHA (image blocking)
- Removed in-browser image/font blocking. It was stripping the images out of
  Lazada's robot-check, so the CAPTCHA couldn't render and **couldn't be solved**.
  CAPTCHAs, login, and checkout pages now display fully.

## v2.5.2 — PayNow in the payment dropdown
- Added **PayNow Transfer** to the task Payment-method options. Choosing it lets the
  bot place orders that pay by QR (no card details to enter), which also fixes the
  "still on checkout — not placed" loop you get when a card payment needs manual entry.

## v2.5.1 — handle sold-out-during-checkout
- If an item **sells out between detection and checkout** (cart shows "Unavailable
  Items" / 0 items / $0.00), the bot no longer tries to place an empty order or
  report a confusing result — it logs "sold out at checkout" and goes straight back
  to monitoring (it may restock).

## v2.5 — per-task proxy pool, better proxy test, quick edit
- **Per-task proxy list** — each task can hold multiple proxies (one per line). It
  fails over to the next proxy if one errors out (re-login stays on the same proxy).
- **Accurate proxy test** — "Test all" now does a lightweight IP-echo request (no
  browser, no heavy page) and reports true latency **plus the exit IP**, instead of
  a slow full Lazada homepage load.
- **Quick edit** — double-click a task's Variant, Qty or Interval cell in the table
  to edit it inline (no dialog). Saves immediately; applies on the task's next start.

## v2.4.3 — push the QR on success too
- On a successful order, the bot now also sends the **full-page order/QR
  screenshot** to Discord (not just a text confirmation), so an AFK user still
  gets the PayNow QR to pay within the ~30-minute window.

## v2.4.2 — purchase-limit detection
- Recognises Lazada's **"reached the limit for this product (OC03)"** — the account
  is already at the per-item max. The task now stops cleanly with a clear
  "limit reached" status + Discord note, instead of retrying 3× and reporting a
  vague "couldn't confirm".

## v2.4.1 — capture the PayNow QR from the new tab
- The PayNow page opens in a **new tab**, so the bot was screenshotting the (blank)
  original tab. It now **follows the new tab**, waits for it to render, and sends a
  **full-page** screenshot — so the actual QR / payment details reach Discord.

## v2.4 — PayNow / pending-payment orders
- **Handles PayNow / bank-transfer orders.** When Place Order reserves the order
  but needs a manual payment (no instant Wallet/card), the bot now recognises it
  as a *success* (no false "checkout failed", no retry/duplicate), marks it bought,
  and **sends the payment-page screenshot (PayNow QR) to Discord** with a
  "pay within ~30 min" alert so you can complete it in time.
- Distinguishes three post-checkout states: instant success, order-not-placed
  (retries), and order-reserved-pending-payment.
- Discord can now attach images (the QR / post-checkout page screenshot).

## v2.3 — scaling + hardening
- **Multi-account** — define accounts (label = phone) and assign one per task;
  each account keeps its own login session.
- **Per-profile sessions / proxy fix** — sessions are keyed by account + proxy, so
  a proxied task logs in through its own IP instead of showing logged-out.
- **Fast monitor (opt-in)** — a lightweight HTML pre-check skips full page loads on
  obvious out-of-stock cycles. Conservative (only short-circuits when certain).
- **Update integrity** — the updater verifies a **SHA-256** from the manifest before
  applying, so a tampered download is rejected.
- **Slider CAPTCHA attempt** — tries a human-like drag before falling back to manual.
- **Per-task error backoff** — exponential backoff on repeated errors/CAPTCHAs to
  avoid hammering an IP into a ban.
- **Crash alerts** — worker errors are pushed to Discord, not just the local log.
- **Dry-run mode** — per task: go all the way to Place Order and stop (validate the
  full flow without buying).
- **CI** — GitHub Action byte-compiles every module on push.
- **UI** — dark theme, colour-coded status, sortable table, Account column,
  Duplicate-task button.

## v2.2 — payment + auto-update
- **Payment method per task** — choose Lazada Wallet, Credit/Debit Card, Cash on
  Delivery, PayLater, etc. (or leave blank to use whatever's pre-selected).
  Checkout is no longer locked to Lazada Wallet.
- **In-app auto-update** — the bot checks a version manifest you host and offers a
  one-click "Update now?" that downloads + swaps the app files (your config,
  tasks, and session are never touched), then restarts. Manual check via the
  ⬇ Updates button.

## v2.1 — feature update
- **Faster, lighter monitoring** — images, fonts and media are blocked, so each
  product check loads quicker and uses less bandwidth.
- **Session auto-recovery** — if the Lazada login expires while monitoring, the
  task pauses and the app auto-prompts a re-login, then resumes (no silent death).
- **Checkout retries** — a failed checkout step is retried up to 3× before the
  task stops, instead of giving up on the first hiccup.
- **Proxy health check** — "Test all" button in the proxy dialog reports which
  proxies actually work (and how fast), in the log.
- **Stealth fingerprinting** — masks `navigator.webdriver` and related signals to
  lower the CAPTCHA rate.
- **CAPTCHA auto-solve (optional)** — set `CAPTCHA_API_KEY` (2captcha) to auto-solve
  reCAPTCHA. The Lazada slider still needs a manual solve in the window.
- **Alert-only mode** — per task: get a Discord ping on restock without auto-buying.
- **Scheduled start** — per task: start monitoring at a set HH:MM (e.g. a drop time).
- **Richer Discord alerts** — embeds with product link + optional role @ping on
  stock / order events.
- **Price guard** — per-task max price; aborts checkout if the total is higher.
- **UI** — Variant and Alert columns, per-row Start/Stop, Self-test button,
  in-app Changelog viewer.
- **Centralized selectors + Self-test** — all Lazada selectors live in one place;
  the Self-test button validates them against a live product page.
- **Order log** — placed orders are recorded to `orders.log`.

## v2.0 — GUI rebuild
- Replaced the single-product CLI bot with a PyQt6 desktop app.
- Multiple products monitored in parallel, each in its own browser + proxy.
- One shared login (OTP entered in-app), session reused across tasks.
- Variant/option selection, buy-once guard, no-buy-loop safety.
- Discord webhook notifications (no bot token needed).
- Uses installed Google Chrome (fixed broken bundled Chromium).
