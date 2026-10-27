from pathlib import Path
from interfaces import ISceneDetector, IKeyframeExtractor
from scene_detector import PySceneDetectorService
from keyframe_extractor import KatnaKeyframeExtractorService


class VideoProcessingPipeline:
    """
    Orchestrator pentru procesarea video
    """

    def __init__(self, scene_detector: ISceneDetector, keyframe_extractor: IKeyframeExtractor):
        self.scene_detector = scene_detector
        self.keyframe_extractor = keyframe_extractor

    def run(self, input_video: Path, base_output_dir: Path, frames_per_scene: int = 3, max_total_keyframes: int = 10):
        input_video = Path(input_video)
        base_output_dir = Path(base_output_dir)

        if not input_video.exists():
            raise FileNotFoundError(f"Fișierul video nu există: {input_video}")

        print(f"=== START PIPELINE (DEBUG MODE): {input_video.name} ===")
        print(f"Limita maximă de cadre-cheie setată: {max_total_keyframes}")

        scenes_dir = base_output_dir / "scenes"
        keyframes_dir = base_output_dir / "keyframes"

        # PASUL 1: Segmentare Macro
        scene_clips = self.scene_detector.detect_and_split(
            video_path=input_video,
            output_dir=scenes_dir
        )

        # PASUL 2: Extragere Micro cu limitare
        total_extracted = 0

        for idx, clip_path in enumerate(scene_clips, start=1):
            if total_extracted >= max_total_keyframes:
                print(f"\n[DEBUG] Limita de {max_total_keyframes} cadre-cheie a fost atinsă. Se oprește procesarea.")
                break

            # Calculăm câte cadre mai avem voie să extragem din scena curentă fără a depăși limita
            remaining_quota = max_total_keyframes - total_extracted
            frames_to_extract = min(frames_per_scene, remaining_quota)

            scene_keyframes_dir = keyframes_dir / f"scene_{idx}"

            extracted_images = self.keyframe_extractor.extract_keyframes(
                video_path=clip_path,
                output_dir=scene_keyframes_dir,
                num_frames=frames_to_extract
            )

            total_extracted += len(extracted_images)

        print(f"\n=== PIPELINE FINALIZAT ===")
        print(f"Total scene analizate: {idx if 'idx' in locals() else 0} din {len(scene_clips)}")
        print(f"Total cadre-cheie generate: {total_extracted}")
        print(f"Cale salvată: {keyframes_dir.resolve()}")


if __name__ == "__main__":
    detector_service = PySceneDetectorService(threshold=27.0)
    extractor_service = KatnaKeyframeExtractorService()

    pipeline = VideoProcessingPipeline(
        scene_detector=detector_service,
        keyframe_extractor=extractor_service
    )

    VIDEO_TEST = Path("test_videos/test_craft.mp4")
    OUTPUT_FOLDER = Path("output/pipeline_output")

    if VIDEO_TEST.exists():
        pipeline.run(
            input_video=VIDEO_TEST,
            base_output_dir=OUTPUT_FOLDER,
            frames_per_scene=3,  # Număr cadre per scenă
            max_total_keyframes=10  # Limita scene pentru test
        )
    else:
        print(f"Fișierul '{VIDEO_TEST}' nu există în rădăcina proiectului.")