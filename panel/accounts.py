"""Account management via direct DB queries (docker compose exec)."""

import hashlib
import os
import re
import subprocess

_VALID_USERNAME = re.compile(r"^[A-Za-z0-9_-]{1,32}$")

# vmangos SRP6 parameters (from core/src/shared/Crypto/Authentication/SRP6.cpp)
_SRP6_N = int("894B645E89E1535BBDAD5B8B290650530801B18EBFBF5E8FAB3C82872A3E9BB7", 16)
_SRP6_g = 7


def _compute_srp6(username, password):
    """Compute SRP6 verifier (v_hex) and salt (s_hex) matching vmangos.

    Mirrors AccountMgr::CreateAccount / SRP6::CalculateVerifier:

      sha_pass = SHA1(UPPER(username) + ':' + UPPER(password))
      s        = random 32-byte value (top-bit set, odd — matches BN_rand flags)
      x        = SHA1(s_little_endian || sha_pass)   [SetBinary → little-endian x]
      v        = g^x mod N
    """
    sha_pass = hashlib.sha1(
        f"{username.upper()}:{password.upper()}".encode("utf-8")
    ).digest()

    # Salt: 32 bytes with MSB and LSB both set to match BN_rand(256, top=0, bottom=1)
    # so BN_num_bytes() is always 32, meaning AsByteArray() always returns 32 bytes.
    salt_bytes = bytearray(os.urandom(32))
    salt_bytes[0] |= 0x80   # top bit → ensures exactly 256-bit length
    salt_bytes[-1] |= 0x01  # bottom bit → odd

    salt_int = int.from_bytes(salt_bytes, "big")

    # AsByteArray(minSize=0, reverse=True) in C++ returns the salt in little-endian order
    salt_le = bytes(salt_bytes)[::-1]

    # x = SHA1(salt_le || sha_pass); SetBinary reverses bytes → little-endian interpretation
    x = int.from_bytes(hashlib.sha1(salt_le + sha_pass).digest(), "little")

    v = pow(_SRP6_g, x, _SRP6_N)

    # AsHexStr() = BN_bn2hex = uppercase hex, padded to whole bytes (even nibble count)
    s_hex = format(salt_int, "X")
    v_hex = format(v, "X")
    # BN_bn2hex pads to even nibble count (whole bytes)
    if len(s_hex) % 2:
        s_hex = "0" + s_hex
    if len(v_hex) % 2:
        v_hex = "0" + v_hex

    return v_hex, s_hex


def _mysql(base_dir, query, database="realmd"):
    """Run a MySQL query in the db container. Returns CompletedProcess."""
    return subprocess.run(
        [
            "docker", "compose", "exec", "-T", "db",
            "mysql", "-uroot", "-pmangos", database,
            "--batch", "--skip-column-names",
            "-e", query,
        ],
        capture_output=True,
        text=True,
        cwd=base_dir,
        timeout=10,
    )


def _validate_username(username):
    """Allow only safe characters so usernames can be embedded in SQL."""
    if not username or not _VALID_USERNAME.match(username):
        return False, "Username must be 1–32 characters: letters, digits, _ or -"
    return True, None


def list_accounts(base_dir):
    """Return (list_of_dicts, error_str). List is None on DB error."""
    result = _mysql(
        base_dir,
        "SELECT id, username, gmlevel, last_ip, last_login, online, locked "
        "FROM account ORDER BY id;",
    )
    if result.returncode != 0:
        return None, (result.stderr or "Database unavailable").strip()

    accounts = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        accounts.append({
            "id": parts[0],
            "username": parts[1],
            "gmlevel": int(parts[2]) if parts[2].isdigit() else 0,
            "last_ip": parts[3],
            "last_login": (
                None if parts[4] in (r"\N", "NULL", "0000-00-00 00:00:00") else parts[4]
            ),
            "online": parts[5] == "1",
            "locked": parts[6] == "1",
        })
    return accounts, None


def create_account(base_dir, username, password):
    """Create a new account. Returns (ok, error_str)."""
    ok, err = _validate_username(username)
    if not ok:
        return False, err
    if not password:
        return False, "Password is required"

    username = username.upper()
    v_hex, s_hex = _compute_srp6(username, password)

    result = _mysql(
        base_dir,
        f"INSERT INTO account(`username`, `v`, `s`, `joindate`) "
        f"VALUES('{username}', '{v_hex}', '{s_hex}', NOW());",
    )
    if result.returncode != 0:
        err = result.stderr.strip()
        if "Duplicate entry" in err:
            return False, "An account with that username already exists"
        return False, err or "Database error"
    return True, None


def set_password(base_dir, username, password):
    """Update an account's password. Returns (ok, error_str)."""
    ok, err = _validate_username(username)
    if not ok:
        return False, err
    if not password:
        return False, "Password is required"

    username = username.upper()
    v_hex, s_hex = _compute_srp6(username, password)

    result = _mysql(
        base_dir,
        f"UPDATE account SET `v`='{v_hex}', `s`='{s_hex}' "
        f"WHERE `username`='{username}';",
    )
    if result.returncode != 0:
        return False, (result.stderr or "Database error").strip()
    return True, None


def set_gmlevel(base_dir, username, gmlevel):
    """Update an account's GM level (0–4). Returns (ok, error_str)."""
    ok, err = _validate_username(username)
    if not ok:
        return False, err
    try:
        gmlevel = int(gmlevel)
        if not 0 <= gmlevel <= 4:
            raise ValueError
    except (ValueError, TypeError):
        return False, "GM level must be 0–4"

    username = username.upper()
    result = _mysql(
        base_dir,
        f"UPDATE account SET `gmlevel`={gmlevel} WHERE `username`='{username}';",
    )
    if result.returncode != 0:
        return False, (result.stderr or "Database error").strip()
    return True, None


def delete_account(base_dir, username):
    """Delete an account. Returns (ok, error_str)."""
    ok, err = _validate_username(username)
    if not ok:
        return False, err

    username = username.upper()
    result = _mysql(
        base_dir,
        f"DELETE FROM account WHERE `username`='{username}';",
    )
    if result.returncode != 0:
        return False, (result.stderr or "Database error").strip()
    return True, None
