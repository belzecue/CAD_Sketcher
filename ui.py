import bpy
from bpy.types import Panel, Menu, UIList
from . import operators, functions


class VIEW3D_UL_sketches(UIList):
    def draw_item(
        self, context, layout, data, item, icon, active_data, active_propname
    ):
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            if item:

                row = layout.row(align=True)
                row.alignment = "LEFT"
                row.prop(
                    item,
                    "visible",
                    icon_only=True,
                    icon=("HIDE_OFF" if item.visible else "HIDE_ON"),
                    emboss=False,
                )
                row.prop(item, "name", text="", emboss=False, icon_value=icon)

                row = layout.row()
                row.alignment = "RIGHT"

                if item.solver_state != "OKAY":
                    row.operator(
                        operators.View3D_OT_slvs_show_solver_state.bl_idname,
                        text="",
                        emboss=False,
                        icon_value=layout.enum_item_icon(
                            item, "solver_state", item.solver_state
                        ),
                    ).index = item.slvs_index

                row.operator(
                    operators.View3D_OT_slvs_set_active_sketch.bl_idname,
                    icon="OUTLINER_DATA_GP_LAYER",
                    text="",
                    emboss=False,
                ).index = item.slvs_index

                # row.operator(
                #     operators.View3D_OT_slvs_delete_entity.bl_idname,
                #     text="",
                #     icon="X",
                #     emboss=False,
                # ).index = item.slvs_index

            else:
                layout.label(text="", translate=False, icon_value=icon)
        elif self.layout_type in {"GRID"}:
            layout.alignment = "CENTER"
            layout.label(text="", icon_value=icon)


class VIEW3D_PT_sketcher(Panel):
    bl_label = "Sketcher"
    bl_idname = "VIEW3D_PT_sketcher"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Sketcher"

    def draw(self, context):
        layout = self.layout

        sketch_selector(context, layout, show_selector=False)
        sketch = context.scene.sketcher.active_sketch
        layout.use_property_split = True
        layout.use_property_decorate = False

        if sketch:

            if sketch.solver_state != "OKAY":
                state = sketch.get_solver_state()

                row = layout.row()
                row.alignment = "CENTER"
                row.scale_y = 1.2
                row.operator(
                    operators.View3D_OT_slvs_show_solver_state.bl_idname,
                    text=state.name,
                    icon=state.icon,
                    emboss=False,
                ).index = sketch.slvs_index

            row = layout.row()
            row.prop(sketch, "name")
            layout.prop(sketch, "convert_type")
            if sketch.convert_type != "NONE":
                layout.prop(sketch, "fill_shape")

            layout.operator(
                operators.View3D_OT_slvs_delete_entity.bl_idname,
                text="Delete Sketch",
                icon="X",
            ).index = sketch.slvs_index

        else:
            layout.template_list(
                "VIEW3D_UL_sketches",
                "",
                context.scene.sketcher.entities,
                "sketches",
                context.scene.sketcher,
                "ui_active_sketch",
            )

        layout.separator()

        layout.label(text="Constraints:")
        col = layout.column(align=True)
        for op in operators.constraint_operators:
            col.operator(op.bl_idname)

        prefs = functions.get_prefs()
        if prefs.show_debug_settings:
            layout.use_property_split = False
            layout.separator()
            layout.label(text="Debug:")
            layout.operator(operators.VIEW3D_OT_slvs_write_selection_texture.bl_idname)
            layout.operator(operators.View3D_OT_slvs_solve.bl_idname)
            layout.operator(
                operators.View3D_OT_slvs_solve.bl_idname, text="Solve All"
            ).all = True
            layout.prop(context.scene.sketcher, "show_origin")
            layout.prop(prefs, "fade_inactive_geometry")
            layout.prop(prefs, "hide_inactive_constraints")


class VIEW3D_MT_sketches(Menu):
    bl_label = "Sketches"
    bl_idname = "VIEW3D_MT_sketches"

    def draw(self, context):
        layout = self.layout
        sse = context.scene.sketcher.entities
        layout.operator(
            operators.View3D_OT_slvs_add_sketch.bl_idname
        ).wait_for_input = True

        if len(sse.sketches):
            layout.separator()

        for i, sk in enumerate(sse.sketches):
            layout.operator(
                operators.View3D_OT_slvs_set_active_sketch.bl_idname, text=sk.name
            ).index = sk.slvs_index


def sketch_selector(context, layout, is_header=False, show_selector=True):
    row = layout.row(align=is_header)
    index = context.scene.sketcher.active_sketch_i
    name = "Sketches"

    scale_y = 1 if is_header else 1.8

    if index != -1:
        sketch = context.scene.sketcher.active_sketch
        name = sketch.name

        row.operator(
            operators.View3D_OT_slvs_set_active_sketch.bl_idname,
            text="Leave: " + name,
            icon="BACK",
            depress=True,
        ).index = -1

        row.active = True
        row.scale_y = scale_y

    else:
        row.scale_y = scale_y
        # TODO: Don't show text when is_header
        row.operator(
            operators.View3D_OT_slvs_add_sketch.bl_idname, icon="ADD"
        ).wait_for_input = True

        if not is_header:
            row = layout.row()
        if show_selector:
            row.menu(VIEW3D_MT_sketches.bl_idname, text=name)


class SKETCHER_MT_theme_presets(Menu):
    bl_label = "Theme Presets"
    preset_subdir = "bgs/theme"
    preset_operator = "script.execute_preset"
    draw = Menu.draw_preset


from bl_ui.utils import PresetPanel


class SKETCHER_PT_theme_presets(PresetPanel, Panel):
    bl_label = "Theme Presets"
    preset_subdir = "bgs/theme"
    preset_operator = "script.execute_preset"
    preset_add_operator = operators.SKETCHER_OT_add_preset_theme.bl_idname


classes = (
    VIEW3D_UL_sketches,
    VIEW3D_PT_sketcher,
    VIEW3D_MT_sketches,
    SKETCHER_MT_theme_presets,
    SKETCHER_PT_theme_presets,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
