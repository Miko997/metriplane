# Metriplane Coordinate Frames

**Purpose**: Define coordinate frame conventions for Metriplane v1.0  
**Last Updated**: 2026-04-27  
**Status**: ✅ Complete - Planar mapping (Z=0 assumption)

---

## Overview

Metriplane uses three primary coordinate frames to transform video pixels into metric world coordinates:

1. **Camera Frame** (pixel coordinates)
2. **World Frame** (metric XY plane)
3. **Object Frame** (marker-local, not used for v1.0 planar mapping)

---

## 1. Camera Frame (Pixel Coordinates)

**Definition**: Raw pixel coordinates from camera image  
**Origin**: Top-left corner of image  
**Units**: pixels  
**Axes**:
- **u**: horizontal (left→right, 0 to image_width)
- **v**: vertical (top→bottom, 0 to image_height)

**Range**: `[0, image_width) × [0, image_height)`

**Example**:
- Image resolution: 640×480
- Pixel at center: `(u=320, v=240)`
- ArUco marker detected at: `(u=245, v=180)`

**Used For**:
- Raw camera capture
- ArUco detection (outputs pixel corners)
- Intrinsic calibration (distortion correction)

---

## 2. World Frame (Metric Coordinates)

**Definition**: Metric coordinate system on physical workspace plane  
**Origin**: User-defined anchor point on workspace (typically corner or center of board/table)  
**Units**: meters (m)  
**Axes**:
- **X**: horizontal (board width direction, typically left→right when facing board)
- **Y**: horizontal (board depth direction, typically top→bottom when facing board)
- **Z**: vertical (**fixed at Z=0 for v1.0 planar mapping**)

**Planar Assumption**: All tracked objects lie on Z=0 plane (tabletop, floor, or board surface)

**Range**: Defined by workspace size (e.g., `[0, 1.1m] × [0, 0.4m]` for 110cm × 40cm board)

**Example**:
- Board dimensions: 1.1m × 0.4m
- Object at world coordinates: `(X=0.275m, Y=0.200m, Z=0.0m)`
- Origin (0,0,0): Bottom-left corner of board (user convention)

**Used For**:
- Object state output (`pos_world` field in `ObjectStateModel`)
- Zone definitions (polygons in world XY)
- Multi-camera fusion (common reference frame)
- Analytics (distances, velocities)

---

## 3. Object Frame (Marker-Local)

**Definition**: Local coordinate frame attached to each ArUco marker  
**Not Used in v1.0**: Metriplane v1.0 only tracks marker center position, not full 6-DOF pose

**Future Work**:
- Full marker orientation (roll, pitch, yaw)
- 3D reconstruction (non-planar objects)
- 6-DOF pose tracking

---

## Coordinate Transformations

### Pixel → World (Planar Homography)

**Method**: Homography matrix `H` (3×3) maps pixel `(u, v)` to world `(X, Y)`

**Process**:
1. **Calibration**: Place markers at known world coordinates, record pixel positions
2. **Compute** `H`: Solve homogeneous system using OpenCV `findHomography()`
3. **Apply**: For each detected marker center `(u, v)`, compute `(X, Y) = H @ [u, v, 1]`

**Files**:
- Calibration script: `tools/calibrate_planar_homography.py`
- Stored mapping: `calib/profiles/{profile}/cam*/mapping.yaml`
- Applied at runtime: `metriplane/mapping/planar.py`

**Validation**:
- Test grid protocol: ≥9 known points
- Mapping error benchmark: `benchmarks/run_mapping_error.py`
- Typical accuracy: mean < 1cm, max < 2cm (for well-calibrated setup)

### Multi-Camera Fusion

**Problem**: Multiple cameras observe same object, each producing independent world coordinates

**Solution**: Fusion algorithms merge observations into single `pos_world_fused`

**Strategies** (implemented in `metriplane/fusion/`):
1. **Nearest-neighbor**: Select closest observation to previous fused position
2. **Weighted average**: Merge observations weighted by confidence
3. **Kalman filter**: Bayesian fusion with motion model (constant velocity)

**Output**: Single fused position per object, marked with `fused=True` in schema

---

## Schema Integration

World coordinates appear in `FrameStateModel` schema:

```python
class ObjectStateModel(BaseModel):
    id: str
    pos_world: tuple[float, float, float] | None  # (X, Y, Z) in meters
    vel_world: tuple[float, float, float] | None  # (vX, vY, vZ) m/s (Kalman only)
    zone: str | None  # Zone ID if inside polygon
    confidence: float | None
```

**Multi-Camera Schema**:
```python
class FrameStateModel(BaseModel):
    # ...
    objects: list[ObjectStateModel]  # Legacy: first camera or fused
    fused: list[ObjectStateModel] | None  # Fused across cameras
    raw_per_camera: list[CameraFrameModel] | None  # Per-camera observations
```

---

## Frame

 Visualization

```
Camera Frame (pixels)          World Frame (meters, Z=0 plane)
┌─────────────────┐            
│ (0,0)           │            Y ↑ (depth, 0.4m max)
│   ·             │            │
│     · marker    │            │     · object
│ ↓              →│            │       (0.275, 0.200)
│ v            u  │            │
│                 │            └───────→ X (width, 1.1m max)
│        (640,480)│              origin (0,0)
└─────────────────┘

      Homography H
      pixel → world
```

---

## Limitations (v1.0)

✅ **Supported**:
- Planar tracking (XY position on Z=0 plane)
- Multi-camera fusion on shared plane
- Zone analytics (2D polygons)

❌ **Not Supported (Future Work)**:
- Full 3D reconstruction (arbitrary Z)
- 6-DOF pose (marker orientation)
- Non-planar surfaces (curved, inclined)
- Stereo depth estimation

---

## Calibration Workflow

### 1. Camera Intrinsics (Optional)
**When Needed**: Wide-angle lenses, fisheye distortion  
**Tool**: `tools/calibrate_intrinsics_chessboard.py`  
**Output**: `calib/profiles/{profile}/cam*/camera.yaml`

### 2. Planar Homography (Required)
**Tool**: `tools/calibrate_planar_homography.py`  
**Input**: Markers at known world positions (≥4 points, recommend 9)  
**Output**: `calib/profiles/{profile}/cam*/mapping.yaml`

### 3. Validation
**Tool**: `benchmarks/run_mapping_error.py`  
**Method**: Test grid protocol (9+ points)  
**Target**: mean error < 1cm, max error < 2cm

**See Also**: `docs/calibration_runbook.md`

---

## References

- Implementation: `metriplane/mapping/planar.py`, `metriplane/fusion/fuse_xy.py`
- Schema: `metriplane/schema.py`, `docs/schema.md`
- Calibration: `tools/calibrate_planar_homography.py`, `docs/calibration_runbook.md`
- Benchmarks: `benchmarks/run_mapping_error.py`, `tools/debug_alignment.py`
- Evidence: `evidence/experiments/mapping_error_001.csv`, `evidence/manifest.csv` row 8 (alignment)
