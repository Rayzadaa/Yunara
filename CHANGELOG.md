# Changelog

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
