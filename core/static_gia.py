"""Independent static native entities for scenery; no dynamic wrapper/decorations.

Field mapping and the unmodified ordinary-entity template come from GPL-3.0
Miliastra-Tools commit 44db6abd01ac80d135ad3c06b3ea388e879b5b69,
miliastra_core/export/builder.py and Template/GPT2Gia_entities.gia.
The template contains primitive entities. For another native model, its three
known template-ID references and companion flag are replaced; unknown fields
are preserved. This does not establish each model's official entity defaults.
Binary checks do not measure in-game load or establish native acceptance.
"""
import copy
import hashlib
import math
import struct
import sys
from pathlib import Path

from .coordinates import native_object, reflected_affine
from .math3d import affine
from .naming import static_entity_label

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor' / 'miliastra_tools'))
from miliastra_core.protobuf import wire as w

ENTITY_DOMAIN = 0x40400000
DOMAIN_MASK = 0xfff00000
LOW_MASK = 0xfffff
TEMPLATE = ROOT / 'vendor/miliastra_tools/Template/GPT2Gia_entities.gia'
TEMPLATE_SHA256 = '0f16b5f34764888810ea002b5eaf4efa3be4f446308a7d6ff39e5bb4fcc6baa1'
SOURCE_COMMIT = '44db6abd01ac80d135ad3c06b3ea388e879b5b69'


def _message(parent, number):
    raw = w.first_bytes(parent, number)
    if raw is None:
        raise ValueError(f'普通实体模板缺少消息字段 {number}')
    return w.parse_fields(raw)


def _typed_slot(core, field, kind, payload):
    matches = []
    for index, item in enumerate(core):
        if item.number == field and item.wire_type == 2:
            fields = w.parse_fields(item.value)
            if w.first_varint(fields, 1) == kind:
                matches.append((index, fields))
    if len(matches) != 1:
        raise ValueError(f'普通实体模板组件不唯一：{field}/{kind}')
    index, fields = matches[0]
    return index, fields, _message(fields, payload)


def _change_slot(core, field, kind, payload, update):
    index, fields, data = _typed_slot(core, field, kind, payload)
    update(data)
    w.set_bytes(fields, payload, w.rebuild_message(data))
    core[index] = core[index].with_value(w.rebuild_message(fields))


def _vector(parent, number, values):
    w.set_bytes(parent, number, w.rebuild_message([
        w.fixed32_field(index, value) for index, value in enumerate(values, 1)]))


def _color(obj):
    if not obj.get('custom_color_enabled', False):
        return None
    color = obj.get('color', {})
    rgb = color.get('rgb')
    if (not isinstance(rgb, (tuple, list)) or len(rgb) != 3 or
            any(isinstance(value, bool) or not isinstance(value, int) or
                not 0 <= value <= 255 for value in rgb)):
        raise ValueError('实体自定义颜色必须是 0..255 的 RGB 三元组')
    opacity = float(color.get('opacity', color.get('alpha_percent', 100)))
    if not math.isfinite(opacity) or not 0 <= opacity <= 100:
        raise ValueError('实体不透明度必须是 0..100 的有限数值')
    value = (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]
    return value, opacity, (round(opacity / 100 * 255) << 24) | value


def _create_asset(template, obj, ident, name):
    asset = copy.deepcopy(template)
    meta = _message(asset, 1)
    w.set_varint(meta, 4, ident)
    w.set_bytes(asset, 1, w.rebuild_message(meta))
    w.set_bytes(asset, 3, name.encode('utf-8'))
    entity = _message(asset, 12)
    core = _message(entity, 1)
    tid = obj['template_id']
    w.set_varint(core, 1, ident)
    reference = _message(core, 2)
    w.set_varint(reference, 1, tid)
    w.set_varint(reference, 2, 1)
    w.set_bytes(core, 2, w.rebuild_message(reference))
    w.set_varint(core, 8, tid)
    w.set_varint(entity, 4, tid)

    def naming(data):
        w.set_bytes(data, 1, name.encode('utf-8'))
        w.set_varint(data, 2, 1)
    _change_slot(core, 5, 1, 11, naming)

    def transform(data):
        for index, key in enumerate(('position', 'rotation', 'scale'), 1):
            _vector(data, index, obj[key])
        w.set_varint(data, 501, 0xffffffff)
    _change_slot(core, 6, 1, 11, transform)
    _change_slot(core, 6, 4, 14, lambda data: w.set_varint(data, 1, 1))

    def collider(data):
        # False is proto3's absent scalar, matching the upstream builder.
        data[:] = [field for field in data if field.number not in (1, 2)]
        if obj.get('collision', True):
            w.set_varint(data, 1, 1)
        if obj.get('climb', False):
            w.set_varint(data, 2, 1)
    _change_slot(core, 6, 5, 15, collider)

    def model_display(data):
        data[:] = [field for field in data if field.number not in (1, 3, 4, 5, 6, 9)]
        color = _color(obj)
        if color is not None:
            rgb, opacity, argb = color
            for number, value in ((1, 1), (3, argb), (5, rgb), (6, 6700)):
                w.set_varint(data, number, value)
            w.set_fixed32(data, 4, opacity)
    _change_slot(core, 6, 22, 32, model_display)
    _change_slot(core, 6, 12, 22,
                 lambda data: data.__setitem__(slice(None), [w.varint_field(501, 1)]))
    _change_slot(core, 6, 20, 30, lambda data: data.clear())
    if any(field.number == 2 for field in asset):
        raise ValueError('普通实体模板不应含有父子依赖')
    if _typed_slot(core, 5, 40, 50)[2]:
        raise ValueError('普通实体模板不应含有装饰物列表')
    w.set_bytes(entity, 1, w.rebuild_message(core))
    w.set_bytes(asset, 12, w.rebuild_message(entity))
    return w.rebuild_message(asset)


