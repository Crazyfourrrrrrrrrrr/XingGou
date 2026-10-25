"""Native prefabs take priority; primitive construction is an explicit fallback.

All model requests terminate at this test's loopback HTTP server. No provider
configuration or credentials from the user's running editor are loaded.
"""
import copy
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.catalog import Catalog, PRIMITIVES
from core.generator import (
    Provider, context, generate_asset, generate_scene,
    node, offline_plan, offline_scene,
)
from core.scene import ProjectStore, empty, flatten
from server import App, Handler

CAT = Catalog()
TEST_TMP = ROOT / '.runtime/tests'
TEST_TMP.mkdir(parents=True, exist_ok=True)


def catalog_subset(predicate):
    """Keep real metadata/search semantics while simulating absent resources."""
    catalog = copy.copy(CAT)
    catalog.assets = [copy.deepcopy(a) for a in CAT.assets if predicate(a)]
    catalog.by_id = {}
    catalog.by_template = {}
    for asset in catalog.assets:
        catalog.by_id[asset['id']] = asset
        for alias in asset['aliases']:
            catalog.by_id.setdefault(alias['id'], asset)
        if asset['templateId']:
            catalog.by_template.setdefault(asset['templateId'], asset)
    catalog.available = any(not a['primitive'] for a in catalog.assets)
    return catalog


