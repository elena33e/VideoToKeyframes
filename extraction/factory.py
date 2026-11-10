"""Construirea pipeline-ului de extragere."""

from .keyframe_extractor import KatnaKeyframeExtractorService
from .pipeline import VideoProcessingPipeline
from .scene_detector import PySceneDetectorService


def create_pipeline(
    *,
    threshold: float,
    max_workers: int,
) -> VideoProcessingPipeline:
    return VideoProcessingPipeline(
        scene_detector=PySceneDetectorService(
            threshold=threshold,
        ),
        keyframe_extractor=KatnaKeyframeExtractorService(
            max_workers=max_workers,
        ),
    )