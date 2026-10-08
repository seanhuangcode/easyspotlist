"""The little always-on-top pop-up in the corner of the screen."""

import io
import queue
import sys
import threading
import tkinter as tk

try:
    from PIL import Image, ImageTk
except ImportError:  # album art is optional
    Image = None

BG = "#181818"
BORDER = "#333333"
FG = "#ffffff"
SUB = "#a7a7a7"
GREEN = "#1ed760"
GREEN_HOVER = "#3be477"
BTN = "#2a2a2a"
BTN_HOVER = "#3a3a3a"
NEW_PREFIX = "+ New: "

IS_MAC = sys.platform == "darwin"
FONT = "Helvetica Neue" if IS_MAC else "Segoe UI"
# Tk on macOS draws 1 point as 1 pixel (Windows: 1.33px), so Mac fonts need bigger numbers to match.
FONT_SCALE = 4 / 3 if IS_MAC else 1


def _enable_dpi_awareness():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def _work_area(root):
    """Screen area minus the taskbar, so the pop-up sits just above it."""
    try:
        import ctypes
        from ctypes import wintypes
        rect = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
        return rect.right, rect.bottom
    except Exception:
        return root.winfo_screenwidth(), root.winfo_screenheight() - 48


def _foreground_window():
    try:
        import ctypes
        return ctypes.windll.user32.GetForegroundWindow()
    except Exception:
        return None


def _dont_steal_focus(win, previous_foreground):
    """Keep whatever you were typing in focused: mark the pop-up as non-activating and
    hand focus back if showing it grabbed focus anyway."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(win.winfo_id())
        GWL_EXSTYLE, WS_EX_NOACTIVATE = -20, 0x08000000
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, user32.GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_NOACTIVATE)
    except Exception:
        pass
    _restore_foreground(previous_foreground)


def _restore_foreground(previous_foreground):
    try:
        import ctypes
        if previous_foreground and ctypes.windll.user32.GetForegroundWindow() != previous_foreground:
            ctypes.windll.user32.SetForegroundWindow(previous_foreground)
    except Exception:
        pass


def _corner(root, w, h, margin):
    """Where the pop-up goes: bottom-right above the taskbar on Windows, top-right under the
    menu bar on Mac (where macOS shows its own notifications)."""
    if IS_MAC:
        return root.winfo_screenwidth() - w - margin, 38 + margin
    right, bottom = _work_area(root)
    return right - w - margin, bottom - h - margin


def _mac_dont_steal_focus(win):
    """macOS version of WS_EX_NOACTIVATE: a floating window that doesn't take focus (same trick IDLE uses)."""
    if IS_MAC:
        try:
            win.tk.call("::tk::unsupported::MacWindowStyle", "style", win._w, "help", "noActivates")
        except tk.TclError:
            pass


def _truncate(text, n):
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


