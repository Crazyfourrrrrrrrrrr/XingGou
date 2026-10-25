"""Find or start this checkout's local server, then open the editor."""
import argparse,json,os,socket,subprocess,sys,time,urllib.error,urllib.request,webbrowser
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def request(url,data=None):
    req=urllib.request.Request(url,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json','X-StarScene':'1'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=2) as r:return json.load(r)
def existing():
    try:
        url=json.loads((ROOT/'.runtime/server.json').read_text())['url'];health=request(url+'/api/health')
        if health.get('tool')=='StarSceneStudio' and Path(health['root']).resolve()==ROOT:return url
    except (OSError,ValueError,KeyError,urllib.error.URLError):pass
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--no-browser',action='store_true');parser.add_argument('--stop',action='store_true');args=parser.parse_args()
    url=existing()
    if args.stop:
        if url:
            request(url+'/api/shutdown',{})
            for _ in range(30):
                time.sleep(.1)
                if not existing():break
        print('StarScene server stopped.' if url else 'StarScene server is not running.');return
    if not url:
        for port in range(8770,8791):
            with socket.socket() as s:
                try:s.bind(('127.0.0.1',port));break
                except OSError:continue
        else:raise RuntimeError('No free local port in 8770..8790')
        runtime=ROOT/'.runtime';runtime.mkdir(exist_ok=True)
        with (runtime/'server.log').open('ab') as log:
            env=os.environ.copy();env['PYTHONUTF8']='1'
            subprocess.Popen([sys.executable,str(ROOT/'server.py'),'--port',str(port)],cwd=ROOT,stdout=log,stderr=log,stdin=subprocess.DEVNULL,env=env,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,start_new_session=os.name!='nt')
        for _ in range(80):
            time.sleep(.15);url=existing()
            if url:break
        if not url:raise RuntimeError('Server failed to start. See .runtime/server.log')
    print(url,flush=True)
    if not args.no_browser:webbrowser.open(url)
if __name__=='__main__':main()
