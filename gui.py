"""
QPop setup / status window (tkinter).

`app` is the running qpop module, passed in rather than imported so we share
its live STATUS / PAUSED state (qpop usually runs as __main__).
"""

import ctypes
import os
import threading
from urllib.parse import urlparse
import tkinter as tk
from tkinter import messagebox

import qrcode
from PIL import Image, ImageTk

import steam_setup

APP_STORE_URL = "https://apps.apple.com/app/ntfy/id1625396347"
PLAY_STORE_URL = "https://play.google.com/store/apps/details?id=io.heckel.ntfy"

BG = "#14151f"
CARD = "#1e2030"
FG = "#e8e9f3"
MUTED = "#9a9cb8"
ACCENT = "#5b5bf7"
ACCENT_HOVER = "#7373ff"
OK = "#3ecf8e"
WARN = "#ffb020"

FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI Semibold", 11)
FONT_TITLE = ("Segoe UI Semibold", 17)
FONT_MONO = ("Consolas", 12)


def qr_image(data, px):
    q = qrcode.QRCode(border=2, box_size=8, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(data)
    q.make(fit=True)
    img = q.make_image(fill_color="black", back_color="white").get_image().convert("RGB")
    return img.resize((px, px), Image.NEAREST)


def run_in_background(widget, fn, done):
    """Run fn() off the UI thread, then call done(result_or_exception) on the UI thread."""
    box = {}
    t = threading.Thread(target=lambda: box.setdefault("r", _safe(fn)), daemon=True)
    t.start()

    def poll():
        if t.is_alive():
            widget.after(150, poll)
        else:
            done(box.get("r"))
    poll()


def _safe(fn):
    try:
        return fn()
    except Exception as e:
        return e


def dark_title_bar(win):
    try:
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        val = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass


class Button(tk.Label):
    """Flat button with hover state (tk.Button can't be fully styled on Windows)."""

    def __init__(self, parent, text, command, primary=True, **kw):
        self.bg = ACCENT if primary else "#2c2f45"
        self.hover = ACCENT_HOVER if primary else "#3a3e5a"
        super().__init__(parent, text=text, bg=self.bg, fg="white", font=FONT_BOLD,
                         padx=14, pady=6, cursor="hand2", **kw)
        self.command = command
        self.bind("<Button-1>", lambda e: self.command())
        self.bind("<Enter>", lambda e: self.config(bg=self.hover))
        self.bind("<Leave>", lambda e: self.config(bg=self.bg))


class Window:
    def __init__(self, root, app, cfg):
        self.app = app
        self.cfg = cfg
        self.win = tk.Toplevel(root)
        self.win.title("QPop")
        self.win.configure(bg=BG)
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", self.win.withdraw)
        self._logo = ImageTk.PhotoImage(app.draw_logo(app.COLORS["normal"]))
        self.win.iconphoto(False, self._logo)
        dark_title_bar(self.win)
        self._build()
        self.refresh_deadlock()
        self._fix_size()
        self.set_platform(self.cfg.get("phone", "iphone"), save=False)
        self._tick()

    # ------------------------------------------------------------------ layout

    def _card(self, parent, title, number=None, **pack):
        outer = tk.Frame(parent, bg=CARD, padx=18, pady=14)
        outer.pack(fill="both", pady=(0, 12), **pack)
        head = tk.Frame(outer, bg=CARD)
        head.pack(fill="x", pady=(0, 8))
        if number:
            tk.Label(head, text=str(number), bg=ACCENT, fg="white", font=FONT_BOLD, width=2).pack(side="left", padx=(0, 10))
        tk.Label(head, text=title, bg=CARD, fg=FG, font=FONT_BOLD).pack(side="left")
        outer.head = head
        return outer

    def _text(self, parent, text, color=MUTED, **kw):
        lbl = tk.Label(parent, text=text, bg=CARD, fg=color, font=FONT, justify="left", anchor="w", **kw)
        lbl.pack(fill="x")
        return lbl

    def _build(self):
        self.body = tk.Frame(self.win, bg=BG, padx=20, pady=18)
        self.body.pack(fill="both")

        # Header
        head = tk.Frame(self.body, bg=BG)
        head.pack(fill="x", pady=(0, 16))
        self._logo_big = ImageTk.PhotoImage(self.app.draw_logo(self.app.COLORS["normal"]).resize((48, 48)))
        tk.Label(head, image=self._logo_big, bg=BG).pack(side="left", padx=(0, 12))
        titles = tk.Frame(head, bg=BG)
        titles.pack(side="left")
        tk.Label(titles, text="QPop", bg=BG, fg=FG, font=FONT_TITLE).pack(anchor="w")
        tk.Label(titles, text="A ping on your phone when your queue pops", bg=BG, fg=MUTED, font=FONT).pack(anchor="w")

        cols = tk.Frame(self.body, bg=BG)
        cols.pack(fill="both")
        left = tk.Frame(cols, bg=BG)
        left.pack(side="left", fill="both", padx=(0, 12))
        right = tk.Frame(cols, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        # 1. Phone
        topic = self.cfg["ntfy_topic"]
        card = self._card(left, "Connect your phone", 1, expand=True)
        card.config(highlightthickness=2, highlightbackground=CARD, highlightcolor=CARD)
        self.phone_card = card

        # iPhone | Android switch, top-right of the card
        seg = tk.Frame(card.head, bg=CARD)
        seg.pack(side="right")
        self.platform_btns = {}
        for key, label in (("iphone", "iPhone"), ("android", "Android")):
            b = tk.Label(seg, text=label, font=FONT, fg="white", padx=12, pady=3, cursor="hand2")
            b.pack(side="left")
            b.bind("<Button-1>", lambda e, k=key: self.set_platform(k))
            self.platform_btns[key] = b

        qrs = tk.Frame(card, bg=CARD)
        qrs.pack(pady=(2, 10))
        self.qr_labels = []
        for col in range(2):
            f = tk.Frame(qrs, bg=CARD)
            f.grid(row=0, column=col, padx=14)
            img = tk.Label(f, bg=CARD)
            img.pack()
            cap = tk.Label(f, bg=CARD, fg=MUTED, font=FONT)
            cap.pack(pady=(6, 0))
            self.qr_labels.append((img, cap))

        self.topic_hint = self._text(card, "", wraplength=420)
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", pady=(6, 10))
        self.topic_entry = tk.Entry(row, font=FONT_MONO, bg="#12131c", fg=FG, readonlybackground="#12131c",
                                    relief="flat", insertbackground=FG, justify="center")
        self.topic_entry.insert(0, topic)
        self.topic_entry.config(state="readonly")
        self.topic_entry.pack(side="left", fill="x", expand=True, ipady=6)
        self.copy_btn = Button(row, "Copy", self.copy_topic, primary=False)
        self.copy_btn.pack(side="left", padx=(8, 0))

        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x")
        Button(row, "Send test notification", self.send_test).pack(side="left")
        Button(row, "New phone?", self.start_relink, primary=False).pack(side="right")
        self.test_result = tk.Label(row, text="", bg=CARD, fg=OK, font=FONT)
        self.test_result.pack(side="left", padx=12)
        self.platform_tip = self._text(card, "", wraplength=420)
        self.platform_tip.pack_configure(pady=(10, 0))


        # 2. Deadlock
        card = self._card(right, "Deadlock", 2)
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x")
        self.dl_status = tk.Label(row, text="Checking...", bg=CARD, fg=MUTED, font=FONT, anchor="w", justify="left")
        self.dl_status.pack(side="left", fill="x", expand=True)
        self.dl_btn = Button(row, "Add it for me", self.fix_deadlock)
        self.dl_live = self._text(card, "")

        # 3. League
        card = self._card(right, "League of Legends / TFT", 3)
        self._text(card, "No setup needed - just open the League client.", color=FG)
        self.lol_live = self._text(card, "")

        # Options
        card = self._card(right, "Options")
        self.startup_var = tk.BooleanVar(value=self.app.startup_enabled())
        self.pause_var = tk.BooleanVar(value=self.app.PAUSED.is_set())
        for text, var, cmd in [("Start with Windows", self.startup_var, self.toggle_startup),
                               ("Pause notifications", self.pause_var, self.toggle_pause)]:
            tk.Checkbutton(card, text=text, variable=var, command=cmd, bg=CARD, fg=FG, font=FONT,
                           selectcolor="#12131c", activebackground=CARD, activeforeground=FG,
                           anchor="w", cursor="hand2").pack(fill="x")

        self.footer = tk.Label(self.body, bg=BG, fg=MUTED, font=FONT)
        self.footer.pack(pady=(4, 0))
        self.footer.bind("<Button-1>", lambda e: self.app.UPDATE and os.startfile(self.app.UPDATE["url"]))

    # ------------------------------------------------------------------ behaviour

    def _fix_size(self):
        """Size the window for whichever platform layout is bigger, so switching doesn't make it jump."""
        sizes = []
        for p in ("android", "iphone"):
            self.set_platform(p, save=False)
            self.win.update_idletasks()
            sizes.append((self.win.winfo_reqwidth(), self.win.winfo_reqheight()))
        self.win.geometry(f"{max(w for w, _ in sizes)}x{max(h for _, h in sizes)}")

    def _subscribe_link(self):
        """ntfy:// deep link - opens the Android app and subscribes in one go."""
        server = urlparse(self.cfg["ntfy_server"])
        link = f"ntfy://{server.netloc}/{self.cfg['ntfy_topic']}?display=QPop"
        return link + ("&secure=false" if server.scheme == "http" else "")

    def set_platform(self, platform, save=True):
        if platform == "android":
            qrs = [(PLAY_STORE_URL, "Scan to get the ntfy app"),
                   (self._subscribe_link(), "Then scan to subscribe")]
            hint = "Or, in ntfy, tap  +  and type this topic:"
            tip = ("Tip: set ntfy's battery usage to Unrestricted (Settings > Apps > ntfy > Battery) "
                   "so alerts aren't delayed.")
        else:
            platform = "iphone"
            qrs = [(APP_STORE_URL, "Scan to get the ntfy app"),
                   (self.cfg["ntfy_topic"], "Scan to copy your topic")]
            hint = "In ntfy, tap  +  and paste or type this topic:"
            tip = ("Tip: in Settings > Notifications > ntfy, turn on Time Sensitive Notifications "
                   "so alerts get through Focus modes.")

        self._qr_images = [ImageTk.PhotoImage(qr_image(data, 150)) for data, _ in qrs]
        for (img_lbl, cap_lbl), photo, (_, caption) in zip(self.qr_labels, self._qr_images, qrs):
            img_lbl.config(image=photo)
            cap_lbl.config(text=caption)
        self.topic_hint.config(text=hint)
        self.platform_tip.config(text=tip)
        for key, b in self.platform_btns.items():
            b.config(bg=ACCENT if key == platform else "#2c2f45")

        self.platform = platform
        if save and self.cfg.get("phone") != platform:
            self.cfg["phone"] = platform
            self.app.save_config(self.cfg)

    def _center(self):
        """Centre on the primary monitor's work area (above the taskbar)."""
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        rect = (ctypes.c_long * 4)()
        ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
        x = rect[0] + max(0, (rect[2] - rect[0] - w) // 2)
        y = rect[1] + max(0, (rect[3] - rect[1] - h) // 2)
        # Tk skips geometry() calls it thinks are no-ops, so move the real window directly.
        hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id())
        ctypes.windll.user32.SetWindowPos(hwnd, 0, x, y, 0, 0, 0x0001 | 0x0004 | 0x0010)  # NOSIZE|NOZORDER|NOACTIVATE

    def _settle(self, tries):
        """Windows can minimise or re-place a new window behind Tk's back (e.g. when launched
        from a hidden process), and Tk's own state()/geometry() then think nothing changed.
        So for a short while, fix it via the Win32 API directly."""
        hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id())
        if ctypes.windll.user32.IsIconic(hwnd):
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        if not self._centered:
            self._center()
            if tries == 1:
                self._centered = True
        if tries > 1:
            self.win.after(100, self._settle, tries - 1)

    def show(self):
        self._centered = getattr(self, "_centered", False)
        self.win.deiconify()
        self.win.update_idletasks()
        self._settle(20)  # watch for ~2 seconds
        self.win.lift()
        self.win.attributes("-topmost", True)  # Windows won't always let a background app take focus
        self.win.after(300, lambda: self.win.attributes("-topmost", False))
        self.win.focus_force()
        self.refresh_deadlock()
        self.startup_var.set(self.app.startup_enabled())

    def _tick(self):
        """Live status lines, refreshed every second."""
        self.lol_live.config(text=f"Status: {self.app.STATUS['League']}")
        self.dl_live.config(text=f"Status: {self.app.STATUS['Deadlock']}")
        if self.app.UPDATE:
            self.footer.config(text=f"Update available: v{self.app.UPDATE['version']} - click to download",
                               fg=ACCENT_HOVER, cursor="hand2")
        else:
            self.footer.config(text=f"Closing this window keeps QPop running in your tray.   ·   "
                                    f"v{self.app.__version__}", fg=MUTED, cursor="")
        if self.pause_var.get() != self.app.PAUSED.is_set():
            self.pause_var.set(self.app.PAUSED.is_set())
        self.win.after(1000, self._tick)

    def copy_topic(self):
        self.win.clipboard_clear()
        self.win.clipboard_append(self.cfg["ntfy_topic"])
        self.copy_btn.config(text="Copied!")
        self.win.after(1500, lambda: self.copy_btn.config(text="Copy"))

    def send_test(self):
        self.test_result.config(text="Sending...", fg=MUTED)
        run_in_background(
            self.win,
            lambda: self.app.notify(self.cfg, "QPop test", "If you can see this, you're all set!", force=True),
            lambda ok: self.test_result.config(
                text="Sent! Check your phone." if ok is True else "Couldn't send - check your internet.",
                fg=OK if ok is True else WARN),
        )

    def refresh_deadlock(self):
        state = steam_setup.has_option("-condebug")
        if state is None:
            self.dl_status.config(text="Deadlock isn't installed for your Steam account.", fg=MUTED)
            self.dl_btn.pack_forget()
        elif state:
            self.dl_status.config(text="✓  Ready - the -condebug launch option is set.", fg=OK)
            self.dl_btn.pack_forget()
        else:
            self.dl_status.config(text="Needs the -condebug launch option so QPop\ncan see when a match loads.", fg=WARN)
            self.dl_btn.pack(side="right")

    def fix_deadlock(self):
        if self.app.process_running("deadlock.exe"):
            messagebox.showinfo("QPop", "Close Deadlock first, then try again.", parent=self.win)
            return
        steam_was_running = self.app.process_running("steam.exe")
        if steam_was_running and not messagebox.askokcancel(
            "QPop",
            "Steam needs to close for a moment to change Deadlock's launch options.\n\n"
            "QPop will close Steam, add -condebug, and reopen Steam.",
            parent=self.win,
        ):
            return
        self.dl_status.config(text="Closing Steam..." if steam_was_running else "Updating...", fg=MUTED)
        self.dl_btn.pack_forget()

        def work():
            if not steam_setup.shutdown_steam():
                raise RuntimeError("Steam didn't close. Close it manually and try again.")
            steam_setup.add_launch_option("-condebug")
            if steam_was_running:
                steam_setup.start_steam()
            return True

        def done(result):
            if isinstance(result, Exception):
                messagebox.showerror("QPop", f"Couldn't update Deadlock:\n{result}", parent=self.win)
            self.refresh_deadlock()

        run_in_background(self.win, work, done)

    def toggle_startup(self):
        try:
            self.app.set_startup(self.startup_var.get())
        except Exception as e:
            messagebox.showerror("QPop", f"Couldn't change startup setting:\n{e}", parent=self.win)
        self.startup_var.set(self.app.startup_enabled())

    def toggle_pause(self):
        (self.app.PAUSED.set if self.pause_var.get() else self.app.PAUSED.clear)()

    # ------------------------------------------------------------------ re-link

    def start_relink(self):
        """Ask whether the new phone joins the current topic or replaces the old phone."""
        dlg = tk.Toplevel(self.win)
        dlg.title("Link a new phone")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.transient(self.win)
        dlg.iconphoto(False, self._logo)
        dark_title_bar(dlg)

        body = tk.Frame(dlg, bg=BG, padx=24, pady=20)
        body.pack()
        tk.Label(body, text="Link a new phone", bg=BG, fg=FG, font=FONT_TITLE).pack(anchor="w")
        tk.Label(body, text="Should your current phone keep getting alerts?", bg=BG, fg=MUTED,
                 font=FONT).pack(anchor="w", pady=(2, 14))

        def option(title, desc, command):
            box = tk.Frame(body, bg=CARD, padx=16, pady=12)
            box.pack(fill="x", pady=(0, 10))
            Button(box, title, command).pack(anchor="w")
            tk.Label(box, text=desc, bg=CARD, fg=MUTED, font=FONT, justify="left",
                     wraplength=380).pack(anchor="w", pady=(8, 0))

        def keep():
            dlg.destroy()
            self._highlight_phone("Scan these codes with your new phone.")

        def replace():
            dlg.destroy()
            self.app.replace_topic(self.cfg)
            self.topic_entry.config(state="normal")
            self.topic_entry.delete(0, "end")
            self.topic_entry.insert(0, self.cfg["ntfy_topic"])
            self.topic_entry.config(state="readonly")
            self.set_platform(self.platform, save=False)  # rebuild QR codes for the new topic
            self._highlight_phone("New topic ready - scan with your new phone.")

        option("Yes, keep both phones",
               "Your new phone subscribes to the same topic. Both phones get alerts.", keep)
        option("No, replace my old phone",
               "Makes a new private topic. Your old phone gets one last message, then no more "
               "alerts. Use this if the old phone was sold, lost or given away.", replace)
        Button(body, "Cancel", dlg.destroy, primary=False).pack(anchor="e", pady=(4, 0))

        # Centre over the main window and make it modal.
        dlg.update_idletasks()
        x = self.win.winfo_rootx() + (self.win.winfo_width() - dlg.winfo_reqwidth()) // 2
        y = self.win.winfo_rooty() + (self.win.winfo_height() - dlg.winfo_reqheight()) // 3
        dlg.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        dlg.grab_set()
        dlg.focus_force()

    def _highlight_phone(self, message):
        """Light up the phone card for a few seconds so it's obvious where to look."""
        self.phone_card.config(highlightbackground=ACCENT, highlightcolor=ACCENT)
        self.test_result.config(text="", fg=OK)
        self.topic_hint.config(text=message, fg=OK)

        def reset():
            self.phone_card.config(highlightbackground=CARD, highlightcolor=CARD)
            self.set_platform(self.platform, save=False)
            self.topic_hint.config(fg=MUTED)
        self.win.after(6000, reset)
