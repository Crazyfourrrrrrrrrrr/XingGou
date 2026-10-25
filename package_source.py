"""Build a shareable source archive; never includes user/game files or secrets."""
import hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
FILES={'server.py','launch.py','mcp_server.py','package_source.py','README.md','THIRD_PARTY.md','LICENSE','.gitignore','.gitattributes','config.example.json','启动星构.cmd','停止星构.cmd'}
DIRS={'core','web','vendor','licenses','tests','docs','.github'}
MEDIA={'docs/images/editor-example.png'}
EXAMPLES={'溪畔小聚.starscene.json','坐标校准.starscene.json','原生水体验证.starscene.json','mcp-config.example.json'}

def allowed(rel):
    """Only publish known source types and deliberately selected documentation media."""
    value=rel.as_posix();top=rel.parts[0]
    if value in FILES or value in MEDIA:return True
    if '__pycache__' in rel.parts or rel.name.endswith('.local.json'):return False
    if top=='examples':return rel.name in EXAMPLES and len(rel.parts)==2
    if top=='core':return rel.suffix=='.py'
    if top=='tests':return rel.suffix in ('.py','.cjs')
    if top=='docs':return rel.suffix in ('.md','.svg')
    if top=='.github':return rel.suffix in ('.yml','.yaml','.md')
    if top=='licenses':return value=='licenses/three-LICENSE'
    if top=='vendor':return rel.suffix=='.py' or value in {
        'vendor/miliastra_tools/Template/GPT2Gia_entities.gia',
        'vendor/miliastra_tools/Template/GPT2Gia_decorations.gia'}
    if top=='web':return value=='web/vendor/three/FILES.json' or rel.suffix in ('.js','.cjs','.css','.html','.svg')
    return False
def main():
    target=ROOT.parent/'StarSceneStudio-0.1.4-source.zip';manifest=[]
    three=json.loads((ROOT/'web/vendor/three/FILES.json').read_text('utf-8'))['files']
    candidates=[ROOT/p for p in FILES]
    for name in DIRS|{'examples'}:candidates.extend(p for p in (ROOT/name).rglob('*') if p.is_file())
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(set(candidates)):
            if not p.is_file():continue
            rel=p.relative_to(ROOT)
            if not allowed(rel):continue
            if rel.as_posix().startswith('web/vendor/three/') and rel.as_posix()[17:] not in three and rel.name!='FILES.json':continue
            z.write(p,'StarSceneStudio/'+rel.as_posix());manifest.append(dict(path=rel.as_posix(),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
        z.writestr('StarSceneStudio/SOURCE_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    print(json.dumps(dict(path=str(target),files=len(manifest),bytes=target.stat().st_size,sha256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))
if __name__=='__main__':main()
