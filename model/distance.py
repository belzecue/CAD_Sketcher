import logging

import math
from bpy.types import PropertyGroup
from bpy.props import BoolProperty, FloatProperty, EnumProperty
from bpy.utils import register_classes_factory
from mathutils import Vector, Matrix
from mathutils.geometry import distance_point_to_plane, intersect_point_line

from .. import functions
from ..solver import Solver
from ..utilities import preferences
from ..global_data import WpReq
from ..functions import location_3d_to_region_2d
from .base_constraint import GenericConstraint
from .utilities import slvs_entity_pointer
from .categories import point, line, point_2d, curve

from .workplane import SlvsWorkplane
from .point_3d import SlvsPoint3D
from .line_3d import SlvsLine3D
from .point_2d import SlvsPoint2D
from .line_2d import SlvsLine2D
from .arc import SlvsArc
from .circle import SlvsCircle

logger = logging.getLogger(__name__)


def get_side_of_line(line_start, line_end, point):
    line_end = line_end - line_start
    point = point - line_start
    return -(
        (line_end.x - line_start.x) * (point.y - line_start.y)
        - (line_end.y - line_start.y) * (point.x - line_start.x)
    )


align_items = [
    ("NONE", "None", "", 0),
    ("HORIZONTAL", "Horizontal", "", 1),
    ("VERTICAL", "Vertical", "", 2),
]


