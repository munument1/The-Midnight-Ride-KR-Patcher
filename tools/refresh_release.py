"""Refresh a released catalog against an installed MO2 profile without changing it.

The previous release supplies the base Korean resources, validated backend and
translation banks. New source-controlled dictionaries are merged before building
an Output; changed payloads are promoted only after the normal safety checks.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import tmrkr
from tmrkr_output import build_output, _provider_target, _contained
from tmrkr_plugin_safety import PLUGIN_POLICY_VERSION, offset_tables


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def refresh(previous: Path, mo2: Path, profile: str, package: Path, output: Path, resume=False, backend=None):
    if not resume and (package.exists() or output.exists()):
        raise FileExistsError("Use new package and Output directories")
    if not resume:
        shutil.copytree(previous, package)
    data = package / "TranslationData"
    if backend:
        if resume:
            raise ValueError("A new backend requires a fresh Output")
        shutil.copy2(backend, data / "Backend/TmrPluginTranslator.exe")
    catalog = read(data / "catalog.json")
    catalog["version"] = tmrkr.VERSION
    catalog["profile_built_from"] = profile
    for path in (ROOT / "TranslationData/updates/direct-maps").glob("*.json"):
        relative = f"direct-maps/{path.name}"
        document = read(path)
        target = data / relative
        changed = not target.is_file() or read(target) != document
        write(target, document)
        for entry in catalog["plugins"]:
            if entry["name"].casefold() == document["target"].casefold():
                entry["direct_mapping"] = relative
                if changed:
                    entry.pop("plugin_policy_version", None)
    updates = read(ROOT / "TranslationData/updates/interface.json")
    for name, additions in updates.items():
        relative = f"interface-maps/{name}"
        target = data / relative
        mapping = read(target) if target.is_file() else {}
        mapping.update(additions)
        write(target, mapping)
        path = f"Interface/Translations/{Path(name).stem}.txt"
        if not any(s["path"].casefold() == path.casefold() for s in catalog["interface"]):
            catalog["interface"].append({"path": path, "mapping": relative})
    write(data / "catalog.json", catalog)
    if resume:
        if any(e.get("payload") and not e.get("plugin_policy_version") for e in catalog["plugins"]):
            raise ValueError("A direct dictionary changed; generate a fresh Output")
        report = read(output / "TMR-Korean-Patcher-report.json")
        installation = tmrkr.Installation(mo2, profile)
        if report["profile"] != profile or Path(report["mo2_root"]).resolve() != mo2.resolve():
            raise ValueError("Output does not belong to the requested installation/profile")
        for row in report["plugins"]:
            if tmrkr.sha256(installation.source(row["plugin"])) != row["source_sha256"]:
                raise ValueError(f"Source changed since Output was built: {row['plugin']}")
    else:
        report = build_output(mo2, package / "FO4_AE_1.11.191.Kor", data, output, profile)
    old = {e["name"].casefold(): e for e in catalog["plugins"]}
    entries = []
    for row in report["plugins"]:
        name = row["plugin"]
        status = row["status"]
        if status == "skipped_localized_strings":
            # Keep the existing, documented exclusion visible at runtime.
            entries.append({"name": name, "source_sha256": row["source_sha256"],
                            "baseline_status": status, "changed": 0})
            continue
        if status.startswith("skipped_") or status == "source_missing":
            raise RuntimeError(f"Resolve skipped/missing plugin before release: {name}: {row}")
        entry = dict(old.get(name.casefold(), {}))
        for key in ("payload", "payload_sha256", "sidecar_dir"):
            entry.pop(key, None)
        entry.update(name=name, source_sha256=row["source_sha256"],
                     plugin_policy_version=PLUGIN_POLICY_VERSION,
                     baseline_status="translated" if row["changed"] else "no_changes",
                     changed=row["changed"])
        if row["changed"]:
            detail = row.get("detail", {})
            if status != "exact_payload" and not detail.get("utf8_text_verified"):
                raise ValueError(f"Unverified UTF-8 output: {name}")
            if status != "exact_payload" and (detail.get("final_binary_verified") is not True
                    or detail.get("world_index_policy") != "strip_wrld_ofst_clsz_v1"):
                raise ValueError(f"Unverified final binary: {name}")
            payload = _provider_target(output, {"provider": row["provider"], "path": row["relative_path"]})
            if not payload.is_file() or offset_tables(payload):
                raise ValueError(f"Missing or unsafe payload: {name}")
            relative = f"exact-plugins/{name}"
            target = _contained(data, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(payload, target)
            entry.update(payload=relative, payload_sha256=tmrkr.sha256(target),
                         payload_encoding="utf-8", text_roundtrip_verified=True,
                         final_binary_verified=True, world_index_policy="strip_wrld_ofst_clsz_v1")
        entries.append(entry)
    catalog["plugins"] = entries
    # Retain dictionaries for removed optional mods, but remove stale exact files.
    used = {e["payload"].casefold() for e in entries if "payload" in e}
    for path in (data / "exact-plugins").iterdir():
        if path.is_file() and path.relative_to(data).as_posix().casefold() not in used:
            path.unlink()
    write(data / "catalog.json", catalog)
    write(package / "BUILD-INFO.json", {
        "version": tmrkr.VERSION,
        "profile": profile,
        "plugin_policy_version": PLUGIN_POLICY_VERSION,
        "plugins": [{"name": e["name"], "source_sha256": e["source_sha256"],
                     "changed": e["changed"]} for e in entries],
        "interface": [{k: r[k] for k in ("path", "matched", "missing")}
                      for r in report["interface"]],
    })
    print(json.dumps({"plugins": len(entries), "payloads": len(used),
                      "interface": report["interface"], "warnings": report["warnings"]}, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--previous", type=Path, required=True)
    ap.add_argument("--mo2-root", type=Path, required=True)
    ap.add_argument("--profile", default="The Midnight Ride Extended")
    ap.add_argument("--package", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--resume", action="store_true", help="Promote an existing Output after verifying source hashes")
    ap.add_argument("--backend-exe", type=Path, help="Use a newly published self-contained backend")
    args = ap.parse_args()
    refresh(args.previous, args.mo2_root, args.profile, args.package, args.output, args.resume, args.backend_exe)
