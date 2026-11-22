"""VORTEX CLONER - command line entry point."""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from typing import Any, Dict, List, Optional

import vortex_ui as ui
from vortex_api import DiscordAPI, DiscordError
from vortex_backup import SECTIONS, capture, diff_snapshots, load_snapshot, save_snapshot, section_counts
from vortex_cloner import Cloner, CloneOptions, CloneReport
from vortex_config import APP_NAME, MADE_BY, VERSION, Settings, app_dir
from vortex_i18n import (LANGUAGES, get_language, language_codes, language_name,
                          resolve, set_language, t)

_CURRENT_TOKEN = ""


def log_event(message: str) -> None:
    settings = _SETTINGS
    path = os.path.join(app_dir(), settings.log_file)
    safe = message.replace(_CURRENT_TOKEN, "<redacted>") if _CURRENT_TOKEN else message
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{dt.datetime.now().isoformat(timespec='seconds')} {safe}\n")
    except OSError:
        pass


_SETTINGS = Settings.load()


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="VORTEX CLONER",
        description=f"{APP_NAME} v{VERSION} - made by {MADE_BY}",
    )
    parser.add_argument("--token", help="discord token (prompted when omitted)")
    parser.add_argument("--source", help="source guild id")
    parser.add_argument("--target", help="target guild id")
    parser.add_argument("--backup", help="save a snapshot to this .json path")
    parser.add_argument("--restore", help="restore a snapshot from this .json path")
    parser.add_argument("--compare", help="compare a snapshot against a live guild")
    parser.add_argument("--sections", help="comma separated sections to include")
    parser.add_argument("--dry-run", action="store_true", help="preview actions without writing")
    parser.add_argument("--yes", action="store_true", help="skip confirmations")
    parser.add_argument("--no-delete", action="store_true", help="do not clear the target first")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} v{VERSION} - {MADE_BY}")
    parser.add_argument("--language", help="interface language code (en, it, es, ...)")
    return parser.parse_args(argv)


def get_token(settings: Settings, supplied: Optional[str] = None) -> Optional[str]:
    global _CURRENT_TOKEN
    token = supplied or os.environ.get("DISCORD_TOKEN", "")
    if not token:
        ui.info(t("token.hint"))
        token = ui.prompt(t("token.prompt"), password=True)
    token = token.strip().strip('"')
    if len(token) < 20 or len(token) > 4096:
        ui.err(t("token.length"))
        return None
    _CURRENT_TOKEN = token
    return token


def open_api(token: str, settings: Settings) -> Optional[DiscordAPI]:
    api = DiscordAPI(token, settings)
    try:
        user = api.validate_token()
    except DiscordError as exc:
        ui.err(t("login.rejected", status=exc.status, message=exc.message))
        api.close()
        return None
    name = user.get("global_name") or user.get("username", "?")
    discriminator = user.get("discriminator", "0")
    shown = f"{name}#{discriminator}" if discriminator != "0" else name
    ui.ok(t("login.ok", name=shown, id=user.get("id", "?")))
    log_event(f"login ok: {user.get('id', '?')}")
    return api


def choose_guild(api: DiscordAPI, label: str, preferred: Optional[str] = None) -> Optional[str]:
    try:
        guilds = api.list_guilds()
    except DiscordError as exc:
        ui.err(t("guild.list_failed", status=exc.status, message=exc.message))
        return None
    if not guilds:
        ui.err(t("guild.none"))
        return None
    if preferred:
        match = next((g for g in guilds if str(g.get("id")) == preferred), None)
        if match:
            ui.ok(t("guild.selected", label=label, name=match.get("name"), id=preferred))
            return preferred
        ui.err(t("guild.missing", id=preferred))
        return None
    rows = []
    for guild in guilds[:200]:
        rows.append((
            str(guild.get("name", "?"))[:40],
            str(guild.get("id", "?")),
            "owner" if guild.get("owner") else "",
        ))
    ui.table((t("table.server"), t("table.id"), t("table.flags")), rows)
    index = ui.pick_from_list([f"{r[0]}  {r[1]}" for r in rows], t("pick.prompt", label=label))
    if index is None:
        raw = ui.prompt(t("prompt.guild_id"))
        if raw.isdigit() and any(str(g.get("id")) == raw for g in guilds):
            return raw
        return None
    return str(rows[index][1])


