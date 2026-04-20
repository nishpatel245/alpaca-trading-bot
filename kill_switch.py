"""
Emergency stop script.

Run this from a second terminal window to immediately halt the trading bot:

    python kill_switch.py          ← activates kill switch
    python kill_switch.py --reset  ← removes kill switch (allows bot to resume)
"""
import os
import sys

KILL_SWITCH_PATH = os.path.join(os.path.dirname(__file__), "KILL_SWITCH")


def activate():
    with open(KILL_SWITCH_PATH, "w") as f:
        f.write("KILL SWITCH ACTIVE\n")
    print(f"Kill switch ACTIVATED. Bot will stop after current scan.")
    print(f"File created at: {KILL_SWITCH_PATH}")


def reset():
    if os.path.exists(KILL_SWITCH_PATH):
        os.remove(KILL_SWITCH_PATH)
        print("Kill switch REMOVED. Bot can now be restarted.")
    else:
        print("Kill switch was not active.")


if __name__ == "__main__":
    if "--reset" in sys.argv:
        reset()
    else:
        activate()
