# Lazada Bot — User Guide

A desktop bot that watches Lazada SG and auto-checks-out when an item drops, with
Discord alerts. This guide covers setup, every feature, and **tips to actually win
the checkout.**

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
4. Launch with **`run_gui.bat`**.

## 2. Discord notifications
1. In Discord: **Channel → Edit → Integrations → Webhooks → New Webhook → Copy URL**.
2. In the bot: **🔔 Discord…** → paste the URL → **Send test** → **Save**.
3. (Optional) add a **user or role ID** to get @pinged on stock/order events.

## 3. Logging in
- **🔐 Login** → an OTP is texted to your phone → type it in the popup → wait for
  **"✅ Logged in"**. If a CAPTCHA appears, solve it in the browser window.
- **Multiple accounts:** **👤 Accounts…** → add `label = phone` lines (e.g. `BB = 91234567`).
  Then **🔐 Login** lets you pick which account. Each account keeps its own session.

## 4. Task types
**Add Task**, then choose ONE monitoring mode:

| Mode | Fill in | What it does |
|---|---|---|
| **Product** (most reliable) | Product URL | Watches one product in a browser; auto-buys on stock. Use for **must-win items**. |
| **Watch list** (lightweight) | Watch list URLs (one/line) | HTTP-polls many URLs in parallel (no browser); opens a browser only to check out a drop. Use for **breadth**. |
| **Keyword** (alert) | Keyword (+ optional shop URL) | Pings Discord when a NEW matching listing appears. Alert-only. |

Common fields: **Variant** (exact option text, e.g. `Sealed ETB` — required for option
products), **Quantity**, **Check interval (s)**, **Max price** (abort if total exceeds),
**Scheduled start** (HH:MM), **Payment method**, **Account**, **Alert only**, **Dry run**.

## 5. Payment
- **Lazada Wallet** — instant; checkout completes immediately. **Best option.** Keep it funded.
- **PayNow Transfer** — reserves the order and shows a QR; the bot sends the QR to Discord
  and you **pay within ~30 minutes**. Set the task's Payment to `PayNow Transfer`.
- Blank = use whatever's pre-selected on the account.

## 6. Running
- **▶ Start** a row (or **Start All**). Status is colour-coded; the **Log** pane and
  `bot.log` record everything; orders go to `orders.log`.
- **Quick edit:** double-click a Variant / Qty / Interval cell to change it inline.
- **Buy-once guard:** it won't re-buy the same item in a run.

## 7. Updates
The bot checks for updates on launch (and **⬇ Updates**). Click **Update now** → it
verifies the signature and swaps the code, keeping your config/tasks/login.

---

## 🎯 Tips to maximise your checkout chances

**Setup (do these before a drop):**
1. **Use Lazada Wallet, kept funded.** Instant payment = fastest checkout, no card form,
   fewest security checks. It's the single biggest win-rate factor.
2. **Pre-set your shipping address and payment** on the Lazada account so checkout has
   nothing to fill in.
3. **Log in early and stay logged in.** A warm, trusted session checks out faster and
   gets far fewer CAPTCHAs than a cold one.
4. **Set the correct Variant** for option products (ETB, etc.) — wrong/blank variant =
   Buy Now does nothing.

**Strategy:**
5. **Few tasks beats many.** For a hot drop, **one focused Product task** on your must-win
   item wins more than 20 tasks all triggering CAPTCHAs and competing for CPU.
6. **Must-wins = Product task; "maybes" = Watch list.** Dedicated browser tasks are the
   most reliable; the watch list is for cheaply covering a big batch.
7. **Sane interval.** 5–15s for a must-win, 20–30s for watch lists. Too aggressive =
   CAPTCHA.
8. **Use Scheduled start** for known drop times, and have the bot already logged in.

**Avoiding CAPTCHA (it's mostly reputation, not luck):**
9. **Run on your real IP — no proxy.** Proxies are the #1 CAPTCHA trigger and break logins.
10. **Don't hammer the account for hours** before a drop. A "hot" account gets challenged
    constantly; give it quiet time to cool down.
11. **Be ready to solve a CAPTCHA fast** — the bot resumes the instant you solve it
    (scan the QR with the Lazada app, or drag the slider in the window).

**Safety:**
12. **Set a Max price** to avoid scalper relists or pricing glitches.
13. **Respect purchase limits** — Lazada caps quantity per account (error OC03); set
    Quantity within the limit.
14. **Test the flow first** with a cheap in-stock item or **Dry run** (stops at Place
    Order without buying) so you know it works before the real drop.

**Bottom line:** logged-in + Lazada Wallet funded + real IP + one focused task + correct
variant = your best odds. Use watch lists for breadth, Product tasks for the win.
