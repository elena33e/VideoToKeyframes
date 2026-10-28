from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List

import cv2
import Katna.config as katna_config
from Katna.video import Video
from Katna.writer import KeyFrameDiskWriter

from interfaces import IKeyframeExtractor


# De testat cu mai multe valori!!
KATNA_WINDOW_FRAMES = 15


class CheckedFrameWriter(KeyFrameDiskWriter):
    def __init__(self, location: Path, limit: int):
        super().__init__(location=str(location))
        self.limit = limit
        self.paths = []

    def save_frame_data_to_disk(self, frame, file_name):
        path = Path(self.output_dir_path) / f"{file_name}{self.file_ext}"

        if not cv2.imwrite(str(path), frame):
            raise OSError(
                f"Imaginea nu a putut fi salvată: {path}"
            )

        self.paths.append(path)

    def write(self, filepath, data):
        super().write(filepath, data[:self.limit])


class KatnaKeyframeExtractorService(IKeyframeExtractor):
    def __init__(self, max_workers: int = 2):
        if type(max_workers) is not int or max_workers < 1:
            raise ValueError(
                "Numărul de procese Katna trebuie să fie pozitiv."
            )

        self.window_frames = KATNA_WINDOW_FRAMES

        if (
            type(self.window_frames) is not int
            or self.window_frames < 3
        ):
            raise ValueError(
                "Fereastra Katna trebuie să fie "
                "un întreg de minimum 3 cadre."
            )

        self.max_workers = max_workers
        self._engine = Video()
        self._engine.n_processes = max_workers

    def extract_keyframes(
        self,
        video_path: Path,
        output_dir: Path,
        num_frames: int = 3,
    ) -> List[Path]:
        video_path = Path(video_path).resolve()
        output_dir = Path(output_dir).resolve()

        if not video_path.is_file() or video_path.stat().st_size == 0:
            raise ValueError(
                f"Fișier video inexistent sau gol: {video_path}"
            )

        if type(num_frames) is not int or num_frames < 1:
            raise ValueError(
                "Numărul de cadre trebuie să fie un întreg pozitiv."
            )

        if output_dir.exists():
            raise FileExistsError(
                "Directorul imaginilor trebuie să fie nou: "
                f"{output_dir}"
            )

        output_dir.parent.mkdir(parents=True, exist_ok=True)

        old_temp_folder = self._engine.temp_folder
        old_window = katna_config.FrameExtractor.len_window

        try:
            # Configurarea se aplică înainte ca Katna să creeze
            # extractorul de candidați pentru această scenă.
            katna_config.FrameExtractor.len_window = self.window_frames

            with TemporaryDirectory(
                prefix=".katna-",
                dir=output_dir.parent,
            ) as temp:
                temp_path = Path(temp)
                clips_dir = temp_path / "clips"
                images_dir = temp_path / "images"

                clips_dir.mkdir()
                images_dir.mkdir()

                self._engine.temp_folder = str(clips_dir)
                writer = CheckedFrameWriter(images_dir, num_frames)

                self._engine.extract_video_keyframes(
                    no_of_frames=num_frames,
                    file_path=str(video_path),
                    writer=writer,
                )

                if not writer.paths or any(
                    not path.is_file()
                    or path.stat().st_size == 0
                    for path in writer.paths
                ):
                    raise RuntimeError(
                        "Katna nu a generat imagini valide."
                    )

                names = [path.name for path in writer.paths]

                # Publicăm imaginile după verificarea extragerii
                images_dir.rename(output_dir)

                return [
                    output_dir / name
                    for name in names
                ]

        except Exception as exc:
            raise RuntimeError(
                f"Extragerea a eșuat pentru {video_path.name}: {exc}"
            ) from exc

        finally:
            self._engine.temp_folder = old_temp_folder
            katna_config.FrameExtractor.len_window = old_window