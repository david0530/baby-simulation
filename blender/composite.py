"""
Combine the 3D frames (renders/frames) with the 2D UI overlay frames (overlay_frames)
in Blender's video sequencer and write an MP4.

  Blender -b --factory-startup -P composite.py -- [--no-overlay] [--out name.mp4]
"""
import bpy, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
out_name = argv[argv.index('--out') + 1] if '--out' in argv else 'baby-sim-blender.mp4'

scene = bpy.context.scene
scene.render.fps = 24
scene.view_settings.view_transform = 'Standard'   # frames are already tone-mapped; don't apply AgX twice
scene.view_settings.look = 'None'
scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1280, 720, 100
se = scene.sequence_editor_create()
strips = se.strips if hasattr(se, 'strips') else se.sequences

def image_strip(folder, channel):
    files = sorted(f for f in os.listdir(folder) if f.endswith('.png'))
    s = strips.new_image(name=os.path.basename(folder), filepath=os.path.join(folder, files[0]), channel=channel, frame_start=1)
    for f in files[1:]: s.elements.append(f)
    return s, len(files)

base, n = image_strip(os.path.join(HERE, 'renders', 'frames'), 1)
overlay_dir = os.path.join(HERE, 'overlay_frames')
if '--no-overlay' not in argv and os.path.isdir(overlay_dir):
    ov, _ = image_strip(overlay_dir, 2)
    ov.blend_type = 'ALPHA_OVER'
    ov.frame_final_end = base.frame_final_end

scene.frame_start, scene.frame_end = 1, n
r = scene.render
r.use_sequencer = True
if hasattr(r.image_settings, 'media_type'): r.image_settings.media_type = 'VIDEO'
r.image_settings.file_format = 'FFMPEG'
r.ffmpeg.format = 'MPEG4'
r.ffmpeg.codec = 'H264'
r.ffmpeg.constant_rate_factor = 'HIGH'
r.ffmpeg.ffmpeg_preset = 'GOOD'
r.filepath = os.path.join(HERE, out_name)
bpy.ops.render.render(animation=True)
print('wrote', r.filepath)
