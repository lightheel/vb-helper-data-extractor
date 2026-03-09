#!/usr/bin/env python3

import UnityPy
import os
import zipfile
import shutil
from pathlib import Path
import argparse
import logging
from PIL import Image
import io
import time
from tqdm import tqdm
import gc
import sys
import threading
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed, ThreadPoolExecutor
import json
import re
from collections import defaultdict
import psutil

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Safe tqdm wrapper that handles None stdout/stderr (common in GUI apps)
def safe_tqdm(*args, **kwargs):
    """Wrapper for tqdm that handles None stdout/stderr"""
    try:
        # Check if stdout/stderr are available
        if sys.stdout is None or sys.stderr is None:
            # Return a dummy progress bar that does nothing
            class DummyTqdm:
                def __init__(self, *args, **kwargs):
                    self.total = kwargs.get('total', 0)
                    self.n = 0
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    return False
                def update(self, n=1):
                    self.n += n
                def set_postfix(self, *args, **kwargs):
                    # Accept either dict as positional arg or keyword args (like real tqdm)
                    pass
                def refresh(self):
                    pass
            return DummyTqdm(*args, **kwargs)
        else:
            # Use regular tqdm but redirect to stderr to avoid GUI issues
            kwargs.setdefault('file', sys.stderr)
            return tqdm(*args, **kwargs)
    except Exception:
        # If tqdm fails for any reason, return dummy
        class DummyTqdm:
            def __init__(self, *args, **kwargs):
                self.total = kwargs.get('total', 0)
                self.n = 0
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def update(self, n=1):
                self.n += n
            def set_postfix(self, *args, **kwargs):
                # Accept either dict as positional arg or keyword args (like real tqdm)
                pass
            def refresh(self):
                pass
        return DummyTqdm(*args, **kwargs)

