"""Crop region selector — runs as subprocess to avoid rumps/tkinter conflict."""

from __future__ import annotations

import json
import subprocess
import sys
import os
import log

L = log.get("selector")

SELECTOR_SCRIPT = os.path.join(os.path.dirname(__file__), "selector.py")


def select_region() -> dict | None:
    """Launch selector as subprocess, return region dict or None."""
    L.info("Starte Selector als Subprocess...")
    try:
        venv_python = os.path.join(os.path.dirname(__file__), ".venv", "bin", "python")
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
    from PIL import Image, ImageTk
    from Quartz import (
        CGDisplayBounds, CGMainDisplayID,
        CGRectMake, CGWindowListCreateImage,
        kCGWindowListOptionOnScreenOnly, kCGNullWindowID, kCGWindowImageDefault,
    )
    from Quartz.CoreGraphics import (
        CGImageGetWidth, CGImageGetHeight, CGImageGetBytesPerRow,
        CGDataProviderCopyData, CGImageGetDataProvider,
    )
    import numpy as np

    region_result = None

    bounds = CGDisplayBounds(CGMainDisplayID())
    sw, sh = int(bounds.size.width), int(bounds.size.height)

    # Take screenshot of full screen as background
    rect = CGRectMake(0, 0, sw, sh)
    cg_image = CGWindowListCreateImage(
        rect, kCGWindowListOptionOnScreenOnly, kCGNullWindowID, kCGWindowImageDefault,
    )
    width = CGImageGetWidth(cg_image)
    height = CGImageGetHeight(cg_image)
    bpr = CGImageGetBytesPerRow(cg_image)
    data = CGDataProviderCopyData(CGImageGetDataProvider(cg_image))
    arr = np.frombuffer(data, dtype=np.uint8).reshape((height, bpr // 4, 4))
    arr = arr[:height, :width, [2, 1, 0]]  # BGRA → RGB
    bg_image = Image.fromarray(arr)
    # Resize to logical screen size (Retina)
    bg_image = bg_image.resize((sw, sh), Image.LANCZOS)

    root = tk.Tk()
    root.title("Poker Trainer — Region wählen")
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.lift()
    root.focus_force()

    canvas = tk.Canvas(root, width=sw, height=sh, highlightthickness=0, cursor="crosshair")
    canvas.pack(fill=tk.BOTH, expand=True)

    # Show screenshot as background with dark tint
    from PIL import ImageEnhance
    bg_dark = ImageEnhance.Brightness(bg_image).enhance(0.5)
    bg_tk = ImageTk.PhotoImage(bg_dark)
    canvas.create_image(0, 0, anchor=tk.NW, image=bg_tk)

    canvas.create_text(
        sw // 2, 40,
        text="Ziehe ein Rechteck über den Poker-Tisch. ESC = Abbrechen",
        fill="white", font=("Helvetica", 20),
    )

    state = {"start_x": 0, "start_y": 0, "rect_id": None, "preview_id": None}

    def on_press(event):
        state["start_x"] = event.x
        state["start_y"] = event.y
        if state["rect_id"]:
            canvas.delete(state["rect_id"])
        if state["preview_id"]:
            canvas.delete(state["preview_id"])
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
            region_result = {"x": x, "y": y, "w": w, "h": h}
            root.destroy()

    def on_escape(event):
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", on_escape)

    root.mainloop()
    print(json.dumps(region_result) if region_result else "None")
