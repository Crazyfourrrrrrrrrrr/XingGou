"""Editor glTF coordinates <-> native game coordinates.

AnimeStudio ModelConverter.SetFrame reflects position X and quaternion Y/Z
while exporting Unity data. Its mesh vertices and normals reflect X as well.
StarScene edits those right-handed GLBs, so native export must undo that
reflection for BOTH position and orientation. For Rz @ Ry @ Rx this is
position=(-x,y,z), rotation=(rx,-ry,-rz); positive scale is preserved.
Do not use Mx*R*Mz: that assumes a different primitive's local geometry basis.
"""
import copy

MIRROR=(-1,1,1)

def native_object(obj):
    result=copy.deepcopy(obj)
    x,y,z=obj['position'];rx,ry,rz=obj.get('rotation',[0,0,0])
    result['position']=[-x,y,z];result['rotation']=[rx,-ry,-rz]
    return result

def reflected_affine(transform):
    """Reflect a decoded native affine back to the editor basis (an involution)."""
    matrix,position=transform
    return ([[MIRROR[i]*matrix[i][j]*MIRROR[j] for j in range(3)] for i in range(3)],
            [MIRROR[i]*position[i] for i in range(3)])
