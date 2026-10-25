import copy,json,math,re,uuid,threading
from pathlib import Path
from .math3d import combine,decompose

SCHEMA='starscene/1'
def uid(prefix='n'):return prefix+'_'+uuid.uuid4().hex[:12]
def empty(name='未命名场景'):
    return dict(schema=SCHEMA,name=name,nodes=[],definitions={},settings=dict(snap=1,rotateSnap=15),design=None)

def vec(value,default,scale=False):
    v=default if value is None else value
    if not isinstance(v,(list,tuple)) or len(v)!=3 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in v):raise ValueError('三维参数必须由三个有限数字组成')
    if scale and any(x<.001 or x>10000 for x in v):raise ValueError('缩放必须在 0.001–10000 之间')
    if any(abs(x)>1000000 for x in v):raise ValueError('位置/角度超出本工具可处理范围')
    return list(map(float,v))

def validate(scene,catalog):
    if not isinstance(scene,dict) or scene.get('schema')!=SCHEMA:raise ValueError('请打开 StarScene 工程（starscene/1）')
    s=copy.deepcopy(scene);defs=s.get('definitions',{})
    if not isinstance(defs,dict) or len(defs)>300:raise ValueError('自定义资产数量超出本工具预算')
    if not isinstance(s.get('nodes'),list) or len(s['nodes'])>5000:raise ValueError('本工具单工程最多 5000 个对象')
    seen=set()
    def node(n):
        if not isinstance(n,dict):raise ValueError('物件必须为对象')
        if not isinstance(n.get('id'),str) or not n['id'] or len(n['id'])>100:raise ValueError('物件缺少唯一标识')
        a=str(n.get('assetId',''))
        if a not in catalog.by_id and a not in defs:raise ValueError('未找到资产：'+a)
        n['assetId']=a;n['name']=str(n.get('name',catalog.by_id.get(a,{}).get('name',a)))[:160]
        n['position']=vec(n.get('position'),[0,0,0]);n['rotation']=vec(n.get('rotation'),[0,0,0]);n['scale']=vec(n.get('scale'),[1,1,1],True)
        n['visible']=bool(n.get('visible',True));n['locked']=bool(n.get('locked',False));n['layer']=str(n.get('layer','场景'))[:80]
        if n.get('color') and not re.fullmatch(r'#[0-9a-fA-F]{6}',n['color']):raise ValueError('颜色须为 #RRGGBB')
        if n.get('color') and a in catalog.by_id and not catalog.by_id[a].get('primitive'):raise ValueError('本工具仅支持原生基元调色，请保留原生模型材质')
    for key,d in defs.items():
        if not isinstance(d,dict) or not isinstance(d.get('components'),list) or not 1<=len(d['components'])<=999:raise ValueError('组合物件需包含 1–999 个组件')
        if key in catalog.by_id:raise ValueError('自定义资产不能覆盖游戏物件')
        for c in d['components']:node(c)
    for n in s['nodes']:
        node(n)
        if n['id'] in seen:raise ValueError('场景物件标识重复')
        seen.add(n['id'])
    heights={}
    def acyclic(k,stack):
        if k in stack:raise ValueError('自定义资产出现循环引用')
        if len(stack)>8:raise ValueError('组合层级过深')
        if k in heights:return heights[k]
        if k in defs:
            h=1+max(acyclic(c['assetId'],stack+[k]) for c in defs[k]['components'])
            if h>8:raise ValueError('组合层级过深')
            heights[k]=h;return h
        return 0
    for k in defs:acyclic(k,[])
    s['name']=str(s.get('name','未命名场景'))[:120];s['definitions']=defs
    settings=s.get('settings') or {}
    if not isinstance(settings,dict):raise ValueError('工程设置无效')
    for k,default,lo,hi in [('snap',1,0,100),('rotateSnap',15,1,180)]:
        v=settings.get(k,default)
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not lo<=v<=hi:raise ValueError('吸附设置无效')
        settings[k]=v
    floor=settings.get('groundHeight',0)
    if isinstance(floor,bool) or not isinstance(floor,(int,float)) or not math.isfinite(floor) or abs(floor)>1000000:raise ValueError('地面高度无效')
    settings['groundHeight']=floor
    s['settings']=settings
    return s

def flatten(scene,catalog):
    s=validate(scene,catalog);out=[];blocked=[];visited=0
    def visit(n,parent=None,path='',depth=0,root_id=None):
        nonlocal visited
        visited+=1
        if visited>25000:raise ValueError('展开后的场景超过本工具预算，请分场景导出')
        if not n.get('visible',True):return
        root_id=root_id or n['id']
        transform=combine(parent,n);key=n['assetId'];name=path+n['name']
        if key in s['definitions']:
            for c in s['definitions'][key]['components']:visit(c,transform,name+' / ',depth+1,root_id)
            return
        a=catalog.by_id[key]
        if not a['templateId']:blocked.append(dict(id=root_id,componentId=n['id'],name=name,assetId=key));return
        item=dict(name=name[:180],template_id=a['templateId'],asset_id=key,source_id=n['id'],**decompose(transform),custom_color_enabled=bool(n.get('color')),collision=bool(n.get('collision',True)),climb=False)
        if n.get('color'):item['color']={'rgb':[int(n['color'][j:j+2],16) for j in (1,3,5)],'opacity':100}
        out.append(item)
        if len(out)>12000:raise ValueError('展开后的场景超过本工具 12000 组件预算，请分场景导出')
    for n in s['nodes']:visit(n)
    return out,blocked

class ProjectStore:
    def __init__(self,root,catalog):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.path=self.root/'current.starscene.json';self.catalog=catalog;self.lock=threading.RLock();self.rev=0;self.source='startup'
        self.scene=validate(json.loads(self.path.read_text('utf-8')),catalog) if self.path.is_file() else empty()
    def get(self):
        with self.lock:return dict(project=copy.deepcopy(self.scene),revision=self.rev,source=self.source)
    def put(self,scene,revision=None,source='web'):
        s=validate(scene,self.catalog)
        with self.lock:
            if revision is not None and revision!=self.rev:raise RuntimeError('工程已被另一端更新，请重新载入后继续')
            tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(s,ensure_ascii=False,indent=2),'utf-8');tmp.replace(self.path)
            self.scene=s;self.rev+=1;self.source=source;return self.get()
