import shutil
import subprocess

import pytest

from maya_sawa.services.azure_speech_rest import merge_mp3_parts


def test_multi_part_mp3_merge_decodes_as_complete_audio(tmp_path):
    ffmpeg = shutil.which('ffmpeg')
    ffprobe = shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        pytest.skip('ffmpeg and ffprobe are required for the media integration test')
    parts = []
    for index, (frequency, duration) in enumerate(((440, 0.6), (660, 0.8))):
        path = tmp_path / f'part-{index}.mp3'
        subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                        f'sine=frequency={frequency}:duration={duration}', '-ar', '24000', '-ac', '1',
                        '-b:a', '48k', '-write_xing', '1', '-id3v2_version', '3', '-y', str(path)],
                       check=True, capture_output=True)
        parts.append(path.read_bytes())

    merged = merge_mp3_parts(parts)
    merged_path = tmp_path / 'complete.mp3'
    merged_path.write_bytes(merged)
    decoded = subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-i', str(merged_path),
                              '-map', '0:a:0', '-f', 'null', '-'], capture_output=True)
    assert decoded.returncode == 0, decoded.stderr.decode(errors='replace')
    duration = float(subprocess.check_output([ffprobe, '-v', 'error', '-show_entries', 'format=duration',
                                             '-of', 'csv=p=0', str(merged_path)]).decode().strip())
    assert duration == pytest.approx(1.4, abs=0.15)
