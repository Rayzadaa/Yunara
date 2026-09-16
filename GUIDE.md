# Lazada Bot — User Guide

A desktop bot that watches Lazada SG and auto-checks-out when an item drops, with
Discord **and** desktop alerts. This guide covers setup, every feature, and **tips to
actually win the checkout.**

---

## 1. First-time setup
1. Install **Python 3.10+** and **Google Chrome** (the bot drives your installed Chrome).
2. In the bot folder, open a terminal:
   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Make your config: `copy config.example.py config.py`, then set **`LAZADA_PHONE`**
   to your account's phone number.
4. Launch with **`run_gui.bat`** (or `venv\Scripts\python.exe gui_app.py`).

## 2. The toolbar at a glance
`🔐 Login` · `▶ Start All` · `■ Stop All` · `➕ Add` `✎ Edit` `⧉ Dup` `🗑 Remove` ·
`⚙ Settings ▾` (Accounts, Proxies, Discord, Alerts, Self-test, Changelog) · `📜 Orders` · `⬇ Updates`

The bottom **status bar** shows live counts: running · idle · purchased · errors.

## 3. Notifications

**Discord (remote alerts):**
1. In Discord: **Channel → Edit → Integrations → Webhooks → New Webhook → Copy URL**.
2. In the bot: **⚙ Settings → 🔔 Discord…** → paste the URL → **Send test** → **Save**.
3. (Optional) add a **user or role ID** to get @pinged on stock/order events.

