"""Two-stage design generation; offline recipes and a real compatible chat API."""
import copy,hashlib,json,math,os,random,re,threading,urllib.error,urllib.request,urllib.parse
from pathlib import Path
from .scene import empty,uid,validate
from .branding import environment

def node(asset,name,position=(0,0,0),scale=(1,1,1),rotation=(0,0,0),color=None,layer='场景'):
    n=dict(id=uid(),assetId=str(asset),name=name,position=list(position),scale=list(scale),rotation=list(rotation),visible=True,locked=False,layer=layer)
    if color:n['color']=color
    return n

def recipe(idea,kind=None):
    kinds={'bridge':['桥','bridge'],'arch':['门','拱','arch'],'well':['井','well'],'tower':['塔','tower'],'stall':['摊','棚','stall']}
    kind=kind or next((k for k,terms in kinds.items() if any(t in idea.casefold() for t in terms)),'arch')
    if kind not in kinds:raise ValueError('离线配方支持木桥、拱门、水井、瞭望塔、集市摊位；其他造型请使用模型接口')
    cs=[];wood='#805c40';stone='#a5aa9e';dark='#4f5d52';cloth='#b55b43'
    def box(name,p,s,color=wood,r=(0,0,0)):cs.append(node('10009001',name,p,s,r,color))
    def cylinder(name,p,s,color=stone,r=(0,0,0)):cs.append(node('10009008',name,p,s,r,color))
    if kind=='bridge':
        for i in range(16):box(f'桥面木板 {i+1}',(0,.4,-5.625+i*.75),(4,.22,.69))
        for x in (-1.85,1.85):
            for z in (-5.5,-3.3,-1.1,1.1,3.3,5.5):box('桥栏立柱',(x,1.0,z),(.16,1.5,.16),dark)
            box('扶手',(x,1.7,0),(.2,.18,11.5),dark)
        name='溪上木桥';description='16 块桥板和两侧护栏，沿 Z 轴跨越。'
    elif kind=='arch':
        for x in (-2.6,2.6):
            box('柱基',(x,.3,0),(1.4,.6,1.4),stone);box('立柱',(x,2.6,0),(.72,4.2,.72),dark)
            box('柱帽',(x,4.8,0),(1.05,.3,1.05),wood)
        box('横梁',(0,5.0,0),(7,.45,1),wood)
        box('上檐左',(-1.6,5.6,0),(3.6,.3,1.5),cloth,(0,0,9));box('上檐右',(1.6,5.6,0),(3.6,.3,1.5),cloth,(0,0,-9))
        box('牌匾',(0,4.4,-.55),(1.7,.8,.15),wood)
        name='山林迎客门';description='双柱、飞檐和牌匾组成的入口。'
    elif kind=='well':
        for i in range(12):
            a=math.tau*i/12;cylinder('井壁石段',(math.cos(a)*1.1,.55,math.sin(a)*1.1),(.55,1.1,.55))
        for x in (-1.6,1.6):box('支架',(x,1.7,0),(.25,3.4,.25))
        box('横梁',(0,3.25,0),(3.6,.25,.3));cylinder('卷轴',(0,2.7,0),(.24,3.2,.24),wood,(0,0,90))
        box('井水',(0,.2,0),(1.5,.1,1.5),'#579f9d');name='林间水井';description='石砌井圈、木支架和卷轴。'
    elif kind=='tower':
        for x in (-2,2):
            for z in (-2,2):box('塔脚',(x,3.5,z),(.45,7,.45),dark)
        box('观景平台',(0,6.5,0),(5,.4,5))
        for x in (-2.3,2.3):box('护栏',(x,7.25,0),(.2,1,5),dark)
        for z in (-2.3,2.3):box('护栏',(0,7.25,z),(5,1,.2),dark)
        for i in range(12):box('梯阶',(0,.3+i*.5,2.9-i*.06),(1.3,.16,.38))
        cs.append(node('10009009','尖顶',(0,9,0),(6,2.6,6),color=cloth))
        name='木质瞭望塔';description='四根塔脚、平台、梯阶和锥形顶。'
    else:
        for x in (-1.8,1.8):
            for z in (-1,1):box('棚柱',(x,1.5,z),(.16,3,.16),dark)
        box('货台',(0,1,0),(3.6,.3,1.8));box('布棚左',(-1,3.2,0),(2.3,.12,2.8),cloth,(0,0,12));box('布棚右',(1,3.2,0),(2.3,.12,2.8),cloth,(0,0,-12))
        for x in (-1,0,1):box('陈列箱',(x,1.45,0),(.7,.6,.7),wood)
        name='林间集市摊位';description='布篷、货台与陈列箱。'
    return dict(id='custom_'+uid('asset'),name=name,description=description,components=cs,origin='offline',prompt=idea)

