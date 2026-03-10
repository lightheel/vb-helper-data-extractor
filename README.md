# VB Helper Data Extractor

APK extractor built using UnityPy.

Extracts JSON game data, .wav SFX/BGM, battle background PNGs, and attack sprite PNGs.

# Instructions
1. Download [windows-vb-helper-data-extractor-v1.0.1.exe](https://github.com/lightheel/vb-helper-data-extractor/releases/download/v.1.0.1/windows-vb-helper-data-extractor-v1.0.1.exe) from v1.0.1 releases.

2. Select VITAL BRACELET ARENA_2.1.0.apk with the "Browse" button. (If you have an XAPK file, rename the file type to APK)

![apk_select](https://github.com/lightheel/vb-helper-data-extractor/blob/main/apk_select.png)


![apk_example](https://github.com/lightheel/vb-helper-data-extractor/blob/main/apk_example.png)


3. Extract the files with "Extract Assets" button.

![extract_button](https://github.com/lightheel/vb-helper-data-extractor/blob/main/extract_button.png)


4. Create a VBHelper folder on your Android device's root storage if one doesn't already exist.

4. Copy the following folders to VBHelper battle_sprites folder:
- extracted_atksprites
- extracted_battlebgs
- extracted_digimon_stats
- extracted_hit_sprites

Place audio files in the VBHelper folder:
- extracted_audio


![extracted_folder_names](https://github.com/lightheel/vb-helper-data-extractor/blob/main/extracted_folder_names.png)

# NOTE
Setting up the assets for using Battle requires you run both **VB Helper Data Extractor** and **VB Helper Sprite Extractor**.

**VB Helper Sprite Extractor** can be found [here](https://github.com/lightheel/vb-helper-sprite-extractor).
