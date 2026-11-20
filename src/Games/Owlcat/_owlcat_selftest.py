"""Focused checks for the Owlcat (Pathfinder / Rogue Trader) handlers.

Run directly from the source tree::

    python3 src/Games/Owlcat/_owlcat_selftest.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# Handlers create their config dirs on construction; keep them out of ~/.config.
_CONFIG = tempfile.TemporaryDirectory()
os.environ["XDG_CONFIG_HOME"] = _CONFIG.name

_SRC_ROOT = Path(__file__).resolve().parents[2]
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from Games.Owlcat.owlcat_base import (  # noqa: E402
    TEMPLATE_MANIFEST, UMM_MANIFEST, apply_settings_sync, classify_mod_dir,
    locallow_rel, sync_enabled, template_id,
)

_RT_DIR = "Warhammer 40000 Rogue Trader"


def test_locallow_rel_variants() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        prefix = Path(tmp) / "a"
        (prefix / "drive_c" / "users" / "steamuser").mkdir(parents=True)
        assert locallow_rel(prefix, _RT_DIR) == (
            "drive_c/users/steamuser/AppData/LocalLow/Owlcat Games/" + _RT_DIR)

        user = os.environ.get("USER") or "someone"
        os.environ["USER"] = user
        prefix2 = Path(tmp) / "b"
        (prefix2 / "pfx" / "drive_c" / "users" / user).mkdir(parents=True)
        assert locallow_rel(prefix2, _RT_DIR) == (
            f"pfx/drive_c/users/{user}/AppData/LocalLow/Owlcat Games/{_RT_DIR}")

        prefix3 = Path(tmp) / "c"
        (prefix3 / "drive_c" / "users").mkdir(parents=True)
        assert locallow_rel(prefix3, _RT_DIR) == (
            "drive_c/users/steamuser/AppData/LocalLow/Owlcat Games/" + _RT_DIR)

        assert locallow_rel(None, _RT_DIR) is None
        empty = Path(tmp) / "d"
        empty.mkdir()
        assert locallow_rel(empty, _RT_DIR) is None
    print("✓ locallow_rel variants")


def test_classify() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        umm = root / "umm"
        umm.mkdir()
        (umm / UMM_MANIFEST).write_text("{}")
        both = root / "both"
        both.mkdir()
        (both / UMM_MANIFEST).write_text("{}")
        (both / TEMPLATE_MANIFEST).write_text("{}")
        tmpl = root / "tmpl"
        tmpl.mkdir()
        (tmpl / TEMPLATE_MANIFEST).write_text("{}")
        neither = root / "neither"
        neither.mkdir()
        (neither / "readme.txt").write_text("")
        assert classify_mod_dir(umm) == "umm"
        assert classify_mod_dir(both) == "umm"
        assert classify_mod_dir(tmpl) == "template"
        assert classify_mod_dir(neither) is None
    print("✓ classify_mod_dir")


def test_template_id() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        unit = Path(tmp) / "mymod-1.2"
        unit.mkdir()
        (unit / TEMPLATE_MANIFEST).write_text(json.dumps({"UniqueName": "MyMod"}))
        assert template_id(unit) == "MyMod"
        (unit / TEMPLATE_MANIFEST).write_bytes(
            b"\xef\xbb\xbf" + json.dumps({"UniqueName": "BomMod"}).encode())
        assert template_id(unit) == "BomMod"
        (unit / TEMPLATE_MANIFEST).write_text("{not json")
        assert template_id(unit) is None
        (unit / TEMPLATE_MANIFEST).write_text(json.dumps({"UniqueName": "  "}))
        assert template_id(unit) is None
    print("✓ template_id")


def test_sync_adds_and_removes_managed() -> None:
    result, state = sync_enabled([], ["A"], {})
    assert result == ["A"]
    assert state["managed"] == ["A"]
    result, state = sync_enabled(result, [], state)
    assert result == []
    assert state["managed"] == []
    print("✓ sync adds and removes managed ids")


def test_sync_keeps_unmanaged_order() -> None:
    result, _state = sync_enabled(["X", "Y"], ["A"], {})
    assert result == ["X", "Y", "A"]
    print("✓ sync keeps unmanaged entries in order")


def test_sync_user_owned_survives_disable() -> None:
    result, state = sync_enabled(["toybox"], ["ToyBox"], {})
    assert result == ["toybox"]
    assert [v.casefold() for v in state["user_owned"]] == ["toybox"]
    assert state["managed"] == []
    result, state = sync_enabled(result, [], state)
    assert result == ["toybox"]
    print("✓ user-added entry survives disable")


def test_apply_preserves_other_keys() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        settings = Path(tmp) / "settings.json"
        settings.write_text(json.dumps(
            {"$id": "1", "SourceDirectories": [], "EnabledModifications": []}))
        logs: list[str] = []
        assert apply_settings_sync(settings, ["A"], Path(tmp) / "state.json", logs.append)
        data = json.loads(settings.read_text())
        assert data == {"$id": "1", "SourceDirectories": [], "EnabledModifications": ["A"]}
    print("✓ apply preserves other keys")


def test_apply_invalid_json_untouched() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        settings = Path(tmp) / "settings.json"
        settings.write_bytes(b"{not json")
        logs: list[str] = []
        assert not apply_settings_sync(settings, ["A"], Path(tmp) / "state.json", logs.append)
        assert settings.read_bytes() == b"{not json"
        assert any(str(settings) in line for line in logs)
        settings.write_text(json.dumps({"EnabledModifications": "oops"}))
        before = settings.read_bytes()
        assert not apply_settings_sync(settings, ["A"], Path(tmp) / "state.json", logs.append)
        assert settings.read_bytes() == before
    print("✓ apply leaves invalid settings untouched")


def test_apply_creates_missing_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        settings = Path(tmp) / "LocalLow" / "settings.json"
        state = Path(tmp) / "state.json"
        assert apply_settings_sync(settings, ["A"], state, lambda _m: None)
        assert json.loads(settings.read_text()) == {"EnabledModifications": ["A"]}
        assert json.loads(state.read_text())["managed"] == ["A"]
    print("✓ apply creates missing settings file")


def _games():
    from Games.Owlcat.pathfinder_kingmaker import PathfinderKingmaker
    from Games.Owlcat.pathfinder_wotr import PathfinderWotR
    from Games.Owlcat.rogue_trader import RogueTrader
    return PathfinderKingmaker(), PathfinderWotR(), RogueTrader()


def _point(game, root: Path, *, prefix: bool = True) -> None:
    game._game_path = root / "game"
    game._game_path.mkdir(parents=True, exist_ok=True)
    if prefix:
        game._prefix_path = root / "pfx"
        (game._prefix_path / "drive_c" / "users" / "steamuser").mkdir(
            parents=True, exist_ok=True)
    else:
        game._prefix_path = None


def test_identity() -> None:
    km, wotr, rt = _games()
    assert (km.game_id, km.exe_name, km.steam_id, km.nexus_game_domain) == (
        "pathfinder_kingmaker", "Kingmaker.exe", "640820", "pathfinderkingmaker")
    assert (wotr.game_id, wotr.exe_name, wotr.steam_id, wotr.nexus_game_domain) == (
        "pathfinder_wotr", "Wrath.exe", "1184370", "pathfinderwrathoftherighteous")
    assert (rt.game_id, rt.exe_name, rt.steam_id, rt.nexus_game_domain) == (
        "rogue_trader", "WH40KRT.exe", "2186680", "warhammer40kroguetrader")
    print("✓ identity")


def test_data_paths() -> None:
    _km, wotr, rt = _games()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _point(wotr, root)
        _point(rt, root)
        assert wotr.get_mod_data_path() == root / "game" / "Mods"
        assert rt.get_mod_data_path() == (
            root / "pfx" / "drive_c/users/steamuser/AppData/LocalLow/Owlcat Games"
            / _RT_DIR / "UnityModManager")
        _point(rt, root, prefix=False)
        assert rt.get_mod_data_path() is None
    print("✓ data paths")


def test_routing_rules() -> None:
    from Utils.deployment.custom_rules import compute_routed_destinations
    km, wotr, rt = _games()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for game in (km, wotr, rt):
            _point(game, root)
        paths = ["Modifications/B/OwlcatModificationManifest.json",
                 "Modifications/B/Assemblies/b.dll", "A/Info.json", "A/a.dll",
                 "Portraits/P/Small.png"]

        def routed(game, rel):
            claims = compute_routed_destinations(paths, game.custom_routing_rules)
            return [(to_prefix, d.lower()) for to_prefix, d in claims.get(rel, [])]

        for game, base in ((km, "Pathfinder Kingmaker"),
                           (wotr, "Pathfinder Wrath Of The Righteous"), (rt, _RT_DIR)):
            locallow = f"drive_c/users/steamuser/AppData/LocalLow/Owlcat Games/{base}".lower()
            assert routed(game, "portraits/p/small.png") == [
                (True, f"{locallow}/portraits/p/small.png")], game.name
            assert routed(game, "a/info.json") == [] and routed(game, "a/a.dll") == []
            if game is km:  # Kingmaker doesn't load Template mods
                assert routed(game, "modifications/b/assemblies/b.dll") == []
            else:
                assert routed(game, "modifications/b/assemblies/b.dll") == [
                    (True, f"{locallow}/modifications/b/assemblies/b.dll")], game.name
        _point(rt, root, prefix=False)
        assert rt.custom_routing_rules == []
    print("✓ routing rules")


def test_prepare_staging_restructures() -> None:
    _km, wotr, _rt = _games()
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "staging"
        flat_umm = staging / "FlatUMM"
        flat_umm.mkdir(parents=True)
        (flat_umm / UMM_MANIFEST).write_text("{}")
        (flat_umm / "Mod.dll").write_text("")
        flat_tmpl = staging / "FlatTmpl"
        flat_tmpl.mkdir()
        (flat_tmpl / TEMPLATE_MANIFEST).write_text("{}")
        nested = staging / "Nested" / "Inner"
        nested.mkdir(parents=True)
        (nested / TEMPLATE_MANIFEST).write_text("{}")
        dual = staging / "Dual" / "Dual"
        dual.mkdir(parents=True)
        (dual / UMM_MANIFEST).write_text("{}")
        (dual / TEMPLATE_MANIFEST).write_text("{}")
        assert wotr.prepare_mod_staging(staging, lambda _m: None)
        assert (flat_umm / "FlatUMM" / UMM_MANIFEST).is_file()
        assert (flat_umm / "FlatUMM" / "Mod.dll").is_file()
        assert (flat_tmpl / "Modifications" / "FlatTmpl" / TEMPLATE_MANIFEST).is_file()
        assert (staging / "Nested" / "Modifications" / "Inner" / TEMPLATE_MANIFEST).is_file()
        assert (dual / UMM_MANIFEST).is_file()
        assert not wotr.prepare_mod_staging(staging, lambda _m: None)
    print("✓ staging restructure")


def test_rt_excludes_bundled_umm() -> None:
    km, wotr, rt = _games()
    assert {"winhttp.dll", "doorstop_config.ini"} <= rt.excluded_loose_filenames
    assert "winhttp.dll" not in wotr.excluded_loose_filenames
    assert rt.wine_dll_overrides == {}
    assert wotr.wine_dll_overrides == {"winhttp": "native,builtin"}
    assert km.wine_dll_overrides == {"winhttp": "native,builtin"}
    print("✓ Rogue Trader excludes bundled UMM")


def test_umm_detection() -> None:
    _km, wotr, rt = _games()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _point(wotr, root)
        assert "Unity Mod Manager" in wotr.frameworks
        assert wotr.framework_installed("Unity Mod Manager") is False
        marker = root / "game" / "Wrath_Data" / "Managed" / "UnityModManager"
        marker.mkdir(parents=True)
        (marker / "UnityModManager.dll").write_text("")
        assert wotr.framework_installed("Unity Mod Manager") is True
        assert rt.frameworks == {}
    print("✓ UMM detection")


def test_discovered() -> None:
    from Utils.games import discovery
    games = discovery.discover_games()
    for name in ("Pathfinder: Kingmaker", "Pathfinder: Wrath of the Righteous",
                 "Warhammer 40,000: Rogue Trader"):
        assert name in games, name
    failures = [f for f in discovery.get_load_failures() if "Owlcat" in str(f)]
    assert not failures, failures
    print("✓ discovered")


def _profile(game, root: Path, lines: list[str]) -> Path:
    staging = root / "Profiles" / "mods"
    profile = root / "Profiles" / "profiles" / "default"
    profile.mkdir(parents=True, exist_ok=True)
    (profile / "modlist.txt").write_text("\n".join(lines) + "\n")
    game._staging_path = root / "Profiles"  # custom staging root holds mods/ + profiles/
    game._active_profile_dir = profile
    staging.mkdir(parents=True, exist_ok=True)
    return staging


def test_post_deploy_syncs_enabled_templates() -> None:
    _km, wotr, _rt = _games()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _point(wotr, root)
        staging = _profile(wotr, root, ["+TmplMod", "-OffMod", "+UmmMod"])
        unit = staging / "TmplMod" / "Modifications" / "Tm"
        unit.mkdir(parents=True)
        (unit / TEMPLATE_MANIFEST).write_text(json.dumps({"UniqueName": "TmplUnique"}))
        off = staging / "OffMod" / "Modifications" / "Off"
        off.mkdir(parents=True)
        (off / TEMPLATE_MANIFEST).write_text(json.dumps({"UniqueName": "OffUnique"}))
        umm = staging / "UmmMod" / "Umm"
        umm.mkdir(parents=True)
        (umm / UMM_MANIFEST).write_text("{}")
        wotr.pop_deploy_warnings()
        wotr.post_deploy(lambda _m: None)
        settings = (wotr.locallow_root() / "OwlcatModificationManagerSettings.json")
        assert json.loads(settings.read_text())["EnabledModifications"] == ["TmplUnique"]
        warnings = wotr.pop_deploy_warnings()
        assert any("Unity Mod Manager isn't installed" in w for w in warnings), warnings
        wotr.post_clean_game_folder(lambda _m: None)
        assert json.loads(settings.read_text())["EnabledModifications"] == []
    print("✓ post_deploy syncs enabled Template mods")


def test_post_deploy_without_prefix() -> None:
    _km, wotr, _rt = _games()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _point(wotr, root, prefix=False)
        _profile(wotr, root, [])
        logs: list[str] = []
        wotr.post_deploy(logs.append)
        assert any("launch the game once" in line for line in logs), logs
    print("✓ post_deploy without prefix")


def test_restore_whitelist_protects_umm() -> None:
    _km, wotr, rt = _games()
    match = wotr.restore_whitelist_matcher()
    assert match is not None
    for rel in ("winhttp.dll", "doorstop_config.ini",
                "wrath_data/managed/unitymodmanager/unitymodmanager.dll"):
        assert match(rel), rel
    assert not match("wrath_data/managed/assembly-csharp.dll")
    assert rt.restore_whitelist_matcher() is None
    print("✓ restore whitelist protects UMM")


def test_no_prefix_keeps_templates_out_of_mods() -> None:
    km, wotr, _rt = _games()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _point(wotr, root, prefix=False)
        assert {"modifications", "portraits"} <= wotr.filemap_exclude_dirs
        _point(wotr, root)
        assert not {"modifications", "portraits"} & wotr.filemap_exclude_dirs
        _point(km, root, prefix=False)
        assert "portraits" in km.filemap_exclude_dirs
    print("✓ no prefix keeps Template mods out of Mods/")


def test_sync_reclaims_user_removed_entry() -> None:
    _result, state = sync_enabled(["Foo"], ["Foo"], {})
    assert [v.casefold() for v in state["user_owned"]] == ["foo"]
    result, state = sync_enabled([], ["Foo"], state)  # user removed it by hand
    assert result == ["Foo"] and state["managed"] == ["Foo"]
    result, state = sync_enabled(result, [], state)
    assert result == []
    print("✓ user-removed entry becomes managed again")


def test_flat_umm_wraps_into_id_folder() -> None:
    _km, wotr, _rt = _games()
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp)
        cases = {
            "ToyBox-1.6.3": ({"Id": "ToyBox"}, "ToyBox"),
            "NoId-1.0": ({"DisplayName": "x"}, "NoId-1.0"),
            "Escape-1.0": ({"Id": "../evil"}, "Escape-1.0"),
            "Slash-1.0": ({"Id": "a\\b"}, "Slash-1.0"),
            "Dot-1.0": ({"Id": ".."}, "Dot-1.0"),
        }
        for folder, (info, _expected) in cases.items():
            mod = staging / folder
            mod.mkdir()
            (mod / UMM_MANIFEST).write_bytes(b"\xef\xbb\xbf" + json.dumps(info).encode())
            (mod / "Mod.dll").write_text("")
            assert wotr.mod_staging_wrap_subdir_name(mod) == _expected, folder
        tmpl = staging / "Tmpl-2.0"
        tmpl.mkdir()
        (tmpl / TEMPLATE_MANIFEST).write_text(json.dumps({"UniqueName": "T"}))
        assert wotr.mod_staging_wrap_subdir_name(tmpl) == "Tmpl-2.0"
        assert wotr.prepare_mod_staging(staging, lambda _m: None)
        assert (staging / "ToyBox-1.6.3" / "ToyBox" / UMM_MANIFEST).is_file()
        assert (staging / "ToyBox-1.6.3" / "ToyBox" / "Mod.dll").is_file()
        assert (staging / "NoId-1.0" / "NoId-1.0" / UMM_MANIFEST).is_file()
        assert (staging / "Escape-1.0" / "Escape-1.0" / UMM_MANIFEST).is_file()
        assert (staging / "Tmpl-2.0" / "Modifications" / "Tmpl-2.0" / TEMPLATE_MANIFEST).is_file()
    print("✓ flat UMM mods wrap into their Id folder")


def test_case_insensitive_folders_and_manifests() -> None:
    _km, wotr, _rt = _games()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _point(wotr, root)
        staging = _profile(wotr, root, ["+Lower", "+LowerUmm"])
        unit = staging / "Lower" / "modifications" / "L"
        unit.mkdir(parents=True)
        (unit / "owlcatmodificationmanifest.json").write_text(
            json.dumps({"UniqueName": "LowerUnique"}))
        umm = staging / "LowerUmm" / "mods" / "U"
        umm.mkdir(parents=True)
        (umm / "info.json").write_text("{}")
        assert classify_mod_dir(unit) == "template"
        assert classify_mod_dir(umm) == "umm"
        assert template_id(unit) == "LowerUnique"
        wotr.pop_deploy_warnings()
        wotr.post_deploy(lambda _m: None)
        settings = wotr.locallow_root() / "OwlcatModificationManagerSettings.json"
        assert json.loads(settings.read_text())["EnabledModifications"] == ["LowerUnique"]
        assert any("Unity Mod Manager isn't installed" in w
                   for w in wotr.pop_deploy_warnings())
    print("✓ case-insensitive folders and manifests")


def test_apply_does_not_create_empty_settings() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        settings = Path(tmp) / "LocalLow" / "settings.json"
        state = Path(tmp) / "state.json"
        assert apply_settings_sync(settings, [], state, lambda _m: None)
        assert not settings.exists()
        assert not settings.parent.exists()
        assert state.is_file()
    print("✓ empty sync doesn't create the settings file")


def test_reserved_ids_fall_back_to_mod_name() -> None:
    _km, wotr, _rt = _games()
    with tempfile.TemporaryDirectory() as tmp:
        for reserved in ("Mods", "modifications", "UnityModManager", "FOMOD",
                         "Portraits"):
            mod = Path(tmp) / f"Mod-{reserved}"
            mod.mkdir()
            (mod / UMM_MANIFEST).write_text(json.dumps({"Id": reserved}))
            assert wotr.mod_staging_wrap_subdir_name(mod) == mod.name, reserved
    print("✓ reserved Ids fall back to the mod name")


_PORTRAIT_PNGS = ("Fulllength.png", "Medium.png", "Small.png")


def _portrait(folder: Path, names=_PORTRAIT_PNGS) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"png")


def test_portrait_staging() -> None:
    km, wotr, _rt = _games()
    for game in (km, wotr):
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp)
            flat = staging / "Flat"
            _portrait(flat)
            (flat / "meta.ini").write_text("")
            _portrait(staging / "Pack" / "A")
            _portrait(staging / "Pack" / "B", ["medium.png"])
            _portrait(staging / "Wrapped" / "Portraits" / "C")
            _portrait(staging / "Deep" / "My Pack" / "Portraits" / "D")
            umm = staging / "Umm"
            _portrait(umm / "Art", ["Small.png"])
            (umm / UMM_MANIFEST).write_text(json.dumps({"Id": "Umm"}))
            tmpl = staging / "Tmpl" / "T"
            _portrait(tmpl / "Art", ["Small.png"])
            (tmpl / TEMPLATE_MANIFEST).write_text("{}")

            assert game.prepare_mod_staging(staging, lambda _m: None)
            for name in _PORTRAIT_PNGS:
                assert (flat / "Portraits" / "Flat" / name).is_file(), name
                assert not (flat / name).exists()
            assert (flat / "meta.ini").is_file()
            assert (staging / "Pack" / "Portraits" / "A" / "Small.png").is_file()
            assert (staging / "Pack" / "Portraits" / "B" / "medium.png").is_file()
            assert not (staging / "Pack" / "A").exists()
            assert (staging / "Wrapped" / "Portraits" / "C" / "Small.png").is_file()
            assert (staging / "Deep" / "Portraits" / "D" / "Small.png").is_file()
            assert not (staging / "Deep" / "My Pack").exists()
            assert (umm / "Umm" / "Art" / "Small.png").is_file()
            assert not (umm / "Portraits").exists()
            assert not (staging / "Tmpl" / "Portraits").exists()
            assert not game.prepare_mod_staging(staging, lambda _m: None)
    print("✓ portrait staging")


def test_portrait_name_clash_left_in_place() -> None:
    _km, wotr, _rt = _games()
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp)
        mod = staging / "Clash"
        _portrait(mod / "Portraits" / "X")
        _portrait(mod / "Extra" / "X", ["Small.png"])
        wotr.prepare_mod_staging(staging, lambda _m: None)
        assert (mod / "Extra" / "X" / "Small.png").is_file()
        assert (mod / "Portraits" / "X" / "Fulllength.png").is_file()
    print("✓ portrait name clash left in place")


# -- Unity Mod Manager installer ----------------------------------------------

_UMM_CONFIG = """<?xml version="1.0" encoding="utf-8"?>
<Config xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
\t<Repository>https://example.invalid/Repository.json</Repository>
\t<GameInfo Name="Pathfinder: Kingmaker">
\t\t<Folder>Pathfinder Kingmaker</Folder>
\t\t<ModsDirectory>Mods</ModsDirectory>
\t\t<ModInfo>Info.json</ModInfo>
\t\t<GameExe>Kingmaker.exe</GameExe>
\t\t<EntryPoint>[UnityEngine.UIModule.dll]UnityEngine.Canvas.cctor:Before</EntryPoint>
\t\t<MinimalManagerVersion>0.12.0</MinimalManagerVersion>
\t</GameInfo>
\t<GameInfo Name="Pathfinder: Wrath of the Righteous">
\t\t<Folder>Pathfinder Second Adventure</Folder>
\t\t<ModsDirectory>Mods</ModsDirectory>
\t\t<ModInfo>Info.json</ModInfo>
\t\t<GameExe>Wrath.exe</GameExe>
\t\t<EntryPoint>[UnityEngine.UIModule.dll]UnityEngine.Canvas.cctor:Before</EntryPoint>
\t\t<StartingPoint>[Assembly-CSharp.dll]Kingmaker.GameStarter.Awake:Before &amp; more</StartingPoint>
\t\t<MinimalManagerVersion>0.22.15</MinimalManagerVersion>
\t</GameInfo>
</Config>
"""


def _fake_umm(folder: Path, config: str = _UMM_CONFIG) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("0Harmony.dll", "dnlib.dll", "System.Xml.dll", "UnityModManager.dll",
                 "UnityModManager.xml", "UnityModManager.exe", "Console.exe",
                 "winhttp_x64.dll", "winhttp_x86.dll", "readme.txt"):
        (folder / name).write_bytes(name.encode())
    for rel in ("Harmony/1.2/0Harmony12.dll", "Harmony/1.2/0Harmony-1.2.dll",
                "Harmony/2.2/0Harmony.dll"):
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_bytes(rel.encode())
    (folder / "UnityModManagerConfig.xml").write_text(config, encoding="utf-8")
    return folder


def _fake_game(root: Path, exe: str, *, machine: int = 0x8664,
               system_xml: bool = True) -> Path:
    import struct
    root.mkdir(parents=True, exist_ok=True)
    header = bytearray(0x80)
    header[:2] = b"MZ"
    header[0x3C:0x40] = struct.pack("<I", 0x40)
    header[0x40:0x46] = b"PE\0\0" + struct.pack("<H", machine)
    (root / exe).write_bytes(bytes(header))
    managed = root / f"{Path(exe).stem}_Data" / "Managed"
    managed.mkdir(parents=True)
    if system_xml:
        (managed / "System.Xml.dll").write_bytes(b"game")
    return root


def test_umm_payload_matches_doorstop_install() -> None:
    import xml.etree.ElementTree as ET
    from Games.Owlcat.umm_install import build_umm_payload
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = _fake_umm(root / "UnityModManagerInstaller")
        game = _fake_game(root / "game", "Wrath.exe")
        out = root / "payload"
        files = build_umm_payload(source, game, "Wrath.exe", out)
        manager = "Wrath_Data/Managed/UnityModManager"
        assert sorted(p.as_posix() for p in files) == sorted([
            "winhttp.dll", "doorstop_config.ini",
            *(f"{manager}/{n}" for n in ("0Harmony.dll", "dnlib.dll", "UnityModManager.dll",
                                         "UnityModManager.xml", "Config.xml"))]), files
        assert (out / "winhttp.dll").read_bytes() == b"winhttp_x64.dll"
        assert (out / "doorstop_config.ini").read_bytes() == (
            b"[General]\r\nenabled = true\r\n"
            b"target_assembly = Wrath_Data\\Managed\\UnityModManager\\UnityModManager.dll")
        config = ET.parse(out / manager / "Config.xml").getroot()
        assert config.tag == "Config"
        assert config.get("Name") == "Pathfinder: Wrath of the Righteous"
        assert config.findtext("GameExe") == "Wrath.exe"
        assert config.findtext("Folder") == "Pathfinder Second Adventure"
        assert config.findtext("StartingPoint").endswith("& more")
        assert config.find("Repository") is None
        assert (out / manager / "UnityModManager.dll").read_bytes() == b"UnityModManager.dll"
    print("✓ UMM payload matches the Doorstop install")


def test_umm_payload_variants() -> None:
    from Games.Owlcat.umm_install import build_umm_payload
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = _fake_umm(root / "UnityModManagerInstaller")
        # Game without System.Xml.dll gets UMM's copy.
        game = _fake_game(root / "nosysxml", "Wrath.exe", system_xml=False)
        files = build_umm_payload(source, game, "Wrath.exe", root / "p1")
        assert Path("Wrath_Data/Managed/UnityModManager/System.Xml.dll") in files
        # Kingmaker supports UMM < 0.22, so it also gets the Harmony 1.2 shims.
        game = _fake_game(root / "km", "Kingmaker.exe")
        files = {p.as_posix() for p in build_umm_payload(source, game, "Kingmaker.exe", root / "p2")}
        assert {"Kingmaker_Data/Managed/UnityModManager/0Harmony12.dll",
                "Kingmaker_Data/Managed/UnityModManager/0Harmony-1.2.dll"} <= files
        assert (root / "p2" / "Kingmaker_Data/Managed/UnityModManager/0Harmony.dll"
                ).read_bytes() == b"0Harmony.dll"
        # A 32-bit exe gets the x86 proxy.
        game = _fake_game(root / "x86", "Wrath.exe", machine=0x014C)
        build_umm_payload(source, game, "Wrath.exe", root / "p3")
        assert (root / "p3" / "winhttp.dll").read_bytes() == b"winhttp_x86.dll"
        # The data folder keeps its on-disk spelling.
        game = _fake_game(root / "case", "Wrath.exe")
        (game / "Wrath_Data").rename(game / "wrath_data")
        files = build_umm_payload(source, game, "Wrath.exe", root / "p4")
        assert Path("wrath_data/Managed/UnityModManager/Config.xml") in files
        assert b"target_assembly = wrath_data\\Managed" in (
            root / "p4" / "doorstop_config.ini").read_bytes()
    print("✓ UMM payload variants")


def test_umm_payload_errors() -> None:
    from Games.Owlcat.umm_install import build_umm_payload
    from Utils.wizards.payload import PayloadInstallError
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = _fake_umm(root / "umm", _UMM_CONFIG.replace("Wrath.exe", "Other.exe"))
        game = _fake_game(root / "game", "Wrath.exe")
        for case in ("no game entry", "no proxy", "no data folder"):
            if case == "no proxy":
                source = _fake_umm(root / "umm2")
                (source / "winhttp_x64.dll").unlink()
            if case == "no data folder":
                source = _fake_umm(root / "umm3")
                game = root / "empty"
                game.mkdir()
            try:
                build_umm_payload(source, game, "Wrath.exe", root / case.replace(" ", "_"))
            except PayloadInstallError:
                continue
            raise AssertionError(case)
    print("✓ UMM payload errors")


def test_umm_prepare_from_archive() -> None:
    import zipfile
    from Games.Owlcat.umm_install import prepare_umm_payload
    _km, wotr, _rt = _games()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = _fake_umm(root / "src" / "UnityModManagerInstaller")
        archive = root / "UnityModManager 21 0.33.4.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            for path in sorted(source.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(source.parent).as_posix())
        wotr._game_path = _fake_game(root / "game", "Wrath.exe")
        with prepare_umm_payload(wotr, archive) as payload:
            assert payload.archive == archive
            names = {p.as_posix() for p in payload.files}
            assert "winhttp.dll" in names and "doorstop_config.ini" in names
            assert all((payload.root / p).is_file() for p in payload.files)
            assert not any("Console.exe" in n or "readme" in n for n in names)
    print("✓ UMM payload from archive")


def test_umm_wizard_tool() -> None:
    import wizards_qt
    km, wotr, rt = _games()
    for game in (km, wotr):
        tools = {tool.id: tool for tool in game.wizard_tools}
        assert "install_reshade" in tools
        tool = tools["install_umm"]
        assert tool.dialog_class_path in wizards_qt.REGISTRY, tool.dialog_class_path
    assert "install_umm" not in {tool.id for tool in rt.wizard_tools}
    print("✓ UMM wizard tool")


def test_umm_missing_warning_points_to_wizard() -> None:
    _km, wotr, _rt = _games()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _point(wotr, root)
        staging = _profile(wotr, root, ["+UmmMod"])
        umm = staging / "UmmMod" / "Umm"
        umm.mkdir(parents=True)
        (umm / UMM_MANIFEST).write_text("{}")
        wotr.pop_deploy_warnings()
        wotr.post_deploy(lambda _m: None)
        warnings = wotr.pop_deploy_warnings()
        assert any("Install Unity Mod Manager" in w and "Wizard" in w for w in warnings), warnings
    print("✓ missing-UMM warning points to the wizard")


if __name__ == "__main__":
    test_locallow_rel_variants()
    test_classify()
    test_template_id()
    test_sync_adds_and_removes_managed()
    test_sync_keeps_unmanaged_order()
    test_sync_user_owned_survives_disable()
    test_apply_preserves_other_keys()
    test_apply_invalid_json_untouched()
    test_apply_creates_missing_file()
    test_identity()
    test_data_paths()
    test_routing_rules()
    test_prepare_staging_restructures()
    test_rt_excludes_bundled_umm()
    test_umm_detection()
    test_discovered()
    test_post_deploy_syncs_enabled_templates()
    test_post_deploy_without_prefix()
    test_restore_whitelist_protects_umm()
    test_no_prefix_keeps_templates_out_of_mods()
    test_sync_reclaims_user_removed_entry()
    test_flat_umm_wraps_into_id_folder()
    test_case_insensitive_folders_and_manifests()
    test_apply_does_not_create_empty_settings()
    test_reserved_ids_fall_back_to_mod_name()
    test_portrait_staging()
    test_portrait_name_clash_left_in_place()
    test_umm_payload_matches_doorstop_install()
    test_umm_payload_variants()
    test_umm_payload_errors()
    test_umm_prepare_from_archive()
    test_umm_wizard_tool()
    test_umm_missing_warning_points_to_wizard()
    print("All Owlcat checks passed.")
