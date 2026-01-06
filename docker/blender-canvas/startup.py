"""
Blender Startup Script
Runs automatically when Blender starts to configure the environment
Configured for Xvfb + Software OpenGL (Mesa llvmpipe) + noVNC
"""
import bpy

def configure_blender():
    """Configure Blender for MCP operation with Software OpenGL"""

    try:
        # Disable splash screen
        bpy.context.preferences.view.show_splash = False
    except Exception:
        pass

    # Keep default render engine (Eevee) - user can switch via MCP if needed

    # Set resolution
    try:
        bpy.context.scene.render.resolution_x = 1920
        bpy.context.scene.render.resolution_y = 1080
    except Exception:
        pass

    # Set viewport to Material Preview to see materials
    try:
        if hasattr(bpy.context, 'screen') and bpy.context.screen:
            for area in bpy.context.screen.areas:
                if area.type == 'VIEW_3D':
                    for space in area.spaces:
                        if space.type == 'VIEW_3D':
                            space.shading.type = 'MATERIAL'  # Material Preview
                            space.shading.use_scene_lights = True
                            space.shading.use_scene_world = False
    except Exception:
        pass  # Ignore viewport errors in headless mode

    print("Blender configured for MCP operation")

# Run on startup with error handling
try:
    configure_blender()
except Exception as e:
    print(f"Startup configuration warning: {e}")
