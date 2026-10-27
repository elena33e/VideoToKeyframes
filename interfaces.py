from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List

# current/total sunt scene finalizate/scene selectate.
# O scenă finalizată poate fi reușită sau eșuată.
# total=0: etapă cu progres nedeterminat.
ProgressCallback = Callable[[str, int, int], None]


@dataclass(frozen=True)
class Scene:
    index: int
    start_seconds: float
    end_seconds: float
    start_frame: int
    end_frame: int

    @property
    def midpoint(self) -> float:
        return (self.start_seconds + self.end_seconds) / 2


class ISceneDetector(ABC):
    @abstractmethod
    def detect_scenes(self, video_path: Path) -> List[Scene]:
        """Returnează intervalele scenelor, fără exportul clipurilor."""
        raise NotImplementedError

    @abstractmethod
    def export_scene(
        self, video_path: Path, scene: Scene, output_dir: Path
    ) -> Path:
        """Exportă o singură scenă într-un director nou."""
        raise NotImplementedError

    def detect_and_split(self, video_path: Path, output_dir: Path) -> List[Path]:
        """Compatibilitate cu apelurile vechi; exportă toate scenele."""
        scenes = self.detect_scenes(video_path)
        if len(scenes) == 1:
            return [Path(video_path)]
        return [
            self.export_scene(video_path, scene, output_dir / f"scene_{scene.index:04d}")
            for scene in scenes
        ]


class IKeyframeExtractor(ABC):
    @abstractmethod
    def extract_keyframes(
        self, video_path: Path, output_dir: Path, num_frames: int
    ) -> List[Path]:
        """Salvează între 1 și num_frames imagini sau ridică o excepție.

        output_dir trebuie să fie nou. Rezultatele unei încercări eșuate
        nu trebuie publicate drept rezultate valide.
        """
        raise NotImplementedError
