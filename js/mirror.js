// Signal Nine — WS-B1d: downtown wet-road planar mirror. Hand-rolled:
// THREE.Reflector is NOT in the bundle, and the downtown road is a flat
// horizontal plane, so the mirrored camera is a simple Y-across-plane flip —
// no oblique clipping needed (that simplification is only valid for flat
// mirrors, which is exactly the case here). Renders the scene from the
// mirrored camera to a half-res RT each frame; the road material samples it
// in screen space through a texture matrix (injected via onBeforeCompile in
// main.js). Downtown + ?lit=1 only — measured cost rides the landing.
window.S9 = window.S9 || {};
(function () {
  class MirrorPass {
    // roadMesh: the road surface mesh (world-flat, normal +Y)
    // planeY: the mirror plane height (road surface y)
    constructor(renderer, scene, camera, roadMesh, planeY) {
      this.renderer = renderer;
      this.scene = scene;
      this.camera = camera;
      this.roadMesh = roadMesh;
      this.planeY = planeY;
      this.enabled = true;
      const w = (renderer.getSize(new THREE.Vector2()).x * renderer.getPixelRatio()) >> 1 || 480;
      const h = (renderer.getSize(new THREE.Vector2()).y * renderer.getPixelRatio()) >> 1 || 270;
      this.rt = new THREE.WebGLRenderTarget(w, h, { type: THREE.HalfFloatType });
      this.virtualCam = new THREE.PerspectiveCamera();
      this.virtualCam.matrixAutoUpdate = false;
      this.textureMatrix = new THREE.Matrix4();
      this._mirrorMat = new THREE.Matrix4()
        .makeTranslation(0, planeY, 0)
        .multiply(new THREE.Matrix4().makeScale(1, -1, 1))
        .multiply(new THREE.Matrix4().makeTranslation(0, -planeY, 0));
    }

    resize(w, h) {
      this.rt.setSize((w * this.renderer.getPixelRatio()) >> 1, (h * this.renderer.getPixelRatio()) >> 1);
    }

    render() {
      if (!this.enabled) return;
      const cam = this.camera;
      const vc = this.virtualCam;

      // virtual camera = mirror reflection of the real camera across y = planeY
      vc.matrixWorld.copy(this._mirrorMat).multiply(cam.matrixWorld);
      vc.matrixWorldInverse.copy(vc.matrixWorld).invert();
      vc.projectionMatrix.copy(cam.projectionMatrix);
      vc.projectionMatrixInverse.copy(cam.projectionMatrixInverse);

      // screen-space texture matrix: bias * proj * view (three.Reflector scheme)
      this.textureMatrix.set(
        0.5, 0.0, 0.0, 0.5,
        0.0, 0.5, 0.0, 0.5,
        0.0, 0.0, 0.5, 0.5,
        0.0, 0.0, 0.0, 1.0);
      this.textureMatrix.multiply(vc.projectionMatrix);
      this.textureMatrix.multiply(vc.matrixWorldInverse);
      this.textureMatrix.multiply(this.roadMesh.matrixWorld);

      // hide the road itself so the reflection never sees the mirror surface
      const road = this.roadMesh;
      road.visible = false;
      const prevTarget = this.renderer.getRenderTarget();
      this.renderer.setRenderTarget(this.rt);
      this.renderer.render(this.scene, vc);
      this.renderer.setRenderTarget(prevTarget);
      road.visible = true;
    }
  }

  S9.MirrorPass = MirrorPass;
})();