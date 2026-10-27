import math
import shutil
import subprocess
from pathlib import Path
from typing import List

from scenedetect import ContentDetector, detect
from interfaces import ISceneDetector, Scene


class PySceneDetectorService(ISceneDetector):
    def __init__(self, threshold: float = 27.0):
        if not math.isfinite(threshold) or threshold <= 0:
            raise ValueError("Pragul de detectare trebuie să fie pozitiv și finit.")
        self.threshold = threshold

    def detect_scenes(self, video_path: Path) -> List[Scene]:
        video_path = Path(video_path).resolve()
        if not video_path.is_file() or video_path.stat().st_size == 0:
            raise ValueError(f"Fișier video inexistent sau gol: {video_path}")
        try:
            intervals = detect(
                str(video_path), ContentDetector(threshold=self.threshold),
                start_in_scene=True,
            )
        except Exception as exc:
            raise RuntimeError(f"Detectarea scenelor a eșuat: {exc}") from exc

        scenes = [
            Scene(
                index=index,
                start_seconds=start.seconds,
                end_seconds=end.seconds,
                start_frame=start.frame_num,
                end_frame=end.frame_num,
            )
            for index, (start, end) in enumerate(intervals, start=1)
        ]
        if not scenes or any(s.end_seconds <= s.start_seconds for s in scenes):
            raise RuntimeError("Videoclipul nu conține intervale decodabile valide.")
        return scenes

    @staticmethod
    def _ffmpeg_path() -> str:
        binary = shutil.which("ffmpeg")
        if binary:
            return binary
        try:
            from imageio_ffmpeg import get_ffmpeg_exe
            return get_ffmpeg_exe()
        except Exception as exc:
            raise RuntimeError(
                "FFmpeg nu este disponibil. Instalează FFmpeg sau imageio-ffmpeg."
            ) from exc

    def export_scene(
        self, video_path: Path, scene: Scene, output_dir: Path
    ) -> Path:
        video_path = Path(video_path).resolve()
        output_dir = Path(output_dir).resolve()
        if not video_path.is_file():
            raise FileNotFoundError(f"Videoclipul nu există: {video_path}")
        if scene.start_seconds < 0 or scene.end_seconds <= scene.start_seconds:
            raise ValueError("Intervalul scenei este invalid.")
        output_dir.mkdir(parents=True, exist_ok=False)
        output_path = output_dir / f"scene-{scene.index:04d}.mp4"
        command = [
            self._ffmpeg_path(), "-hide_banner", "-loglevel", "error",
            "-nostdin", "-n", "-ss", f"{scene.start_seconds:.9f}",
            "-i", str(video_path),
            "-t", f"{scene.end_seconds - scene.start_seconds:.9f}",
            "-map", "0:v:0", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-c:a", "aac", "-sn", str(output_path),
        ]
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            raise RuntimeError(f"FFmpeg nu a putut fi pornit: {exc}") from exc
        if completed.returncode != 0:
            raise RuntimeError(
                f"FFmpeg a eșuat pentru scena {scene.index}: "
                f"{completed.stderr.strip()[-2000:]}"
            )
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RuntimeError(f"Clipul scenei {scene.index} lipsește sau este gol.")
        return output_path
