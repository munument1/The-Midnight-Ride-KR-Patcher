"""Audit UFO4P/Zimonja and PRP raw data in the actual distribution ZIP."""
import argparse
from collections import Counter
import json
from pathlib import Path
import struct
import sys
import tempfile
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import tmrkr
from tmrkr_plugin_safety import offset_tables
from verify_release_output import TEXT_FIELDS, headers, pairs, protected_zimonja, text

TARGETS = ('unofficial fallout 4 patch.esp', 'ppf.esm', 'prp.esp')


def records(path):
    offset_tables(path)  # Validate record and nested group boundaries first.
    data = path.read_bytes()
    result, pos = {}, 0
    while pos < len(data):
        sig, size, flags, form = struct.unpack_from('<4sIII', data, pos)
        if sig == b'GRUP':
            pos += 24
            continue
        raw = data[pos:pos + 24 + size]
        body = raw[24:]
        if flags & 0x40000:
            expected = struct.unpack_from('<I', body)[0]
            body = zlib.decompress(body[4:])
            if len(body) != expected:
                raise ValueError('Decompressed size mismatch')
        key = sig.decode(), f'{form:08X}'
        if key in result:
            raise ValueError(f'Duplicate record: {key}')
        result[key] = body, raw
        pos += len(raw)
    return result


def fields(body):
    """Keep XXXX markers and field headers, so untouched fields compare bytewise."""
    pos, result = 0, []
    while pos < len(body):
        start = pos
        sig, size = struct.unpack_from('<4sH', body, pos)
        pos += 6
        if sig == b'XXXX':
            if size != 4:
                raise ValueError('Invalid XXXX')
            size = struct.unpack_from('<I', body, pos)[0]
            sig = body[pos + 4:pos + 8]
            pos += 10
        if pos + size > len(body):
            raise ValueError('Invalid field boundary')
        value = body[pos:pos + size]
        pos += size
        result.append((sig, value, body[start:pos]))
    return result


def audit(mo2, profile, package):
    installation = tmrkr.Installation(mo2, profile)
    results = []
    with zipfile.ZipFile(package) as archive, tempfile.TemporaryDirectory(prefix='tmrkr-audit-') as tmp:
        catalogs = [n for n in archive.namelist() if n.endswith('/TranslationData/catalog.json')]
        if len(catalogs) != 1:
            raise ValueError('Expected one release catalog')
        prefix = catalogs[0].removesuffix('catalog.json')
        catalog = json.loads(archive.read(catalogs[0]).decode('utf-8-sig'))
        entries = {e['name'].casefold(): e for e in catalog['plugins']}
        bank = pairs(json.loads(archive.read(prefix + 'fallback/fallout4-base-dlc-fallback.json').decode('utf-8-sig')))
        for name in TARGETS:
            source = installation.source(name)
            entry = entries[name]
            target = Path(tmp) / name
            target.write_bytes(archive.read(prefix + entry['payload']))
            if (tmrkr.sha256(source) != entry['source_sha256']
                    or tmrkr.sha256(target) != entry['payload_sha256']):
                raise ValueError(f'Source or payload hash mismatch: {name}')
            original, translated = records(source), records(target)
            if list(original) != list(translated) or headers(source) != headers(target):
                raise ValueError(f'Record or header mismatch: {name}')
            approved = bank.copy()
            if entry.get('direct_mapping'):
                approved.update(pairs(json.loads(archive.read(prefix + entry['direct_mapping']).decode('utf-8-sig'))))
            changed, removed, untouched = Counter(), Counter(), 0
            for key, (body, raw) in original.items():
                new_body, new_raw = translated[key]
                if body == new_body:
                    if raw != new_raw:
                        raise ValueError(f'Untouched record bytes changed: {name} {key}')
                    untouched += 1
                    continue
                before = []
                for f in fields(body):
                    if key[0] == 'WRLD' and f[0] in {b'OFST', b'CLSZ'}:
                        removed[f[0].decode()] += 1
                    else:
                        before.append(f)
                after = fields(new_body)
                if len(before) != len(after):
                    raise ValueError(f'Field count mismatch: {name} {key}')
                for (sig, a, a_raw), (other, b, b_raw) in zip(before, after):
                    if sig != other:
                        raise ValueError(f'Field order mismatch: {name} {key}')
                    if a_raw == b_raw:
                        continue
                    if sig not in TEXT_FIELDS or not a.endswith(b'\0') or not b.endswith(b'\0'):
                        raise ValueError(f'Non-text bytes changed: {name} {key} {sig}')
                    new_text = b[:-1].decode('utf-8').replace('\r\n', '\n')
                    if text(a) != new_text and (text(a), new_text) not in approved:
                        raise ValueError(f'Unapproved translation: {name} {key} {sig}')
                    changed[sig.decode()] += 1
            zimonja = []
            bodies = {k: v[0] for k, v in original.items()}
            for key in protected_zimonja(bodies, name):
                if original[key][1] != translated[key][1]:
                    raise ValueError(f'Zimonja raw record changed: {name} {key}')
                fs = fields(original[key][0])
                zimonja.append({'record': key[0], 'form_id': key[1],
                    'editor_id': next((text(v) for s, v, _ in fs if s == b'EDID'), ''),
                    'names': [text(v) for s, v, _ in fs if s == b'FULL'],
                    'raw_record_identical': True})
            if offset_tables(target):
                raise ValueError(f'Remaining world index: {name}')
            results.append({'plugin': name, 'source_sha256': tmrkr.sha256(source),
                'payload_sha256': tmrkr.sha256(target), 'records_including_TES4': len(original),
                'byte_identical_records': untouched, 'changed_text_fields': dict(changed),
                'world_indexes_removed': dict(removed), 'world_indexes_remaining': 0,
                'record_and_group_headers_preserved_except_size': True,
                'nontext_raw_fields_and_XXXX_preserved': True, 'protected_zimonja': zimonja})
    return {'schema_version': 1, 'package': package.name, 'package_sha256': tmrkr.sha256(package),
            'status': 'passed_file_audit', 'in_game_validation': 'not_performed', 'plugins': results}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mo2-root', type=Path, required=True)
    ap.add_argument('--profile', default='The Midnight Ride Extended')
    ap.add_argument('--package-zip', type=Path, required=True)
    ap.add_argument('--report', type=Path, required=True)
    args = ap.parse_args()
    result = audit(args.mo2_root, args.profile, args.package_zip)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': result['status'], 'plugins': len(result['plugins']),
                      'report': str(args.report)}, ensure_ascii=True))
