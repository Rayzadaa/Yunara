"""PyQt6 GUI for the Lazada multi-task checkout bot (v2.3)."""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import json
import os
import queue
import re
import subprocess
import threading
from datetime import datetime

from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTableWidget, QTableWidgetItem, QTextEdit, QDialog, QLineEdit,
    QSpinBox, QDoubleSpinBox, QFormLayout, QPlainTextEdit, QInputDialog,
    QMessageBox, QHeaderView, QComboBox, QCheckBox,
)

import engine
import notifier
import updater

HERE = os.path.dirname(__file__)
DATA_FILE = os.path.join(HERE, "bot_data.json")
LOG_FILE = os.path.join(HERE, "bot.log")
CHANGELOG = os.path.join(HERE, "CHANGELOG.md")

PAYMENTS = ["", "PayNow Transfer", "Lazada Wallet", "Credit / Debit Card",
            "Cash on Delivery", "PayLater", "GrabPay", "Bank Transfer"]

COLS = ["Name", "Product URL", "Account", "Variant", "Qty", "Proxy", "Interval", "Mode", "Status", ""]
C_NAME, C_URL, C_ACCT, C_VAR, C_QTY, C_PROXY, C_INT, C_MODE, C_STATUS, C_ACT = range(10)

DARK_QSS = """
QWidget { background:#1e1f22; color:#e3e3e6; font-size:12px; }
QPushButton { background:#2b2d31; border:1px solid #3a3c41; padding:5px 9px; border-radius:5px; }
QPushButton:hover { background:#35373c; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {
  background:#2b2d31; border:1px solid #3a3c41; border-radius:4px; padding:3px; }
QTableWidget { background:#232428; gridline-color:#3a3c41; }
QHeaderView::section { background:#2b2d31; padding:4px; border:0; }
QTableWidget::item:selected { background:#3a4a63; }
"""


def load_phone():
    try:
        from config import LAZADA_PHONE
        return LAZADA_PHONE
    except Exception:
        return ""


def status_color(s):
    s = s.lower()
    if "purchased" in s or "in stock" in s:
        return QColor("#3ba55d")
    if "error" in s or "failed" in s or "expired" in s or "captcha" in s:
        return QColor("#ed4245")
    if "buying" in s or "checking out" in s or "scheduled" in s:
        return QColor("#faa61a")
    return QColor("#a0a0a4")


class Bridge(QObject):
    log = pyqtSignal(str, str)
    status = pyqtSignal(str, str)
    otp_request = pyqtSignal()
    login_done = pyqtSignal(bool, str)
    needs_login = pyqtSignal(str, str, str)
    update_found = pyqtSignal(dict)
    update_done = pyqtSignal(bool, str)


# ─── Dialogs ──────────────────────────────────────────────────────

