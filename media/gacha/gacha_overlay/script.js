(() => {
  "use strict";

  const CONFIG = {
    MAX_VISIBLE: 4,
    HORIZONTAL_SPACING: 450,
    DROP_STAGGER_MS: 120,
    OPENING_STAGGER_MS: 120,
    CARD_STAGGER_MS: 60,
    DROP_FREEZE_MS: 250,
    CONVERSION_CHAIN_DELAY_MS: 250,
    CARD_REVEAL_DELAY_MS: 250,
    STAGE_HANDOFF_DELAY_MS: 50,
    SILHOUETTE_DELAY_MS: 250,
    FRAME_DELAY_MS: 20,
    CARD_TARGET_SCALE: 0.85,
    CARD_START_RATIO: 0.28,
    CARD_MULTI_START_RATIO: 0.22,
    CARD_MIN_START_SCALE: 0.18,
    CARD_MAX_SCALE: 1.2,
    CARD_START_Y: 0,
    CARD_TARGET_Y: -360,
    CARD_PRIME_HOLD_MS: 200,
    CARD_BEHIND_SCALE_MULT: 0.65,
    CARD_BEHIND_CENTER_RATIO: 0.5,
    CARD_PROMOTION_TARGET_RATIO: 0.75,
    CARD_PLACEMENT_FALLBACK_PX: 320,
    CARD_CENTER_OFFSET_PX: -30,
    CARD_RISE_DURATION_MS: 650,
    CARD_SILHOUETTE_DURATION_MS: 480,
    CARD_LABEL_FADE_DURATION_MS: 320,
    OPENING_PROMOTION_DELAY_MS: 350,
    OPENING_REVEAL_PROGRESS: 0.15,
    OPENING_REVEAL_TIMEOUT_MS: 1500,
    BATCH_HOLD_MS: 3000,
    FADE_STEPS: 20,
    LEVEL_INITIAL_HOLD_MS: 500,
    LEVEL_POP_DURATION_MS: 420,
    LEVEL_PEAK_SCALE: 1.8,
    MEDIA_START_TIMEOUT_MS: 1000,
    MEDIA_DEFAULT_TIMEOUT_MS: 25000,
    ASSETS_ROOT: "assets",
    ANIMATION_ROOT: "animations",
    IMAGES_ROOT: "images",
    DROP_FILE: "drop.webm",
    MUTE_VIDEOS: false,
    STAR_START_SCALE_RATIO: 0.22,
    STAR_TARGET_SCALE_MULT: 2.8,
    STAR_MAX_SCALE: 4.5,
    STAR_GROW_DURATION_MS: 420,
    STAR_ROTATION_DURATION_MS: 14000,
    STAR_PULSE_DURATION_MS: 1800,
    STAR_VERTICAL_OFFSET_PX: -30,
    STAR_ANIMATION_JITTER_RATIO: 0.15,
    COMMON_ONLY_OPENING_DELAY_MS: 250,
    ASSET_SCALE_BY_COUNT: {
      1: 1,
      2: 1,
      3: 0.92,
      4: 0.9,
    },
  };

  const DEBUG_OVERLAY = true;
  const overlayLog = (...args) => {
    if (DEBUG_OVERLAY) {
      console.log("[GachaOverlay]", ...args);
    }
  };
  const overlayWarn = (...args) => {
    if (DEBUG_OVERLAY) {
      console.warn("[GachaOverlay]", ...args);
    }
  };

  const OVERLAY_BASE_URL = (() => {
    try {
      const url = new URL(window.location.href);
      url.hash = "";
      url.search = "";
      return url.href;
    } catch {}
    return window.location.href.split(/[?#]/)[0];
  })();

  const SLOT_LAYOUTS = {
    1: [0],
    2: [-0.8, 0.8],
    3: [-1, 0, 1],
    4: [-1.5, -0.5, 0.5, 1.5],
    5: [-2, -1, 0, 1, 2],
  };

  const RARITY_KEY_MAP = {
    UR: "legendary",
    SSR: "epic",
    SR: "rare",
    R: "uncommon",
    N: "common",
    LEGENDARY: "legendary",
    EPIC: "epic",
    RARE: "rare",
    UNCOMMON: "uncommon",
    COMMON: "common",
  };

  const RARITY_STAR_MAP = {
    common: "star_yellow.svg",
    uncommon: "star_green.svg",
    rare: "star_blue.svg",
    epic: "star_purple.svg",
    legendary: "star_orange.svg",
  };

  const BADGE_RARITIES = ["common", "uncommon", "rare", "epic", "legendary"];

  class BrowserGachaAnimator {
    constructor(stageEl) {
      this.stage = stageEl;
      this.queue = Promise.resolve();
      this._activeMeta = null;
      this.setBannerEl = null;
      this.setBannerNameEl = null;
      this._ensureStageChrome();
    }

    _ensureStageChrome() {
      if (!this.stage) {
        return;
      }
      if (!this.entryHost || !this.entryHost.isConnected) {
        this.entryHost = document.createElement("div");
        this.entryHost.className = "gacha-stage-host";
        this.stage.append(this.entryHost);
      }
      if (!this.bannerEl || !this.bannerEl.isConnected) {
        const banner = document.createElement("div");
        banner.className = "gacha-batch-banner";
        const label = document.createElement("span");
        label.className = "banner-label";
        label.textContent = "Now Summoning";
        const name = document.createElement("span");
        name.className = "banner-name";
        const pulls = document.createElement("span");
        pulls.className = "banner-pulls";
        banner.append(label, name, pulls);
        this.stage.append(banner);
        this.bannerEl = banner;
        this.bannerNameEl = name;
        this.bannerPullsEl = pulls;
      }
      if (!this.setBannerEl || !this.setBannerEl.isConnected) {
        const setBanner = document.createElement("div");
        setBanner.className = "gacha-set-banner";
        const prefix = document.createElement("span");
        prefix.className = "set-banner-prefix";
        prefix.textContent = "Summoning From";
        const name = document.createElement("span");
        name.className = "set-banner-name";
        setBanner.append(prefix, name);
        this.stage.append(setBanner);
        this.setBannerEl = setBanner;
        this.setBannerNameEl = name;
      }
    }

    _updateBanner(meta) {
      this._ensureStageChrome();
      if (!this.bannerEl) {
        return;
      }
      this._updateSetBanner(meta);
      const rawName = meta?.displayName || meta?.userName || meta?.userId;
      const displayName = typeof rawName === "string" ? rawName.trim() : "";
      const totalPulls = Number(meta?.totalPulls);
      if (!displayName) {
        if (this.bannerNameEl) {
          this.bannerNameEl.textContent = "";
        }
        if (this.bannerPullsEl) {
          this.bannerPullsEl.textContent = "";
        }
        this.bannerEl.classList.remove("is-visible");
        return;
      }
      if (this.bannerNameEl) {
        this.bannerNameEl.textContent = displayName;
      }
      if (this.bannerPullsEl) {
        if (Number.isFinite(totalPulls) && totalPulls > 0) {
          const noun = totalPulls === 1 ? "pull" : "pulls";
          this.bannerPullsEl.textContent = `${totalPulls} ${noun}`;
        } else {
          this.bannerPullsEl.textContent = "rolling now";
        }
      }
      this.bannerEl.classList.add("is-visible");
    }

    clear() {
      this._ensureStageChrome();
      if (this.entryHost) {
        this.entryHost.innerHTML = "";
      }
      this._activeMeta = null;
      this._updateBanner(null);
      this._updateSetBanner(null);
    }

    enqueue(pulls, meta = {}) {
      this.queue = this.queue
        .then(() => this._run(pulls, meta))
        .catch((err) => console.error("[GachaOverlay] Animation failed", err));
      return this.queue;
    }

    async _run(pulls, meta = {}) {
      this._ensureStageChrome();
      const sanitized = Array.isArray(pulls) ? pulls.filter(Boolean) : [];
      if (!sanitized.length) {
        this.clear();
        return;
      }
      const normalizedMeta = {
        totalPulls: Number.isFinite(Number(meta?.totalPulls)) ? Number(meta.totalPulls) : sanitized.length,
        displayName: typeof meta?.displayName === "string" ? meta.displayName : "",
        userName: typeof meta?.userName === "string" ? meta.userName : "",
        userId: typeof meta?.userId === "string" ? meta.userId : "",
        setName: formatSetName(
          typeof meta?.setName === "string"
            ? meta.setName
            : typeof meta?.set_name === "string"
              ? meta.set_name
              : typeof meta?.set === "string"
                ? meta.set
                : "",
        ),
      };
      this._activeMeta = normalizedMeta;
      this._updateBanner(normalizedMeta);
      const batches = chunkArray(sanitized, CONFIG.MAX_VISIBLE);
      for (const batch of batches) {
        if (!batch.length) {
          continue;
        }
        await this._animateBatch(batch);
      }
      this._activeMeta = null;
      this._updateBanner(null);
       this._updateSetBanner(null);
    }

    _updateSetBanner(meta) {
      this._ensureStageChrome();
      if (!this.setBannerEl || !this.setBannerNameEl) {
        return;
      }
      const raw = typeof meta?.setName === "string" ? meta.setName.trim() : "";
      if (!raw) {
        this.setBannerNameEl.textContent = "";
        this.setBannerEl.classList.remove("is-visible");
        return;
      }
      this.setBannerNameEl.textContent = raw;
      this.setBannerEl.classList.add("is-visible");
    }

    async _animateBatch(batch) {
      this._ensureStageChrome();
      if (this.entryHost) {
        this.entryHost.innerHTML = "";
      }
      const slots = computeSlotOffsets(batch.length, CONFIG.HORIZONTAL_SPACING);
      const entries = batch.map((data, index) => this._mountEntry(data, slots[index], batch.length));
      await Promise.all(entries.map((entry) => entry.ready));
      await this._runSequence(entries);
      await sleep(CONFIG.BATCH_HOLD_MS);
      await this._fadeAndCleanup(entries);
    }

    _mountEntry(data, slot, batchSize) {
      const order = slot?.order ?? 0;
      const offset = slot?.offset ?? 0;
      const root = document.createElement("div");
      root.className = "gacha-chain";
      root.style.setProperty("--slot-offset", `${offset}px`);
      const videoStack = document.createElement("div");
      videoStack.className = "video-stack";
      const dropVideo = this._createVideoElement("drop");
      const conversionVideo = this._createVideoElement("conversion");
      const openingVideo = this._createVideoElement("open");
      videoStack.append(dropVideo, conversionVideo, openingVideo);

      const cardRig = document.createElement("div");
      cardRig.className = "card-rig";
      const cardFrame = document.createElement("div");
      cardFrame.className = "gacha-card-frame";
      const cardImg = document.createElement("img");
      cardImg.className = "gacha-card";
      cardImg.decoding = "async";
      cardImg.draggable = false;
      cardFrame.append(cardImg);
      cardRig.classList.add("is-hidden");
      cardRig.dataset.layer = "behind";

      const labelStack = document.createElement("div");
      labelStack.className = "label-stack";
      const nameEl = document.createElement("div");
      nameEl.className = "gacha-name";
      const levelEl = document.createElement("div");
      levelEl.className = "gacha-level";
      const levelPrefix = document.createElement("span");
      levelPrefix.className = "prefix";
      levelPrefix.textContent = "Lv.";
      const levelNumber = document.createElement("span");
      levelNumber.className = "number";
      levelNumber.style.setProperty("--level-peak-scale", CONFIG.LEVEL_PEAK_SCALE.toString());
      levelEl.append(levelPrefix, levelNumber);
      labelStack.append(nameEl, levelEl);

      const starWrapper = document.createElement("div");
      starWrapper.className = "gacha-star-wrapper";
      const starRotator = document.createElement("div");
      starRotator.className = "gacha-star-rotator";
      const starBase = document.createElement("div");
      starBase.className = "gacha-star-base";
      const starImg = document.createElement("img");
      starImg.className = "gacha-star";
      starImg.decoding = "async";
      starImg.draggable = false;
      starImg.alt = "";
      starBase.append(starImg);
      starRotator.append(starBase);
      starWrapper.append(starRotator);

      cardRig.append(starWrapper, cardFrame, labelStack);

      root.append(videoStack, cardRig);
      (this.entryHost || this.stage).append(root);

      const rarityKey = resolveRarityKey(data?.rarity);
      const isShiny = Boolean(data?.is_shiny);
      root.dataset.rarity = rarityKey;
      cardFrame.classList.toggle("is-shiny", isShiny);
      starWrapper.classList.toggle("is-shiny", isShiny);
      nameEl.textContent = formatName(data?.name);
      const levelMeta = resolveLevelMeta(data);
      levelNumber.textContent = levelMeta.currentText;
      levelNumber.classList.toggle("is-upgraded", levelMeta.currentText === "MAX");
      labelStack.style.setProperty("--label-opacity", "0");

      const imageSrc = resolveImageSource(data);
      if (imageSrc) {
        cardImg.src = imageSrc;
      }
      cardImg.alt = nameEl.textContent || "Gacha pull";

      const assetScale = this._resolveAssetScale(batchSize);
      const metrics = this._computeCardMetrics(batchSize > 1, assetScale);
      cardRig.style.setProperty("--card-scale", metrics.startScale.toFixed(3));
      cardRig.style.setProperty("--card-translateY", `${metrics.startY}px`);
      cardRig.style.setProperty("--silhouette-strength", "1");

      this._assignVideoSources(
        {
          drop: dropVideo,
          conversion: conversionVideo,
          opening: openingVideo,
        },
        rarityKey,
        isShiny,
      );

      const entry = {
        data: data || {},
        order,
        root,
        videoStack,
        videos: {
          drop: dropVideo,
          conversion: conversionVideo,
          opening: openingVideo,
        },
        cardRig,
        cardFrame,
        cardImage: cardImg,
        labels: labelStack,
        nameEl,
        levelNumber,
        levelMeta,
        metrics,
        assetScale,
        labelOpacity: 0,
        rarityKey,
        star: {
          wrapper: starWrapper,
          rotator: starRotator,
          base: starBase,
          image: starImg,
          metrics: null,
        },
      };
      const starAsset = resolveStarAsset(rarityKey, isShiny);
      const starReady = this._configureStar(entry, starAsset);
      const badgeAsset = resolveBadgeAsset(rarityKey, isShiny);
      if (badgeAsset) {
        entry.badge = this._createRarityBadge(cardFrame, badgeAsset, isShiny, rarityKey);
      }
      const badgeReady = entry.badge?.ready || Promise.resolve();
      entry.ready = Promise.all([loadImage(cardImg), starReady, badgeReady]);
      return entry;
    }

    _createVideoElement(stageName) {
      const video = document.createElement("video");
      video.className = stageName;
      video.playsInline = true;
      video.preload = "auto";
      video.muted = CONFIG.MUTE_VIDEOS;
      video.controls = false;
      video.loop = false;
      video.disablePictureInPicture = true;
      video.setAttribute("webkit-playsinline", "true");
      video.addEventListener("error", (event) => {
        overlayWarn(`Video error on ${stageName}`, {
          src: video.currentSrc || video.src,
          error: event?.message || event,
        });
      });
      return video;
    }

    _assignVideoSources(videos, rarityKey, isShiny) {
      const dropPath = buildAnimationPath(CONFIG.DROP_FILE);
      overlayLog("Assign drop clip", { dropPath });
      setVideoSource(videos.drop, dropPath);
      if (isShiny) {
        const shinyConversion = buildAnimationPath("conversion", "shiny.webm");
        const shinyOpening = buildAnimationPath("opening", "shiny.webm");
        overlayLog("Assign shiny clips", { shinyConversion, shinyOpening });
        setVideoSource(videos.conversion, shinyConversion);
        setVideoSource(videos.opening, shinyOpening);
        return;
      }
      const conversionKey = rarityKey === "common" ? null : buildAnimationPath("conversion", `${rarityKey}.webm`);
      overlayLog("Assign conversion clip", { conversionKey, rarityKey });
      setVideoSource(videos.conversion, conversionKey);
      const openingPath = buildAnimationPath("opening", `${rarityKey}.webm`);
      overlayLog("Assign opening clip", { openingPath });
      setVideoSource(videos.opening, openingPath);
    }

    _createRarityBadge(container, assetSrc, isShiny, rarityKey) {
      if (!container || !assetSrc) {
        return null;
      }
      const root = document.createElement("div");
      root.className = "rarity-badge";
      const dataKey = isShiny ? "shiny" : (rarityKey || "common").toLowerCase();
      root.dataset.rarity = dataKey;
      const img = document.createElement("img");
      img.className = "rarity-badge-image";
      img.alt = "";
      img.decoding = "async";
      img.draggable = false;
      img.src = assetSrc;
      root.append(img);
      root.classList.add("is-stealthed");
      root.style.setProperty("--badge-scale", "0.05");
      container.append(root);
      return { root, image: img, ready: loadImage(img) };
    }

    _configureStar(entry, assetSrc) {
      const star = entry.star;
      if (!star?.wrapper) {
        return Promise.resolve();
      }
      if (!assetSrc) {
        star.wrapper.classList.add("is-hidden");
        star.metrics = null;
        star.wrapper.style.removeProperty("--star-offset");
        star.rotator.style.removeProperty("animation-delay");
        star.wrapper.style.removeProperty("--star-rotation-duration");
        star.wrapper.style.removeProperty("--star-pulse-duration");
        star.dynamicDurations = null;
        return Promise.resolve();
      }
      star.wrapper.classList.remove("is-hidden");
      star.wrapper.style.setProperty("--star-offset", `${CONFIG.STAR_VERTICAL_OFFSET_PX}px`);
      const jitterRatio = clamp(Number(CONFIG.STAR_ANIMATION_JITTER_RATIO) || 0, 0, 0.9);
      const baseRotation = Math.max(1, CONFIG.STAR_ROTATION_DURATION_MS);
      const basePulse = Math.max(50, CONFIG.STAR_PULSE_DURATION_MS);
      const rotationDuration = applyJitter(baseRotation, jitterRatio);
      const pulseDuration = applyJitter(basePulse, jitterRatio);
      const rotationPhase = Math.random() * rotationDuration;
      star.rotator.style.animationDelay = `-${rotationPhase}ms`;
      star.dynamicDurations = {
        rotation: rotationDuration,
        pulse: pulseDuration,
      };
      star.image.src = assetSrc;
      star.metrics = this._computeStarMetrics(entry.metrics);
      this._applyStarMetrics(entry);
      return loadImage(star.image);
    }

    _computeCardMetrics(isMultiBatch, assetScale = 1) {
      const normalizedAssetScale = clamp(Number(assetScale) || 1, 0.5, 1);
      const baseTargetScale = clamp(CONFIG.CARD_TARGET_SCALE, 0.2, CONFIG.CARD_MAX_SCALE);
      const targetScale = clamp(baseTargetScale * normalizedAssetScale, 0.2, CONFIG.CARD_MAX_SCALE);
      const startRatio = isMultiBatch ? CONFIG.CARD_MULTI_START_RATIO : CONFIG.CARD_START_RATIO;
      const startScale = clamp(targetScale * startRatio, CONFIG.CARD_MIN_START_SCALE, targetScale);
      return {
        startScale,
        baseStartScale: startScale,
        targetScale,
        startY: CONFIG.CARD_START_Y,
        targetY: CONFIG.CARD_TARGET_Y,
      };
    }

    _resolveAssetScale(activeCount) {
      if (!activeCount || activeCount <= 2) {
        return 1;
      }
      const map = CONFIG.ASSET_SCALE_BY_COUNT || {};
      const direct = map[activeCount];
      if (typeof direct === "number" && Number.isFinite(direct)) {
        return clamp(direct, 0.5, 1);
      }
      if (activeCount >= CONFIG.MAX_VISIBLE) {
        const fallback = map[CONFIG.MAX_VISIBLE];
        if (typeof fallback === "number" && Number.isFinite(fallback)) {
          return clamp(fallback, 0.5, 1);
        }
      }
      return 1;
    }

    _computeStarMetrics(cardMetrics) {
      const baseScale = Math.max(0.2, cardMetrics?.targetScale || CONFIG.CARD_TARGET_SCALE);
      const startScale = clamp(baseScale * CONFIG.STAR_START_SCALE_RATIO, 0.05, baseScale * 0.9);
      const rawTarget = Math.max(startScale * 1.2, baseScale * CONFIG.STAR_TARGET_SCALE_MULT);
      const targetScale = Math.min(rawTarget, CONFIG.STAR_MAX_SCALE);
      return { startScale, targetScale };
    }

    _applyStarMetrics(entry) {
      const star = entry.star;
      if (!star?.wrapper || !star.metrics) {
        return;
      }
      star.wrapper.style.setProperty("--star-scale", star.metrics.startScale.toFixed(3));
      star.wrapper.style.setProperty("--star-grow-duration", `${Math.max(100, CONFIG.STAR_GROW_DURATION_MS)}ms`);
      const rotationDuration = star.dynamicDurations?.rotation ?? Math.max(100, CONFIG.STAR_ROTATION_DURATION_MS);
      const pulseDuration = star.dynamicDurations?.pulse ?? Math.max(100, CONFIG.STAR_PULSE_DURATION_MS);
      star.wrapper.style.setProperty("--star-rotation-duration", `${rotationDuration}ms`);
      star.wrapper.style.setProperty("--star-pulse-duration", `${pulseDuration}ms`);
    }

    _setStarScale(entry, scale) {
      const star = entry.star;
      if (!star?.wrapper || !star.metrics) {
        return;
      }
      const value = clamp(scale, 0.05, CONFIG.STAR_MAX_SCALE);
      star.wrapper.style.setProperty("--star-scale", value.toFixed(3));
    }

    async _runSequence(entries) {
      if (!entries.length) {
        return;
      }
      overlayLog("Sequence start", { entries: entries.length });
      await this._runDropStage(entries);
      await this._runConversionStage(entries);
      if (this._shouldHoldBeforeOpening(entries)) {
        const extraHold = Math.max(0, Number(CONFIG.COMMON_ONLY_OPENING_DELAY_MS) || 0);
        if (extraHold > 0) {
          overlayLog("Common-only hold", { extraHold });
          await sleep(extraHold);
        }
      }
      await this._primeCards(entries);
      await this._runOpeningStage(entries);
    }

    async _runDropStage(entries) {
      overlayLog("Drop stage", { count: entries.length });
      const dropStagger = Math.max(0, Number(CONFIG.DROP_STAGGER_MS ?? CONFIG.CARD_STAGGER_MS) || 0);
      const tasks = entries.map((entry, index) => this._playStageVideo(entry, "drop", index * dropStagger, true));
      await Promise.all(tasks);
    }

    async _runConversionStage(entries) {
      const eligible = entries.filter((entry) => {
        const rarity = (entry?.rarityKey || "").toLowerCase();
        const isShiny = Boolean(entry?.data?.is_shiny);
        return isShiny || rarity !== "common";
      });
      if (!eligible.length) {
        overlayLog("Conversion stage skipped (all entries common)");
        return;
      }
      if (CONFIG.DROP_FREEZE_MS > 0) {
        overlayLog("Conversion drop freeze", { duration: CONFIG.DROP_FREEZE_MS });
        await sleep(CONFIG.DROP_FREEZE_MS);
      }
      overlayLog("Conversion stage", { count: eligible.length });
      const tasks = eligible.map((entry, index) => {
        if (!entry.videos.conversion?.dataset?.src) {
          overlayLog("Conversion skipped (no clip)", { index });
          return Promise.resolve();
        }
        const delay = index * CONFIG.CONVERSION_CHAIN_DELAY_MS;
        return this._playStageVideo(entry, "conversion", delay, true);
      });
      await Promise.all(tasks);
    }

    _shouldHoldBeforeOpening(entries) {
      if (!Array.isArray(entries) || !entries.length) {
        return false;
      }
      const delay = Math.max(0, Number(CONFIG.COMMON_ONLY_OPENING_DELAY_MS) || 0);
      if (!delay) {
        return false;
      }
      return entries.every((entry) => (entry?.rarityKey || "").toLowerCase() === "common");
    }

    async _primeCards(entries) {
      if (!entries.length) {
        return;
      }
      entries.forEach((entry) => this._prepareCardReveal(entry));
      this._exposePreparedCards(entries);
      if (CONFIG.CARD_PRIME_HOLD_MS > 0) {
        await sleep(CONFIG.CARD_PRIME_HOLD_MS);
      }
    }

    _prepareCardReveal(entry) {
      if (!entry?.cardRig) {
        return;
      }
      const metrics = entry.metrics;
      const stackHeight = this._measureVideoStackHeight(entry);
      const centerRatio = clamp(CONFIG.CARD_BEHIND_CENTER_RATIO, 0, 1);
      const promotionRatio = clamp(CONFIG.CARD_PROMOTION_TARGET_RATIO, 0, 1);
      const offsetPx = Number(CONFIG.CARD_CENTER_OFFSET_PX) || 0;
      metrics.startY = -stackHeight * centerRatio - offsetPx;
      metrics.targetY = -stackHeight * promotionRatio - offsetPx;
      entry.cardRig.style.setProperty("--card-translateY", `${metrics.startY}px`);

      const baseStartScale = metrics.baseStartScale ?? metrics.startScale;
      const behindScale = clamp(
        baseStartScale * CONFIG.CARD_BEHIND_SCALE_MULT,
        CONFIG.CARD_MIN_START_SCALE,
        metrics.targetScale,
      );
      metrics.startScale = behindScale;
      entry.cardRig.style.setProperty("--card-scale", behindScale.toFixed(3));
      entry.cardRig.style.setProperty("--silhouette-strength", "1");
      entry.cardRig.classList.add("is-hidden", "is-stealthed");
      this._setCardLayer(entry, "behind");
    }

    _exposePreparedCards(entries) {
      if (!Array.isArray(entries) || !entries.length) {
        return;
      }
      entries.forEach((entry) => {
        if (!entry?.cardRig) {
          return;
        }
        entry.cardRig.classList.add("is-stealthed");
        this._setCardLayer(entry, "behind");
      });
    }

    _measureVideoStackHeight(entry) {
      const rect = entry.videoStack?.getBoundingClientRect();
      const height = rect?.height || 0;
      return Math.max(height, CONFIG.CARD_PLACEMENT_FALLBACK_PX);
    }

    async _runOpeningStage(entries) {
      overlayLog("Opening stage", { count: entries.length });
      if (!entries.length) {
        return;
      }
      const orderedEntries = [...entries].sort((a, b) => (a.order || 0) - (b.order || 0));
      const fadeTask = this._fadeInCardBackdrops(orderedEntries);
      const videoTasks = orderedEntries.map((entry, index) => this._playOpeningVideo(entry, index));
      const revealChainTask = this._runOpeningRevealChain(orderedEntries);
      await Promise.all([...videoTasks, revealChainTask, fadeTask]);
    }

    _fadeInCardBackdrops(entries) {
      if (!Array.isArray(entries) || !entries.length) {
        return Promise.resolve();
      }
      return Promise.all(
        entries.map(
          (entry) =>
            new Promise((resolve) => {
              const rig = entry?.cardRig;
              if (!rig) {
                resolve();
                return;
              }
              rig.classList.add("is-stealthed");
              rig.classList.remove("is-hidden");
              requestAnimationFrame(() => {
                rig.classList.remove("is-stealthed");
                resolve();
              });
            }),
        ),
      );
    }

    async _playOpeningVideo(entry, orderIndex) {
      const openingStagger = Math.max(0, Number(CONFIG.OPENING_STAGGER_MS ?? CONFIG.CARD_STAGGER_MS) || 0);
      const staggerDelay = Math.max(0, (Number(orderIndex) || 0) * openingStagger);
      if (staggerDelay > 0) {
        await sleep(staggerDelay);
      }
      const openingVideo = entry.videos.opening?.dataset?.src ? entry.videos.opening : null;
      if (!openingVideo) {
        return;
      }
      await this._playStageVideo(entry, "opening", 0, false);
    }

    async _runOpeningRevealChain(entries) {
      if (!Array.isArray(entries) || !entries.length) {
        return;
      }
      const tasks = entries.map((entry, index) => {
        const delay = this._computeChainRevealDelay(entry, index);
        return this._animateCard(entry, delay, null, { skipVideoGate: true });
      });
      await Promise.all(tasks);
    }

    _computeChainRevealDelay(entry, orderIndex) {
      const hasCustomDelay = typeof entry?.data?.revealTime === "number";
      const baseDelay = hasCustomDelay ? Math.max(0, entry.data.revealTime) : Math.max(0, CONFIG.CARD_REVEAL_DELAY_MS);
      const openingStagger = Math.max(0, Number(CONFIG.OPENING_STAGGER_MS ?? CONFIG.CARD_STAGGER_MS) || 0);
      const staggerDelay = Math.max(0, (Number(orderIndex) || 0) * openingStagger);
      return baseDelay + staggerDelay;
    }

    async _playStageVideo(entry, stageName, delayMs, holdFinalFrame) {
      const video = entry.videos[stageName];
      const source = video?.dataset?.src || video?.getAttribute?.("data-src") || video?.currentSrc || video?.src || "";
      if (!video || !source) {
        overlayWarn("Stage skipped (missing video)", { stageName, src: source });
        return;
      }
      if (delayMs > 0) {
        await sleep(delayMs);
      }
      await ensureVideoReady(video);
      this._setActiveStage(entry, stageName);
      video.currentTime = 0;
      overlayLog("Stage play start", {
        stageName,
        src: source,
        delayMs,
      });
      const started = waitForVideoStart(video, CONFIG.MEDIA_START_TIMEOUT_MS);
      await safePlay(video);
      await started;
      await waitForVideoEnd(video, CONFIG.MEDIA_DEFAULT_TIMEOUT_MS);
      if (holdFinalFrame) {
        video.pause();
        overlayLog("Stage hold final frame", { stageName });
      } else {
        this._clearStage(entry, stageName);
      }
    }

    _setActiveStage(entry, stageName) {
      if (entry.activeStage === stageName) {
        return;
      }
      if (entry.activeStage) {
        this._clearStage(entry, entry.activeStage, false);
      }
      overlayLog("Active stage", { stageName });
      const video = entry.videos[stageName];
      if (video) {
        video.classList.add("is-active");
      }
      entry.activeStage = stageName;
    }

    _clearStage(entry, stageName, resetActive = true) {
      const video = entry.videos[stageName];
      if (!video) {
        return;
      }
      video.classList.remove("is-active");
      video.pause();
      if (resetActive && entry.activeStage === stageName) {
        entry.activeStage = null;
      }
    }

    _setCardLayer(entry, layer) {
      if (!entry?.cardRig) {
        return;
      }
      entry.cardRig.dataset.layer = layer;
    }

    async _animateCard(entry, revealDelay, openingVideo, options = {}) {
      const skipVideoGate = Boolean(options.skipVideoGate);
      const normalizedDelay = Math.max(0, typeof revealDelay === "number" ? revealDelay : 0);
      const shouldDelayAfterGate = skipVideoGate || !openingVideo;
      if (!skipVideoGate && openingVideo) {
        await waitForVideoStart(openingVideo, CONFIG.MEDIA_START_TIMEOUT_MS);
        if (CONFIG.STAGE_HANDOFF_DELAY_MS > 0) {
          await sleep(CONFIG.STAGE_HANDOFF_DELAY_MS);
        }
        const revealProgress = clamp(CONFIG.OPENING_REVEAL_PROGRESS, 0.05, 0.95);
        const revealTimeout = Math.max(CONFIG.OPENING_REVEAL_TIMEOUT_MS, normalizedDelay);
        const durationReady = await waitForVideoDuration(openingVideo, CONFIG.MEDIA_START_TIMEOUT_MS);
        const hitProgress = durationReady
          ? await waitForVideoProgress(openingVideo, revealProgress, revealTimeout)
          : false;
        if (!hitProgress && normalizedDelay > 0) {
          await sleep(normalizedDelay);
        }
      }
      if (CONFIG.OPENING_PROMOTION_DELAY_MS > 0) {
        await sleep(CONFIG.OPENING_PROMOTION_DELAY_MS);
      }
      if (shouldDelayAfterGate && normalizedDelay > 0) {
        await sleep(normalizedDelay);
      }
      entry.cardRig.classList.remove("is-hidden");
      this._setCardLayer(entry, "front");
      if (CONFIG.SILHOUETTE_DELAY_MS > 0) {
        await sleep(CONFIG.SILHOUETTE_DELAY_MS);
      }
      await this._tweenCard(entry);
      await this._popBadge(entry);
      await this._animateLevel(entry);
    }

    async _popBadge(entry) {
      const badgeRoot = entry?.badge?.root;
      if (!badgeRoot || badgeRoot.dataset.popComplete === "1") {
        return;
      }
      badgeRoot.dataset.popComplete = "1";
      badgeRoot.classList.add("is-visible");
      badgeRoot.classList.remove("is-stealthed");
      const overshootScale = 1.2;
      const settleScale = 1;
      await new Promise((resolve) =>
        requestAnimationFrame(() => {
          badgeRoot.style.setProperty("--badge-scale", overshootScale.toFixed(2));
          resolve();
        }),
      );
      await sleep(130);
      badgeRoot.style.setProperty("--badge-scale", settleScale.toFixed(3));
      await sleep(90);
    }

    _tweenCard(entry) {
      const metrics = entry.metrics;
      const riseDuration = Math.max(100, CONFIG.CARD_RISE_DURATION_MS);
      const silhouetteDuration = Math.max(50, CONFIG.CARD_SILHOUETTE_DURATION_MS);
      const labelDuration = Math.max(50, CONFIG.CARD_LABEL_FADE_DURATION_MS);
      entry.cardRig.style.setProperty("--card-rise-duration", `${riseDuration}ms`);
      entry.cardRig.style.setProperty("--card-silhouette-duration", `${silhouetteDuration}ms`);
      entry.cardRig.style.setProperty("--card-label-duration", `${labelDuration}ms`);
      entry.cardRig.style.setProperty("--card-scale", metrics.startScale.toFixed(3));
      entry.cardRig.style.setProperty("--card-translateY", `${metrics.startY}px`);
      entry.cardRig.style.setProperty("--silhouette-strength", "1");
      this._setLabelOpacity(entry, 0);
      const hasStar = Boolean(entry.star?.metrics);
      if (hasStar) {
        this._applyStarMetrics(entry);
      }
      return new Promise((resolve) => {
        requestAnimationFrame(() => {
          entry.cardRig.style.setProperty("--card-scale", metrics.targetScale.toFixed(3));
          entry.cardRig.style.setProperty("--card-translateY", `${metrics.targetY}px`);
          entry.cardRig.style.setProperty("--silhouette-strength", "0");
          this._setLabelOpacity(entry, 1);
          if (hasStar) {
            this._setStarScale(entry, entry.star.metrics.targetScale);
          }
        });
        setTimeout(resolve, riseDuration + 50);
      });
    }

    _applyCardState(entry, scale, translateY, silhouetteStrength) {
      entry.cardRig.style.setProperty("--card-scale", scale.toFixed(3));
      entry.cardRig.style.setProperty("--card-translateY", `${translateY.toFixed(1)}px`);
      entry.cardRig.style.setProperty("--silhouette-strength", silhouetteStrength.toFixed(3));
    }

    _setLabelOpacity(entry, value) {
      const clamped = clamp(value, 0, 1);
      if (Math.abs(clamped - entry.labelOpacity) < 0.02) {
        return;
      }
      entry.labelOpacity = clamped;
      entry.labels.style.setProperty("--label-opacity", clamped.toFixed(3));
    }

    async _animateLevel(entry) {
      const numberEl = entry.levelNumber;
      if (!numberEl) {
        return;
      }
      const finalText = entry.levelMeta.finalText;
      if (CONFIG.LEVEL_INITIAL_HOLD_MS > 0) {
        await sleep(CONFIG.LEVEL_INITIAL_HOLD_MS);
      }
      numberEl.textContent = finalText;
      numberEl.classList.add("is-upgraded", "pop");
      await sleep(CONFIG.LEVEL_POP_DURATION_MS);
      numberEl.classList.remove("pop");
    }

    async _fadeAndCleanup(entries) {
      const steps = Math.max(1, CONFIG.FADE_STEPS);
      for (let i = 0; i < steps; i += 1) {
        const remaining = 1 - (i + 1) / steps;
        entries.forEach((entry) => {
          entry.root.style.opacity = remaining.toFixed(3);
          entry.root.dataset.state = "fading";
        });
        await sleep(CONFIG.FRAME_DELAY_MS);
      }
      entries.forEach((entry) => {
        Object.values(entry.videos).forEach((video) => {
          if (!video) {
            return;
          }
          video.pause();
          video.removeAttribute("src");
        });
        entry.root.remove();
      });
    }
  }

  function chunkArray(source, size) {
    const chunks = [];
    for (let i = 0; i < source.length; i += size) {
      chunks.push(source.slice(i, i + size));
    }
    return chunks;
  }

  function buildAnimationPath(...segments) {
    return buildAssetPath(CONFIG.ANIMATION_ROOT, ...segments);
  }

  function buildImagePath(...segments) {
    return buildAssetPath(CONFIG.IMAGES_ROOT, ...segments);
  }

  function buildAssetPath(rootFolder, ...segments) {
    const parts = [CONFIG.ASSETS_ROOT, rootFolder, ...segments]
      .filter((segment) => typeof segment === "string" && segment.length > 0)
      .map((segment) => segment.replace(/^[\\/]+|[\\/]+$/g, ""));
    return parts.join("/");
  }

  function resolveStarAsset(rarityKey, isShiny) {
    if (isShiny) {
      return buildImagePath("star_prismatic.svg");
    }
    const normalized = (rarityKey || "common").toString().toLowerCase();
    const fileName = RARITY_STAR_MAP[normalized] || RARITY_STAR_MAP.common;
    return fileName ? buildImagePath(fileName) : "";
  }

  function resolveBadgeAsset(rarityKey, isShiny) {
    if (isShiny) {
      return buildImagePath("badge_shiny.png");
    }
    const normalized = (rarityKey || "common").toString().trim().toLowerCase();
    const safeRarity = BADGE_RARITIES.includes(normalized) ? normalized : "common";
    return buildImagePath(`badge_${safeRarity}.png`);
  }

  function computeSlotOffsets(count, spacing) {
    const clamped = Math.max(1, Math.min(CONFIG.MAX_VISIBLE, count));
    const layout = SLOT_LAYOUTS[clamped] || SLOT_LAYOUTS[CONFIG.MAX_VISIBLE];
    return (layout || []).slice(0, count).map((unit, order) => ({
      offset: unit * spacing,
      order,
    }));
  }

  function resolveRarityKey(raw) {
    if (!raw) {
      return "common";
    }
    const normalized = raw.toString().trim().toUpperCase();
    return RARITY_KEY_MAP[normalized] || normalized.toLowerCase();
  }

  function formatName(raw) {
    if (!raw) {
      return "Unknown";
    }
    return raw
      .toString()
      .replace(/[\-_]+/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .replace(/\b\w/g, (char) => char.toUpperCase());
  }

  function formatSetName(raw) {
    if (!raw) {
      return "";
    }
    return formatName(raw);
  }

  function resolveLevelMeta(data) {
    const rawLevel = Number.isFinite(Number(data?.level)) ? Number(data.level) : 0;
    const current = Math.max(0, Math.trunc(rawLevel));
    return {
      currentText: String(current),
      finalText: String(current + 1),
    };
  }

  function resolveImageSource(data) {
    const direct = data?.image_path || data?.imagePath || data?.image_url;
    if (direct) {
      return direct.toString().replace(/\\/g, "/");
    }
    const setName = data?.set || data?.set_name || "default";
    const rarity = (data?.rarity || "common").toString().toLowerCase();
    if (data?.image) {
      return `../${setName}/${rarity}/${data.image}`;
    }
    return "";
  }

  function loadImage(img) {
    return new Promise((resolve) => {
      if (!img || !img.src) {
        resolve();
        return;
      }
      if (img.complete && img.naturalWidth > 0) {
        resolve();
        return;
      }
      const done = () => {
        cleanup();
        resolve();
      };
      const cleanup = () => {
        img.removeEventListener("load", done);
        img.removeEventListener("error", done);
      };
      img.addEventListener("load", done);
      img.addEventListener("error", done);
    });
  }

  function setVideoSource(video, src) {
    if (!video) {
      return;
    }
    if (!src) {
      video.removeAttribute("src");
      video.dataset.src = "";
      return;
    }
    const normalized = src.replace(/\\/g, "/");
    let resolved = normalized;
    try {
      resolved = new URL(normalized, OVERLAY_BASE_URL).href;
    } catch (err) {
  function formatSetName(raw) {
    if (!raw) {
      return "";
    }
    return formatName(raw);
  }
      overlayWarn("Unable to resolve video path", normalized, err);
    }
    video.src = resolved;
    try {
      video.dataset.src = resolved;
    } catch (err) {
      overlayWarn("Unable to set dataset src", { resolved, err });
    }
    video.setAttribute("data-src", resolved);
    try {
      video.load();
    } catch (err) {
      overlayWarn("Unable to trigger video load", resolved, err);
    }
    overlayLog("Stage video source set", {
      stage: video.className,
      src: resolved,
    });
  }

  function ensureVideoReady(video) {
    return new Promise((resolve) => {
      if (!video) {
        resolve();
        return;
      }
      if (video.readyState >= 2) {
        resolve();
        return;
      }
      const cleanup = () => {
        video.removeEventListener("loadeddata", cleanup);
        video.removeEventListener("error", cleanup);
        resolve();
      };
      video.addEventListener("loadeddata", cleanup);
      video.addEventListener("error", cleanup);
    });
  }

  async function safePlay(video) {
    if (!video) {
      return;
    }
    try {
      await video.play();
    } catch (err) {
      console.warn("[GachaOverlay] Unable to autoplay video", err);
    }
  }

  function waitForVideoStart(video, timeout) {
    return new Promise((resolve) => {
      if (!video) {
        resolve(false);
        return;
      }
      if (!video.paused && video.currentTime > 0) {
        resolve(true);
        return;
      }
      let timer = null;
      const cleanup = () => {
        video.removeEventListener("playing", onStart);
        video.removeEventListener("loadeddata", onStart);
        if (timer) {
          clearTimeout(timer);
        }
      };
      const onStart = () => {
        cleanup();
        overlayLog("Video started", { src: video.currentSrc || video.src });
        resolve(true);
      };
      if (timeout > 0) {
        timer = setTimeout(() => {
          cleanup();
          overlayWarn("Video failed to start before timeout", { src: video.currentSrc || video.src, timeout });
          resolve(false);
        }, timeout);
      }
      video.addEventListener("playing", onStart, { once: true });
      video.addEventListener("loadeddata", onStart, { once: true });
    });
  }

  function waitForVideoDuration(video, timeout) {
    return new Promise((resolve) => {
      if (!video) {
        resolve(false);
        return;
      }
      if (Number.isFinite(video.duration) && video.duration > 0) {
        resolve(true);
        return;
      }
      let timer = null;
      const cleanup = () => {
        video.removeEventListener("loadedmetadata", onMetadata);
        video.removeEventListener("durationchange", onMetadata);
        if (timer) {
          clearTimeout(timer);
        }
      };
      const onMetadata = () => {
        if (Number.isFinite(video.duration) && video.duration > 0) {
          cleanup();
          resolve(true);
        }
      };
      video.addEventListener("loadedmetadata", onMetadata, { once: true });
      video.addEventListener("durationchange", onMetadata);
      if (timeout > 0) {
        timer = setTimeout(() => {
          cleanup();
          resolve(false);
        }, timeout);
      }
    });
  }

  function waitForVideoEnd(video, timeout) {
    return new Promise((resolve) => {
      if (!video) {
        resolve();
        return;
      }
      let timer = null;
      const cleanup = () => {
        video.removeEventListener("ended", onComplete);
        video.removeEventListener("error", onComplete);
        if (timer) {
          clearTimeout(timer);
        }
      };
      const onComplete = () => {
        cleanup();
        overlayLog("Video ended", { src: video.currentSrc || video.src });
        resolve();
      };
      if (timeout > 0) {
        timer = setTimeout(onComplete, timeout);
      }
      video.addEventListener("ended", onComplete, { once: true });
      video.addEventListener("error", onComplete, { once: true });
    });
  }

  function waitForVideoProgress(video, ratio, timeout) {
    return new Promise((resolve) => {
      if (!video) {
        resolve(false);
        return;
      }
      const target = clamp(ratio, 0, 0.99);
      let timer = null;
      let poller = null;
      const cleanup = () => {
        video.removeEventListener("timeupdate", onUpdate);
        video.removeEventListener("ended", onEnded);
        if (timer) {
          clearTimeout(timer);
        }
        if (poller) {
          clearInterval(poller);
        }
      };
      const checkProgress = () => {
        const duration = video.duration;
        if (!Number.isFinite(duration) || duration <= 0) {
          return false;
        }
        const currentRatio = duration ? video.currentTime / duration : 0;
        if (currentRatio >= target) {
          cleanup();
          resolve(true);
          return true;
        }
        return false;
      };
      const onUpdate = () => {
        checkProgress();
      };
      const onEnded = () => {
        cleanup();
        resolve(true);
      };
      video.addEventListener("timeupdate", onUpdate);
      video.addEventListener("ended", onEnded, { once: true });
      if (!checkProgress()) {
        poller = setInterval(checkProgress, 33);
        if (timeout > 0) {
          timer = setTimeout(() => {
            cleanup();
            resolve(false);
          }, timeout);
        }
      }
    });
  }

  function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  function applyJitter(base, ratio) {
    const clampedRatio = clamp(ratio, 0, 0.95);
    const delta = (Math.random() * 2 - 1) * clampedRatio;
    const jittered = base * (1 + delta);
    return Math.max(1, jittered);
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, Math.max(0, ms)));
  }

  const stageEl = document.getElementById("stage");
  const animator = stageEl ? new BrowserGachaAnimator(stageEl) : null;

  window.runPulls = (pulls, meta = {}) => {
    if (!animator) {
      return Promise.resolve();
    }
    const items = Array.isArray(pulls) ? pulls : [];
    const metadata = meta && typeof meta === "object" ? meta : {};
    return animator.enqueue(items, metadata);
  };

  function clearStage() {
    if (animator) {
      animator.clear();
      return;
    }
    if (stageEl) {
      stageEl.innerHTML = "";
    }
  }

  function handleSocketPayload(raw, socketApi) {
    if (!raw) {
      return;
    }
    let data;
    try {
      data = JSON.parse(raw);
    } catch (err) {
      console.warn("[GachaOverlay] Received malformed payload", err);
      return;
    }
    if (!data || typeof data !== "object") {
      return;
    }
    switch (data.type) {
      case "gacha_pulls": {
        const payload = data.payload || data.data || {};
        let pulls = [];
        if (Array.isArray(payload.pulls)) {
          pulls = payload.pulls;
        } else if (Array.isArray(data.pulls)) {
          pulls = data.pulls;
        }
        const candidates = [
          payload.displayName,
          payload.display_name,
          payload.userDisplayName,
          payload.user_name,
          payload.user?.displayName,
          payload.user?.display_name,
          payload.user,
        ];
        let displayName = "";
        for (const candidate of candidates) {
          if (typeof candidate === "string" && candidate.trim().length) {
            displayName = candidate.trim();
            break;
          }
        }
        const rawTotal = Number(payload.totalPulls ?? payload.total_pulls);
        const normalizedTotal = Number.isFinite(rawTotal) && rawTotal > 0 ? rawTotal : pulls.length;
        let userId = "";
        if (typeof payload.userId === "string" && payload.userId.trim().length) {
          userId = payload.userId.trim();
        } else if (typeof payload.user_id === "string" && payload.user_id.trim().length) {
          userId = payload.user_id.trim();
        } else if (payload.user && typeof payload.user.id === "string" && payload.user.id.trim().length) {
          userId = payload.user.id.trim();
        }
        const setNameCandidates = [
          payload.setName,
          payload.set_name,
          payload.set,
          data.setName,
          data.set_name,
          data.set,
        ];
        let setName = "";
        for (const candidate of setNameCandidates) {
          if (typeof candidate === "string" && candidate.trim().length) {
            setName = candidate.trim();
            break;
          }
        }
        const meta = {
          totalPulls: normalizedTotal,
          displayName,
          userId,
          setName: formatSetName(setName),
        };
        if (pulls.length) {
          window.runPulls(pulls, meta);
        } else {
          clearStage();
        }
        break;
      }
      case "clear": {
        clearStage();
        break;
      }
      case "ping": {
        socketApi?.send({ type: "pong", ts: data.ts });
        break;
      }
      default:
        break;
    }
  }

  function initializeOverlayConnection() {
    if (!("WebSocket" in window)) {
      console.warn("[GachaOverlay] WebSocket is not supported in this browser context.");
      return null;
    }
    const params = new URLSearchParams(window.location.search);
    const config = buildOverlayConfig(params);
    const endpoint = config.url || buildOverlayUrl(config);
    if (!endpoint) {
      console.warn("[GachaOverlay] Overlay endpoint is undefined; skipping socket connection.");
      return null;
    }
    return createOverlaySocket(endpoint, config.token);
  }

  function buildOverlayConfig(params) {
    const host = (params.get("wsHost") || defaultOverlayHost()).trim() || defaultOverlayHost();
    const portParam = params.get("wsPort");
    const secure = parseBooleanParam(
      params.get("wsSecure"),
      window.location.protocol === "https:"
    );
    const rawPath = params.get("wsPath")?.trim();
    const path = normalizeOverlayPath(rawPath);
    return {
      url: params.get("wsUrl")?.trim() || "",
      host,
      port: portParam && !Number.isNaN(Number(portParam)) ? Number(portParam) : 17890,
      secure,
      path,
      token: params.get("wsToken")?.trim() || "",
    };
  }

  function buildOverlayUrl(config) {
    const protocol = config.secure ? "wss" : "ws";
    const portSegment = config.port ? `:${config.port}` : "";
    return `${protocol}://${config.host}${portSegment}${config.path}`;
  }

  function normalizeOverlayPath(rawPath) {
    const fallback = "/gacha";
    if (!rawPath) {
      return fallback;
    }
    return rawPath.startsWith("/") ? rawPath : `/${rawPath}`;
  }

  function defaultOverlayHost() {
    return window.location.hostname || "127.0.0.1";
  }

  function parseBooleanParam(raw, fallback) {
    if (raw === null || raw === undefined || raw === "") {
      return fallback;
    }
    const normalized = raw.toString().trim().toLowerCase();
    return normalized === "1" || normalized === "true" || normalized === "yes";
  }

  function createOverlaySocket(url, token) {
    let socket = null;
    let retryDelay = 1000;
    const maxDelay = 10000;

    const api = {
      send(payload) {
        if (!socket || socket.readyState !== WebSocket.OPEN) {
          return;
        }
        try {
          socket.send(JSON.stringify(payload));
        } catch (err) {
          console.warn("[GachaOverlay] Failed to send message to host", err);
        }
      },
    };

    const connect = () => {
      try {
        socket = new WebSocket(url);
      } catch (err) {
        scheduleReconnect(err);
        return;
      }
      socket.addEventListener("open", () => {
        retryDelay = 1000;
        api.send({ type: "ready", version: 1, token: token || undefined, overlay: "gacha" });
      });
      socket.addEventListener("message", (event) => handleSocketPayload(event.data, api));
      socket.addEventListener("error", (err) => {
        console.warn("[GachaOverlay] Socket error", err);
        socket?.close();
      });
      socket.addEventListener("close", (evt) => {
        scheduleReconnect(evt);
      });
    };

    const scheduleReconnect = (reason) => {
      if (reason) {
        console.warn("[GachaOverlay] Socket closed, retrying", reason);
      }
      const delay = retryDelay;
      retryDelay = Math.min(maxDelay, retryDelay * 1.5);
      setTimeout(connect, delay);
    };

    connect();
    return api;
  }

  const overlaySocket = initializeOverlayConnection();
})();
