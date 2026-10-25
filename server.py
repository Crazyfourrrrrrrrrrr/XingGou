"""XingGou local service. Python 3.10+, standard library only."""
import argparse,json,mimetypes,os,re,sys,threading,time,traceback,urllib.parse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from core.catalog import Catalog
from core.scene import ProjectStore
from core.generator import Provider,generate_plan,generate_scene,generate_asset,offline_plan,offline_scene
from core.gia import export_scene,ExportBlocked
from core.branding import TOOL,DISPLAY_NAME,VERSION

ROOT=Path(__file__).resolve().parent
class App:
    def __init__(self):
        self.catalog=Catalog();self.store=ProjectStore(ROOT/'projects',self.catalog);self.provider=Provider(ROOT/'projects');self.exports=ROOT/'exports'
        if not self.store.path.is_file():self.store.put(offline_scene(offline_plan('小型溪流营地，4栋木屋，森林、木桥和入口拱门'),self.catalog),source='sample')
    def boot(self):
        c=self.catalog
        return dict(tool=TOOL,displayName=DISPLAY_NAME,version=VERSION,catalog=c.all(),catalogStatus=dict(total=len(c.assets),ready=sum(a['exportable'] for a in c.assets),libraryAvailable=c.available,assetRoot=str(c.root)),provider=self.provider.status(),**self.store.get())

