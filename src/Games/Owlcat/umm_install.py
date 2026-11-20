"""GUI-free Unity Mod Manager (Doorstop Proxy) installer for Kingmaker / Wrath.

Reproduces what UMM's own installer (``UnityModManagerApp/Form.cs``,
``InstallDoorstop``) writes for the Doorstop Proxy method, so no Windows app has
to run under Wine:

* ``winhttp.dll`` - UMM's ``winhttp_x64.dll`` / ``winhttp_x86.dll``, matching
  the game exe's architecture;
* ``doorstop_config.ini`` - points Doorstop at ``UnityModManager.dll``;
* ``<Exe>_Data/Managed/UnityModManager/`` - the manager libraries plus
  ``Config.xml``, the game's ``<GameInfo>`` entry from the archive's
  ``UnityModManagerConfig*.xml`` saved under a ``<Config>`` root (UMM's
  ``GameInfo`` type serializes with ``XmlRoot("Config")``).

The files are laid out relative to the game root in a temporary folder and
handed to the shared wizard payload installer, which puts them in the game
folder, Root_Folder or a managed root-flagged mod.
"""

from __future__ import annotations

import shutil
import struct
import tempfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Callable
from xml.sax.saxutils import escape, quoteattr

if TYPE_CHECKING:
    from Games.base_game import BaseGame

LogFn = Callable[[str], None]

MOD_NAME = "Unity Mod Manager"
_CONFIG_PREFIX = "unitymodmanagerconfig"
_MANAGER = "UnityModManager"
# (source path in the installer, condition) - mirrors Form.cs libraryFiles.
_LIBRARIES = (
    ("0Harmony.dll", "always"),
    ("Harmony/2.2/0Harmony.dll", "harmony_2_2"),
    ("Harmony/1.2/0Harmony12.dll", "below_0_22"),
    ("Harmony/1.2/0Harmony-1.2.dll", "below_0_22"),
    ("dnlib.dll", "always"),
    ("System.Xml.dll", "no_game_system_xml"),
    ("UnityModManager.dll", "always"),
    ("UnityModManager.xml", "always"),
)
_PE_MACHINE_X86 = 0x014C


def _noop(_message: str) -> None:
    pass


def _error(name: str, message: str, details: dict | None = None):
    from Utils.wizards.payload import PayloadInstallError
    return PayloadInstallError(name, message, details)


def _child(parent: Path, name: str) -> Path | None:
    from Games.Owlcat.owlcat_base import find_child
    return find_child(parent, name) if parent.is_dir() else None


def _resolve(parent: Path, rel: str) -> Path | None:
    current: Path | None = parent
    for part in rel.split("/"):
        current = _child(current, part) if current is not None else None
    return current if current is not None and current.is_file() else None


def find_installer_root(extracted: Path) -> Path:
    """The folder of an unpacked UMM archive holding its config and manager."""
    for config in sorted(extracted.rglob("*")):
        if (config.is_file() and config.name.casefold() == "unitymodmanagerconfig.xml"
                and _resolve(config.parent, "UnityModManager.dll") is not None):
            return config.parent
    raise _error("umm_archive_invalid",
                 "This archive isn't a Unity Mod Manager installer "
                 "(UnityModManagerConfig.xml and UnityModManager.dll not found).")


def _version(text: str | None) -> tuple[int, ...]:
    parts = []
    for piece in (text or "").strip().split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def find_game_info(installer: Path, exe: str) -> ET.Element:
    """The ``<GameInfo>`` entry whose ``GameExe`` is *exe* (main config first)."""
    configs = sorted((path for path in installer.iterdir() if path.is_file()
                      and path.name.casefold().startswith(_CONFIG_PREFIX)
                      and path.suffix.casefold() == ".xml"),
                     key=lambda path: (path.name.casefold() != "unitymodmanagerconfig.xml",
                                       path.name.casefold()))
    for config in configs:
        try:
            root = ET.parse(config).getroot()
        except (ET.ParseError, OSError):
            continue
        for info in root.iter("GameInfo"):
            if (info.findtext("GameExe") or "").strip().casefold() == exe.casefold():
                return info
    raise _error("umm_game_unsupported",
                 f"This Unity Mod Manager version has no entry for {exe}.", {"exe": exe})


def config_xml(info: ET.Element) -> bytes:
    """Serialize a ``<GameInfo>`` entry the way UMM writes ``Config.xml``."""
    lines = ['<?xml version="1.0" encoding="utf-8"?>',
             '<Config xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
             'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
             f'Name={quoteattr(info.get("Name", ""))}>']
    for child in info:
        if isinstance(child.tag, str):
            lines.append(f"  <{child.tag}>{escape((child.text or '').strip())}</{child.tag}>")
    lines.append("</Config>")
    return "\r\n".join(lines).encode("utf-8")