**Desktop (when you're at the PC but AFK):**
- **⚙ Settings → 🖥 Alerts…** → toggle a Windows notification + sound on the events that
  need you: **in stock**, **order placed**, and **CAPTCHA**. Use the **Test** button to check.

## 4. Logging in
- **🔐 Login** → an OTP is texted to your phone → type it in the popup → wait for
  **"Logged in"** (the dot next to Login turns green). If a CAPTCHA appears, solve it in
  the browser window (it pops to the front automatically).
- **Multiple accounts:** **⚙ Settings → 👤 Accounts…** → add `label = phone` lines (e.g.
  `BB = 91234567`). Then **🔐 Login** lets you pick which account. Each account keeps its
  own (encrypted) session, so you stay logged in between runs.

## 5. Task types
**➕ Add**, then choose ONE monitoring mode:

| Mode | Fill in | What it does |
|---|---|---|
| **Product** (most reliable) | Product URL | Watches one product in a browser; auto-buys on stock. Use for **must-win items**. |
| **Watch list** (lightweight) | Watch list URLs (one/line) | HTTP-polls many URLs in parallel (no browser); opens a browser only to check out a drop. Use for **breadth**. |
| **Keyword** (alert) | Keyword (+ optional shop URL) | Pings Discord when a NEW matching listing appears. Alert-only. |

**Task options:**
- **Variant** — exact option text, e.g. `Sealed ETB` (required for option products; wrong/blank = Buy Now does nothing).
- **Quantity** — keep within Lazada's per-account limit (see tips).
- **Check interval (s)** — how often to poll (see tips for sane values).
- **Max price** — abort the buy if the order total exceeds this (scalper/glitch guard).
- **Scheduled start** — `HH:MM` or `HH:MM:SS` (24h); the task waits until then to begin.
  Use seconds for a known drop time (e.g. `13:00:00`) so polling starts on the second.
- **Payment method** — see §6.
- **Proxies** — one per line; rotates/fails over. **Usually leave blank** (see tips).
- **Account** — which logged-in account to buy with.
- **Alert only** — notify on stock, don't buy.
- **Dry run** — go all the way to **Place Order** but don't click it (safe test).
- **Fast monitor** — a cheap HTTP pre-check that skips a full page load on clear out-of-stock.
- **⚡ Turbo mode** — blocks images while monitoring (faster polls) and trims checkout
  delays + skips debug screenshots (~2–4s faster buy). Opt-in; slightly more bot-like.
  Image-blocking auto-disables if a CAPTCHA appears.

The **Mode** column shows the active flags, e.g. `buy·fast·turbo`.

## 6. Payment
- **Lazada Wallet** — instant; checkout completes immediately. **Best option.** Keep it funded.
- **PayNow Transfer** — reserves the order and shows a QR; the bot sends the QR to Discord
  and you **pay within ~30 minutes**. Set the task's Payment to `PayNow Transfer`.
- Blank = use whatever's pre-selected on the account.

## 7. Running & monitoring
- **▶ Start** a row (or **Start All**). The **Status** pill is colour-coded; the **Log**
  pane (and `bot.log`) record everything.
- **Quick edit:** double-click a Variant / Qty / Interval cell to change it inline.
- **Buy-once guard:** a task won't re-buy the same item within a run.
- **📜 Orders** — view every placed order (time, product, order #, amount) from `orders.log`,
  with pending PayNow orders highlighted.

## 8. CAPTCHA
Lazada's slider CAPTCHA is mostly triggered by account/IP reputation, not luck. When one
appears the bot: pings Discord, fires a desktop alert, **brings the window to the front**,
and makes a best-effort auto-drag. If that doesn't clear it, solve it yourself in the
window (drag the slider, or scan the QR with the Lazada app) — the bot resumes the instant
it's cleared. There is **no reliable full auto-solver** for the slider; avoidance is the
real fix (see tips). reCAPTCHA (not the slider) can be auto-solved if you set a 2captcha
`CAPTCHA_API_KEY` in `config.py`.

## 9. Updates & security
- The bot checks for updates on launch and via **⬇ Updates**. An update is applied only if
  it carries a valid hash **and** a valid signature, so a tampered/forged update is refused.
  Your `config.py`, tasks, and login are never touched.
- **Session files are encrypted at rest** (bound to your Windows user), but they're still
  account access — **only run the bot on a trusted personal PC.**

---

## 🎯 Tips to maximise your checkout chances

**Setup (do these before a drop):**
1. **Use Lazada Wallet, kept funded.** Instant payment = fastest checkout, no card form,
   fewest security checks. The single biggest win-rate factor.
2. **Pre-set your shipping address and payment** on the account so checkout has nothing to fill in.
3. **Log in early and stay logged in.** A warm, trusted session checks out faster and gets
   far fewer CAPTCHAs than a cold one.
4. **Set the correct Variant** for option products (ETB, etc.) — wrong/blank variant =
   Buy Now does nothing.

**Strategy:**
5. **Few tasks beats many.** For a hot drop, **one focused Product task** on your must-win
   item wins more than 20 tasks all triggering CAPTCHAs and competing for CPU.
6. **Must-wins = Product task; "maybes" = Watch list.** Dedicated browser tasks are the most
   reliable; the watch list cheaply covers a big batch.
7. **Sane interval.** 5–15s for a must-win, 20–30s for watch lists. Too aggressive = CAPTCHA.
8. **Use Scheduled start** for known drop times, with the bot already logged in.
9. **Turn on ⚡ Turbo for the must-win task** to shave seconds — but leave it off if that
   account is CAPTCHA-prone, since faster is slightly more bot-like.

**Avoiding CAPTCHA (it's mostly reputation, not luck):**
10. **Run on your real IP — no proxy.** Proxies are the #1 CAPTCHA trigger and break logins.
11. **Don't hammer the account for hours** before a drop; give a "hot" account quiet time to cool down.
12. **Be ready to solve a CAPTCHA fast.** Turn on **🖥 Alerts** so you hear it; the window
    auto-focuses and the bot resumes the moment you solve it.

**Safety:**
13. **Set a Max price** to avoid scalper relists or pricing glitches.
14. **Respect purchase limits** — Lazada caps quantity per account (error OC03); set Quantity
    within the limit.
15. **Test the flow first** with a cheap in-stock item or **Dry run** (stops at Place Order
    without buying) so you know it works before the real drop.

**Bottom line:** logged-in + Lazada Wallet funded + real IP + one focused task + correct
variant = your best odds. Use watch lists for breadth, Product tasks for the win, and
Turbo to shave the final seconds.
