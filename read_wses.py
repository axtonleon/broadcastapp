#!/usr/bin/env py -3
"""
Script to read and parse .wses (WSES) files.
Format: Binary with "WSES" magic header, used by Slik session files.
"""

import struct
import sys
from pathlib import Path


def extract_strings(data: bytes, min_len: int = 4) -> list[str]:
    """Extract readable ASCII strings from binary data."""
    result = []
    current = []
    for b in data:
        if 32 <= b < 127 or b in (9, 10, 13):
            current.append(chr(b))
        else:
            if len(current) >= min_len:
                result.append("".join(current).strip())
            current = []
    if len(current) >= min_len:
        result.append("".join(current).strip())
    return result


def is_meaningful(s: str) -> bool:
    """Filter out binary junk - keep session IDs, paths, alphanumeric names."""
    if len(s) < 5:
        return False
    s_clean = s.split()[0] if s.split() else s  # first token (before binary junk)
    # Session IDs: session_XX_NNN
    if s_clean.startswith("session_"):
        return True
    # Paths with / or .
    if "/" in s_clean or (s_clean.count(".") >= 1 and s_clean.replace(".", "").replace("_", "").isalnum()):
        return True
    # Mostly alphanumeric + underscore (e.g. variable names)
    alnum_underscore = sum(1 for c in s_clean if c.isalnum() or c in "_-")
    special = sum(1 for c in s_clean if c in r"|{}[]\^`~<>@#$%&*+=;!?\\")
    return alnum_underscore >= 8 and special <= 1


def read_wses(file_path: str) -> dict:
    """
    Read a .wses file and return parsed data.
    
    Args:
        file_path: Path to the .wses file.
        
    Returns:
        Dictionary with header info, raw bytes for analysis, and extracted strings.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    
    with open(path, "rb") as f:
        data = f.read()
    
    if len(data) < 4:
        raise ValueError("File too small to be a valid WSES file")
    
    magic = data[:4].decode("ascii", errors="replace")
    if magic != "WSES":
        raise ValueError(f"Invalid magic: expected 'WSES', got {magic!r}")
    
    # Parse header (best-effort based on observed structure)
    result = {
        "path": str(path),
        "size": len(data),
        "magic": magic,
        "header_bytes": data[4:20].hex(),
    }
    
    # Try to parse version/flags (bytes 4-8)
    if len(data) >= 8:
        v1, v2, v3, v4 = struct.unpack_from("<BBBB", data, 4)
        result["version_candidates"] = {"v1": v1, "v2": v2, "v3": v3, "v4": v4}
    
    # Try 8-byte value at offset 8 (could be timestamp or size)
    if len(data) >= 16:
        val = struct.unpack_from("<Q", data, 8)[0]
        result["field_at_8"] = val
    
    # Hash-like 32 bytes at offset 16
    if len(data) >= 48:
        result["hash_32"] = data[16:48].hex()
    
    # Extract readable strings; filter for meaningful ones (session IDs, paths, etc.)
    all_strings = [s for s in extract_strings(data, min_len=5) if s]
    result["strings"] = [s for s in all_strings if is_meaningful(s)]
    result["all_strings_count"] = len(all_strings)
    
    # Raw hex of first 128 bytes for debugging
    result["raw_preview"] = data[:128].hex()
    
    return result


def main() -> None:
    """Entry point."""
    default_path = r"C:\Users\PC\Downloads\slik-session\session_IL_972_he_326.wses"
    path = sys.argv[1] if len(sys.argv) > 1 else default_path
    
    try:
        info = read_wses(path)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Print in ASCII-safe way
    print("=== WSES File Contents ===")
    print(f"Path: {info['path']}")
    print(f"Size: {info['size']} bytes")
    print(f"Magic: {info['magic']}")
    print(f"Header (hex): {info['header_bytes']}")
    if "version_candidates" in info:
        print(f"Version bytes: {info['version_candidates']}")
    if "field_at_8" in info:
        print(f"Field at offset 8: {info['field_at_8']}")
    if "hash_32" in info:
        print(f"Hash (32 bytes): {info['hash_32']}")
    print()
    print("Meaningful strings (session IDs, paths, etc.):")
    for s in info["strings"]:
        print(f"  - {s}")
    if info.get("all_strings_count"):
        print(f"  (Filtered from {info['all_strings_count']} total extracted)")
    print()
    print("Raw preview (first 128 bytes hex):")
    print(info["raw_preview"])


if __name__ == "__main__":
    main()