FEATURE_WORDS={
    'bridge':('桥','bridge','qiao_'),
    'arch':('拱门','门楼','牌坊','鸟居','入口','山门','arch','paifang'),
    'well':('水井','井','well'),
    'tower':('瞭望塔','塔楼','木塔','tower'),
    'stall':('摊位','摊棚','棚','集市','货摊','stall','lowshop'),
    'road':('石路','道路','步道','石径','road'),
    'water':('水体','水面','溪流','河流','waterobject'),
}
FEATURE_IDS={
    'bridge':('20002204','20001522','20002195','20002628'),
    'arch':('20002217','20002400'),
    'well':('20002112','20002007'),
    'tower':(),
    'stall':('20001125','20001809','20002428','20002520'),
    'road':('20001073','20001052','20001053'),
    'water':('10005106','10005107','10005108'),
}
PRIMITIVE_IDS={str(i) for i in range(10009001,10009012)}

def is_native_model(asset):
    """Check the resolved template too: aliases must not bypass the policy."""
    return bool(asset and asset.get('exportable') and asset.get('templateId')
                and not asset.get('primitive') and str(asset['templateId']) not in PRIMITIVE_IDS)

def native_candidates(kind,catalog):
    eligible=[a for a in catalog.assets if is_native_model(a)]
    preferred=[a for ident in FEATURE_IDS.get(kind,()) for a in eligible if a['id']==ident]
    words=FEATURE_WORDS.get(kind,())
    other=[a for a in eligible if a not in preferred and any(w.casefold() in (a['name']+' '+a.get('internalName','')).casefold() for w in words)]
    return preferred+other

def feature_kind(idea):
    text=str(idea).casefold()
    return next((k for k,words in FEATURE_WORDS.items() if any(w.casefold() in text for w in words)),None)

def native_matches(idea,catalog,limit=12):
    """Return actual catalog entries, never inferred IDs or primitive stand-ins."""
    text=str(idea).strip().casefold()
    exact=[a for a in catalog.assets if is_native_model(a) and (a['id']==text or a['name'].casefold()==text or a.get('internalName','').casefold()==text)]
    if exact:return exact[:limit]
    # A role mentioned in the background is not the requested object. Nor is
    # an ordinary bridge a match for a new spiral/mechanical sculptural shape.
    # Require unusual shape constraints to exist in the actual catalog text.
    constraints=re.findall(r'独特|自定义|螺旋|旋转|机械|巨龙|鲸鱼|星形|雕塑|(?:双|三|四|五|六|七|八|九|十|\d+)(?:层|头|翼)',text)
    eligible=[a for a in catalog.assets if is_native_model(a)]
    if constraints:
        def supports(a):
            metadata=(a['name']+' '+a.get('internalName','')+' '+' '.join(x['name'] for x in a.get('aliases',[]))).casefold()
            return all(term in metadata for term in constraints)
        eligible=[a for a in eligible if supports(a)]
        if not eligible:return []
    kind=feature_kind(text)
    if kind:
        rows=[a for a in native_candidates(kind,catalog) if a in eligible]
        for material in ('木质','石质','金属'):
            if material in text:rows=[a for a in rows if material in a['name']]
        return rows[:limit]
    names=[a for a in eligible if len(a['name'])>=2 and a['name'].casefold() in text]
    names.sort(key=lambda a:-len(a['name']))
    if names:return names[:limit]
    return [catalog.by_id[a['id']] for a in catalog.search(str(idea),ready=True,limit=limit) if catalog.by_id[a['id']] in eligible]

