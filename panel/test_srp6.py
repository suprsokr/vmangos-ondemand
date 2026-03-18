#!/usr/bin/env python3
"""
SRP6 verification tool — compare Python output against vmangos DB.

Usage (run from the vmangos root or the panel directory):

  # Check an existing account (created by mangosd or the panel):
  python panel/test_srp6.py check <USERNAME> <PASSWORD>

  # Create a test account via Python, then verify:
  python panel/test_srp6.py create <USERNAME> <PASSWORD>

Examples:
  python panel/test_srp6.py create TESTGM testpass
  python panel/test_srp6.py check TESTGM testpass

The 'check' command:
  1. Reads the stored (v, s) from realmd.account for USERNAME
  2. Recomputes v using our Python algorithm with the *same* stored s
  3. Prints stored v vs computed v so you can see if they match
"""

import hashlib
import subprocess
import sys
import os

# --- SRP6 constants (from core/src/shared/Crypto/Authentication/SRP6.cpp) ---
N = int("894B645E89E1535BBDAD5B8B290650530801B18EBFBF5E8FAB3C82872A3E9BB7", 16)
g = 7

# Locate the project root (one level up if run from panel/)
_HERE = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_HERE) if os.path.basename(_HERE) == "panel" else _HERE


# ---------------------------------------------------------------------------
# Core SRP6 math
# ---------------------------------------------------------------------------

def compute_sha_pass(username: str, password: str) -> bytes:
    """SHA1(UPPER(username) + ':' + UPPER(password)) — CalculateShaPassHash."""
    return hashlib.sha1(
        f"{username.upper()}:{password.upper()}".encode("utf-8")
    ).digest()


def compute_v_for_salt(sha_pass: bytes, s_hex: str) -> str:
    """
    Recompute the verifier v from an existing salt s_hex (as stored in DB).

    Mirrors SRP6::CalculateVerifier(rI, salt):
      - s bytes = AsByteArray(reverse=True) = little-endian
        but: AsByteArray returns exactly BN_num_bytes(s) bytes, NOT padded to 32.
      - mDigest = double-reverse of I bytes = original sha_pass bytes
      - x = SHA1(s_le || mDigest)  (A is zero so contributes nothing)
      - v = g^x mod N
    """
    salt_int = int(s_hex, 16)
    num_bytes = (salt_int.bit_length() + 7) // 8  # matches BN_num_bytes()
    salt_le = salt_int.to_bytes(num_bytes, "little")  # AsByteArray(reverse=True)

    x = int.from_bytes(hashlib.sha1(salt_le + sha_pass).digest(), "little")
    v = pow(g, x, N)

    v_hex = format(v, "X")
    if len(v_hex) % 2:
        v_hex = "0" + v_hex
    return v_hex


def generate_srp6(username: str, password: str):
    """Generate a fresh (v_hex, s_hex) pair — used when creating accounts."""
    sha_pass = compute_sha_pass(username, password)

    # 32-byte random salt; top-bit set (BN_RAND_TOP_ONE) so BN_num_bytes = 32 always
    salt_bytes = bytearray(os.urandom(32))
    salt_bytes[0] |= 0x80
    salt_bytes[-1] |= 0x01  # odd (BN_RAND_BOTTOM_ODD)
    salt_int = int.from_bytes(salt_bytes, "big")

    v_hex = compute_v_for_salt(sha_pass, format(salt_int, "X"))

    s_hex = format(salt_int, "X")
    if len(s_hex) % 2:
        s_hex = "0" + s_hex
    return v_hex, s_hex


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def mysql(query: str, database: str = "realmd"):
    r = subprocess.run(
        [
            "docker", "compose", "exec", "-T", "db",
            "mysql", "-uroot", "-pmangos", database,
            "--batch", "--skip-column-names", "-e", query,
        ],
        capture_output=True, text=True, cwd=BASE_DIR, timeout=10,
    )
    return r


def fetch_account(username: str):
    """Return dict with id, v, s for USERNAME, or None."""
    r = mysql(
        f"SELECT id, username, v, s FROM account WHERE username = '{username.upper()}';"
    )
    if r.returncode != 0:
        print(f"[DB ERROR] {r.stderr.strip()}")
        return None
    lines = [l for l in r.stdout.strip().splitlines() if l]
    if not lines:
        return None
    parts = lines[0].split("\t")
    return {"id": parts[0], "username": parts[1], "v": parts[2], "s": parts[3]}


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_check(username: str, password: str):
    print(f"\n=== Checking account: {username.upper()} ===\n")

    row = fetch_account(username)
    if row is None:
        print(f"[FAIL] Account '{username.upper()}' not found in DB.")
        return

    print(f"  id       : {row['id']}")
    print(f"  username : {row['username']}")
    print(f"  s (DB)   : {row['s']}")
    print(f"  v (DB)   : {row['v']}")
    print()

    sha_pass = compute_sha_pass(username, password)
    print(f"  sha_pass : {sha_pass.hex().upper()}  (SHA1 of {username.upper()}:{password.upper()})")
    print()

    computed_v = compute_v_for_salt(sha_pass, row["s"])
    match = computed_v.upper() == row["v"].upper()
    print(f"  v (Python computed from stored s): {computed_v}")
    print()
    if match:
        print("  ✓  MATCH — Python SRP6 is correct for this account.")
    else:
        print("  ✗  MISMATCH — Python SRP6 produces a different v.")
        print("     The algorithm or byte-ordering may differ from vmangos.")
    print()


def cmd_create(username: str, password: str):
    print(f"\n=== Creating account via Python: {username.upper()} ===\n")

    v_hex, s_hex = generate_srp6(username, password)
    print(f"  s (Python) : {s_hex}")
    print(f"  v (Python) : {v_hex}")
    print()

    r = mysql(
        f"INSERT INTO account(`username`, `v`, `s`, `joindate`) "
        f"VALUES('{username.upper()}', '{v_hex}', '{s_hex}', NOW());"
    )
    if r.returncode != 0:
        err = r.stderr.strip()
        if "Duplicate entry" in err:
            print(f"  [SKIP] Account already exists — running check instead.\n")
        else:
            print(f"  [FAIL] {err}")
            return
    else:
        print("  Account inserted into DB.")
        print()

    cmd_check(username, password)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in ("check", "create"):
        print(__doc__)
        sys.exit(1)

    _, cmd, user, pw = sys.argv
    if cmd == "check":
        cmd_check(user, pw)
    elif cmd == "create":
        cmd_create(user, pw)