def choose_sections(defaults: Optional[Dict[str, bool]] = None) -> Dict[str, bool]:
    base = {name: True for name in SECTIONS}
    if defaults:
        base.update(defaults)
    ui.info(t("sections.list", list=", ".join(SECTIONS)))
    raw = ui.prompt(t("prompt.sections")).lower()
    if not raw or raw == "all":
        return base
    if raw == "none":
        return {name: False for name in SECTIONS}
    picked = {part.strip() for part in raw.split(",") if part.strip()}
    unknown = picked - set(SECTIONS)
    if unknown:
        ui.warn(t("sections.unknown", list=", ".join(sorted(unknown))))
    return {name: name in picked for name in SECTIONS}


def parse_sections(raw: Optional[str]) -> Optional[Dict[str, bool]]:
    if raw is None:
        return None
    picked = {part.strip() for part in raw.split(",") if part.strip()}
    if not picked:
        return None
    return {name: name in picked for name in SECTIONS}


def print_plan(plan: Dict[str, Any], options: CloneOptions) -> None:
    print()
    ui.table((t("table.item"), t("table.value")), [
        (t("plan.from"), plan["source"]),
        (t("plan.to"), f"{plan['target']} ({plan['target_id']})"),
        ("roles", plan["roles"]),
        ("categories", plan["categories"]),
        ("channels", plan["channels"]),
        ("emojis", plan["emojis"]),
        ("stickers", plan["stickers"]),
        ("invites", plan["invites"]),
        ("webhooks", plan["webhooks"]),
        (t("plan.mode"), t("plan.dry") if options.dry_run else t("plan.live")),
        (t("plan.clean"), t("plan.yes") if options.delete_first else t("plan.no")),
    ])
    enabled = [name for name, value in options.sections.items() if value]
    ui.info(t("sections.list", list=", ".join(enabled) or t("sections.none")))


def print_report(report: CloneReport) -> None:
    print()
    if report.dry_run:
        ui.info(t("dryrun.done"))
    else:
        for section, count in sorted(report.created.items()):
            if count:
                ui.ok(t("section.done", section=section, count=count))
    if report.invites:
        ui.info(t("invites.count", count=len(report.invites)))
        for invite in report.invites[:20]:
            print("    " + invite)
    if report.failed:
        ui.warn(t("failures.count", count=len(report.failed)))
        for failure in report.failed[:15]:
            print("    " + failure[:180])
    ui.info(t("api.requests", count=report.api_requests))
    log_event(f"clone finished: {report.created} failures={len(report.failed)}")


def make_options(settings: Settings, args: argparse.Namespace,
                 interactive: bool, delete_default: Optional[bool] = None) -> CloneOptions:
    sections = parse_sections(args.sections)
    if sections is None and interactive:
        sections = choose_sections()
    if sections is None:
        sections = {name: True for name in SECTIONS}
    delete_first = (not args.no_delete) and (
        bool(delete_default) if delete_default is not None else settings.delete_first_default)
    if interactive and not args.yes and settings.confirm_destructive:
        ui.warn(t("clean.warning"))
        delete_first = ui.confirm(t("confirm.clear"), delete_first)
    return CloneOptions(
        sections=sections,
        dry_run=args.dry_run,
        delete_first=delete_first,
    )


def do_clone(api: DiscordAPI, settings: Settings, snapshot: Dict[str, Any],
             args: argparse.Namespace, target_id: str) -> None:
    options = make_options(settings, args, interactive=not args.yes)
    cloner = Cloner(api, settings, log=ui.info, progress=ui.progress, progress_done=ui.progress_done)
    plan = cloner.plan(snapshot, target_id)
    print_plan(plan, options)
    if not args.yes and not options.dry_run and not ui.confirm(t("confirm.start"), True):
        return
    log_event(f"clone start: {plan['source']} -> {plan['target_id']} dry={options.dry_run}")
    report = cloner.execute(snapshot, target_id, options)
    print_report(report)


def do_backup(api: DiscordAPI, settings: Settings, guild_id: str, args: argparse.Namespace) -> None:
    sections = parse_sections(args.sections) or {name: True for name in SECTIONS}
    ui.info(t("capture.snapshot"))
    snapshot = capture(api, guild_id, settings, sections)
    counts = section_counts(snapshot)
    ui.table((t("table.section"), t("table.items")), [(key, value) for key, value in counts.items()])
    for warning in snapshot.get("warnings", []):
        ui.warn(warning)
    name = str(snapshot["guild"].get("name", "server"))
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    default_path = os.path.join(app_dir(), "backups", f"{name}_{stamp}.json")
    path = args.backup if args.backup and args.backup.lower().endswith(".json") else default_path
    if save_snapshot(snapshot, path):
        ui.ok(t("backup.saved", path=path))
        log_event(f"backup saved: {path}")
    else:
        ui.err(t("backup.write_failed"))


