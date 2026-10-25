"""Run with Blender --background --factory-startup --python ... -- <glb> <report> [blend]."""
import bpy,json,sys
from pathlib import Path
args=sys.argv[sys.argv.index('--')+1:];source=Path(args[0]).resolve();report=Path(args[1]).resolve()
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(source))
meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
images=[im for im in bpy.data.images if im.name not in ('Render Result','Viewer Node')]
invalid=[im.name for im in images if min(im.size)<1]
result=dict(blenderVersion=bpy.app.version_string,source=str(source),sourceBytes=source.stat().st_size,objects=len(bpy.context.scene.objects),meshes=len(meshes),vertices=sum(len(o.data.vertices) for o in meshes),polygons=sum(len(o.data.polygons) for o in meshes),materials=len(bpy.data.materials),images=len(images),packedImages=sum(bool(im.packed_file) for im in images),invalidImages=invalid,passed=bool(meshes) and not invalid)
if len(args)>2:
    target=Path(args[2]).resolve();bpy.ops.wm.save_as_mainfile(filepath=str(target));result['blend']=str(target)
report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8');print('STARSCENE_BLENDER_RESULT '+json.dumps(result,ensure_ascii=False))
if not result['passed']:raise RuntimeError('GLB verification failed')
