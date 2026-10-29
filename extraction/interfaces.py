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
        """Returnează intervalele scenelor"""
        raise NotImplementedError

    @abstractmethod
    def export_scene(
        self, video_path: Path, scene: Scene, output_dir: Path
    ) -> Path:
        """Exportă o singură scenă într-un director nou"""
        raise NotImplementedError



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
