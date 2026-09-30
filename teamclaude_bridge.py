#!/usr/bin/env python3
"""Local-only TeamClaude adapter. Credentials never leave the HTTP header."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

UNIT = "omarchy-teamclaude.service"
MAX_REPLY = 2 * 1024 * 1024
LABELS = {"fiveHour": "Session · 5 hours", "weeklyShared": "Weekly",
          "weeklySonnet": "Sonnet weekly", "weeklyFable": "Fable weekly",
          "tokens": "Token allowance", "requests": "Request allowance"}


def state_dir():
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "omarchy/teamclaude"


def config_path():
    return Path(os.environ.get("TEAMCLAUDE_CONFIG") or
                str(Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "teamclaude.json")).expanduser()


def read_config():
    try:
        return json.loads(config_path().read_text())
    except FileNotFoundError:
        return {}


def cli():
    binary = shutil.which("teamclaude")
    if not binary:
        # GUI sessions do not always inherit mise's interactive PATH.
        candidate = Path.home() / ".local/share/mise/shims/teamclaude"
        if candidate.exists():
            binary = str(candidate)
    if not binary:
        raise RuntimeError("TeamClaude is not on PATH. Install it or add its bin directory to the shell environment.")
    return binary


class LocalOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("The local TeamClaude endpoint returned an unexpected redirect.")


class Client:
    def __init__(self, config):
        proxy = config.get("proxy", {})
        host = os.environ.get("TEAMCLAUDE_HOST") or proxy.get("host", "127.0.0.1")
        if host in ("0.0.0.0", "::", "localhost"):
            host = "127.0.0.1" if host != "::" else "::1"
        if host not in ("127.0.0.1", "::1"):
            raise RuntimeError("This widget supports a local TeamClaude proxy bound to loopback or all interfaces.")
        port = int(proxy.get("port", 3456))
        self.base = f"http://{'[' + host + ']' if ':' in host else host}:{port}"
        self.key = proxy.get("apiKey", "")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), LocalOnlyRedirect())

    def call(self, path, body=None, timeout=4):
        headers = {"Accept": "application/json"}
        if self.key:
            headers["x-api-key"] = self.key
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        request = urllib.request.Request(self.base + "/teamclaude/" + path, data=data, headers=headers)
        with self.opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_REPLY + 1)
        if len(raw) > MAX_REPLY:
            raise RuntimeError("TeamClaude response is too large.")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise RuntimeError("Unexpected TeamClaude response.")
        return value

    def action(self, path, body):
        result = self.call(path, body, timeout=45)
        if result.get("ok") is not True:
            raise RuntimeError("TeamClaude did not confirm the action.")
        return result


def clean(value, limit=180):
    return re.sub(r"[\x00-\x1f\x7f]", "", str(value or ""))[:limit]


def meters(buckets, aggregate=False):
    result = []
    for key, label in LABELS.items():
        bucket = buckets.get(key)
        if not isinstance(bucket, dict):
            if key in ("fiveHour", "weeklyShared"):
                result.append({"label": label, "percent": None, "reset": None})
            continue
        # Do not repeat the shared weekly meter under a model name.
        if not aggregate and key in ("weeklySonnet", "weeklyFable") and bucket.get("source") == "unified7d":
            continue
        value = bucket.get("utilization")
        result.append({"label": label, "percent": value if isinstance(value, (float, int)) else None,
                       "reset": bucket.get("nextResetAt" if aggregate else "resetAt"),
                       "knownAccounts": bucket.get("knownAccounts")})
    return result


def normalize(status, quota):
    if not isinstance(status.get("accounts"), list) or not isinstance(status.get("server"), dict):
        raise RuntimeError("The configured port did not return TeamClaude status.")
    quota_accounts = quota.get("accounts", [])
    accounts = []
    for index, account in enumerate(status["accounts"]):
        # Endpoints preserve account order, but check identity across snapshots.
        q = quota_accounts[index] if index < len(quota_accounts) else {}
        if q.get("name") != account.get("name") or q.get("type") != account.get("type"):
            q = {}
        usage = account.get("usage", {})
        counters = {key: usage.get(key, 0) for key in
                    ("totalInputTokens", "totalOutputTokens", "totalCacheReadTokens", "totalCacheCreationTokens", "totalRequests")}
        provider = account.get("provider", "anthropic")
        current = status.get("currentIndexes", {}).get(provider)
        accounts.append({"name": clean(account.get("name")), "target": account.get("name", ""),
                         "org": account.get("orgName") or "", "disabled": bool(account.get("disabled")),
                         "status": clean(account.get("status")), "active": current == index,
                         "tier": clean(q.get("tier", {}).get("rateLimitTier") or account.get("type")),
                         "sessions": account.get("sessions", 0), "usage": counters,
                         "meters": meters(q.get("buckets", {}))})
    return {"online": True, "accounts": accounts, "meters": [],
            "unknownTiers": len(quota.get("unknownTiers", [])),
            "version": clean(status["server"].get("version")),
            "sessions": status.get("sessions", {}).get("active", 0),
            "startedAt": status["server"].get("startedAt"),
            "requests": sum(a["usage"]["totalRequests"] for a in accounts)}


def managed():
    return subprocess.run(["systemctl", "--user", "is-active", "--quiet", UNIT],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def activity_path():
    override = os.environ.get("OMARCHY_TEAMCLAUDE_LOG")
    if override:
        return Path(override).expanduser()
    # Discover --activity-log on a server started in a terminal. Never return
    # full argv: unrelated command arguments may contain secrets.
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            args = (entry / "cmdline").read_bytes().decode(errors="replace").split("\0")
            if not any("teamclaude" in a for a in args[:3]) or "server" not in args or "--activity-log" not in args:
                continue
            path = Path(args[args.index("--activity-log") + 1])
            return path if path.is_absolute() else (entry / "cwd").resolve() / path
        except (OSError, ValueError, IndexError):
            continue
    return state_dir() / "activity.log"


def running_server_log():
    """Return the active server's explicit log, or explain that it has none."""
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            args = (entry / "cmdline").read_bytes().decode(errors="replace").split("\0")
            if not any("teamclaude" in part for part in args[:4]) or "server" not in args:
                continue
            if "--activity-log" not in args:
                return None, "This server has no activity log. Restart it with --activity-log to show requests here."
            path = Path(args[args.index("--activity-log") + 1])
            if not path.is_absolute():
                path = (entry / "cwd").resolve() / path
            return path, ""
        except (OSError, ValueError, IndexError):
            continue
    return None, ""


