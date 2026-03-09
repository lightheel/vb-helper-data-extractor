# -*- mode: python ; coding: utf-8 -*-
# Minimal spec: exclude heavy packages (pandas, torch, scipy) to avoid
# OpenBLAS memory errors and SubprocessDiedError during analysis.
import os
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

datas = []
binaries = []
hiddenimports = []

# Exclude heavy packages so PyInstaller never traces into them (avoids
# OpenBLAS/memory issues and pandas hook subprocess death).
excludes = [
    'pandas', 'torch', 'scipy', 'IPython', 'tensorboard', 'matplotlib',
    'tkinter.test', 'test', 'unittest', 'pydoc', 'doctest', 'pdb',
    'setuptools', 'distutils', 'wheel', 'pip', 'Cython',
]

# Bundle fmod_toolkit's libfmod (fmod.dll etc.) so UnityPy audio/texture extraction works when frozen.
# datas must be list of (src, dest) 2-tuples; dest goes under _MEIPASS/fmod_toolkit/libfmod/...
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
        print(f"WARNING: fmod_toolkit libfmod dir not found at {libfmod_dir} - audio/DLL may fail when frozen")
except Exception as e:
    print(f"WARNING: Could not collect fmod_toolkit libfmod: {e}")

# Only collect what we need; avoid collect_all for packages that pull in the world.
for dep in ['PIL', 'tqdm', 'psutil', 'UnityPy', 'fmod_toolkit', 'pyfmodex']:
    try:
        dep_data, dep_binaries, dep_hidden = collect_all(dep)
        datas.extend(dep_data)
        binaries.extend(dep_binaries)
        hiddenimports.extend(dep_hidden)
        if dep not in hiddenimports:
            hiddenimports.append(dep)
    except Exception as e:
        print(f"WARNING: Could not collect {dep}: {e}")
        if dep not in hiddenimports:
            hiddenimports.append(dep)

try:
    for submod in collect_submodules('UnityPy'):
        if submod not in hiddenimports:
            hiddenimports.append(submod)
except Exception:
    pass

try:
    import archspec
    datas += collect_data_files('archspec')
    if 'archspec' not in hiddenimports:
        hiddenimports.append('archspec')
except ImportError:
    pass

additional_imports = [
    'UnityPy.classes', 'UnityPy.classes.Object', 'UnityPy.classes.Texture2D',
    'UnityPy.classes.AudioClip', 'UnityPy.classes.Sprite', 'UnityPy.classes.Material',
    'UnityPy.classes.Mesh', 'UnityPy.classes.AnimationClip',
    'UnityPy.classes.AnimatorController', 'UnityPy.classes.AnimatorOverrideController',
    'UnityPy.classes.RuntimeAnimatorController', 'UnityPy.classes.AnimatorStateMachine',
    'UnityPy.classes.AnimatorState', 'UnityPy.classes.AnimatorTransition',
    'UnityPy.classes.AnimatorCondition', 'UnityPy.classes.AnimatorParameter',
]
hiddenimports.extend(additional_imports)

a = Analysis(
    ['vb_arena_extractor_gui.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
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
    name='vb_arena_extractor_gui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI app - no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