class LocalModel(BaseHTTPRequestHandler):
    result = {}
    requests = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        type(self).requests.append(request)
        payload = json.dumps({
            'choices': [{'message': {'content': json.dumps(type(self).result)}}]
        }).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class NativePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(dir=TEST_TMP)
        cls.root = Path(cls.tmp.name).resolve()
        assert cls.root.is_relative_to(TEST_TMP.resolve())
        cls.mock = ThreadingHTTPServer(('127.0.0.1', 0), LocalModel)
        cls.mock.daemon_threads = True
        threading.Thread(target=cls.mock.serve_forever, daemon=True).start()
        cls.provider = Provider(cls.root / 'provider')
        # Override any provider environment defaults with a loopback-only target.
        cls.provider.configure({
            'baseUrl': f'http://127.0.0.1:{cls.mock.server_port}/v1',
            'model': 'native-policy-test', 'apiKey': 'local-mock-only',
        })
        app = object.__new__(App)
        app.catalog = CAT
        app.provider = cls.provider
        app.store = ProjectStore(cls.root / 'projects', CAT)
        app.exports = cls.root / 'exports'
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.server.app = app
        cls.server.daemon_threads = True
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.mock.shutdown()
        cls.mock.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        LocalModel.result = {}
        LocalModel.requests = []

    def require_real_library(self):
        if not CAT.available:
            self.skipTest('External game library is not configured')

    def assert_native_scene(self, scene, catalog=CAT):
        objects, blocked = flatten(scene, catalog)
        self.assertFalse(blocked)
        self.assertEqual(len(scene['definitions']), 0, 'Offline placement must reference complete native prefabs')
        for obj in objects:
            self.assertNotIn(obj['template_id'], PRIMITIVES)
            self.assertFalse(catalog.by_id[obj['asset_id']]['primitive'])
            self.assertFalse(obj['custom_color_enabled'])
        return objects

    def test_offline_scene_uses_existing_prefabs_without_primitive_surfaces(self):
        self.require_real_library()
        scene = offline_scene(offline_plan('森林溪流村庄，3栋木质房屋和木桥、入口拱门、摊位'), CAT)
        objects = self.assert_native_scene(scene)
        self.assertGreater(len(objects), 30)
        self.assertEqual(sum(n['layer'] == '建筑' for n in scene['nodes']), 3)
        names = [CAT.by_id[o['asset_id']]['name'] for o in objects]
        for term in ('桥', '门', '摊'):
            self.assertTrue(any(term in name for name in names), term)
        self.assertFalse(any(n['name'] in ('地形基座', '溪流示意面', '小屋替代组合') for n in scene['nodes']))

    def test_native_features_and_legacy_custom_assets_both_use_one_bridge_prefab(self):
        self.require_real_library()
        for key in ('nativeFeatures', 'customAssets'):
            with self.subTest(plan_field=key):
                plan = dict(title='一座桥', buildings=0, trees=0, rocks=0,
                            water=True, **{key: ['bridge']})
                scene = offline_scene(plan, CAT)
                objects = self.assert_native_scene(scene)
                bridges = [o for o in objects if '桥' in CAT.by_id[o['asset_id']]['name']]
                self.assertEqual(len(bridges), 1)
                self.assertLess(len(objects), 30, 'An existing bridge must not expand into a 30-piece recipe')

    def test_missing_library_does_not_create_fake_buildings_trees_or_water(self):
        missing = catalog_subset(lambda a: bool(a['primitive']))
        scene = offline_scene(dict(title='缺库', buildings=3, trees=5, rocks=4,
                                  water=True, nativeFeatures=['bridge', 'arch', 'stall']), missing)
        objects = self.assert_native_scene(scene, missing)
        self.assertFalse(objects)
        self.assertTrue(scene['design'].get('notes'), 'Missing resources must be reported instead of substituted')

    def test_missing_road_and_water_are_reported_without_white_model_fallback(self):
        self.require_real_library()
        # A real house-only catalog has neither road/water nor their native IDs.
        houses = catalog_subset(lambda a: a['id'] == '20002078' or bool(a['primitive']))
        scene = offline_scene(dict(title='房屋', buildings=1, trees=0, rocks=0, water=True,
                                  nativeFeatures=[]), houses)
        objects = self.assert_native_scene(scene, houses)
        self.assertTrue(objects)
        self.assertTrue(all(o['asset_id'] == '20002078' for o in objects))
        notes = json.dumps(scene['design'].get('notes', []), ensure_ascii=False)
        self.assertTrue(any(term in notes for term in ('水', '溪', '河')))
        self.assertTrue(any(term in notes for term in ('路', '道')))

    def test_model_context_excludes_primitives_and_includes_native_features(self):
        self.require_real_library()
        assets = context(CAT, '桥边的小集市入口')
        self.assertTrue(assets)
        for asset in assets:
            canonical = CAT.by_id[asset['assetId']]
            self.assertFalse(canonical['primitive'])
            self.assertNotIn(canonical['templateId'], PRIMITIVES)
        for term in ('桥', '门', '摊'):
            self.assertTrue(any(term in asset['name'] for asset in assets), term)

    def test_model_scene_rejects_direct_nested_and_alias_primitives(self):
        alias_catalog = copy.copy(CAT)
        alias_catalog.by_id = dict(CAT.by_id)
        alias_catalog.by_id['primitive-box-alias'] = copy.deepcopy(CAT.by_id['10009001'])
        # A native ID is authoritative even when incoming metadata omits its kind.
        disguised = copy.deepcopy(CAT.by_id['10009001'])
        disguised['primitive'] = None
        alias_catalog.by_id['primitive-without-kind'] = disguised
        for ident, nested in [('10009001', False), ('10009001', True),
                              ('primitive-box-alias', False), ('primitive-box-alias', True),
                              ('primitive-without-kind', True)]:
            with self.subTest(asset_id=ident, nested=nested):
                scene = empty('不允许自动基元')
                if nested:
                    scene['definitions'] = {
                        'custom_leaf': {'components': [node(ident, '基元')]},
                        'custom_outer': {'components': [node('custom_leaf', '内组')]},
                    }
                    scene['nodes'] = [node('custom_outer', '根组')]
                else:
                    scene['nodes'] = [node(ident, '直接基元')]
                LocalModel.result = scene
                with self.assertRaises(ValueError):
                    generate_scene(dict(title='纯原生'), 'ai', alias_catalog, self.provider)

    def test_model_scene_allows_grouping_complete_native_prefabs(self):
        self.require_real_library()
        scene = empty('原生分组')
        scene['definitions']['custom_houses'] = {'components': [
            node('20002078', '屋一', (-6, 0, 0)), node('20002218', '屋二', (6, 0, 0)),
        ]}
        scene['nodes'] = [node('custom_houses', '房屋组')]
        LocalModel.result = scene
        result = generate_scene(dict(title='纯原生'), 'ai', CAT, self.provider)
        objects, blocked = flatten(result, CAT)
        self.assertFalse(blocked)
        self.assertEqual(len(objects), 2)
        self.assertTrue(all(o['template_id'] not in PRIMITIVES for o in objects))

    def test_asset_native_match_wins_even_with_primitive_fallback_enabled(self):
        self.require_real_library()
        for mode in ('offline', 'ai'):
            for allowed in (False, True):
                with self.subTest(mode=mode, allow_primitives=allowed):
                    asset = generate_asset('木桥', mode, self.provider, CAT, allow_primitives=allowed)
                    self.assertEqual(asset['origin'], 'native')
                    self.assertTrue(asset['nativeModel'])
                    self.assertIn(str(asset['id']), CAT.by_id)
                    self.assertFalse(CAT.by_id[str(asset['id'])]['primitive'])
                    self.assertIn('桥', CAT.by_id[str(asset['id'])]['name'])
                    self.assertFalse(asset.get('components'))
        self.assertFalse(LocalModel.requests, 'Existing assets must be resolved without a model request')

    def test_primitive_fallback_requires_permission_and_a_known_offline_shape(self):
        missing = catalog_subset(lambda a: bool(a['primitive']))
        for mode in ('offline', 'ai'):
            with self.subTest(mode=mode):
                with self.assertRaises(ValueError):
                    generate_asset('螺旋星形雕塑', mode, self.provider, missing)
        self.assertFalse(LocalModel.requests)
        with self.assertRaises(ValueError):
            generate_asset('螺旋星形雕塑', 'offline', self.provider, missing, allow_primitives=True)
        bridge = generate_asset('木桥', 'offline', self.provider, missing, allow_primitives=True)
        self.assertTrue(bridge['components'])
        self.assertTrue(all(int(c['assetId']) in PRIMITIVES for c in bridge['components']))
        LocalModel.result = dict(name='螺旋星形雕塑', description='仅测试',
                                 components=[node('10009001', '主体')])
        asset = generate_asset('螺旋星形雕塑', 'ai', self.provider, missing, allow_primitives=True)
        self.assertEqual(asset['origin'], 'ai')
        self.assertEqual(len(LocalModel.requests), 1)

    def test_unique_shapes_do_not_match_background_bridge_or_entrance(self):
        self.require_real_library()
        descriptions = ('桥边盘旋的机械巨龙雕塑', '入口旁的三头龙雕塑', '双层旋转螺旋木桥')
        for idea in descriptions:
            with self.subTest(idea=idea):
                before = len(LocalModel.requests)
                for mode in ('offline', 'ai'):
                    with self.assertRaises(ValueError):
                        generate_asset(idea, mode, self.provider, CAT)
                self.assertEqual(len(LocalModel.requests), before,
                                 'An unmatched shape must not call a model without explicit fallback')
                LocalModel.result = dict(name=idea, description='独特造型测试',
                                         components=[node('10009001', '主体')])
                asset = generate_asset(idea, 'ai', self.provider, CAT, allow_primitives=True)
                self.assertEqual(asset['origin'], 'ai')
                self.assertTrue(asset['components'])
                self.assertEqual(len(LocalModel.requests), before + 1)
                payload = json.loads(LocalModel.requests[-1]['messages'][1]['content'])
                self.assertEqual(payload['idea'], idea, 'Shape constraints must reach the model unchanged')
        before = len(LocalModel.requests)
        bridge = generate_asset('木桥', 'ai', self.provider, CAT, allow_primitives=True)
        self.assertEqual(bridge['origin'], 'native')
        self.assertTrue(bridge['nativeModel'])
        self.assertIn('桥', CAT.by_id[str(bridge['id'])]['name'])
        self.assertEqual(len(LocalModel.requests), before,
                         'An ordinary existing bridge must still bypass generation')

    def test_http_asset_endpoint_keeps_primitive_fallback_opt_in(self):
        idea = '螺旋星形雕塑'
        LocalModel.result = dict(name=idea, description='仅测试', components=[node('10009001', '主体')])
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def request(data):
            return opener.open(urllib.request.Request(
                self.url + '/api/ai/asset', data=json.dumps(data).encode(),
                headers={'Content-Type': 'application/json', 'X-StarScene': '1'},
            ), timeout=15)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            request(dict(idea=idea, mode='ai'))
        self.assertEqual(caught.exception.code, 400)
        self.assertFalse(LocalModel.requests)
        with request(dict(idea=idea, mode='ai', allowPrimitives=True)) as response:
            asset = json.load(response)['asset']
        self.assertEqual(asset['origin'], 'ai')
        self.assertEqual(len(LocalModel.requests), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
