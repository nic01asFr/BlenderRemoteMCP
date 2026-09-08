"""
Blender Startup Script
Runs automatically when Blender starts to configure the environment
Configured for Xvfb + Software OpenGL (Mesa llvmpipe) + noVNC
"""
import bpy


def _cpus_du_cgroup():
    """Nombre de CPU reellement alloues, lu dans le cgroup.

    cgroup v2 : /sys/fs/cgroup/cpu.max donne « quota periode », ou « max »
    quand il n'y a pas de limite. cgroup v1 : deux fichiers separes.
    Retourne None si rien n'est lisible — mieux vaut le defaut de Blender
    qu'une valeur inventee.
    """
    import os

    try:
        with open("/sys/fs/cgroup/cpu.max") as f:
            quota, periode = f.read().split()
        if quota != "max":
            return max(1, int(int(quota) / int(periode)))
    except Exception:
        pass

    try:
        with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us") as f:
            quota = int(f.read())
        with open("/sys/fs/cgroup/cpu/cpu.cfs_period_us") as f:
            periode = int(f.read())
        if quota > 0:
            return max(1, int(quota / periode))
    except Exception:
        pass

    return None


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
        import os
        largeur, hauteur = (os.environ.get("DISPLAY_GEOMETRY", "1280x720")
                            .split("x")[:2])
        bpy.context.scene.render.resolution_x = int(largeur)
        bpy.context.scene.render.resolution_y = int(hauteur)
    except Exception:
        pass

    # Nombre de fils aligne sur le quota REEL du container.
    #
    # Dans un pod, /proc et nproc montrent les CPU de la MACHINE, pas le quota
    # du cgroup : Blender y lisait 104 coeurs pour un quota de 4 et lancait
    # 256 fils. La sur-souscription coute plus qu'elle ne rapporte — commutation
    # de contexte et cache piétiné — et c'est une cause directe de saccades.
    try:
        quota = _cpus_du_cgroup()
        if quota:
            bpy.context.scene.render.threads_mode = "FIXED"
            bpy.context.scene.render.threads = quota
            print(f"Threads Blender fixes a {quota} (quota du cgroup)")
    except Exception as e:
        print(f"Reglage des fils impossible : {e}")

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

    # Configure input for web canvas (laptop-friendly controls)
    try:
        prefs = bpy.context.preferences.inputs
        # Enable 3-button mouse emulation: Alt+LMB = Middle Mouse Button
        prefs.use_mouse_emulate_3_button = True
        # Enable continuous grab for smoother orbit/pan
        prefs.use_mouse_continuous = True
        # Zoom to mouse cursor position (more intuitive)
        prefs.use_zoom_to_mouse = True
        # Enable drag immediately for faster response
        prefs.use_drag_immediately = True
        print("Input configured: 3-button emulation enabled (Alt+LMB = MMB)")
    except Exception as e:
        print(f"Input config warning: {e}")

    print("Blender configured for MCP operation")

# Run on startup with error handling
try:
    configure_blender()
except Exception as e:
    print(f"Startup configuration warning: {e}")
