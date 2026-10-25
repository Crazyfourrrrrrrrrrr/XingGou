"""Static scenery export, with legacy decoration compatibility and TRS checks.

The encoder and wire reader are the pinned GPL-3.0 Miliastra-Tools sources.
Validation does not claim that a native editor accepted the generated file.
"""
import collections,datetime,hashlib,json,math,secrets,struct,sys,zipfile
from pathlib import Path
from .scene import flatten,validate
from .math3d import affine,combine
from .coordinates import native_object,reflected_affine
from .naming import export_label
from .branding import TOOL,VERSION

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor'/'miliastra_tools'))
from miliastra_core.export.decoration import build_decorated_gia,DecorationGroup
from miliastra_core.protobuf import wire as w

ENTITY=0x40400000
DECOR=0x40000000
MASK=0xfff00000
SLOTS=0xfffff

class ExportBlocked(ValueError):
    def __init__(self,blocked):
        super().__init__('场景含有未绑定游戏模板编号的模型；请绑定编号、隐藏这些物件，或先保存工程。')
        self.blocked=blocked

def payload(fields,container,kind,field):
    values=[]
    for f in fields:
        if f.number==container and f.wire_type==2:
            c=w.parse_fields(bytes(f.value))
            if w.first_varint(c,1)==kind:values.append(w.parse_fields(w.first_bytes(c,field) or b''))
    if len(values)!=1:raise ValueError(f'GIA 组件不唯一：{container}/{kind}')
    return values[0]

def transform(fields,container):
    p=payload(fields,container,1,11)
    def v(num,default):
        b=w.first_bytes(p,num)
        if b is None:return default
        fs=w.parse_fields(b)
        return [w.unpack_fixed32(w.first_field(fs,k,5)) or 0.0 for k in (1,2,3)]
    return dict(position=v(1,[0,0,0]),rotation=v(2,[0,0,0]),scale=v(3,[1,1,1]))

def check(blob,expected=None,*,expected_space='native'):
    if expected_space not in ('native','editor'):raise ValueError('Unknown expected coordinate space')
    if len(blob)<24 or int.from_bytes(blob[:4],'big')!=len(blob)-4 or int.from_bytes(blob[16:20],'big')!=len(blob)-24:raise ValueError('GIA 文件长度校验失败')
    if [int.from_bytes(blob[a:b],'big') for a,b in ((8,12),(12,16),(-4,len(blob)))]!=[0x326,3,0x679]:raise ValueError('GIA 类型或头尾标记错误')
    fields=w.parse_fields(blob[20:-4])
    if not any(f.number==2 and f.wire_type==2 for f in fields):
        from .static_gia import check_static_gia
        source=expected if expected_space=='editor' or expected is None else [native_object(o) for o in expected]
        result=check_static_gia(blob,source)
        result['expectedCoordinateSpace']=expected_space
        result['coordinateConversion']='passed' if expected is not None and expected_space=='editor' else 'not_checked'
        return result
    parents={};decs={};order=[]
    for f in w.parse_fields(blob[20:-4]):
        if f.number not in (1,2) or f.wire_type!=2:continue
        asset=w.parse_fields(bytes(f.value));meta=w.parse_fields(w.first_bytes(asset,1) or b'');ident=w.first_varint(meta,4)
        domain=ENTITY if f.number==1 else DECOR
        if not isinstance(ident,int) or ident&MASK!=domain or not ident&SLOTS:raise ValueError('GIA 原生编号段不正确')
        target=parents if f.number==1 else decs
        if ident in target:raise ValueError('GIA 编号重复')
        wrapper=w.parse_fields(w.first_bytes(asset,12 if f.number==1 else 21) or b'')
        core=w.parse_fields(w.first_bytes(wrapper,1) or b'')
        if w.first_varint(core,1)!=ident:raise ValueError('GIA 元数据与核心编号不一致')
        if f.number==1:
            if w.first_varint(asset,5)!=3:raise ValueError('GIA 父实体类型错误')
            ids=w.decode_packed_varints(w.first_bytes(payload(core,5,40,50),501) or b'')
            deps=[w.first_varint(w.parse_fields(bytes(x.value)),4) for x in asset if x.number==2 and x.wire_type==2]
            if ids!=deps or len(ids)!=len(set(ids)):raise ValueError('GIA 依赖与装饰物清单不一致')
            if w.first_varint(payload(core,5,1,11),2)==1:raise ValueError('场景父实体不能设为静态')
            if w.first_varint(payload(core,6,4,14),1)!=1:raise ValueError('场景父实体未开启初始创建')
            parents[ident]=dict(ids=ids,**transform(core,6))
        else:
            owner=w.first_varint(payload(core,4,40,50),502)
            c=payload(core,5,22,32)
            decs[ident]=dict(owner=owner,template_id=w.first_varint(core,2),custom_color_enabled=w.first_varint(c,1)==1,color=w.first_varint(c,5),**transform(core,5));order.append(ident)
    if not parents or not decs:raise ValueError('不能导出空场景')
    seen=collections.Counter()
    for pid,p in parents.items():
        for did in p['ids']:
            if did not in decs or decs[did]['owner']!=pid:raise ValueError('GIA 装饰物父级连接错误')
            seen[did]+=1
    if set(seen)!=set(decs) or any(v!=1 for v in seen.values()):raise ValueError('GIA 有孤立或重复装饰物')
    max_error=0.0
    if expected is not None:
        if len(expected)!=len(order):raise ValueError('GIA 数量与场景不一致')
        for ident,obj in zip(order,expected):
            dec=decs[ident]
            if dec['template_id']!=obj['template_id']:raise ValueError('GIA 模板编号与场景不一致')
            if dec['custom_color_enabled']!=obj.get('custom_color_enabled',False):raise ValueError('GIA 颜色启用状态不一致')
            if dec['custom_color_enabled']:
                rgb=obj['color']['rgb'];rgb=(rgb[0]<<16)|(rgb[1]<<8)|rgb[2]
                if dec['color']!=rgb:raise ValueError('GIA 颜色与场景不一致')
            actual=combine(affine(parents[dec['owner']]),dec)
            if expected_space=='editor':actual=reflected_affine(actual)
            wanted=affine(obj)
            flat=lambda a:[*a[1],*[v for row in a[0] for v in row]]
            for a,b in zip(flat(actual),flat(wanted)):
                err=abs(a-b);max_error=max(max_error,err)
                if err>max(0.0002,abs(b)*0.000002):raise ValueError('GIA 世界变换回读不一致')
    return dict(fileStructure='passed',nativeIdDomains='passed',parentChildLinks='passed',worldTransforms='passed' if expected is not None else 'not_checked',expectedCoordinateSpace=expected_space,coordinateConversion='passed' if expected is not None and expected_space=='editor' else 'not_checked',maxTransformError=max_error,parents=len(parents),components=len(decs),nativeEditorValidation='pending')

