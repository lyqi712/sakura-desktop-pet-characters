(function () {
  var scene = null;
  var camera = null;
  var renderer = null;
  var controls = null;
  var model = null;
  var helper = null;
  var clock = null;
  var outlineEffect = null;
  var currentConfig = window.__SAKURA_MMD_INITIAL_CONFIG || {};
  var loadRequestId = 0;
  var targetLip = 0;
  var smoothLip = 0;
  var mouthFrame = 0;
  var lastMouthAt = Date.now();
  var lastBlinkAt = Date.now();
  var blinkUntil = 0;
  var blinkInterval = 2600 + Math.random() * 1800;
  var blinkCloseMs = 90;
  var blinkOpenMs = 130;
  var startedAt = Date.now();
  var targetLookX = 0;
  var targetLookY = 0;
  var smoothLookX = 0;
  var smoothLookY = 0;
  var assetsReady = false;
  var modelReadyForReveal = false;
  var speakingActive = false;
  var thinkingActive = false;
  var doubleBlink = false;
  var pointerInteractionInstalled = false;
  var pointerLookAtThrottleMs = 33;
  var lastPointerLookAtAt = 0;
  var pendingPointerLookAt = null;
  var pointerLookAtTimer = 0;
  var activeExpressions = [];
  var controlledExpressionIndices = {};
  var morphCache = {
    blinkKey: "",
    blinkIndex: -1,
    mouthKey: "",
    mouthIndices: []
  };
  var livenessState = {
    seed: Math.random() * 1000,
    poseX: 0,
    poseY: 0,
    poseZ: 0,
    targetX: 0,
    targetY: 0,
    targetZ: 0,
    nextPoseAt: Date.now() + 1800 + Math.random() * 2400,
    interactionUntil: 0,
    interactionPulse: 0,
    interactionKind: ""
  };
  var status = {
    done: false,
    loading: false,
    error: "",
    engine: "three",
    model: "",
    modelUrl: "",
    materialPreset: "",
    materialsTuned: 0,
    textureMaps: 0,
    envMaps: 0,
    morphDictionary: {},
    resolvedMorphs: {}
  };

  function clamp(v, min, max) {
    v = Number(v);
    if (!Number.isFinite(v)) return min;
    return Math.max(min, Math.min(max, v));
  }

  function easeOut(v) {
    v = clamp(v, 0, 1);
    return 1 - Math.pow(1 - v, 3);
  }

  function hash1(n) {
    var s = Math.sin(n) * 43758.5453123;
    return s - Math.floor(s);
  }

  function vnoise(x) {
    var i = Math.floor(x);
    var f = x - i;
    var u = f * f * (3 - 2 * f);
    return (hash1(i) * (1 - u) + hash1(i + 1) * u) * 2 - 1;
  }

  function fbm(x) {
    return vnoise(x) * 0.6 + vnoise(x * 2.13 + 11.7) * 0.28 + vnoise(x * 4.07 + 23.1) * 0.12;
  }

  function livenessOption(name, fallback, min, max) {
    var source = currentConfig.liveness || {};
    var value = Number(source[name]);
    if (!Number.isFinite(value)) value = fallback;
    return clamp(value, min, max);
  }

  function effectivePixelRatio() {
    var deviceRatio = Number(window.devicePixelRatio) || 1;
    var maxRatio = Number(currentConfig.pixel_ratio_max);
    if (!Number.isFinite(maxRatio) || maxRatio <= 0) maxRatio = 1.25;
    return clamp(deviceRatio, 1, maxRatio);
  }

  function mmdHelperOptions() {
    var warmupFrames = Math.floor(Number(currentConfig.physics_warmup_frames) || 8);
    var maxStepNum = Math.floor(Number(currentConfig.physics_max_step_num) || 1);
    return {
      physics: currentConfig.physics_enabled !== false,
      warmup: Math.max(0, warmupFrames),
      maxStepNum: Math.max(1, maxStepNum)
    };
  }

  function toFileUrl(path) {
    if (!path) return "";
    if (/^(file|https?):\/\//i.test(path)) return path;
    return "file:///" + String(path).replace(/\\/g, "/").replace(/^\/+/, "");
  }

  function loadCharacter(config) {
    currentConfig = Object.assign({}, currentConfig || {}, config || {});
    status.loading = true;
    status.done = false;
    status.error = "";
    status.model = currentConfig.model || "";
    status.modelUrl = currentConfig.model_url || "";
    status.materialPreset = currentConfig.material_preset || "game_toon";
    initScene();
    loadModel();
  }

  function initScene() {
    if (renderer) return;
    scene = new THREE.Scene();
    clock = new THREE.Clock();
    var cameraOptions = currentConfig.camera || {};
    camera = new THREE.PerspectiveCamera(Number(cameraOptions.fov) || 45, window.innerWidth / Math.max(1, window.innerHeight), 1, 2000);
    var position = cameraOptions.position || [0, 11, 34];
    camera.position.set(Number(position[0]) || 0, Number(position[1]) || 11, Number(position[2]) || 34);
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, premultipliedAlpha: false, preserveDrawingBuffer: false });
    renderer.setClearColor(0x000000, 0);
    renderer.setPixelRatio(effectivePixelRatio());
    renderer.setSize(window.innerWidth, window.innerHeight);
    // PMX diffuse/sphere textures are authored for sRGB display.
    renderer.toneMapping = THREE.NoToneMapping;
    renderer.toneMappingExposure = 1.0;
    if (THREE.sRGBEncoding !== undefined) {
      renderer.outputEncoding = THREE.sRGBEncoding;
    }
    document.body.appendChild(renderer.domElement);
    installPointerInteraction();
    controls = new THREE.OrbitControls(camera, renderer.domElement);
    var target = cameraOptions.target || [0, 10, 0];
    controls.target.set(Number(target[0]) || 0, Number(target[1]) || 10, Number(target[2]) || 0);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.enablePan = false;
    controls.enableZoom = false;
    controls.enableRotate = false;
    scene.add(new THREE.AmbientLight(0xffffff, 0.38));
    var keyLight = new THREE.DirectionalLight(0xffffff, 0.60);
    keyLight.position.set(0.6, 2.0, 2.5).normalize();
    scene.add(keyLight);
    var fillLight = new THREE.DirectionalLight(0xd8e8ff, 0.15);
    fillLight.position.set(-1.5, 0.8, 1.5).normalize();
    scene.add(fillLight);
    var rimLight = new THREE.DirectionalLight(0xfff0e0, 0.07);
    rimLight.position.set(-0.3, 1.2, -2.5).normalize();
    scene.add(rimLight);
    // OutlineEffect 是 MMDLoader 官方依赖，二次元描边必须
    if (typeof THREE !== "undefined" && THREE.OutlineEffect) {
      outlineEffect = new THREE.OutlineEffect(renderer, {
        defaultThickness: 0.003,
        defaultColor: [0, 0, 0],
        defaultAlpha: 0.8,
        defaultKeepAlive: true
      });
    }
    requestAnimationFrame(animate);
  }

  function loadModel() {
    var requestId = ++loadRequestId;
    var modelUrl = currentConfig.model_url || toFileUrl(currentConfig.model);
    if (!modelUrl) {
      status.error = "Missing PMX model path";
      status.loading = false;
      return;
    }
    status.modelUrl = modelUrl;
    clearCurrentModel();
    assetsReady = false;
    modelReadyForReveal = false;
    morphCache = { blinkKey: "", blinkIndex: -1, mouthKey: "", mouthIndices: [] };
    status.resolvedMorphs = {};
    // 隐藏 body，等 PMX、贴图和首帧渲染都完成后再淡入，避免用户看到"一块一块显现"的过程。
    document.body.style.opacity = "0";
    document.body.style.transition = "opacity 0.18s ease";

    var loadingManager = new THREE.LoadingManager();
    loadingManager.onLoad = function () {
      if (requestId !== loadRequestId) return;
      if (model) tuneMmdMaterials(model);
      assetsReady = true;
      revealModelWhenReady();
    };
    loadingManager.onError = function (url) {
      if (requestId !== loadRequestId) return;
      status.lastAssetError = String(url || "");
    };

    var loader = new THREE.MMDLoader(loadingManager);
    loader.load(
      modelUrl,
      function (mmd) {
        if (requestId !== loadRequestId) {
          disposeObject3D(mmd);
          return;
        }
        model = mmd;
        model.visible = false;
        var position = currentConfig.model_position || [0, -8, 0];
        model.position.set(Number(position[0]) || 0, Number(position[1]) || -8, Number(position[2]) || 0);
        var scale = Number(currentConfig.model_scale) || 1;
        model.scale.set(scale, scale, scale);
        tuneMmdMaterials(model);
        scene.add(model);
        frameModel();
        helper = new THREE.MMDAnimationHelper();
        helper.add(model, mmdHelperOptions());
        applyRestPose(0);
        status.done = true;
        status.loading = false;
        status.morphDictionary = model.morphTargetDictionary || {};
        modelReadyForReveal = true;
        revealModelWhenReady();
      },
      undefined,
      function (error) {
        if (requestId !== loadRequestId) return;
        status.error = String(error && (error.message || error) || "MMD load failed");
        status.loading = false;
        document.body.style.opacity = "1";
      }
    );
  }

  function revealModelWhenReady() {
    if (!model || !assetsReady || !modelReadyForReveal) return;
    tuneMmdMaterials(model);
    frameModel();
    applyRestPose((Date.now() - startedAt) / 1000);
    applyLookAt();
    applyLivenessMotion((Date.now() - startedAt) / 1000, 0.016);
    applyLipSync();
    applyBlink();
    model.visible = true;
    renderFrame();
    requestAnimationFrame(function () {
      if (!model || !model.visible) return;
      renderFrame();
      document.body.style.opacity = "1";
    });
  }

  function renderFrame() {
    if (!renderer || !scene || !camera) return;
    if (controls) controls.update();
    if (outlineEffect) {
      outlineEffect.render(scene, camera);
    } else {
      renderer.render(scene, camera);
    }
  }

  function installPointerInteraction() {
    if (!renderer || !renderer.domElement || pointerInteractionInstalled) return;
    pointerInteractionInstalled = true;
    var element = renderer.domElement;
    element.addEventListener("pointermove", function (event) {
      var rect = element.getBoundingClientRect();
      if (!rect || rect.width <= 0 || rect.height <= 0) return;
      var x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      var y = ((event.clientY - rect.top) / rect.height) * 2 - 1;
      requestPointerLookAt(x, y);
    });
    element.addEventListener("pointerdown", function () {
      triggerInteraction("touch");
    });
  }

  function requestPointerLookAt(x, y) {
    pendingPointerLookAt = {
      x: clamp(x, -1, 1),
      y: clamp(y, -1, 1)
    };
    var now = Date.now();
    var waitMs = pointerLookAtThrottleMs - (now - lastPointerLookAtAt);
    if (waitMs <= 0) {
      flushPointerLookAt();
      return;
    }
    if (!pointerLookAtTimer) {
      pointerLookAtTimer = setTimeout(flushPointerLookAt, waitMs);
    }
  }

  function flushPointerLookAt() {
    if (!pendingPointerLookAt) {
      pointerLookAtTimer = 0;
      return;
    }
    var nextLookAt = pendingPointerLookAt;
    pendingPointerLookAt = null;
    pointerLookAtTimer = 0;
    lastPointerLookAtAt = Date.now();
    lookAt(nextLookAt.x, nextLookAt.y);
  }

  function clearCurrentModel() {
    if (!model) {
      helper = null;
      return;
    }
    if (helper && typeof helper.remove === "function") {
      try {
        helper.remove(model);
      } catch (error) {
        // Helper state can lag during async loads; removing from scene is the source of truth.
      }
    }
    if (scene) scene.remove(model);
    disposeObject3D(model);
    model = null;
    helper = null;
  }

  function disposeObject3D(object) {
    if (!object || typeof object.traverse !== "function") return;
    object.traverse(function (child) {
      if (child.geometry && typeof child.geometry.dispose === "function") {
        child.geometry.dispose();
      }
      var materials = Array.isArray(child.material) ? child.material : [child.material];
      for (var i = 0; i < materials.length; i++) {
        var material = materials[i];
        if (material && typeof material.dispose === "function") {
          material.dispose();
        }
      }
    });
  }

  function tuneMmdMaterials(mesh) {
    if (!mesh) return;
    var preset = currentConfig.material_preset || "game_toon";
    status.materialPreset = preset;
    if (preset === "raw_mmd") return;

    var tuned = 0;
    var textureMaps = 0;
    var envMaps = 0;
    var materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (var i = 0; i < materials.length; i++) {
      var material = materials[i];
      if (!material) continue;
      var bucket = classifyMaterial(material);
      rememberMaterialBase(material);

      if (material.map) {
        tuneColorTexture(material.map);
        textureMaps += 1;
      }
      if (material.envMap) {
        tuneColorTexture(material.envMap);
        envMaps += 1;
      }
      if (material.gradientMap) {
        material.gradientMap.magFilter = THREE.NearestFilter;
        material.gradientMap.minFilter = THREE.NearestFilter;
        material.gradientMap.needsUpdate = true;
      }

      material.toneMapped = false;
      material.depthWrite = !material.transparent;
      if (material.transparent) {
        material.alphaTest = Math.max(Number(material.alphaTest) || 0, 0.015);
      }
      tuneMaterialBucket(material, bucket);
      tuned += 1;
    }
    status.materialsTuned = tuned;
    status.textureMaps = textureMaps;
    status.envMaps = envMaps;
  }

  function rememberMaterialBase(material) {
    material.userData = material.userData || {};
    if (material.userData.sakuraBaseMaterial) return;
    var outline = material.userData.outlineParameters || {};
    material.userData.sakuraBaseMaterial = {
      color: material.color && material.color.clone ? material.color.clone() : null,
      emissive: material.emissive && material.emissive.clone ? material.emissive.clone() : null,
      reflectivity: Number(material.reflectivity),
      outlineThickness: Number(outline.thickness),
      outlineAlpha: Number(outline.alpha)
    };
  }

  function tuneMaterialBucket(material, bucket) {
    var base = material.userData.sakuraBaseMaterial || {};
    var settings = {
      env: 0.32,
      emissive: 1.0,
      color: 1.0,
      opacity: null,
      textureSoftness: 0,
      alphaTest: 0.015,
      outline: 1.0,
      outlineAlpha: 0.72,
      outlineVisible: true,
      alphaMode: "opaque",
      premultiplyAlpha: false
    };
    if (bucket === "skin") {
      settings.env = 0.12;
      settings.emissive = 1.08;
      settings.outline = 0.75;
      settings.outlineAlpha = 0.48;
    } else if (bucket === "eye") {
      settings.env = 0.65;
      settings.emissive = 1.22;
      settings.color = 1.02;
      settings.outline = 0.65;
      settings.outlineAlpha = 0.45;
    } else if (bucket === "hair") {
      settings.env = 0.28;
      settings.emissive = 0.96;
      settings.outline = 0.9;
      settings.outlineAlpha = 0.62;
    } else if (bucket === "cloth") {
      settings.env = 0.26;
      settings.emissive = 1.0;
      settings.color = 1.0;
      settings.alphaTest = 0.02;
      settings.outline = 0.98;
      settings.outlineAlpha = 0.66;
    } else if (bucket === "fur") {
      settings.env = 0.02;
      settings.emissive = 0.9;
      settings.color = 0.96;
      settings.alphaTest = 0.14;
      settings.outline = 0.76;
      settings.outlineAlpha = 0.5;
    } else if (bucket === "plush") {
      settings.env = 0.04;
      settings.emissive = 1.0;
      settings.color = 1.0;
      settings.alphaTest = 0.02;
      settings.outline = 0.9;
      settings.outlineAlpha = 0.58;
    }
    applyMaterialOverride(material, bucket, settings);

    if (material.envMap) {
      material.reflectivity = settings.env;
    }
    if (base.emissive && material.emissive && material.emissive.copy) {
      material.emissive.copy(base.emissive).multiplyScalar(settings.emissive);
    }
    if (base.color && material.color && material.color.copy) {
      material.color.copy(base.color).multiplyScalar(settings.color);
    }
    if (Number.isFinite(settings.opacity)) {
      material.opacity = settings.opacity;
      if (settings.opacity < 0.999) material.transparent = true;
    }
    if (Number.isFinite(settings.alphaTest)) {
      material.alphaTest = Math.max(Number(material.alphaTest) || 0, settings.alphaTest);
      if (settings.alphaMode === "cutout") {
        material.transparent = false;
        material.depthWrite = true;
        material.alphaToCoverage = true;
        material.blending = THREE.NormalBlending;
      } else if (settings.alphaMode === "blend") {
        material.transparent = true;
        material.depthWrite = settings.alphaTest >= 0.045;
        material.alphaToCoverage = false;
        material.blending = THREE.NormalBlending;
      } else if (settings.alphaTest >= 0.045) {
        material.depthWrite = true;
      }
    }
    applyMaterialTextureSettings(material, settings);
    softenMaterialTexture(material.map, settings);

    var outline = material.userData.outlineParameters;
    if (outline && outline.visible !== false) {
      if (settings.outlineVisible === false) {
        outline.visible = false;
      } else {
      var baseThickness = Number.isFinite(base.outlineThickness) ? base.outlineThickness : Number(outline.thickness) || 0.003;
      var baseAlpha = Number.isFinite(base.outlineAlpha) ? base.outlineAlpha : Number(outline.alpha) || 1;
      outline.thickness = clamp(baseThickness * settings.outline, 0.0012, 0.0045);
      outline.alpha = clamp(Math.min(baseAlpha, settings.outlineAlpha), 0.35, 0.85);
      }
    }
    material.needsUpdate = true;
  }

  function applyMaterialOverride(material, bucket, settings) {
    var overrides = currentConfig.material_overrides || {};
    applyMaterialSettingsOverride(overrides[bucket], settings);
    var nameOverride = findMaterialNameOverride(material);
    applyMaterialSettingsOverride(nameOverride, settings);
    if (material && material.userData) material.userData.sakuraMaterialBucket = bucket;
  }

  function applyMaterialSettingsOverride(override, settings) {
    if (!override) return;
    if (Number.isFinite(Number(override.env))) settings.env = clamp(Number(override.env), 0, 1);
    if (Number.isFinite(Number(override.emissive))) settings.emissive = clamp(Number(override.emissive), 0.2, 1.4);
    if (Number.isFinite(Number(override.color))) settings.color = clamp(Number(override.color), 0.35, 1.2);
    if (Number.isFinite(Number(override.opacity))) settings.opacity = clamp(Number(override.opacity), 0.15, 1);
    if (Number.isFinite(Number(override.textureSoftness))) settings.textureSoftness = clamp(Number(override.textureSoftness), 0, 0.8);
    if (Number.isFinite(Number(override.alphaTest))) settings.alphaTest = clamp(Number(override.alphaTest), 0, 0.35);
    if (Number.isFinite(Number(override.outline))) settings.outline = clamp(Number(override.outline), 0.4, 1.3);
    if (Number.isFinite(Number(override.outlineAlpha))) settings.outlineAlpha = clamp(Number(override.outlineAlpha), 0.25, 0.9);
    if (typeof override.outlineVisible === "boolean") settings.outlineVisible = override.outlineVisible;
    if (typeof override.alphaMode === "string") {
      var mode = override.alphaMode.toLowerCase();
      if (mode === "opaque" || mode === "blend" || mode === "cutout") settings.alphaMode = mode;
    }
    if (typeof override.premultiplyAlpha === "boolean") {
      settings.premultiplyAlpha = override.premultiplyAlpha;
    }
  }

  function findMaterialNameOverride(material) {
    var overrides = currentConfig.material_name_overrides || {};
    if (!material || !overrides) return null;
    var names = [String(material.name || "")];
    var textureName = textureFileName(material.map);
    if (textureName) names.push(textureName);
    for (var i = 0; i < names.length; i++) {
      var name = names[i];
      if (!name) continue;
      if (Object.prototype.hasOwnProperty.call(overrides, name)) return overrides[name];
      var lower = name.toLowerCase();
      if (Object.prototype.hasOwnProperty.call(overrides, lower)) return overrides[lower];
    }
    return null;
  }

  function textureFileName(texture) {
    var src = textureSource(texture);
    if (!src) return "";
    var parts = src.replace(/\\/g, "/").split("/");
    return (parts[parts.length - 1] || "").toLowerCase();
  }

  function applyMaterialTextureSettings(material, settings) {
    if (!material || !material.map) return;
    applyTextureMaterialSettings(material.map, settings);
  }

  function applyTextureMaterialSettings(texture, settings) {
    if (!texture || !settings) return;
    if (settings.premultiplyAlpha === true) {
      texture.premultiplyAlpha = true;
      texture.needsUpdate = true;
    }
  }

  function softenMaterialTexture(texture, settings) {
    if (!texture || !texture.image || !settings || !(settings.textureSoftness > 0)) return;
    if (texture.userData && texture.userData.sakuraSoftenedTexture) return;
    var source = texture.image;
    var width = Number(source.naturalWidth || source.width) || 0;
    var height = Number(source.naturalHeight || source.height) || 0;
    if (!width || !height || typeof document === "undefined") return;
    try {
      var canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      var ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.drawImage(source, 0, 0, width, height);
      var imageData = ctx.getImageData(0, 0, width, height);
      var data = imageData.data;
      var softness = settings.textureSoftness;
      for (var i = 0; i < data.length; i += 4) {
        var alpha = data[i + 3] / 255;
        if (alpha <= 0.001) continue;
        var fade = softness * (0.35 + 0.65 * (1 - alpha));
        data[i] = data[i] + (255 - data[i]) * fade;
        data[i + 1] = data[i + 1] + (255 - data[i + 1]) * fade;
        data[i + 2] = data[i + 2] + (255 - data[i + 2]) * fade;
      }
      ctx.putImageData(imageData, 0, 0);
      texture.image = canvas;
      texture.userData = texture.userData || {};
      texture.userData.sakuraSoftenedTexture = true;
      texture.needsUpdate = true;
    } catch (error) {
      status.textureSofteningError = String(error && (error.message || error) || "texture softening failed");
    }
  }

  function tuneColorTexture(texture) {
    if (!texture) return;
    if (THREE.sRGBEncoding !== undefined) {
      texture.encoding = THREE.sRGBEncoding;
    }
    if (renderer && renderer.capabilities && renderer.capabilities.getMaxAnisotropy) {
      texture.anisotropy = Math.min(16, renderer.capabilities.getMaxAnisotropy());
    }
    texture.needsUpdate = true;
  }

  function classifyMaterial(material) {
    var hint = [
      material.name || "",
      textureSource(material.map),
      textureSource(material.envMap)
    ].join(" ").toLowerCase();
    if (/fur|fur_d|fur_d2|毛|袖/.test(hint)) return "fur";
    if (/plush|doll|toy|bear|bodymc|mc12|mc123|布偶|娃娃|熊/.test(hint)) return "plush";
    if (/cloth|up|down|dress|fabric|裙|衣|布/.test(hint)) return "cloth";
    if (/eye|瞳|目/.test(hint)) return "eye";
    if (/face|skin|肌|顔|脸|cheek/.test(hint)) return "skin";
    if (/hair|髪|发|bangs/.test(hint)) return "hair";
    if (/cloth|up|down|fur|袖|裙|衣/.test(hint)) return "cloth";
    return "default";
  }

  function textureSource(texture) {
    if (!texture || !texture.image) return "";
    return String(texture.image.currentSrc || texture.image.src || "");
  }

  function frameModel() {
    if (!model || !camera || !controls) return;
    var cameraOptions = currentConfig.camera || {};
    if (cameraOptions.auto_frame === false || cameraOptions.frame === "manual") return;
    model.updateMatrixWorld(true);
    var box = new THREE.Box3().setFromObject(model);
    var size = box.getSize(new THREE.Vector3());
    if (!Number.isFinite(size.x + size.y + size.z) || size.y <= 0) return;
    var center = box.getCenter(new THREE.Vector3());
    var frame = cameraOptions.frame || "portrait";
    var coverage = clamp(Number(cameraOptions.coverage) || (frame === "full" ? 0.78 : 0.76), 0.45, 0.95);
    var height = frame === "full" ? size.y : size.y * 0.52;
    var targetRatio = frame === "full" ? 0.50 : 0.66;
    if (Number.isFinite(Number(cameraOptions.target_ratio))) {
      targetRatio = clamp(Number(cameraOptions.target_ratio), 0.35, 0.78);
    }
    var targetY = box.min.y + size.y * targetRatio;
    var fovRad = (camera.fov || 45) * Math.PI / 180;
    var distance = (height * 0.5) / Math.max(0.001, Math.tan(fovRad * 0.5) * coverage);
    distance = Math.max(distance, size.z * 1.25, 8);
    var offsetX = Number(cameraOptions.offset_x);
    if (!Number.isFinite(offsetX)) {
      offsetX = frame === "portrait" ? 0 : 0;
    }
    var offsetY = Number(cameraOptions.offset_y) || 0;
    var target = new THREE.Vector3(center.x + offsetX, targetY + offsetY, center.z);
    controls.target.copy(target);
    camera.position.set(target.x, target.y, target.z + distance);
    camera.near = Math.max(0.1, distance / 200);
    camera.far = Math.max(2000, distance * 12 + size.length());
    camera.updateProjectionMatrix();
    controls.update();
    status.frame = {
      mode: frame,
      coverage: coverage,
      distance: distance,
      modelHeight: size.y
    };
  }

  function applyRestPose(elapsed) {
    // PMX 模型加载后默认停在建模用的 T-pose/A-pose（双手平举）。桌宠场景没有
    // VMD 动作文件矫正它，所以每帧在 helper.update() 后维持一个安静待机基准。
    // 幅度保持克制：手臂自然放低但不贴死身体，只叠一点与呼吸同步的微动。
    if (!model || !model.skeleton) return;
    elapsed = Number(elapsed) || 0;
    var breath = Math.sin(elapsed * 0.35);
    var idleEnergy = livenessOption("idle_energy", 0.66, 0.25, 1.0);
    var armSway = livenessOption("arm_sway", 0.34, 0.0, 1.0);
    var bones = currentConfig.bones || {};
    var leftShoulder = findBone(bones.leftShoulder || "左肩");
    var rightShoulder = findBone(bones.rightShoulder || "右肩");
    var leftArm = findBone(bones.leftArm || "左腕");
    var rightArm = findBone(bones.rightArm || "右腕");
    var leftElbow = findBone(bones.leftElbow || "左ひじ");
    var rightElbow = findBone(bones.rightElbow || "右ひじ");
    if (leftShoulder) leftShoulder.rotation.z = -0.08 + breath * 0.005 * idleEnergy * armSway;
    if (rightShoulder) rightShoulder.rotation.z = 0.08 - breath * 0.005 * idleEnergy * armSway;
    if (leftArm) leftArm.rotation.z = -0.72 + breath * 0.012 * armSway + livenessState.poseZ * 0.10 * armSway;
    if (rightArm) rightArm.rotation.z = 0.72 - breath * 0.012 * armSway + livenessState.poseZ * 0.08 * armSway;
    if (leftElbow) leftElbow.rotation.z = -0.12 + breath * 0.004 * armSway;
    if (rightElbow) rightElbow.rotation.z = 0.12 - breath * 0.004 * armSway;
  }

  function resizeMmd(width, height, layoutHeight) {
    if (!renderer || !camera) return;
    var w = Math.max(1, Math.floor(Number(width) || window.innerWidth || 1));
    var h = Math.max(1, Math.floor(Number(height) || window.innerHeight || 1));
    var lh = Math.max(h, Math.floor(Number(layoutHeight) || h));
    renderer.setSize(w, h);
    camera.aspect = w / Math.max(1, h);
    camera.updateProjectionMatrix();
    if (model) {
      var scaleBase = Math.max(0.4, Math.min(1.8, h / Math.max(1, lh)));
      var userScale = Number(currentConfig.model_scale) || 1;
      model.scale.set(userScale * scaleBase, userScale * scaleBase, userScale * scaleBase);
      frameModel();
    }
  }

  function setLipSync(value) {
    targetLip = clamp(value, 0, 1);
  }

  function lookAt(x, y) {
    targetLookX = clamp(x, -1, 1);
    targetLookY = clamp(y, -1, 1);
  }

  function applyLookAt() {
    if (!model || !model.skeleton) return;
    var head = findBone((currentConfig.bones || {}).head || "頭");
    if (!head) return;
    smoothLookX += (targetLookX - smoothLookX) * 0.18;
    smoothLookY += (targetLookY - smoothLookY) * 0.18;
    var headPitchNeutral = Number(currentConfig.head_pitch_neutral);
    if (!Number.isFinite(headPitchNeutral)) headPitchNeutral = 0.04;
    headPitchNeutral = clamp(headPitchNeutral, -0.25, 0.25);
    head.rotation.y = smoothLookX * 0.30;
    head.rotation.x = headPitchNeutral + smoothLookY * 0.16;
  }

  function setExpression(name, weight) {
    var requested = String(name || "");
    if (!model || !model.morphTargetInfluences) {
      status.lastExpression = {
        requested: requested,
        candidates: [],
        index: -1,
        applied: false,
        reason: "model_not_ready",
        at: Date.now()
      };
      return;
    }
    var candidates = resolveExpressionCandidates(name);
    var index = resolveMorphIndex(candidates, []);
    if (index < 0) {
      status.lastExpression = {
        requested: requested,
        candidates: candidates,
        index: -1,
        applied: false,
        reason: "morph_not_found",
        at: Date.now()
      };
      return;
    }
    activeExpressions.push({
      index: index,
      weight: clamp(weight, 0, 1),
      startedAt: Date.now(),
      duration: 2400
    });
    status.lastExpression = {
      requested: requested,
      candidates: candidates,
      index: index,
      applied: true,
      at: Date.now()
    };
    if (activeExpressions.length > 8) activeExpressions.shift();
  }

  function resolveExpressionCandidates(name) {
    var aliases = currentConfig.expressions && currentConfig.expressions[name];
    var candidates = [];
    pushMorphCandidates(candidates, aliases);
    pushMorphCandidates(candidates, name);
    return candidates;
  }

  function playMotion(name, loop) {
    var motion = String(name || "");
    status.lastMotion = { name: motion, loop: !!loop, at: Date.now() };
    if (/talk|speak|speaking|tts/i.test(motion)) speakingActive = true;
    if (/think|thinking|llm/i.test(motion)) thinkingActive = true;
    if (/tap|click|pet_clicked|touch/i.test(motion)) triggerInteraction("tap");
  }

  function stopMotion(name) {
    var motion = String(name || "");
    status.lastStoppedMotion = { name: motion, at: Date.now() };
    if (!motion || /talk|speak|speaking|tts/i.test(motion)) speakingActive = false;
    if (!motion || /think|thinking|llm/i.test(motion)) thinkingActive = false;
  }

  function triggerInteraction(kind) {
    livenessState.interactionKind = String(kind || "tap");
    livenessState.interactionUntil = Date.now() + 900;
    livenessState.interactionPulse = 1.0;
    status.lastInteraction = { kind: livenessState.interactionKind, at: Date.now() };
  }

  function getRendererStatus() {
    return JSON.stringify(status);
  }

  function animate() {
    requestAnimationFrame(animate);
    var delta = clock ? clock.getDelta() : 0.016;
    var elapsed = (Date.now() - startedAt) / 1000;
    if (helper) helper.update(Math.min(0.033, delta || 0.016));
    applyRestPose(elapsed);
    applyLookAt();
    applyLivenessMotion(elapsed, delta || 0.016);
    applyLipSync();
    applyBlink();
    applyExpressionBlends();
    renderFrame();
  }

  function selectorCacheKey(selector, fallbackCandidates) {
    try {
      return JSON.stringify([selector, fallbackCandidates]);
    } catch (error) {
      return String(selector || "") + "|" + String(fallbackCandidates || "");
    }
  }

  function pushMorphCandidates(out, value) {
    if (Array.isArray(value)) {
      for (var i = 0; i < value.length; i++) pushMorphCandidates(out, value[i]);
      return;
    }
    if (value === null || value === undefined || value === "") return;
    out.push(value);
  }

  function morphNameLookup(dictionary, name) {
    if (!dictionary || !name) return -1;
    if (typeof dictionary[name] === "number") return dictionary[name];
    var normalized = String(name).trim().toLowerCase();
    var keys = Object.keys(dictionary);
    for (var i = 0; i < keys.length; i++) {
      if (String(keys[i]).trim().toLowerCase() === normalized) {
        return dictionary[keys[i]];
      }
    }
    return -1;
  }

  function resolveMorphIndex(selector, fallbackCandidates) {
    if (!model || !model.morphTargetInfluences) return -1;
    var dictionary = model.morphTargetDictionary || {};
    var candidates = [];
    pushMorphCandidates(candidates, selector);
    pushMorphCandidates(candidates, fallbackCandidates);
    for (var i = 0; i < candidates.length; i++) {
      var candidate = candidates[i];
      if (typeof candidate === "number" && Number.isFinite(candidate)) {
        var numeric = Math.floor(candidate);
        if (typeof model.morphTargetInfluences[numeric] === "number") return numeric;
        continue;
      }
      var text = String(candidate || "").trim();
      if (!text) continue;
      if (/^-?\d+$/.test(text)) {
        var parsed = Number(text);
        if (typeof model.morphTargetInfluences[parsed] === "number") return parsed;
      }
      var named = morphNameLookup(dictionary, text);
      if (typeof model.morphTargetInfluences[named] === "number") return named;
    }
    return -1;
  }

  function resolveMorphIndices(selector, fallbackCandidates) {
    if (!model || !model.morphTargetInfluences) return [];
    var candidates = [];
    pushMorphCandidates(candidates, selector);
    if (!candidates.length) pushMorphCandidates(candidates, fallbackCandidates);
    var seen = {};
    var indices = [];
    for (var i = 0; i < candidates.length; i++) {
      var index = resolveMorphIndex(candidates[i], []);
      if (index < 0 || seen[index]) continue;
      seen[index] = true;
      indices.push(index);
    }
    return indices;
  }

  function applyExpressionBlends() {
    if (!model || !model.morphTargetInfluences) return;
    clearControlledExpressionInfluences();
    if (!activeExpressions.length) return;
    var now = Date.now();
    var next = [];
    var values = {};
    for (var i = 0; i < activeExpressions.length; i++) {
      var item = activeExpressions[i];
      var progress = clamp((now - item.startedAt) / Math.max(1, item.duration), 0, 1);
      var value = item.weight * (1 - easeOut(progress));
      values[item.index] = Math.max(values[item.index] || 0, value);
      if (progress < 1 && value > 0.01) next.push(item);
    }
    var keys = Object.keys(values);
    for (var j = 0; j < keys.length; j++) {
      var index = Number(keys[j]);
      if (typeof model.morphTargetInfluences[index] === "number") {
        model.morphTargetInfluences[index] = clamp(values[index], 0, 1);
        controlledExpressionIndices[index] = true;
      }
    }
    activeExpressions = next;
  }

  function clearControlledExpressionInfluences() {
    var keys = Object.keys(controlledExpressionIndices);
    for (var i = 0; i < keys.length; i++) {
      var index = Number(keys[i]);
      if (model && model.morphTargetInfluences && typeof model.morphTargetInfluences[index] === "number") {
        model.morphTargetInfluences[index] = 0;
      }
    }
    controlledExpressionIndices = {};
  }

  function resolveBlinkMorphIndex() {
    var selector = (currentConfig.morphs || {}).blink;
    var fallback = ["まばたき", "瞬き", "E_Close", "blink", "Blink", "EyeClose", "eye close", "目閉じ"];
    var key = selectorCacheKey(selector, fallback);
    if (morphCache.blinkKey !== key) {
      morphCache.blinkKey = key;
      morphCache.blinkIndex = resolveMorphIndex(selector, fallback);
      status.resolvedMorphs = status.resolvedMorphs || {};
      status.resolvedMorphs.blink = morphCache.blinkIndex;
    }
    return morphCache.blinkIndex;
  }

  function resolveMouthMorphIndices() {
    var selector = (currentConfig.morphs || {}).mouth;
    var fallback = ["あ", "い", "う", "え", "お", "A", "I", "U", "E", "O"];
    var key = selectorCacheKey(selector, fallback);
    if (morphCache.mouthKey !== key) {
      morphCache.mouthKey = key;
      morphCache.mouthIndices = resolveMorphIndices(selector, fallback);
      status.resolvedMorphs = status.resolvedMorphs || {};
      status.resolvedMorphs.mouth = morphCache.mouthIndices.slice();
    }
    return morphCache.mouthIndices;
  }

  function applyLipSync() {
    if (!model || !model.morphTargetInfluences) return;
    var mouth = resolveMouthMorphIndices();
    if (!mouth.length) return;
    smoothLip += (targetLip - smoothLip) * 0.38;
    for (var i = 0; i < mouth.length; i++) {
      if (typeof model.morphTargetInfluences[mouth[i]] === "number") {
        model.morphTargetInfluences[mouth[i]] = 0;
      }
    }
    if (smoothLip <= 0.035) return;
    var now = Date.now();
    if (now - lastMouthAt > 95) {
      mouthFrame = (mouthFrame + 1) % mouth.length;
      lastMouthAt = now;
    }
    var index = mouth[mouthFrame];
    if (typeof model.morphTargetInfluences[index] === "number") {
        model.morphTargetInfluences[index] = Math.min(1, 0.2 + smoothLip * 0.8 * (Number(currentConfig.mouth_gain) || 1));
    }
  }

  function applyBlink() {
    if (!model || !model.morphTargetInfluences) return;
    var blink = resolveBlinkMorphIndex();
    if (blink < 0) return;
    if (typeof model.morphTargetInfluences[blink] !== "number") return;
    var now = Date.now();
    var blinkDuration = blinkCloseMs + blinkOpenMs;
    if (now >= blinkUntil && now - lastBlinkAt > blinkInterval) {
      blinkUntil = now + blinkDuration;
      lastBlinkAt = now;
      if (doubleBlink) {
        doubleBlink = false;
        blinkInterval = 230 + Math.random() * 120;
      } else {
        doubleBlink = Math.random() < 0.18;
        var base = (speakingActive || thinkingActive) ? 1500 : 2400;
        blinkInterval = base + Math.random() * 2600;
      }
    }
    var value = 0;
    if (now < blinkUntil) {
      var elapsedBlink = blinkDuration - (blinkUntil - now);
      if (elapsedBlink <= blinkCloseMs) {
        value = clamp(elapsedBlink / blinkCloseMs, 0, 1);
      } else {
        value = clamp(1 - (elapsedBlink - blinkCloseMs) / blinkOpenMs, 0, 1);
      }
    }
    model.morphTargetInfluences[blink] = value;
  }

  function scheduleNewPose(now) {
    var active = speakingActive || thinkingActive;
    var idleEnergy = livenessOption("idle_energy", 0.66, 0.25, 1.0);
    var thinkingStillness = thinkingActive ? livenessOption("thinking_stillness", 0.72, 0.35, 1.0) : 1.0;
    var energy = idleEnergy * thinkingStillness;
    var wide = Math.random() < (active ? 0.42 : 0.24);
    livenessState.targetX = (Math.random() * 2 - 1) * (wide ? 0.055 : 0.022) * energy;
    livenessState.targetY = (Math.random() * 2 - 1) * (wide ? 0.064 : 0.026) * energy;
    livenessState.targetZ = (Math.random() * 2 - 1) * (wide ? 0.046 : 0.018) * energy;
    livenessState.nextPoseAt = now + 2400 + Math.random() * (active ? 3000 : 5200);
  }

  function applyLivenessMotion(elapsed, delta) {
    if (!model || !model.skeleton) return;
    var now = Date.now();
    if (now >= livenessState.nextPoseAt) scheduleNewPose(now);
    var step = clamp((Number(delta) || 0.016) * 60, 0.4, 2.0);
    var idleEnergy = livenessOption("idle_energy", 0.66, 0.25, 1.0);
    var speakingBody = speakingActive ? livenessOption("speaking_body", 0.48, 0.0, 1.0) : 0.0;
    var thinkingStillness = thinkingActive ? livenessOption("thinking_stillness", 0.72, 0.35, 1.0) : 1.0;
    var poseRate = (thinkingActive ? 0.022 : 0.018) * step;
    livenessState.poseX += (livenessState.targetX - livenessState.poseX) * poseRate;
    livenessState.poseY += (livenessState.targetY - livenessState.poseY) * poseRate;
    livenessState.poseZ += (livenessState.targetZ - livenessState.poseZ) * poseRate;

    var interaction = 0;
    if (now < livenessState.interactionUntil) {
      interaction = easeOut((livenessState.interactionUntil - now) / 900);
      livenessState.interactionPulse = interaction;
    } else {
      livenessState.interactionPulse *= 0.86;
      interaction = livenessState.interactionPulse;
    }

    var seed = livenessState.seed;
    var breathRate = speakingActive ? 1.14 : 0.82;
    var breath = Math.sin(elapsed * breathRate + seed);
    var microScale = idleEnergy * thinkingStillness;
    var microX = fbm(elapsed * 0.18 + seed) * 0.007 * microScale;
    var microY = fbm(elapsed * 0.16 + seed + 17.0) * 0.009 * microScale;
    var microZ = fbm(elapsed * 0.14 + seed + 31.0) * 0.005 * microScale;
    var bones = currentConfig.bones || {};
    var chest = findBone(bones.chest || "上半身2");
    var neck = findBone(bones.neck || "首");
    var head = findBone(bones.head || "頭");
    if (chest) {
      chest.rotation.x = breath * 0.006 * idleEnergy + livenessState.poseX * 0.24 + interaction * 0.016 + smoothLip * speakingBody * 0.010;
      chest.rotation.y = livenessState.poseY * 0.10;
      chest.rotation.z = livenessState.poseZ * 0.18 - interaction * 0.018;
    }
    if (neck) {
      neck.rotation.x = smoothLookY * 0.050 + livenessState.poseX * 0.24 + microX;
      neck.rotation.y = smoothLookX * 0.085 + livenessState.poseY * 0.24 + microY;
      neck.rotation.z = livenessState.poseZ * 0.16 + microZ;
    }
    if (head) {
      head.rotation.x += breath * 0.004 * idleEnergy + livenessState.poseX * 0.56 + microX + interaction * 0.030 + smoothLip * speakingBody * Math.sin(elapsed * 7.4) * 0.010;
      head.rotation.y += livenessState.poseY * 0.50 + microY + smoothLip * speakingBody * Math.sin(elapsed * 5.8) * 0.007;
      head.rotation.z = livenessState.poseZ * 0.88 + microZ - interaction * 0.060;
    }
  }

  function findBone(name) {
    if (!model || !model.skeleton) return null;
    return model.skeleton.bones.find(function (bone) { return bone.name === name; }) || null;
  }

  window.loadCharacter = loadCharacter;
  window.resizeMmd = resizeMmd;
  window.setLipSync = setLipSync;
  window.lookAt = lookAt;
  window.setExpression = setExpression;
  window.playMotion = playMotion;
  window.stopMotion = stopMotion;
  window.triggerInteraction = triggerInteraction;
  window.getRendererStatus = getRendererStatus;
  window.addEventListener("resize", function () {
    resizeMmd(window.innerWidth, window.innerHeight, window.innerHeight);
  });
  loadCharacter(currentConfig);
})();
