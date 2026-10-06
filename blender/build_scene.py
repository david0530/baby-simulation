"""
Baby Sim — Blender proof of concept.

Builds the nursery + baby from baby-sim.html in Blender, bakes the same 63.5 s
timeline (design screen + story) as keyframes, saves baby-sim.blend and
optionally renders.

  Blender -b -P build_scene.py -- [--preview] [--stills 2,12,42] [--anim] [--every N]

Coordinates: the web version is Y-up (Three.js); Blender is Z-up.
V(x, y, z) converts a Three.js position to Blender: (x, -z, y).
"""
import bpy, bmesh, math, os, sys
from math import sin, cos, pi, sqrt
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
FPS = 24
INTRO = 23.5                      # design-screen segment before the story
DURATION = INTRO + 40
NFRAMES = round(DURATION * FPS)   # 1524

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
def arg(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default
PREVIEW = '--preview' in argv

# ---------------------------------------------------------------- math helpers
clamp = lambda x, a=0.0, b=1.0: min(b, max(a, x))
lerp = lambda a, b, k: a + (b - a) * k
def smooth(a, b, t):
    k = clamp((t - a) / (b - a)); return k * k * (3 - 2 * k)
within = lambda t, a, b: a <= t < b
def pulse(t, a, b, f=0.4):
    return smooth(a, a + f, t) * (1 - smooth(b - f, b, t))

V = lambda x, y, z: (x, -z, y)                         # three -> blender position
S3 = lambda sx, sy, sz: (sx, sz, sy)                    # three -> blender scale
R3 = lambda a, b, c: (a, -c, b)                         # three XYZ euler -> blender 'YZX'

def lin(c): return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
def col(h, a=1.0):
    h = h.lstrip('#'); return tuple(lin(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4)) + (a,)
def mix(c1, c2, k): return tuple(lerp(a, b, k) for a, b in zip(c1, c2))

# ---------------------------------------------------------------- scene reset
for o in list(bpy.data.objects): bpy.data.objects.remove(o, do_unlink=True)
for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras, bpy.data.actions):
    for b in list(coll): coll.remove(b)
scene = bpy.context.scene
root = scene.collection

# ---------------------------------------------------------------- materials
def material(name, hexc, rough=0.65, alpha=1.0, **inputs):
    m = bpy.data.materials.new(name)
    p = m.node_tree.nodes['Principled BSDF']
    p.inputs['Base Color'].default_value = col(hexc)
    p.inputs['Roughness'].default_value = rough
    if alpha < 1: p.inputs['Alpha'].default_value = alpha
    for k, v in inputs.items(): p.inputs[k.replace('_', ' ')].default_value = v
    return m

def bsdf(m): return m.node_tree.nodes['Principled BSDF']

SKIN_SSS = dict(Subsurface_Weight=0.18, Subsurface_Scale=0.04, Subsurface_Radius=(1.0, 0.35, 0.2))
skin = material('Skin', '#f6c9a6', 0.5, **SKIN_SSS)
outfitTop = material('OutfitTop', '#ffd46e', 0.85, Sheen_Weight=0.4)
outfitArms = material('OutfitArms', '#ffd46e', 0.85, Sheen_Weight=0.4)
outfitLegs = material('OutfitLegs', '#ffd46e', 0.85, Sheen_Weight=0.4)
bellyMat = material('Belly', '#fff2cc', 0.9, Sheen_Weight=0.4)
footMat = material('Feet', '#f6c9a6', 0.55)
hairMat = material('Hair', '#6b4a33', 0.55, Sheen_Weight=0.3, Coat_Weight=0.15)
trimMat = material('Trim', '#ffffff', 0.8)
eyeMat = material('Eye', '#2a1d22', 0.12, Coat_Weight=0.6)
shineMat = material('Shine', '#ffffff', 0.3, Emission_Color=col('#ffffff'), Emission_Strength=3.0)
cheekMat = material('Cheek', '#ff9aa8', 0.8, alpha=0.6)
mouthMat = material('Mouth', '#9a3d45', 0.5)
bowMat = material('Bow', '#ff5f8a', 0.45)
tieMat = material('Tie', '#ff6f91', 0.5)
tearMat = material('Tear', '#a8dcff', 0.05, alpha=0.85, Emission_Color=col('#3b86c2'), Emission_Strength=0.4)
heartMat = material('Heart', '#ff6f91', 0.5, Emission_Color=col('#ff6f91'), Emission_Strength=1.2)

# ---------------------------------------------------------------- mesh builders (return bmesh in blender coords)
def bm_sphere(r, ws=48, hs=32):
    bm = bmesh.new(); bmesh.ops.create_uvsphere(bm, u_segments=ws, v_segments=hs, radius=r); return bm

