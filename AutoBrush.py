
bl_info = {
    "name": "Texture Paint World Radius Debug",
    "author": "pilotRL",
    "version": (2, 0, 0),
    "blender": (5, 1, 1),
    "location": "View3D > Sidebar > Brush Helper",
    "description": "Adjust Texture Paint brush size using focus-object distance",
    "category": "Paint",
}

import bpy
import math
from mathutils import Vector
from bpy_extras import view3d_utils

def find_viewport():
    """Find a 3D View and its main drawing region."""

    context = bpy.context

    if context.area and context.area.type == 'VIEW_3D':
        area = context.area
        region = next(
            (r for r in area.regions if r.type == 'WINDOW'),
            None,
        )
        if region:
            return area, region, area.spaces.active.region_3d

    wm = context.window_manager

    for window in wm.windows:
        if window.screen is None:
            continue

        for area in window.screen.areas:
            if area.type != 'VIEW_3D':
                continue

            region = next(
                (r for r in area.regions if r.type == 'WINDOW'),
                None,
            )

            if region:
                return area, region, area.spaces.active.region_3d

    return None, None, None


def get_world_center(obj):
    """Calculate the focus object's world-space bounding-box center."""

    corners = [
        obj.matrix_world @ Vector(corner)
        for corner in obj.bound_box
    ]

    if not corners:
        return obj.matrix_world.translation.copy()

    return sum(corners, Vector()) / len(corners)

LAST_MOUSE = {"x": None, "y": None}

def get_surface_point(context, region, rv3d, focus):
    """Raycast from the mouse (or region center) onto the focus object."""

    if LAST_MOUSE["x"] is not None:
        coord = Vector((
            LAST_MOUSE["x"] - region.x,
            LAST_MOUSE["y"] - region.y,
        ))
        if not (0 <= coord.x <= region.width and 0 <= coord.y <= region.height):
            coord = Vector((region.width / 2, region.height / 2))
    else:
        coord = Vector((region.width / 2, region.height / 2))

    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)

    inv = focus.matrix_world.inverted()
    origin_local = inv @ origin
    direction_local = (inv.to_3x3() @ direction).normalized()

    depsgraph = context.evaluated_depsgraph_get()
    hit, location, normal, index = focus.ray_cast(
        origin_local, direction_local, depsgraph=depsgraph
    )

    if hit:
        return focus.matrix_world @ location, True

    return get_world_center(focus), False


def calculate_brush_size(context, region, rv3d, focus, world_radius):
    """Brush diameter in px for a world-space radius at the surface point."""

    point, _hit = get_surface_point(context, region, rv3d, focus)

    view_matrix = rv3d.view_matrix
    view_position = view_matrix.inverted().translation.copy()
    distance = (point - view_position).length

    if region.width <= 0 or region.height <= 0:
        return distance, None

    point_view = view_matrix @ point
    if rv3d.view_perspective == 'PERSP' and point_view.z >= -0.00001:
        return distance, None

    right = rv3d.view_rotation @ Vector((1.0, 0.0, 0.0))
    up = rv3d.view_rotation @ Vector((0.0, 1.0, 0.0))

    p2d = view3d_utils.location_3d_to_region_2d(region, rv3d, point)
    r2d = view3d_utils.location_3d_to_region_2d(region, rv3d, point + right * world_radius)
    u2d = view3d_utils.location_3d_to_region_2d(region, rv3d, point + up * world_radius)

    if p2d is None or r2d is None or u2d is None:
        return distance, None

    radius_px = ((r2d - p2d).length + (u2d - p2d).length) / 2.0
    diameter = max(1, min(5000, round(radius_px * 2)))

    return distance, diameter

def refresh_viewports():
    wm = bpy.context.window_manager

    for window in wm.windows:
        if window.screen is None:
            continue

        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

def update_texture_brush():
    if not hasattr(bpy.types.Scene, "tp_world_enabled"):
        return None

    context = bpy.context
    scene = context.scene

    if scene is None:
        return 0.1

    focus = scene.tp_world_focus

    try:
        brush = context.tool_settings.image_paint.brush
    except (AttributeError, RuntimeError):
        brush = None

    if brush is not None:
        scene.tp_world_actual = brush.size
    else:
        scene.tp_world_actual = 0

    if focus is None:
        scene.tp_world_status = "Select a Focus Object"
        refresh_viewports()
        return 0.1

    if focus.type != 'MESH':
        scene.tp_world_status = "Focus object must be a mesh"
        refresh_viewports()
        return 0.1

    area, region, rv3d = find_viewport()

    if area is None or region is None or rv3d is None:
        scene.tp_world_status = "ERROR: No 3D View found"
        refresh_viewports()
        return 0.1

    try:
        distance, calculated = calculate_brush_size(
            context,
            region,
            rv3d,
            focus,
            scene.tp_world_radius,
        )
    except Exception as exc:
        scene.tp_world_status = f"Calculation error: {exc}"
        refresh_viewports()
        return 0.1

    scene.tp_world_distance = distance

    if calculated is None:
        scene.tp_world_calculated = 0
        scene.tp_world_status = "Invalid view depth"
        refresh_viewports()
        return 0.1

    scene.tp_world_calculated = calculated

    if not scene.tp_world_enabled:
        scene.tp_world_status = "Calculation ready; auto update is OFF"

    elif context.mode != 'PAINT_TEXTURE':
        scene.tp_world_status = (
            f"Mode is {context.mode}; switch to Texture Paint"
        )

    elif brush is None:
        scene.tp_world_status = (
            "No Texture Paint brush found"
        )

    else:
        if brush.size != calculated:
            brush.size = calculated

        scene.tp_world_actual = brush.size

        if brush.size == calculated:
            scene.tp_world_status = "OK: Texture Paint brush updated"
        else:
            scene.tp_world_status = "ERROR: Brush size did not update"

    if (
        abs(distance - scene.tp_world_last_distance) > 0.001
        or calculated != scene.tp_world_last_calculated
        or scene.tp_world_status != scene.tp_world_last_status
    ):
        print(
            "[Texture Paint World Radius] "
            f"Status={scene.tp_world_status} | "
            f"Distance={distance:.5f} BU | "
            f"Actual={scene.tp_world_actual} px | "
            f"Calculated={calculated} px | "
            f"Radius={scene.tp_world_radius:.5f} BU"
        )

        scene.tp_world_last_distance = distance
        scene.tp_world_last_calculated = calculated
        scene.tp_world_last_status = scene.tp_world_status

    refresh_viewports()
    return 0.1