# Deliberately separate wire decoder: validation never calls the encoder reader.
def _decode_varint(data, position):
    value = shift = 0
    while position < len(data) and shift < 70:
        byte = data[position]
        position += 1
        value |= (byte & 127) << shift
        if byte < 128:
            if value > 0xffffffffffffffff:
                raise ValueError('GIA varint 超出 uint64')
            return value, position
        shift += 7
    raise ValueError('GIA varint 无效或被截断')


def _decode(data):
    fields = []
    position = 0
    while position < len(data):
        key, position = _decode_varint(data, position)
        number, wire = key >> 3, key & 7
        if not 0 < number < (1 << 29):
            raise ValueError('GIA protobuf 字段编号无效')
        if wire == 0:
            value, position = _decode_varint(data, position)
        elif wire == 2:
            size, position = _decode_varint(data, position)
            value = data[position:position + size]
            if len(value) != size:
                raise ValueError('GIA 消息被截断')
            position += size
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            value = data[position:position + size]
            if len(value) != size:
                raise ValueError('GIA 固定长度字段被截断')
            position += size
        else:
            raise ValueError(f'不支持的 GIA wire type {wire}')
        fields.append((number, wire, value))
    return fields


def _single(fields, number, wire, default=None):
    matches = [value for n, t, value in fields if n == number and t == wire]
    if len(matches) > 1:
        raise ValueError(f'GIA 标量字段重复：{number}')
    return matches[0] if matches else default


def _nested(fields, number):
    raw = _single(fields, number, 2)
    if raw is None:
        raise ValueError(f'GIA 缺少必要消息：{number}')
    return _decode(raw)


def _slot(core, field, kind, payload):
    matches = []
    for number, wire, value in core:
        if number == field and wire == 2:
            parsed = _decode(value)
            if _single(parsed, 1, 0) == kind:
                matches.append(_nested(parsed, payload))
    if len(matches) != 1:
        raise ValueError(f'GIA 缺少或重复组件：{field}/{kind}')
    return matches[0]


def _container(blob):
    if len(blob) < 24:
        raise ValueError('GIA 文件过短')
    if struct.unpack('>5I', blob[:20]) != (len(blob) - 4, 1, 0x326, 3, len(blob) - 24):
        raise ValueError('GIA 文件头或长度错误')
    if blob[-4:] != bytes.fromhex('00000679'):
        raise ValueError('GIA 文件尾标记错误')
    return _decode(blob[20:-4])