def do_restore(api: DiscordAPI, settings: Settings, args: argparse.Namespace, target_id: str) -> None:
    path = args.restore or ui.prompt(t("prompt.backup_path"))
    try:
        snapshot = load_snapshot(path, settings)
    except (ValueError, OSError) as exc:
        ui.err(t("backup.load_failed", error=exc))
        return
    ui.ok(t("backup.loaded", name=snapshot.get('guild', {}).get('name', '?')))
    do_clone(api, settings, snapshot, args, target_id)


def do_compare(api: DiscordAPI, settings: Settings, args: argparse.Namespace, guild_id: str) -> None:
    path = args.compare or ui.prompt(t("prompt.backup_path"))
    try:
        backup = load_snapshot(path, settings)
    except (ValueError, OSError) as exc:
        ui.err(t("backup.load_failed", error=exc))
        return
    ui.info(t("capture.live"))
    live = capture(api, guild_id, settings)
    differences = diff_snapshots(backup, live)
    if not differences:
        ui.ok(t("diff.none"))
        return
    ui.warn(t("diff.count", count=len(differences)))
    for line in differences[:60]:
        print("    " + line)


def do_audit(api: DiscordAPI, guild_id: str) -> None:
    try:
        guild = api.get_guild(guild_id)
        roles = api.get_roles(guild_id)
        channels = api.get_channels(guild_id)
        emojis = api.get_emojis(guild_id)
        stickers = api.get_stickers(guild_id)
    except DiscordError as exc:
        ui.err(t("audit.failed", status=exc.status, message=exc.message))
        return
    counts = {
        "roles": len(roles),
        "channels": len(channels),
        "emojis": len(emojis),
        "stickers": len(stickers),
        "members": guild.get("approximate_member_count", "?"),
        "boosts": guild.get("premium_subscription_count", "?"),
        "verification": guild.get("verification_level", "?"),
        "features": ", ".join((guild.get("features") or [])[:6]) or "none",
    }
    ui.table((t("table.field"), t("table.value")), [(key, str(value)[:60]) for key, value in counts.items()])


def do_settings(settings: Settings) -> None:
    while True:
        ui.table((t("table.setting"), t("table.value")), [
            ("api_base", settings.api_base),
            ("request_delay", settings.request_delay),
            ("timeout", settings.timeout),
            ("max_retries", settings.max_retries),
            ("delete_first_default", settings.delete_first_default),
            ("copy_invites", settings.copy_invites),
            ("copy_webhooks", settings.copy_webhooks),
            ("copy_stickers", settings.copy_stickers),
            ("confirm_destructive", settings.confirm_destructive),
            ("language", language_name(get_language())),
            ("log_file", settings.log_file),
        ])
        choice = ui.menu(t("menu.settings"), [
            t("settings.delay"), t("settings.delete"), t("settings.invites"),
            t("settings.webhooks"), t("settings.stickers"), t("settings.confirm"),
            t("settings.language"), t("settings.reset"), t("settings.save"),
        ])
        if choice == "1":
            value = ui.prompt(t("prompt.delay"), str(settings.request_delay))
            try:
                settings.request_delay = max(0.0, min(5.0, float(value)))
            except ValueError:
                ui.err(t("err.number"))
        elif choice == "2":
            settings.delete_first_default = ui.confirm(t("confirm.clear_default"), settings.delete_first_default)
        elif choice == "3":
            settings.copy_invites = ui.confirm(t("confirm.copy_invites"), settings.copy_invites)
        elif choice == "4":
            settings.copy_webhooks = ui.confirm(t("confirm.copy_webhooks"), settings.copy_webhooks)
        elif choice == "5":
            settings.copy_stickers = ui.confirm(t("confirm.copy_stickers"), settings.copy_stickers)
        elif choice == "6":
            settings.confirm_destructive = ui.confirm(t("confirm.ask_clean"), settings.confirm_destructive)
        elif choice == "7":
            current = settings.language if settings.language != "auto" else get_language()
            ui.info(t("language.current", name=language_name(current)))
            for index, (code, name) in enumerate(LANGUAGES, 1):
                print(f"    [{index}] {name} ({code})")
            print(f"    [auto] {language_name(resolve('auto'))} (auto)")
            raw = ui.prompt(t("language.prompt"), current).strip().lower()
            picked = None
            if raw.isdigit() and 1 <= int(raw) <= len(LANGUAGES):
                picked = LANGUAGES[int(raw) - 1][0]
            elif raw in language_codes():
                picked = raw
            elif raw in ("auto", "a"):
                picked = "auto"
            if picked:
                settings.language = picked
                set_language(picked)
                settings.save()
            else:
                ui.err(t("err.invalid"))
        elif choice == "8":
            fresh = Settings()
            for key, value in fresh.__dict__.items():
                setattr(settings, key, value)
            set_language(settings.language)
        elif choice == "9" or choice == "0":
            settings.save()
            ui.ok(t("settings.saved"))
            return