class VIEW3D_OT_tp_track_mouse(bpy.types.Operator):
    bl_idname = "view3d.tp_track_mouse"
    bl_label = "Start Mouse Tracking"

    def modal(self, context, event):
        if not hasattr(bpy.types.Scene, "tp_world_enabled"):
            return {'CANCELLED'}
        if event.type == 'MOUSEMOVE':
            LAST_MOUSE["x"] = event.mouse_x
            LAST_MOUSE["y"] = event.mouse_y
        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

class VIEW3D_PT_texture_paint_world_radius(bpy.types.Panel):
    bl_label = "Texture Paint World Radius"
    bl_idname = "VIEW3D_PT_texture_paint_world_radius"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Brush Helper"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        layout.prop(
            scene,
            "tp_world_focus",
            text="Focus Object",
        )

        layout.prop(
            scene,
            "tp_world_radius",
            text="Target World Radius",
        )

        layout.prop(
            scene,
            "tp_world_enabled",
            text="Apply Automatically",
        )

        layout.operator("view3d.tp_track_mouse", icon='RESTRICT_SELECT_OFF')

        layout.separator()

        box = layout.box()
        box.label(text="LIVE DEBUG", icon='CONSOLE')
        box.label(text=f"Status: {scene.tp_world_status}")
        box.label(
            text=f"Distance: {scene.tp_world_distance:.5f} BU"
        )
        box.label(
            text=f"Actual Brush: {scene.tp_world_actual} px"
        )
        box.label(
            text=f"Calculated Brush: {scene.tp_world_calculated} px"
        )

        layout.separator()
        layout.label(text="BU = Blender world units")
        layout.label(text="Texture Paint mode only")

CLASSES = (
    VIEW3D_OT_tp_track_mouse,
    VIEW3D_PT_texture_paint_world_radius,
)

PROPERTY_NAMES = (
    "tp_world_focus",
    "tp_world_radius",
    "tp_world_enabled",
    "tp_world_status",
    "tp_world_distance",
    "tp_world_actual",
    "tp_world_calculated",
    "tp_world_last_distance",
    "tp_world_last_calculated",
    "tp_world_last_status",
)


def register():
    for name in PROPERTY_NAMES:
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)

    bpy.types.Scene.tp_world_focus = bpy.props.PointerProperty(
        name="Focus Object",
        description="Object used as the distance reference",
        type=bpy.types.Object,
    )

    bpy.types.Scene.tp_world_radius = bpy.props.FloatProperty(
        name="Target World Radius",
        description="Desired radius in Blender world units",
        default=0.1,
        min=0.0001,
        max=10000.0,
        precision=4,
        unit='LENGTH',
    )

    bpy.types.Scene.tp_world_enabled = bpy.props.BoolProperty(
        name="Apply Automatically",
        description="Automatically change the Texture Paint brush size",
        default=False,
    )

    bpy.types.Scene.tp_world_status = bpy.props.StringProperty(
        default="Waiting for focus object",
    )

    bpy.types.Scene.tp_world_distance = bpy.props.FloatProperty(
        default=0.0,
        precision=5,
    )

    bpy.types.Scene.tp_world_actual = bpy.props.IntProperty(
        default=0,
    )

    bpy.types.Scene.tp_world_calculated = bpy.props.IntProperty(
        default=0,
    )

    bpy.types.Scene.tp_world_last_distance = bpy.props.FloatProperty(
        default=-1.0,
    )

    bpy.types.Scene.tp_world_last_calculated = bpy.props.IntProperty(
        default=-1,
    )

    bpy.types.Scene.tp_world_last_status = bpy.props.StringProperty(
        default="",
    )

    for cls in CLASSES:
        bpy.utils.register_class(cls)

    if bpy.app.timers.is_registered(update_texture_brush):
        bpy.app.timers.unregister(update_texture_brush)

    bpy.app.timers.register(
        update_texture_brush,
        first_interval=0.2,
        persistent=True,
    )


def unregister():
    if bpy.app.timers.is_registered(update_texture_brush):
        bpy.app.timers.unregister(update_texture_brush)

    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass

    for name in PROPERTY_NAMES:
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)


if __name__ == "__main__":
    register()
