# Rebuild 2: contracts and checks

The Windows UI is not an inference engine. These boundaries deliberately keep
inference diagnostics independent of mouse injection.

| Component | Input | Output / responsibility |
|---|---|---|
| `settings` | JSON / UI / CLI | validated, migrated settings |
| `capture.ScreenCapture` | monitor + explicit region/backend | BGR ndarray, **source** timestamp, monitor-relative origin, capture time |
| `inference.TorchBackend` | BGR ndarray | local boxes + stage times via Ultralytics |
| `inference.OnnxBackend` | BGR ndarray | local boxes + direct stage times; raw YOLOv8/11 only |
| `detector.Detector` | capture + inference | one latest generation-tagged result, mapped monitor coordinates, diagnostics |
| `diagnostics` | Detector(preview=True) | read-only preview, JSON report; never injects OS input |
| `tracking` | detections + source time | transient identities, confidence hysteresis, bounded visual lead |
| `aim_control` | new sequence + confirmed raw box | one bounded correction per result, stability confirmation, deadzone; no OS calls |
| `trigger` | confirmed target + explicit gates | nonblocking down/up decisions |
| `app` | settings + latest result | focus-gated input, overlay, live settings |
| `menu` / `launcher` | validated settings | one shared sidebar UI, explicit launch/export/data actions |

## Timestamp rules

- Capture timestamp is taken before acquisition; copying/inference time is not
  disguised as fresh data at publication.
- A reused DXGI frame retains its original timestamp and is not inferred twice.
- After 80 ms without a new DXGI frame, MSS refreshes the actual desktop.
- Enable/disable/menu transitions invalidate both outstanding results and the
  capture cache. No queue of obsolete detections is consumed after reactivation.
- Prediction changes coordinates, never the source timestamp or age limit.
- `total_ms` measures wall-clock processing; source age is reported separately.
- UI rendering/input happen on Tk's thread; neither capture nor inference calls Tk.

## Mapping rules

MSS monitor positions can be negative. Capture origin is relative to that monitor,
not the virtual desktop. ONNX letterbox is undone before adding that origin.
DXGI output ordering is not assumed identical to MSS ordering. Auto therefore
uses MSS for multi-monitor setups. Full ESP and centre-crop ESP are explicit modes.

## Runtime fallback

Optional DXcam failure -> MSS. Only one DXGI owner is permitted per process;
opening a new session before the old capture closes falls back rather than sharing
a DXcam camera object across worker threads. Requested unavailable GPU/provider or
failed GPU warmup -> CPU. Backend names and warnings remain visible. PyTorch and
ONNX share class/self exclusion rules but are not assumed numerically identical.
ONNX format mismatches raise errors instead of silently interpreting another layout.

## Verification boundary

Unit tests exercise a real ONNX Runtime CPU session with a constant-output fixture,
pre/postprocessing, confidence/self filters, RGB conversion, source timestamps,
MSS/DXGI fallback mocks, generation invalidation and ROI offsets. This is not a
benchmark of game weights. No GTA, Windows desktop capture, DirectML, CUDA, Tk GUI
or Windows EXE was available for end-to-end validation in the Linux workspace.

Use the input-free preview on the target PC first. Compare the **same frames,
weights, input size and thresholds** across .pt / .onnx backends. Report actual
provider lists, capture backend, timings, source age and detection quality; do not
claim an acceleration factor from the backend name alone.

No source code, models or loaders from the studied third-party repositories are
bundled into this implementation. The existing user-supplied game weights remain
unchanged and must be evaluated independently.
