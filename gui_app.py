"""PyQt6 GUI for the Lazada multi-task checkout bot (v2.3)."""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import html
import json
import os
import queue
import re
import subprocess
import threading
from datetime import datetime

from PyQt6.QtCore import Qt, QObject, pyqtSignal, QSize, QRect
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTableWidget, QTableWidgetItem, QTextEdit, QDialog, QLineEdit,
    QSpinBox, QDoubleSpinBox, QFormLayout, QPlainTextEdit, QInputDialog,
    QMessageBox, QHeaderView, QComboBox, QCheckBox, QSystemTrayIcon, QStyle,
    QToolButton, QMenu, QFrame, QStyledItemDelegate,
)

try:
    import desktop_alert
except Exception:  # update transition: module may be absent on first launch
    desktop_alert = None
try:
    import secure_store
except Exception:
    secure_store = None
import engine
import notifier
import updater

HERE = os.path.dirname(__file__)
DATA_FILE = os.path.join(HERE, "bot_data.json")
LOG_FILE = os.path.join(HERE, "bot.log")
CHANGELOG = os.path.join(HERE, "CHANGELOG.md")
ORDERS_FILE = os.path.join(HERE, "orders.log")

PAYMENTS = ["", "PayNow Transfer", "Lazada Wallet", "Credit / Debit Card",
            "Cash on Delivery", "PayLater", "GrabPay", "Bank Transfer"]

COLS = ["Name", "Product URL", "Account", "Variant", "Qty", "Proxy", "Interval", "Mode", "Status", ""]
C_NAME, C_URL, C_ACCT, C_VAR, C_QTY, C_PROXY, C_INT, C_MODE, C_STATUS, C_ACT = range(10)

ACCENT = "#f57224"  # Lazada orange

DARK_QSS = f"""
QWidget {{ background:#1e1f22; color:#e3e3e6; font-size:12px; }}
QMainWindow, QDialog {{ background:#1e1f22; }}
QLabel {{ background:transparent; }}
QPushButton {{ background:#2b2d31; border:1px solid #3a3c41; padding:5px 10px; border-radius:6px; }}
QPushButton:hover {{ background:#35373c; border-color:#4a4d54; }}
QPushButton:pressed {{ background:#222327; }}
QPushButton#primary {{ background:{ACCENT}; border:1px solid {ACCENT}; color:#1a1a1a; font-weight:bold; }}
QPushButton#primary:hover {{ background:#ff8338; }}
QPushButton#danger:hover {{ background:#5a2326; border-color:#ed4245; color:#ff6b6e; }}
QToolButton {{ background:#2b2d31; border:1px solid #3a3c41; padding:5px 10px; border-radius:6px; }}
QToolButton:hover {{ background:#35373c; border-color:#4a4d54; }}
QToolButton::menu-indicator {{ image:none; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
  background:#2b2d31; border:1px solid #3a3c41; border-radius:5px; padding:4px; }}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
  border:1px solid {ACCENT}; }}
QTableWidget {{ background:#232428; gridline-color:#2e3033; alternate-background-color:#26282c;
  border:1px solid #3a3c41; border-radius:6px; }}
QTableWidget::item {{ padding:5px 6px; }}
QTableWidget::item:selected {{ background:#3a4a63; }}
QHeaderView::section {{ background:#2b2d31; padding:6px; border:0; border-bottom:1px solid #3a3c41;
  color:#b8b8bc; font-weight:bold; }}
QMenu {{ background:#2b2d31; border:1px solid #3a3c41; }}
QMenu::item {{ padding:6px 18px; }}
QMenu::item:selected {{ background:{ACCENT}; color:#1a1a1a; }}
QStatusBar {{ background:#202125; color:#b8b8bc; border-top:1px solid #3a3c41; }}
QStatusBar::item {{ border:0; }}
QScrollBar:vertical {{ background:#1e1f22; width:11px; margin:0; }}
QScrollBar::handle:vertical {{ background:#3a3c41; border-radius:5px; min-height:24px; }}
QScrollBar::handle:vertical:hover {{ background:#4a4d54; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height:0; }}
"""

# Status pill palette: (background, foreground) keyed by status category.
PILL_GREEN = ("#1e4d33", "#5fd587")
PILL_RED = ("#4d2a2d", "#ff7b7e")
PILL_AMBER = ("#4d3f1f", "#ffc04d")
PILL_GRAY = ("#3a3d43", "#c2c2c6")
PILL_BLUE = ("#2c3e4f", "#8fbce0")


