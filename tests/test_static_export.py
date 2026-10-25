"""Static scene exports are standalone native entities, not dynamic wrappers.

The small decoder below deliberately does not use the exporter's wire reader.
It inspects saved bytes and world TRS; corruption cases exercise the production
checker separately so an encoder/checker agreement is not the only evidence.
"""
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.coordinates import native_object
from core.static_gia import build_static_gia, check_static_gia
from core.gia import check, w

TEST_TMP = ROOT / '.runtime/tests'
TEST_TMP.mkdir(parents=True, exist_ok=True)


def read_varint(blob, pos):
    value = shift = 0
    while pos < len(blob) and shift < 70:
        byte = blob[pos]
        pos += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, pos
        shift += 7
    raise ValueError('Truncated or oversized varint')


def decode(blob):
    fields = []
    pos = 0
    while pos < len(blob):
        key, pos = read_varint(blob, pos)
        number, kind = key >> 3, key & 7
        if not number:
            raise ValueError('Invalid field number')
        if kind == 0:
            value, pos = read_varint(blob, pos)
        elif kind in (1, 2, 5):
            if kind == 2:
                size, pos = read_varint(blob, pos)
            else:
                size = 8 if kind == 1 else 4
            value = blob[pos:pos + size]
            if len(value) != size:
                raise ValueError('Truncated payload')
            pos += size
        else:
            raise ValueError('Unsupported wire type')
        fields.append((number, kind, value))
    return fields


def field(fields, number, kind, default=None):
    values = [value for n, k, value in fields if n == number and k == kind]
    if len(values) > 1:
        raise ValueError('Duplicate field')
    return values[0] if values else default


def message(fields, number):
    raw = field(fields, number, 2)
    if raw is None:
        raise ValueError('Missing message')
    return decode(raw)


def typed(core, number, kind, payload):
    matches = []
    for n, wire, value in core:
        if n == number and wire == 2:
            entry = decode(value)
            if field(entry, 1, 0) == kind:
                matches.append(message(entry, payload))
    if len(matches) != 1:
        raise ValueError('Missing or duplicate component')
    return matches[0]


def mutate_message(fields, number, callback):
    nested = w.parse_fields(w.first_bytes(fields, number) or b'')
    callback(nested)
    w.set_bytes(fields, number, w.rebuild_message(nested))


def mutate_component(core, number, kind, payload, callback):
    matches = [(i, w.parse_fields(f.value)) for i, f in enumerate(core)
               if f.number == number and f.wire_type == 2
               and w.first_varint(w.parse_fields(f.value), 1) == kind]
    if len(matches) != 1:
        raise AssertionError('Test fixture component not unique')
    index, entry = matches[0]
    mutate_message(entry, payload, callback)
    core[index] = core[index].with_value(w.rebuild_message(entry))


def altered(blob, callback, *, index=0):
    collection = w.parse_fields(blob[20:-4])
    slots = [i for i, f in enumerate(collection) if f.number == 1 and f.wire_type == 2]
    slot = slots[index]
    asset = w.parse_fields(collection[slot].value)
    wrapper = w.parse_fields(w.first_bytes(asset, 12) or b'')
    core = w.parse_fields(w.first_bytes(wrapper, 1) or b'')
    callback(asset, wrapper, core)
    w.set_bytes(wrapper, 1, w.rebuild_message(core))
    w.set_bytes(asset, 12, w.rebuild_message(wrapper))
    collection[slot] = collection[slot].with_value(w.rebuild_message(asset))
    payload = w.rebuild_message(collection)
    return struct.pack('>5I', len(payload) + 20, 1, 0x326, 3, len(payload)) + payload + blob[-4:]


def fixture():
    # Native models retain their materials. Only the explicitly coloured box
    # enables custom colour. All collision combinations must survive export.
    return [
        dict(name='原生木屋', template_id=20002218, position=[3.25, 2, -7],
             rotation=[17, -31, 47], scale=[2, .7, 3],
             custom_color_enabled=False, collision=False, climb=False),
        dict(name='手动基元', template_id=10009001, position=[-8, .6, 12],
             rotation=[0, 90, 0], scale=[.25, 4, 1.5],
             custom_color_enabled=True, color={'rgb': [190, 114, 84], 'opacity': 100},
             collision=True, climb=True),
        dict(name='原生木屋二', template_id=20002219, position=[1, 5, 20],
             rotation=[24, -90, 73], scale=[1, 1, 1],
             custom_color_enabled=False, collision=True, climb=False),
    ]


class StaticExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=TEST_TMP)
        self.path = Path(self.tmp.name).resolve()
        self.assertTrue(self.path.is_relative_to(TEST_TMP.resolve()))
        self.addCleanup(self.tmp.cleanup)
        self.editor = fixture()
        self.native = [native_object(obj) for obj in self.editor]
        self.gia = self.path / 'static-test.gia'
        self.metadata = build_static_gia(
            self.native, self.gia, '静态导出测试', 0x40400100)
        self.blob = self.gia.read_bytes()

    def test_saved_entities_have_static_flags_native_refs_and_direct_world_trs(self):
        self.assertEqual(struct.unpack('>5I', self.blob[:20]),
                         (len(self.blob) - 4, 1, 0x326, 3, len(self.blob) - 24))
        self.assertEqual(self.blob[-4:], bytes.fromhex('00000679'))
        collection = decode(self.blob[20:-4])
        self.assertFalse(any(n == 2 for n, _, _ in collection), 'No decoration assets')
        assets = [decode(v) for n, k, v in collection if n == 1 and k == 2]
        self.assertEqual(len(assets), len(self.native))
        seen = set()
        for asset, wanted in zip(assets, self.native):
            self.assertEqual(field(asset, 5, 0), 3)
            self.assertFalse(any(n == 2 for n, _, _ in asset), 'No parent dependencies')
            ident = field(message(asset, 1), 4, 0)
            self.assertEqual(ident & 0xfff00000, 0x40400000)
            self.assertNotEqual(ident & 0xfffff, 0)
            self.assertNotIn(ident, seen)
            seen.add(ident)
            wrapper = message(asset, 12)
            core = message(wrapper, 1)
            self.assertEqual(field(core, 1, 0), ident)
            ref = message(core, 2)
            for reference in (field(ref, 1, 0), field(core, 8, 0), field(wrapper, 4, 0)):
                self.assertEqual(reference, wanted['template_id'])
            self.assertEqual(field(ref, 2, 0), 1)
            self.assertEqual(field(typed(core, 5, 1, 11), 2, 0), 1, 'Static entity')
            self.assertFalse(typed(core, 5, 40, 50), 'No decoration children')
            self.assertEqual(field(typed(core, 6, 4, 14), 1, 0), 1, 'Created initially')
            transform = typed(core, 6, 1, 11)
            for number, key in enumerate(('position', 'rotation', 'scale'), 1):
                vec = message(transform, number)
                values = [struct.unpack('<f', field(vec, axis, 5, bytes(4)))[0]
                          for axis in (1, 2, 3)]
                for actual, expected in zip(values, wanted[key]):
                    self.assertTrue(math.isfinite(actual))
                    self.assertAlmostEqual(actual, expected, places=5,
                                           msg='Standalone entity uses direct world TRS, no .01 parent')

    def test_original_material_and_explicit_primitive_color_and_collision_survive(self):
        assets = [decode(v) for n, k, v in decode(self.blob[20:-4]) if n == 1 and k == 2]
        for asset, wanted in zip(assets, self.native):
            core = message(message(asset, 12), 1)
            collision = typed(core, 6, 5, 15)
            self.assertEqual(bool(field(collision, 1, 0, 0)), wanted['collision'])
            self.assertEqual(bool(field(collision, 2, 0, 0)), wanted['climb'])
            color = typed(core, 6, 22, 32)
            if wanted['custom_color_enabled']:
                self.assertEqual(field(color, 1, 0), 1)
                self.assertEqual(field(color, 5, 0), 0xbe7254)
                self.assertEqual(field(color, 3, 0), 0xffbe7254)
            else:
                self.assertFalse(any(n in (1, 3, 4, 5, 6, 9) for n, _, _ in color),
                                 'No primitive material overrides on complete native models')

    def test_static_checker_and_legacy_dispatch_agree_on_editor_coordinate_roundtrip(self):
        checks = check_static_gia(self.blob, self.editor)
        for key in ('parents', 'decorations'):
            self.assertEqual(checks[key], 0)
        for key in ('components', 'entities', 'staticEntities'):
            self.assertEqual(checks[key], len(self.editor))
        self.assertEqual(checks['coordinateConversion'], 'passed')
        self.assertEqual(checks['worldTransforms'], 'passed')
        self.assertEqual(check(self.blob, self.editor, expected_space='editor')['staticEntities'], len(self.editor))
        self.assertEqual(check(self.blob, self.native)['worldTransforms'], 'passed')
        with self.assertRaises(ValueError):
            check_static_gia(self.blob[:-1], self.editor)

    def test_checker_rejects_dynamic_flags_template_refs_and_parent_links(self):
        changes = {
            'dynamic_flag': lambda a, e, c: mutate_component(c, 5, 1, 11, lambda p: w.set_varint(p, 2, 0)),
            'template_ref': lambda a, e, c: mutate_message(c, 2, lambda p: w.set_varint(p, 1, 20002078)),
            'template_kind': lambda a, e, c: mutate_message(c, 2, lambda p: w.set_varint(p, 2, 0)),
            'template_core': lambda a, e, c: w.set_varint(c, 8, 20002078),
            'template_wrapper': lambda a, e, c: w.set_varint(e, 4, 20002078),
            'dependency': lambda a, e, c: a.append(w.len_field(2, w.rebuild_message([w.varint_field(4, 0x40000001)]))),
            'decoration_children': lambda a, e, c: mutate_component(c, 5, 40, 50, lambda p: w.set_bytes(p, 501, w.encode_packed_varints([0x40000001]))),
            'initially_disabled': lambda a, e, c: mutate_component(c, 6, 4, 14, lambda p: w.set_varint(p, 1, 0)),
        }
        for title, change in changes.items():
            with self.subTest(corruption=title), self.assertRaises(ValueError):
                check_static_gia(altered(self.blob, change), self.editor)

    def test_checker_rejects_changed_world_transforms_colors_and_collision(self):
        def vector_change(number, value):
            return lambda a, e, c: mutate_component(c, 6, 1, 11,
                lambda p: mutate_message(p, number, lambda vector: w.set_fixed32(vector, 1, value)))
        changes = [
            ('position', 0, vector_change(1, 777)),
            ('rotation', 0, vector_change(2, 111)),
            ('scale', 0, vector_change(3, 100)),
            ('nonfinite_transform', 0, vector_change(1, float('nan'))),
            ('native_color_enabled', 0, lambda a, e, c: mutate_component(c, 6, 22, 32, lambda p: w.set_varint(p, 1, 1))),
            ('primitive_color_changed', 1, lambda a, e, c: mutate_component(c, 6, 22, 32, lambda p: w.set_varint(p, 5, 0x123456))),
            ('collision_changed', 0, lambda a, e, c: mutate_component(c, 6, 5, 15, lambda p: w.set_varint(p, 1, 1))),
            ('climb_changed', 1, lambda a, e, c: mutate_component(c, 6, 5, 15, lambda p: w.set_varint(p, 2, 0))),
        ]
        for title, index, change in changes:
            with self.subTest(corruption=title), self.assertRaises(ValueError):
                check_static_gia(altered(self.blob, change, index=index), self.editor)

    def test_checker_rejects_duplicate_and_wrong_domain_instance_ids(self):
        def change_id(ident):
            def update(asset, wrapper, core):
                mutate_message(asset, 1, lambda p: w.set_varint(p, 4, ident))
                w.set_varint(core, 1, ident)
            return update
        for ident in (0x40000101, 0x40400000, 0x40400100):
            with self.subTest(ident=hex(ident)), self.assertRaises(ValueError):
                check_static_gia(altered(self.blob, change_id(ident), index=1), self.editor)


if __name__ == '__main__':
    unittest.main(verbosity=2)