class TaskDialog(QDialog):
    def __init__(self, parent, proxies, accounts, task=None):
        super().__init__(parent)
        self.setWindowTitle("Task")
        self.resize(600, 0)
        form = QFormLayout(self)
        t = task or {}
        self.name = QLineEdit(t.get("name", ""))
        self.url = QLineEdit(t.get("url", ""))
        self.keyword = QLineEdit(t.get("keyword", ""))
        self.keyword.setPlaceholderText("search-monitor: alerts on NEW matches (alert-only). Put a shop's store URL in Product URL to scope to one seller.")
        self.account = QComboBox(); self.account.addItem("")
        for a in accounts:
            self.account.addItem(a["label"])
        self.account.setCurrentText(t.get("account", ""))
        self.variant = QLineEdit(t.get("variant", ""))
        self.variant.setPlaceholderText("exact option text, e.g. Sealed ETB — blank if none")
        self.qty = QSpinBox(); self.qty.setRange(1, 99); self.qty.setValue(int(t.get("quantity", 1)))
        self.interval = QSpinBox(); self.interval.setRange(2, 600); self.interval.setValue(int(t.get("interval", 8)))
        self.maxprice = QDoubleSpinBox(); self.maxprice.setRange(0, 100000); self.maxprice.setDecimals(2)
        self.maxprice.setValue(float(t.get("max_price", 0))); self.maxprice.setSpecialValueText("no limit")
        self.start_at = QLineEdit(t.get("start_at", "")); self.start_at.setPlaceholderText("HH:MM (24h) — blank = now")
        self.payment = QComboBox(); self.payment.setEditable(True)
        for pm in PAYMENTS:
            self.payment.addItem(pm)
        self.payment.setEditText(t.get("payment", ""))
        self.proxy = QPlainTextEdit(); self.proxy.setMaximumHeight(80)
        self.proxy.setPlaceholderText("one proxy per line — host:port[:user:pass]; rotates/fails over; blank = none")
        existing = t.get("proxies")
        if not existing and t.get("proxy"):
            existing = [t["proxy"]]
        self.proxy.setPlainText("\n".join(existing or []))
        self.alert_only = QCheckBox("Alert only (notify, don't buy)"); self.alert_only.setChecked(bool(t.get("alert_only")))
        self.dry_run = QCheckBox("Dry run (stop at Place Order, don't click)"); self.dry_run.setChecked(bool(t.get("dry_run")))
        self.fast = QCheckBox("Fast monitor (lightweight pre-check)"); self.fast.setChecked(bool(t.get("fast")))

        form.addRow("Name", self.name)
        form.addRow("Product URL", self.url)
        form.addRow("Keyword (search)", self.keyword)
        form.addRow("Account", self.account)
        form.addRow("Variant / Option", self.variant)
        form.addRow("Quantity", self.qty)
        form.addRow("Check interval (s)", self.interval)
        form.addRow("Max price ($)", self.maxprice)
        form.addRow("Scheduled start", self.start_at)
        form.addRow("Payment method", self.payment)
        form.addRow("Proxies (one/line)", self.proxy)
        form.addRow("", self.alert_only)
        form.addRow("", self.dry_run)
        form.addRow("", self.fast)

        row = QHBoxLayout()
        ok = QPushButton("Save"); cancel = QPushButton("Cancel")
        ok.clicked.connect(self.accept); cancel.clicked.connect(self.reject)
        row.addStretch(1); row.addWidget(cancel); row.addWidget(ok)
        form.addRow(row)

    def get_task(self):
        return {
            "name": self.name.text().strip(), "url": self.url.text().strip(),
            "keyword": self.keyword.text().strip(),
            "account": self.account.currentText().strip(), "variant": self.variant.text().strip(),
            "quantity": self.qty.value(), "interval": self.interval.value(),
            "max_price": self.maxprice.value(), "start_at": self.start_at.text().strip(),
            "payment": self.payment.currentText().strip(),
            "proxies": [ln.strip() for ln in self.proxy.toPlainText().splitlines() if ln.strip()],
            "alert_only": self.alert_only.isChecked(), "dry_run": self.dry_run.isChecked(),
            "fast": self.fast.isChecked(),
        }


class ProxyDialog(QDialog):
    def __init__(self, parent, proxies):
        super().__init__(parent)
        self.parent_win = parent
        self.setWindowTitle("Proxy pool"); self.resize(540, 420)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("One per line — host:port or host:port:user:pass"))
        self.text = QPlainTextEdit("\n".join(proxies)); lay.addWidget(self.text)
        row = QHBoxLayout()
        test = QPushButton("Test all (background)"); test.clicked.connect(self._test)
        ok = QPushButton("Save"); cancel = QPushButton("Cancel")
        ok.clicked.connect(self.accept); cancel.clicked.connect(self.reject)
        row.addWidget(test); row.addStretch(1); row.addWidget(cancel); row.addWidget(ok)
        lay.addLayout(row)

    def _test(self):
        proxies = self.get_proxies()
        if proxies:
            self.parent_win.test_proxies(proxies)
            QMessageBox.information(self, "Testing", "Testing in background — results in the log.")

    def get_proxies(self):
        return [ln.strip() for ln in self.text.toPlainText().splitlines() if ln.strip()]


class AccountsDialog(QDialog):
    def __init__(self, parent, accounts):
        super().__init__(parent)
        self.setWindowTitle("Accounts"); self.resize(460, 360)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("One per line:  label = phone   (e.g.  main = 91234567)\n"
                             "The default account uses LAZADA_PHONE from config.py."))
        text = "\n".join(f"{a['label']} = {a['phone']}" for a in accounts)
        self.text = QPlainTextEdit(text); lay.addWidget(self.text)
        row = QHBoxLayout()
        ok = QPushButton("Save"); cancel = QPushButton("Cancel")
        ok.clicked.connect(self.accept); cancel.clicked.connect(self.reject)
        row.addStretch(1); row.addWidget(cancel); row.addWidget(ok)
        lay.addLayout(row)

    def get_accounts(self):
        out = []
        for ln in self.text.toPlainText().splitlines():
            if "=" in ln:
                label, phone = ln.split("=", 1)
                if label.strip() and phone.strip():
                    out.append({"label": label.strip(), "phone": phone.strip()})
        return out


