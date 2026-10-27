"""Măsurători pentru pipeline"""

import json
import sys
from multiprocessing.pool import Pool
from pathlib import Path
from time import perf_counter

from Katna.image_selector import ImageSelector

from keyframe_extractor import KatnaKeyframeExtractorService
from scene_detector import PySceneDetectorService


class PerformanceMonitor:
    def __init__(self):
        self.report = {
            "measurement": "wall_time_in_pipeline_worker",
            "detection_seconds": 0.0,
            "pool_creations": 0,
            "exports": [],
            "extractions": [],
            "selections": [],
            "observer_errors": [],
        }
        self._active = {}
        self._scene = None
        self._selection = None

    def __enter__(self):
        if sys.getprofile() is not None:
            raise RuntimeError(
                "Rulează diagnosticul cu Run, fără alt profiler activ."
            )



        self._targets = {
            PySceneDetectorService.detect_scenes.__code__: "detect",
            PySceneDetectorService.export_scene.__code__: "export",
            KatnaKeyframeExtractorService.extract_keyframes.__code__: "extract",
            ImageSelector.select_best_frames.__code__: "select",
            ImageSelector.__filter_optimum_brightness_and_contrast_images__.__code__: "filter",
            Pool.__init__.__code__: "pool",
            Pool.map.__code__: "map",
        }

        self._started = perf_counter()
        sys.setprofile(self._observe)
        return self

    def __exit__(self, exc_type, exc, traceback):
        sys.setprofile(None)

        self.report["pipeline_seconds"] = (
            perf_counter() - self._started
        )
        self.report["observer_ok"] = (
            not self.report["observer_errors"]
        )

        selections = self.report["selections"]

        self.report["totals"] = {
            "export_seconds": sum(
                x.get("seconds", 0)
                for x in self.report["exports"]
            ),
            "extraction_seconds": sum(
                x.get("seconds", 0)
                for x in self.report["extractions"]
            ),
            "selection_seconds": sum(
                x.get("seconds", 0)
                for x in selections
            ),
            "filter_seconds": sum(
                x["filter_seconds"]
                for x in selections
            ),
            "selection_calls": len(selections),
            "calls_with_repeated_filtering": sum(
                x["filter_rounds"] > 1
                for x in selections
            ),
            "brightness_map_items": sum(
                x["brightness_map_items"]
                for x in selections
            ),
            "entropy_map_items": sum(
                x["entropy_map_items"]
                for x in selections
            ),
        }

        return False

    def _observe(self, frame, event, arg):
        if event not in ("call", "return"):
            return

        kind = self._targets.get(frame.f_code)
        if kind is None:
            return

        try:
            self._record(frame, event, arg, kind)
        except Exception as exc:
            # O problemă de diagnostic nu trebuie
            # să oprească procesarea videoclipului.
            self.report["observer_errors"].append(
                f"{type(exc).__name__}: {exc}"
            )
            sys.setprofile(None)

    def _record(self, frame, event, arg, kind):
        if event == "return":
            saved = self._active.pop(id(frame), None)
            if saved is None:
                return

            started, entry, previous = saved
            elapsed = perf_counter() - started

            if kind == "detect":
                self.report["detection_seconds"] += elapsed

            elif kind == "filter":
                entry["filter_seconds"] += elapsed
                if isinstance(arg, list):
                    entry["filter_rounds_completed"] += 1

            else:
                entry["seconds"] = elapsed

                if kind == "extract":
                    self._scene = previous

                elif kind == "select":
                    entry["returned"] = (
                        len(arg) if isinstance(arg, list)
                        else None
                    )
                    self._selection = previous

            return

        values = frame.f_locals
        previous = None

        if kind == "pool":
            self.report["pool_creations"] += 1

            if self._scene is not None:
                self._scene["pool_creations"] += 1

            return

        if kind == "map":
            name = getattr(
                values.get("func"),
                "__name__",
                "",
            )

            if self._selection is not None:
                field = {
                    "__get_brightness_score__":
                        "brightness_map_items",
                    "__get_entropy_score__":
                        "entropy_map_items",
                }.get(name)

                if field is not None:
                    self._selection[field] += len(
                        values["iterable"]
                    )

            return

        if kind == "detect":
            entry = None

        elif kind == "export":
            entry = {
                "scene": f"scene_{values['scene'].index:04d}",
            }
            self.report["exports"].append(entry)

        elif kind == "extract":
            entry = {
                "scene": Path(values["output_dir"]).name,
                "requested": values["num_frames"],
                "pool_creations": 0,
            }
            self.report["extractions"].append(entry)

            previous = self._scene
            self._scene = entry

        elif kind == "select":
            entry = {
                "scene": (
                    self._scene["scene"]
                    if self._scene else None
                ),
                "candidates": len(values["input_key_frames"]),
                "requested": values["number_of_frames"],
                "filter_rounds": 0,
                "filter_rounds_completed": 0,
                "filter_seconds": 0.0,
                "brightness_map_items": 0,
                "entropy_map_items": 0,
            }
            self.report["selections"].append(entry)

            previous = self._selection
            self._selection = entry

        elif kind == "filter":
            entry = self._selection

            if entry is None:
                return

            entry["filter_rounds"] += 1

        self._active[id(frame)] = (
            perf_counter(),
            entry,
            previous,
        )

    def save(self, output_dir):
        path = Path(output_dir) / "performance.json"
        temporary = path.with_suffix(".json.tmp")

        temporary.write_text(
            json.dumps(
                self.report,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        temporary.replace(path)
        return path