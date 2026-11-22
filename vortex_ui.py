"""Console presentation helpers for VORTEX CLONER."""
from __future__ import annotations

import getpass
import os
import shutil
import sys
from typing import Iterable, Optional, Sequence

from vortex_config import APP_NAME, MADE_BY, VERSION
from vortex_i18n import t

try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=False)
    _GREEN = Fore.GREEN
    _RED = Fore.RED
    _YELLOW = Fore.YELLOW
    _CYAN = Fore.CYAN
    _MAGENTA = Fore.MAGENTA
    _DIM = Style.DIM
    _RESET = Style.RESET_ALL
except Exception:  # colorama is optional
    _GREEN = _RED = _YELLOW = _CYAN = _MAGENTA = _DIM = _RESET = ""

BANNER = r"""
██╗   ██╗ ██████╗ ██████╗ ████████╗███████╗██╗  ██╗
██║   ██║██╔═══██╗██╔══██╗╚══██╔══╝██╔════╝╚██╗██╔╝
██║   ██║██║   ██║██████╔╝   ██║   █████╗   ╚███╔╝
╚██╗ ██╔╝██║   ██║██╔══██╗   ██║   ██╔══╝   ██╔██╗
 ╚████╔╝ ╚██████╔╝██║  ██║   ██║   ███████╗██╔╝ ██╗
  ╚═══╝   ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚══════╝╚═╝  ╚═╝

 ██████╗██╗      ██████╗ ███╗   ██╗███████╗██████╗
██╔════╝██║     ██╔═══██╗████╗  ██║██╔════╝██╔══██╗
██║     ██║     ██║   ██║██╔██╗ ██║█████╗  ██████╔╝
██║     ██║     ██║   ██║██║╚██╗██║██╔══╝  ██╔══██╗
╚██████╗███████╗╚██████╔╝██║ ╚████║███████╗██║  ██║
 ╚═════╝╚══════╝ ╚═════╝ ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝
"""


def prepare_console() -> None:
    """Make block characters survive Windows console code pages."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _masked_input(text: str) -> str:
    """Read a secret while echoing a star per character.

    getpass writes nothing on some Windows consoles, which looks like a dead
    field. Stars give feedback without putting the token on screen.
    """
    if os.name != "nt":
        return getpass.getpass(text)
    try:
        import msvcrt
    except ImportError:
        return getpass.getpass(text)
    sys.stdout.write(text)
    sys.stdout.flush()
    chars: list[str] = []
    while True:
        try:
            char = msvcrt.getwch()
        except (OSError, ValueError):
            sys.stdout.write("\n")
            return getpass.getpass("")
        if char in ("\r", "\n"):
            sys.stdout.write("\n")
            return "".join(chars)
        if char == "\x03":
            sys.stdout.write("\n")
            raise KeyboardInterrupt
        if char == "\x08":
            if chars:
                chars.pop()
                sys.stdout.write("\b \b")
                sys.stdout.flush()
            continue
        if char in ("\x00", "\xe0"):
            msvcrt.getwch()
            continue
        if not char.isprintable():
            continue
        chars.append(char)
        sys.stdout.write("*")
        sys.stdout.flush()


def banner() -> None:
    prepare_console()
    print(_MAGENTA + BANNER + _RESET)
    print(f"  {_CYAN}{APP_NAME}{_RESET}  {_DIM}v{VERSION}{_RESET}")
    print(f"  {_DIM}{t('ui.made_by', name=MADE_BY)}{_RESET}")
    print("  " + "─" * 58)


def ok(message: str) -> None:
    print(f"{_GREEN}[+]{_RESET} {message}")


def err(message: str) -> None:
    print(f"{_RED}[!]{_RESET} {message}")


def warn(message: str) -> None:
    print(f"{_YELLOW}[~]{_RESET} {message}")


def info(message: str) -> None:
    print(f"{_CYAN}[*]{_RESET} {message}")


def step(index: int, total: int, message: str) -> None:
    print(f"{_MAGENTA}[{index}/{total}]{_RESET} {message}")


def progress(done: int, total: int, label: str = "") -> None:
    if total <= 0:
        return
    width = max(10, min(40, shutil.get_terminal_size((80, 24)).columns - 34))
    filled = int(width * done / total)
    bar = "█" * filled + "░" * (width - filled)
    text = f"\r  {label[:26]:<26} {bar} {done}/{total}"
    sys.stdout.write(text)
    sys.stdout.flush()


def progress_done() -> None:
    sys.stdout.write("\n")
    sys.stdout.flush()


def menu(title: str, options: Sequence[str]) -> str:
    print()
    print(f"  {_MAGENTA}{title}{_RESET}")
    for index, option in enumerate(options, 1):
        print(f"    {_CYAN}[{index}]{_RESET} {option}")
    print(f"    {_DIM}[0]{_RESET} {t('ui.back')}")
    return prompt(t("ui.choose"))


def prompt(label: str, default: Optional[str] = None, password: bool = False) -> str:
    suffix = f" ({default})" if default else ""
    text = f"{_RED}>{_RESET} {label}{suffix}: "
    try:
        value = _masked_input(text) if password else input(text)
    except (EOFError, KeyboardInterrupt):
        print()
        return ""
    value = value.strip()
    return value if value else (default or "")


def confirm(label: str, default: bool = False) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        value = prompt(f"{label} [{hint}]").lower()
        if not value:
            return default
        if value in ("y", "yes", "s", "si", "sì", "sí", "oui", "ja", "д", "да",
                     "e", "evet", "t", "tak", "是", "はい", "예", "네"):
            return True
        if value in ("n", "no", "non", "nein", "нет", "hayır", "nie", "否", "いいえ",
                     "아니오", "아니요"):
            return False


def pick_from_list(items: Iterable[str], label: str) -> Optional[int]:
    rows = list(items)
    if not rows:
        err("nothing to pick from")
        return None
    for index, row in enumerate(rows, 1):
        print(f"    {_CYAN}[{index}]{_RESET} {row}")
    raw = prompt(label)
    if not raw.isdigit():
        return None
    number = int(raw)
    if number < 1 or number > len(rows):
        return None
    return number - 1


def table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
    cells = [[str(cell) for cell in row] for row in rows]
    widths = [len(header) for header in headers]
    for row in cells:
        for index, cell in enumerate(row):
            if index < len(widths):
                widths[index] = min(48, max(widths[index], len(cell)))
    line = "  ".join(header.ljust(widths[i]) for i, header in enumerate(headers))
    print("  " + _DIM + line + _RESET)
    print("  " + "─" * len(line))
    for row in cells:
        print("  " + "  ".join(cell[:widths[i]].ljust(widths[i]) for i, cell in enumerate(row)))


def pause() -> None:
    input(f"\n{_DIM}press enter to continue...{_RESET}")
