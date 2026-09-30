#!/usr/bin/env python3
"""Install through Omarchy's supported clone workflow, preserving a backup."""
from datetime import datetime
import getpass
import json
from pathlib import Path
import shutil
import subprocess

source = Path(__file__).resolve().parent
plugin_id = getpass.getuser() + ".agents"
target = Path.home() / ".config/omarchy/plugins" / plugin_id
stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
backup = Path.home() / ".local/state/omarchy/teamclaude" / ("backup-" + stamp)
backup.mkdir(parents=True, mode=0o700)
shell_config = Path.home() / ".config/omarchy/shell.json"
shutil.copy2(shell_config, backup / "shell.json")
if target.exists():
    manifest = json.loads((target / "manifest.json").read_text())
    if manifest.get("omarchy", {}).get("clonedFrom") != "omarchy.agents":
        raise SystemExit("Refusing to overwrite an unrelated plugin: " + str(target))
    shutil.copytree(target, backup / plugin_id)
else:
    subprocess.run(["omarchy", "plugin", "clone", "omarchy.agents"], check=True)

# A fresh entry-point URL avoids Qt retaining the original clone's compiled
# Panel component. No shell restart is needed (including while locked).
runtime = target / ("runtime-" + stamp)
runtime.mkdir()
for name in ("Panel.qml", "Main.qml", "Agent.qml", "TeamClaude.qml", "teamclaude_bridge.py", "README.md", "README.upstream.md"):
    shutil.copy2(source / name, runtime / name)
shutil.copytree(source / "assets", runtime / "assets")
manifest = json.loads((source / "manifest.json").read_text())
manifest["id"] = plugin_id
manifest["entryPoints"]["barWidget"] = runtime.name + "/Panel.qml"
(target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
subprocess.run(["omarchy-shell", "shell", "rescanPlugins"], check=True)
subprocess.run(["omarchy", "plugin", "enable", plugin_id], check=True)
print("Installed:", target)
print("Backup:", backup)
