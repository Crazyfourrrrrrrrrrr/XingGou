"""Y-up, degrees, extrinsic X then Y then Z (Rz @ Ry @ Rx)."""
import math

def rotation(v):
    x,y,z=map(math.radians,v);cx,sx=math.cos(x),math.sin(x);cy,sy=math.cos(y),math.sin(y);cz,sz=math.cos(z),math.sin(z)
    return [[cz*cy,cz*sy*sx-sz*cx,cz*sy*cx+sz*sx],[sz*cy,sz*sy*sx+cz*cx,sz*sy*cx-cz*sx],[-sy,cy*sx,cy*cx]]

def mm(a,b):return [[sum(a[i][k]*b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
def mv(a,v):return [sum(a[i][j]*v[j] for j in range(3)) for i in range(3)]
def add(a,b):return [a[i]+b[i] for i in range(3)]
def euler(r):
    y=math.asin(max(-1,min(1,-r[2][0])))
    if abs(math.cos(y))>1e-7:x,z=math.atan2(r[2][1],r[2][2]),math.atan2(r[1][0],r[0][0])
    else:x,z=0,math.atan2(-r[0][1],r[1][1])
    return [math.degrees(a) for a in (x,y,z)]

def affine(node):
    r=rotation(node.get('rotation',[0,0,0]));s=node.get('scale',[1,1,1])
    return [[r[i][j]*s[j] for j in range(3)] for i in range(3)],list(node.get('position',[0,0,0]))

def combine(parent,node):
    m,p=affine(node)
    if parent is None:return m,p
    return mm(parent[0],m),add(parent[1],mv(parent[0],p))

def decompose(a):
    m,p=a;s=[math.sqrt(sum(m[i][j]**2 for i in range(3))) for j in range(3)]
    if min(s)<1e-7:raise ValueError('缩放过小，无法导出')
    r=[[m[i][j]/s[j] for j in range(3)] for i in range(3)]
    if any(abs(sum(r[k][i]*r[k][j] for k in range(3)))>1e-5 for i,j in ((0,1),(0,2),(1,2))):
        raise ValueError('组合出现剪切变形，请使用等比缩放，或解除组合后调整')
    return dict(position=p,rotation=euler(r),scale=s)