def check_static_gia(blob, expected_editor=None):
    """Decode static entities and optionally compare right-handed editor affines.

    Every entity is in direct world coordinates. No .01 wrapper compensation is
    present. The returned records use the native left-handed coordinate space.
    """
    collection = _container(blob)
    if any(number == 2 for number, wire, value in collection):
        raise ValueError('静态场景不能混入资源装饰物')
    if any(number == 1 and wire != 2 for number, wire, value in collection):
        raise ValueError('GIA 实体列表 wire type 错误')
    assets = [_decode(value) for number, wire, value in collection if number == 1]
    if not assets:
        raise ValueError('不能导出空场景')
    if expected_editor is not None and len(assets) != len(expected_editor):
        raise ValueError('静态实体数量与工程不一致')
    ids = set()
    records = []
    max_error = 0.0
    for index, asset in enumerate(assets):
        if _single(asset, 5, 0) != 3 or any(n == 2 for n, t, v in asset):
            raise ValueError('静态实体类型错误或含父子依赖')
        ident = _single(_nested(asset, 1), 4, 0)
        if (not isinstance(ident, int) or not 0 < ident <= 0xffffffff or
                ident & DOMAIN_MASK != ENTITY_DOMAIN or
                not ident & LOW_MASK or ident in ids):
            raise ValueError('静态实体编号段错误或重复')
        ids.add(ident)
        entity = _nested(asset, 12)
        core = _nested(entity, 1)
        reference = _nested(core, 2)
        tid = _single(entity, 4, 0)
        if not isinstance(tid, int) or not 0 < tid <= 0xffffffff:
            raise ValueError('静态实体模板编号无效')
        if _single(core, 1, 0) != ident:
            raise ValueError('静态实体元数据与核心编号不一致')
        # Three model-ID references and the observed companion flag.
        if (_single(reference, 1, 0), _single(core, 8, 0)) != (tid, tid):
            raise ValueError('静态实体模板编号引用不一致')
        if _single(reference, 2, 0) != 1:
            raise ValueError('静态实体模板 companion flag 错误')
        naming = _slot(core, 5, 1, 11)
        if _single(naming, 2, 0) != 1:
            raise ValueError('场景实体未设为静态')
        name = _single(asset, 3, 2)
        if not name or _single(naming, 1, 2) != name:
            raise ValueError('静态实体名称不一致或为空')
        name = name.decode('utf-8')
        if _slot(core, 5, 40, 50):
            raise ValueError('静态实体不能包含父级或装饰物列表')
        if _single(_slot(core, 6, 4, 14), 1, 0) != 1:
            raise ValueError('静态实体未开启初始创建')
        collider = _slot(core, 6, 5, 15)
        collision, climb = [_single(collider, key, 0, 0) for key in (1, 2)]
        if collision not in (0, 1) or climb not in (0, 1):
            raise ValueError('静态实体碰撞或攀爬标记错误')
        color = _slot(core, 6, 22, 32)
        enabled = _single(color, 1, 0, 0)
        rgb = _single(color, 5, 0, 0)
        opacity = struct.unpack('<f', _single(color, 4, 5, struct.pack('<f', 100)))[0]
        if enabled == 0:
            if any(n in (1, 3, 4, 5, 6, 9) for n, t, v in color):
                raise ValueError('未启用自定义色却残留覆盖字段')
        elif enabled == 1:
            if (not 0 <= rgb <= 0xffffff or not math.isfinite(opacity) or
                    not 0 <= opacity <= 100 or _single(color, 6, 0) != 6700 or
                    _single(color, 9, 0, 0) != 0):
                raise ValueError('静态实体自定义色字段无效')
            argb = (round(opacity / 100 * 255) << 24) | rgb
            if _single(color, 3, 0) != argb:
                raise ValueError('静态实体 RGB/ARGB/不透明度不一致')
        else:
            raise ValueError('静态实体自定义色标记错误')
        if _slot(core, 6, 12, 22) != [(501, 0, 1)]:
            raise ValueError('静态实体未关闭范围外运行')
        if _slot(core, 6, 20, 30):
            raise ValueError('静态实体范围外显示不是默认值')
        transform = _slot(core, 6, 1, 11)
        if _single(transform, 501, 0) != 0xffffffff:
            raise ValueError('静态实体变换标记错误')
        decoded = {}
        for number, key in enumerate(('position', 'rotation', 'scale'), 1):
            vector = _nested(transform, number)
            decoded[key] = [struct.unpack('<f', _single(vector, k, 5, bytes(4)))[0]
                            for k in (1, 2, 3)]
            if any(not math.isfinite(value) for value in decoded[key]):
                raise ValueError('静态实体变换含非有限数值')
        if min(decoded['scale']) <= 0:
            raise ValueError('静态实体缩放必须为正')
        if expected_editor is not None:
            wanted = expected_editor[index]
            if tid != wanted['template_id']:
                raise ValueError('静态实体模板与工程不一致')
            if (bool(collision), bool(climb)) != (bool(wanted.get('collision', True)),
                                                  bool(wanted.get('climb', False))):
                raise ValueError('静态实体碰撞或攀爬与工程不一致')
            expected_color = _color(wanted)
            if bool(enabled) != (expected_color is not None):
                raise ValueError('静态实体颜色启用状态与工程不一致')
            if expected_color is not None:
                if rgb != expected_color[0] or abs(opacity - expected_color[1]) > .00002:
                    raise ValueError('静态实体颜色与工程不一致')
            actual_m, actual_p = reflected_affine(affine(decoded))
            wanted_m, wanted_p = affine(wanted)
            actual_values = actual_p + sum(actual_m, [])
            wanted_values = wanted_p + sum(wanted_m, [])
            for actual, expected in zip(actual_values, wanted_values):
                error = abs(actual - expected)
                max_error = max(max_error, error)
                if error > max(.0002, abs(expected) * .000002):
                    raise ValueError('静态实体世界变换或坐标转换回读不一致')
        records.append(dict(index=index + 1, entityId=ident, templateId=tid,
                            name=name, static=True, initialCreation=True,
                            collision=bool(collision), climb=bool(climb),
                            customColor=bool(enabled), color=rgb if enabled else None,
                            opacity=opacity if enabled else None,
                            outOfRangeRun=False, outOfRangeDisplay=0, **decoded))
    return dict(fileStructure='passed', independentDecoder=True,
                nativeIdDomains='passed', parentChildLinks='passed',
                worldTransforms='passed' if expected_editor is not None else 'not_checked',
                expectedCoordinateSpace='editor' if expected_editor is not None else 'not_checked',
                coordinateConversion='passed' if expected_editor is not None else 'not_checked',
                nativeTemplateReferences='passed', staticAndInitialCreation='passed',
                collisionAndColor='passed', rangeDefaults='passed',
                maxTransformError=max_error, parents=0, components=len(records),
                entities=len(records), staticEntities=len(records), decorationCount=0, decorations=0,
                nativeEditorValidation='pending', measuredLoadReduction='pending',
                records=records)


