# -*- mode: python ; coding: utf-8 -*-
import os
import site
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

datas = []
binaries = []
hiddenimports = []

# Bundle fmod_toolkit's libfmod (fmod.dll) so UnityPy audio/texture works when frozen. datas = list of (src, dest).
try:
    import fmod_toolkit
    fmod_root = os.path.dirname(fmod_toolkit.__file__)
    libfmod_dir = os.path.join(fmod_root, 'libfmod')
    if os.path.isdir(libfmod_dir):
        for root, _dirs, files in os.walk(libfmod_dir):
            for f in files:
                src = os.path.join(root, f)
                # PyInstaller expects (src, dest_dir); it copies file into dest_dir keeping filename
                rel_dir = os.path.relpath(root, libfmod_dir)
                dest_dir = os.path.join('fmod_toolkit', 'libfmod', rel_dir).replace(os.sep, '/')
                datas.append((src, dest_dir))
        print(f"Added fmod_toolkit libfmod tree from {libfmod_dir}")
    else:
        print(f"WARNING: fmod_toolkit libfmod dir not found at {libfmod_dir}")
except Exception as e:
    print(f"WARNING: Could not collect fmod_toolkit libfmod: {e}")

# Collect all dependencies using collect_all for proper bundling
dependencies = ['PIL', 'tqdm', 'psutil', 'UnityPy', 'fmod_toolkit', 'pyfmodex']

for dep in dependencies:
    try:
        # Use collect_all to get everything each dependency needs
        dep_data, dep_binaries, dep_hidden = collect_all(dep)
        datas.extend(dep_data)
        binaries.extend(dep_binaries)
        hiddenimports.extend(dep_hidden)
        
        # Ensure the main module is in hiddenimports
        if dep not in hiddenimports:
            hiddenimports.append(dep)
        
    except Exception as e:
        print(f"WARNING: Could not collect {dep}: {e}")
        # Still add it to hiddenimports
        if dep not in hiddenimports:
            hiddenimports.append(dep)

# Collect UnityPy submodules explicitly
try:
    unitypy_submodules = collect_submodules('UnityPy')
    for submod in unitypy_submodules:
        if submod not in hiddenimports:
            hiddenimports.append(submod)
except Exception:
    pass

# Collect archspec data files (this is the missing dependency)
try:
    import archspec
    archspec_data = collect_data_files('archspec')
    datas += archspec_data
    if 'archspec' not in hiddenimports:
        hiddenimports.append('archspec')
except ImportError:
    pass

# Add any other potential missing dependencies
additional_imports = [
    'UnityPy.classes',
    'UnityPy.classes.Object',
    'UnityPy.classes.Texture2D',
    'UnityPy.classes.AudioClip',
    'UnityPy.classes.Sprite',
    'UnityPy.classes.Material',
    'UnityPy.classes.Mesh',
    'UnityPy.classes.AnimationClip',
    'UnityPy.classes.AnimatorController',
    'UnityPy.classes.AnimatorOverrideController',
    'UnityPy.classes.RuntimeAnimatorController',
    'UnityPy.classes.AnimatorStateMachine',
    'UnityPy.classes.AnimatorState',
    'UnityPy.classes.AnimatorTransition',
    'UnityPy.classes.AnimatorCondition',
    'UnityPy.classes.AnimatorParameter',
    'UnityPy.classes.AnimatorLayerBlendingMode',
    'UnityPy.classes.AnimatorLayerWeight',
    'UnityPy.classes.AnimatorLayerOverride',
    'UnityPy.classes.AnimatorLayerOverrideController',
    'UnityPy.classes.AnimatorLayerOverrideStateMachine',
    'UnityPy.classes.AnimatorLayerOverrideState',
    'UnityPy.classes.AnimatorLayerOverrideTransition',
    'UnityPy.classes.AnimatorLayerOverrideCondition',
    'UnityPy.classes.AnimatorLayerOverrideParameter',
    'UnityPy.classes.AnimatorLayerOverrideBlendingMode',
    'UnityPy.classes.AnimatorLayerOverrideWeight',
    'UnityPy.classes.AnimatorLayerOverrideOverride',
    'UnityPy.classes.AnimatorLayerOverrideOverrideController',
    'UnityPy.classes.AnimatorLayerOverrideOverrideStateMachine',
    'UnityPy.classes.AnimatorLayerOverrideOverrideState',
    'UnityPy.classes.AnimatorLayerOverrideOverrideTransition',
    'UnityPy.classes.AnimatorLayerOverrideOverrideCondition',
    'UnityPy.classes.AnimatorLayerOverrideOverrideParameter',
    'UnityPy.classes.AnimatorLayerOverrideOverrideBlendingMode',
    'UnityPy.classes.AnimatorLayerOverrideOverrideWeight',
    'UnityPy.classes.AnimatorLayerOverrideOverrideOverride',
]

hiddenimports.extend(additional_imports)

a = Analysis(
    ['vb_arena_extractor.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='vb_arena_extractor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)