class PopupUI:
    def __init__(self):
        _enable_dpi_awareness()
        previous_foreground = _foreground_window()
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.update()
        _restore_foreground(previous_foreground)  # the hidden main window grabs focus on creation
        # Windows: grow pixel sizes with display scaling. Mac: Retina scaling is automatic.
        self.scale = 1.0 if IS_MAC else self.root.winfo_fpixels("1i") / 96
        self._calls = queue.Queue()
        self.win = None
        self.uri = None
        self.busy = False
        self.root.after(100, self._drain)

    # ---------- threading: other threads hand work to the UI thread via post() ----------

    def post(self, fn):
        self._calls.put(fn)

    def _drain(self):
        while True:
            try:
                fn = self._calls.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception as e:
                print(f"Pop-up error: {e!r}")
        self.root.after(100, self._drain)

    def run(self):
        self.root.mainloop()

    def quit(self):
        self.root.quit()

    # ---------- pop-up ----------

    def px(self, v):
        return int(v * self.scale)

    def font(self, size, *style):
        return (FONT, round(size * FONT_SCALE), *style)

    def show(self, pick, choices, selected, on_add, timeout=0):
        """
        pick: {"uri", "title", "artist", "reason", "image": bytes or None}
        choices: playlist names for the dropdown; selected: the one pre-selected.
        on_add(choice) -> message to show. Runs on a background thread; raise to report an error.
        """
        self.close(fade=False)
        self.uri = pick["uri"]
        self.busy = False
        previous_foreground = _foreground_window()

        win = tk.Toplevel(self.root, bg=BORDER)
        self.win = win
        win.overrideredirect(True)
        _mac_dont_steal_focus(win)
        win.attributes("-topmost", True)
        win.attributes("-alpha", 0.0)

        card = tk.Frame(win, bg=BG, padx=self.px(14), pady=self.px(12))
        card.pack(padx=1, pady=1, fill="both", expand=True)
        card.columnconfigure(1, weight=1)

        art_size = self.px(76)
        self._art = None
        if Image and pick.get("image"):
            try:
                img = Image.open(io.BytesIO(pick["image"])).convert("RGB").resize((art_size, art_size), Image.LANCZOS)
                self._art = ImageTk.PhotoImage(img, master=win)
            except Exception:
                pass
        if self._art:
            tk.Label(card, image=self._art, bg=BG, bd=0).grid(row=0, column=0, rowspan=4, sticky="nw", padx=(0, self.px(12)))

        tk.Label(card, text=pick.get("header", "VIBE PICK"), fg=GREEN, bg=BG, font=self.font(8, "bold")).grid(row=0, column=1, sticky="w")
        close = tk.Label(card, text="✕", fg=SUB, bg=BG, font=self.font(10), cursor="hand2")
        close.grid(row=0, column=2, sticky="ne")
        close.bind("<Button-1>", lambda e: self.close())
        close.bind("<Enter>", lambda e: close.config(fg=FG))
        close.bind("<Leave>", lambda e: close.config(fg=SUB))

        tk.Label(card, text=_truncate(pick["title"], 38), fg=FG, bg=BG, font=self.font(12, "bold"),
                 anchor="w").grid(row=1, column=1, columnspan=2, sticky="w")
        tk.Label(card, text=_truncate(pick["artist"], 44), fg=SUB, bg=BG, font=self.font(10),
                 anchor="w").grid(row=2, column=1, columnspan=2, sticky="w")
        if pick.get("reason"):
            tk.Label(card, text=_truncate(pick["reason"], 52), fg=SUB, bg=BG, font=self.font(8, "italic"),
                     anchor="w").grid(row=3, column=1, columnspan=2, sticky="w")

        actions = tk.Frame(card, bg=BG)
        actions.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(self.px(10), 0))
        self._actions = actions

        tk.Label(actions, text="Add to playlist?", fg=FG, bg=BG, font=self.font(9)).pack(side="left")

        var = tk.StringVar(value=selected)
        menu_btn = tk.OptionMenu(actions, var, *choices) if choices else tk.OptionMenu(actions, var, "")
        menu_btn.config(bg=BTN, fg=FG, activebackground=BTN_HOVER, activeforeground=FG, font=self.font(9),
                        relief="flat", bd=0, highlightthickness=0, width=18, anchor="w", cursor="hand2",
                        indicatoron=True)
        menu_btn["menu"].config(bg=BTN, fg=FG, activebackground=GREEN, activeforeground="#000000",
                                font=self.font(9), bd=0)
        menu_btn.pack(side="left", padx=(self.px(8), self.px(6)), ipady=self.px(2))
        if not IS_MAC:
            # Windows dropdown menus only close properly if their window has focus; you clicked it, so take it.
            menu_btn.bind("<ButtonPress-1>", lambda e: win.focus_force(), add=True)

        no_btn = self._button(actions, "No", BTN, BTN_HOVER, FG, lambda: self.close())
        no_btn.pack(side="right")
        yes_btn = self._button(actions, "Yes", GREEN, GREEN_HOVER, "#000000",
                               lambda: self._add_clicked(win, var.get(), on_add))
        yes_btn.pack(side="right", padx=(0, self.px(6)))

        win.update_idletasks()
        x, y = _corner(self.root, win.winfo_reqwidth(), win.winfo_reqheight(), self.px(16))
        win.geometry(f"+{x}+{y}")
        win.update()
        _dont_steal_focus(win, previous_foreground)
        self._fade(win, 0.0, 1.0, 0.12)

        if timeout:
            win.after(int(timeout * 1000), lambda: self.win is win and not self.busy and self.close())

    def _button(self, parent, text, bg, hover, fg, command):
        b = tk.Label(parent, text=text, bg=bg, fg=fg, font=self.font(9, "bold"), cursor="hand2",
                     padx=self.px(14), pady=self.px(4))
        b.bind("<Button-1>", lambda e: command())
        b.bind("<Enter>", lambda e: b.config(bg=hover))
        b.bind("<Leave>", lambda e: b.config(bg=bg))
        return b

    def _add_clicked(self, win, choice, on_add):
        if self.busy or not choice:
            return
        self.busy = True
        self._set_status(win, "Adding…", SUB)

        def work():
            try:
                msg = on_add(choice)
                self.post(lambda: self._done(win, msg))
            except Exception as e:
                msg = f"Couldn't add it: {e}"
                self.post(lambda: self._failed(win, msg))

        threading.Thread(target=work, daemon=True).start()

    def _set_status(self, win, text, color):
        if self.win is not win:
            return
        for child in self._actions.winfo_children():
            child.destroy()
        tk.Label(self._actions, text=_truncate(text, 60), fg=color, bg=BG,
                 font=self.font(9, "bold")).pack(side="left", pady=self.px(4))

    def _done(self, win, text):
        self._finish(win, text, GREEN, 2200)

    def _failed(self, win, text):
        self._finish(win, text, "#f15e6c", 6000)

    def _finish(self, win, text, color, close_after_ms):
        if self.win is not win:  # user closed it, or a newer pop-up replaced it
            return
        self.busy = False
        self._set_status(win, text, color)
        win.after(close_after_ms, lambda: self.win is win and self.close())

    def close_unless(self, uri):
        """Song changed: close an unanswered pop-up that's about a different song."""
        if self.win and self.uri != uri and not self.busy:
            self.close()

    def close(self, fade=True):
        win, self.win, self.uri = self.win, None, None
        if not win:
            return
        if fade:
            self._fade(win, float(win.attributes("-alpha")), 0.0, -0.15, then=win.destroy)
        else:
            win.destroy()

    def _fade(self, win, alpha, target, step, then=None):
        try:
            alpha = min(target, alpha + step) if step > 0 else max(target, alpha + step)
            win.attributes("-alpha", alpha)
            if alpha != target:
                win.after(15, lambda: self._fade(win, alpha, target, step, then))
            elif then:
                then()
        except tk.TclError:
            pass  # window already gone