def activity():
    active_path, warning = running_server_log()
    path = active_path or activity_path()
    if warning:
        return {"lines": [], "logPath": str(path), "logUpdated": None,
                "logAvailable": False, "logMessage": warning}
    try:
        with path.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - 65536))
            raw = stream.read()
        lines = raw.decode(errors="replace").splitlines()
        if size > 65536:
            lines = lines[1:]
        # TeamClaude writes startup/configuration messages to this same file.
        # Its terminal Activity pane contains completed request records only.
        requests = [line for line in lines
                    if re.search(r"\s(?:GET|POST|PUT|PATCH|DELETE)\s+\S+.*\s→\s.+\s\(\d{3},\s*[^)]*s\)$", line)]
        return {"lines": [clean(line, 2000) for line in requests[-200:]], "logPath": str(path),
                "logUpdated": path.stat().st_mtime, "logAvailable": True, "logMessage": ""}
    except FileNotFoundError:
        return {"lines": [], "logPath": str(path), "logUpdated": None,
                "logAvailable": bool(active_path), "logMessage": ""}


def snapshot():
    config = read_config()
    try:
        client = Client(config)
        result = normalize(client.call("status"), client.call("quota"))
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        result = {"online": False, "accounts": [], "meters": [],
                  "message": "Proxy unavailable. Start TeamClaude here or in a terminal."}
    result.update(activity())
    if result.get("online") and result.get("logAvailable") is None:
        result["logAvailable"] = False
    result["managed"] = managed()
    result["installed"] = bool(shutil.which("teamclaude"))
    result["mcpFull"] = config.get("proxy", {}).get("mcp") == "full"
    return result


def run_cli(*args):
    result = subprocess.run([cli(), *args], capture_output=True, text=True, timeout=40)
    if result.returncode:
        # CLI output may echo configuration; keep credentials out of QML/errors.
        raise RuntimeError(f"TeamClaude {args[0]} failed (exit {result.returncode}). Check it in a terminal.")