def bounded_plan(plan):
    if not isinstance(plan,dict):raise ValueError('设计草案必须是 JSON 对象')
    p=copy.deepcopy(plan)
    def number(k,default,lo,hi):
        value=p.get(k,default)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('草案参数无效：'+k)
        p[k]=int(max(lo,min(hi,value)))
    for args in [('width',64,24,200),('depth',64,24,200),('buildings',4,0,30),('trees',20,0,160),('rocks',8,0,80),('seed',42,0,2147483647)]:number(*args)
    p['theme']=str(p.get('theme','village'))[:40];p['title']=str(p.get('title','林溪营地'))[:80];p['summary']=str(p.get('summary',''))[:1200]
    kinds=p.get('nativeFeatures',p.get('customAssets',[]))
    if not isinstance(kinds,list):raise ValueError('草案 nativeFeatures 必须为列表')
    p.pop('customAssets',None)
    p['water']=bool(p.get('water',False));p['nativeFeatures']=list(dict.fromkeys(k for k in kinds if k in ('bridge','arch','well','tower','stall')))[:8]
    p['assetPolicy']='native-only'
    zones=p.get('zones',[])
    p['zones']=[dict(name=str(z.get('name','区域'))[:80],purpose=str(z.get('purpose',''))[:200]) for z in zones[:8] if isinstance(z,dict)] if isinstance(zones,list) else []
    return p

def offline_plan(idea):
    idea=str(idea).strip()
    if not idea:raise ValueError('先写下你的场景想法')
    theme='ruins' if any(x in idea for x in ('遗迹','废墟','神殿')) else 'camp' if '帐篷' in idea or '营地' in idea and not any(x in idea for x in ('木屋','房屋','村')) else 'market' if any(x in idea for x in ('集市','城镇','市集')) else 'village'
    size=96 if any(x in idea for x in ('大型','辽阔','大场景')) else 48 if any(x in idea for x in ('小型','小巧','迷你')) else 64
    water=any(x in idea for x in ('河','溪','水','桥','湖'))
    houses=re.search(r'(\d+)\s*(?:栋|座|间|个)\s*(?:木质|石质|木|石)?(?:房屋|房|屋|建筑|帐篷)',idea)
    kinds=[k for k,terms in {'arch':['门','拱'],'well':['井'],'tower':['塔'],'stall':['摊','集市']}.items() if any(t in idea for t in terms)]
    if water:kinds.insert(0,'bridge')
    if not kinds:kinds=['arch']
    title={'ruins':'林荫旧迹','camp':'林溪营地','market':'山间集市','village':'溪畔小聚'}[theme]
    return bounded_plan(dict(title=title,theme=theme,summary='沿原生石路组织建筑，两侧保留植被缓冲；'+('优先使用原生水体和桥梁连接两岸，水体效果需在游戏中核对。' if water else '原生入口与中心节点建立游览动线。'),width=size,depth=size,buildings=int(houses.group(1)) if houses else (6 if theme=='market' else 4),trees=28 if '森林' in idea or '密林' in idea else 18,rocks=8,water=water,seed=int(hashlib.sha256(idea.encode()).hexdigest()[:7],16),zones=[dict(name='入口',purpose='从现有完整门楼中选用，保留原生模型'),dict(name='生活区' if theme!='ruins' else '遗迹区',purpose='原生建筑沿步道错落分布'),dict(name='自然缓冲',purpose='树木与岩石避让主路和建筑')],nativeFeatures=kinds,prompt=idea,mode='offline'))

