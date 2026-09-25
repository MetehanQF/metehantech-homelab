# examples

Every environment-dependent value in this repository comes from a template.
Nothing here contains a real address, hostname or credential — addresses use the
RFC documentation ranges (`192.0.2.0/24`, `100.64.0.0/10`) and point at nothing.

| Template | Copy to | Holds | Committed? |
|---|---|---|---|
| [`../config.example.env`](../config.example.env) | `<repo>/config.env` | node addresses, credential paths, container names — used by every script | no |
| [`../dns/examples/adguard.env.example`](../dns/examples/adguard.env.example) | `dns/adguard/.env` | bind addresses for the AdGuard compose file | no |
| [`../dns/examples/credentials.example.json`](../dns/examples/credentials.example.json) | outside the repo, mode `0600` | AdGuard admin username/password per node | no |
| [`../mqtt/examples/credentials.example.json`](../mqtt/examples/credentials.example.json) | outside the repo, mode `0600` | MQTT account passwords | no |
| [`../mqtt/examples/passwords.example`](../mqtt/examples/passwords.example) | `mqtt/config/passwords` | Mosquitto bcrypt hashes — **generate, don't write by hand** | no |

## Resolution order

`homelab_config.py` resolves each value as:

```
process environment  →  config file  →  ConfigError
```

The config file is the first match of:

1. `$HOMELAB_CONFIG` — exclusive when set, useful for isolated runs
2. `<repo>/config.env`
3. `~/.config/metehantech-homelab/config.env`

Parsing follows systemd `EnvironmentFile` semantics rather than shell semantics,
so a value containing spaces is read intact and surrounding quotes are stripped.

## Why there are no defaults

A missing required value raises `ConfigError`, and the compose files use
`${VAR:?}` so Docker refuses to start. That is deliberate. For a DNS resolver the
two silent-failure modes are both worse than not starting:

- falling back to a *wrong* address means queries go somewhere unintended
- falling back to an *empty* bind means Docker publishes on `0.0.0.0`, which turns
  the resolver into an open resolver reachable from outside the LAN

So the tools refuse to guess.
