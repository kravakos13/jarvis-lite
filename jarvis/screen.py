"""Active window info, screen capture and optional Tesseract OCR (Jarvis Lite: no vision model)."""
from __future__ import annotations

import logging
import shutil
from typing import Optional

from . import platform_utils as pu

log = logging.getLogger(__name__)


def foreground_window() -> tuple[str, str, Optional[tuple[int, int, int, int]]]:
    """-> (process name, window title, rect) of the active window (Windows), else ('', '', None)."""
    if not pu.IS_WIN:
        return "", "", None
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        name = ""
        try:
            import psutil
            name = psutil.Process(pid.value).name()
        except Exception:
            pass
        return name, buf.value, (rect.left, rect.top, rect.right, rect.bottom)
    except Exception as e:
        log.debug("foreground: %s", e)
        return "", "", None


def capture(active_window: bool = False, max_side: int = 1280):
    """Returns a PIL image of the primary monitor (or the active window)."""
    from PIL import Image
    import mss
    with mss.mss() as sct:
        region = sct.monitors[1]
        if active_window:
            _, _, rect = foreground_window()
            if rect and rect[2] - rect[0] > 50 and rect[3] - rect[1] > 50:
                region = {"left": rect[0], "top": rect[1], "width": rect[2] - rect[0], "height": rect[3] - rect[1]}
        shot = sct.grab(region)
        img = Image.frombytes("RGB", shot.size, shot.rgb)
    img.thumbnail((max_side, max_side))
    return img


def ocr(img, tesseract_path: str = "", langs: str = "rus+eng") -> Optional[str]:
    try:
        import pytesseract
    except ImportError:
        return None
    exe = tesseract_path or shutil.which("tesseract") or (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe" if pu.IS_WIN else "")
    if not exe:
        return None
    pytesseract.pytesseract.tesseract_cmd = exe
    try:
        return pytesseract.image_to_string(img, lang=langs).strip()
    except Exception as e:
        log.warning("OCR: %s", e)
        return None


def read_text(tesseract_path: str = "") -> str:
    """«Прочитай текст на экране»: OCR of the whole screen (needs Tesseract installed)."""
    try:
        img = capture(False, 2400)
    except Exception as e:
        return f"Не получилось сделать снимок экрана: {e}"
    text = ocr(img, tesseract_path)
    if text is None:
        return "Для чтения экрана нужна программа Tesseract OCR — она не найдена. Как поставить — в инструкции."
    return text[:800] if text else "Текста на экране не нашёл."
