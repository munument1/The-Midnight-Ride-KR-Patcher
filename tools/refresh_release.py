"""Refresh a released catalog against an installed MO2 profile without changing it.

The previous release supplies the base Korean resources, validated backend and
translation banks. New source-controlled dictionaries are merged before building
an Output. Only dictionaries and runtime resources are packaged; translated
plugins remain in the local validation Output.
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
from tmrkr_output import build_output
from tmrkr_plugin_safety import PLUGIN_POLICY_VERSION


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def release_copy_ignore(directory, names):
    return [name for name in names if name.casefold() in {"exact-plugins", "exact-sidecars"}
            or Path(name).suffix.casefold() in tmrkr.PLUGIN_SUFFIXES]


def refresh(previous: Path, mo2: Path, profile: str, package: Path, output: Path, resume=False, backend=None):
    if not resume and (package.exists() or output.exists()):
        raise FileExistsError("Use new package and Output directories")
    if not resume:
        # Import historical resources without carrying forward whole plugins.
        shutil.copytree(previous, package, ignore=release_copy_ignore)
    data = package / "TranslationData"
    if backend:
        if resume:
            raise ValueError("A new backend requires a fresh Output")
        shutil.copy2(backend, data / "Backend/TmrPluginTranslator.exe")
    catalog = read(data / "catalog.json")
    catalog["schema_version"] = 2
    catalog["plugin_generation"] = "installed_source_only"
    for entry in catalog["plugins"]:
        for key in ("payload", "payload_sha256", "payload_encoding", "sidecar_dir",
                    "text_roundtrip_verified", "final_binary_verified", "world_index_policy"):
            entry.pop(key, None)
    catalog["version"] = tmrkr.VERSION
    catalog["profile_built_from"] = profile
    dictionaries_changed = False
    for path in (ROOT / "TranslationData/updates/direct-maps").glob("*.json"):
        relative = f"direct-maps/{path.name}"
        document = read(path)
        target = data / relative
        changed = not target.is_file() or read(target) != document
        dictionaries_changed |= changed
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
        if dictionaries_changed:
            raise ValueError("A dictionary changed; generate a fresh Output")
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
        entry.update(name=name, source_sha256=row["source_sha256"],
                     plugin_policy_version=PLUGIN_POLICY_VERSION,
                     baseline_status="translated" if row["changed"] else "no_changes",
                     changed=row["changed"])
        if row["changed"]:
            detail = row.get("detail", {})
            if not detail.get("utf8_text_verified"):
                raise ValueError(f"Unverified UTF-8 output: {name}")
            if (detail.get("final_binary_verified") is not True
                    or detail.get("world_index_policy") != "strip_wrld_ofst_clsz_v1"):
                raise ValueError(f"Unverified final binary: {name}")
        entries.append(entry)
    catalog["plugins"] = entries
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
    print(json.dumps({"plugins": len(entries), "plugin_generation": "installed_source_only",
                      "interface": report["interface"], "warnings": report["warnings"]}, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--previous", type=Path, required=True)
    ap.add_argument("--mo2-root", type=Path, required=True)
    ap.add_argument("--profile", default="The Midnight Ride Extended")
    ap.add_argument("--package", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--resume", action="store_true", help="Record an existing validated Output after verifying source hashes")
    ap.add_argument("--backend-exe", type=Path, help="Use a newly published self-contained backend")
    args = ap.parse_args()
    refresh(args.previous, args.mo2_root, args.profile, args.package, args.output, args.resume, args.backend_exe)
