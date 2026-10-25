"""Build the portable public toolbox from verified source, GLBs and Python files."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import stat
import struct
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from core.branding import TOOL, VERSION

INVENTORY_FIELDS = ('id', 'name', 'group', 'internal_name', 'section', 'status', 'glb',
                    'vertices', 'triangles', 'packed_images', 'missing_textures', 'warnings')
MASTER_FIELDS = ('internal_name', 'dimensions_in_blender', 'total_triangles',
                 'total_vertices', 'status', 'warnings', 'missing_textures')
PRIVATE_PATH = re.compile(r'(?i)(?:[a-z]:[\\/]|file:/|\\\\[^\\]+\\|/(?:home|Users|tmp)/)')
PRIVATE_KEY = re.compile(r'(?i)^(?:uid|user[_-]?id|account[_-]?id|machine[_-]?id|thread[_-]?id|chat[_-]?id|api[_-]?key|access[_-]?token|authorization|email)$')


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def relative_path(value):
    """Accept one unambiguous archive-relative POSIX path."""
    if not isinstance(value, str) or not value or '\\' in value or ':' in value or '\0' in value:
        raise ValueError(f'Invalid relative path: {value!r}')
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ('', '.', '..') for part in value.split('/')):
        raise ValueError(f'Unsafe relative path: {value!r}')
    return path


def contained_file(root, relative):
    path = root.joinpath(*relative.parts)
    path.resolve().relative_to(root.resolve())
    if not path.is_file():
        raise FileNotFoundError(f'Missing package file: {relative.as_posix()}')
    return path


def public_metadata(value, where='$'):
    """Reject local metadata accidentally surviving the explicit field projection."""
    if isinstance(value, dict):
        for key, item in value.items():
            if PRIVATE_KEY.fullmatch(key):
                raise ValueError(f'Private metadata key at {where}.{key}')
            public_metadata(item, where + '.' + key)
    elif isinstance(value, list):
        for item in value:
            public_metadata(item, where + '[]')
    elif isinstance(value, str) and PRIVATE_PATH.search(value):
        raise ValueError(f'Local path found in public metadata at {where}')
    return value


def read_indexes(library):
    inventory = json.loads((library / 'inventory.json').read_text('utf-8-sig'))
    master = json.loads((library / 'master-verification.json').read_text('utf-8-sig'))
    if not isinstance(inventory, list) or not isinstance(master.get('assets'), list):
        raise ValueError('Expected an inventory array and a master object with an assets array')
    clean_inventory = [{key: row[key] for key in INVENTORY_FIELDS if key in row} for row in inventory]
    clean_master = {'assets': [{key: row[key] for key in MASTER_FIELDS if key in row} for row in master['assets']]}
    for key in ('processed', 'requested', 'counts'):
        if key in master:
            clean_master[key] = master[key]
    public_metadata(clean_inventory)
    public_metadata(clean_master)
    models = {}
    referenced_rows = 0
    for row in inventory:
        value = row.get('glb')
        if not value:
            continue
        relative = relative_path(value)
        if relative.parts[0] != 'assets' or relative.suffix.lower() != '.glb':
            raise ValueError(f'Expected an assets/**/*.glb path: {value}')
        referenced_rows += 1
        if value not in models:
            models[value] = contained_file(library, relative)
    if not models:
        raise ValueError('The inventory contains no usable GLB models')
    fallbacks = []
    for row in master['assets']:
        if row.get('static_fallback'):
            fallbacks.append({'id': row.get('id'), 'internal_name': row.get('internal_name'),
                              'static_model': True, 'skin_exported': False,
                              'reason': 'Native prefab reexported without skin data after Blender FBX armature_setup import errors.'})
    stats = {'inventory_rows': len(inventory), 'model_files': len(models),
             'nonempty_glb_rows': referenced_rows, 'shared_model_alias_rows': referenced_rows - len(models),
             'rows_without_glb': len(inventory) - referenced_rows,
             'material_warning_records': sum(row.get('status') == 'warning' for row in master['assets']),
             'static_compatibility_models': fallbacks}
    public_metadata(stats)
    return clean_inventory, clean_master, models, stats


def inspect_glb(path):
    """Inspect the JSON chunk and bounds without decoding or rewriting model bytes."""
    size = path.stat().st_size
    with path.open('rb') as stream:
        header = stream.read(12)
        if len(header) != 12:
            raise ValueError('Truncated GLB header')
        magic, version, declared = struct.unpack('<III', header)
        if (magic, version, declared) != (0x46546C67, 2, size):
            raise ValueError('Invalid GLB header/version/length')
        document, bins = None, []
        while stream.tell() < size:
            chunk = stream.read(8)
            if len(chunk) != 8:
                raise ValueError('Truncated GLB chunk header')
            length, kind = struct.unpack('<II', chunk)
            if stream.tell() + length > size:
                raise ValueError('GLB chunk exceeds the file')
            if kind == 0x4E4F534A:
                if document is not None:
                    raise ValueError('Multiple GLB JSON chunks')
                document = json.loads(stream.read(length).decode('utf-8').rstrip('\0 \r\n\t'))
            else:
                if kind == 0x004E4942:
                    bins.append(length)
                stream.seek(length, 1)
    if document is None:
        raise ValueError('Missing GLB JSON chunk')
    public_metadata(document, '$glb')
    buffers = document.get('buffers', [])
    views = document.get('bufferViews', [])
    for index, buffer in enumerate(buffers):
        uri = buffer.get('uri')
        if uri is None:
            if index != 0 or not bins or buffer.get('byteLength', 0) > bins[0]:
                raise ValueError('A GLB buffer has no matching BIN chunk')
        elif not isinstance(uri, str) or not uri.startswith('data:'):
            raise ValueError('External buffer URI is not allowed in the portable GLB package')
    for view in views:
        index = view.get('buffer', -1)
        if not isinstance(index, int) or not 0 <= index < len(buffers):
            raise ValueError('Invalid GLB bufferView buffer index')
        if view.get('byteOffset', 0) + view.get('byteLength', 0) > buffers[index].get('byteLength', 0):
            raise ValueError('GLB bufferView exceeds its buffer')
    for image in document.get('images', []):
        if 'bufferView' in image:
            index = image['bufferView']
            if not isinstance(index, int) or not 0 <= index < len(views):
                raise ValueError('Invalid GLB image bufferView')
        elif not isinstance(image.get('uri'), str) or not image['uri'].startswith('data:'):
            raise ValueError('External or missing image URI is not allowed in the portable GLB package')
    return {'bytes': size, 'embedded_images': len(document.get('images', []))}


def verify_source(archive):
    """Validate every source archive member against SOURCE_MANIFEST.json."""
    prefix = TOOL + '/'
    manifest_name = prefix + 'SOURCE_MANIFEST.json'
    members = {}
    with zipfile.ZipFile(archive) as source:
        entries = [info for info in source.infolist() if not info.is_dir()]
        if len({info.filename for info in entries}) != len(entries):
            raise ValueError('Duplicate source archive member names')
        names = {info.filename for info in entries}
        manifest_data = source.read(manifest_name)
        manifest = json.loads(manifest_data.decode('utf-8-sig'))
        if not isinstance(manifest, list):
            raise ValueError('SOURCE_MANIFEST.json must be an array')
        expected = {manifest_name}
        for row in manifest:
            relative = relative_path(row['path']).as_posix()
            name = prefix + relative
            if name in expected:
                raise ValueError('Duplicate source manifest path')
            expected.add(name)
            info = source.getinfo(name)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError('Source archive symlinks are not supported')
            if relative.split('/')[0] in ('library', 'runtime', 'projects', 'logs') or relative.endswith('.local.json'):
                raise ValueError('Local/runtime/model files are not permitted in the source archive')
            data = source.read(info)
            if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
                raise ValueError(f'Source manifest verification failed: {relative}')
            members[name] = data
        if names != expected:
            raise ValueError('Source archive has unlisted or missing members')
        members[manifest_name] = manifest_data
    return members


def runtime_files(runtime):
    if not (runtime / 'python.exe').is_file():
        raise ValueError('The Python runtime directory must contain python.exe')
    result = []
    for path in sorted(runtime.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(runtime)
        if '__pycache__' in relative.parts:
            continue
        if path.is_symlink():
            raise ValueError('Runtime symlinks are not supported')
        contained_file(runtime, relative_path(relative.as_posix()))
        result.append((relative.as_posix(), path))
    licenses = [relative for relative, _ in result if PurePosixPath(relative).name.lower().startswith('license')]
    if not licenses:
        raise ValueError('The official runtime LICENSE file is missing')
    return result, licenses


def source_notes(stats):
    return f'''# 素材来源与转换说明

本包提供 {stats['model_files']} 个独立 GLB。游戏素材来自原神 7.1.0 的千星相关本机资源，原游戏模型和贴图的权利归 HoYoverse 及相关权利人。AnimeStudio 用于读取资源，Blender 用于转换 GLB 与通用材质。GLB 实际引用的几何缓冲和图像均内嵌，未重复附带 FBX、.blend 或原始纹理目录。

中文名称、编号与尺寸目录来自 [8itlab/genshin-miliastra-mcp 的 asset-catalog.json](https://github.com/8itlab/genshin-miliastra-mcp/blob/main/src/scene/asset-catalog.json)。该数据文件声明依据 hang-ZYM/qianxing-format-docs 的 docs/08 与 data/prefab_sizes_full.json，目录数据为 CC BY 4.0。地块描述及 extra/terrain/creature/struct 等编号属于本地目录说明，内部资源名称保留。

本批记录有 {stats['material_warning_records']} 条材质近似等警告；原游戏专用着色器并未完整复现。原始 FBX/.blend 中未连入通用材质的 normal/mask 图像不属于本 GLB 包的实际引用图像，inventory 中 packed_images 仍是原 .blend 打包统计。{len(stats['static_compatibility_models'])} 个模型因 Blender 原 FBX 骨架导入问题，以同一原生 prefab 关闭蒙皮后重新导出，保留静态几何与贴图，不包含骨架及动作；内部名与原因列在 asset-pack.json。

工具代码按源码包 LICENSE 中的 GPL 授权提供。代码授权及 CC BY 4.0 目录数据授权没有重新授权游戏模型和贴图；本说明记录来源和转换事实。

[AnimeStudio](https://github.com/Escartem/AnimeStudio) · [Blender](https://www.blender.org/)
'''


def zip_info(name):
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info._compresslevel = 6
    return info


def build(args):
    library, runtime = args.library.resolve(), args.python_runtime.resolve()
    source_archive = (args.source_archive or ROOT.parent / f'{TOOL}-{VERSION}-source.zip').resolve()
    output = (args.output or source_archive.with_name(f'{TOOL}-{VERSION}-full.zip')).resolve()
    if output == source_archive:
        raise ValueError('The full archive cannot overwrite the source archive')
    source_members = verify_source(source_archive)
    inventory, master, models, stats = read_indexes(library)
    runtimes, licenses = runtime_files(runtime)
    image_count = 0
    glb_bytes = 0
    for index, (relative, path) in enumerate(models.items(), 1):
        try:
            meta = inspect_glb(path)
        except Exception as error:
            raise ValueError(f'Invalid portable model {relative}: {error}') from error
        image_count += meta['embedded_images']
        glb_bytes += meta['bytes']
        if index % 100 == 0:
            print(f'CHECK {index}/{len(models)}', flush=True)
    pack = {'tool': TOOL, 'version': VERSION, **stats, 'embedded_images': image_count,
            'external_dependencies': 0, 'glb_bytes': glb_bytes,
            'source_archive_sha256': sha256_file(source_archive),
            'python_runtime': {'file_count': len(runtimes), 'bytes': sum(path.stat().st_size for _, path in runtimes),
                               'license_files': licenses}}
    public_metadata(pack)
    if args.dry_run:
        return {'dry_run': True, 'output': str(output), **pack}
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.name + f'.{os.getpid()}.partial')
    manifest = []
    try:
        with zipfile.ZipFile(partial, 'w', zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as target:
            for name, data in source_members.items():
                target.writestr(zip_info(name), data)
            for relative, path in runtimes:
                target.write(path, f'{TOOL}/runtime/python/{relative}')
            for index, (relative, path) in enumerate(models.items(), 1):
                digest, count = hashlib.sha256(), 0
                with path.open('rb') as stream, target.open(zip_info(f'{TOOL}/library/{relative}'), 'w', force_zip64=True) as destination:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(chunk)
                        count += len(chunk)
                        destination.write(chunk)
                if count != path.stat().st_size:
                    raise ValueError(f'Model changed during packaging: {relative}')
                manifest.append({'path': relative, 'bytes': count, 'sha256': digest.hexdigest()})
                if index % 100 == 0:
                    print(f'PACK {index}/{len(models)}', flush=True)
            for name, value in (('inventory.json', inventory), ('master-verification.json', master),
                                ('ASSET-MANIFEST.json', manifest), ('asset-pack.json', pack)):
                target.writestr(zip_info(f'{TOOL}/library/{name}'), json_bytes(value))
            target.writestr(zip_info(f'{TOOL}/library/来源与转换说明.md'), source_notes(stats).encode('utf-8'))
        os.replace(partial, output)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return {'path': str(output), 'bytes': output.stat().st_size, 'sha256': sha256_file(output), **pack}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', required=True, type=Path)
    parser.add_argument('--python-runtime', required=True, type=Path)
    parser.add_argument('--source-archive', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--report', type=Path, help='Optional private JSON build report, never included in the archive')
    parser.add_argument('--dry-run', action='store_true', help='Verify inputs and report counts without creating the full archive')
    args = parser.parse_args()
    result = build(args)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_bytes(json_bytes(result))
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
