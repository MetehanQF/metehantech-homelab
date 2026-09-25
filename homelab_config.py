"""Shared configuration for every script in this repository.

Nothing about a particular installation is hard-coded. Values are resolved in
this order:

  1. process environment            PRIMARY_NODE_IP=... python3 tools/...
  2. a config file, first match of:
       $HOMELAB_CONFIG               (explicit path; exclusive when set)
       <repo>/config.env             (git-ignored)
       ~/.config/metehantech-homelab/config.env
  3. nothing — a required value raises ConfigError

There is deliberately **no fallback to a real address**. Pointing a DNS tool at
the wrong resolver silently is worse than refusing to start, so a missing value
is an error with a message that says which key and where to put it.

Parsing follows systemd EnvironmentFile semantics, not shell semantics:
`KEY=two words` is read intact and surrounding quotes are stripped.

Template: config.example.env
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
EXAMPLE = "config.example.env"


class ConfigError(RuntimeError):
    """A required configuration value is not set."""


def _candidates():
    override = os.environ.get("HOMELAB_CONFIG", "").strip()
    if override:
        return [Path(override)]
    return [
        REPO_ROOT / "config.env",
        Path.home() / ".config" / "metehantech-homelab" / "config.env",
    ]


def _parse(text):
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _load():
    for path in _candidates():
        try:
            return _parse(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, PermissionError, IsADirectoryError, OSError):
            continue
    return {}


_FILE = _load()


def env(name):
    """Required value. Raises ConfigError with a usable message when missing."""
    value = (os.environ.get(name) or _FILE.get(name) or "").strip()
    if not value:
        raise ConfigError(
            "{0} is not set. Copy {1} to config.env and fill it in, or export "
            "{0} in the environment. This repository deliberately ships no real "
            "addresses as fallbacks.".format(name, EXAMPLE)
        )
    return value


def optional(name, default=None):
    """Optional value; returns default (None) when unset."""
    return (os.environ.get(name) or _FILE.get(name) or "").strip() or default


def path(name):
    """Required value interpreted as a filesystem path."""
    return Path(env(name))


def optional_path(name):
    """Optional path; None when unset. Callers must disable the feature explicitly."""
    value = optional(name)
    return Path(value) if value else None
