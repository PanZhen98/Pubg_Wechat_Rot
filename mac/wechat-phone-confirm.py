#!/usr/bin/env python3
"""
Auto-confirm WeChat desktop login on connected Android phone via ADB.

Flow:
  1. Poll phone every CHECK_INTERVAL seconds
  2. If a WeChat login-confirmation notification is detected → open it
  3. Dump UI, find the "确认登录" button, tap it
  4. Cooldown to avoid double-taps
"""
import re
import subprocess
import sys
import time
import logging
import xml.etree.ElementTree as ET

ADB_BIN        = "/opt/homebrew/bin/adb"
SERIAL         = "e472c9ee"
CHECK_INTERVAL = 5      # seconds between polls
COOLDOWN       = 60     # seconds after a successful tap before next check
WECHAT_PKG     = "com.tencent.mm"

# Text / content-desc patterns on the confirmation button
CONFIRM_PATTERNS = [
    "确认登录",
    "同意登录",
    "允许登录",
    "登录",        # fallback — must also be clickable
    "Confirm",
    "Allow",
    "Log In",
]

# Text patterns in notification that indicate a login request
NOTIFICATION_PATTERNS = [
    r"电脑.*登录",
    r"登录.*请求",
    r"申请.*登录",
    r"正在申请",
    r"DeviceLogin",
    r"device.*login",
    r"PC.*login",
]


# ── ADB helpers ──────────────────────────────────────────────────────────────

def adb(*args, timeout=20):
    cmd = [ADB_BIN, "-s", SERIAL] + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.stdout


def wake_and_unlock():
    """Wake the screen (no PIN assumed)."""
    adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")
    time.sleep(0.8)


def foreground_package():
    out = adb("shell", "dumpsys", "activity", "activities")
    m = re.search(r"mResumedActivity[^{]*\{[^}]*\s(\S+)/", out)
    return m.group(1) if m else None


def has_login_notification():
    """Check notification dump for a WeChat login request."""
    out = adb("shell", "dumpsys", "notification", "--noredact")
    for pattern in NOTIFICATION_PATTERNS:
        if re.search(pattern, out, re.IGNORECASE):
            return True
    return False


def ui_dump():
    adb("shell", "uiautomator", "dump", "/sdcard/uidump.xml")
    return adb("shell", "cat", "/sdcard/uidump.xml")


def find_confirm_button(xml_str):
    """Return (x, y) of the login-confirm button, or None."""
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return None

    for node in root.iter("node"):
        text     = node.get("text", "")
        desc     = node.get("content-desc", "")
        rid      = node.get("resource-id", "")
        clickable = node.get("clickable", "false") == "true"
        label    = text or desc

        # Match by resource-id first (most reliable)
        if any(kw in rid for kw in ("confirm", "agree", "allow", "login_btn")):
            pass  # fall through to bounds extraction

        # Then match by visible text
        elif not any(p.lower() in label.lower() for p in CONFIRM_PATTERNS):
            continue

        bounds = node.get("bounds", "")
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
        if m:
            x = (int(m.group(1)) + int(m.group(3))) // 2
            y = (int(m.group(2)) + int(m.group(4))) // 2
            if x == 0 and y == 0:
                continue
            logging.info("Confirm button: text=%r rid=%r → (%d, %d)", label, rid, x, y)
            return (x, y)

    return None


def open_wechat():
    """Bring WeChat to foreground via am start."""
    adb("shell", "am", "start", "-n", f"{WECHAT_PKG}/.ui.LauncherUI")
    time.sleep(2)


def expand_notifications():
    adb("shell", "cmd", "statusbar", "expand-notifications")
    time.sleep(1.5)


def close_notifications():
    adb("shell", "input", "keyevent", "KEYCODE_BACK")


# ── Main loop ────────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("/tmp/wechat-phone-confirm.log"),
        ],
    )
    logging.info("WeChat phone auto-confirm started (device=%s)", SERIAL)

    last_tapped = 0

    while True:
        try:
            if time.time() - last_tapped < COOLDOWN:
                time.sleep(CHECK_INTERVAL)
                continue

            fg = foreground_package()
            logging.debug("Foreground: %s", fg)

            confirmed = False

            if fg == WECHAT_PKG:
                # WeChat already open — check if login confirm UI is visible
                xml_str = ui_dump()
                pos = find_confirm_button(xml_str)
                if pos:
                    wake_and_unlock()
                    logging.info("Tapping confirm button at %s", pos)
                    adb("shell", "input", "tap", str(pos[0]), str(pos[1]))
                    confirmed = True

            elif has_login_notification():
                # WeChat is not in front but has a login notification
                logging.info("Login notification detected — opening notification shade")
                wake_and_unlock()
                expand_notifications()
                xml_str = ui_dump()
                pos = find_confirm_button(xml_str)
                if pos:
                    logging.info("Tapping notification confirm at %s", pos)
                    adb("shell", "input", "tap", str(pos[0]), str(pos[1]))
                    confirmed = True
                else:
                    # Tap didn't work in notification shade — open WeChat directly
                    logging.info("No button in shade, opening WeChat directly")
                    close_notifications()
                    open_wechat()
                    xml_str = ui_dump()
                    pos = find_confirm_button(xml_str)
                    if pos:
                        logging.info("Tapping confirm in WeChat app at %s", pos)
                        adb("shell", "input", "tap", str(pos[0]), str(pos[1]))
                        confirmed = True

            if confirmed:
                last_tapped = time.time()
                logging.info("Tap sent. Cooling down %ds before next check.", COOLDOWN)
                time.sleep(COOLDOWN)
                continue

        except Exception as e:
            logging.error("Error: %s", e)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