LEGACY_IMPORT_STEPS='''XingGou 星构工具箱场景导入说明（旧动态装饰包装模式）

1. 解压，保留 .gia 和导出报告；.starscene.json 可在 XingGou 星构工具箱继续编辑。
2. 将 .gia 放入原神 Beyond_Local_Export 文件夹，常见位置：
   %USERPROFILE%\\AppData\\LocalLow\\miHoYo\\原神\\BeyondLocal\\Beyond_Local_Export
3. 在千星奇域编辑器的“资产导入导出管理 → 加载外部资产”中加载。
4. 放置本文件的场景父实体。父级缩放为 0.01，子物件已经补偿，整体世界尺寸不变；不要手动把父级改成 1。超过 999 组件时保持各组原点和缩放一致。
5. 首次使用先导入 examples 中的坐标校准场景，检查方向、尺寸、材质与碰撞。

本文件引用游戏内的模板编号，不包含自定义 FBX/GLB 的上传。AI 新资产通过原生基元组合生成。
文件结构、编号、父子引用与变换已经本工具回读验证；游戏内实际接受情况仍需在原生编辑器检查。
角色、交互机关等模板的行为并不由本工具生成；这里的导出目标是装饰场景。
自定义编号绑定未经官方目录确认，会列在报告中。未知编号会导致游戏拒绝资产，请先做小规模导入测试。
工程坐标采用右手 Y-UP、度数、Rz·Ry·Rx；生成 GIA 时转换到游戏左手系。components.json 是工程坐标，native-components.json 是转换后的 GIA 世界坐标。
默认游戏地面为 Y=0。将场景放到其他地形时，请整体移动父实体，使基座高于原地面，避免共面闪烁。
预览材质为近似效果，特殊着色器以游戏实际效果为准。
'''

