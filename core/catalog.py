"""Index a user-owned, external library; game files never live in this repository."""
import json,os,re,threading
from pathlib import Path
from .branding import environment

ROOT=Path(__file__).resolve().parents[1]
PRIMITIVES={10009001:('长方体','box'),10009002:('球体','sphere'),10009003:('平面','plane'),10009004:('三棱柱','prism3'),10009005:('五棱柱','prism5'),10009006:('三棱锥','pyramid3'),10009007:('五棱锥','pyramid5'),10009008:('圆柱','cylinder'),10009009:('圆锥','cone'),10009010:('线框长方体','wirebox'),10009011:('线框圆柱','wirecylinder')}
TAGS={'建筑':['House','Build','Minju','Huishi','ShenShe','房屋','建筑','塔楼','门楼'],'植被':['Tree','Grass','Flower','Plant','Lvy','灌木','乔木','花丛','树'],'岩石':['Rock','Stone','岩石','石块'],'道路':['Road','Path','道路','地板','楼梯'],'机关':['Prop','交互机关','挑战装置'],'地块':['Tile','地块'],'生物':['Monster','Animal','生物']}

class Catalog:
    def __init__(self,path=None):
        config=ROOT/'config.local.json'
        local=json.loads(config.read_text('utf-8-sig')) if config.is_file() else {}
        raw=path or environment('ASSET_ROOT') or local.get('assetRoot') or '../Miliastra-Asset-Library'
        self.root=(ROOT/raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
        self.path=ROOT/'projects'/'bindings.json';self.path.parent.mkdir(exist_ok=True)
        self.bindings=json.loads(self.path.read_text('utf-8')) if self.path.is_file() else {}
        self.assets=[];self.by_id={};self.by_template={};self.lock=threading.RLock();self.available=False
        self.load()

    def load(self):
        inventory=self.root/'inventory.json';master=self.root/'master-verification.json'
        if inventory.is_file():
            rows=json.loads(inventory.read_text('utf-8-sig'))
            stats={x['internal_name']:x for x in json.loads(master.read_text('utf-8-sig'))['assets']} if master.is_file() else {}
            grouped={}
            for r in rows:
                if not r.get('glb'):continue
                grouped.setdefault(r['internal_name'],[]).append(r)
            for internal,group in grouped.items():
                r=group[0];ident=str(r['id']);data=stats.get(internal,{})
                ids=[str(x['id']) for x in group if isinstance(x.get('id'),int)]
                size=data.get('dimensions_in_blender',[1,1,1]);size=[size[0],size[2],size[1]]
                searchable=' '.join([internal,*[str(x.get('name','')) for x in group],*ids])
                tags=[tag for tag,terms in TAGS.items() if any(t.casefold() in searchable.casefold() for t in terms)]
                a=dict(id=ident,name=r['name'],category=r['group'],internalName=internal,aliases=[dict(id=str(x['id']),name=x['name']) for x in group],templateId=int(ids[0]) if ids else None,tags=tags,dimensions=size,triangles=data.get('total_triangles',r.get('triangles',0)),modelUrl='/models/'+ident+'.glb',glb=r['glb'],warnings=r.get('warnings',[]),primitive=None)
                if ids and int(ids[0]) in PRIMITIVES:a['primitive']=PRIMITIVES[int(ids[0])][1]
                # Extraction retained a sample instance translation for water.
                # This correction only affects the external mesh preview;
                # GIA references the untouched native template and node TRS.
                water_ids=set(ids)&{'10005106','10005107','10005108'}
                if water_ids:
                    offset=14.239 if '10005108' in water_ids else 8.710000038
                    a.update(previewOffset=[offset,0,0],previewMaterial='water',previewNote='原生水体；外部水材质近似，游戏内效果待验证')
                self.assets.append(a)
            self.available=True
        for tid,(name,kind) in PRIMITIVES.items():
            if not any(a['id']==str(tid) for a in self.assets):self.assets.append(dict(id=str(tid),name=name,category='几何体',internalName='primitive_'+kind,aliases=[],templateId=tid,tags=['基元'],dimensions=[1,1,1],triangles=0,modelUrl=None,glb=None,warnings=[],primitive=kind))
        self.assets.sort(key=lambda a:(a['category'],a['name'],a['id']))
        for a in self.assets:
            if a['id'] in self.bindings:a['templateId']=int(self.bindings[a['id']]);a['userBinding']=True
            a['exportable']=bool(a['templateId']);self.by_id[a['id']]=a
            for alias in a['aliases']:self.by_id.setdefault(alias['id'],a)
            if a['templateId']:self.by_template.setdefault(a['templateId'],a)

    def public(self,a):return {k:v for k,v in a.items() if k not in ('glb',)}
    def all(self):return [self.public(a) for a in self.assets]
    def search(self,query='',category='',ready=False,limit=60):
        tokens=[x.casefold() for x in re.split(r'[\s,，]+',query.strip()) if x]
        ranked=[]
        for a in self.assets:
            if category and category not in (a['category'],*a['tags']):continue
            if ready and not a['exportable']:continue
            text=' '.join([a['id'],a['name'],a['internalName'],a['category'],*a['tags'],*[x['name'] for x in a['aliases']]]).casefold()
            score=sum(4 if t in a['name'].casefold() else 1 for t in tokens if t in text)
            if tokens and not score:continue
            ranked.append((score,a))
        ranked.sort(key=lambda v:-v[0])
        return [self.public(a) for _,a in ranked[:max(1,min(500,int(limit)))]]
    def model_path(self,ident):
        a=self.by_id.get(str(ident))
        if not a or not a.get('glb'):raise FileNotFoundError('模型文件不存在')
        p=(self.root/a['glb']).resolve()
        if not p.is_relative_to(self.root) or not p.is_file():raise FileNotFoundError('模型路径无效')
        return p
    def bind(self,ident,tid):
        if str(ident) not in self.by_id:raise ValueError('未找到这个模型')
        if isinstance(tid,bool) or not isinstance(tid,int) or not 1<=tid<=0xffffffff:raise ValueError('模板编号必须是有效的整数')
        with self.lock:
            a=self.by_id[str(ident)];self.bindings[a['id']]=tid;tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(self.bindings,ensure_ascii=False,indent=2),'utf-8');tmp.replace(self.path)
            a.update(templateId=tid,exportable=True,userBinding=True);self.by_template[tid]=a
        return self.public(a)