def offline_scene(plan,catalog):
    p=bounded_plan(plan);rng=random.Random(p['seed']);s=empty(p['title']);s['design']=p
    w,d=p['width'],p['depth'];ns=s['nodes'];occupied=[];notes=[]
    native=[a for a in catalog.assets if is_native_model(a)]
    # The existing native terrain is the floor. A box is not a substitute for
    # an unbound terrain tile, and an absent model is never a whitebox fallback.
    s['settings']['groundHeight']=0
    houses=[a for a in native if ('帐篷' in a['name'] if p['theme']=='camp' else '石质' in a['name'] and ('房屋' in a['name'] or '遗迹' in a['name']) if p['theme']=='ruins' else a['name']=='木质房屋') and 4<max(a['dimensions'][::2])<16]
    if p['theme'] in ('village','market'):
        preferred=[a for a in houses if a['id'] in ('20002061','20002062','20002064','20002078','20002218','20002219')]
        if preferred:houses=preferred
    trees=[a for a in native if a['name']=='乔木' and 5<a['dimensions'][1]<13 and max(a['dimensions'][::2])<12 and any(k in a['internalName'] for k in ('SongShu','Fs_','QiaoMu','Arbor'))]
    rocks=[a for a in native if a['name'] in ('岩石','石块') and 1<max(a['dimensions'])<7]
    preferred=[a for a in rocks if any(k in a['internalName'] for k in ('Rock_A_','Rock_Full_','Rock_Quarry'))]
    if preferred:rocks=preferred
    if not trees:trees=[a for a in native if '植被' in a['tags']][:10]
    if p['buildings'] and not houses:notes.append('缺少符合主题的原生房屋：保留建筑区域，未用基元替代。')
    if p['trees'] and not trees:notes.append('缺少原生树木：未放置白模树。')
    if p['rocks'] and not rocks:notes.append('缺少原生岩石：未放置白模岩石。')
    def place_native(a,name,x,z,target,angle,layer):
        k=target/max(.1,max(a['dimensions'][::2]));ns.append(node(a['id'],name,(x,0,z),(k,k,k),(0,angle,0),layer=layer));return target*.58
    count=p['buildings'];rows=max(1,math.ceil(count/2));spacing=min(14,(d-16)/rows)
    for i in range(count):
        x=(-1 if i%2==0 else 1)*(w*.24);z=(i//2-(rows-1)/2)*spacing
        if p['water'] and abs(z)<10:z+=11 if z>=0 else -11
        target=min(9,w*.19,spacing*.77)
        if houses:
            a=rng.choice(houses);r=place_native(a,f'{a["name"]} {i+1}',x,z,target,90 if x<0 else -90,'建筑')
        else:continue
        occupied.append((x,z,r))
    for i in range(p['trees']):
        for attempt in range(150):
            x=rng.uniform(-w*.46,w*.46);z=rng.uniform(-d*.46,d*.46)
            if abs(x)<6 or p['water'] and abs(z)<6 or any(math.hypot(x-a,z-b)<r+2 for a,b,r in occupied):continue
            break
        else:continue
        if trees:place_native(rng.choice(trees),f'林木 {i+1}',x,z,rng.uniform(3.7,6.0),rng.uniform(0,360),'自然')
        else:continue
        occupied.append((x,z,1.7))
    for i in range(p['rocks']):
        x=rng.choice((-1,1))*rng.uniform(w*.35,w*.46);z=rng.uniform(-d*.44,d*.44)
        if rocks:place_native(rng.choice(rocks),f'岩石 {i+1}',x,z,rng.uniform(1.3,2.7),rng.uniform(0,360),'自然')
    features=p['nativeFeatures'];bridge_half=0
    for i,kind in enumerate(features):
        choices=native_candidates(kind,catalog)
        if not choices:notes.append(f'缺少可导出的原生{dict(bridge="桥梁",arch="门楼",well="水井",tower="塔楼",stall="摊位")[kind]}：已保留需求，未自动拼搭。');continue
        a=choices[0];pos=(0,0,d*.42) if kind=='arch' else (w*.34,0,-d*.32) if kind=='tower' else (7+i*5,0,-d*.31)
        scale=(1,1,1);angles=(0,0,0)
        if kind=='bridge':
            k=14.56/max(a['dimensions'][::2]);scale=(k,k,k);angles=(0,90 if a['dimensions'][0]>a['dimensions'][2] else 0,0)
            # Qiao_04's end deck is Y=1.558 in its original model; bury
            # the supports so each complete bridge end meets native ground.
            pos=(0,-1.558*k if a['id']=='20002204' else 0,0);bridge_half=7.28
        elif a['id']=='20001125':pos=(pos[0],.09706,pos[2])
        ns.append(node(a['id'],a['name'],pos,scale,angles,layer='原生设施'))
    roads=native_candidates('road',catalog)
    if roads:
        a=roads[0];k=.7 if a['id']=='20001073' else 4.5/max(.1,a['dimensions'][0]);length=a['dimensions'][2]*k
        offset_x=-.03814 if a['id']=='20001073' else 0;offset_z=-.19103 if a['id']=='20001073' else 0
        gap=bridge_half if bridge_half else 4.3 if p['water'] else 0
        if gap:
            side_length=max(0,d/2-2-gap);count=max(1,round(side_length/length)) if side_length else 0
            for sign in (-1,1):
                for i in range(count):
                    center=sign*(gap+length/2+i*(length-.14))
                    ns.append(node(a['id'],'原生石路',(offset_x,0,center+offset_z),(k,k,k),layer='道路'))
        else:
            count=max(1,math.ceil((d-4)/length))
            for i in range(count):ns.append(node(a['id'],'原生石路',(offset_x,0,(i-(count-1)/2)*(length-.14)+offset_z),(k,k,k),layer='道路'))
    else:notes.append('缺少可导出的原生道路：保留通行区域，未用基元铺路。')
    if p['water']:
        waters=native_candidates('water',catalog)
        if waters:
            a=waters[0]
            if a['id']=='10005106':ns.append(node(a['id'],'原生浅水带',(0,.02,0),(w,.08,7.7),layer='原生水体'))
            else:ns.append(node(a['id'],a['name'],layer='原生水体'))
            notes.append('已引用原生水体；网页水材质仅近似显示，浅水带的游戏内效果需复验。深河道需在原生地形工具中开挖。')
        else:notes.append('缺少可导出的原生水体：保留溪流区域，未使用蓝色白模代替。')
    notes.append('沿用游戏已有地面；原始地块编号未确认，不生成白模基座。')
    s['design']['notes']=notes
    return validate(s,catalog)

class Provider:
    def __init__(self,root):
        self.file=Path(root)/'provider.local.json';self.lock=threading.RLock()
        c=json.loads(self.file.read_text('utf-8')) if self.file.is_file() else {}
        self.base=environment('AI_BASE_URL',c.get('baseUrl','http://localhost:11434/v1'))
        self.model=environment('AI_MODEL',c.get('model',''));self.key=environment('AI_KEY','');self.json_mode=c.get('jsonMode',True)
        self.token_parameter=c.get('tokenParameter','max_tokens');self.max_tokens=c.get('maxTokens',12000)
    def status(self):
        with self.lock:return dict(baseUrl=self.base,model=self.model,hasKey=bool(self.key),jsonMode=self.json_mode,tokenParameter=self.token_parameter,maxTokens=self.max_tokens)
    def configure(self,c):
        with self.lock:
            if c.get('clearKey') and set(c)=={'clearKey'}:self.key='';return self.status()
            base=str(c.get('baseUrl',self.base)).strip().rstrip('/');model=str(c.get('model',self.model)).strip()
            u=urllib.parse.urlsplit(base)
            if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.query or u.fragment:raise ValueError('接口地址须为 http(s) URL，例如 http://localhost:11434/v1')
            if not model:raise ValueError('请填写模型名称')
            token_parameter=c.get('tokenParameter',self.token_parameter);limit=c.get('maxTokens',self.max_tokens)
            if token_parameter not in ('max_tokens','max_completion_tokens'):raise ValueError('输出长度参数无效')
            if isinstance(limit,bool) or not isinstance(limit,int) or not 1024<=limit<=32768:raise ValueError('输出 token 上限应在 1024–32768 之间')
            self.base=base;self.model=model;self.json_mode=bool(c.get('jsonMode',True))
            self.token_parameter=token_parameter;self.max_tokens=limit
            if 'apiKey' in c and c['apiKey']:
                key=str(c['apiKey']).strip()
                if len(key)>8192 or '\n' in key or '\r' in key:raise ValueError('密钥过长或包含换行')
                self.key=key
            if c.get('clearKey'):self.key=''
            self.file.parent.mkdir(exist_ok=True)
            self.file.write_text(json.dumps({k:v for k,v in self.status().items() if k!='hasKey'},ensure_ascii=False,indent=2),'utf-8')
            return self.status()
    def ask(self,system,data):
        with self.lock:base,model,key,json_mode,token_parameter,limit=self.base,self.model,self.key,self.json_mode,self.token_parameter,self.max_tokens
        if not model:raise ValueError('请先配置模型名称，或切换离线配方模式')
        body=dict(model=model,messages=[dict(role='system',content=system),dict(role='user',content=json.dumps(data,ensure_ascii=False))]);body[token_parameter]=limit
        if json_mode:body['response_format']={'type':'json_object'}
        headers={'Content-Type':'application/json','Accept':'application/json'}
        if key:headers['Authorization']='Bearer '+key
        endpoint=base if base.endswith('/chat/completions') else base+'/chat/completions'
        req=urllib.request.Request(endpoint,data=json.dumps(body).encode(),headers=headers,method='POST')
        try:
            # Direct requests keep local-model traffic out of machine proxy settings.
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=120) as r:
                raw=r.read(4_000_001)
                if len(raw)>4_000_000:raise ValueError('模型响应超过 4 MB')
                response=json.loads(raw)
        except urllib.error.HTTPError as e:
            # Never echo provider bodies: they can include request data or secrets.
            raise ValueError(f'模型接口返回 HTTP {e.code}；检查地址、模型、密钥和 JSON 模式') from e
        except (urllib.error.URLError,TimeoutError,OSError) as e:raise ValueError('无法连接模型接口或请求超时；检查服务是否运行与接口地址') from e
        try:
            choice=response['choices'][0]
            if choice.get('finish_reason')=='length':raise ValueError('模型输出达到长度上限；请在设置中调大输出 token 上限，或减少物件数量')
            if choice['message'].get('refusal'):raise ValueError('模型拒绝了这次生成，请调整描述')
            content=choice['message']['content']
        except (KeyError,IndexError,TypeError) as e:raise ValueError('接口响应缺少 choices[0].message.content') from e
        if not isinstance(content,str):raise ValueError('模型须返回 JSON 文本')
        content=re.sub(r'^\s*```(?:json)?\s*','',content);content=re.sub(r'\s*```\s*$','',content)
        try:return json.loads(content)
        except json.JSONDecodeError as e:raise ValueError('模型没有返回有效 JSON，请启用 JSON 模式或换用支持结构化输出的模型') from e

