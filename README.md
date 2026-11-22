# VORTEX CLONER

made by [@piangendoci on discord](https://discord.com/users/piangendoci)

A console tool that copies a Discord server into another one: roles, categories,
channels, permissions, emojis, stickers, invites and webhooks. It talks to the
Discord REST API directly, so there is no gateway connection and no library
version to fight with.

![version](https://img.shields.io/badge/version-1.0.0-8b5cf6)
![platform](https://img.shields.io/badge/platform-windows%2010%20%7C%2011-0ea5e9)
![license](https://img.shields.io/badge/license-MIT-22c55e)

## Features

- **live to live** - read a server and rebuild it on another, no intermediate file
- **backup and restore** - snapshot a server to JSON, restore it later, diff it
  against the live version
- **clean first** - wipe the target's channels, roles, emojis, stickers and
  webhooks before writing, or merge into what is already there
- **dry run** - walk the whole plan and write nothing
- **12 languages** - English, Italiano, Español, Português, Français, Deutsch,
  Русский, Türkçe, Polski, 中文, 日本語, 한국어
- **survives failures** - per-item errors are collected, the run keeps going
- **rate-limit aware** - 429 and 5xx handled with bounded waits, bucket-aware

## What it clones

| Section | Contents |
|---|---|
| roles | name, color, permissions, hoist, mentionable, position |
| categories | name, position, permission overwrites |
| channels | text, voice, announcement, stage, forum; topic, slowmode, NSFW, bitrate, user limit, positions |
| emojis | name, image |
| stickers | name, description, tags, image |
| settings | guild name, icon, banner, verification level, content filter |
| invites | recreated on matching channels |
| webhooks | name, avatar, channel |

## Install

Download `VORTEX CLONER.exe` from the [Releases](../../releases) page and run it.
Nothing to install, no Python needed.

No binary is committed to this repository - the release build is produced by the
GitHub Actions workflow in `.github/workflows/build.yml`, so what you download is
compiled from the source in this tree.

## Usage

```bat
"VORTEX CLONER.exe"
```

Paste a user token when asked, or set `DISCORD_TOKEN` first. The menu gives you
clone, backup, restore, compare, list servers, audit, settings and token switch.

### Batch flags

```bat
"VORTEX CLONER.exe" --token TOKEN --source 111 --target 222 --dry-run --yes
"VORTEX CLONER.exe" --token TOKEN --source 111 --backup backups\old.json
"VORTEX CLONER.exe" --token TOKEN --target 222 --restore backups\old.json --yes
"VORTEX CLONER.exe" --token TOKEN --target 222 --compare backups\old.json
```

| Flag | Meaning |
|---|---|
| `--source ID` | server to read |
| `--target ID` | server to write |
| `--backup PATH` | snapshot the source to this file |
| `--restore PATH` | build the target from this file |
| `--compare PATH` | diff this file against the live target |
| `--sections LIST` | roles,categories,channels,emojis,stickers,settings,invites,webhooks |
| `--no-delete` | keep existing target content |
| `--dry-run` | plan only, zero writes |
| `--yes` | skip confirmation prompts |
| `--language CODE` | en, it, es, pt, fr, de, ru, tr, pl, zh, ja, ko, auto |
| `--version` | print the version |

## Languages

Pick one in `settings -> language`, or set it once:

```bat
"VORTEX CLONER.exe" --language it
```

`auto` follows the Windows locale. The choice is saved to `vortex_settings.json`,
so it survives the next start. API diagnostics and the log file stay in English,
because a translated HTTP error is an error you cannot search for.

## Files

| File | Role |
|---|---|
| `vortex_main.py` | CLI, menus, batch flags |
| `vortex_api.py` | REST client, rate limits, retries, asset downloads |
| `vortex_backup.py` | JSON snapshots, validation, diff |
| `vortex_cloner.py` | clone orchestration |
| `vortex_ui.py` | banner, colors, prompts, progress |
| `vortex_i18n.py` | interface translations |
| `vortex_config.py` | settings, caps, paths |
| `build.bat` | Windows build script |
| `build.py` | cross-platform build script |

## Safety rails in the code

- per-section caps and bounded asset downloads
- 429/5xx retry handling with bounded waits
- dry-run mode that performs zero writes
- per-item failures collected instead of aborting the run
- token redacted from the log file
- backup files validated before they are read: version, size, sections

## Build

```bat
build.bat
```

or, on any platform with PyInstaller installed:

```bat
python build.py
```

## Repository layout

```text
.github/workflows/build.yml   GitHub Actions: builds the exe on v* tags
.gitignore                    ignores caches, build dirs, local settings/logs
.gitattributes                line-ending rules
LICENSE                       MIT, @piangendoci on discord
requirements.txt              runtime dependencies
requirements-dev.txt          runtime + PyInstaller
build.bat                     Windows build script
build.py                      cross-platform build script
vortex_*.py                   application source
```

The executable is a build artifact, not a tracked file: `build.bat` writes it to
the project root, and the release workflow uploads it from `dist/`.

## Publish to GitHub

```bat
git init
git add .
git commit -m "VORTEX CLONER v1.0.0"
git branch -M main
git remote add origin https://github.com/<user>/<repo>.git
git push -u origin main
```

Then tag the release:

```bat
git tag -a v1.0.0 -m "VORTEX CLONER v1.0.0"
git push origin v1.0.0
```

The tag starts the Actions build, which compiles the exe and attaches it to the
`v1.0.0` release automatically. Nothing to upload by hand.

## License

MIT - see [LICENSE](LICENSE).
