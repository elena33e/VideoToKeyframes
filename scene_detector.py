# Identifică intervalele scenelor și exportă fiecare scenă într-un fișier video

import math
from pathlib import Path
from typing import List

from scenedetect import (
    ContentDetector,
    FrameTimecode,
    detect,
    is_ffmpeg_available,
    open_video,
    split_video_ffmpeg,
)

from interfaces import ISceneDetector, Scene


class PySceneDetectorService(ISceneDetector):
    def __init__(self, threshold: float = 27.0):
        if not math.isfinite(threshold) or threshold <= 0:
            raise ValueError(
                "Pragul de detectare trebuie să fie pozitiv și finit."
            )

        self.threshold = threshold
        self._frame_rates = {}
        self._ffmpeg_checked = False

    def detect_scenes(self, video_path: Path) -> List[Scene]:
        video_path = Path(video_path).resolve()

        if not video_path.is_file() or video_path.stat().st_size == 0:
            raise ValueError(
                f"Fișier video inexistent sau gol: {video_path}"
            )

        try:
            intervals = detect(
                str(video_path),
                ContentDetector(threshold=self.threshold),
                start_in_scene=True,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Detectarea scenelor a eșuat: {exc}"
            ) from exc

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

        if not scenes or any(
            not math.isfinite(scene.start_seconds)
            or not math.isfinite(scene.end_seconds)
            or scene.start_seconds < 0
            or scene.end_seconds <= scene.start_seconds
            for scene in scenes
        ):
            raise RuntimeError(
                "Videoclipul nu conține intervale decodabile valide."
            )

        # Reutilizăm rata de cadre identificată la detectare.
        self._frame_rates[video_path] = intervals[0][0].frame_rate

        return scenes

    def export_scene(
        self,
        video_path: Path,
        scene: Scene,
        output_dir: Path,
    ) -> Path:
        video_path = Path(video_path).resolve()
        output_dir = Path(output_dir).resolve()

        if not video_path.is_file():
            raise FileNotFoundError(
                f"Videoclipul nu există: {video_path}"
            )

        if (
            not math.isfinite(scene.start_seconds)
            or not math.isfinite(scene.end_seconds)
            or scene.start_seconds < 0
            or scene.end_seconds <= scene.start_seconds
        ):
            raise ValueError("Intervalul scenei este invalid.")

        # Verificăm disponibilitatea o singură dată pe instanță.
        if not self._ffmpeg_checked:
            if not is_ffmpeg_available():
                raise RuntimeError(
                    "FFmpeg nu este disponibil pentru export."
                )
            self._ffmpeg_checked = True

        frame_rate = self._frame_rates.get(video_path)

        if frame_rate is None:
            # Permite și exportul fără detectare anterioară
            # pe această instanță.
            frame_rate = open_video(str(video_path)).frame_rate
            self._frame_rates[video_path] = frame_rate

        start = FrameTimecode(
            float(scene.start_seconds),
            fps=frame_rate,
        )
        end = FrameTimecode(
            float(scene.end_seconds),
            fps=frame_rate,
        )

        # Directorul trebuie să fie nou.
        output_dir.mkdir(parents=True, exist_ok=False)
        output_path = output_dir / f"scene-{scene.index:04d}.mp4"

        try:
            return_code = split_video_ffmpeg(
                input_video_path=str(video_path),
                scene_list=[(start, end)],
                output_dir=output_dir,
                output_file_template=output_path.name,
                arg_override=(
                    "-hide_banner -loglevel error "
                    "-map 0:v:0 -map 0:a? "
                    "-c:v libx264 -preset veryfast -crf 18 "
                    "-c:a aac"
                ),
                show_progress=False,
                show_output=True,
            )

        except Exception as exc:
            raise RuntimeError(
                f"Exportul scenei {scene.index} a eșuat: {exc}"
            ) from exc

        if return_code != 0:
            raise RuntimeError(
                f"FFmpeg a eșuat pentru scena {scene.index}, "
                f"cod {return_code}. "
                "Detaliile FFmpeg sunt afișate în consola aplicației."
            )

        if (
            not output_path.is_file()
            or output_path.stat().st_size == 0
        ):
            raise RuntimeError(
                f"Clipul scenei {scene.index} lipsește sau este gol."
            )

        return output_path