PLAN_SYSTEM='''你是千星场景设计师。仅返回 JSON，不写代码。优先复用千星已有的完整原生资产，不能用白模/基元拼搭替代现成资源。将想法转成可审核草案。字段：title 中文名, summary 设计思路, theme(village/camp/market/ruins), width/depth 24..200, buildings 0..30, trees 0..160, rocks 0..80, water 布尔, seed 整数, zones [{name,purpose}], nativeFeatures [bridge/arch/well/tower/stall]（这是检索完整原生模型的需求，不是基元配方）。缺资源留为待补充项。保留用户约束，不许声称已在游戏中创建。'''
SCENE_SYSTEM='''你是千星外部场景设计师。仅返回 starscene/1 JSON 工程，不写代码。字段 schema="starscene/1",name,nodes,definitions。nodes每项{id唯一字符串,assetId字符串,name,position:[x,y,z],rotation:[x,y,z],scale:[x,y,z],layer}。Y向上，旋转度数 Rz*Ry*Rx，默认现有地面Y=0。仅使用给定目录里的完整原生模型；禁止10009001..10009011、基元别名、白模及由基元组成的definitions。模型、材质保持原样，不添加color。可以用definitions给完整原生资产分组，不能借分组绕过基元禁用。桥、入口、摊位、道路都先选已有模型。目录没有的地形或独特造型，省略并通过notes字符串列表列出缺项，不要用盒子假装。水体仅选真实WaterObject模板，外部材质近似、游戏效果需核对；深河道留给游戏地形工具。最多250顶层物件、800展开组件。避免穿插，保留主路、间距和分区。'''
ASSET_SYSTEM='''你是千星原生基元造型师。仅返回 JSON {name,description,components:[{id,assetId,name,position:[x,y,z],rotation:[x,y,z],scale:[x,y,z],color:"#RRGGBB"}]}。只可用给出的基元ID（10009001..10009011），最多160组件。Y向上，旋转度数 Rz*Ry*Rx，单位尺寸，中心原点，底部落在Y=0。生成可辨识的完整组合模型，分层细节，和谐配色。不要输出外部网格、纹理URL、代码或占位文字。'''

