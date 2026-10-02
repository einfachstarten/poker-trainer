"""Crop region selector — runs as subprocess to avoid rumps/tkinter conflict."""

from __future__ import annotations

import json
import subprocess
import sys
import os
import log

L = log.get("selector")


def _selector_script_path() -> str:
    """Resolve path to selector.py — handle both dev mode and py2app bundle."""
    # py2app bundle: selector.py is shipped as a resource via DATA_FILES
    resource_path = os.environ.get("RESOURCEPATH")
    if resource_path:
        bundled = os.path.join(resource_path, "selector.py")
        if os.path.exists(bundled):
            return bundled
    # Dev mode: alongside this module on disk
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "selector.py")


SELECTOR_SCRIPT = _selector_script_path()


def select_region() -> dict | None:
    """Launch selector as subprocess, return region dict or None."""
    L.info(f"Starte Selector als Subprocess: {SELECTOR_SCRIPT}")
    try:
        venv_python = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "bin", "python")
        if not os.path.exists(venv_python):
            venv_python = sys.executable

        result = subprocess.run(
            [venv_python, SELECTOR_SCRIPT],
            capture_output=True, text=True, timeout=60,
        )
        stdout = result.stdout.strip()
        L.info(f"Selector stdout: {stdout}")
        if result.stderr:
            L.debug(f"Selector stderr: {result.stderr.strip()}")

        if stdout and stdout != "None":
            region = json.loads(stdout)
            L.info(f"Region empfangen: {region}")
            return region
        L.info("Selector abgebrochen (kein Ergebnis)")
        return None
    except subprocess.TimeoutExpired:
        L.warning("Selector Timeout (60s)")
        return None
    except Exception as e:
        L.error(f"Selector Error: {e}")
        return None


# --- Standalone mode: when run as subprocess ---
if __name__ == "__main__":
    import tkinter as tk
    from Quartz import CGGetActiveDisplayList, CGDisplayBounds

    region_result = None

    err, displays, count = CGGetActiveDisplayList(16, None, None)
    if err != 0 or not count:
        print("None")
        sys.exit(0)

    bounds_list = [CGDisplayBounds(d) for d in displays[:count]]
    min_x = int(min(b.origin.x for b in bounds_list))
    min_y = int(min(b.origin.y for b in bounds_list))
    max_x = int(max(b.origin.x + b.size.width for b in bounds_list))
    max_y = int(max(b.origin.y + b.size.height for b in bounds_list))
    union_w, union_h = max_x - min_x, max_y - min_y

    root = tk.Tk()
    root.title("Poker Trainer — Region wählen")
    # Single-display fast path: use Tk's own screen metrics — guaranteed to
    # match Tk's pixel grid (macOS Retina point-vs-pixel mismatches have
    # caused the selector window to land off-center on multi-resolution setups).
    if count == 1 and min_x == 0 and min_y == 0:
        union_w = root.winfo_screenwidth()
        union_h = root.winfo_screenheight()

    # Order matters on macOS: size+position FIRST (while window is still
    # decorated), then borderless + topmost + alpha. Otherwise the window
    # manager occasionally ignores the geometry call.
    root.geometry(f"{union_w}x{union_h}+{min_x}+{min_y}")
    root.update_idletasks()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    # Semi-transparent overlay so the live poker table stays visible underneath
    # — far more reliable than CGWindowListCreateImage, which on macOS 14+ often
    # captures only the desktop for GPU-accelerated apps (browsers, games).
    root.attributes("-alpha", 0.45)
    root.lift()
    root.focus_force()
    root.update_idletasks()
    # macOS pushes overrideredirect Tk windows below the menu bar; the canvas's
    # on-screen origin is therefore not (min_x, min_y). Read the real position
    # so canvas coords map back to global Quartz coords correctly.
    real_x = root.winfo_rootx()
    real_y = root.winfo_rooty()

    canvas = tk.Canvas(root, width=union_w, height=union_h,
                       highlightthickness=0, cursor="crosshair", bg="#101018")
    canvas.pack(fill=tk.BOTH, expand=True)

    canvas.create_text(
        union_w // 2, 40,
        text="Ziehe ein Rechteck über den Poker-Tisch. ESC = Abbrechen",
        fill="white", font=("Helvetica", 20),
    )

    state = {"start_x": 0, "start_y": 0, "rect_id": None}

    def on_press(event):
        state["start_x"] = event.x
        state["start_y"] = event.y
        if state["rect_id"]:
            canvas.delete(state["rect_id"])
        state["rect_id"] = canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline="lime", width=2,
        )

    def on_drag(event):
        if state["rect_id"]:
            canvas.coords(state["rect_id"],
                          state["start_x"], state["start_y"],
                          event.x, event.y)

    def on_release(event):
        global region_result
        x1, y1 = state["start_x"], state["start_y"]
        x2, y2 = event.x, event.y
        x, y = min(x1, x2), min(y1, y2)
        w, h = abs(x2 - x1), abs(y2 - y1)
        if w > 20 and h > 20:
            # Window-local canvas coords → global screen coords
            region_result = {
                "x": int(x + min_x),
                "y": int(y + min_y),
                "w": int(w),
                "h": int(h),
            }
            root.destroy()

    def on_escape(event):
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", on_escape)

    root.mainloop()
    print(json.dumps(region_result) if region_result else "None")