class WebhookDialog(QDialog):
    def __init__(self, parent, url, role):
        super().__init__(parent)
        self.setWindowTitle("Discord notifications"); self.resize(600, 0)
        form = QFormLayout(self)
        form.addRow(QLabel("Channel → Edit → Integrations → Webhooks → New Webhook → Copy URL"))
        self.url = QLineEdit(url); self.url.setPlaceholderText("https://discord.com/api/webhooks/...")
        self.role = QLineEdit(role); self.role.setPlaceholderText("optional role ID to @ping")
        form.addRow("Webhook URL", self.url); form.addRow("Ping role ID", self.role)
        row = QHBoxLayout()
        test = QPushButton("Send test"); test.clicked.connect(self._test)
        ok = QPushButton("Save"); cancel = QPushButton("Cancel")
        ok.clicked.connect(self.accept); cancel.clicked.connect(self.reject)
        row.addWidget(test); row.addStretch(1); row.addWidget(cancel); row.addWidget(ok)
        form.addRow(row)

    def _test(self):
        u = self.url.text().strip()
        if not u:
            QMessageBox.warning(self, "No URL", "Enter a webhook URL first."); return
        pw, pr = notifier.get_webhook(), notifier.get_role()
        notifier.set_webhook(u); notifier.set_role(self.role.text().strip())
        ok = notifier.send_event("✅ Lazada Bot test", description="Notifications work!", color=0x3498DB)
        notifier.set_webhook(pw); notifier.set_role(pr)
        QMessageBox.information(self, "Test", "Sent — check Discord." if ok else "Failed — check the URL.")

    def get(self):
        return self.url.text().strip(), self.role.text().strip()


class ChangelogDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Changelog / Updates"); self.resize(560, 480)
        lay = QVBoxLayout(self)
        view = QTextEdit(); view.setReadOnly(True)
        try:
            view.setPlainText(open(CHANGELOG, encoding="utf-8").read())
        except Exception:
            view.setPlainText("No changelog found.")
        lay.addWidget(view)
        close = QPushButton("Close"); close.clicked.connect(self.accept); lay.addWidget(close)