def load_phone():
    try:
        from config import LAZADA_PHONE
        return LAZADA_PHONE
    except Exception:
        return ""


def pill_colors(status):
    s = status.lower()
    if any(k in s for k in ("purchased", "in stock", "ordered", "order placed", "all done")):
        return PILL_GREEN
    if any(k in s for k in ("error", "failed", "expired", "captcha", "unavailable", "sold out")):
        return PILL_RED
    if any(k in s for k in ("buying", "checking out", "checkout", "scheduled", "polling",
                            "verifying", "scanning", "resuming", "drop", "login")):
        return PILL_AMBER
    if any(k in s for k in ("idle", "out of stock", "stopping")):
        return PILL_GRAY
    return PILL_BLUE


class StatusPillDelegate(QStyledItemDelegate):
    """Paints the Status cell as a rounded colour pill. Drawn via a delegate (not
    a cell widget) so the status is real item data — the column's auto-size sees
    its true width on every change, so longer statuses never clip."""
    _PADX, _PADY, _MARGIN = 12, 4, 6

    @staticmethod
    def _bold(option):
        f = QFont(option.font); f.setBold(True)
        return f

    def paint(self, painter, option, index):
        status = index.data(Qt.ItemDataRole.DisplayRole) or ""
        bg, fg = pill_colors(status)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        painter.setFont(self._bold(option))
        fm = painter.fontMetrics()
        pill_w = fm.horizontalAdvance(status) + self._PADX * 2
        pill_h = fm.height() + self._PADY * 2
        x = option.rect.x() + self._MARGIN
        y = option.rect.y() + (option.rect.height() - pill_h) // 2
        rect = QRect(x, y, pill_w, pill_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(bg))
        painter.drawRoundedRect(rect, 10, 10)
        painter.setPen(QColor(fg))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, status)
        painter.restore()

    def sizeHint(self, option, index):
        status = index.data(Qt.ItemDataRole.DisplayRole) or ""
        fm = QFontMetrics(self._bold(option))
        return QSize(fm.horizontalAdvance(status) + self._PADX * 2 + self._MARGIN * 2,
                     fm.height() + self._PADY * 2 + 6)


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
        self.watchlist = QPlainTextEdit(); self.watchlist.setMaximumHeight(90)
        self.watchlist.setPlaceholderText("watch-list: one product URL per line — HTTP-polled in parallel; a browser opens only to check out a drop")
        self.watchlist.setPlainText("\n".join(t.get("watchlist", []) or []))
        self.account = QComboBox(); self.account.setEditable(True); self.account.addItem("")
        labels = [a["label"] for a in accounts]
        for lbl in labels:
            self.account.addItem(lbl)
        cur = t.get("account", "")
        if cur and cur not in labels:
            self.account.addItem(cur)  # keep the task's account even if the list changed
        self.account.setCurrentText(cur)
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
        self.turbo = QCheckBox("⚡ Turbo mode (block images while monitoring + trim checkout delays — faster, slightly higher detection risk)")
        self.turbo.setChecked(bool(t.get("turbo")))

        form.addRow("Name", self.name)
        form.addRow("Product URL", self.url)
        form.addRow("Keyword (search)", self.keyword)
        form.addRow("Watch list (URLs)", self.watchlist)
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
        form.addRow("", self.turbo)

        row = QHBoxLayout()
        ok = QPushButton("Save"); cancel = QPushButton("Cancel")
        ok.clicked.connect(self.accept); cancel.clicked.connect(self.reject)
        row.addStretch(1); row.addWidget(cancel); row.addWidget(ok)
        form.addRow(row)

    def get_task(self):
        return {
            "name": self.name.text().strip(), "url": self.url.text().strip(),
            "keyword": self.keyword.text().strip(),
            "watchlist": [ln.strip() for ln in self.watchlist.toPlainText().splitlines() if ln.strip()],
            "account": self.account.currentText().strip(), "variant": self.variant.text().strip(),
            "quantity": self.qty.value(), "interval": self.interval.value(),
            "max_price": self.maxprice.value(), "start_at": self.start_at.text().strip(),
            "payment": self.payment.currentText().strip(),
            "proxies": [ln.strip() for ln in self.proxy.toPlainText().splitlines() if ln.strip()],
            "alert_only": self.alert_only.isChecked(), "dry_run": self.dry_run.isChecked(),
            "fast": self.fast.isChecked(), "turbo": self.turbo.isChecked(),
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
    def __init__(self, parent, url, role, health_url=""):
        super().__init__(parent)
        self.setWindowTitle("Discord notifications"); self.resize(620, 0)
        form = QFormLayout(self)
        form.addRow(QLabel("Channel → Edit → Integrations → Webhooks → New Webhook → Copy URL"))
        self.url = QLineEdit(url); self.url.setPlaceholderText("https://discord.com/api/webhooks/...")
        self.role = QLineEdit(role); self.role.setPlaceholderText("optional USER or ROLE ID to @ping on stock/order")
        form.addRow("Webhook URL", self.url); form.addRow("Ping user/role ID", self.role)
        self.health = QLineEdit(health_url)
        self.health.setPlaceholderText("optional product URL — checked on startup; alerts if Lazada's layout changed")
        form.addRow("Selector health URL", self.health)
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
        return self.url.text().strip(), self.role.text().strip(), self.health.text().strip()


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


class AlertsDialog(QDialog):
    def __init__(self, parent, desktop_on, sound_on):
        super().__init__(parent)
        self.parent_win = parent
        self.setWindowTitle("Desktop alerts"); self.resize(440, 0)
        form = QFormLayout(self)
        form.addRow(QLabel("Pop a Windows notification + sound on the events that\n"
                           "need you — in stock, order placed, CAPTCHA — for when\n"
                           "you're at the PC but away from Discord."))
        self.desktop = QCheckBox("Show desktop notifications"); self.desktop.setChecked(desktop_on)
        self.sound = QCheckBox("Play alert sound"); self.sound.setChecked(sound_on)
        form.addRow(self.desktop); form.addRow(self.sound)
        row = QHBoxLayout()
        test = QPushButton("Test"); test.clicked.connect(self._test)
        ok = QPushButton("Save"); cancel = QPushButton("Cancel")
        ok.clicked.connect(self.accept); cancel.clicked.connect(self.reject)
        row.addWidget(test); row.addStretch(1); row.addWidget(cancel); row.addWidget(ok)
        form.addRow(row)

    def _test(self):
        if self.sound.isChecked() and desktop_alert:
            desktop_alert.enabled = True
            desktop_alert.play("order")
        if self.desktop.isChecked():
            self.parent_win.show_tray_message("Lazada Bot", "Desktop alerts are working ✓", "order")

    def get(self):
        return self.desktop.isChecked(), self.sound.isChecked()


class OrdersDialog(QDialog):
    """In-app viewer for orders.log (tab-separated: time, product, order#, amount)."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Order history"); self.resize(740, 470)
        lay = QVBoxLayout(self)
        self.summary = QLabel(""); lay.addWidget(self.summary)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Time", "Product", "Order #", "Amount"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        refresh = QPushButton("Refresh"); refresh.clicked.connect(self._load)
        close = QPushButton("Close"); close.clicked.connect(self.accept)
        row.addWidget(refresh); row.addStretch(1); row.addWidget(close)
        lay.addLayout(row)
        self._load()

    def _load(self):
        rows = []
        try:
            with open(ORDERS_FILE, encoding="utf-8") as f:
                for line in f:
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) >= 2:
                        parts += [""] * (4 - len(parts))
                        rows.append(parts[:4])
        except FileNotFoundError:
            rows = []
        except Exception:
            rows = []
        rows.reverse()  # newest first
        self.table.setRowCount(0)
        pending = 0
        for ts, name, order_no, amount in rows:
            if order_no == "pending-payment":
                pending += 1
            r = self.table.rowCount(); self.table.insertRow(r)
            label = "pending payment" if order_no == "pending-payment" else order_no
            for c, val in enumerate([ts, name, label, amount]):
                item = QTableWidgetItem(val)
                if order_no == "pending-payment":
                    item.setForeground(QColor("#faa61a"))
                self.table.setItem(r, c, item)
        total = len(rows)
        self.summary.setText(
            f"{total} order(s) · {total - pending} confirmed · {pending} pending payment"
            if total else "No orders yet — placed orders will be logged here.")


# ─── Main window ──────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Lazada Bot — Multi-Task  v{engine.VERSION}")
        self.resize(1240, 700)
        self.tasks = []; self.proxies = []; self.accounts = []
        self.workers = {}
        self.logged_in = False
        self.webhook_url = ""; self.role_id = ""; self.health_url = ""
        self.otp_queue = queue.Queue()
        self._login_busy = False
        self._refreshing = False
        self.desktop_alerts = True; self.alert_sound = True
        self._last_alert = {}  # task name -> last alert category fired
        self._statuses = {}    # task name -> latest status text (for the summary bar)

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
        if (self.health_url or "").strip():
            threading.Thread(target=self._selector_health_bg, daemon=True).start()

    def _build_ui(self):
        # System-tray icon — used for desktop notification toasts.
        self.tray = None
        try:
            if QSystemTrayIcon.isSystemTrayAvailable():
                icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
                self.tray = QSystemTrayIcon(icon, self)
                self.tray.setToolTip("Lazada Bot")
                self.tray.show()
        except Exception:
            self.tray = None

        central = QWidget(); self.setCentralWidget(central)
        root = QVBoxLayout(central)
        bar = QHBoxLayout(); bar.setSpacing(6)

        # Login control with a colored connection dot.
        self.login_dot = QLabel("●"); self.login_dot.setStyleSheet("color:#ed4245; font-size:14px;")
        self.login_btn = QPushButton("🔐 Login"); self.login_btn.clicked.connect(self.login_clicked)
        self.login_lbl = QLabel("Not logged in")
        bar.addWidget(self.login_dot); bar.addWidget(self.login_btn)
        bar.addWidget(self.login_lbl); bar.addStretch(1)

        # Cluster 1 — run controls.
        start_all = QPushButton("▶ Start All"); start_all.setObjectName("primary")
        start_all.clicked.connect(self.start_all)
        stop_all = QPushButton("■ Stop All"); stop_all.clicked.connect(self.stop_all)
        bar.addWidget(start_all); bar.addWidget(stop_all)
        bar.addWidget(self._vsep())

        # Cluster 2 — task CRUD.
        for text, fn, oid in [("➕ Add", self.add_task, ""), ("✎ Edit", self.edit_task, ""),
                              ("⧉ Dup", self.dup_task, ""), ("🗑 Remove", self.remove_task, "danger")]:
            b = QPushButton(text); b.clicked.connect(fn)
            if oid:
                b.setObjectName(oid)
            bar.addWidget(b)
        bar.addWidget(self._vsep())

        # Cluster 3 — settings menu + the rest.
        settings = QToolButton(); settings.setText("⚙ Settings ▾")
        settings.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(settings)
        for label, fn in [("👤 Accounts…", self.manage_accounts), ("🌐 Proxies…", self.manage_proxies),
                          ("🔔 Discord…", self.manage_webhook), ("🖥 Alerts…", self.manage_alerts)]:
            menu.addAction(label, fn)
        menu.addSeparator()
        menu.addAction("🧪 Self-test", self.run_self_test)
        menu.addAction("📋 Changelog", self.show_changelog)
        settings.setMenu(menu)
        bar.addWidget(settings)
        for text, fn in [("📜 Orders", self.show_orders), ("⬇ Updates", self.check_updates)]:
            b = QPushButton(text); b.clicked.connect(fn); bar.addWidget(b)
        root.addLayout(bar)

        self.empty_hint = QLabel("No tasks yet — click ➕ Add to create your first checkout task.")
        self.empty_hint.setStyleSheet("color:#8a8a8e; padding:6px 2px;")
        root.addWidget(self.empty_hint)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(C_URL, QHeaderView.ResizeMode.Stretch)
        # Status auto-fits the widest pill so longer statuses (purchased, buying…)
        # never clip; the stretched URL column absorbs the width change.
        hh.setSectionResizeMode(C_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setItemDelegateForColumn(C_STATUS, StatusPillDelegate(self.table))
        hh.setSectionResizeMode(C_ACT, QHeaderView.ResizeMode.Fixed)  # room to center the button
        self.table.setColumnWidth(C_ACT, 120)
        vh = self.table.verticalHeader()
        vh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)  # uniform row height
        vh.setDefaultSectionSize(38)
        self.table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.itemChanged.connect(self.on_item_changed)
        root.addWidget(self.table, 3)

        log_head = QHBoxLayout()
        log_head.addWidget(QLabel("Log")); log_head.addStretch(1)
        clear_btn = QPushButton("🧹 Clear"); clear_btn.clicked.connect(self._clear_log)
        log_head.addWidget(clear_btn)
        root.addLayout(log_head)
        self.logview = QTextEdit(); self.logview.setReadOnly(True)
        self.logview.document().setMaximumBlockCount(500)  # cap retained lines (file keeps full)
        mono = QFont("Consolas", 9); mono.setStyleHint(QFont.StyleHint.Monospace)
        self.logview.setFont(mono)
        root.addWidget(self.logview, 2)

        # Summary bar — live run-state counts.
        self.chip_run = self._make_chip(PILL_BLUE)
        self.chip_idle = self._make_chip(PILL_GRAY)
        self.chip_buy = self._make_chip(PILL_GREEN)
        self.chip_err = self._make_chip(PILL_RED)
        for chip in (self.chip_run, self.chip_idle, self.chip_buy, self.chip_err):
            self.statusBar().addWidget(chip)
        self._update_summary()

    def _vsep(self):
        f = QFrame(); f.setFrameShape(QFrame.Shape.VLine)
        f.setStyleSheet("color:#3a3c41;")
        return f

    def _make_chip(self, colors):
        bg, fg = colors
        lbl = QLabel("")
        lbl.setStyleSheet(f"background:{bg}; color:{fg}; border-radius:9px; padding:2px 10px; "
                          "font-weight:bold; margin:2px 1px;")
        return lbl

    def _status_item(self, status):
        """Status cell as a real (non-editable) item — the pill is painted by
        StatusPillDelegate. Full text on hover."""
        it = QTableWidgetItem(status)
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
        it.setToolTip(status)
        return it

    def _action_cell(self, name):
        """A compact Start/Stop button centered in the cell at its natural size
        (stretches on both sides stop it filling the whole cell)."""
        holder = QWidget(); holder.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(holder); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        btn = QPushButton("▶ Start")
        btn.setFixedHeight(26); btn.setFixedWidth(88)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(lambda _, n=name: self.toggle_task(n))
        lay.addStretch(1); lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter); lay.addStretch(1)
        return holder

    def _clear_log(self):
        self.logview.clear()

    def _set_login_dot(self, color):
        self.login_dot.setStyleSheet(f"color:{color}; font-size:14px;")

    def _update_summary(self):
        total = len(self.tasks)
        running = len(self.workers)
        purchased = sum(1 for s in self._statuses.values()
                        if "purchased" in s.lower() or "ordered" in s.lower())
        errors = sum(1 for n, s in self._statuses.items()
                     if n in self.workers and ("error" in s.lower() or "failed" in s.lower()))
        idle = max(0, total - running)
        self.chip_run.setText(f"▶ {running} running")
        self.chip_idle.setText(f"⏸ {idle} idle")
        self.chip_buy.setText(f"✓ {purchased} purchased")
        self.chip_err.setText(f"⚠ {errors} error(s)")

    # ---- persistence ----
    def _read_data(self):
        """Load bot_data.json — DPAPI-sealed via secure_store, transparently
        reading a legacy plaintext file. Returns {} if absent, or None if a file
        exists but can't be read (e.g. sealed on another PC)."""
        if not os.path.exists(DATA_FILE):
            return {}
        try:
            if secure_store:
                data = secure_store.load(DATA_FILE)
            else:
                data = json.load(open(DATA_FILE, encoding="utf-8"))
        except Exception:
            data = None
        return data if isinstance(data, dict) else None

    def _load(self):
        data = self._read_data()
        if data is None:  # file exists but unreadable — don't silently wipe it
            QMessageBox.warning(self, "Settings unreadable",
                                "bot_data.json couldn't be read (was it copied from another PC, "
                                "where it was encrypted?). Starting with empty settings; saving "
                                "will overwrite it.")
            data = {}
        if data:
            try:
                self.tasks = data.get("tasks", [])
                for t in self.tasks:  # migrate old single proxy -> list
                    if "proxies" not in t:
                        t["proxies"] = [t["proxy"]] if t.get("proxy") else []
                self.proxies = data.get("proxies", [])
                self.accounts = data.get("accounts", [])
                self.webhook_url = data.get("webhook", ""); self.role_id = data.get("role", "")
                self.health_url = data.get("health_url", "")
                notifier.set_webhook(self.webhook_url); notifier.set_role(self.role_id)
                self.desktop_alerts = data.get("desktop_alerts", True)
                self.alert_sound = data.get("alert_sound", True)
                if desktop_alert:
                    desktop_alert.enabled = self.alert_sound
            except Exception:
                pass
        if os.path.exists(engine.SESSION_FILE):
            self.logged_in = True
            self.login_lbl.setText("Session found (login to refresh)")
            self._set_login_dot("#faa61a")  # amber: have a session, not freshly verified
        self._refresh_table()

    def _save(self):
        data = {"tasks": self.tasks, "proxies": self.proxies, "accounts": self.accounts,
                "webhook": self.webhook_url, "role": self.role_id, "health_url": self.health_url,
                "desktop_alerts": self.desktop_alerts, "alert_sound": self.alert_sound}
        # DPAPI-seal at rest (webhook URL / tasks), transparently. Falls back to
        # plaintext if secure_store is unavailable so saving never fails.
        if secure_store:
            secure_store.save(DATA_FILE, data)
        else:
            json.dump(data, open(DATA_FILE, "w", encoding="utf-8"), indent=2)

    def _mode(self, t):
        m = "alert" if t.get("alert_only") else ("dry" if t.get("dry_run") else "buy")
        if t.get("fast"):
            m += "·fast"
        if t.get("turbo"):
            m += "·turbo"
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
            name_it = self._cell(t["name"]); name_it.setToolTip(t["name"])
            self.table.setItem(r, C_NAME, name_it)
            if t.get("watchlist"):
                urlcell = f"📋 watch list ({len(t['watchlist'])} URLs)"
                tip = "\n".join(t["watchlist"])
            elif t.get("keyword"):
                urlcell = "🔎 " + t["keyword"]
                tip = "keyword monitor: " + t["keyword"]
            else:
                urlcell = t["url"]
                tip = t["url"]
            url_it = self._cell(urlcell); url_it.setToolTip(tip)
            self.table.setItem(r, C_URL, url_it)
            self.table.setItem(r, C_ACCT, self._cell(t.get("account", "") or "default"))
            self.table.setItem(r, C_VAR, self._cell(t.get("variant", "") or "—", editable=True))
            self.table.setItem(r, C_QTY, self._cell(str(t.get("quantity", 1)), editable=True))
            self.table.setItem(r, C_PROXY, self._cell(proxy_txt))
            self.table.setItem(r, C_INT, self._cell(str(t.get("interval", 8)) + "s", editable=True))
            self.table.setItem(r, C_MODE, self._cell(self._mode(t)))
            self.table.setItem(r, C_STATUS, self._status_item("idle"))
            self.table.setCellWidget(r, C_ACT, self._action_cell(t["name"]))
        self.table.setSortingEnabled(True)
        self._refreshing = False
        self.empty_hint.setVisible(not self.tasks)
        self._update_summary()

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
        self.logview.append(
            f'<span style="color:#6a6a6e;">{ts}</span> '
            f'<span style="color:#8a8a8e;">[{html.escape(who)}]</span> {html.escape(msg)}')
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] [{who}] {msg}\n")
        except Exception:
            pass

    def on_log(self, name, msg):
        self.log_line(name, msg)

    def on_status(self, name, status):
        self._statuses[name] = status
        r = self._row_of(name)
        if r is not None:
            self._refreshing = True
            self.table.setItem(r, C_STATUS, self._status_item(status))
            self._refreshing = False
        self.log_line(name, f"status → {status}")
        self._maybe_alert(name, status)
        if status.startswith("purchased") or status.startswith("checkout") or status.startswith("error"):
            self._set_row_button(name, start=True)
            if status.startswith("purchased") or status.startswith("checkout"):
                self.workers.pop(name, None)
        self._update_summary()

    # ---- desktop alerts ----
    @staticmethod
    def _alert_category(status):
        s = status.lower()
        if "purchased" in s or "ordered" in s:
            return "order"
        if "in stock" in s:
            return "stock"
        if "captcha" in s:
            return "captcha"
        return None

    def _maybe_alert(self, name, status):
        cat = self._alert_category(status)
        # Only fire when the category actually changes, so a status that repeats
        # (stock → checking → stock) doesn't re-alert every poll.
        if not cat or self._last_alert.get(name) == cat:
            return
        self._last_alert[name] = cat
        titles = {"order": "🎉 Order placed", "stock": "🟢 In stock",
                  "captcha": "⚠️ CAPTCHA — solve it"}
        if self.desktop_alerts:
            self.show_tray_message(titles.get(cat, "Lazada Bot"), f"{name}: {status}", cat)
        if self.alert_sound and desktop_alert:
            desktop_alert.enabled = True
            desktop_alert.play(cat)

    def show_tray_message(self, title, message, cat="order"):
        if not self.tray:
            return
        try:
            mi = QSystemTrayIcon.MessageIcon
            icon = mi.Warning if cat == "captcha" else mi.Information
            self.tray.showMessage(title, message, icon, 8000)
        except Exception:
            pass

    def manage_alerts(self):
        dlg = AlertsDialog(self, self.desktop_alerts, self.alert_sound)
        if dlg.exec():
            self.desktop_alerts, self.alert_sound = dlg.get()
            if desktop_alert:
                desktop_alert.enabled = self.alert_sound
            self._save()
            self.log_line("alerts", f"desktop {'on' if self.desktop_alerts else 'off'}, "
                                    f"sound {'on' if self.alert_sound else 'off'}")

    def show_orders(self):
        OrdersDialog(self).exec()

    def _selector_health_bg(self):
        """Startup check that Lazada's key selectors still resolve; alert if not."""
        url = (self.health_url or "").strip()
        if not url:
            return
        ok, missing = engine.selector_health(url, lambda m: self.bridge.log.emit("health", m))
        if ok:
            self.bridge.log.emit("health", "selector health OK ✓")
            return
        msg = "Lazada selectors changed — the bot may fail to buy: " + ", ".join(missing)
        self.bridge.log.emit("health", "⚠️ " + msg)
        try:
            notifier.send_event("⚠️ Selector health check FAILED", description=msg,
                                color=0xE74C3C, ping=True)
        except Exception:
            pass

    def _set_row_button(self, name, start):
        r = self._row_of(name)
        if r is None:
            return
        holder = self.table.cellWidget(r, C_ACT)
        btn = holder.findChild(QPushButton) if holder else None
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

    def login_clicked(self):
        """Let the user pick which account to log in (default = config phone)."""
        if self.accounts:
            choices = ["(default account)"] + [a["label"] for a in self.accounts]
            choice, ok = QInputDialog.getItem(self, "Login", "Log in as which account?",
                                              choices, 0, False)
            if not ok:
                return
            self.do_login("" if choice.startswith("(default") else choice)
        else:
            self.do_login()

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
        self._set_login_dot("#faa61a")  # amber while in progress

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
            self.login_lbl.setText(f"Logged in ({label})")
            self._set_login_dot("#3ba55d")  # green
        else:
            self.login_lbl.setText(f"Login failed ({label})")
            self._set_login_dot("#ed4245")  # red

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
            if not t["name"] or (not t["url"] and not t.get("keyword") and not t.get("watchlist")):
                QMessageBox.warning(self, "Missing", "Name and a URL, Keyword, or Watch list are required."); return
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
        self._statuses.pop(name, None); self._last_alert.pop(name, None)
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
        dlg = WebhookDialog(self, self.webhook_url, self.role_id, self.health_url)
        if dlg.exec():
            self.webhook_url, self.role_id, self.health_url = dlg.get()
            notifier.set_webhook(self.webhook_url); notifier.set_role(self.role_id)
            self._save(); self.log_line("discord", "settings saved")
            if self.health_url:  # run the health check now so the user gets feedback
                threading.Thread(target=self._selector_health_bg, daemon=True).start()

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
        self._last_alert.pop(name, None)
        worker.start()
        self._set_row_button(name, start=False)
        self.log_line(name, "started")
        self._update_summary()

    def stop_task(self, name):
        w = self.workers.pop(name, None)
        if w:
            w.stop(); self.log_line(name, "stopping…")
        self._set_row_button(name, start=True)
        self._statuses[name] = "idle"
        r = self._row_of(name)
        if r is not None:
            self._refreshing = True
            self.table.setItem(r, C_STATUS, self._status_item("idle"))
            self._refreshing = False
        self._update_summary()

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


def _cap_log():
    """Keep bot.log bounded — on startup, if it's over ~2 MB, keep the last 2000 lines."""
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 2_000_000:
            with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.writelines(lines[-2000:])
    except Exception:
        pass


def main():
    _cap_log()
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_QSS)
    w = MainWindow(); w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
