"""Dependency-free stdio MCP bridge to the running local XingGou editor."""
import json,os,sys,urllib.error,urllib.request
from pathlib import Path
from core.branding import TOOL,VERSION,environment
ROOT=Path(__file__).resolve().parent
TOOLS=[
 dict(name='catalog_search',description='搜索本机千星模型；ready=true 仅返回已绑定模板编号的资产。优先选择 primitive 为空的现成完整原生模型，保留原材质。',inputSchema=dict(type='object',properties=dict(query=dict(type='string'),ready=dict(type='boolean'),limit=dict(type='integer',minimum=1,maximum=100)))),
 dict(name='scene_get',description='读取当前网页工程和 revision。坐标 Y-UP，角度制，Rz*Ry*Rx。',inputSchema=dict(type='object',properties={})),
 dict(name='scene_replace',description='把完整 starscene/1 工程写入网页；必须带上 scene_get 的 revision 防止覆盖其他端修改。只放置目录中的资产，默认使用现成完整原生模型；没有匹配资源时记录缺项，不得自动白模兜底。definitions 是工程编辑分组，GIA 导出时展开为独立静态单位，不创建动态父实体。',inputSchema=dict(type='object',properties=dict(project=dict(type='object'),revision=dict(type='integer')),required=['project','revision'])),
 dict(name='scene_export',description='严格检查并导出当前固定布景 GIA，默认每个原生模型为独立静态单位，无动态父实体和父级缩放补偿；返回本机 ZIP 下载地址。未绑定模板编号的物件将报错；游戏实际导入和负载需在千星编辑器确认。',inputSchema=dict(type='object',properties={})),
 dict(name='asset_recipes',description='先查找现成完整原生模型，返回 asset.nativeModel=true 时直接引用 asset.id。仅无匹配资源且用户明确允许基元补充时，才传 allowPrimitives=true 返回组合定义。组件数不是游戏官方负载值。',inputSchema=dict(type='object',properties=dict(idea=dict(type='string'),allowPrimitives=dict(type='boolean',default=False)),required=['idea'])),
]
def api(path,data=None):
    url=environment('URL')
    if not url:
        try:url=json.loads((ROOT/'.runtime/server.json').read_text())['url']
        except (OSError,KeyError,ValueError):raise ValueError('请先启动星构工具箱本机编辑器')
    req=urllib.request.Request(url+path,data=json.dumps(data,ensure_ascii=False).encode() if data is not None else None,headers={'Content-Type':'application/json','X-XingGou':'1','X-StarScene':'1'})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=180) as r:return json.load(r)
    except urllib.error.HTTPError as e:
        try:message=json.load(e).get('error',f'HTTP {e.code}')
        except ValueError:message=f'HTTP {e.code}'
        raise ValueError(message)
    except urllib.error.URLError:raise ValueError('无法连接星构工具箱服务，请先启动网页编辑器')
def dispatch(message):
    method=message.get('method');params=message.get('params') or {}
    if method=='initialize':return dict(protocolVersion='2024-11-05',capabilities={'tools':{}},serverInfo={'name':TOOL,'version':VERSION},instructions='用 catalog_search 检索真实资产，scene_get 读取工程，scene_replace 提交完整 starscene/1 场景（含 revision）。默认优先使用千星现成完整原生模型与原材质；桥、建筑、道路等已有资源不得用基元重造。缺少可导出资源时在 design.notes 记录待补充项，禁止自动白模兜底；只有确无匹配资源且用户明确允许时才以基元补充独特造型。固定布景默认导出为独立静态单位；definitions 仅用于工程组合编辑，导出会展开，不挂动态父实体，不使用父级 0.01 缩放补偿。运动或交互需求需要另行实现与验证，当前工具不生成这些行为。组件数不是游戏官方负载值。工程采用右手 Y-UP，导出器自动转换到游戏左手系；不要手动二次镜像。默认地面 Y=0，沿用工程 settings.groundHeight；不自动创建白模基座。不要猜测模板编号。scene_export 的校验成功不等同游戏内导入成功或负载验收通过。')
    if method=='ping':return {}
    if method=='tools/list':return {'tools':TOOLS}
    if method=='tools/call':
        args=params.get('arguments',{});name=params.get('name')
        try:
            if name=='catalog_search':
                import urllib.parse
                result=api('/api/catalog?'+urllib.parse.urlencode(dict(q=args.get('query',''),ready=str(args.get('ready',True)).lower(),limit=min(100,args.get('limit',30)))))
            elif name=='scene_get':result=api('/api/project')
            elif name=='scene_replace':result=api('/api/project',dict(project=args['project'],revision=args['revision'],source='mcp'))
            elif name=='scene_export':result=api('/api/export',{})
            elif name=='asset_recipes':result=api('/api/ai/asset',dict(idea=args['idea'],mode='offline',allowPrimitives=args.get('allowPrimitives',False)))
            else:raise ValueError('工具不存在')
            return dict(content=[dict(type='text',text=json.dumps(result,ensure_ascii=False))])
        except (ValueError,KeyError) as e:return dict(isError=True,content=[dict(type='text',text=str(e))])
    raise LookupError('Method not found')
def main():
    for line in sys.stdin:
        try:
            m=json.loads(line)
            if 'id' not in m:continue
            try:out=dict(jsonrpc='2.0',id=m['id'],result=dispatch(m))
            except LookupError:out=dict(jsonrpc='2.0',id=m['id'],error=dict(code=-32601,message='Method not found'))
            except Exception as e:out=dict(jsonrpc='2.0',id=m['id'],error=dict(code=-32603,message=str(e)))
        except ValueError:out=dict(jsonrpc='2.0',id=None,error=dict(code=-32700,message='Parse error'))
        print(json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8');sys.stdin.reconfigure(encoding='utf-8')
    main()
