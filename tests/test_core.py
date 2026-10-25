import copy,json,math,os,struct,subprocess,sys,tempfile,threading,unittest,urllib.error,urllib.request,zipfile
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from core.catalog import Catalog
from core.scene import empty,validate,flatten,ProjectStore
from core.math3d import rotation,mv,affine,combine,add
from core.coordinates import native_object,reflected_affine
from core.generator import node,recipe,offline_plan,offline_scene,Provider,generate_plan,generate_scene,generate_asset
from core.gia import export_scene,check,ExportBlocked,w
from server import Handler,App

CAT=Catalog()
TEST_TMP=ROOT/'.runtime/tests';TEST_TMP.mkdir(parents=True,exist_ok=True)
class SceneTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=TEST_TMP);self.path=Path(self.tmp.name).resolve();self.assertTrue(self.path.is_relative_to(TEST_TMP.resolve()));self.addCleanup(self.tmp.cleanup)
    def test_catalog_real_roots_and_unbound_terrain(self):
        if not CAT.available:self.skipTest('External game library is not configured')
        self.assertEqual(len(CAT.assets),2996);self.assertEqual(sum(a['exportable'] for a in CAT.assets),2367)
        self.assertTrue(CAT.model_path('20002078').is_file());self.assertFalse(next(a for a in CAT.assets if a['id'].startswith('terrain-'))['exportable'])
        self.assertEqual(CAT.by_id['10009001']['primitive'],'box')
    def test_catalog_portable_library_and_explicit_settings_precedence(self):
        # Metadata-only libraries prove which source was loaded; no game model
        # or private installation configuration is needed for this test.
        install=self.path/'portable';install.mkdir()
        libraries={name:install/name for name in ('library','configured','old-env','new-env','explicit')}
        libraries['legacy']=install.parent/'Miliastra-Asset-Library'
        ids={}
        for index,(name,path) in enumerate(libraries.items()):
            path.mkdir();ids[name]=str(21000000+index)
            row=dict(id=int(ids[name]),internal_name='House_'+name,name='测试房屋 '+name,group='建筑',glb='metadata-only.glb')
            (path/'inventory.json').write_text(json.dumps([row]),'utf-8')
        def selected(name,catalog):
            self.assertEqual(catalog.root,libraries[name].resolve())
            self.assertTrue(catalog.available)
            self.assertIn(ids[name],catalog.by_id)
        with patch('core.catalog.ROOT',install),patch.dict(os.environ,{},clear=False):
            os.environ.pop('XINGGOU_ASSET_ROOT',None);os.environ.pop('STARSCENE_ASSET_ROOT',None)
            selected('library',Catalog())
            config=install/'config.local.json';config.write_text(json.dumps(dict(assetRoot='configured')),'utf-8')
            selected('configured',Catalog())
            os.environ['STARSCENE_ASSET_ROOT']='old-env';selected('old-env',Catalog())
            os.environ['XINGGOU_ASSET_ROOT']='new-env';selected('new-env',Catalog())
            selected('explicit',Catalog('explicit'))
            # With no override or bundled inventory, existing adjacent-library
            # installations continue to work; a completely absent library must
            # still expose only the eleven explicit primitive entries.
            config.unlink();os.environ.pop('XINGGOU_ASSET_ROOT');os.environ.pop('STARSCENE_ASSET_ROOT')
            (libraries['library']/'inventory.json').unlink();selected('legacy',Catalog())
            (libraries['legacy']/'inventory.json').unlink();missing=Catalog()
            self.assertFalse(missing.available);self.assertEqual(len(missing.assets),11)
            self.assertTrue(all(asset['primitive'] for asset in missing.assets))
    def test_rotation_contract_and_reject_shear(self):
        self.assertAlmostEqual(mv(rotation([0,90,0]),[1,0,0])[2],-1)
        s=empty();s['definitions']['custom_a']=dict(components=[node('10009001','梁',rotation=(0,45,0))]);s['nodes']=[node('custom_a','组合',scale=(2,1,1))]
        with self.assertRaisesRegex(ValueError,'剪切'):flatten(s,CAT)
    def test_handedness_maps_geometry_points_and_is_involutive(self):
        # A native prefab point is reflected too, not just its instance position.
        # This would fail if only X translation or an unrelated 180° rotation
        # were used for the extracted GLB's local basis.
        for angles in ([17,-31,47],[0,90,0],[24,-90,73],[-8,16,-125]):
            original=dict(position=[3.25,2,-7],rotation=angles,scale=[2,.7,3])
            native=native_object(original);self.assertEqual(native_object(native),original)
            source_m,source_p=affine(original);native_m,native_p=affine(native)
            for point in ([.17,.43,-.91],[-.8,.12,.33],[1,0,0]):
                wanted=add(source_p,mv(source_m,point));q=[-point[0],point[1],point[2]]
                actual=add(native_p,mv(native_m,q));actual[0]*=-1
                for a,b in zip(actual,wanted):self.assertAlmostEqual(a,b,places=10)
    def test_native_export_reverses_handedness_and_legacy_wrapper_still_reads(self):
        s=empty();s['nodes']=[node('10009001','定向长方体',(3.25,2,-7),(2,.7,3),(17,-31,47),'#be7254')]
        r=export_scene(s,CAT,self.path);folder=self.path/Path(r['url']).stem
        gia=next(folder.glob('*.gia')).read_bytes();objects,_=flatten(s,CAT)
        native=json.loads((folder/'native-components.json').read_text('utf-8'))
        self.assertEqual(native[0]['position'],[-3.25,2,-7])
        for a,b in zip(native[0]['rotation'],[17,31,-47]):self.assertAlmostEqual(a,b,places=9)
        self.assertEqual(r['report']['exportMode'],'static_entities')
        self.assertEqual(r['report']['groups'],[])
        self.assertEqual(r['report']['checks']['parents'],0)
        self.assertEqual(check(gia,objects,expected_space='editor')['coordinateConversion'],'passed')
        with self.assertRaisesRegex(ValueError,'世界变换'):check(gia,objects,expected_space='native')
        legacy=export_scene(s,CAT,self.path,mode='decorations');legacy_folder=self.path/Path(legacy['url']).stem
        self.assertEqual(legacy['report']['groups'][0]['scale'],[.01,.01,.01])
        self.assertEqual(check(next(legacy_folder.glob('*.gia')).read_bytes(),objects,expected_space='editor')['coordinateConversion'],'passed')
    def test_invalid_project_and_cycles(self):
        s=empty();s['nodes']=[node('10009001','无效',position=(float('nan'),0,0))]
        with self.assertRaises(ValueError):validate(s,CAT)
        s=empty();s['definitions']['custom_a']=dict(components=[node('custom_a','循环')])
        with self.assertRaisesRegex(ValueError,'循环'):validate(s,CAT)
    def test_expansion_budget(self):
        s=empty();s['definitions']['custom_a']=dict(components=[node('10009001','基元') for _ in range(200)]);s['definitions']['custom_b']=dict(components=[node('custom_a','组') for _ in range(100)]);s['nodes']=[node('custom_b','大组')]
        with self.assertRaisesRegex(ValueError,'预算'):flatten(s,CAT)
    def test_unbound_is_never_silently_exported(self):
        local=next((a for a in CAT.assets if not a['exportable']),None)
        if not local:self.skipTest('No unbound library models')
        s=empty();s['definitions']['custom_a']=dict(components=[node(local['id'],'未绑定')]);s['nodes']=[node('custom_a','根物件'),node('10009001','可导出')]
        with self.assertRaises(ExportBlocked) as caught:export_scene(s,CAT,self.path)
        self.assertEqual(caught.exception.blocked[0]['id'],s['nodes'][0]['id'])
        s['nodes'][0]['visible']=False;self.assertEqual(export_scene(s,CAT,self.path)['report']['checks']['components'],1)
    def test_recipes_native_roundtrip(self):
        for kind in ('bridge','arch','well','tower','stall'):
            with self.subTest(kind=kind):
                a=recipe(kind,kind);s=empty('配方-'+kind);s['definitions'][a['id']]=a;s['nodes']=[node(a['id'],'成品',(10,2,-7),(1.4,1.4,1.4),(10,36,15))]
                result=export_scene(s,CAT,self.path);r=result['report'];self.assertEqual(r['checks']['worldTransforms'],'passed');self.assertEqual(r['expandedComponents'],len(a['components']))
                gia=next((self.path/Path(result['url']).name.replace('.zip','')).glob('*.gia'));blob=gia.read_bytes()
                self.assertEqual(check(blob)['components'],len(a['components']))
                with self.assertRaisesRegex(ValueError,'长度'):check(blob[:-1])
    def test_native_materials_preserved_without_dynamic_group_limit(self):
        s=empty();s['nodes']=[node('10009001',str(i),(i%25,0,i//25),rotation=(0,i%180,0)) for i in range(1003)]
        if CAT.available:s['nodes'].append(node('20002078','原生房屋',(30,0,0)))
        r=export_scene(s,CAT,self.path);self.assertEqual(r['report']['checks']['parents'],0);self.assertEqual(r['report']['groups'],[])
        self.assertEqual(r['report']['staticEntities'],len(s['nodes']))
        self.assertEqual(r['report']['checks']['components'],len(s['nodes']))
        self.assertEqual(r['report']['checks']['decorations'],0)
        with zipfile.ZipFile(self.path/Path(r['url']).name) as z:
            objects=json.loads(z.read('components.json'));self.assertTrue(all(not o['custom_color_enabled'] for o in objects))
    def test_project_conflicts_and_atomic_persistence(self):
        store=ProjectStore(self.path,CAT);s=empty('版本 A');store.put(s,0)
        with self.assertRaises(RuntimeError):store.put(empty('冲突'),0)
        self.assertEqual(ProjectStore(self.path,CAT).get()['project']['name'],'版本 A')
    def test_offline_stages_use_real_assets(self):
        if not CAT.available:self.skipTest('External game library is not configured')
        p=offline_plan('小型森林溪流村庄，3栋木质房屋和入口拱门');self.assertEqual(p['buildings'],3);self.assertEqual(p['theme'],'village')
        s=offline_scene(p,CAT);objects,blocked=flatten(s,CAT);self.assertFalse(blocked);self.assertGreater(len(objects),40)
        self.assertFalse(s['definitions'])
        self.assertTrue(all(not CAT.by_id[o['asset_id']]['primitive'] for o in objects))
        self.assertTrue(all(not o['custom_color_enabled'] for o in objects))
        self.assertFalse(any(n['name'] in ('地形基座','溪流示意面','小屋替代组合') for n in s['nodes']))
        if CAT.available:self.assertEqual(sum(n['layer']=='建筑' for n in s['nodes']),3)

class MockModel(BaseHTTPRequestHandler):
    result={};seen={};code=200
    def log_message(self,*args):pass
    def do_POST(self):
        type(self).seen=dict(path=self.path,authorization=self.headers.get('Authorization'),body=json.loads(self.rfile.read(int(self.headers['Content-Length']))))
        b=json.dumps(dict(choices=[dict(message=dict(content=json.dumps(type(self).result,ensure_ascii=False)))]),ensure_ascii=False).encode();self.send_response(type(self).code);self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)

class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(dir=TEST_TMP);cls.root=Path(cls.tmp.name).resolve();assert cls.root.is_relative_to(TEST_TMP.resolve());app=object.__new__(App);app.catalog=CAT;app.store=ProjectStore(cls.root/'projects',CAT);app.provider=Provider(cls.root/'provider');app.exports=cls.root/'exports';cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);cls.server.app=app;cls.server.daemon_threads=True;cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start();cls.url='http://127.0.0.1:'+str(cls.server.server_port)
        cls.mock=ThreadingHTTPServer(('127.0.0.1',0),MockModel);threading.Thread(target=cls.mock.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.mock.shutdown();cls.mock.server_close();cls.tmp.cleanup()
    def request(self,path,data=None,extra=None,client_header='X-XingGou'):
        req=urllib.request.Request(self.url+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json',client_header:'1',**(extra or {})})
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=15)
    def test_ready_assets_model_range_and_static_confinement(self):
        with self.request('/api/health') as r:self.assertEqual(json.load(r)['tool'],'XingGou')
        if CAT.available:
            with self.request('/models/20002078.glb',extra={'Range':'bytes=0-11'}) as r:self.assertEqual(r.status,206);self.assertEqual(r.read()[:4],b'glTF')
        for path in ('/%2e%2e/server.py','/models/../../server.py','/download/%2e%2e/server.py'):
            with self.assertRaises(urllib.error.HTTPError) as e:self.request(path)
            self.assertIn(e.exception.code,(403,404))
    def test_cross_site_and_revision_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as e:self.request('/api/project',{}, {'Origin':'https://example.invalid'})
        self.assertEqual(e.exception.code,403)
        for client_header in ('X-XingGou','X-StarScene'):
            with self.subTest(client_header=client_header):
                rev=self.server.app.store.get()['revision']
                with self.request('/api/project',dict(project=empty(),revision=rev),client_header=client_header) as r:self.assertEqual(r.status,200)
                with self.assertRaises(urllib.error.HTTPError) as e:self.request('/api/project',dict(project=empty(),revision=rev),client_header=client_header)
                self.assertEqual(e.exception.code,409)
    def test_export_endpoint_defaults_to_static_and_rejects_unbound(self):
        scene=empty('静态 HTTP 测试');scene['nodes']=[node('10009001','显式基元')]
        with self.request('/api/export',dict(project=scene)) as response:result=json.load(response)
        self.assertEqual(result['report']['exportMode'],'static_entities')
        self.assertEqual(result['report']['checks']['parents'],0)
        self.assertEqual(result['report']['staticEntities'],1)
        local=next((a for a in CAT.assets if not a['exportable']),None)
        if local:
            scene['nodes'].append(node(local['id'],'未绑定'))
            with self.assertRaises(urllib.error.HTTPError) as caught:self.request('/api/export',dict(project=scene))
            self.assertEqual(caught.exception.code,422)
            self.assertEqual(json.load(caught.exception)['blocked'][0]['assetId'],local['id'])
    def test_compatible_api_real_http_without_key_persistence(self):
        provider=self.server.app.provider;provider.configure(dict(baseUrl=f'http://127.0.0.1:{self.mock.server_port}/v1',model='test-model',apiKey='test-only-not-a-secret'))
        MockModel.result=offline_plan('森林营地');MockModel.code=200;p=generate_plan('森林营地','ai',provider);self.assertEqual(p['mode'],'ai');self.assertEqual(MockModel.seen['path'],'/v1/chat/completions');self.assertEqual(MockModel.seen['authorization'],'Bearer test-only-not-a-secret');self.assertNotIn('test-only',provider.file.read_text())
        with self.request('/api/provider') as response:self.assertNotIn('test-only-not-a-secret',response.read().decode('utf-8'))
        # The compatible API's JSON transport and key handling do not require a
        # game library. Exercise a native model too when that integration exists.
        MockModel.result=empty('模型测试')
        if CAT.available:MockModel.result['nodes']=[node('20002078','原生房屋')]
        s=generate_scene(p,'ai',CAT,provider);self.assertEqual(s['name'],'模型测试')
        MockModel.result=dict(name='螺旋星形雕塑',description='测试',components=[node('10009001','柱')]);self.assertEqual(generate_asset('螺旋星形雕塑','ai',provider,CAT,allow_primitives=True)['origin'],'ai')
        MockModel.code=401
        with self.assertRaisesRegex(ValueError,'HTTP 401') as rejected:generate_plan('场景','ai',provider)
        self.assertNotIn('test-only-not-a-secret',str(rejected.exception))
        if isinstance(rejected.exception.__cause__,urllib.error.HTTPError):rejected.exception.__cause__.close()
        MockModel.code=200
    def test_mcp_stdio_connects_to_same_engine(self):
        messages=[dict(jsonrpc='2.0',id=1,method='initialize',params={}),dict(jsonrpc='2.0',id=2,method='tools/list'),dict(jsonrpc='2.0',id=3,method='tools/call',params=dict(name='catalog_search',arguments=dict(query='长方体',ready=True,limit=3))),dict(jsonrpc='2.0',id=4,method='tools/call',params=dict(name='scene_get',arguments={}))]
        for preferred in (False,True):
            with self.subTest(new_environment_priority=preferred):
                env=os.environ.copy();env.pop('XINGGOU_URL',None);env['STARSCENE_URL']=self.url
                if preferred:env.update(XINGGOU_URL=self.url,STARSCENE_URL='http://127.0.0.1:1')
                result=subprocess.run([sys.executable,str(ROOT/'mcp_server.py')],input='\n'.join(json.dumps(x,ensure_ascii=False) for x in messages)+'\n',text=True,encoding='utf-8',capture_output=True,env=env,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                self.assertEqual(result.returncode,0,result.stderr);rows=[json.loads(x) for x in result.stdout.splitlines()];self.assertEqual(len(rows),4);self.assertEqual(rows[0]['result']['serverInfo']['name'],'XingGou');self.assertEqual(len(rows[1]['result']['tools']),5);self.assertFalse(rows[2]['result'].get('isError'));self.assertIn('revision',json.loads(rows[3]['result']['content'][0]['text']))

if __name__=='__main__':unittest.main(verbosity=2)