def context(catalog,idea):
    assets=[];seen=set()
    def add_asset(a):
        if a['id'] not in seen and is_native_model(a):
            assets.append(dict(assetId=a['id'],name=a['name'],internalName=a.get('internalName',''),dimensions=[round(x,3) for x in a['dimensions']],primitive=None));seen.add(a['id'])
    for kind in ('bridge','arch','stall','well','road','water'):
        for a in native_candidates(kind,catalog)[:3]:add_asset(a)
    for query,limit in [(idea,25),('房屋',20),('乔木',15),('岩石',8),('灯笼',6),('地板',8)]:
        for a in catalog.search(query,ready=True,limit=limit):
            add_asset(catalog.by_id[a['id']])
    return assets

def generate_plan(idea,mode,provider):
    if mode=='offline':return offline_plan(idea)
    if mode!='ai':raise ValueError('生成模式无效')
    p=bounded_plan(provider.ask(PLAN_SYSTEM,{'idea':str(idea)[:6000]}));p.update(mode='ai',prompt=str(idea)[:6000]);return p

def generate_scene(plan,mode,catalog,provider):
    p=bounded_plan(plan)
    if mode=='offline':return offline_scene(p,catalog)
    if mode!='ai':raise ValueError('生成模式无效')
    result=provider.ask(SCENE_SYSTEM,dict(design=p,catalog=context(catalog,p.get('prompt',p['summary']))))
    result=result.get('scene',result) if isinstance(result,dict) else result
    s=validate(result,catalog)
    all_nodes=s['nodes']+[n for definition in s['definitions'].values() for n in definition['components']]
    if any(n['assetId'] in catalog.by_id and not is_native_model(catalog.by_id[n['assetId']]) for n in all_nodes):raise ValueError('默认生成必须使用完整原生资产，不能包含基元或白模定义。')
    from .scene import flatten
    flat,blocked=flatten(s,catalog)
    if blocked:raise ValueError('模型选择了未绑定资产，请调整想法后重新生成')
    if any(not is_native_model(catalog.by_id[o['asset_id']]) for o in flat):raise ValueError('场景生成只使用完整原生资产，不能用基元或白模替代；独特新造型请单独开启基元补充。')
    if len(s['nodes'])>250 or len(flat)>800:raise ValueError('模型生成的场景超出 AI 预算，请缩小场景')
    notes=s.pop('notes',[])
    if isinstance(notes,list):p['notes']=[str(n)[:400] for n in notes[:20]]
    s['design']=p;return s

