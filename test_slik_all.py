#!/usr/bin/env py -3
"""Test Slik send with every session in app/slik-session/.

Usage:
  py -3 test_slik_all.py <phone> <message>

Example:
  py -3 test_slik_all.py +2347031090186 "Hello test"
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.config import settings


def normalize_phone(phone: str) -> str:
    return "".join(c for c in phone if c.isdigit() or c == "+").replace("+", "")


def discover_sessions() -> list[str]:
    """Session IDs from folders (Baileys auth) and .wses stems."""
    folder = settings.SLIK_SESSION_DIR
    if not folder.exists():
        return []
    found = set()
    for p in folder.iterdir():
        if p.is_dir():
            found.add(p.name)
        elif p.suffix == ".wses":
            found.add(p.stem)
    return sorted(found)


async def test_one(session_id: str, phone: str, message: str) -> tuple[str, bool, str]:
    """Run send test for one session. Returns (session_id, success, details)."""
    session_folder = settings.SLIK_SESSION_DIR / session_id
    bridge = Path(settings.BASE_DIR) / "slik-bridge" / "send.js"

    if not session_folder.exists():
        return session_id, False, "folder not found"
    if not session_folder.is_dir():
        return session_id, False, "not a folder (Baileys needs folder)"
    if not bridge.exists():
        return session_id, False, "bridge not found"

    to_digits = normalize_phone(phone)
    if not to_digits:
        return session_id, False, "invalid phone"

    proc = await asyncio.create_subprocess_exec(
        "node",
        str(bridge),
        str(session_folder),
        to_digits,
        message,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(settings.BASE_DIR),
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return session_id, False, "timeout 120s"

    err = (stderr or stdout or b"").decode("utf-8", errors="replace").strip()
    if err.startswith("ERROR: "):
        err = err[7:]
    if proc.returncode == 0 and b"OK" in (stdout or b""):
        return session_id, True, "OK"
    return session_id, False, err or f"exit {proc.returncode}"


async def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    phone = sys.argv[1]
    message = " ".join(sys.argv[2:])
    to_digits = normalize_phone(phone)
    if not to_digits:
        print("ERROR: Invalid phone")
        sys.exit(1)

    sessions = discover_sessions()
    if not sessions:
        print("No sessions found in", settings.SLIK_SESSION_DIR)
        sys.exit(1)

    print("=" * 60)
    print("Slik Send Test — All Sessions")
    print("=" * 60)
    print(f"  To:      {phone} ({to_digits})")
    print(f"  Message: {message[:50]}{'...' if len(message) > 50 else ''}")
    print(f"  Sessions: {len(sessions)}")
    print("=" * 60)

    for sid in sessions:
        print(f"\n[{sid}] ", end="", flush=True)
        _, ok, details = await test_one(sid, phone, message)
        if ok:
            print("SUCCESS")
        else:
            print("FAILED:", details)

    print("\n" + "=" * 60)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