class Handler(BaseHTTPRequestHandler):
    server_version=TOOL+'/'+VERSION
    def log_message(self,*args):pass
    def same_origin(self):
        host=self.headers.get('Host','');u=urllib.parse.urlsplit('http://'+host)
        try:valid=u.hostname in ('localhost','127.0.0.1') and u.port==self.server.server_port
        except ValueError:valid=False
        if not valid:raise PermissionError('仅允许本机访问')
        origin=self.headers.get('Origin')
        if origin and origin not in ('http://'+host,'http://127.0.0.1:'+str(self.server.server_port),'http://localhost:'+str(self.server.server_port)):raise PermissionError('不允许跨站请求')
    def headers_out(self,status,mime,length,extra=None):
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(length));self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
        for k,v in (extra or {}).items():self.send_header(k,v)
        self.end_headers()
    def json(self,value,status=200):
        b=json.dumps(value,ensure_ascii=False,allow_nan=False).encode();self.headers_out(status,'application/json; charset=utf-8',len(b),{'Cache-Control':'no-store'})
        if self.command!='HEAD':self.wfile.write(b)
    def file(self,path,download=False):
        if not path.is_file():raise FileNotFoundError('文件不存在')
        size=path.stat().st_size;start=0;end=size-1;status=200
        headers={'Accept-Ranges':'bytes','Cache-Control':'public, max-age=3600' if path.suffix=='.glb' else 'no-cache'}
        if self.headers.get('Range'):
            match=re.fullmatch(r'bytes=(\d*)-(\d*)',self.headers['Range'])
            if not match or not any(match.groups()):self.headers_out(416,'text/plain',0,{'Content-Range':f'bytes */{size}'});return
            a,b=match.groups()
            if a:start=int(a);end=min(int(b),end) if b else end
            else:start=max(0,size-int(b))
            if start>=size or start>end:self.headers_out(416,'text/plain',0,{'Content-Range':f'bytes */{size}'});return
            status=206;headers['Content-Range']=f'bytes {start}-{end}/{size}'
        if download:headers['Content-Disposition']="attachment; filename*=UTF-8''"+urllib.parse.quote(path.name)
        mime={'.js':'text/javascript; charset=utf-8','.json':'application/json; charset=utf-8','.glb':'model/gltf-binary'}.get(path.suffix,mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.headers_out(status,mime,end-start+1,headers)
        if self.command=='HEAD':return
        with path.open('rb') as f:
            f.seek(start);left=end-start+1
            while left:
                block=f.read(min(left,1024*256))
                if not block:break
                self.wfile.write(block);left-=len(block)
    def get(self):
        self.same_origin();u=urllib.parse.urlsplit(self.path);path=urllib.parse.unquote(u.path);qs=urllib.parse.parse_qs(u.query);app=self.server.app
        if path=='/api/health':return self.json(dict(tool=TOOL,displayName=DISPLAY_NAME,root=str(ROOT),version=VERSION))
        if path=='/api/boot':return self.json(app.boot())
        if path=='/api/project':return self.json(app.store.get())
        if path=='/api/catalog':return self.json(dict(assets=app.catalog.search(qs.get('q',[''])[0],qs.get('category',[''])[0],qs.get('ready',[''])[0]=='true',qs.get('limit',[60])[0])))
        if path=='/api/provider':return self.json(app.provider.status())
        if path.startswith('/models/') and re.fullmatch(r'/models/[\w-]+\.glb',path):return self.file(app.catalog.model_path(path[8:-4]))
        if path.startswith('/download/'):
            file=(app.exports/path[10:]).resolve()
            if not file.is_relative_to(app.exports.resolve()):raise PermissionError('路径无效')
            return self.file(file,True)
        if path.startswith('/api/'):raise FileNotFoundError('接口不存在')
        file=(ROOT/'web'/('index.html' if path=='/' else path.lstrip('/'))).resolve()
        if not file.is_relative_to((ROOT/'web').resolve()):raise PermissionError('路径无效')
        self.file(file)
    def do_GET(self):self.guard(self.get)
    def do_HEAD(self):self.guard(self.get)
    def do_POST(self):self.guard(self.post)
    def do_OPTIONS(self):self.guard(lambda:(_ for _ in ()).throw(PermissionError('不开放跨站接口')))
    def post(self):
        self.same_origin()
        client=self.headers.get('X-XingGou',self.headers.get('X-StarScene'))
        if client!='1' or self.headers.get_content_type()!='application/json':raise PermissionError('请求须来自星构工具箱编辑器或其 MCP 客户端')
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:raise ValueError('请求长度错误')
        if not 0<length<=12_000_000:raise ValueError('请求内容应在 12 MB 以内')
        data=json.loads(self.rfile.read(length));app=self.server.app;path=urllib.parse.urlsplit(self.path).path
        if not isinstance(data,dict):raise ValueError('请求必须为 JSON 对象')
        if path=='/api/project':return self.json(app.store.put(data.get('project'),data.get('revision'),data.get('source','web')))
        if path=='/api/bindings':return self.json(app.catalog.bind(data.get('assetId'),data.get('templateId')))
        if path=='/api/provider':return self.json(app.provider.configure(data))
        if path=='/api/export':return self.json(export_scene(data.get('project',app.store.get()['project']),app.catalog,app.exports))
        if path=='/api/ai/plan':return self.json(dict(plan=generate_plan(data.get('idea',''),data.get('mode','offline'),app.provider)))
        if path=='/api/ai/scene':return self.json(dict(project=generate_scene(data.get('plan'),data.get('mode','offline'),app.catalog,app.provider)))
        if path=='/api/ai/asset':return self.json(dict(asset=generate_asset(data.get('idea',''),data.get('mode','offline'),app.provider,app.catalog,data.get('allowPrimitives',False))))
        if path=='/api/shutdown':
            self.json({'ok':True});threading.Thread(target=self.server.shutdown,daemon=True).start();return
        raise FileNotFoundError('接口不存在')
    def guard(self,fn):
        try:fn()
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
        except ExportBlocked as e:self.json(dict(error=str(e),blocked=e.blocked),422)
        except RuntimeError as e:self.json(dict(error=str(e),conflict=True),409)
        except PermissionError as e:self.json(dict(error=str(e)),403)
        except FileNotFoundError as e:self.json(dict(error=str(e)),404)
        except (ValueError,KeyError,TypeError,OverflowError) as e:self.json(dict(error=str(e)),400)
        except Exception:
            traceback.print_exc();self.json(dict(error='服务处理失败，详细记录见本机 .runtime/server.log'),500)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8770);args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);server.daemon_threads=True;server.app=App()
    runtime=ROOT/'.runtime';runtime.mkdir(exist_ok=True)
    (runtime/'server.json').write_text(json.dumps(dict(url=f'http://127.0.0.1:{args.port}',pid=os.getpid(),root=str(ROOT))),encoding='utf-8')
    print(f'{TOOL} {DISPLAY_NAME} {VERSION} http://127.0.0.1:{args.port}',flush=True)
    try:server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