def generate_asset(idea,mode,provider,catalog,allow_primitives=False):
    if mode not in ('offline','ai'):raise ValueError('生成模式无效')
    if not isinstance(allow_primitives,bool):raise ValueError('基元补充开关必须为布尔值')
    idea=str(idea).strip()[:6000]
    if not idea:raise ValueError('先描述需要的资产')
    matches=native_matches(idea,catalog)
    if matches:
        a=matches[0]
        return dict(id=a['id'],name=a['name'],templateId=a['templateId'],origin='native',nativeModel=True,description='使用目录中的完整原生模型与材质')
    if not allow_primitives:raise ValueError('未找到匹配的完整原生资产。需要独特新造型时，可明确开启“无匹配原生资产时允许基元补充”。')
    if mode=='offline':
        kind=feature_kind(idea)
        if kind not in ('bridge','arch','well','tower','stall'):raise ValueError('离线基元配方不支持这个独特造型；请使用已配置的 AI 模型，或继续查找原生资产。')
        return recipe(idea,kind)
    from .catalog import PRIMITIVES
    a=provider.ask(ASSET_SYSTEM,dict(idea=idea,nativeSearch='no matching complete native model',primitives=[dict(assetId=str(k),name=v[0]) for k,v in PRIMITIVES.items()]))
    if not isinstance(a,dict) or not isinstance(a.get('components'),list) or not 1<=len(a['components'])<=160:raise ValueError('模型须返回 1–160 个基元组件')
    for c in a['components']:
        if str(c.get('assetId')) not in {str(k) for k in PRIMITIVES}:raise ValueError('生成资产只能使用原生基元')
        c['id']=uid()
    a.update(id='custom_'+uid('asset'),name=str(a.get('name','AI 组合资产'))[:120],origin='ai',prompt=str(idea)[:6000])
    s=empty();s['definitions'][a['id']]=a;validate(s,catalog)
    return a
