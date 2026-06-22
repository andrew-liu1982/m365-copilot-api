"""Command-line entry point.

    python -m copilot login        # interactive sign-in, persists the session
    python -m copilot ask "hi"     # one-shot completion via the browser driver

Use ``COPILOT_MODE=m365`` env var to target M365 Copilot instead of consumer.
"""

import os
import sys

from .browser import BrowserCopilot


def main(argv) -> int:
    mode = os.environ.get("COPILOT_MODE", "consumer")
    cmd = argv[0] if argv else "ask"
    if cmd == "login":
        BrowserCopilot(headless=False, mode=mode).login()
        return 0
    if cmd == "ask":
        prompt = " ".join(argv[1:]) or "Hello!"
        with BrowserCopilot(mode=mode) as bot:
            for chunk in bot.create_completion(prompt, stream=True):
                print(chunk, end="", flush=True)
            print()
        return 0
    print(f"Unknown command: {cmd!r}. Use 'login' or 'ask <prompt>'.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