def action(name, target="", org=""):
    config = read_config()
    client = Client(config)
    if name == "start":
        try:
            normalize(client.call("status"), {})
            return "A TeamClaude server is already running."
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        directory = state_dir()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Bound disk growth across launches; never rotate a live server's file.
        log = directory / "activity.log"
        if log.exists() and log.stat().st_size > 4 * 1024 * 1024:
            log.replace(directory / "activity.previous.log")
        command = ["systemd-run", "--user", "--collect", "--unit=" + UNIT,
                   "--property=UMask=0077", "--setenv=PATH=" + os.environ.get("PATH", ""),
                   "--setenv=TEAMCLAUDE_CONFIG=" + str(config_path()),
                   cli(), "server", "--headless", "--activity-log", str(log)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise RuntimeError("Could not start the user service. Inspect systemctl --user status " + UNIT)
        return "Starting TeamClaude…"
    if name == "stop":
        if not managed():
            raise RuntimeError("This server was started elsewhere. Stop it in its terminal or service manager.")
        subprocess.run(["systemctl", "--user", "stop", UNIT], check=True, timeout=30)
        return "TeamClaude stopped."
    if name in ("login", "run", "attach"):
        subprocess.Popen(["omarchy-launch-terminal", cli(), name], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"login": "Complete login in the terminal/browser. Accounts refresh automatically.",
                "run": "Opened Claude through TeamClaude.", "attach": "Opened the TeamClaude terminal dashboard."}[name]
    if name == "probe":
        client.action("probe", {})
        return "Account quotas refreshed."
    if name == "switch":
        client.action("switch", {"account": target})
        return "Preferred account updated; routing rules still apply."
    if name not in ("enable", "disable", "remove") or not target:
        raise RuntimeError("Unknown action or missing account.")
    # Validate against the current config before invoking account mutations.
    matches = [a for a in config.get("accounts", []) if a.get("name") == target
               and (not org or a.get("orgName") == org)]
    if len(matches) != 1:
        raise RuntimeError("Account changed or is ambiguous. Refresh before trying again.")
    suffix = ["--org", org] if org else []
    if name == "remove" and config.get("proxy", {}).get("mcp") == "full":
        args = {"account": target}
        if org:
            args["org"] = org
        response = client.call("mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                      "params": {"name": "remove_account", "arguments": args}})
        result = response.get("result", {})
        if "error" in response or result.get("isError") or not result.get("content"):
            raise RuntimeError("TeamClaude could not remove the account through its management API.")
        return "Account removed from the server and saved configuration."
    if name == "remove":
        # CLI removal alone leaves a live credential in memory. Disable and
        # confirm the reload before deleting it from disk.
        run_cli("disable", target, *suffix)
        try:
            client.action("reload", {})
            status = client.call("status")
            rows = [a for a in status.get("accounts", []) if a.get("name") == target]
            if not rows or any(not a.get("disabled") for a in rows):
                raise RuntimeError("Could not confirm the account is disabled; removal was cancelled.")
        except urllib.error.URLError:
            raise RuntimeError("Could not confirm the running account is disabled; removal was cancelled. Retry after reconnecting.")
        run_cli("remove", target, *suffix)
        return "Credentials removed; the disabled runtime row disappears after the server restarts."
    run_cli(name, target, *suffix)
    return "Account " + ("enabled." if name == "enable" else "disabled.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["snapshot", "action"])
    parser.add_argument("action", nargs="?", default="")
    parser.add_argument("target", nargs="?", default="")
    parser.add_argument("org", nargs="?", default="")
    args = parser.parse_args()
    try:
        value = snapshot() if args.command == "snapshot" else {"ok": True, "message": action(args.action, args.target, args.org)}
    except Exception as error:
        if isinstance(error, RuntimeError):
            message = str(error)
        elif isinstance(error, urllib.error.HTTPError):
            message = f"TeamClaude returned HTTP {error.code}. Check proxy authentication/settings."
        else:
            message = "TeamClaude operation failed (" + type(error).__name__ + "). Check configuration and server status."
        value = {"ok": False, "online": False, "message": message}
    print(json.dumps(value, allow_nan=False))


if __name__ == "__main__":
    main()