IMPORT_STEPS='''XingGou 星构工具箱静态布景导入说明

1. 解压，保留 .gia、.starscene.json 和检查报告。
2. 将 .gia 放入：
   %USERPROFILE%\\AppData\\LocalLow\\miHoYo\\原神\\BeyondLocal\\Beyond_Local_Export
3. 在千星编辑器“资产导入导出管理 → 加载外部资产”中载入。
4. 本文件包含独立静态单位，不使用动态父实体挂接模型。保留各物件写入的位置、旋转和缩放，不套用旧版父级 0.01 的操作。
5. 若要整体调整布局，请在编辑器多选这些静态物件一起移动，保持相对位置。当前已核对文件内的世界变换；具体原生批量放置流程与实际负载仍需实机确认。

固定布景默认静态导出。需要运动、组件、节点图或交互行为时，另行配置适用的动态单位；本文件不实现这些行为。
默认优先引用现有完整原生模型，保留原材质；手动制作的基元造型按各组件展开为静态单位。
未绑定模板编号会阻止导出，不猜测编号。原生水体和专有着色器的外部预览仅近似显示。
普通实体模板与已知字段来自固定版本 Miliastra-Tools；检查不等同于已测得游戏负载降幅。
components.json 使用工程右手 Y-UP 坐标，native-components.json 使用游戏左手 Y-UP 坐标。
'''

def export_scene(scene,catalog,directory,*,mode='static_entities'):
    if mode not in ('static_entities','decorations'):raise ValueError('不支持的 GIA 导出模式')
    scene=validate(scene,catalog);objects,blocked=flatten(scene,catalog)
    if blocked:raise ExportBlocked(blocked)
    if not objects:raise ValueError('请先在场景中放置可见物件')
    root=Path(directory);root.mkdir(parents=True,exist_ok=True)
    token=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3)
    folder=root/token;folder.mkdir()
    name=export_label(scene['name'],mode)
    # The native asset picker truncates long labels, so type/version come first.
    gia=folder/(name+'.gia')
    native=[native_object(o) for o in objects]
    start=lambda domain,n:domain+1+secrets.randbelow(SLOTS-n)
    if mode=='static_entities':
        from .static_gia import build_static_gia
        encoded=build_static_gia(native,gia,name,start(ENTITY,len(objects)))
        group_records=[]
        notes=['固定布景默认导出为独立静态单位，无动态父级和缩放补偿','保持各物件世界位置、旋转、缩放和碰撞设置','原生模板引用不上传外部网格','原生导入、批量放置与实际负载尚待复验']
    else:
        groups=[DecorationGroup(parent_position=(0,0,0),parent_scale=(.01,.01,.01),objects=tuple(native[i:i+999]),parent_name=f'{name} · {i//999+1:02d}') for i in range(0,len(native),999)]
        encoded=build_decorated_gia(objects=native,decoration_template_path=ROOT/'vendor/miliastra_tools/Template/GPT2Gia_decorations.gia',output_path=gia,max_per_parent=999,entity_id_start=start(ENTITY,len(groups)),decoration_id_start=start(DECOR,len(objects)),wrapper_static=False,wrapper_collision=False,wrapper_climb=False,decoration_groups=groups,wrapper_mode='SHRINK_HIDE',wrapper_hidden_scale=.01)
        group_records=[{k:p[k] for k in ('name','parent_id','position','rotation','scale','decoration_count')} for p in encoded['parents']]
        notes=['旧动态装饰包装兼容模式，不是固定布景的默认导出','父级缩放0.01且子变换补偿；仅此旧模式遵循父级缩放规则','原生编辑器负载需另行实测']
    checks=check(gia.read_bytes(),objects,expected_space='editor')
    used={o['asset_id'] for o in objects}
    bindings=[dict(assetId=a['id'],name=a['name'],templateId=a['templateId']) for a in catalog.assets if a['id'] in used and a.get('userBinding')]
    report=dict(tool=TOOL,version=VERSION,exportMode=mode,sceneName=scene['name'],createdAt=datetime.datetime.now(datetime.timezone.utc).isoformat(),visibleObjects=len([n for n in scene['nodes'] if n.get('visible',True)]),expandedComponents=len(objects),staticEntities=len(objects) if mode=='static_entities' else 0,dynamicEntities=len(group_records),decorationComponents=0 if mode=='static_entities' else len(objects),checks=checks,userBindings=bindings,sha256=hashlib.sha256(gia.read_bytes()).hexdigest(),groups=group_records,coordinates=dict(editor='Y_UP_RIGHT_HANDED',gia='Y_UP_LEFT_HANDED',mapping='position=(-x,y,z); rotation=(rx,-ry,-rz)'),notes=notes)
    def save(filename,value):
        (folder/filename).write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf-8')
    save(name+'.starscene.json',scene);save('export-report.json',report);save('components.json',objects);save('native-components.json',native)
    (folder/'导入说明.txt').write_text(IMPORT_STEPS if mode=='static_entities' else LEGACY_IMPORT_STEPS,'utf-8-sig')
    archive=root/(token+'.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in folder.iterdir():z.write(p,p.name)
    return dict(url='/download/'+archive.name,filename=name+'.zip',giaUrl='/download/'+token+'/'+gia.name,report=report)