def _is_32bit(exe: Path) -> bool:
    """True only when *exe* is a readable i386 PE image (UMM's default is x64)."""
    try:
        with exe.open("rb") as handle:
            head = handle.read(0x40)
            if len(head) < 0x40 or head[:2] != b"MZ":
                return False
            handle.seek(struct.unpack_from("<I", head, 0x3C)[0])
            pe = handle.read(6)
    except OSError:
        return False
    return len(pe) == 6 and pe[:4] == b"PE\0\0" and \
        struct.unpack_from("<H", pe, 4)[0] == _PE_MACHINE_X86


def build_umm_payload(installer: Path, game_root: Path, exe: str, dest: Path) -> list[Path]:
    """Lay out UMM's Doorstop install under *dest*; return the relative files."""
    data = _child(game_root, f"{Path(exe).stem}_Data")
    managed = _child(data, "Managed") if data is not None else None
    if managed is None or not managed.is_dir():
        raise _error("umm_game_files_missing",
                     f"{Path(exe).stem}_Data/Managed was not found in the game folder.",
                     {"game": str(game_root)})
    info = find_game_info(installer, exe)
    below_0_22 = _version(info.findtext("MinimalManagerVersion") or "0.22") < (0, 22)
    harmony_2_2 = _version(info.findtext("HarmonyVersion")) == (2, 2)
    has_system_xml = _child(managed, "System.Xml.dll") is not None

    manager_rel = Path(data.name) / managed.name / _MANAGER
    files: dict[Path, Path | bytes] = {}
    proxy = "winhttp_x86.dll" if _is_32bit(game_root / exe) else "winhttp_x64.dll"
    proxy_src = _resolve(installer, proxy)
    if proxy_src is None:
        raise _error("umm_archive_invalid", f"{proxy} is missing from the archive.")
    files[Path("winhttp.dll")] = proxy_src
    target = "\\".join((*manager_rel.parts, "UnityModManager.dll"))
    files[Path("doorstop_config.ini")] = (
        f"[General]\r\nenabled = true\r\ntarget_assembly = {target}").encode("utf-8")
    for rel, condition in _LIBRARIES:
        wanted = {"always": True, "harmony_2_2": harmony_2_2, "below_0_22": below_0_22,
                  "no_game_system_xml": not has_system_xml}[condition]
        if not wanted:
            continue
        source = _resolve(installer, rel)
        if source is None:
            raise _error("umm_archive_invalid", f"{rel} is missing from the archive.")
        files[manager_rel / Path(rel).name] = source  # later entries win (Harmony 2.2)
    files[manager_rel / "Config.xml"] = config_xml(info)

    for rel, content in files.items():
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            out.write_bytes(content)
        else:
            shutil.copyfile(content, out)
    return sorted(files)


@contextmanager
def prepare_umm_payload(game: "BaseGame", archive: Path, *, log_fn: LogFn = _noop,
                        checkpoint=lambda: None):
    """Extract *archive* and yield a PreparedPayload of UMM's game files."""
    from Utils.wizards.archives import extract_to_dir
    from Utils.wizards.payload import PreparedPayload, archive_token

    archive = Path(archive)
    identity = archive_token(archive)
    game_root = game.get_game_path()
    if game_root is None or not Path(game_root).is_dir():
        raise _error("umm_game_files_missing", "The game path is not configured.")
    with tempfile.TemporaryDirectory(prefix="amethyst-umm-") as raw:
        extracted, payload_root = Path(raw) / "archive", Path(raw) / "payload"
        extract_to_dir(archive, extracted, log_fn=log_fn)
        checkpoint()
        installer = find_installer_root(extracted)
        files = build_umm_payload(installer, Path(game_root), game.exe_name, payload_root)
        log_fn(f"UMM Wizard: prepared {len(files)} file(s) for {game.name}.")
        payload = PreparedPayload(archive, payload_root, tuple(files), identity)
        payload.check_archive()
        yield payload


def install_umm(game: "BaseGame", archive: Path, mode: str = "mod", *,
                restore_first: bool = False, delete_archive: bool = False,
                log_fn: LogFn = _noop) -> tuple[str, int, str | None]:
    """Install UMM into the game folder, Root_Folder or a managed root mod."""
    from Utils.wizards.payload import install_prepared_payload
    with prepare_umm_payload(game, archive, log_fn=log_fn) as payload:
        return install_prepared_payload(
            game, payload, mode, mod_fallback_name=MOD_NAME, mod_name_override=MOD_NAME,
            restore_first=restore_first, delete_archive=delete_archive, log_fn=log_fn)
