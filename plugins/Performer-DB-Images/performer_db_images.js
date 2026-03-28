(() => {
  "use strict";

  const GALLERY_ID = "performer-db-images__gallery";
  const PREVIEW_ID = "performer-db-images__preview";
  const SETTINGS_STORAGE_KEY = "performer_db_images_settings";
  const PAGE_SIZE_OPTIONS = [5, 10, 20, 30, 50, 100];
  const DEFAULT_SETTINGS = {
    maxImages: 50,
    pageSize: 10,
  };

  let currentGalleryState = null;
  let previewKeydownHandler = null;

  async function gqlFull(query, variables = {}) {
    const apiKey = localStorage.getItem("apiKey") || "";
    const headers = {
      "Content-Type": "application/json",
    };
    if (apiKey) {
      headers.ApiKey = apiKey;
      headers.Authorization = `Bearer ${apiKey}`;
    }

    const response = await fetch(localStorage.getItem("apiEndpoint") || "/graphql", {
      method: "POST",
      headers,
      credentials: "include",
      body: JSON.stringify({ query, variables }),
    });

    const text = await response.text();
    let data = {};
    try {
      data = text ? JSON.parse(text) : {};
    } catch {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      throw new Error("GraphQL response is not valid JSON");
    }

    if (!response.ok && !data?.errors?.length) {
      throw new Error(`HTTP ${response.status}`);
    }

    return data;
  }

  async function runPluginOperation(args) {
    const result = await gqlFull(
      `mutation RunPluginOperation($plugin_id: ID!, $args: Map) {
        runPluginOperation(plugin_id: $plugin_id, args: $args)
      }`,
      {
        plugin_id: "performer_db_images",
        args,
      }
    );

    if (result?.errors?.length) {
      throw new Error(result.errors[0]?.message || "runPluginOperation failed");
    }

    const raw = result?.data?.runPluginOperation;
    const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
    return parsed?.output || parsed || {};
  }

  function loadSettings() {
    try {
      const raw = localStorage.getItem(SETTINGS_STORAGE_KEY);
      const parsed = raw ? JSON.parse(raw) : {};
      const pageSize = Number(parsed?.pageSize);
      return {
        ...DEFAULT_SETTINGS,
        ...(Number.isFinite(pageSize) && pageSize > 0 ? { pageSize } : {}),
      };
    } catch {
      return { ...DEFAULT_SETTINGS };
    }
  }

  function saveSettings(settings) {
    try {
      localStorage.setItem(
        SETTINGS_STORAGE_KEY,
        JSON.stringify({
          pageSize: Number(settings?.pageSize) || DEFAULT_SETTINGS.pageSize,
        })
      );
    } catch {
      // Ignore localStorage failures and keep runtime-only settings.
    }
  }

  async function setPerformerImage(performerId, imageUrl) {
    const result = await gqlFull(
      `mutation PerformerUpdate($input: PerformerUpdateInput!) {
        performerUpdate(input: $input) {
          id
          image_path
        }
      }`,
      {
        input: {
          id: performerId,
          image: imageUrl,
        },
      }
    );

    if (result?.errors?.length) {
      throw new Error(result.errors[0]?.message || "performerUpdate failed");
    }

    return result?.data?.performerUpdate || null;
  }

  function normalizeUrl(url) {
    return String(url || "").trim().replace(/\/+$/, "");
  }

  function getBaseUrl(endpoint) {
    const value = normalizeUrl(endpoint);
    return value.toLowerCase().endsWith("/graphql") ? value.slice(0, -8) : value;
  }

  function isTpdbEndpoint(endpoint) {
    const value = normalizeUrl(endpoint).toLowerCase();
    return value.includes("theporndb.net") || value.includes("tpdb");
  }

  function getSourceLabel(endpoint) {
    try {
      return new URL(getBaseUrl(endpoint)).host;
    } catch {
      return endpoint;
    }
  }

  function dedupeAndLimitImages(images, maxImages) {
    const seen = new Set();
    const result = [];

    for (const image of images || []) {
      const key = normalizeUrl(image?.url);
      if (!key || seen.has(key)) continue;
      seen.add(key);
      result.push(image);
      if (result.length >= maxImages) break;
    }

    return result;
  }

  function closeGallery() {
    currentGalleryState = null;
    document.getElementById(GALLERY_ID)?.remove();
  }

  function closePreview() {
    document.getElementById(PREVIEW_ID)?.remove();
    if (previewKeydownHandler) {
      document.removeEventListener("keydown", previewKeydownHandler);
      previewKeydownHandler = null;
    }
  }

  function showPreview(images, startIndex, performerId) {
    closePreview();
    if (!images?.length) return;

    let index = startIndex;
    const overlay = document.createElement("div");
    overlay.id = PREVIEW_ID;
    overlay.className = "performer-db-images__preview";

    const image = document.createElement("img");
    image.className = "performer-db-images__preview-img";

    const stage = document.createElement("div");
    stage.className = "performer-db-images__preview-stage";

    const meta = document.createElement("div");
    meta.className = "performer-db-images__preview-meta";

    const leftArrow = document.createElement("div");
    leftArrow.className = "performer-db-images__preview-arrow is-left";
    leftArrow.textContent = "‹";

    const rightArrow = document.createElement("div");
    rightArrow.className = "performer-db-images__preview-arrow is-right";
    rightArrow.textContent = "›";

    const openBtn = document.createElement("a");
    openBtn.className = "performer-db-images__preview-btn performer-db-images__link";
    openBtn.target = "_blank";
    openBtn.rel = "noopener noreferrer";
    openBtn.textContent = "新窗口打开";

    const setImageBtn = document.createElement("button");
    setImageBtn.className = "performer-db-images__preview-btn";
    setImageBtn.textContent = "设为演员图片";
    setImageBtn.classList.toggle("performer-db-images__is-hidden", !performerId);

    const closeBtn = document.createElement("button");
    closeBtn.className = "performer-db-images__preview-btn";
    closeBtn.textContent = "关闭";

    const bar = document.createElement("div");
    bar.className = "performer-db-images__preview-bar";
    bar.append(meta);

    const topbar = document.createElement("div");
    topbar.className = "performer-db-images__preview-topbar";

    function render() {
      const current = images[index];
      image.src = current.url;
      image.alt = `${current.source || "来源图片"} ${index + 1}`;
      openBtn.href = current.url;
      meta.textContent = `${index + 1} / ${images.length} · ${current.source}`;
      if (performerId) {
        setImageBtn.disabled = false;
        setImageBtn.textContent = "设为演员图片";
      }
    }

    function showPrev() {
      index = (index - 1 + images.length) % images.length;
      render();
    }

    function showNext() {
      index = (index + 1) % images.length;
      render();
    }

    setImageBtn.onclick = async (event) => {
      event.stopPropagation();
      if (!performerId) return;

      const current = images[index];
      if (!current?.url) return;

      setImageBtn.disabled = true;
      setImageBtn.textContent = "保存中...";

      try {
        await setPerformerImage(performerId, current.url);
        setImageBtn.textContent = "已保存";
      } catch (error) {
        setImageBtn.disabled = false;
        setImageBtn.textContent = "设为演员图片";
        alert(`设置演员图片失败：${error?.message || error}`);
      }
    };

    closeBtn.onclick = closePreview;

    function isInBrowseBand(clientY) {
      const top = window.innerHeight / 6;
      const bottom = window.innerHeight * 5 / 6;
      return clientY >= top && clientY <= bottom;
    }

    function setActiveSide(clientX, clientY) {
      overlay.classList.remove("is-left-active", "is-right-active");
      if (!isInBrowseBand(clientY)) {
        return;
      }
      if (clientX < window.innerWidth / 2) {
        overlay.classList.add("is-left-active");
      } else {
        overlay.classList.add("is-right-active");
      }
    }

    overlay.onmousemove = (event) => {
      setActiveSide(event.clientX, event.clientY);
    };
    overlay.onmouseleave = () => {
      overlay.classList.remove("is-left-active", "is-right-active");
    };

    overlay.onclick = (event) => {
      if (event.defaultPrevented || event.button !== 0) return;

      const target = event.target;
      if (
        target instanceof Element &&
        (topbar.contains(target) || bar.contains(target))
      ) {
        return;
      }

      if (!isInBrowseBand(event.clientY)) {
        closePreview();
      } else if (event.clientX < window.innerWidth / 2) {
        showPrev();
      } else {
        showNext();
      }
    };

    previewKeydownHandler = (event) => {
      if (event.key === "ArrowLeft") showPrev();
      if (event.key === "ArrowRight") showNext();
      if (event.key === "Escape") closePreview();
    };

    document.addEventListener("keydown", previewKeydownHandler);

    stage.append(leftArrow, image, rightArrow);
    topbar.append(setImageBtn, openBtn, closeBtn);
    overlay.append(topbar, stage, bar);
    document.body.appendChild(overlay);
    render();
  }

  function buildSourceKey(entry) {
    return [entry.sourceType, normalizeUrl(entry.endpoint), normalizeUrl(entry.stashId)].join("::");
  }

  function prepareSources(performer) {
    const seen = new Set();
    const rawSources = (performer?.stash_ids || [])
      .map((stashId) => {
        const endpoint = normalizeUrl(stashId?.endpoint);
        const stashIdValue = normalizeUrl(stashId?.stash_id);
        if (!endpoint || !stashIdValue) return null;

        return {
          endpoint,
          stashId: stashIdValue,
          sourceType: isTpdbEndpoint(endpoint) ? "theporndb" : "stashbox",
          sourceName: getSourceLabel(endpoint),
        };
      })
      .filter(Boolean)
      .map((entry) => {
        const key = buildSourceKey(entry);
        return {
          ...entry,
          key,
        };
      })
      .filter((entry) => {
        if (seen.has(entry.key)) return false;
        seen.add(entry.key);
        return true;
      });

    const labelCounts = rawSources.reduce((acc, entry) => {
      const label = entry.sourceName || entry.sourceType;
      acc[label] = (acc[label] || 0) + 1;
      return acc;
    }, {});

    return rawSources.map((entry) => {
      const baseLabel = entry.sourceName || entry.sourceType;
      const label =
        labelCounts[baseLabel] > 1
          ? `${baseLabel} · ${entry.stashId.slice(0, 8)}`
          : baseLabel;
      return {
        ...entry,
        label,
      };
    });
  }

  function buildPerformerLink(source) {
    const base = getBaseUrl(source.endpoint);
    if (!base || !source.stashId) return "";
    return `${base}/performers/${source.stashId}`;
  }

  function formatSourceError(sourceType, message) {
    const finalMessage = String(message || "").trim() || "GraphQL request failed";
    return `${sourceType}: ${finalMessage}`;
  }

  async function scrapeSinglePerformerImages(source, maxImages) {
    const result = await gqlFull(
      `query ScrapeSinglePerformer(
        $source: ScraperSourceInput!
        $input: ScrapeSinglePerformerInput!
      ) {
        scrapeSinglePerformer(source: $source, input: $input) {
          remote_site_id
          images
        }
      }`,
      {
        source: {
          stash_box_endpoint: source.endpoint,
        },
        input: {
          query: source.stashId,
        },
      }
    );

    if (result?.errors?.length) {
      throw new Error(
        formatSourceError(source.sourceName || source.sourceType, result.errors[0]?.message)
      );
    }

    const performers = result?.data?.scrapeSinglePerformer || [];
    const selected =
      performers.find(
        (performer) =>
          String(performer?.remote_site_id || "").trim() === source.stashId
      ) || performers[0];

    return dedupeAndLimitImages(
      (selected?.images || [])
        .map((url) => String(url || "").trim())
        .filter(Boolean)
        .map((url) => ({
          url,
          source: source.label,
        })),
      maxImages
    );
  }

  async function loadTpdbExactImages(source, maxImages) {
    const result = await runPluginOperation({
      mode: "tpdbExactImages",
      entry: {
        sourceName: source.label,
        stashId: source.stashId,
      },
    });

    if (!result?.success && !(result?.images || []).length) {
      throw new Error(
        result?.error || formatSourceError(source.sourceName || source.sourceType, "TPDB exact lookup failed")
      );
    }

    return dedupeAndLimitImages(result?.images || [], maxImages);
  }

  function setSourceButtonText(button, source, cacheEntry) {
    if (!button) return;
    let suffix = "";
    if (cacheEntry?.status === "loaded" || cacheEntry?.status === "empty") {
      suffix = ` (${cacheEntry.images.length})`;
    } else if (cacheEntry?.status === "loading") {
      suffix = " (...)";
    } else if (cacheEntry?.status === "error") {
      suffix = " (!)";
    }
    button.textContent = `${source.label}${suffix}`;
  }

  function updateSourceButtons(state) {
    for (const source of state.sources) {
      const button = state.sourceButtons.get(source.key);
      if (!button) continue;
      button.classList.toggle("is-active", source.key === state.activeSourceKey);
      setSourceButtonText(button, source, state.cache.get(source.key));
    }
  }

  function renderGalleryBody(state) {
    const source = state.sources.find((item) => item.key === state.activeSourceKey);
    if (!source) return;

    const cacheEntry = state.cache.get(source.key);
    const externalLink = buildPerformerLink(source);
    const pageSize = Math.max(1, Number(state.settings.pageSize) || 10);

    state.elements.sourceMeta.textContent = `${source.label} · stash id ${source.stashId}`;
    state.elements.openSourceLink.href = externalLink || "#";
    state.elements.openSourceLink.classList.toggle("performer-db-images__is-hidden", !externalLink);

    state.elements.content.innerHTML = "";

    if (!cacheEntry || cacheEntry.status === "loading") {
      const loading = document.createElement("div");
      loading.className = "performer-db-images__status";
      loading.textContent = `正在从 ${source.label} 加载图片...`;
      state.elements.content.appendChild(loading);
      return;
    }

    if (cacheEntry.status === "error") {
      const error = document.createElement("div");
      error.className = "performer-db-images__empty";
      error.textContent = cacheEntry.error || `从 ${source.label} 加载图片失败。`;
      state.elements.content.appendChild(error);
      return;
    }

    if (!cacheEntry.images.length) {
      const empty = document.createElement("div");
      empty.className = "performer-db-images__empty";
      empty.textContent = `${source.label} 没有返回可浏览图片。`;
      state.elements.content.appendChild(empty);
      return;
    }

    const grid = document.createElement("div");
    grid.className = "performer-db-images__grid";
    const totalImages = cacheEntry.images.length;
    const totalPages = Math.max(1, Math.ceil(totalImages / pageSize));
    const currentPage = Math.min(
      totalPages,
      Math.max(1, state.pageBySource.get(source.key) || 1)
    );
    const pageStart = (currentPage - 1) * pageSize;
    const pageImages = cacheEntry.images.slice(pageStart, pageStart + pageSize);

    state.pageBySource.set(source.key, currentPage);

    pageImages.forEach((image, index) => {
      const card = document.createElement("div");
      card.className = "performer-db-images__card";
      card.onclick = () => showPreview(cacheEntry.images, pageStart + index, state.performerId);

      const thumbWrap = document.createElement("div");
      thumbWrap.className = "performer-db-images__thumb-wrap";

      const thumb = document.createElement("img");
      thumb.className = "performer-db-images__thumb";
      thumb.src = image.url;
      thumb.loading = "lazy";
      thumb.decoding = "async";
      thumb.alt = `${state.performerName} ${index + 1}`;

      thumbWrap.appendChild(thumb);

      const footer = document.createElement("div");
      footer.className = "performer-db-images__footer";

      const hint = document.createElement("div");
      hint.className = "performer-db-images__hint";
      hint.textContent = `第 ${index + 1} 张`;

      const link = document.createElement("a");
      link.className = "performer-db-images__link";
      link.href = image.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "打开";
      link.onclick = (event) => event.stopPropagation();

      footer.append(hint, link);
      card.append(thumbWrap, footer);
      grid.appendChild(card);
    });

    state.elements.content.appendChild(grid);

    if (totalPages > 1) {
      const pagination = document.createElement("div");
      pagination.className = "performer-db-images__pagination";

      const prevBtn = document.createElement("button");
      prevBtn.type = "button";
      prevBtn.className = "performer-db-images__pagination-btn";
      prevBtn.textContent = "上一页";
      prevBtn.disabled = currentPage <= 1;
      prevBtn.onclick = () => {
        if (currentPage <= 1) return;
        state.pageBySource.set(source.key, currentPage - 1);
        renderGalleryBody(state);
      };

      const info = document.createElement("div");
      info.className = "performer-db-images__pagination-info";
      info.textContent = `第 ${currentPage} / ${totalPages} 页 · 共 ${totalImages} 张`;

      const nextBtn = document.createElement("button");
      nextBtn.type = "button";
      nextBtn.className = "performer-db-images__pagination-btn";
      nextBtn.textContent = "下一页";
      nextBtn.disabled = currentPage >= totalPages;
      nextBtn.onclick = () => {
        if (currentPage >= totalPages) return;
        state.pageBySource.set(source.key, currentPage + 1);
        renderGalleryBody(state);
      };

      pagination.append(prevBtn, info, nextBtn);
      state.elements.content.appendChild(pagination);
    }
  }

  async function fetchSourceImages(state, source) {
    const images = await scrapeSinglePerformerImages(source, state.settings.maxImages);
    if (source.sourceType === "theporndb" && !images.length) {
      return loadTpdbExactImages(source, state.settings.maxImages);
    }
    return images;
  }

  async function activateSource(state, sourceKey) {
    const source = state.sources.find((item) => item.key === sourceKey);
    if (!source) return;

    state.activeSourceKey = source.key;
    updateSourceButtons(state);

    let cacheEntry = state.cache.get(source.key);
    if (!cacheEntry) {
      cacheEntry = {
        status: "loading",
        images: [],
        error: null,
        promise: null,
      };
      state.cache.set(source.key, cacheEntry);
    }

    renderGalleryBody(state);

    if (cacheEntry.status === "loaded" || cacheEntry.status === "empty" || cacheEntry.status === "error") {
      return;
    }

    if (!cacheEntry.promise) {
      cacheEntry.status = "loading";
      cacheEntry.promise = fetchSourceImages(state, source)
        .then((images) => {
          cacheEntry.images = images;
          cacheEntry.error = null;
          cacheEntry.status = images.length ? "loaded" : "empty";
        })
        .catch((error) => {
          cacheEntry.images = [];
          cacheEntry.error = error?.message || `从 ${source.label} 加载图片失败。`;
          cacheEntry.status = "error";
        })
        .finally(() => {
          cacheEntry.promise = null;
        });
    }

    await cacheEntry.promise;

    if (currentGalleryState === state && state.activeSourceKey === source.key) {
      updateSourceButtons(state);
      renderGalleryBody(state);
    } else {
      updateSourceButtons(state);
    }
  }

  function showGallery(performerId, performerName, sources, settings) {
    closeGallery();
    closePreview();

    const overlay = document.createElement("div");
    overlay.id = GALLERY_ID;
    overlay.className = "performer-db-images__overlay";

    const dialog = document.createElement("div");
    dialog.className = "performer-db-images__dialog";

    const header = document.createElement("div");
    header.className = "performer-db-images__header";

    const titleWrap = document.createElement("div");
    const title = document.createElement("h2");
    title.className = "performer-db-images__title";
    title.textContent = `${performerName} · 外部图片`;

    const meta = document.createElement("div");
    meta.className = "performer-db-images__meta";
    meta.textContent = sources.length
      ? `${sources.length} 个来源，按来源单独加载`
      : "没有可用的 StashBox 来源";

    titleWrap.append(title, meta);

    const closeBtn = document.createElement("button");
    closeBtn.className = "performer-db-images__close";
    closeBtn.textContent = "关闭";
    closeBtn.onclick = closeGallery;

    header.append(titleWrap, closeBtn);
    dialog.appendChild(header);

    const content = document.createElement("div");
    const sourceMeta = document.createElement("div");
    sourceMeta.className = "performer-db-images__source-meta";
    const sourceActions = document.createElement("div");
    sourceActions.className = "performer-db-images__source-actions";

    const openSourceLink = document.createElement("a");
    openSourceLink.className = "performer-db-images__link";
    openSourceLink.target = "_blank";
    openSourceLink.rel = "noopener noreferrer";
    openSourceLink.textContent = "打开来源页";

    const pageSizeWrap = document.createElement("label");
    pageSizeWrap.className = "performer-db-images__page-size";
    pageSizeWrap.textContent = "每页";

    const pageSizeSelect = document.createElement("select");
    pageSizeSelect.className = "performer-db-images__page-size-select";
    for (const value of PAGE_SIZE_OPTIONS) {
      const option = document.createElement("option");
      option.value = String(value);
      option.textContent = `${value} 张`;
      if (Number(settings.pageSize) === value) {
        option.selected = true;
      }
      pageSizeSelect.appendChild(option);
    }
    pageSizeWrap.appendChild(pageSizeSelect);
    sourceActions.append(pageSizeWrap, openSourceLink);

    if (!sources.length) {
      const empty = document.createElement("div");
      empty.className = "performer-db-images__empty";
      empty.textContent = "当前演员没有可用的 StashBox 外部 ID。";
      dialog.appendChild(empty);
    } else {
      const sourceBar = document.createElement("div");
      sourceBar.className = "performer-db-images__source-bar";

      const sourceSummary = document.createElement("div");
      sourceSummary.className = "performer-db-images__source-summary";
      sourceSummary.append(sourceMeta, sourceActions);

      dialog.append(sourceBar, sourceSummary, content);

      const state = {
        performerId,
        performerName,
        settings,
        sources,
        activeSourceKey: sources[0].key,
        cache: new Map(),
        pageBySource: new Map(),
        sourceButtons: new Map(),
        elements: {
          content,
          sourceMeta,
          openSourceLink,
        },
      };
      currentGalleryState = state;

      pageSizeSelect.onchange = () => {
        const nextPageSize = Number(pageSizeSelect.value) || DEFAULT_SETTINGS.pageSize;
        state.settings.pageSize = nextPageSize;
        saveSettings(state.settings);
        renderGalleryBody(state);
      };

      sources.forEach((source) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "performer-db-images__source-btn";
        button.onclick = () => {
          activateSource(state, source.key).catch((error) => {
            console.error("[performer_db_images] Source activation failed:", error);
          });
        };
        state.sourceButtons.set(source.key, button);
        sourceBar.appendChild(button);
      });

      updateSourceButtons(state);
      activateSource(state, sources[0].key).catch((error) => {
        console.error("[performer_db_images] Initial source load failed:", error);
      });
    }

    overlay.onclick = (event) => {
      if (event.target === overlay) closeGallery();
    };

    dialog.onclick = (event) => event.stopPropagation();
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);
  }

  function PerformerDbImagesButton(props) {
    const React = window.PluginApi.React;
    const performer = props?.performer;
    const [loading, setLoading] = React.useState(false);

    if (!performer) {
      return null;
    }

    return React.createElement(
      "div",
      { className: "performer-db-images__action" },
      React.createElement(
        "button",
        {
          className: "btn btn-secondary performer-db-images__button",
          type: "button",
          disabled: loading,
          onClick: async () => {
            try {
              setLoading(true);
              showGallery(
                performer.id,
                performer.name || "Performer",
                prepareSources(performer),
                loadSettings()
              );
            } catch (error) {
              console.error("[performer_db_images] Failed to open gallery:", error);
              alert(`加载图片失败：${error.message}`);
            } finally {
              setLoading(false);
            }
          },
        },
        loading ? "加载中..." : "DB 图片"
      )
    );
  }

  function init() {
    if (!window.PluginApi?.React || !window.PluginApi?.patch?.after) {
      return;
    }

    const React = window.PluginApi.React;
    window.PluginApi.patch.after("PerformerDetailsPanel", (props, _context, result) => {
      if (!props?.performer) {
        return result;
      }

      return React.createElement(
        React.Fragment,
        null,
        result,
        React.createElement(PerformerDbImagesButton, { performer: props.performer })
      );
    });

    if (window.PluginApi?.Event?.addEventListener) {
      window.PluginApi.Event.addEventListener("stash:location", () => {
        closeGallery();
        closePreview();
      });
    }
  }

  init();
})();
