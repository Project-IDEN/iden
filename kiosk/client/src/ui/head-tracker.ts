import { FaceLandmarker, FilesetResolver, type NormalizedLandmark } from "@mediapipe/tasks-vision";

/**
 * Head pose in the browser, so a face capture can wait for a movement instead
 * of guessing when it happens. The engine still judges every frame it is sent;
 * this only decides when to take them.
 *
 * Yaw and pitch are the engine's own proxies (`engine/src/engine/pose.py`),
 * from the same five points — eyes, nose tip, mouth corners — taken from
 * MediaPipe's face mesh, so "turned far enough" means the same on both sides.
 */

export interface Pose {
  /** Nose offset from the eyes' midpoint over the eye distance; + is the person's left. */
  yaw: number;
  /** Where the nose sits between the eye line (0) and the mouth line (1). */
  pitch: number;
}

export interface HeadTracker {
  /** The pose in the latest camera frame, or null while no face is in view. */
  latest: () => Pose | null;
  stop: () => void;
}

// Face-mesh indices in the unmirrored picture, where the person's right eye is
// on the left of the image.
const IMAGE_LEFT_EYE = [33, 133];
const IMAGE_RIGHT_EYE = [362, 263];
const NOSE_TIP = 1;
const MOUTH_CORNERS = [61, 291];

type Point = [number, number];

function mean(points: Point[]): Point {
  const [x, y] = points.reduce(([sx, sy], [px, py]) => [sx + px, sy + py], [0, 0]);
  return [x / points.length, y / points.length];
}

function poseOf(mesh: NormalizedLandmark[], width: number, height: number): Pose | null {
  const at = (indices: number[]): Point | null => {
    const points = indices.flatMap((i) => {
      const p = mesh[i];
      return p ? [[p.x * width, p.y * height] as Point] : [];
    });
    return points.length === indices.length ? mean(points) : null;
  };
  const leftEye = at(IMAGE_LEFT_EYE);
  const rightEye = at(IMAGE_RIGHT_EYE);
  const nose = at([NOSE_TIP]);
  const mouth = at(MOUTH_CORNERS);
  if (!leftEye || !rightEye || !nose || !mouth) return null;

  // Undo the head's tilt first, so a tilted head does not read as turned.
  const eyes = mean([leftEye, rightEye]);
  const roll = Math.atan2(rightEye[1] - leftEye[1], rightEye[0] - leftEye[0]);
  const level = ([x, y]: Point): Point => [
    (x - eyes[0]) * Math.cos(roll) + (y - eyes[1]) * Math.sin(roll),
    -(x - eyes[0]) * Math.sin(roll) + (y - eyes[1]) * Math.cos(roll),
  ];
  const [noseX, noseY] = level(nose);
  const [, mouthY] = level(mouth);
  const eyeDistance = Math.hypot(rightEye[0] - leftEye[0], rightEye[1] - leftEye[1]);
  return {
    yaw: eyeDistance ? noseX / eyeDistance : 0,
    pitch: noseY / Math.max(mouthY, 1e-6),
  };
}

const loading = new Map<string, Promise<FaceLandmarker>>();

/** The runtime and model are ~15 MB, so they load once per page. The GPU when
 * the browser offers WebGL2, the CPU otherwise. */
function load(files: string): Promise<FaceLandmarker> {
  let model = loading.get(files);
  if (!model) {
    model = FilesetResolver.forVisionTasks(files).then((fileset) => {
      const create = (delegate: "GPU" | "CPU") =>
        FaceLandmarker.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: `${files}/face_landmarker.task`, delegate },
          runningMode: "VIDEO",
          numFaces: 1,
        });
      return create("GPU").catch(() => create("CPU"));
    });
    model.catch(() => loading.delete(files));
    loading.set(files, model);
  }
  return model;
}

/**
 * Follows the face in `video` on every new frame until stopped. `files` is
 * where the app serves the tracker's runtime and model.
 */
export async function trackHead(video: HTMLVideoElement, files: string): Promise<HeadTracker> {
  const model = await load(files);
  let latest: Pose | null = null;
  let running = true;
  let shown = -1;

  const step = () => {
    if (!running) return;
    if (video.readyState >= 2 && video.currentTime !== shown) {
      shown = video.currentTime;
      const mesh = model.detectForVideo(video, performance.now()).faceLandmarks[0];
      latest = mesh ? poseOf(mesh, video.videoWidth, video.videoHeight) : null;
    }
    requestAnimationFrame(step);
  };
  requestAnimationFrame(step);

  return {
    latest: () => latest,
    stop: () => {
      running = false;
    },
  };
}