def build_static_gia(objects_native, output_path, name, entity_id_start):
    """Write native-space world TRS as independent static entities.

    Returns counts, records, source provenance and binary checks. The caller owns
    the initial editor -> native conversion and can check against its original
    editor objects with check_static_gia(blob, expected_editor).
    """
    if not isinstance(objects_native, list) or not objects_native:
        raise ValueError('静态实体导出需要非空物件列表')
    count = len(objects_native)
    if (isinstance(entity_id_start, bool) or not isinstance(entity_id_start, int) or
            not 0 < entity_id_start <= 0xffffffff or
            entity_id_start + count - 1 > 0xffffffff or
            entity_id_start & DOMAIN_MASK != ENTITY_DOMAIN or
            not entity_id_start & LOW_MASK or
            (entity_id_start + count - 1) & DOMAIN_MASK != ENTITY_DOMAIN):
        raise ValueError('静态实体起始编号段无效或数量超出编号段')
    for obj in objects_native:
        tid = obj.get('template_id')
        if isinstance(tid, bool) or not isinstance(tid, int) or not 0 < tid <= 0xffffffff:
            raise ValueError('静态实体需要有效原生模板编号')
        for key in ('position', 'rotation', 'scale'):
            vector = obj.get(key)
            if (not isinstance(vector, (tuple, list)) or len(vector) != 3 or
                    any(isinstance(v, bool) or not isinstance(v, (int, float)) or
                        not math.isfinite(v) for v in vector)):
                raise ValueError(f'静态实体 {key} 必须为有限数值三元组')
            if key == 'scale' and min(vector) <= 0:
                raise ValueError('静态实体缩放必须为正')
        _color(obj)
    template_blob = TEMPLATE.read_bytes()
    if hashlib.sha256(template_blob).hexdigest() != TEMPLATE_SHA256:
        raise ValueError('普通实体模板 SHA256 与固定来源不一致')
    _container(template_blob)
    collection = w.parse_fields(template_blob[20:-4])
    templates = {}
    for field in collection:
        if field.number == 1 and field.wire_type == 2:
            asset = w.parse_fields(field.value)
            tid = w.first_varint(_message(asset, 12), 4)
            templates.setdefault(tid, asset)
    if 10009001 not in templates:
        raise ValueError('普通实体模板缺少通用长方体样板')
    assets = []
    for index, obj in enumerate(objects_native):
        template = templates.get(obj['template_id'], templates[10009001])
        entity_name = static_entity_label(obj.get('name') or f'物件 {index + 1:04d}', name)
        assets.append(w.len_field(1, _create_asset(template, obj,
                                                 entity_id_start + index, entity_name)))
    output_path = Path(output_path)
    rest = [field for field in collection if field.number not in (1, 2, 3)]
    rest.append(w.len_field(3, ('generated\\' + output_path.name).encode('utf-8')))
    payload = w.rebuild_message(assets + rest)
    blob = struct.pack('>5I', len(payload) + 20, 1, 0x326, 3, len(payload)) + payload + template_blob[-4:]
    # native_object is an involution, so these are editor-space expectations.
    expected = [native_object(obj) for obj in objects_native]
    checks = check_static_gia(blob, expected)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(blob)
    check_static_gia(output_path.read_bytes(), expected)
    return dict(output=str(output_path), asset_count=count, entity_count=count,
                decoration_count=0, parent_count=0, records=checks['records'],
                checks=checks, file_size=len(blob), sha256=hashlib.sha256(blob).hexdigest(),
                sourceCommit=SOURCE_COMMIT, templateSha256=TEMPLATE_SHA256,
                templateDefaults='matching_primitive_or_generic_ordinary_entity_unknown_fields_preserved',
                nativeEditorValidation='pending', measuredLoadReduction='pending')