class MasterExtractor:
    def __init__(self):
        # When running as .exe, put all outputs next to the executable so the user can find them
        if getattr(sys, "frozen", False) and getattr(sys, "executable", None):
            self._output_base = Path(sys.executable).parent.resolve()
            logger.info(f"Running as executable - output folder: {self._output_base}")
        else:
            self._output_base = Path.cwd().resolve()
        
        # Use resolve() so paths are always absolute (critical when running as exe from different CWD)
        self.atksprites_dir = (self._output_base / "extracted_atksprites").resolve()
        self.audio_dir = (self._output_base / "extracted_audio").resolve()
        self.battlebg_dir = (self._output_base / "extracted_battlebgs").resolve()
        self.hit_sprites_dir = (self._output_base / "extracted_hit_sprites").resolve()
        
        # Create main directories with error handling
        try:
            self.atksprites_dir.mkdir(parents=True, exist_ok=True)
            self.audio_dir.mkdir(parents=True, exist_ok=True)
            self.battlebg_dir.mkdir(parents=True, exist_ok=True)
            self.hit_sprites_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Output directories: {self._output_base}")
        except Exception as e:
            logger.error(f"Error creating output directories: {e}")
            logger.error(f"Current working directory: {Path.cwd()}")
            raise
        
        # Create audio subdirectories
        self.se_dir = (self.audio_dir / "sound_effects").resolve()
        self.bgm_dir = (self.audio_dir / "background_music").resolve()
        self.game_dir = (self.audio_dir / "game_sounds").resolve()
        
        try:
            self.se_dir.mkdir(parents=True, exist_ok=True)
            self.bgm_dir.mkdir(parents=True, exist_ok=True)
            self.game_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Error creating audio subdirectories: {e}")
            raise
        
        # BattleBg counter
        self.battlebg_counter = 0
        
        self.extracted_animations = set()
        self.failed_animations = set()
        self.problematic_bundles = set()
        
        self.created_anim_dirs = set()
        self._anim_dirs_lock = threading.Lock()
        
        # Shared thread pool for PNG saving - CRITICAL: PNG encoding is CPU-bound and GIL-limited
        cpu_count = os.cpu_count() or 1
        # Use CPU count + 1 for I/O overlap (file writes release GIL), but cap low to reduce overhead
        max_png_workers = min(cpu_count + 1, 8)  # Cap at 8 to reduce overhead
        self.png_save_executor = ThreadPoolExecutor(max_workers=max_png_workers)
        logger.info(f"Created shared PNG save thread pool with {max_png_workers} workers (CPU-OPTIMIZED: {cpu_count} cores)")
        
        # Callback for animation extraction updates (for GUI)
        self.animation_callback = None
        
        # Callback for stats extraction updates (for GUI)
        self.stats_callback = None
        
        # Audio tracking
        self.extracted_audio = set()
        self.failed_audio = set()
        
        # Track extracted files to skip existence checks (performance optimization)
        self.extracted_atksprites = set()
        self.extracted_battlebgs = set()
        self.extracted_hit_sprites = set()
        self.extracted_stats_files = set()
        
        # Thread locks for thread-safe operations
        self._atksprites_lock = threading.Lock()
        self._battlebgs_lock = threading.Lock()
        self._hit_sprites_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        # Debug: sample of texture/sprite names that matched no category (cap 50)
        self._unmatched_texture_names = set()
        self._unmatched_lock = threading.Lock()
        self._unmatched_max = 50
        self._audio_lock = threading.Lock()
        self._animations_lock = threading.Lock()
        self._counters_lock = threading.Lock()
        
        # Digimon stats tracking
        self.extracted_stats = {
            "GameData": 0,
            "CharacterData": 0,
            "StatsData": 0,
            "ConfigData": 0,
            "JsonData": 0
        }
        
        # Create stats output directories
        self.stats_dir = self._output_base / "extracted_digimon_stats"
        self.game_data_dir = self.stats_dir / "game_data"
        self.character_data_dir = self.stats_dir / "character_data"
        self.stats_data_dir = self.stats_dir / "stats_data"
        self.config_data_dir = self.stats_dir / "config_data"
        self.json_data_dir = self.stats_dir / "json_data"
        
        try:
            self.stats_dir.mkdir(exist_ok=True)
            self.game_data_dir.mkdir(exist_ok=True)
            self.character_data_dir.mkdir(exist_ok=True)
            self.stats_data_dir.mkdir(exist_ok=True)
            self.config_data_dir.mkdir(exist_ok=True)
            self.json_data_dir.mkdir(exist_ok=True)
        except Exception as e:
            logger.error(f"Error creating stats directories: {e}")
            raise
        
    
    
    # ===== APK EXTRACTION FUNCTIONS (from atksprites_extractor.py) =====
    
    def extract_main_apk(self, main_apk_path):
        """Extract main APK and find UnityDataAssetPack.apk inside"""
        temp_dir = Path("temp_main_extraction")
        temp_dir.mkdir(exist_ok=True)
        
        logger.info(f"Extracting main APK: {main_apk_path}")
        with zipfile.ZipFile(main_apk_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        
        # Look for UnityDataAssetPack.apk inside the extracted files
        unity_apk_path = None
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                if file == "UnityDataAssetPack.apk":
                    unity_apk_path = Path(root) / file
                    break
            if unity_apk_path:
                break
        
        if not unity_apk_path:
            logger.error("UnityDataAssetPack.apk not found in the main APK!")
            return None
        
        logger.info(f"Found UnityDataAssetPack.apk at: {unity_apk_path}")
        return unity_apk_path
    
    def extract_apk(self, apk_path):
        """Extract APK and return path to extracted directory. When running as .exe, extract next to the exe."""
        if getattr(sys, "frozen", False) and getattr(sys, "executable", None):
            temp_dir = Path(sys.executable).parent / "temp_extraction"
        else:
            temp_dir = Path("temp_extraction")
        temp_dir.mkdir(exist_ok=True)
        logger.info(f"Extracting Unity APK to: {temp_dir}")
        with zipfile.ZipFile(apk_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        return temp_dir
    
    def _temp_extraction_paths(self):
        """Paths to search for temp_extraction (and assets). When running as .exe, include exe directory."""
        paths = [
            Path("temp_extraction"),
            Path(".") / "temp_extraction",
            Path.cwd() / "temp_extraction",
        ]
        try:
            paths.append(Path(__file__).parent / "temp_extraction")
        except Exception:
            pass
        if getattr(sys, "frozen", False) and getattr(sys, "executable", None):
            paths.append(Path(sys.executable).parent / "temp_extraction")
        return paths
    
    def find_unity_assets(self, extracted_dir):
        """Find all Unity asset files with size filtering"""
        unity_files = []
        
        if isinstance(extracted_dir, str):
            extracted_dir = Path(extracted_dir)
        base_paths = ([extracted_dir] if extracted_dir else []) + self._temp_extraction_paths()
        seen = set()
        unique_paths = []
        for p in base_paths:
            try:
                key = str(p.resolve()) if p.exists() else str(p)
            except Exception:
                key = str(p)
            if key not in seen:
                seen.add(key)
                unique_paths.append(p)
        
        for path in unique_paths:
            if path.exists():
                for root, dirs, files in os.walk(path):
                    for file in files:
                        if file.endswith(('.assets', '.bundle')):
                            file_path = Path(root) / file
                            # Skip very small files that likely don't contain textures
                            if file_path.stat().st_size > 1024:  # Skip files smaller than 1KB
                                unity_files.append(file_path)
                
                if unity_files:
                    logger.info(f"Found Unity assets in: {path}")
                    break
        
        if not unity_files:
            logger.error("No Unity asset files found in any expected location!")
            logger.error(f"Checked paths: {[str(p) for p in unique_paths]}")
            return []
        
        # Sort by path for deterministic processing
        unity_files.sort(key=lambda x: str(x))
        return unity_files
    
    def clean_filename(self, name):
        """Clean filename for safe saving"""
        if not name:
            return "unnamed"
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '_')
        return name.strip()
    
    def get_texture_name(self, texture_data, asset_type="Texture2D"):
        """Get a name for the texture, handling different attribute names"""
        # Try different possible attribute names
        possible_names = ['name', 'm_Name', 'Name']
        
        for attr in possible_names:
            if hasattr(texture_data, attr):
                name = getattr(texture_data, attr)
                if name:
                    return self.clean_filename(name)
        
        # If no name found, use a hash or index
        return f"{asset_type.lower()}_{hash(str(texture_data)) % 10000}"
    
    def get_object_name(self, obj_data, asset_type="GameObject"):
        """Get a name for the object, handling different attribute names"""
        # Try different possible attribute names
        possible_names = ['name', 'm_Name', 'Name', 'id', 'm_Id', 'Id']
        
        for attr in possible_names:
            if hasattr(obj_data, attr):
                name = getattr(obj_data, attr)
                if name:
                    return self.clean_filename(str(name))
        
        # If no name found, use a hash or index
        return f"{asset_type.lower()}_{hash(str(obj_data)) % 10000}"
    
    def is_relevant_object_type(self, obj_type):
        """Check if this object type is relevant for Digimon stats extraction"""
        relevant_types = [
            'GameObject', 'MonoBehaviour', 'ScriptableObject', 'TextAsset',
            'MonoScript', 'AssetBundle', 'Transform', 'RectTransform'
        ]
        return obj_type in relevant_types
    
    def has_character_stats(self, obj_data):
        """Check if an object contains character stats fields"""
        character_stat_fields = [
            'name', 'stage', 'attribute', 'baseHp', 'currentHp', 'baseBp', 'baseAp',
            'm_name', 'm_stage', 'm_attribute', 'm_baseHp', 'm_currentHp', 'm_baseBp', 'm_baseAp',
            'Name', 'Stage', 'Attribute', 'BaseHp', 'CurrentHp', 'BaseBp', 'BaseAp',
            'm_Name', 'm_Stage', 'm_Attribute', 'm_BaseHp', 'm_CurrentHp', 'm_BaseBp', 'm_BaseAp',
            'hp', 'bp', 'ap', 'stage', 'attribute', 'm_Hp', 'm_Bp', 'm_Ap',
        ]
        found_stats = 0
        for field in character_stat_fields:
            if hasattr(obj_data, field):
                try:
                    value = getattr(obj_data, field)
                    if value is not None:
                        found_stats += 1
                except Exception:
                    pass
        return found_stats >= 2

    def is_character_data_by_name(self, obj_name):
        """Name-based hint for character/digimon data (used with at least one stat field)."""
        if not obj_name:
            return False
        n = obj_name.lower()
        return any(k in n for k in ('character', 'digimon', 'monster', 'dim', 'partner', 'vpet'))

    def has_any_character_field(self, obj_data):
        """True if object has at least one character-stat-like attribute."""
        character_stat_fields = [
            'name', 'stage', 'attribute', 'baseHp', 'currentHp', 'baseBp', 'baseAp',
            'm_name', 'm_stage', 'm_attribute', 'm_baseHp', 'm_currentHp', 'm_baseBp', 'm_baseAp',
            'Name', 'Stage', 'Attribute', 'BaseHp', 'CurrentHp', 'BaseBp', 'BaseAp',
            'm_Name', 'm_Stage', 'm_Attribute', 'm_BaseHp', 'm_CurrentHp', 'm_BaseBp', 'm_BaseAp',
            'hp', 'bp', 'ap', 'm_Hp', 'm_Bp', 'm_Ap',
        ]
        for field in character_stat_fields:
            if hasattr(obj_data, field):
                try:
                    if getattr(obj_data, field) is not None:
                        return True
                except Exception:
                    pass
        return False
    
    def is_vb_repository_object(self, obj_type, obj_name):
        """Check if this object is related to VB.Repository classes from the decompiled code"""
        vb_keywords = [
            'vb', 'repository', 'characterstorage', 'memberslist', 
            'localdataloader', 'playerprefs', 'jsonutility',
            'character', 'storage', 'data', 'loader'
        ]
        
        obj_type_lower = obj_type.lower()
        obj_name_lower = obj_name.lower()
        
        for keyword in vb_keywords:
            if keyword in obj_type_lower or keyword in obj_name_lower:
                return True
        
        return False
    
    # ===== ATTACK SPRITES EXTRACTION (from atksprites_extractor.py) =====
    
    def is_atksprite_texture(self, texture_data):
        """Check if this texture is an attack sprite texture"""
        texture_name = self.get_texture_name(texture_data, "Texture2D")
        texture_name_lower = texture_name.lower()
        # Broad patterns: 124_atk, atk_l, atk_s, atkdot, or any atk_ prefix
        return (texture_name_lower.startswith('124_atk') or
                texture_name_lower.startswith('atk_l') or
                texture_name_lower.startswith('atk_s') or
                texture_name_lower.startswith('atkdot') or
                texture_name_lower.startswith('atk_'))
    
    def is_atksprite_sprite(self, sprite_data):
        """Check if this sprite is an attack sprite"""
        sprite_name = self.get_texture_name(sprite_data, "Sprite")
        sprite_name_lower = sprite_name.lower()
        return (sprite_name_lower.startswith('124_atk') or
                sprite_name_lower.startswith('atk_l') or
                sprite_name_lower.startswith('atk_s') or
                sprite_name_lower.startswith('atkdot') or
                sprite_name_lower.startswith('atk_'))
    
    # ===== BATTLE BACKGROUND EXTRACTION (from BattleBg_extractor.py) =====
    
    def is_battlebg_texture(self, texture_data):
        """Check if this texture is a BattleBg texture (case-insensitive)"""
        texture_name = self.get_texture_name(texture_data, "Texture2D")
        name_lower = texture_name.lower()
        return ("battlebg" in name_lower or "battle_bg" in name_lower or
                "battle bg" in name_lower or "battlebackground" in name_lower or
                ("battle" in name_lower and "bg" in name_lower))
    
    # ===== HIT/DMG SPRITES EXTRACTION =====
    
    def is_hit_sprite_texture(self, texture_data):
        """Check if this texture is a hit/damage sprite (dmg_* or hit_*)"""
        texture_name = self.get_texture_name(texture_data, "Texture2D")
        name_lower = texture_name.lower()
        return name_lower.startswith("dmg_") or name_lower.startswith("hit_")
    
    def is_hit_sprite_sprite(self, sprite_data):
        """Check if this sprite is a hit/damage sprite (dmg_* or hit_*)"""
        sprite_name = self.get_texture_name(sprite_data, "Sprite")
        name_lower = sprite_name.lower()
        return name_lower.startswith("dmg_") or name_lower.startswith("hit_")
    
    # ===== AUDIO EXTRACTION (from audio_extractor.py) =====
    
    def find_audio_bundle(self):
        """Find the bundle file containing audio assets"""
        bundle_files = []
        for path in self._temp_extraction_paths():
            if path.exists():
                bundle_files.extend(path.rglob("*.bundle"))
                if bundle_files:
                    logger.info(f"Found bundle files in: {path}")
                    break
        
        if not bundle_files:
            logger.error("No bundle files found in any expected location!")
            logger.error(f"Checked paths: {[str(p) for p in self._temp_extraction_paths()]}")
            return None
        
        # Look for the serverdata bundle which contains audio
        for bundle_file in bundle_files:
            if "serverdata" in bundle_file.name:
                logger.info(f"Found audio bundle: {bundle_file.name}")
                return bundle_file
        
        logger.error("No audio bundle found!")
        return None
    
    def categorize_audio(self, audio_name):
        """Categorize audio by type based on naming convention"""
        if audio_name.startswith("se_"):
            return "sound_effects"
        elif audio_name.startswith("bgm_"):
            return "background_music"
        else:
            return "game_sounds"
    
    def get_output_path(self, audio_name, category):
        """Get the appropriate output path for the audio file"""
        if category == "sound_effects":
            return self.se_dir / f"{audio_name}.wav"
        elif category == "background_music":
            return self.bgm_dir / f"{audio_name}.wav"
        else:
            return self.game_dir / f"{audio_name}.wav"
    
    def extract_audio_clip(self, audio_obj, audio_data):
        """Extract a single audio clip. UnityPy samples dict key is filename with correct extension (.wav/.ogg/.m4a)."""
        audio_name = audio_data.m_Name
        
        # Skip if already extracted
        if audio_name in self.extracted_audio:
            logger.debug(f"Skipping already extracted: {audio_name}")
            return False
        
        try:
            # Get audio samples (key = filename with extension from UnityPy)
            if not audio_data.samples:
                logger.warning(f"No samples found for: {audio_name}")
                self.failed_audio.add(audio_name)
                return False
            
            sample_filename, sample_data = next(iter(audio_data.samples.items()))
            if not sample_data:
                logger.warning(f"No audio data found for: {audio_name}")
                self.failed_audio.add(audio_name)
                return False
            
            # Categorize and save using correct extension from UnityPy
            category = self.categorize_audio(audio_name)
            if category == "sound_effects":
                out_dir = self.se_dir
            elif category == "background_music":
                out_dir = self.bgm_dir
            else:
                out_dir = self.game_dir
            output_path = out_dir / sample_filename
            
            # Save the audio file
            with open(output_path, 'wb') as f:
                f.write(sample_data)
            
            # Update stats
            self.extracted_audio.add(audio_name)
            
            logger.debug(f"Extracted: {audio_name} -> {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to extract {audio_name}: {e}")
            self.failed_audio.add(audio_name)
            return False
    
    def extract_all_audio(self):
        """Extract all audio clips from the bundle"""
        logger.info("Starting audio extraction...")
        
        # Find the audio bundle
        bundle_file = self.find_audio_bundle()
        if not bundle_file:
            return
        
        try:
            # Load the bundle
            logger.info(f"Loading bundle: {bundle_file}")
            env = UnityPy.load(str(bundle_file))
            
            # Try to load assets with error handling
            try:
                env.load_folder('temp_extraction')
            except Exception as e:
                logger.warning(f"Could not load temp_extraction folder: {e}")
                # Try alternative paths
                try:
                    env.load_folder('.')
                except Exception as e2:
                    logger.warning(f"Could not load current directory: {e2}")
            
            # Find all AudioClip objects
            audio_clips = [obj for obj in env.objects if obj.type.name == 'AudioClip']
            
            logger.info(f"Found {len(audio_clips)} audio clips")
            
            # Extract each audio clip
            with tqdm(total=len(audio_clips), desc="Extracting audio") as pbar:
                for audio_obj in audio_clips:
                    try:
                        audio_data = audio_obj.read()
                        success = self.extract_audio_clip(audio_obj, audio_data)
                        
                        # Update progress
                        pbar.set_postfix({
                            'Extracted': len(self.extracted_audio),
                            'Failed': len(self.failed_audio)
                        })
                        
                    except Exception as e:
                        logger.error(f"Error processing audio clip: {e}")
                        self.failed_audio.add(f"error_{len(self.failed_audio)}")
                    
                    pbar.update(1)
            
            # Print final statistics
            logger.info("=== AUDIO EXTRACTION COMPLETE ===")
            logger.info(f"Total audio found: {len(audio_clips)}")
            logger.info(f"Total audio extracted: {len(self.extracted_audio)}")
            logger.info(f"Failed extractions: {len(self.failed_audio)}")
            
            # Show extracted files by category
            se_files = [name for name in self.extracted_audio if name.startswith("se_")]
            bgm_files = [name for name in self.extracted_audio if name.startswith("bgm_")]
            game_files = [name for name in self.extracted_audio if not name.startswith(("se_", "bgm_"))]
            
            logger.info(f"Sound effects: {len(se_files)}")
            logger.info(f"Background music: {len(bgm_files)}")
            logger.info(f"Game sounds: {len(game_files)}")
            
            logger.info(f"All audio files saved to: {self.audio_dir}")
            
        except Exception as e:
            logger.error(f"Error loading bundle: {e}")
            logger.error(f"Bundle file: {bundle_file}")
            logger.error(f"Bundle exists: {bundle_file.exists()}")
            logger.error(f"Bundle size: {bundle_file.stat().st_size if bundle_file.exists() else 'N/A'}")
    
    # ===== DIM MON EXTRACTION (from dim_mon_extractor.py) =====
    
    def find_bundle_files(self, extracted_dir=None):
        """Find all Unity bundle files"""
        bundle_files = []
        base_paths = ([Path(extracted_dir) if isinstance(extracted_dir, str) else extracted_dir] if extracted_dir else []) + self._temp_extraction_paths()
        seen = set()
        unique_paths = []
        for p in base_paths:
            try:
                key = str(p.resolve()) if p.exists() else str(p)
            except Exception:
                key = str(p)
            if key not in seen:
                seen.add(key)
                unique_paths.append(p)
        
        for path in unique_paths:
            if path.exists():
                bundle_files.extend(path.rglob("*.bundle"))
                if bundle_files:
                    logger.info(f"Found bundle files in: {path}")
                    break
        
        if not bundle_files:
            logger.error("No bundle files found in any expected location!")
            logger.error(f"Checked paths: {[str(p) for p in unique_paths]}")
            return []
        
        # Sort by file size (largest first) for better efficiency
        bundle_files.sort(key=lambda x: x.stat().st_size, reverse=True)
        
        # Filter out problematic bundles
        bundle_files = [b for b in bundle_files if b.name not in self.problematic_bundles]
        
        logger.info(f"Found {len(bundle_files)} bundle files (excluding {len(self.problematic_bundles)} problematic ones)")
        return bundle_files
    
    # ===== MAIN EXTRACTION PROCESS =====
    
    def process_main_apk(self, main_apk_path):
        """Main processing function that runs all extractions in order"""
        logger.info(f"Starting extraction from main APK: {main_apk_path}")
        
        # Step 1: Extract main APK to find UnityDataAssetPack.apk
        unity_apk_path = self.extract_main_apk(main_apk_path)
        if not unity_apk_path:
            return
        
        try:
            # Step 2: Extract Unity APK
            temp_dir = self.extract_apk(unity_apk_path)
            
            try:
                # Step 3: EXTRACTION - Single pass through all files
                logger.info("===EXTRACTION ===")
                self.extract_all_assets(temp_dir)
                
                # Final summary
                logger.info("=== MASTER EXTRACTION COMPLETE ===")
                logger.info(f"All assets extracted successfully!")
                logger.info(f"Audio files: {len(self.extracted_audio)}")
                logger.info(f"Attack sprites: {len(self.extracted_atksprites)}")
                logger.info(f"Battle backgrounds: {self.battlebg_counter}")
                logger.info(f"Hit/Dmg sprites: {len(self.extracted_hit_sprites)}")
                logger.info(f"Stats data: {sum(self.extracted_stats.values())}")
                
                # Don't cleanup so we can examine the files
                logger.info("Skipping cleanup to examine extracted files")
                
            except Exception as e:
                import traceback
                logger.error(f"Error during extraction: {e}")
                logger.error(f"Full traceback: {traceback.format_exc()}")
                
        except Exception as e:
            import traceback
            logger.error(f"Error during main APK processing: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
    
    def run_extraction(self):
        """Main processing function that runs all extractions from existing temp_extraction directory"""
        logger.info("Starting extraction from existing temp_extraction directory")
        
        try:
            # EXTRACTION - Single pass through all files
            logger.info("=== EXTRACTION ===")
            self.extract_all_assets("temp_extraction")
            
            # Final summary
            logger.info("=== MASTER EXTRACTION COMPLETE ===")
            logger.info(f"All assets extracted successfully!")
            logger.info(f"Attack sprites: {len(self.extracted_atksprites)}")
            logger.info(f"Battle backgrounds: {self.battlebg_counter}")
            logger.info(f"Audio files: {len(self.extracted_audio)}")
            logger.info(f"Stats data: {sum(self.extracted_stats.values())}")
            
        except Exception as e:
            import traceback
            logger.error(f"Error during extraction: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
    
    def extract_all_audio_fast(self):
        """Audio extraction using proven working approach with better progress tracking"""
        logger.info("Starting audio extraction...")
        
        # Find the audio bundle
        bundle_file = self.find_audio_bundle()
        if not bundle_file:
            return
        
        try:
            # Load the bundle (proven working approach)
            logger.info(f"Loading audio bundle: {bundle_file}")
            env = UnityPy.load(str(bundle_file))
            
            # Find all AudioClip objects
            audio_clips = [obj for obj in env.objects if obj.type.name == 'AudioClip']
            logger.info(f"Found {len(audio_clips)} audio clips")
            
            # Track progress with better feedback
            total_found = len(audio_clips)
            extracted_count = 0
            failed_count = 0
            start_time = time.time()
            
            # Extract each audio clip with progress tracking
            with tqdm(total=total_found, desc="Extracting audio", unit="clip", ncols=100) as pbar:
                for clip_idx, audio_obj in enumerate(audio_clips):
                    try:
                        audio_data = audio_obj.read()
                        audio_name = audio_data.m_Name
                        
                        # Update progress immediately for each clip
                        pbar.set_postfix({
                            'Clip': f"{clip_idx+1}/{total_found}",
                            'Extracted': extracted_count,
                            'Failed': failed_count,
                            'Current': audio_name[:15]
                        }, refresh=True)
                        
                        # Skip if already extracted
                        if audio_name in self.extracted_audio:
                            pbar.update(1)
                            continue
                        
                        # Check if audio has samples (key = filename with correct extension)
                        if not audio_data.samples:
                            logger.debug(f"No samples for: {audio_name}")
                            failed_count += 1
                            pbar.update(1)
                            continue
                        
                        sample_filename, sample_data = next(iter(audio_data.samples.items()))
                        if not sample_data:
                            logger.debug(f"No audio data for: {audio_name}")
                            failed_count += 1
                            pbar.update(1)
                            continue
                        
                        # Categorize and save with correct extension (.wav/.ogg/.m4a)
                        if audio_name.startswith("se_"):
                            output_path = self.se_dir / sample_filename
                        elif audio_name.startswith("bgm_"):
                            output_path = self.bgm_dir / sample_filename
                        else:
                            output_path = self.game_dir / sample_filename
                        
                        # Save the audio file
                        with open(output_path, 'wb') as f:
                            f.write(sample_data)
                        
                        # Update tracking
                        self.extracted_audio.add(audio_name)
                        extracted_count += 1
                        
                        # Update progress bar with current stats
                        pbar.set_postfix({
                            'Clip': f"{clip_idx+1}/{total_found}",
                            'Extracted': extracted_count,
                            'Failed': failed_count,
                            'Current': audio_name[:15],
                            'Rate': f"{extracted_count/(time.time() - start_time):.1f}/s" if (time.time() - start_time) > 0 else "0.0/s"
                        }, refresh=True)
                        
                    except Exception as e:
                        logger.error(f"Error extracting audio clip: {e}")
                        failed_count += 1
                    
                    pbar.update(1)
                    
                    # Force refresh every 10 clips
                    if (clip_idx + 1) % 10 == 0:
                        pbar.refresh()
            
            # Print final statistics
            logger.info("=== AUDIO EXTRACTION COMPLETE ===")
            logger.info(f"Total audio found: {total_found}")
            logger.info(f"Total audio extracted: {extracted_count}")
            logger.info(f"Failed extractions: {failed_count}")
            
            # Show extracted files by category
            se_files = [name for name in self.extracted_audio if name.startswith("se_")]
            bgm_files = [name for name in self.extracted_audio if name.startswith("bgm_")]
            game_files = [name for name in self.extracted_audio if not name.startswith(("se_", "bgm_"))]
            
            logger.info(f"Sound effects: {len(se_files)}")
            logger.info(f"Background music: {len(bgm_files)}")
            logger.info(f"Game sounds: {len(game_files)}")
            
            logger.info(f"All audio files saved to: {self.audio_dir}")
            
        except Exception as e:
            logger.error(f"Error in audio extraction: {e}")
    
    def extract_all_dim_animations_fast(self):
        """Dim animation extraction using proven working approach with frequent progress updates"""
        logger.info("Starting dim animation extraction...")
        
        start_time = time.time()
        bundle_files = self.find_bundle_files()
        logger.info(f"Found {len(bundle_files)} bundle files")
        
        # Process bundles sequentially with frequent progress updates
        with tqdm(total=len(bundle_files), desc="Processing bundles", unit="bundle", ncols=100) as pbar:
            for bundle_idx, bundle_file in enumerate(bundle_files):
                try:
                    # Update progress immediately when starting each bundle
                    pbar.set_postfix({
                        'Bundle': f"{bundle_idx+1}/{len(bundle_files)}",
                        'Animations': len(self.extracted_animations),
                        'Current': bundle_file.name[:15],
                        'Time': f"{(time.time() - start_time):.1f}s"
                    }, refresh=True)
                    
                    # Process the bundle
                    result = self.extract_animation_from_bundle_fast(bundle_file)
                    
                    # Mark problematic bundles
                    if result and result.get("status") == "error":
                        self.problematic_bundles.add(result.get("bundle_name", bundle_file.name))
                    
                    # Update progress immediately after processing
                    pbar.set_postfix({
                        'Bundle': f"{bundle_idx+1}/{len(bundle_files)}",
                        'Animations': len(self.extracted_animations),
                        'Current': bundle_file.name[:15],
                        'Time': f"{(time.time() - start_time):.1f}s",
                        'Rate': f"{len(self.extracted_animations)/(time.time() - start_time):.1f}/s" if (time.time() - start_time) > 0 else "0.0/s"
                    }, refresh=True)
                    
                    # Save checkpoint every 5 bundles (more frequent)
                    if (bundle_idx + 1) % 5 == 0:
                        self.save_dim_mon_checkpoint()
                        logger.info(f"Checkpoint saved: {len(self.extracted_animations)} animations extracted")
                        
                except Exception as e:
                    logger.error(f"Error processing bundle {bundle_file.name}: {e}")
                    self.problematic_bundles.add(bundle_file.name)
                
                pbar.update(1)
                
                # Force refresh every few bundles
                if (bundle_idx + 1) % 3 == 0:
                    pbar.refresh()
        
        # Print final statistics
        elapsed_time = time.time() - start_time
        logger.info("=== DIM MON EXTRACTION COMPLETE ===")
        logger.info(f"Total animations extracted: {len(self.extracted_animations)}")
        logger.info(f"Total sprites extracted: {len(self.extracted_animations) * 12}")
        logger.info(f"Failed animations: {len(self.failed_animations)}")
        logger.info(f"Problematic bundles: {len(self.problematic_bundles)}")
        logger.info(f"Total elapsed time: {elapsed_time:.2f} seconds")
        
        logger.info(f"All animations saved to: {self.dim_sprites_dir}")
    
    def extract_all_assets_fast(self, temp_dir):
        """Fast extraction of all assets using parallel processing and memory optimization"""
        logger.info("Starting FAST parallel asset extraction...")
        
        # Find Unity assets
        unity_files = self.find_unity_assets(temp_dir)
        logger.info(f"Found {len(unity_files)} Unity asset files")
        
        # Initialize counters
        self.total_atksprites = 0
        self.total_battlebgs = 0
        
        # Process files in parallel batches
        batch_size = 10  # Process 10 files at a time
        total_batches = (len(unity_files) + batch_size - 1) // batch_size
        
        with tqdm(total=len(unity_files), desc="Extracting all assets (FAST)") as pbar:
            for batch_start in range(0, len(unity_files), batch_size):
                batch_end = min(batch_start + batch_size, len(unity_files))
                batch_files = unity_files[batch_start:batch_end]
                
                # Process batch in parallel
                with ProcessPoolExecutor(max_workers=min(8, len(batch_files))) as executor:
                    # Submit all file processing tasks for this batch
                    future_to_file = {
                        executor.submit(self.process_single_file_fast, file): file 
                        for file in batch_files
                    }
                    
                    # Process completed tasks
                    for future in as_completed(future_to_file):
                        try:
                            result = future.result()
                            
                            # Update counters
                            self.total_atksprites += result["atksprites"]
                            self.total_battlebgs += result["battlebgs"]
                            self.extracted_stats["GameData"] += result["stats"]["GameData"]
                            self.extracted_stats["CharacterData"] += result["stats"]["CharacterData"]
                            self.extracted_stats["StatsData"] += result["stats"]["StatsData"]
                            self.extracted_stats["ConfigData"] += result["stats"]["ConfigData"]
                            self.extracted_stats["JsonData"] += result["stats"]["JsonData"]
                            
                            # Update progress
                            pbar.set_postfix({
                                'AtkSprites': self.total_atksprites,
                                'BattleBgs': self.total_battlebgs,
                                'GameData': self.extracted_stats["GameData"],
                                'CharacterData': self.extracted_stats["CharacterData"]
                            })
                            
                        except Exception as e:
                            logger.error(f"Error in file processing: {e}")
                        
                        pbar.update(1)
                
                # Log progress every batch
                if (batch_start // batch_size + 1) % 5 == 0:
                    logger.info(f"Asset Progress: {batch_end}/{len(unity_files)} files processed")
        
        logger.info(f"FAST asset extraction complete!")
        logger.info(f"Attack sprites: {self.total_atksprites}")
        logger.info(f"Battle backgrounds: {self.total_battlebgs}")
        logger.info(f"Digimon stats data:")
        logger.info(f"  - GameData: {self.extracted_stats['GameData']}")
        logger.info(f"  - CharacterData: {self.extracted_stats['CharacterData']}")
        logger.info(f"  - StatsData: {self.extracted_stats['StatsData']}")
        logger.info(f"  - ConfigData: {self.extracted_stats['ConfigData']}")
        logger.info(f"  - JsonData: {self.extracted_stats['JsonData']}")
    
    def process_single_file_fast(self, asset_path):
        """Process a single file for all asset types - optimized version"""
        result = {
            "atksprites": 0,
            "battlebgs": 0,
            "stats": {"GameData": 0, "CharacterData": 0, "StatsData": 0, "ConfigData": 0, "JsonData": 0}
        }
        
        try:
            # Load Unity environment once for this file
            env = UnityPy.load(str(asset_path))
            
            # Process all objects in one pass
            for obj in env.objects:
                try:
                    data = obj.read()
                    
                    # Check for attack sprites
                    if obj.type.name == "Texture2D" and self.is_atksprite_texture(data):
                        success, _ = self.save_atksprite_texture(data, self.atksprites_dir, "Texture2D")
                        if success:
                            result["atksprites"] += 1
                    
                    elif obj.type.name == "Sprite" and self.is_atksprite_sprite(data):
                        success, _ = self.save_atksprite_sprite(data, self.atksprites_dir, "Sprite")
                        if success:
                            result["atksprites"] += 1
                    
                    # Check for battle backgrounds
                    elif obj.type.name == "Texture2D" and self.is_battlebg_texture(data):
                        success, _ = self.save_battlebg_texture(data, self.battlebg_dir, "Texture2D")
                        if success:
                            result["battlebgs"] += 1
                    
                    # Check for stats data
                    elif self.is_relevant_object_type(obj.type.name):
                        stats_result = self.process_stats_object(obj, data)
                        for key in result["stats"]:
                            result["stats"][key] += stats_result.get(key, 0)
                    
                except Exception as e:
                    logger.debug(f"Error processing object in {asset_path}: {e}")
                    continue
            
            # Clear memory
            del env
            gc.collect()
            
        except Exception as e:
            logger.error(f"Error processing {asset_path}: {e}")
        
        return result
    
    def process_stats_object(self, obj, obj_data):
        """Process a single object for stats extraction"""
        result = {"GameData": 0, "CharacterData": 0, "StatsData": 0, "ConfigData": 0, "JsonData": 0}
        
        try:
            obj_name = self.get_object_name(obj_data, obj.type.name)
            
            # Check if this is a VB.Repository related object
            is_vb_repo = self.is_vb_repository_object(obj.type.name, obj_name)
            
            # Check if this object contains character stats
            has_stats = self.has_character_stats(obj_data)
            
            # Determine category and save
            if has_stats:
                output_dir = self.character_data_dir
                result["CharacterData"] = 1
                category = "CharacterData"
            elif is_vb_repo:
                output_dir = self.game_data_dir
                result["GameData"] = 1
                category = "GameData"
            elif obj.type.name == "TextAsset":
                output_dir = self.json_data_dir
                result["JsonData"] = 1
                category = "JsonData"
            elif "config" in obj_name.lower() or "setting" in obj_name.lower():
                output_dir = self.config_data_dir
                result["ConfigData"] = 1
                category = "ConfigData"
            else:
                output_dir = self.stats_data_dir
                result["StatsData"] = 1
                category = "StatsData"
            
            # Save the object data
            output_file = output_dir / f"{obj.type.name}_{obj_name}.json"
            try:
                # Convert object to dict for JSON serialization
                obj_dict = {}
                for attr in dir(obj_data):
                    if not attr.startswith('_'):
                        try:
                            value = getattr(obj_data, attr)
                            if isinstance(value, (str, int, float, bool, list, dict)):
                                obj_dict[attr] = value
                        except:
                            pass
                
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(obj_dict, f, indent=2, ensure_ascii=False, default=str)
                    
            except Exception as e:
                logger.debug(f"Error saving {obj.type.name} {obj_name}: {e}")
                
        except Exception as e:
            logger.debug(f"Error processing {obj.type.name} object: {e}")
        
        return result
    
    def set_animation_callback(self, callback):
        """Set callback function to be called when animations are extracted (for GUI updates)"""
        self.animation_callback = callback
    
    def set_stats_callback(self, callback):
        """Set callback function to be called when stats objects are extracted (for GUI updates)"""
        self.stats_callback = callback
    
    def cleanup_temp_folders(self, wait_for_pngs=True, timeout=30):
        """Clean up temporary folders and shutdown thread pools"""
        # Shutdown shared PNG save executor - with optional timeout
        # This ensures all sprites are saved before cleanup (if wait_for_pngs=True)
        if hasattr(self, 'png_save_executor'):
            try:
                if wait_for_pngs:
                    logger.info("Waiting for all PNG saves to complete...")
                    # Use shutdown with wait, but don't block forever
                    self.png_save_executor.shutdown(wait=True)
                    logger.info("All PNG saves completed")
                else:
                    # Quick shutdown - don't wait for queued tasks
                    logger.info("Shutting down PNG executor (not waiting for queued tasks)...")
                    self.png_save_executor.shutdown(wait=False)
            except Exception:
                pass
        
        # Clean up temporary extraction folders after successful extraction
        logger.info("=== CLEANING UP TEMPORARY FOLDERS ===")
        
        temp_folders = ["temp_extraction", "temp_main_extraction"]
        
        for folder_name in temp_folders:
            folder_path = Path(folder_name)
            if folder_path.exists():
                try:
                    logger.info(f"Removing temporary folder: {folder_path}")
                    shutil.rmtree(folder_path)
                    logger.info(f"Successfully removed: {folder_path}")
                except Exception as e:
                    logger.error(f"Error removing {folder_path}: {e}")
            else:
                logger.info(f"Temporary folder not found: {folder_path}")

    def extract_all_assets(self, temp_dir):
        """Extraction: Single pass through all files with minimal UnityPy loading"""
        logger.info("=== ASSET EXTRACTION ===")
        logger.info(f"CPU Cores: {psutil.cpu_count()}")
        logger.info(f"Memory: {psutil.virtual_memory().total / (1024**3):.1f} GB")
        
        start_time = time.time()
        
        # When running as .exe, set cwd to output folder so UnityPy and file writes resolve paths correctly
        original_cwd = None
        if getattr(sys, "frozen", False):
            try:
                original_cwd = os.getcwd()
                os.chdir(self._output_base)
                logger.info(f"Set working directory to: {self._output_base}")
            except Exception as e:
                logger.warning(f"Could not set working directory: {e}")
        
        try:
            unity_files = self.find_unity_assets(temp_dir)
            bundle_files = self.find_bundle_files(temp_dir)
        
            logger.info(f"Found {len(unity_files)} asset files and {len(bundle_files)} bundle files")
            
            # Initialize counters
            self.total_atksprites = 0
            self.total_battlebgs = 0
            self.extracted_stats = {
                "GameData": 0,
                "CharacterData": 0,
                "StatsData": 0,
                "ConfigData": 0,
                "JsonData": 0
            }
            
            if unity_files:
                logger.info("Processing asset files...")
                self.process_asset_files(unity_files)
            
            if bundle_files:
                logger.info("Processing bundle files...")
                self.process_bundle_files(bundle_files)
            
            elapsed_time = time.time() - start_time
            logger.info(f"=== EXTRACTION COMPLETE ===")
            logger.info(f"Total time: {elapsed_time:.2f} seconds")
            logger.info(f"Attack sprites: {len(self.extracted_atksprites)}")
            logger.info(f"Battle backgrounds: {self.battlebg_counter}")
            logger.info(f"Hit/Dmg sprites: {len(self.extracted_hit_sprites)}")
            logger.info(f"Audio files: {len(self.extracted_audio)}")
            logger.info(f"Stats data: {sum(self.extracted_stats.values())}")
            logger.info(f"All extraction outputs saved to: {self._output_base.resolve()}")
            if self.extracted_hit_sprites:
                logger.info(f"Hit/Dmg sprites folder: {self.hit_sprites_dir.resolve()}")
            with self._unmatched_lock:
                unmatched = list(self._unmatched_texture_names)
            if unmatched and (len(self.extracted_atksprites) == 0 or self.battlebg_counter == 0):
                sample = sorted(unmatched)[:30]
                logger.info(f"Sample of texture/sprite names not matched (add patterns in code if needed): {sample}")
        finally:
            if original_cwd is not None:
                try:
                    os.chdir(original_cwd)
                except Exception:
                    pass
    
    def process_asset_files(self, unity_files):
        """Process asset files with parallel processing"""
        # Sort files by size (largest first) for better efficiency
        unity_files.sort(key=lambda x: x.stat().st_size, reverse=True)
        
        # CRITICAL OPTIMIZATION: Match worker count to CPU cores
        # Too many threads causes context switching overhead without benefit
        # Python's GIL limits true parallelism, but I/O operations (file reads) release the GIL
        cpu_count = os.cpu_count() or 1
        # Use CPU count + 2 for I/O bound work (file reading), but cap at reasonable limit
        max_workers = min(cpu_count + 2, len(unity_files), 8)  # Cap at 8 to reduce overhead
        logger.info(f"Using {max_workers} parallel workers for asset file processing (CPU-OPTIMIZED: {cpu_count} cores)")
        
        with safe_tqdm(total=len(unity_files), desc="Processing asset files", unit="file") as pbar:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all files for processing
                future_to_file = {
                    executor.submit(self.extract_all_from_single_file, file_path): file_path
                    for file_path in unity_files
                }
                
                # Process completed tasks as they finish
                for future in as_completed(future_to_file):
                    file_path = future_to_file[future]
                    try:
                        result = future.result()
                        
                        # Update counters (thread-safe with GIL)
                        self.total_atksprites += result.get("atksprites", 0)
                        self.total_battlebgs += result.get("battlebgs", 0)
                        
                        # Update progress
                        pbar.set_postfix({
                            'AtkSprites': self.total_atksprites,
                            'BattleBgs': self.total_battlebgs,
                            'Stats': sum(self.extracted_stats.values())
                        })
                        
                    except Exception as e:
                        import traceback
                        error_msg = f"Error processing {file_path}: {e}"
                        logger.error(error_msg)
                        logger.error(f"Traceback: {traceback.format_exc()}")
                    
                    pbar.update(1)
    
    def extract_all_from_single_file(self, asset_path):
        """Extract all asset types from a single file in one UnityPy load"""
        result = {
            "atksprites": 0,
            "battlebgs": 0,
            "stats": {"GameData": 0, "CharacterData": 0, "StatsData": 0, "ConfigData": 0, "JsonData": 0}
        }
        
        try:
            env = UnityPy.load(str(asset_path))
            texture2d_objects = []
            sprite_objects = []
            audio_objects = []
            atlas_objects = []
            stats_objects = []
            
            # Single pass to categorize all objects
            for obj in env.objects:
                obj_type = obj.type.name
                if obj_type == "Texture2D":
                    texture2d_objects.append(obj)
                elif obj_type == "Sprite":
                    sprite_objects.append(obj)
                elif obj_type == "AudioClip":
                    audio_objects.append(obj)
                elif obj_type == "SpriteAtlas":
                    atlas_objects.append(obj)
                elif self.is_relevant_object_type(obj_type):
                    stats_objects.append(obj)
            
            # Process Texture2D objects in parallel (attack sprites and battle backgrounds)
            if texture2d_objects:
                def process_texture2d(obj):
                    try:
                        data = obj.read()
                        atksprite_count = 0
                        battlebg_count = 0
                        
                        # Check for attack sprites
                        if self.is_atksprite_texture(data):
                            try:
                                success, _ = self.save_atksprite_texture(data)
                                if success:
                                    atksprite_count = 1
                            except Exception as e:
                                logger.error(f"Error saving atksprite texture: {e}")
                                import traceback
                                logger.error(f"Traceback: {traceback.format_exc()}")
                        
                        # Check for battle backgrounds
                        elif self.is_battlebg_texture(data):
                            try:
                                success, _ = self.save_battlebg_texture(data)
                                if success:
                                    battlebg_count = 1
                            except Exception as e:
                                logger.error(f"Error saving battlebg texture: {e}")
                                import traceback
                                logger.error(f"Traceback: {traceback.format_exc()}")
                        
                        # Check for hit/dmg sprites (dmg_*, hit_*)
                        elif self.is_hit_sprite_texture(data):
                            try:
                                success, _ = self.save_hit_sprite_texture(data)
                            except Exception as e:
                                logger.error(f"Error saving hit sprite texture: {e}")
                                import traceback
                                logger.error(f"Traceback: {traceback.format_exc()}")
                        else:
                            # Debug: record unmatched texture names (sample)
                            with self._unmatched_lock:
                                if len(self._unmatched_texture_names) < self._unmatched_max:
                                    self._unmatched_texture_names.add(self.get_texture_name(data, "Texture2D"))
                        
                        return atksprite_count, battlebg_count
                    except Exception as e:
                        logger.debug(f"Error reading Texture2D object: {e}")
                        return 0, 0
                
                # Process sequentially - nested parallelism causes overhead
                # UnityPy operations are CPU-bound and GIL-limited anyway
                for obj in texture2d_objects:
                    atksprite_count, battlebg_count = process_texture2d(obj)
                    result["atksprites"] += atksprite_count
                    result["battlebgs"] += battlebg_count
            
            # Process Sprite objects (attack sprites and hit/dmg sprites)
            if sprite_objects:
                def process_sprite(obj):
                    try:
                        data = obj.read()
                        if self.is_atksprite_sprite(data):
                            try:
                                success, _ = self.save_atksprite_sprite(data)
                                return 1 if success else 0
                            except Exception as e:
                                logger.error(f"Error saving atksprite sprite: {e}")
                                import traceback
                                logger.error(f"Traceback: {traceback.format_exc()}")
                        elif self.is_hit_sprite_sprite(data):
                            try:
                                self.save_hit_sprite_sprite(data)
                            except Exception as e:
                                logger.error(f"Error saving hit sprite: {e}")
                                import traceback
                                logger.error(f"Traceback: {traceback.format_exc()}")
                        else:
                            with self._unmatched_lock:
                                if len(self._unmatched_texture_names) < self._unmatched_max:
                                    self._unmatched_texture_names.add(self.get_texture_name(data, "Sprite"))
                        return 0
                    except Exception as e:
                        logger.debug(f"Error reading Sprite object: {e}")
                        return 0
                
                # Process sequentially - nested parallelism causes overhead
                for obj in sprite_objects:
                    result["atksprites"] += process_sprite(obj)
            
            # Process stats objects in parallel
            if stats_objects:
                def process_stats(obj):
                    try:
                        data = obj.read()
                        try:
                            return self.process_stats_object(obj, data)
                        except Exception as e:
                            logger.error(f"Error in process_stats_object for {obj.type.name}: {e}")
                            import traceback
                            logger.error(f"Traceback: {traceback.format_exc()}")
                            return {"GameData": 0, "CharacterData": 0, "StatsData": 0, "ConfigData": 0, "JsonData": 0}
                    except Exception as e:
                        logger.debug(f"Error reading stats object {obj.type.name}: {e}")
                        return {"GameData": 0, "CharacterData": 0, "StatsData": 0, "ConfigData": 0, "JsonData": 0}
                
                # Process sequentially - nested parallelism causes overhead
                for obj in stats_objects:
                    stats_result = process_stats(obj)
                    for key in result["stats"]:
                        result["stats"][key] += stats_result.get(key, 0)
            
            # Clear memory (reduce frequency for better performance)
            del env
            # Only collect garbage every 50 files to maximize throughput
            if hasattr(self, '_file_count'):
                self._file_count += 1
            else:
                self._file_count = 1
            if self._file_count % 50 == 0:
                gc.collect()
            
        except Exception as e:
            logger.error(f"Error in extraction from {asset_path}: {e}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")
        
        return result
    
    def save_atksprite_texture(self, texture_data):
        """Save attack sprite texture with minimal processing (add before save to match working detection counts)."""
        try:
            if hasattr(texture_data, 'image') and texture_data.image:
                safe_name = self.get_texture_name(texture_data, "Texture2D")
                if not safe_name:
                    return False, None
                with self._atksprites_lock:
                    if safe_name in self.extracted_atksprites:
                        return False, None
                    self.extracted_atksprites.add(safe_name)
                output_file = self.atksprites_dir.resolve() / f"{safe_name}.png"
                texture_data.image.save(str(output_file), 'PNG', optimize=False)
                return True, output_file.name
            return False, None
        except Exception as e:
            logger.warning(f"Error saving atksprite texture to disk: {e} (dir: {self.atksprites_dir})")
            return False, None
    
    def save_atksprite_sprite(self, sprite_data):
        """Save attack sprite with minimal processing (add before save to match working detection counts)."""
        try:
            safe_name = self.get_texture_name(sprite_data, "Sprite")
            if not safe_name:
                return False, None
            with self._atksprites_lock:
                if safe_name in self.extracted_atksprites:
                    return False, None
                self.extracted_atksprites.add(safe_name)
            output_file = self.atksprites_dir.resolve() / f"{safe_name}.png"
            if hasattr(sprite_data, 'texture') and sprite_data.texture and hasattr(sprite_data.texture, 'image'):
                sprite_data.texture.image.save(str(output_file), 'PNG', optimize=False)
            elif hasattr(sprite_data, 'image') and sprite_data.image:
                sprite_data.image.save(str(output_file), 'PNG', optimize=False)
            else:
                return False, None
            return True, output_file.name
        except Exception as e:
            logger.warning(f"Error saving atksprite sprite to disk: {e} (dir: {self.atksprites_dir})")
            return False, None
    
    def save_battlebg_texture(self, texture_data):
        """Save battle background texture with minimal processing"""
        try:
            if hasattr(texture_data, 'image') and texture_data.image:
                safe_name = self.get_texture_name(texture_data, "Texture2D")
                if not safe_name:
                    return False, None
                with self._battlebgs_lock:
                    self.battlebg_counter += 1
                    counter = self.battlebg_counter
                output_file = self.battlebg_dir.resolve() / f"BattleBg_{counter:04d}_{safe_name}.png"
                texture_data.image.save(str(output_file), 'PNG', optimize=False)
                return True, output_file.name
            return False, None
        except Exception as e:
            logger.warning(f"Error saving battlebg texture to disk: {e} (dir: {self.battlebg_dir})")
            return False, None
    
    def save_hit_sprite_texture(self, texture_data):
        """Save hit/dmg sprite texture (dmg_*, hit_*) to extracted_hit_sprites (add before save to match working detection)."""
        try:
            if not hasattr(texture_data, 'image') or not texture_data.image:
                return False, None
            safe_name = self.get_texture_name(texture_data, "Texture2D")
            if not safe_name:
                return False, None
            with self._hit_sprites_lock:
                if safe_name in self.extracted_hit_sprites:
                    return False, None
                self.extracted_hit_sprites.add(safe_name)
            output_file = self.hit_sprites_dir.resolve() / f"{safe_name}.png"
            texture_data.image.save(str(output_file), 'PNG', optimize=False)
            return True, output_file.name
        except Exception as e:
            logger.warning(f"Error saving hit sprite texture to disk: {e} (dir: {self.hit_sprites_dir})")
            return False, None
    
    def save_hit_sprite_sprite(self, sprite_data):
        """Save hit/dmg sprite (dmg_*, hit_*) to extracted_hit_sprites (add before save to match working detection)."""
        try:
            safe_name = self.get_texture_name(sprite_data, "Sprite")
            if not safe_name:
                return False, None
            with self._hit_sprites_lock:
                if safe_name in self.extracted_hit_sprites:
                    return False, None
                self.extracted_hit_sprites.add(safe_name)
            output_file = self.hit_sprites_dir.resolve() / f"{safe_name}.png"
            if hasattr(sprite_data, 'texture') and sprite_data.texture and hasattr(sprite_data.texture, 'image'):
                sprite_data.texture.image.save(str(output_file), 'PNG', optimize=False)
            elif hasattr(sprite_data, 'image') and sprite_data.image:
                sprite_data.image.save(str(output_file), 'PNG', optimize=False)
            else:
                return False, None
            return True, output_file.name
        except Exception as e:
            logger.warning(f"Error saving hit sprite to disk: {e} (dir: {self.hit_sprites_dir})")
            return False, None
    
    def process_stats_object(self, obj, obj_data):
        """Process stats object with minimal overhead"""
        result = {"GameData": 0, "CharacterData": 0, "StatsData": 0, "ConfigData": 0, "JsonData": 0}
        
        try:
            obj_name = self.get_object_name(obj_data, obj.type.name)
            
            # Skip if obj_name is None or empty
            if not obj_name:
                return result
            
            # Quick categorization without deep analysis
            output_dir = None
            if obj.type.name == "TextAsset":
                result["JsonData"] = 1
                output_dir = self.json_data_dir
            elif "config" in obj_name.lower() or "setting" in obj_name.lower():
                result["ConfigData"] = 1
                output_dir = self.config_data_dir
            elif self.has_character_stats(obj_data) or (
                self.is_character_data_by_name(obj_name) and self.has_any_character_field(obj_data)
            ):
                result["CharacterData"] = 1
                output_dir = self.character_data_dir
            elif self.is_vb_repository_object(obj.type.name, obj_name):
                result["GameData"] = 1
                output_dir = self.game_data_dir
            else:
                result["StatsData"] = 1
                output_dir = self.stats_data_dir
            
            # Ensure output_dir exists and is valid
            if not output_dir or not hasattr(output_dir, '__truediv__'):
                logger.debug(f"Invalid output_dir for {obj.type.name} {obj_name}")
                return result
            
            # Save with minimal processing
            output_file = output_dir / f"{obj.type.name}_{obj_name}.json"
            if not output_file or not hasattr(output_file, 'exists'):
                logger.debug(f"Invalid output_file for {obj.type.name} {obj_name}")
                return result
            
            # Thread-safe check
            file_key = f"{obj.type.name}_{obj_name}"
            with self._stats_lock:
                if file_key in self.extracted_stats_files:
                    return result
                self.extracted_stats_files.add(file_key)
                
            obj_dict = {}
            for attr in dir(obj_data):
                if not attr.startswith('_'):
                    try:
                        value = getattr(obj_data, attr)
                        if isinstance(value, (str, int, float, bool, list, dict)):
                            obj_dict[attr] = value
                    except:
                        pass
            
            # Ensure we can write to the file
            try:
                with open(str(output_file), 'w', encoding='utf-8') as f:
                    # Use compact JSON (no indentation) for faster writes
                    json.dump(obj_dict, f, separators=(',', ':'), ensure_ascii=False, default=str)
                
                # Update stats counter immediately (thread-safe)
                with self._stats_lock:
                    for key in result:
                        if result[key] > 0:
                            self.extracted_stats[key] += result[key]
                    total_stats = sum(self.extracted_stats.values())
                
                # Call callback to update GUI counter immediately after file is written
                if self.stats_callback:
                    try:
                        self.stats_callback(total_stats)
                    except Exception:
                        pass  # Don't let callback errors break extraction
                            
            except Exception as e:
                logger.debug(f"Error writing to {output_file}: {e}")
                return result
                    
        except Exception as e:
            logger.debug(f"Error in process_stats_object: {e}")
            pass
        
        return result
    
    def process_bundle_files(self, bundle_files):
        """Process bundle files with parallel processing"""
        # Sort by size (largest first) for better efficiency
        bundle_files.sort(key=lambda x: x.stat().st_size, reverse=True)
        
        # CRITICAL OPTIMIZATION: Match worker count to CPU cores
        # Too many threads causes context switching overhead
        cpu_count = os.cpu_count() or 1
        max_workers = min(cpu_count + 2, len(bundle_files), 8)  # Cap at 8 to reduce overhead
        logger.info(f"Using {max_workers} parallel workers for bundle file processing (CPU-OPTIMIZED: {cpu_count} cores)")
        
        with safe_tqdm(total=len(bundle_files), desc="Processing bundle files", unit="bundle") as pbar:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Submit all bundles for processing
                future_to_bundle = {
                    executor.submit(self.extract_all_from_single_bundle, bundle_path): bundle_path
                    for bundle_path in bundle_files
                }
                
                # Process completed tasks as they finish
                for future in as_completed(future_to_bundle):
                    bundle_path = future_to_bundle[future]
                    try:
                        future.result()
                        
                        # Thread-safe progress update
                        with self._audio_lock:
                            pbar.set_postfix({
                                'Audio': len(self.extracted_audio)
                            })
                        
                    except Exception as e:
                        logger.error(f"Error processing bundle {bundle_path}: {e}")
                    
                    pbar.update(1)
    
    def extract_all_from_single_bundle(self, bundle_path):
        """Extract audio, textures/sprites, and stats (including character_data) from a single bundle."""
        try:
            env = UnityPy.load(str(bundle_path))
            audio_objects = []
            texture2d_objects = []
            sprite_objects = []
            stats_objects = []
            for obj in env.objects:
                obj_type = obj.type.name
                if obj_type == "AudioClip":
                    audio_objects.append(obj)
                elif obj_type == "Texture2D":
                    texture2d_objects.append(obj)
                elif obj_type == "Sprite":
                    sprite_objects.append(obj)
                elif self.is_relevant_object_type(obj_type):
                    stats_objects.append(obj)
            # Audio
            for obj in audio_objects:
                try:
                    audio_data = obj.read()
                    self.extract_audio_clip(obj, audio_data)
                except Exception:
                    pass
            # Texture2D: attack sprites, battle bgs, hit/dmg sprites (same logic as asset files)
            for obj in texture2d_objects:
                try:
                    data = obj.read()
                    if self.is_atksprite_texture(data):
                        self.save_atksprite_texture(data)
                    elif self.is_battlebg_texture(data):
                        self.save_battlebg_texture(data)
                    elif self.is_hit_sprite_texture(data):
                        self.save_hit_sprite_texture(data)
                except Exception:
                    pass
            # Sprite: attack sprites, hit/dmg sprites
            for obj in sprite_objects:
                try:
                    data = obj.read()
                    if self.is_atksprite_sprite(data):
                        self.save_atksprite_sprite(data)
                    elif self.is_hit_sprite_sprite(data):
                        self.save_hit_sprite_sprite(data)
                except Exception:
                    pass
            # Stats (GameData, CharacterData, StatsData, ConfigData, JsonData)
            for obj in stats_objects:
                try:
                    data = obj.read()
                    self.process_stats_object(obj, data)
                except Exception:
                    pass
            del env
            # Only collect garbage every 25 bundles to maximize throughput
            if hasattr(self, '_bundle_count'):
                self._bundle_count += 1
            else:
                self._bundle_count = 1
            if self._bundle_count % 25 == 0:
                gc.collect()
            
        except Exception as e:
            logger.error(f"Error in bundle extraction from {bundle_path}: {e}")
    
    def extract_audio_clip(self, audio_obj, audio_data):
        """Extract audio clip. UnityPy returns {filename_with_ext: bytes}. Use correct extension; count on attempt (match working behavior)."""
        audio_name = audio_data.m_Name
        with self._audio_lock:
            if audio_name in self.extracted_audio:
                return False
            self.extracted_audio.add(audio_name)
        try:
            if not audio_data.samples:
                self.failed_audio.add(audio_name)
                return False
            # samples dict key is filename with correct extension (e.g. "se_attack.wav" or "bgm_01.ogg")
            sample_filename, sample_data = next(iter(audio_data.samples.items()))
            if not sample_data:
                self.failed_audio.add(audio_name)
                return False
            # Use key as filename if it looks like "name.ext", else fallback to audio_name.wav
            out_filename = sample_filename if (sample_filename and "." in sample_filename) else f"{audio_name}.wav"
            if audio_name.startswith("se_"):
                out_dir = self.se_dir
            elif audio_name.startswith("bgm_"):
                out_dir = self.bgm_dir
            else:
                out_dir = self.game_dir
            output_path = out_dir.resolve() / out_filename
            with open(str(output_path), 'wb') as f:
                f.write(sample_data)
            return True
        except Exception as e:
            logger.warning(f"Error saving audio clip to disk {audio_name}: {e}")
            self.failed_audio.add(audio_name)
            return False
    
def main():
    parser = argparse.ArgumentParser(description="Vital Bracelet Arena Asset Extractor")
    parser.add_argument("--apk", help="Path to main APK file (e.g., VITAL BRACELET ARENA_2.1.0.apk) - optional if temp_extraction exists")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    extractor = MasterExtractor()
    
    try:
        if args.apk:
            # If APK provided, extract it first
            extractor.process_main_apk(args.apk)
        else:
            # If no APK provided, work with existing temp_extraction
            extractor.run_extraction()
    except Exception as e:
        logger.error(f"Error during extraction: {e}")
    finally:
        # Clean up temporary folders after extraction (whether successful or not)
        extractor.cleanup_temp_folders()

if __name__ == "__main__":
    main()