def bm_param_sphere(r, phiS, phiL, thS, thL, ws=48, hs=24):
    """Partial sphere using Three.js SphereGeometry parameters (for hair caps)."""
    bm = bmesh.new(); grid = []
    for iy in range(hs + 1):
        th = thS + iy / hs * thL; row = []
        for ix in range(ws + 1):
            ph = phiS + ix / ws * phiL
            x, y, z = -r * cos(ph) * sin(th), r * cos(th), r * sin(ph) * sin(th)
            row.append(bm.verts.new(V(x, y, z)))
        grid.append(row)
    for iy in range(hs):
        for ix in range(ws):
            a, b, c, d = grid[iy][ix + 1], grid[iy][ix], grid[iy + 1][ix], grid[iy + 1][ix + 1]
            try: bm.faces.new((a, b, c, d))
            except ValueError: pass
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=1e-6)
    return bm

def bm_capsule(r, length, ws=32, hs=24):
    bm = bm_sphere(r, ws, hs)
    for v in bm.verts: v.co.z += length / 2 if v.co.z >= -1e-6 else -length / 2
    return bm

def bm_torus(R, r, rs=12, ts=48, arc=2 * pi, plane='H'):
    """plane 'H' = horizontal (blender XY), 'V' = facing camera (blender XZ), 'YZ' = side plane."""
    bm = bmesh.new(); closed = abs(arc - 2 * pi) < 1e-6
    tn = ts if closed else ts + 1
    rings = []
    for i in range(tn):
        u = i / ts * arc; ring = []
        for j in range(rs):
            v = j / rs * 2 * pi
            a, b, c = (R + r * cos(v)) * cos(u), (R + r * cos(v)) * sin(u), r * sin(v)
            p = {'H': (a, b, c), 'V': (a, c, b), 'YZ': (c, a, b)}[plane]
            ring.append(bm.verts.new(p))
        rings.append(ring)
    for i in range(ts if closed else ts):
        r1, r2 = rings[i], rings[(i + 1) % tn]
        for j in range(rs):
            bm.faces.new((r1[j], r2[j], r2[(j + 1) % rs], r1[(j + 1) % rs]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm

def bm_cone(r_bottom, r_top, depth, segs=48, caps=True):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=caps, cap_tris=False, segments=segs, radius1=r_bottom, radius2=r_top, depth=depth)
    return bm

def bm_box(sx, sy, sz):
    bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts: v.co.x *= sx; v.co.y *= sy; v.co.z *= sz
    return bm

def bm_extrude(points, depth):
    """2D outline (u right, v up) extruded toward the camera (-Y)."""
    bm = bmesh.new()
    front = [bm.verts.new((u, -depth, v)) for u, v in points]
    back = [bm.verts.new((u, 0, v)) for u, v in points]
    bm.faces.new(front); bm.faces.new(list(reversed(back)))
    n = len(points)
    for i in range(n):
        bm.faces.new((front[i], back[i], back[(i + 1) % n], front[(i + 1) % n]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm

def bm_disc(r, segs=96):
    bm = bmesh.new(); bmesh.ops.create_circle(bm, cap_ends=True, segments=segs, radius=r); return bm

def bm_ring(r1, r2, segs=96):
    bm = bmesh.new(); inner, outer = [], []
    for i in range(segs):
        a = i / segs * 2 * pi
        inner.append(bm.verts.new((r1 * cos(a), r1 * sin(a), 0))); outer.append(bm.verts.new((r2 * cos(a), r2 * sin(a), 0)))
    for i in range(segs):
        j = (i + 1) % segs; bm.faces.new((inner[i], outer[i], outer[j], inner[j]))
    return bm

# ---------------------------------------------------------------- objects
def group(name, parent=None, loc=(0, 0, 0)):
    o = bpy.data.objects.new(name, None); root.objects.link(o)
    o.parent = parent; o.location = V(*loc); o.rotation_mode = 'YZX'; o.empty_display_size = 0.1
    return o

def obj(name, bm, m, parent=None, loc=(0, 0, 0), scale=None, rot=None, smooth_shade=True, shadow=True, bevel=0, loc_b=None):
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    if smooth_shade:
        for p in me.polygons: p.use_smooth = True
    o = bpy.data.objects.new(name, me); root.objects.link(o)
    me.materials.append(m)
    o.parent = parent; o.rotation_mode = 'YZX'
    o.location = loc_b if loc_b is not None else V(*loc)
    if scale: o.scale = S3(*scale)
    if rot: o.rotation_euler = R3(*rot)
    o.visible_shadow = shadow
    if bevel:
        mod = o.modifiers.new('Bevel', 'BEVEL'); mod.width = bevel; mod.segments = 4
    return o

def descendants_meshes(o):
    return [c for c in o.children_recursive if c.type == 'MESH']

# ---------------------------------------------------------------- room
floor = obj('Floor', bm_box(40, 40, 0.01), material('FloorM', '#e8d3bd', 0.95), loc_b=(0, 0, -0.005), smooth_shade=False)
rug = obj('Rug', bm_disc(2.3), material('RugM', '#bfe0d8', 1.0), loc_b=(0, 0, 0.004), smooth_shade=False)
rugRing = obj('RugRing', bm_ring(1.9, 2.0), material('RugRingM', '#f3fbf8', 1.0), loc_b=(0, 0, 0.006), smooth_shade=False)
wall = obj('Wall', bm_box(40, 0.02, 14), material('WallM', '#f8e4d9', 1.0), loc=(0, 7, -3.21), smooth_shade=False)
obj('Skirting', bm_box(40, 0.06, 0.18), material('SkirtM', '#fffaf6', 0.7), loc=(0, 0.09, -3.17), smooth_shade=False)

win = group('Window', loc=(-2.1, 2.4, -3.13))
white = material('WindowWhite', '#ffffff', 0.6)
obj('Frame', bm_box(1.9, 0.1, 1.4), white, win, bevel=0.04, smooth_shade=False)
obj('Glass', bm_box(1.7, 0.005, 1.2), material('GlassM', '#cfe8ff', 0.2, Emission_Color=col('#cfe8ff'), Emission_Strength=1.5),
    win, loc=(0, 0, 0.051), smooth_shade=False, shadow=False)
obj('BarV', bm_box(0.05, 0.03, 1.2), white, win, loc=(0, 0, 0.06), smooth_shade=False)
obj('BarH', bm_box(1.7, 0.03, 0.05), white, win, loc=(0, 0, 0.06), smooth_shade=False)

star_pts = [((0.14 if i % 2 == 0 else 0.06) * cos(i / 10 * 2 * pi + pi / 2), (0.14 if i % 2 == 0 else 0.06) * sin(i / 10 * 2 * pi + pi / 2)) for i in range(10)]
for i, c in enumerate(['#ffcf5c', '#ff9fb5', '#9fd3ff', '#b8e994', '#ffcf5c']):
    obj(f'Star{i}', bm_extrude(star_pts, 0.03), material(f'StarM{i}', c, 0.5), loc=(0.6 + i * 0.55, 2.75 - sin(i / 4 * pi) * 0.25, -3.15),
        smooth_shade=False, shadow=False)

obj('Ball', bm_sphere(0.2, 32, 16), material('BallM', '#8fc7ff', 0.35, Coat_Weight=0.5), loc=(-1.35, 0.2, 0.3))
band = obj('BallBand', bm_torus(0.2, 0.03, 10, 48, plane='V'), material('BallBandM', '#ffffff', 0.4), loc=(-1.35, 0.2, 0.3))
band.rotation_euler = R3(0, 0.8, 0)

# ---------------------------------------------------------------- baby (same proportions as the web version)
baby = group('Baby')
bodyPivot = group('BodyPivot', baby)

body = obj('Body', bm_sphere(0.5), outfitTop, bodyPivot, loc=(0, 0.52, 0), scale=(1, 1.08, 0.92))
belly = obj('BellyPatch', bm_sphere(0.3, 32, 16), bellyMat, bodyPivot, loc=(0, 0.48, 0.4), scale=(1, 1.1, 0.35))

skirt = obj('Skirt', bm_cone(0.68, 0.44, 0.36, caps=False), outfitTop, bodyPivot, loc=(0, 0.3, 0))
hem = obj('Hem', bm_torus(0.68, 0.028, 10, 64), trimMat, bodyPivot, loc=(0, 0.12, 0))
sash = group('Sash', bodyPivot)
sashBand = obj('SashBand', bm_torus(0.5, 0.03, 10, 64), trimMat, sash, loc=(0, 0.46, 0)); sashBand.scale = (1, 0.93, 1)
sashLoops = [obj(f'SashLoop{s}', bm_cone(0.06, 0, 0.12, 16), trimMat, sash, loc=(-s * 0.06, 0.46, 0.475), rot=(0, 0, s * pi / 2)) for s in (-1, 1)]

for s in (-1, 1):
    obj(f'Leg{s}', bm_capsule(0.15, 0.3), outfitLegs, bodyPivot, loc=(s * 0.24, 0.16, 0.36), rot=(pi / 2, 0, 0))
    obj(f'Foot{s}', bm_sphere(0.15, 32, 16), footMat, bodyPivot, loc=(s * 0.24, 0.16, 0.66), scale=(1, 0.85, 1.15))

arms, sleeves = {}, []
for s in (-1, 1):
    pv = group(f'ArmPivot{s}', bodyPivot, loc=(s * 0.43, 0.84, 0.04))
    obj(f'Arm{s}', bm_capsule(0.11, 0.26), outfitArms, pv, loc=(0, -0.2, 0))
    obj(f'Hand{s}', bm_sphere(0.12, 32, 16), skin, pv, loc=(0, -0.43, 0))
    sleeves.append(obj(f'Sleeve{s}', bm_sphere(0.155, 32, 16), outfitTop, pv, loc=(0, -0.07, 0)))
    arms[s] = pv

head = group('Head', bodyPivot, loc=(0, 1.33, 0))
obj('HeadMesh', bm_sphere(0.55, 64, 48), skin, head)
for s in (-1, 1):
    obj(f'Ear{s}', bm_sphere(0.12, 24, 16), skin, head, loc=(s * 0.53, 0, 0), scale=(0.6, 1, 0.9))
eyes, brows, cheeks = {}, {}, []
for s in (-1, 1):
    e = group(f'Eye{s}', head, loc=(s * 0.2, 0.05, 0.485))
    obj(f'EyeBall{s}', bm_sphere(0.075, 32, 16), eyeMat, e, shadow=False)
    obj(f'Shine{s}', bm_sphere(0.022, 16, 8), shineMat, e, loc=(0.025, 0.03, 0.06), shadow=False)
    eyes[s] = e
    cheeks.append(obj(f'Cheek{s}', bm_sphere(0.09, 24, 16), cheekMat, head, loc=(s * 0.32, -0.12, 0.42), scale=(1, 0.7, 0.35), shadow=False))
    b = group(f'Brow{s}', head, loc=(s * 0.2, 0.2, 0.468))
    obj(f'BrowMesh{s}', bm_capsule(0.014, 0.08, 12, 8), hairMat, b, rot=(0, 0, pi / 2), shadow=False)
    brows[s] = b
mouth = obj('Mouth', bm_torus(0.075, 0.018, 10, 24, pi, plane='V'), mouthMat, head, loc=(0, -0.19, 0.51), shadow=False)

# hairstyles
FRONT = pi / 2
def cap(name, parent, r, thL, gap=0.0):
    return obj(name, bm_param_sphere(r, FRONT + gap, 2 * pi - 2 * gap, 0, thL), hairMat, parent)
def on_head(x, y, z, k=1.0):
    n = sqrt(x * x + y * y + z * z); return (x / n * 0.56 * k, y / n * 0.56 * k, z / n * 0.56 * k)

hairStyles = {}
g = group('Hair_tuft', head)
obj('Curl', bm_torus(0.07, 0.025, 10, 24, pi * 1.5, plane='YZ'), hairMat, g, loc=(0.02, 0.57, 0.05))
hairStyles['tuft'] = g

g = group('Hair_bob', head)
cap('BobTop', g, 0.585, 1.05); cap('BobBack', g, 0.605, 1.95, 0.95)
for i in range(-3, 4):
    a = FRONT + i * 0.2
    obj(f'Fringe{i}', bm_sphere(0.075, 16, 12), hairMat, g, scale=(1, 0.8, 0.6),
        loc=(-cos(a) * sin(1.0) * 0.575, cos(1.0) * 0.575, sin(a) * sin(1.0) * 0.575))
hairStyles['bob'] = g

g = group('Hair_pigtails', head)
cap('PigTop', g, 0.585, 1.05); cap('PigBack', g, 0.6, 1.55, 1.1)
for s in (-1, 1):
    obj(f'Puff{s}', bm_sphere(0.17, 24, 16), hairMat, g, loc=(s * 0.6, 0.28, -0.12))
    obj(f'PigTie{s}', bm_torus(0.07, 0.025, 10, 24, plane='YZ'), tieMat, g, loc=(s * 0.5, 0.25, -0.1))
hairStyles['pigtails'] = g

g = group('Hair_curly', head)
cap('CurlyCap', g, 0.57, 1.1)
n = 160
for i in range(n):
    y = 1 - (i / (n - 1)) * 2; r = sqrt(1 - y * y); a = i * 2.39996
    x, z = cos(a) * r, sin(a) * r
    if not (y > 0.5 or (z < 0.1 and y > -0.15)): continue
    obj(f'Curl{i}', bm_sphere(0.1, 12, 8), hairMat, g, loc=on_head(x, y, z, 1.02))
hairStyles['curly'] = g

bow = group('Bow', head, loc=on_head(0.34, 0.42, 0.22, 1.1))
bow.rotation_euler = R3(0.3, 0.4, -0.5)
for s in (-1, 1):
    obj(f'BowLoop{s}', bm_cone(0.075, 0, 0.14, 16), bowMat, bow, loc=(-s * 0.07, 0, 0), rot=(0, 0, s * pi / 2))
obj('BowKnot', bm_sphere(0.04, 12, 8), bowMat, bow)

tears = []
for i in range(2):
    tears.append(obj(f'Tear{i}', bm_sphere(0.035, 16, 12), tearMat, head, shadow=False))

# ---------------------------------------------------------------- blocks + hearts
SZ = 0.34
blocks = [obj(f'Block{i}', bm_box(SZ, SZ, SZ), material(f'BlockM{i}', c, 0.45), bevel=0.05, smooth_shade=False)
          for i, c in enumerate(['#ff8a8a', '#7cc6ff', '#9be38f'])]
tower = [(0.95, SZ / 2 + i * SZ, 0.45) for i in range(3)]
fallen = [((1.05, SZ / 2, 0.52), 0.0, 0.35), ((1.5, SZ / 2, 0.9), -pi / 2, 0.5), ((1.9, SZ / 2, 0.2), -pi, -0.6)]
RESTACK = 28.2

heart_pts = [(16 * sin(a) ** 3 / 17 * 0.5, (13 * cos(a) - 5 * cos(2 * a) - 2 * cos(3 * a) - cos(4 * a)) / 17 * 0.5)
             for a in [i / 40 * 2 * pi for i in range(40)]]
hearts = [obj(f'Heart{i}', bm_extrude(heart_pts, 0.08), heartMat, smooth_shade=False, shadow=False) for i in range(7)]

# ---------------------------------------------------------------- camera + lights
cam_data = bpy.data.cameras.new('Camera'); cam_data.sensor_fit = 'VERTICAL'; cam_data.angle_y = math.radians(35)
camera = bpy.data.objects.new('Camera', cam_data); root.objects.link(camera); scene.camera = camera
cam_target = group('CamTarget')
tc = camera.constraints.new('TRACK_TO'); tc.target = cam_target; tc.track_axis = 'TRACK_NEGATIVE_Z'; tc.up_axis = 'UP_Y'

def sun(name, hexc, energy, frm, angle_deg):
    ld = bpy.data.lights.new(name, 'SUN'); ld.color = col(hexc)[:3]; ld.energy = energy; ld.angle = math.radians(angle_deg)
    o = bpy.data.objects.new(name, ld); root.objects.link(o)
    o.location = frm
    o.rotation_euler = (-Vector(frm)).to_track_quat('-Z', 'Y').to_euler()
    return ld
KEY_ENERGY = 2.4
key = sun('Key', '#fff0dc', KEY_ENERGY, V(3, 5.5, 4), 9)
sun('Rim', '#ffd3e6', 1.4, V(-4, 3, -3), 15)

world = bpy.data.worlds.get('World') or bpy.data.worlds.new('World'); scene.world = world
bg = world.node_tree.nodes['Background']
WARM, COOL = col('#fff3e6'), col('#b9c6e6')
bg.inputs['Color'].default_value = WARM; bg.inputs['Strength'].default_value = 0.55

# ---------------------------------------------------------------- render settings
scene.render.engine = 'BLENDER_EEVEE'
scene.render.fps = FPS
scene.frame_start, scene.frame_end = 1, NFRAMES
scene.render.resolution_x, scene.render.resolution_y = (640, 360) if PREVIEW else (1280, 720)
scene.render.resolution_percentage = 100
scene.eevee.taa_render_samples = 8 if PREVIEW else int(arg('--samples', 32))
vts = [i.identifier for i in scene.view_settings.bl_rna.properties['view_transform'].enum_items]
scene.view_settings.view_transform = 'Khronos PBR Neutral' if 'Khronos PBR Neutral' in vts else 'Standard'
scene.view_settings.exposure = -0.35

# ---------------------------------------------------------------- design-screen script (ported from the web version)
OPTIONS = {
    'gender': ['unspecified', 'girl', 'boy'],
    'face': [('round', (1, 1, 1), 1.0), ('oval', (0.92, 1.08, 0.96), 0.85), ('chubby', (1.1, 0.95, 1.04), 1.4)],
    'hair': ['tuft', 'bob', 'pigtails', 'curly'],
    'outfit': ['onesie', 'overalls', 'dress', 'tshirt'],
}
SCRIPT = [
    (4.8, 'next', 1), (6.0, 'tab', 'face'), (7.2, 'next', 1), (8.2, 'next', 1), (9.4, 'tab', 'skin'),
    (10.5, 'drag', [(10.5, 0.5), (11.3, 0.82), (12.4, 0.12)]), (13.4, 'tab', 'hair'), (14.5, 'next', 1),
    (15.5, 'next', 1), (16.5, 'next', -1), (17.6, 'color', 1), (18.8, 'tab', 'outfit'), (19.9, 'next', 1),
    (20.9, 'next', 1), (22.3, 'start', None),
]
def keyed(keys, c):
    for i in range(1, len(keys)):
        if c < keys[i][0]: return lerp(keys[i - 1][1], keys[i][1], smooth(keys[i - 1][0], keys[i][0], c))
    return keys[-1][1]
def creator_state(c):
    st = dict(tab='gender', gender=0, face=0, hair=0, outfit=0, hairColor=0, skin=0.5)
    for at, do, v in SCRIPT:
        if c < at: break
        if do == 'tab': st['tab'] = v
        elif do == 'next': st[st['tab']] = int(clamp(st[st['tab']] + v, 0, len(OPTIONS[st['tab']]) - 1))
        elif do == 'color': st['hairColor'] = v
        elif do == 'drag': st['skin'] = keyed(v, c)
    return st

SKIN_STOPS = [col(h) for h in ['#fde3d3', '#f3cba8', '#e2ab82', '#c58a5f', '#9c6340', '#71432a', '#4b2c1b']]
def skin_at(v):
    x = clamp(v) * (len(SKIN_STOPS) - 1); i = min(len(SKIN_STOPS) - 2, int(x))
    return mix(SKIN_STOPS[i], SKIN_STOPS[i + 1], x - i)
HAIR_COLORS = [col(h) for h in ['#6b4a33', '#1c1514', '#d9aa5f', '#9a4a2c', '#3a2518']]
OUTFITS = {
    'onesie':   dict(top='#ffd46e', belly='#fff2cc', arms='top', legs='#ffd46e', feet='skin'),
    'dress':    dict(top='#f7a1bd', belly='#ffd3e1', arms='skin', legs='skin', feet='#ffffff', skirt=True, sash=True, sleeves=True),
    'overalls': dict(top='#5f86c4', belly='#86a9dd', arms='#ff9e80', legs='#5f86c4', feet='#ffffff'),
    'tshirt':   dict(top='#8fd3b3', belly='#b5e6cf', arms='skin', legs='#6c7fb3', feet='#ffffff', sleeves=True),
}

# ---------------------------------------------------------------- keyframe recorder (bulk-writes fcurves)
class Recorder:
    def __init__(self): self.ch = {}
    def put(self, block, path, values, frame, step=False):
        for i, v in enumerate(values):
            k = (block.as_pointer(), path, i)
            if k not in self.ch: self.ch[k] = (block, path, i, step, [])
            self.ch[k][4].append((frame, float(v)))
    def vis(self, o, visible, frame):
        self.put(o, 'hide_render', [not visible], frame, step=True)
        self.put(o, 'hide_viewport', [not visible], frame, step=True)
    def flush(self):
        for block, path, idx, step, keys in self.ch.values():
            n = len(keys)
            keep = [keys[i] for i in range(n) if i in (0, n - 1) or keys[i][1] != keys[i - 1][1] or keys[i][1] != keys[i + 1][1]]
            ad = block.animation_data or block.animation_data_create()
            if ad.action is None: ad.action = bpy.data.actions.new(block.name + 'Action')
            fc = ad.action.fcurve_ensure_for_datablock(block, path, index=idx)
            fc.keyframe_points.add(len(keep))
            fc.keyframe_points.foreach_set('co', [x for kv in keep for x in kv])
            fc.keyframe_points.foreach_set('interpolation', [0 if step else 1] * len(keep))
            fc.update()
rec = Recorder()

def put_color(m, rgba, f):
    rec.put(m.node_tree, 'nodes["Principled BSDF"].inputs[0].default_value', rgba[:3], f)

def pose_block(i, t):
    T, (Fp, Frz, Fry) = tower[i], fallen[i]
    rs = RESTACK + i * 1.3; back = smooth(rs, rs + 1.0, t)
    if t >= rs:
        p = (lerp(Fp[0], T[0], back), lerp(Fp[1], T[1], back) + sin(pi * back) * 0.6, lerp(Fp[2], T[2], back))
        return p, (0, lerp(Fry, 0, back), lerp(Frz, 0, back)), 1 + 0.12 * sin(pi * smooth(rs + 0.9, rs + 1.3, t))
    fs = 6.0 + (2 - i) * 0.12; fe = fs + (0.5 if i == 0 else 0.85)
    e = clamp((t - fs) / (fe - fs))
    wob = sin((t - 5.6) * 28) * 0.05 * pulse(t, 5.6, fs + 0.05, 0.1) * i if i > 0 else 0
    out = 1 - (1 - e) ** 2
    p = (lerp(T[0], Fp[0], out), lerp(T[1], Fp[1], e * e) + sin(pi * e) * 0.12 * i, lerp(T[2], Fp[2], out))
    return p, (0, lerp(0, Fry, e), lerp(0, Frz, e) + wob), 1.0

camStart, camBase, camClose = (0.9, 2.3, 7.4), (0.9, 1.6, 5.0), (0.7, 1.5, 3.9)
camCreator, tgtCreator = (0.85, 1.45, 5.0), (0.85, 0.8, 0)
tgtBase, tgtClose = (1.0, 0.85, 0.3), (0.65, 1.1, 0.2)
vlerp = lambda a, b, k: tuple(lerp(x, y, k) for x, y in zip(a, b))
pop_times = [at - INTRO for at, do, _ in SCRIPT if do in ('next', 'color')]
hair_meshes = {k: descendants_meshes(g) for k, g in hairStyles.items()}
bow_meshes = descendants_meshes(bow); sash_meshes = descendants_meshes(sash)

def animate(f):
    g = (f - 1) / FPS; t = g - INTRO
    worried = pulse(t, 7.3, 15.0, 0.5) + pulse(t, 23.0, 26.4, 0.5)
    sadW = smooth(14.35, 15.1, t) * (1 - smooth(22.6, 23.2, t))
    happyW = smooth(26.1, 26.8, t) * (1 - smooth(38.6, 39.8, t))
    lookTower = pulse(t, 3.2, 7.6, 0.5)
    watch = pulse(t, 28.0, 32.2, 0.5)
    surprise = pulse(t, 6.3, 7.4, 0.3)

    # camera
    close = sadW * 0.9 + pulse(t, 26.4, 28.2, 0.5) * 0.55 + pulse(t, 35.6, 40, 1.2) * 0.3
    if t < 0:
        cp = vlerp(camStart, camCreator, smooth(-INTRO, -INTRO + 4, t)); tp = tgtCreator
    else:
        k = smooth(0, 3.5, t)
        cp = vlerp(vlerp(camCreator, camBase, k), camClose, close)
        tp = vlerp(vlerp(tgtCreator, tgtBase, k), tgtClose, close)
    cp = (cp[0] + sin(t * 0.35) * 0.12, cp[1], cp[2])
    rec.put(camera, 'location', V(*cp), f); rec.put(cam_target, 'location', V(*tp), f)

    # mood lighting
    rec.put(key, 'energy', [lerp(KEY_ENERGY, KEY_ENERGY * 0.42, sadW) + 0.4 * happyW], f)
    rec.put(world.node_tree, 'nodes["Background"].inputs[0].default_value', mix(WARM, COOL, sadW)[:3], f)

    # look (design screen)
    st = creator_state(g)
    O = OUTFITS[OPTIONS['outfit'][st['outfit']]]
    _, fscale, fcheek = OPTIONS['face'][st['face']]
    sk = skin_at(st['skin'])
    paint = lambda c: sk if c == 'skin' else col(O['top'] if c == 'top' else c)
    put_color(skin, sk, f); put_color(hairMat, HAIR_COLORS[st['hairColor']], f)
    put_color(outfitTop, col(O['top']), f); put_color(bellyMat, col(O['belly']), f)
    put_color(outfitArms, paint(O['arms']), f); put_color(outfitLegs, paint(O['legs']), f); put_color(footMat, paint(O['feet']), f)
    rec.vis(belly, not O.get('skirt'), f); rec.vis(skirt, bool(O.get('skirt')), f); rec.vis(hem, bool(O.get('skirt')), f)
    for m in sash_meshes: rec.vis(m, bool(O.get('sash')), f)
    for m in sleeves: rec.vis(m, bool(O.get('sleeves')), f)
    for name, ms in hair_meshes.items():
        for m in ms: rec.vis(m, name == OPTIONS['hair'][st['hair']], f)
    for m in bow_meshes: rec.vis(m, OPTIONS['gender'][st['gender']] == 'girl', f)
    for c in cheeks: rec.put(c, 'scale', S3(fcheek, 0.7 * fcheek, 0.35), f)

    pop = max(pulse(t, a, a + 0.5, 0.2) for a in pop_times)
    turntable = smooth(-INTRO + 3, -INTRO + 5, t) * (1 - smooth(-1.5, 0, t))

    # body
    rec.put(baby, 'rotation_euler', R3(0, -0.35 * sadW + 0.2 * watch * happyW + sin(t * 0.9) * 0.45 * turntable, 0), f)
    bpy_ = abs(sin(t * 6)) * 0.07 * happyW * (1 - watch * 0.6) + 0.07 * surprise
    rec.put(bodyPivot, 'location', V(0, bpy_, 0), f)
    k = 1 + 0.07 * pop
    rec.put(bodyPivot, 'scale', S3((1 + 0.03 * sadW) * k, (1 - 0.06 * sadW) * (1 + 0.012 * sin(t * 2.2)) * k, k), f)
    rec.put(bodyPivot, 'rotation_euler', R3(0.08 * sadW, 0, 0), f)

    # head (face shape = head scale)
    rec.put(head, 'scale', S3(*fscale), f)
    rec.put(head, 'rotation_euler', R3(
        0.14 * lookTower + 0.32 * sadW + 0.1 * watch * happyW,
        0.55 * lookTower + 0.45 * watch * happyW,
        0.13 * worried + 0.1 * sadW + sin(t * 4) * 0.14 * happyW * (1 - watch)), f)

    # arms
    reach = smooth(3.8, 5.2, t) * (1 - smooth(6.0, 6.8, t)); tap = pulse(t, 5.4, 5.9, 0.2)
    for s in (-1, 1):
        z = 0.35 + (0.75 * reach if s > 0 else 0) + 0.6 * surprise
        x = -0.3 - (0.9 * reach + 0.25 * tap if s > 0 else 0) - 0.5 * surprise - 0.25 * worried
        z = lerp(z, 0.1, sadW); x = lerp(x, -0.75, sadW)
        z = lerp(z, 2.2 + 0.35 * sin(t * 9 + s), happyW * (1 - watch * 0.7))
        rec.put(arms[s], 'rotation_euler', R3(x, 0, s * z), f)

    # face
    curve = -0.7
    curve = lerp(curve, 0.1, worried); curve = lerp(curve, 1.0, sadW); curve = lerp(curve, -1.4, happyW)
    if abs(curve) < 0.18: curve = -0.18 if curve < 0 else 0.18
    rec.put(mouth, 'scale', S3(1 + 0.35 * happyW - 0.2 * sadW, curve, 1), f)
    rec.put(mouth, 'location', V(0, -0.19 - 0.02 * sadW, 0.51), f)
    blink = 0.1 if (t % 3.3) < 0.12 else 1
    for s in (-1, 1):
        rec.put(eyes[s], 'scale', S3(1, blink * lerp(1, 0.5, happyW) * (1 + 0.25 * surprise), 1), f)
        rec.put(eyes[s], 'location', V(s * 0.2, 0.05 - 0.025 * sadW, 0.485), f)
        rec.put(brows[s], 'rotation_euler', R3(0, 0, -s * (0.25 * worried + 0.45 * sadW - 0.1 * happyW)), f)
        rec.put(brows[s], 'location', V(s * 0.2, 0.2 + 0.03 * worried + 0.03 * happyW + 0.04 * surprise, 0.468), f)

    for i, tear in enumerate(tears):
        s = -1 if i else 1
        c = (((t - 16) + i * 0.7) % 1.4) / 1.4
        y = -0.05 - c * 0.3; x = s * 0.24
        rec.put(tear, 'location', V(x, y, sqrt(max(0, 0.55 ** 2 - x * x - y * y)) + 0.015), f)
        vis = sin(pi * c) * sadW if within(t, 16, 22.4) else 0
        sc = (0.6 + 0.4 * min(1, c * 4)) * clamp(vis * 1.5)
        rec.put(tear, 'scale', S3(sc, sc * 1.35, sc), f)

    for i, b in enumerate(blocks):
        p, r, sc = pose_block(i, t)
        if t < 0: sc = max(0.001, smooth(-1.2, -0.2, t))
        rec.put(b, 'location', V(*p), f); rec.put(b, 'rotation_euler', R3(*r), f); rec.put(b, 'scale', (sc, sc, sc), f)

    head_y = bpy_ + 1.33 * (1 - 0.06 * sadW)
    for i, h in enumerate(hearts):
        life = (t * 0.45 + i / len(hearts)) % 1
        rec.put(h, 'location', V(sin(i * 2.1) * 0.75, head_y + 0.2 + life * 1.3, 0.2), f)
        sc = sin(pi * life) * happyW * (0.2 + 0.05 * sin(t * 5 + i)) * 1.6
        rec.put(h, 'scale', (max(sc, 0.0001),) * 3, f)

for h in hearts:
    c = h.constraints.new('TRACK_TO'); c.target = camera; c.track_axis = 'TRACK_NEGATIVE_Y'; c.up_axis = 'UP_Z'

print('baking keyframes…')
for f in range(1, NFRAMES + 1): animate(f)
rec.flush()
scene.frame_set(1)

blend = os.path.join(HERE, 'baby-sim.blend')
bpy.ops.wm.save_as_mainfile(filepath=blend)
print('saved', blend)

# ---------------------------------------------------------------- render
out = os.path.join(HERE, 'renders')
os.makedirs(out, exist_ok=True)
if arg('--stills'):
    for g in [float(x) for x in arg('--stills').split(',')]:
        f = int(round(g * FPS)) + 1
        scene.frame_set(f)
        scene.render.filepath = os.path.join(out, f'still_{g:05.1f}s.png')
        bpy.ops.render.render(write_still=True)
if '--anim' in argv:
    scene.frame_step = int(arg('--every', 1))
    scene.render.image_settings.file_format = 'PNG'
    scene.render.filepath = os.path.join(out, 'frames', '')
    bpy.ops.render.render(animation=True)
