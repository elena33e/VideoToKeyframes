
import math
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from uuid import uuid4

from extraction.interfaces import (
    IKeyframeExtractor,
    ISceneDetector,
    ProgressCallback,
)

from extraction.models import (
    ExtractedFrame,
    ExtractionError,
    ExtractionResult,
    ExtractionSettings,
    SceneExtractionResult,
)
# Scenele mai scurte decât acest prag sunt comasate cu o scenă vecină
MIN_SCENE_DURATION_SECONDS = 0.5

class PipelineError(RuntimeError):
    def __init__(self, message: str, result: ExtractionResult):
        super().__init__(message)
        self.result = result


class VideoProcessingPipeline:
    def __init__(
        self,
        scene_detector: ISceneDetector,
        keyframe_extractor: IKeyframeExtractor,
    ):
        self.scene_detector = scene_detector
        self.keyframe_extractor = keyframe_extractor

    @staticmethod
    def _select_scenes(scenes, count):
        """Selectează scene distribuite pe durata videoclipului."""
        if not scenes or count <= 0:
            return []

        if count >= len(scenes):
            return sorted(
                scenes,
                key=lambda scene: scene.start_seconds,
            )

        remaining = list(scenes)

        first = min(scene.start_seconds for scene in scenes)
        last = max(scene.end_seconds for scene in scenes)

        anchors = (
            [(first + last) / 2]
            if count == 1
            else [
                first + (last - first) * i / (count - 1)
                for i in range(count)
            ]
        )

        selected = []

        for anchor in anchors:
            scene = min(
                remaining,
                key=lambda item: (
                    abs(item.midpoint - anchor),
                    item.index,
                ),
            )

            remaining.remove(scene)
            selected.append(scene)

        return sorted(
            selected,
            key=lambda scene: scene.start_seconds,
        )

    @staticmethod
    def _merge_short_scenes(
            scenes,
            min_duration=MIN_SCENE_DURATION_SECONDS,
    ):
        """Unește fragmentele foarte scurte cu o scenă vecină"""
        merged = []

        for scene in sorted(
            scenes,
            key=lambda item: item.start_seconds,
        ):
            duration = scene.end_seconds - scene.start_seconds

            if merged and duration < min_duration:
                merged[-1] = replace(
                    merged[-1],
                    end_seconds=scene.end_seconds,
                    end_frame=scene.end_frame,
                )
            else:
                merged.append(scene)

        # Prima scenă nu are un vecin anterior.
        if len(merged) > 1:
            first, second = merged[:2]

            if first.end_seconds - first.start_seconds < min_duration:
                merged[:2] = [
                    replace(
                        first,
                        end_seconds=second.end_seconds,
                        end_frame=second.end_frame,
                    )
                ]

        return merged

    @classmethod
    def _allocate_frames(
            cls, scenes, seconds_per_keyframe, max_total_keyframes=None
    ):
        """Calculează o singură dată planul de extragere."""
        ordered = sorted(scenes, key=lambda scene: scene.start_seconds)
        if not ordered:
            return []

        desired = []
        for scene in ordered:
            duration = scene.end_seconds - scene.start_seconds
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError(
                    "Duratele scenelor trebuie să fie pozitive și finite."
                )

            ratio = duration / seconds_per_keyframe
            if not math.isfinite(ratio):
                raise ValueError("Intervalul pentru keyframes este prea mic.")

            desired.append(max(1, math.ceil(ratio)))

        if max_total_keyframes is None:
            return list(zip(ordered, desired))

        if max_total_keyframes < len(ordered):
            selected = cls._select_scenes(ordered, max_total_keyframes)
            return [(scene, 1) for scene in selected]

        if max_total_keyframes >= sum(desired):
            return list(zip(ordered, desired))

        # Rezervăm un cadru pentru fiecare scenă.
        remaining = max_total_keyframes - len(ordered)
        capacities = [count - 1 for count in desired]
        total_capacity = sum(capacities)

        # Distribuim restul proporțional cu cererea suplimentară.
        parts = [
            divmod(remaining * capacity, total_capacity)
            for capacity in capacities
        ]
        counts = [1 + quotient for quotient, _ in parts]

        unassigned = max_total_keyframes - sum(counts)
        order = sorted(
            range(len(ordered)),
            key=lambda i: (-parts[i][1], ordered[i].index),
        )
        for i in order[:unassigned]:
            counts[i] += 1

        return list(zip(ordered, counts))

    @staticmethod
    def _save_manifest(result: ExtractionResult) -> None:
        """Salvează manifestul folosind un fișier temporar."""
        temporary = result.manifest.with_suffix(".json.tmp")
        temporary.write_text(
            result.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(result.manifest)

    def run(
            self,
            input_video: Path,
            base_output_dir: Path,
            max_total_keyframes: int | None = None,
            progress_callback: ProgressCallback | None = None,
            cancel_event: Event | None = None,
            *,
            seconds_per_keyframe: float,
    ) -> ExtractionResult:
        input_video = Path(input_video).resolve()

        if not input_video.is_file() or input_video.stat().st_size == 0:
            raise ValueError("Selectează un fișier video existent și nevid.")

        if max_total_keyframes is not None and (
                type(max_total_keyframes) is not int or max_total_keyframes < 1
        ):
            raise ValueError("Limita totală trebuie să fie un întreg pozitiv.")

        if (
                type(seconds_per_keyframe) not in (int, float)
                or not math.isfinite(seconds_per_keyframe)
                or seconds_per_keyframe <= 0
        ):
            raise ValueError(
                "Intervalul pentru keyframes trebuie să fie pozitiv și finit."
            )

        settings = ExtractionSettings(
            seconds_per_keyframe=seconds_per_keyframe,
            min_scene_duration_seconds=MIN_SCENE_DURATION_SECONDS,
            max_total_keyframes=max_total_keyframes,
            threshold=getattr(self.scene_detector, "threshold", None),
            max_workers=getattr(self.keyframe_extractor, "max_workers", None),
            katna_window_frames=getattr(
                self.keyframe_extractor, "window_frames", None
            ),
        )

        cancel = cancel_event if cancel_event is not None else Event()

        run_id = (
            f"{input_video.stem[:60]}_"
            f"{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:8]}"
        )
        run_dir = Path(base_output_dir).resolve() / run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        result = ExtractionResult(
            run_id=run_id,
            input_video=input_video,
            output_dir=run_dir,
            manifest=run_dir / "manifest.json",
            started_at=datetime.now(timezone.utc),
            settings=settings,
        )

        def notify(message, current=0, total=0):
            if progress_callback is not None:
                progress_callback(message, current, total)

        failure = None

        try:
            self._save_manifest(result)
            scenes = []

            if not cancel.is_set():
                notify("Detectarea scenelor…")
                scenes = self.scene_detector.detect_scenes(input_video)

                if not scenes:
                    raise RuntimeError(
                        "Detectorul nu a returnat nicio scenă validă."
                    )

                if len({scene.index for scene in scenes}) != len(scenes):
                    raise RuntimeError(
                        "Detectorul a returnat indici de scenă duplicați."
                    )

                result.detected_scenes = len(scenes)

                scenes = self._merge_short_scenes(
                    scenes,
                    min_duration=MIN_SCENE_DURATION_SECONDS,
                )

            allocation = self._allocate_frames(
                scenes,
                seconds_per_keyframe,
                max_total_keyframes,
            )

            requested_by_scene = {
                scene.index: count
                for scene, count in allocation
            }

            result.total_scenes = len(scenes)
            result.selected_scenes = len(allocation)
            result.omitted_scenes = len(scenes) - len(allocation)
            result.target_keyframes = sum(requested_by_scene.values())

            records = {
                scene.index: SceneExtractionResult(
                    index=scene.index,
                    start_seconds=scene.start_seconds,
                    end_seconds=scene.end_seconds,
                    start_frame=scene.start_frame,
                    end_frame=scene.end_frame,
                    status=(
                        "pending"
                        if scene.index in requested_by_scene
                        else "not_selected"
                    ),
                    requested_frames=requested_by_scene.get(scene.index, 0),
                )
                for scene in scenes
            }

            result.scenes = tuple(records.values())
            self._save_manifest(result)

            used_paths: set[Path] = set()

            for scene, requested in allocation:
                if cancel.is_set():
                    break

                record = records[scene.index]
                record.status = "processing"

                current = result.processed_scenes
                total = result.selected_scenes

                self._save_manifest(result)

                try:
                    notify(
                        f"Scena {scene.index}: pregătire…",
                        current,
                        total,
                    )

                    if len(scenes) == 1:
                        clip_path = input_video
                    else:
                        clip_path = self.scene_detector.export_scene(
                            input_video,
                            scene,
                            run_dir / "scenes" / f"scene_{scene.index:04d}",
                        )

                    record.clip = Path(clip_path)

                    if cancel.is_set():
                        record.status = "cancelled"
                        break

                    notify(
                        f"Scena {scene.index}: extragerea a maximum "
                        f"{requested} cadre…",
                        current,
                        total,
                    )

                    images = self.keyframe_extractor.extract_keyframes(
                        video_path=clip_path,
                        output_dir=(
                                run_dir / "keyframes" / f"scene_{scene.index:04d}"
                        ),
                        num_frames=requested,
                    )

                    images = [
                        Path(path).resolve()
                        for path in images
                    ]

                    if not images or len(images) > requested:
                        raise RuntimeError(
                            "Extractorul a returnat un număr invalid de cadre."
                        )

                    if len(set(images)) != len(images) or any(
                            not path.is_file() or path.stat().st_size == 0
                            for path in images
                    ):
                        raise RuntimeError(
                            "Extractorul a returnat imagini "
                            "lipsă, goale sau duplicate."
                        )

                    if used_paths.intersection(images):
                        raise RuntimeError(
                            "O imagine a fost returnată pentru mai multe scene."
                        )

                    frames = tuple(
                        ExtractedFrame(
                            frame_id=f"{run_id}/{uuid4().hex}",
                            scene_index=scene.index,
                            image_path=path.relative_to(run_dir),
                        )
                        for path in images
                    )

                    record.frames = frames
                    record.status = "success"

                    used_paths.update(images)
                    result.total_keyframes += len(frames)
                    result.covered_scenes += 1

                except Exception as exc:
                    record.status = "failed"
                    record.error = str(exc)

                    result.errors += (
                        ExtractionError(
                            scene=scene.index,
                            message=str(exc),
                        ),
                    )

                result.processed_scenes += 1
                self._save_manifest(result)

                notify(
                    f"Scene procesate: {result.processed_scenes} / {total}. "
                    f"Cadre salvate: {result.total_keyframes}.",
                    result.processed_scenes,
                    total,
                )

            if cancel.is_set():
                for record in result.scenes:
                    if record.status == "pending":
                        record.status = "cancelled"

                result.status = "cancelled"
                result.message = (
                    "Procesare anulată. Rezultatele salvate au fost păstrate."
                )

            elif result.total_keyframes == 0:
                raise RuntimeError(
                    "Nu s-a extras niciun cadru. Consultă raportul."
                )

            elif result.errors:
                result.status = "partial"
                result.message = (
                    "Procesare finalizată cu erori în unele scene."
                )

            else:
                result.status = "success"
                result.message = "Procesare finalizată cu succes."

            if result.omitted_scenes:
                result.message += (
                    f" Scene omise prin limita globală: {result.omitted_scenes}."
                )

        except Exception as exc:
            failure = exc
            result.status = "failed"
            result.message = str(exc)

            result.errors += (
                ExtractionError(message=str(exc)),
            )

        result.finished_at = datetime.now(timezone.utc)

        try:
            self._save_manifest(result)

        except OSError as exc:
            failure = exc
            result.status = "failed"
            result.message = (
                f"Raportul rulării nu a putut fi salvat: {exc}"
            )

        if failure is not None:
            raise PipelineError(result.message, result) from failure

        return result