#!/usr/bin/env python3
"""Ship committed code to the Pi recorders in a single SSH call per Pi.

Why not deploy.ps1's `git push`: pushing into a checked-out branch depends on the
Pi's git state cooperating. It needs receive.denyCurrentBranch=updateInstead, it
refuses when the Pi's tree is dirty, it refuses on non-fast-forward, and it can
report success while the checkout stays behind. It also makes four or five SSH
calls per Pi, which is four or five password prompts when key auth is not set up.

This sends a tarball of `git archive HEAD` and extracts it, so nothing on the Pi
can reject the deploy and there is exactly one connection (two with --restart,
because sudo needs its own tty).

What you give up, deliberately:
  * Files deleted from the repo are NOT deleted on the Pi.
  * The Pi's git checkout is untouched, so `git status` there will look dirty and
    `git log` will not show what is actually running. `.deployed_commit` in the
    remote directory records the real commit instead.
  * No stash, no per-Pi status report, no key installer. Use deploy.ps1 for those.

Only committed content ships: `git archive HEAD` ignores the working tree, so
data/, secrets.toml and venv/ cannot travel.

Authentication, best first:
  1. SSH key - `python deploy.py --install-key` once per Pi, password typed once
     ever, nothing stored on disk.
  2. Password in a gitignored .env (PI_PASSWORD=...) or the PI_PASSWORD env var.
     Needs `pip install paramiko`, because Windows OpenSSH refuses to read a
     password from anywhere but the terminal. Stores the password in clear text -
     acceptable only because these rigs are LAN-only with no internet route.
  3. Neither: you get prompted, once or twice per Pi.

Usage:
    python deploy.py                       # push code to both Pis
    python deploy.py --restart             # ...and restart the recorder service
    python deploy.py --host 192.168.0.101  # one Pi only
    python deploy.py --with-exposure       # also overwrite the per-rig exposure.toml
    python deploy.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOSTS = ["192.168.0.100", "192.168.0.101"]
USER = "cmc1"
REMOTE_PATH = "Documents/forensic"
SERVICE = "data-recorder.service"

# Tuned per rig — see CLAUDE.md. Overwriting it silently loses the tuning, so it
# only ships when explicitly asked for.
PROTECTED = ["exposure.toml"]

SSH_OPTS = ["-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=accept-new"]


def load_password() -> str | None:
    """Read PI_PASSWORD from the environment or a gitignored .env beside this script.

    Windows OpenSSH will not accept a password from a file, an env var or stdin -
    it reads the terminal directly - so a password here means the paramiko backend
    instead of the ssh binary. Absent password is the normal, better case: key auth.
    """
    if os.environ.get("PI_PASSWORD"):
        return os.environ["PI_PASSWORD"]

    env_file = Path(__file__).resolve().parent / ".env"
    if not env_file.exists():
        return None

    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() == "PI_PASSWORD":
            return value.strip().strip("\"'") or None
    return None


def paramiko_run(host: str, user: str, password: str, command: str,
                 payload: bytes | None = None) -> tuple[int, str]:
    """Run one command over a password-authenticated SSH session.

    Imported lazily so the key-auth path keeps working with nothing installed.
    """
    try:
        import paramiko
    except ImportError:
        return 1, ("PI_PASSWORD is set but paramiko is not installed.\n"
                   "  install it:  pip install paramiko\n"
                   "  or drop the password and use key auth:  python deploy.py --install-key")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username=user, password=password, timeout=8,
                       allow_agent=False, look_for_keys=False)
        stdin, stdout, stderr = client.exec_command(command)
        if payload is not None:
            stdin.write(payload)
            stdin.flush()
        stdin.channel.shutdown_write()
        code = stdout.channel.recv_exit_status()
        text = (stdout.read().decode(errors="replace")
                + stderr.read().decode(errors="replace")).strip()
        return code, text
    except Exception as exc:                       # auth failure, refused, timeout
        return 1, f"{type(exc).__name__}: {exc}"
    finally:
        client.close()


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def shq(value: str) -> str:
    """Single-quote a value for the remote POSIX shell."""
    return "'" + value.replace("'", "'\\''") + "'"


def public_keys() -> list[Path]:
    """Every local public key, generating a passphrase-free one if there are none.

    A passphrase would put the prompt back (once per SSH call, unless ssh-agent is
    running), which is the exact problem key auth is here to remove. The private
    half never leaves this machine.
    """
    ssh_dir = Path.home() / ".ssh"
    found = [ssh_dir / name for name in ("id_ed25519.pub", "id_rsa.pub")
             if (ssh_dir / name).exists()]
    if found:
        return found

    print("  no SSH key on this machine - generating one")
    ssh_dir.mkdir(mode=0o700, exist_ok=True)
    key = ssh_dir / "id_ed25519"
    # -N "" as a real argv entry: no shell means no quoting trap turning the empty
    # passphrase into a literal pair of quote characters.
    if subprocess.run(["ssh-keygen", "-t", "ed25519", "-f", str(key),
                       "-N", "", "-C", "forensic-deploy", "-q"]).returncode != 0:
        print("  ssh-keygen failed - run it by hand: ssh-keygen -t ed25519")
        return []
    print(f"  generated {key}")
    return [key.with_suffix(".pub")]


def install_key(target: str) -> bool:
    """Append this machine's public keys to the Pi's authorized_keys.

    The password is typed once here, for this one call, and never stored. All keys
    go in, not just the first: ssh chooses which to offer in its own order, so a
    half-installed set still produces prompts.
    """
    keys = public_keys()
    if not keys:
        return False

    print(f"  installing {', '.join(k.name for k in keys)} - enter the Pi's password once")
    commands = ["mkdir -p ~/.ssh", "chmod 700 ~/.ssh",
                "touch ~/.ssh/authorized_keys", "chmod 600 ~/.ssh/authorized_keys"]
    for key in keys:
        text = key.read_text().strip()
        commands.append(
            f"grep -qxF {shq(text)} ~/.ssh/authorized_keys || "
            f"echo {shq(text)} >> ~/.ssh/authorized_keys")

    # No BatchMode: this is the one call that must be allowed to ask for a password.
    if subprocess.run(["ssh", *SSH_OPTS, target, " && ".join(commands)]).returncode != 0:
        print("  key install failed")
        return False

    # Prove it rather than assume it - wrong permissions on the Pi silently defeat
    # authorized_keys, and the next deploy would just prompt again with no clue why.
    check = subprocess.run(["ssh", "-o", "BatchMode=yes", *SSH_OPTS, target, "true"],
                           capture_output=True)
    if check.returncode != 0:
        print("  key installed but passwordless login still fails.")
        print("  on the Pi, check: ls -ld ~/.ssh ~/.ssh/authorized_keys")
        return False

    print("  passwordless login working")
    return True


def ship(host: str, user: str, password: str | None, tar_bytes: bytes, commit: str,
         remote_path: str, excludes: list[str]) -> bool:
    quoted = shq(remote_path)
    tar_args = " ".join(f"--exclude={shq(name)}" for name in excludes)
    command = (
        f"mkdir -p {quoted} && "
        f"tar -x {tar_args} -f - -C {quoted} && "
        f"printf '%s\\n' {shq(commit)} > {quoted}/.deployed_commit"
    )

    if password:
        code, text = paramiko_run(host, user, password, command, payload=tar_bytes)
        if text:
            print(f"  {text}")
        return code == 0

    # stdin carries the tarball, so this call cannot also allocate a tty. That is
    # why --restart costs a second connection.
    return subprocess.run(["ssh", *SSH_OPTS, f"{user}@{host}", command],
                          input=tar_bytes).returncode == 0


def restart(host: str, user: str, password: str | None, service: str) -> bool:
    if password:
        # sudo -S reads its password from stdin; -p '' keeps the prompt out of the
        # output. The login password doubles as the sudo password on these rigs.
        code, text = paramiko_run(host, user, password,
                                  f"sudo -S -p '' systemctl restart {service}",
                                  payload=(password + "\n").encode())
        if code != 0:
            print(f"  restart failed: {text}")
            return False
        state = paramiko_run(host, user, password, f"systemctl is-active {service}")[1]
    else:
        # -t so sudo can prompt; without it a Pi that lacks NOPASSWD hangs silently.
        if subprocess.run(["ssh", *SSH_OPTS, "-t", f"{user}@{host}",
                           f"sudo systemctl restart {service}"]).returncode != 0:
            return False
        state = subprocess.run(["ssh", *SSH_OPTS, f"{user}@{host}",
                                f"systemctl is-active {service}"],
                               capture_output=True, text=True).stdout.strip()

    if state != "active":
        print(f"  service is '{state}' - check: journalctl -u {service} -n 50")
        return False
    print("  service active")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", action="append", dest="hosts", metavar="ADDR",
                        help="Pi to deploy to; repeatable. Default: both.")
    parser.add_argument("--user", default=USER)
    parser.add_argument("--path", default=REMOTE_PATH, help="remote directory")
    parser.add_argument("--service", default=SERVICE)
    parser.add_argument("--restart", action="store_true",
                        help="restart the recorder service after copying")
    parser.add_argument("--with-exposure", action="store_true",
                        help="also overwrite exposure.toml (per-rig tuned; off by default)")
    parser.add_argument("--install-key", action="store_true",
                        help="one-time per Pi: install your SSH key so deploys stop "
                             "asking for a password. Deploys nothing.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.install_key:
        failed = []
        for host in args.hosts or HOSTS:
            print(f"[{host}]")
            if not install_key(f"{args.user}@{host}"):
                failed.append(host)
            print()
        if failed:
            print(f"FAILED: {', '.join(failed)}")
            return 1
        return 0

    repo_root = git("rev-parse", "--show-toplevel")
    commit = git("rev-parse", "HEAD")
    short = git("rev-parse", "--short", "HEAD")
    hosts = args.hosts or HOSTS
    excludes = [] if args.with_exposure else PROTECTED
    password = load_password()

    dirty = git("status", "--porcelain")
    if dirty:
        print("Local working tree is dirty - only committed work ships:")
        for line in dirty.splitlines():
            print(f"    {line}")

    print(f"\nRepository : {repo_root}")
    print(f"Commit     : {short}")
    print(f"Targets    : {', '.join(hosts)} (as {args.user})")
    print(f"Auth       : {'password from .env / PI_PASSWORD' if password else 'ssh key or prompt'}")
    if excludes:
        print(f"Not sent   : {', '.join(excludes)}")
    print()

    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "deploy.tar"
        git("archive", "--format=tar", "-o", str(archive), "HEAD")
        tar_bytes = archive.read_bytes()
        print(f"Archive    : {len(tar_bytes) // 1024} KiB\n")

        failed = []
        for host in hosts:
            target = f"{args.user}@{host}"
            print(f"[{host}]")

            if args.dry_run:
                print(f"  would extract {short} into {args.path}")
                if args.restart:
                    print(f"  would restart {args.service}")
                print()
                continue

            if not password:
                keyed = subprocess.run(["ssh", "-o", "BatchMode=yes", *SSH_OPTS,
                                        target, "true"], capture_output=True).returncode == 0
                if not keyed:
                    print("  no key auth - password will be asked "
                          f"{'twice (copy, then sudo)' if args.restart else 'once'}.")
                    print("  to stop that for good: python deploy.py --install-key")

            ok = ship(host, args.user, password, tar_bytes, commit, args.path, excludes)
            if ok:
                print(f"  code at {short}")
                if args.restart:
                    ok = restart(host, args.user, password, args.service)
            else:
                print("  copy failed")

            if not ok:
                failed.append(host)
            print()

    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