# ─── Main window ──────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Lazada Bot — Multi-Task  v{engine.VERSION}")
        self.resize(1240, 700)
        self.tasks = []; self.proxies = []; self.accounts = []
        self.workers = {}
        self.logged_in = False
        self.webhook_url = ""; self.role_id = ""
        self.otp_queue = queue.Queue()
        self._login_busy = False
        self._refreshing = False

        self.bridge = Bridge()
        self.bridge.log.connect(self.on_log)
        self.bridge.status.connect(self.on_status)
        self.bridge.otp_request.connect(self.on_otp_request)
        self.bridge.login_done.connect(self.on_login_done)
        self.bridge.needs_login.connect(self.on_needs_login)
        self.bridge.update_found.connect(self.on_update_found)
        self.bridge.update_done.connect(self._finish_update)

        self._build_ui()
        self._load()
        threading.Thread(target=self._check_updates_bg, args=(False,), daemon=True).start()

    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central)
        bar = QHBoxLayout()
        self.login_btn = QPushButton("🔐 Login"); self.login_btn.clicked.connect(lambda: self.do_login())
        self.login_lbl = QLabel("Not logged in")
        bar.addWidget(self.login_btn); bar.addWidget(self.login_lbl); bar.addStretch(1)
        for text, fn in [
            ("➕ Add", self.add_task), ("✎ Edit", self.edit_task), ("⧉ Dup", self.dup_task),
            ("🗑 Remove", self.remove_task), ("👤 Accounts…", self.manage_accounts),
            ("🌐 Proxies…", self.manage_proxies), ("🔔 Discord…", self.manage_webhook),
            ("🧪 Self-test", self.run_self_test), ("📋 Changelog", self.show_changelog),
            ("⬇ Updates", self.check_updates),
            ("▶ Start All", self.start_all), ("■ Stop All", self.stop_all),
        ]:
            b = QPushButton(text); b.clicked.connect(fn); bar.addWidget(b)
        root.addLayout(bar)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.horizontalHeader().setSectionResizeMode(C_URL, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(True)
        self.table.itemChanged.connect(self.on_item_changed)
        root.addWidget(self.table, 3)
        root.addWidget(QLabel("Log"))
        self.logview = QTextEdit(); self.logview.setReadOnly(True)
        root.addWidget(self.logview, 2)

    # ---- persistence ----
    def _load(self):
        if os.path.exists(DATA_FILE):
            try:
                data = json.load(open(DATA_FILE, encoding="utf-8"))
                self.tasks = data.get("tasks", [])
                for t in self.tasks:  # migrate old single proxy -> list
                    if "proxies" not in t:
                        t["proxies"] = [t["proxy"]] if t.get("proxy") else []
                self.proxies = data.get("proxies", [])
                self.accounts = data.get("accounts", [])
                self.webhook_url = data.get("webhook", ""); self.role_id = data.get("role", "")
                notifier.set_webhook(self.webhook_url); notifier.set_role(self.role_id)
            except Exception:
                pass
        if os.path.exists(engine.SESSION_FILE):
            self.logged_in = True
            self.login_lbl.setText("Session found (login to refresh)")
        self._refresh_table()

    def _save(self):
        json.dump({"tasks": self.tasks, "proxies": self.proxies, "accounts": self.accounts,
                   "webhook": self.webhook_url, "role": self.role_id},
                  open(DATA_FILE, "w", encoding="utf-8"), indent=2)

    def _mode(self, t):
        m = "alert" if t.get("alert_only") else ("dry" if t.get("dry_run") else "buy")
        if t.get("fast"):
            m += "·fast"
        return m

    def _cell(self, text, editable=False):
        it = QTableWidgetItem(text)
        if not editable:
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return it

    def _refresh_table(self):
        self._refreshing = True
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for t in self.tasks:
            r = self.table.rowCount(); self.table.insertRow(r)
            pl = t.get("proxies") or ([t["proxy"]] if t.get("proxy") else [])
            proxy_txt = f"{len(pl)} proxies" if len(pl) > 1 else (pl[0] if pl else "—")
            self.table.setItem(r, C_NAME, self._cell(t["name"]))
            self.table.setItem(r, C_URL, self._cell(("🔎 " + t["keyword"]) if t.get("keyword") else t["url"]))
            self.table.setItem(r, C_ACCT, self._cell(t.get("account", "") or "default"))
            self.table.setItem(r, C_VAR, self._cell(t.get("variant", "") or "—", editable=True))
            self.table.setItem(r, C_QTY, self._cell(str(t.get("quantity", 1)), editable=True))
            self.table.setItem(r, C_PROXY, self._cell(proxy_txt))
            self.table.setItem(r, C_INT, self._cell(str(t.get("interval", 8)) + "s", editable=True))
            self.table.setItem(r, C_MODE, self._cell(self._mode(t)))
            self.table.setItem(r, C_STATUS, self._cell("idle"))
            btn = QPushButton("▶ Start")
            btn.clicked.connect(lambda _, n=t["name"]: self.toggle_task(n))
            self.table.setCellWidget(r, C_ACT, btn)
        self.table.setSortingEnabled(True)
        self._refreshing = False

    def on_item_changed(self, item):
        if self._refreshing:
            return
        col, row = item.column(), item.row()
        nameit = self.table.item(row, C_NAME)
        if not nameit:
            return
        name = nameit.text()
        t = next((x for x in self.tasks if x["name"] == name), None)
        if not t:
            return
        val = item.text().strip()
        if col == C_VAR:
            t["variant"] = "" if val == "—" else val
        elif col == C_QTY:
            t["quantity"] = max(1, int(re.sub(r"\D", "", val) or 1))
        elif col == C_INT:
            t["interval"] = max(2, int(re.sub(r"\D", "", val) or 8))
        else:
            return
        self._save()
        self.log_line(name, "edited (applies on next start)" if name in self.workers else "edited")
        self._refreshing = True
        if col == C_INT:
            item.setText(f"{t['interval']}s")
        elif col == C_QTY:
            item.setText(str(t["quantity"]))
        self._refreshing = False

    def _row_of(self, name):
        for r in range(self.table.rowCount()):
            it = self.table.item(r, C_NAME)
            if it and it.text() == name:
                return r
        return None

    # ---- logging ----
    def log_line(self, who, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] [{who}] {msg}"
        self.logview.append(line)
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def on_log(self, name, msg):
        self.log_line(name, msg)

    def on_status(self, name, status):
        r = self._row_of(name)
        if r is not None:
            self._refreshing = True
            item = self._cell(status)
            item.setForeground(status_color(status))
            self.table.setItem(r, C_STATUS, item)
            self._refreshing = False
        self.log_line(name, f"status → {status}")
        if status.startswith("purchased") or status.startswith("checkout") or status.startswith("error"):
            self._set_row_button(name, start=True)
            if status.startswith("purchased") or status.startswith("checkout"):
                self.workers.pop(name, None)

    def _set_row_button(self, name, start):
        r = self._row_of(name)
        if r is None:
            return
        btn = self.table.cellWidget(r, C_ACT)
        if btn:
            btn.setText("▶ Start" if start else "■ Stop")

    # ---- login (per profile) ----
    def _phone_for(self, account_label):
        if not account_label:
            return load_phone()
        for a in self.accounts:
            if a["label"] == account_label:
                return a["phone"]
        return ""

    def do_login(self, account_label="", proxy_raw=""):
        if self._login_busy:
            self.log_line("login", "another login is in progress — please wait")
            return
        phone = self._phone_for(account_label)
        if not phone:
            QMessageBox.warning(self, "No phone",
                                f"No phone for account '{account_label or 'default'}'.\n"
                                "Set LAZADA_PHONE in config.py or add it under Accounts.")
            return
        session_file = engine.session_path(account_label, proxy_raw)
        self._login_busy = True
        self.login_btn.setEnabled(False)
        self.login_lbl.setText(f"Logging in ({account_label or 'default'})…")

        def get_otp():
            while not self.otp_queue.empty():
                try: self.otp_queue.get_nowait()
                except Exception: break
            self.bridge.otp_request.emit()
            try:
                return self.otp_queue.get(timeout=300)
            except Exception:
                return None

        def run():
            ok = engine.LoginManager(phone, get_otp, lambda m: self.bridge.log.emit("login", m),
                                     proxy_raw, session_file).run()
            self.bridge.login_done.emit(ok, account_label or "default")

        threading.Thread(target=run, daemon=True).start()

    def on_otp_request(self):
        otp, ok = QInputDialog.getText(self, "OTP", "Enter the SMS code:")
        self.otp_queue.put(otp.strip() if ok else None)

    def on_login_done(self, ok, label):
        self._login_busy = False
        self.login_btn.setEnabled(True)
        if ok:
            self.logged_in = True
            self.login_lbl.setText(f"✅ Logged in ({label})")
        else:
            self.login_lbl.setText(f"❌ Login failed ({label})")

    def on_needs_login(self, name, account, proxy):
        if not self._login_busy:
            self.log_line(name, f"auto re-login for account '{account or 'default'}'")
            self.do_login(account, proxy)

    # ---- task CRUD ----
    def _selected_name(self):
        r = self.table.currentRow()
        if r < 0:
            return None
        it = self.table.item(r, C_NAME)
        return it.text() if it else None

    def add_task(self):
        dlg = TaskDialog(self, self.proxies, self.accounts)
        if dlg.exec():
            t = dlg.get_task()
            if not t["name"] or (not t["url"] and not t.get("keyword")):
                QMessageBox.warning(self, "Missing", "Name and a URL or Keyword are required."); return
            if any(x["name"] == t["name"] for x in self.tasks):
                QMessageBox.warning(self, "Duplicate", "That name exists."); return
            self.tasks.append(t); self._save(); self._refresh_table()

    def edit_task(self):
        name = self._selected_name()
        if not name:
            return
        if name in self.workers:
            QMessageBox.information(self, "Running", "Stop the task before editing."); return
        t = next(x for x in self.tasks if x["name"] == name)
        dlg = TaskDialog(self, self.proxies, self.accounts, t)
        if dlg.exec():
            t.update(dlg.get_task()); self._save(); self._refresh_table()

    def dup_task(self):
        name = self._selected_name()
        if not name:
            return
        src = next(x for x in self.tasks if x["name"] == name)
        copy = dict(src)
        base = copy["name"] + " copy"; n = base; i = 2
        while any(x["name"] == n for x in self.tasks):
            n = f"{base} {i}"; i += 1
        copy["name"] = n
        self.tasks.append(copy); self._save(); self._refresh_table()

    def remove_task(self):
        name = self._selected_name()
        if not name:
            return
        if name in self.workers:
            self.stop_task(name)
        self.tasks = [x for x in self.tasks if x["name"] != name]
        self._save(); self._refresh_table()

    def manage_accounts(self):
        dlg = AccountsDialog(self, self.accounts)
        if dlg.exec():
            self.accounts = dlg.get_accounts(); self._save()
            self.log_line("accounts", f"{len(self.accounts)} account(s) saved")

    def manage_proxies(self):
        dlg = ProxyDialog(self, self.proxies)
        if dlg.exec():
            self.proxies = dlg.get_proxies(); self._save()
            self.log_line("proxies", f"{len(self.proxies)} saved")

    def test_proxies(self, proxies):
        def run():
            for px in proxies:
                ok, msg = engine.test_proxy(px)
                self.bridge.log.emit("proxy-test", f"{'✓' if ok else '✗'} {px} — {msg}")
        threading.Thread(target=run, daemon=True).start()

    def manage_webhook(self):
        dlg = WebhookDialog(self, self.webhook_url, self.role_id)
        if dlg.exec():
            self.webhook_url, self.role_id = dlg.get()
            notifier.set_webhook(self.webhook_url); notifier.set_role(self.role_id)
            self._save(); self.log_line("discord", "settings saved")

    def run_self_test(self):
        name = self._selected_name()
        default = next((x["url"] for x in self.tasks if x["name"] == name), "") if name else ""
        url, ok = QInputDialog.getText(self, "Self-test", "Product URL to validate:", text=default)
        if ok and url.strip():
            threading.Thread(target=lambda: engine.self_test(
                url.strip(), lambda m: self.bridge.log.emit("self-test", m)), daemon=True).start()

    def show_changelog(self):
        ChangelogDialog(self).exec()

    # ---- run control ----
    def toggle_task(self, name):
        if name in self.workers:
            self.stop_task(name)
        else:
            self.start_task(name)

    def start_task(self, name):
        if name in self.workers:
            return
        task = next(x for x in self.tasks if x["name"] == name)
        worker = engine.TaskWorker(
            task,
            on_log=lambda n, m: self.bridge.log.emit(n, m),
            on_status=lambda n, s: self.bridge.status.emit(n, s),
            on_needs_login=lambda n, a, px: self.bridge.needs_login.emit(n, a, px))
        self.workers[name] = worker
        worker.start()
        self._set_row_button(name, start=False)
        self.log_line(name, "started")

    def stop_task(self, name):
        w = self.workers.pop(name, None)
        if w:
            w.stop(); self.log_line(name, "stopping…")
        self._set_row_button(name, start=True)
        r = self._row_of(name)
        if r is not None:
            self._refreshing = True
            self.table.setItem(r, C_STATUS, self._cell("idle"))
            self._refreshing = False

    def start_all(self):
        for t in self.tasks:
            self.start_task(t["name"])

    def stop_all(self):
        for name in list(self.workers.keys()):
            self.stop_task(name)

    # ---- updates ----
    def check_updates(self):
        threading.Thread(target=self._check_updates_bg, args=(True,), daemon=True).start()

    def _check_updates_bg(self, manual):
        available, info = updater.check(engine.VERSION)
        if available:
            self.bridge.update_found.emit(info)
        elif manual:
            err = info.get("error")
            self.bridge.log.emit("update", f"Update check failed: {err}" if err else f"Up to date (v{engine.VERSION}).")

    def on_update_found(self, info):
        latest = info.get("version", "?"); notes = info.get("notes", "")
        ans = QMessageBox.question(self, "Update available",
                                   f"Version {latest} is available (you have {engine.VERSION}).\n\n{notes}\n\nUpdate now?",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ans != QMessageBox.StandardButton.Yes:
            return

        def run():
            ok = updater.apply(info, lambda m: self.bridge.log.emit("update", m))
            self.bridge.update_done.emit(ok, latest)
        threading.Thread(target=run, daemon=True).start()

    def _finish_update(self, ok, latest):
        if ok:
            r = QMessageBox.question(self, "Updated", f"Updated to v{latest}. Restart now?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if r == QMessageBox.StandardButton.Yes:
                self._restart()
        else:
            QMessageBox.warning(self, "Update failed", "Could not apply the update — see the log.")

    def _restart(self):
        try:
            subprocess.Popen([sys.executable, os.path.join(HERE, "gui_app.py")])
        except Exception as e:
            self.log_line("update", f"restart failed: {e}")
        self.close()

    def closeEvent(self, event):
        self.stop_all(); self._save(); event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_QSS)
    w = MainWindow(); w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
