# Agents + TeamClaude

A user-owned clone of Omarchy's Agents bar widget, adding a TeamClaude tab.
The original Claude, Codex and Fireworks views remain available.

![Agents widget with TeamClaude usage and request activity](preview.png)

## Use

Open the AI/Agents icon in the bar and select **TeamClaude**.

The compact view keeps session/weekly meters side by side. Open an account’s
**Details** to see token counters, additional quota windows and management
controls. **Help** beside the activity console reveals logging instructions.

- **Start server / Stop server** manages a transient systemd user service,
  `omarchy-teamclaude.service`. It stays alive when the panel closes, but is
  not enabled automatically at login.
- **Add account** launches `teamclaude login` in a terminal and its normal
  browser sign-in flow. New accounts appear on the next refresh.
- **Launch Claude** runs `teamclaude run` in a terminal.
- **Refresh quotas** runs the read-only quota probe. Normal polling reads
  locally observed quotas; it does not send messages to Anthropic.
- Each account has usage meters and **Prefer**, **Enable/Disable**, and
  **Remove** controls. Removal asks for confirmation inside the panel.
- The activity console shows the latest 200 activity lines, with pause,
  follow and selectable text. Request completions include model, account,
  response code and duration when TeamClaude supplies them.

The widget reads the proxy every 1.5 seconds while its tab is open and every
15 seconds otherwise. It shows per-account token/request counters for the
current server run, and quota percentages/reset times reported by TeamClaude.
Quota meters are shown per account because each account has its own reset
period.

## Terminal-started servers

Plain `teamclaude login` and `teamclaude server` continue to work. The widget
detects a server at the configured local port. For its request console:

```sh
mkdir -p ~/.local/state/omarchy/teamclaude
teamclaude server --activity-log ~/.local/state/omarchy/teamclaude/activity.log
```

The Start button supplies the log flag automatically. Other activity-log paths
are discovered from a running local TeamClaude server's command line; set
`OMARCHY_TEAMCLAUDE_LOG` in the desktop environment to override discovery.
A server started elsewhere must be stopped in its own terminal or service
manager. The widget does not take over or terminate unrelated processes.
The console follows the same completed-request line format as TeamClaude's
terminal activity list. In-progress requests appear in its terminal TUI but
are not exposed by the server's control API or written to its activity file.
The widget calls this out when it detects a server without logging enabled.

## Account removal

If TeamClaude's management API is already enabled (`proxy.mcp: "full"`),
removal updates the running server and disk together. This plugin does not
enable that API. Otherwise, it uses the CLI to disable the account, confirms
that the running proxy applied the change, then removes the saved credentials.
The disabled runtime row remains until restart; the panel reports this.
In-flight requests are subject to TeamClaude's own behavior.

## Requirements

- Omarchy with its Quickshell shell (the stock Agents widget, `omarchy.agents`,
  is what this plugin extends).
- Python 3 and systemd user services (both on a stock Omarchy install).
- [TeamClaude](https://github.com/KarpelesLab/teamclaude) (MIT), the local
  multi-account proxy this tab controls: `npm install -g @karpeleslab/teamclaude`.
  It needs the `/teamclaude/status` and `/teamclaude/quota` endpoints; developed
  against TeamClaude 1.1.x.

## Install

```sh
omarchy plugin add https://github.com/supercleanse/omarchy-teamclaude --enable
```

This adds a second Agents icon. To keep just one, turn off the stock widget:

```sh
omarchy plugin disable omarchy.agents
```

## Remove

```sh
omarchy plugin remove supercleanse.agents
omarchy plugin enable omarchy.agents
systemctl --user stop omarchy-teamclaude.service   # only if the widget started the proxy
rm -rf ~/.local/state/omarchy/teamclaude           # activity log and installer backups
```

TeamClaude itself, and its accounts and config, are left alone.

## Install from a checkout (alternative)

From a local checkout of this repository, `python3 install.py` installs through
Omarchy's own clone workflow instead. The installer uses `omarchy plugin clone omarchy.agents`, installs into
`~/.config/omarchy/plugins/<username>.agents`, and saves a timestamped backup
under `~/.local/state/omarchy/teamclaude/`. Packaged Omarchy files are untouched.
The clone is a snapshot of the installed widget; future upstream changes need
to be incorporated into this source explicitly.

Restore the stock panel after an installer-based install with:

```sh
omarchy plugin disable "$USER.agents"
omarchy plugin enable omarchy.agents
```

Troubleshoot startup with `journalctl --user -u omarchy-teamclaude.service`.
Configuration is read from `TEAMCLAUDE_CONFIG` or the standard XDG config path.
Credentials stay in the Python process and the local HTTP authentication
header; snapshots sent to QML contain only display fields. No request bodies
are collected. The activity file may include account names and request paths.
The console reads at most 64 KiB; logs larger than 4 MiB rotate on the next
widget-managed start, retaining one previous file.

## Validation

```sh
python3 -m unittest discover -v
TEAMCLAUDE_SOURCE=/path/to/node_modules/@karpeleslab/teamclaude/src \
  python3 -m unittest test_integration -v
```

The opt-in integration test starts a real TeamClaude HTTP server using only
synthetic credentials; it checks quota mapping, switching and live removal.
It does not send upstream requests.

Original Agents widget: Omarchy, MIT license. See `README.upstream.md`.
