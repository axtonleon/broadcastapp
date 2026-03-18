#!/usr/bin/env python3
"""
Test Slik/Baileys send from Python - mirrors what the FastAPI app does.
Usage: python test_slik_send.py <session_folder> <phone> [message]

Example:
  python test_slik_send.py app/slik-session/session_IL_972_he_329 2347031090186
  python test_slik_send.py app/slik-session/session_IL_972_he_329 2347031090186 "Hello!"
"""
import asyncio
import os
import sys
from pathlib import Path

# Project root (parent of script)
SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR


def normalize_phone(phone: str) -> str:
    return "".join(c for c in phone if c.isdigit() or c == "+").replace("+", "")


async def send_via_slik(session_folder: str, to_phone: str, message_text: str) -> tuple[bool, str | None]:
    bridge_dir = BASE_DIR / "slik-bridge"
    session_path = (BASE_DIR / session_folder).resolve()

    if not (bridge_dir / "send.js").exists():
        return False, "slik-bridge/send.js not found. Run: cd slik-bridge && npm install"

    to_digits = normalize_phone(to_phone)
    if not to_digits:
        return False, "invalid_phone"

    if not session_path.exists() or not session_path.is_dir():
        return False, f"session folder not found: {session_path}"

    session_str = str(session_path)
    env = {**os.environ, "SLIK_VERBOSE": "1"}

    print(f"[Test] Session: {session_str}")
    print(f"[Test] To: {to_phone} (digits: {to_digits})")
    print(f"[Test] Message: {message_text!r}")
    print(f"[Test] cwd: {bridge_dir}")
    print("[Test] Starting node send.js ...")
    print()

    proc = await asyncio.create_subprocess_exec(
        "node",
        "send.js",
        session_str,
        to_digits,
        message_text,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(bridge_dir),
        env=env,
    )

    stdout_lines = []
    stderr_lines = []

    async def read_stream(stream, lines):
        while True:
            line = await stream.readline()
            if not line:
                return
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                print(f"  {text}")
            lines.append(line)

    try:
        await asyncio.wait_for(
            asyncio.gather(
                read_stream(proc.stdout, stdout_lines),
                read_stream(proc.stderr, stderr_lines),
                proc.wait(),
            ),
            timeout=120,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        print("[Test] TIMEOUT after 120s")
        return False, "timeout_120s"

    stdout = b"".join(stdout_lines)
    stderr = b"".join(stderr_lines)
    stdout_str = (stdout or b"").decode("utf-8", errors="replace").strip()
    stderr_str = (stderr or b"").decode("utf-8", errors="replace").strip()

    print()
    print(f"[Test] Return code: {proc.returncode}")
    print(f"[Test] stdout: {stdout_str!r}")
    print(f"[Test] stderr: {stderr_str!r}")

    if proc.returncode == 0 and b"OK" in (stdout or b""):
        print("[Test] PASS: Message sent")
        return True, None

    err = stderr_str or stdout_str
    if err.startswith("ERROR: "):
        err = err[7:]
    err = err or "send_failed"
    print(f"[Test] FAIL: {err}")
    return False, err


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)

    session_folder = sys.argv[1]
    to_phone = sys.argv[2]
    message_text = sys.argv[3] if len(sys.argv) > 3 else "Test from Python script"

    success, err = asyncio.run(send_via_slik(session_folder, to_phone, message_text))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