def interactive(token: str, settings: Settings, args: argparse.Namespace) -> None:
    api = open_api(token, settings)
    if api is None:
        return
    first = True
    try:
        while True:
            if not first:
                ui.banner()
            first = False
            choice = ui.menu(t("menu.main"), [
                t("main.clone"),
                t("main.backup"),
                t("main.restore"),
                t("main.compare"),
                t("main.list"),
                t("main.audit"),
                t("main.settings"),
                t("main.switch"),
            ])
            if choice == "0":
                return
            try:
                if choice == "1":
                    source = choose_guild(api, t("label.source"), args.source)
                    if source:
                        target = choose_guild(api, t("label.target"), args.target)
                        if target:
                            snapshot = capture(api, source, settings)
                            do_clone(api, settings, snapshot, args, target)
                elif choice == "2":
                    source = choose_guild(api, t("label.source"), args.source)
                    if source:
                        do_backup(api, settings, source, args)
                elif choice == "3":
                    target = choose_guild(api, t("label.target"), args.target)
                    if target:
                        do_restore(api, settings, args, target)
                elif choice == "4":
                    guild = choose_guild(api, t("label.server"), args.target)
                    if guild:
                        do_compare(api, settings, args, guild)
                elif choice == "5":
                    try:
                        guilds = api.list_guilds()
                    except DiscordError as exc:
                        ui.err(t("guild.list_failed", status=exc.status, message=exc.message))
                    else:
                        ui.table((t("table.server"), t("table.id"), t("table.flags")), [
                            (str(g.get("name", "?"))[:40], str(g.get("id", "?")),
                             "owner" if g.get("owner") else "") for g in guilds
                        ])
                elif choice == "6":
                    guild = choose_guild(api, t("label.server"), args.target)
                    if guild:
                        do_audit(api, guild)
                elif choice == "7":
                    do_settings(settings)
                elif choice == "8":
                    return "switch"
                else:
                    ui.err(t("err.invalid"))
            except DiscordError as exc:
                ui.err(t("err.api", status=exc.status, message=exc.message))
                log_event(f"api error: {exc.status} {exc.message}")
    finally:
        api.close()


def run_batch(api: DiscordAPI, settings: Settings, args: argparse.Namespace) -> None:
    try:
        if args.backup:
            source = args.source or ui.prompt(t("prompt.source_id"))
            do_backup(api, settings, source, args)
            return
        if args.restore:
            target = args.target or ui.prompt(t("prompt.target_id"))
            do_restore(api, settings, args, target)
            return
        if args.compare:
            guild = args.target or ui.prompt(t("prompt.guild_id"))
            do_compare(api, settings, args, guild)
            return
        if not args.source or not args.target:
            ui.err(t("batch.needs"))
            return
        ui.info(t("capture.source"))
        snapshot = capture(api, args.source, settings, parse_sections(args.sections))
        do_clone(api, settings, snapshot, args, args.target)
    finally:
        api.close()


def main(argv: Optional[List[str]] = None) -> int:
    global _SETTINGS
    ui.prepare_console()
    args = parse_args(argv)
    _SETTINGS = Settings.load()
    settings = _SETTINGS
    if args.language:
        settings.language = args.language.strip().lower() if args.language.strip().lower() == "auto" else resolve(args.language)
        settings.save()
    set_language(settings.language)
    ui.banner()
    token = get_token(settings, args.token)
    if not token:
        return 1
    batch = bool(args.backup or args.restore or args.compare or args.source or args.target)
    try:
        if batch:
            api = open_api(token, settings)
            if api is None:
                return 1
            run_batch(api, settings, args)
            return 0
        while True:
            result = interactive(token, settings, args)
            if result != "switch":
                return 0
            ui.banner()
            token = get_token(settings)
            if not token:
                return 1
    except KeyboardInterrupt:
        print()
        ui.warn(t("interrupted"))
        return 130


if __name__ == "__main__":
    sys.exit(main())