class SlvsDistance(GenericConstraint, PropertyGroup):
    """Sets the distance between a point and some other entity (point/line/Workplane)."""

    def get_distance_value(self):
        return self.get("value", self.rna_type.properties["value"].default)

    def set_distance_value(self, value):
        self["value"] = abs(value)

    label = "Distance"
    value: FloatProperty(
        name=label,
        subtype="DISTANCE",
        unit="LENGTH",
        update=GenericConstraint.update_system_cb,
        get=get_distance_value,
        set=set_distance_value,
    )
    flip: BoolProperty(name="Flip", update=GenericConstraint.update_system_cb)
    align: EnumProperty(
        name="Align",
        items=align_items,
        update=GenericConstraint.update_system_cb,
    )
    draw_offset: FloatProperty(name="Draw Offset", default=0.3)
    draw_outset: FloatProperty(name="Draw Outset", default=0.0)
    type = "DISTANCE"
    signature = ((*point, *line, SlvsCircle, SlvsArc), (*point, *line, SlvsWorkplane))
    props = ("value",)

    @classmethod
    def get_types(cls, index, entities):
        e = entities[1] if index == 0 else entities[0]

        if e:
            if index == 1 and e.is_line():
                # Allow constraining a single line
                return None
            if e.is_3d():
                return ((SlvsPoint3D,), (SlvsPoint3D, SlvsLine3D, SlvsWorkplane))[index]
            return (point_2d, (*point_2d, SlvsLine2D))[index]
        return cls.signature[index]

    def needs_wp(self):
        if isinstance(self.entity2, SlvsWorkplane):
            return WpReq.FREE
        return WpReq.OPTIONAL

    def use_flipping(self):
        # Only use flipping for constraint between point and line/workplane
        if self.entity1.is_curve():
            return False
        return type(self.entity2) in (*line, SlvsWorkplane)

    def use_align(self):
        if type(self.entity2) in (*line, SlvsWorkplane):
            return False
        if self.entity1.is_curve():
            return False
        return True

    def get_value(self):
        value = self.value
        if self.use_flipping() and self.flip:
            return value * -1
        return value

    def create_slvs_data(self, solvesys, group=Solver.group_fixed):
        if self.entity1 == self.entity2:
            raise AttributeError("Cannot create constraint between one entity itself")
        # TODO: don't allow Distance if Point -> Line if (Point in Line)

        e1, e2 = self.entity1, self.entity2
        if e1.is_line():
            e1, e2 = e1.p1, e1.p2

        func = None
        set_wp = False
        wp = self.get_workplane()
        alignment = self.align
        align = self.use_align() and alignment != "NONE"
        handles = []

        value = self.get_value()

        # circle/arc -> line/point
        if type(e1) in curve:
            # TODO: make Horizontal and Vertical alignment work
            if type(e2) in line:
                return solvesys.addPointLineDistance(
                    value + e1.radius, e1.ct.py_data, e2.py_data, wp, group
                )
            else:
                assert isinstance(e2, SlvsPoint2D)
                return solvesys.addPointsDistance(
                    value + e1.radius, e1.ct.py_data, e2.py_data, wp, group
                )

        elif type(e2) in line:
            func = solvesys.addPointLineDistance
            set_wp = True
        elif isinstance(e2, SlvsWorkplane):
            func = solvesys.addPointPlaneDistance
        elif type(e2) in point:
            if align and all([e.is_2d() for e in (e1, e2)]):
                # Get Point in between
                p1, p2 = e1.co, e2.co
                coords = (p2.x, p1.y)

                params = [solvesys.addParamV(v, group) for v in coords]
                p = solvesys.addPoint2d(wp, *params, group=group)

                handles.append(
                    solvesys.addPointsHorizontal(p, e2.py_data, wp, group=group)
                )
                handles.append(
                    solvesys.addPointsVertical(p, e1.py_data, wp, group=group)
                )

                base_point = e1 if alignment == "VERTICAL" else e2
                handles.append(
                    solvesys.addPointsDistance(
                        value, p, base_point.py_data, wrkpln=wp, group=group
                    )
                )
                return handles
            else:
                func = solvesys.addPointsDistance
            set_wp = True

        kwargs = {
            "group": group,
        }

        if set_wp:
            kwargs["wrkpln"] = self.get_workplane()

        return func(value, e1.py_data, e2.py_data, **kwargs)

    def matrix_basis(self):
        if self.sketch_i == -1 or not self.entity1.is_2d():
            # TODO: Support distance in 3d
            return Matrix()

        sketch = self.sketch
        x_axis = Vector((1, 0))
        alignment = self.align
        align = self.use_align() and alignment != "NONE"

        e1, e2 = self.entity1, self.entity2
        #   e1       e2
        #   ----------------
        #   line     [none]
        #   point    point
        #   point    line
        #   arc      point
        #   arc      line
        #   circle   point
        #   circle   line

        # set p1 and p2
        if e1.is_curve():
            # reframe as point->point and continue
            centerpoint = e1.ct.co
            if e2.is_line():
                p2, _ = intersect_point_line(centerpoint, e2.p1.co, e2.p2.co)
            else:
                assert isinstance(e2, SlvsPoint2D)
                p2 = e2.co
            if (p2 - centerpoint).length > 0:
                vec = (p2 - centerpoint) / (p2 - centerpoint).length
                p1 = centerpoint + (e1.radius * Vector(vec))
            else:
                # This is a curve->line where the centerpoint of the curve is
                # coincident with the line.  By reassigning p1 to an endpoint
                # of the line, we avoid p1=p2 errors and the result is
                # (correctly) an invalid constraint
                p1 = e2.p1.co
        elif e1.is_line():
            # reframe as point->point and continue
            e1, e2 = e1.p1, e1.p2
            p1, p2 = e1.co, e2.co
        else:
            assert isinstance(e1, SlvsPoint2D)
            p1 = e1.co

        if type(e2) in point_2d:
            # this includes "Line Length" (now point->point)
            # and curve -> point
            p2 = e2.co
            if not align:
                v_rotation = p2 - p1
            else:
                v_rotation = (
                    Vector((1.0, 0.0))
                    if alignment == "HORIZONTAL"
                    else Vector((0.0, 1.0))
                )
            angle = v_rotation.angle_signed(x_axis)
            mat_rot = Matrix.Rotation(angle, 2, "Z")
            v_translation = (p2 + p1) / 2

        elif e2.is_line():
            # curve -> line
            # or point -> line
            if e1.is_curve():
                if not align:
                    v_rotation = p2 - p1
                else:
                    v_rotation = (
                        Vector((1.0, 0.0))
                        if alignment == "HORIZONTAL"
                        else Vector((0.0, 1.0))
                    )
                if v_rotation.length != 0:
                    angle = v_rotation.angle_signed(x_axis)
                else:
                    angle = 0
                mat_rot = Matrix.Rotation(angle, 2, "Z")
                v_translation = (p2 + p1) / 2
            else:
                assert isinstance(e1, SlvsPoint2D)
                orig = e2.p1.co
                end = e2.p2.co
                vec = end - orig
                angle = (math.tau / 4) + functions.range_2pi(math.atan2(vec[1], vec[0]))
                mat_rot = Matrix.Rotation(angle, 2, "Z")
                p1 = p1 - orig
                v_translation = orig + (p1 + p1.project(vec)) / 2

        mat_local = Matrix.Translation(v_translation.to_3d()) @ mat_rot.to_4x4()
        return sketch.wp.matrix_basis @ mat_local

    def init_props(self, **kwargs):
        # Set initial distance value to the current spacing
        e1, e2 = self.entity1, self.entity2
        if e1.is_line():
            value = e1.length
        elif type(e1) in curve:
            centerpoint = e1.ct.co
            if isinstance(e2, SlvsLine2D):
                endpoint, _ = intersect_point_line(centerpoint, e2.p1.co, e2.p2.co)
            else:
                assert isinstance(e2, SlvsPoint2D)
                endpoint = e2.co
            value = (centerpoint - endpoint).length - e1.radius
        elif isinstance(e2, SlvsWorkplane):
            # Returns the signed distance to the plane
            value = distance_point_to_plane(e1.location, e2.p1.location, e2.normal)
        elif type(e2) in line:
            orig = e2.p1.location
            end = e2.p2.location - orig
            p1 = e1.location - orig
            value = (p1 - (p1).project(end)).length

            # NOTE: Comment from solvespace documentation:
            # When constraining the distance between a point and a plane,
            # or a point and a plane face, or a point and a line in a workplane,
            # the distance is signed. The distance may be positive or negative,
            # depending on whether the point is above or below the plane.
            # The distance is always shown positive on the sketch;
            # to flip to the other side, enter a negative value.
            value = math.copysign(
                value,
                get_side_of_line(e2.p1.location, e2.p2.location, e1.location),
            )
        else:
            value = (e1.location - e2.location).length

        if self.use_flipping() and value < 0:
            value = abs(value)
            self.flip = not self.flip

        self.value = value
        return value, None

    def text_inside(self, ui_scale):
        return (ui_scale * abs(self.draw_outset)) < self.value / 2

    def update_draw_offset(self, pos, ui_scale):
        self.draw_offset = pos[1] / ui_scale
        self.draw_outset = pos[0] / ui_scale

    def draw_props(self, layout):
        sub = super().draw_props(layout)

        sub.prop(self, "value")

        row = sub.row()
        row.active = self.use_flipping()
        row.prop(self, "flip")

        sub.label(text="Alignment:")
        row = sub.row()
        row.active = self.use_align()
        row.prop(self, "align", text="")

        if preferences.is_experimental():
            sub.prop(self, "draw_offset")

        return sub

    def value_placement(self, context):
        """location to display the constraint value"""
        region = context.region
        rv3d = context.space_data.region_3d
        ui_scale = context.preferences.system.ui_scale

        offset = ui_scale * self.draw_offset
        outset = ui_scale * self.draw_outset
        coords = self.matrix_basis() @ Vector((outset, offset, 0))
        return location_3d_to_region_2d(region, rv3d, coords)


slvs_entity_pointer(SlvsDistance, "entity1")
slvs_entity_pointer(SlvsDistance, "entity2")
slvs_entity_pointer(SlvsDistance, "sketch")

register, unregister = register_classes_factory((SlvsDistance,))
