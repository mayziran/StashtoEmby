(() => {
  "use strict";

  // ═══════════════════════════════════════════════════════════
  // 常量定义
  // ═══════════════════════════════════════════════════════════

  const PLUGIN_ID = "open_in_emby";
  const ICON_URL = "https://cdn.jsdelivr.net/gh/lige47/QuanX-icon-rule@main/icon/04ProxySoft/emby.png";

  const TYPE_PATTERNS = {
    scene: /\/scenes\/(\d+)/,
    performer: /\/performers\/(\d+)/,
    studio: /\/studios\/(\d+)/
  };

  const EMBY_TYPE_MAP = {
    scene: "Movie",
    performer: "Person",
    studio: "BoxSet"
  };

  // ═══════════════════════════════════════════════════════════
  // 模块 1: 按钮管理（UI 层）
  // ═══════════════════════════════════════════════════════════

  let cachedIcon = null;

  function getIconNode() {
    if (cachedIcon) return cachedIcon.cloneNode(true);

    const img = document.createElement("img");
    img.src = ICON_URL;
    img.style.cssText = "display:block;width:1.2em;height:1.2em;";

    img.onload = () => { cachedIcon = img.cloneNode(true); };

    img.onerror = () => {
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", "0 0 512 512");
      svg.style.cssText = "display:block;width:1.2em;height:1.2em;";
      svg.innerHTML = `<circle cx="256" cy="256" r="200" fill="#52B54B"/><text x="256" y="320" font-size="200" text-anchor="middle" fill="white" font-weight="bold">E</text>`;
      cachedIcon = svg;
      img.replaceWith(svg.cloneNode(true));
    };

    return img;
  }

  function initCSS() {
    if (document.getElementById("open-in-emby-css")) return;

    const style = document.createElement("style");
    style.id = "open-in-emby-css";
    style.textContent = `
      .open-in-emby-btn {
        background: none !important;
        border: none !important;
        padding: 0 !important;
        cursor: pointer;
        display: inline-flex;
        align-items: center;
        justify-content: center;
      }
      .open-in-emby-btn:hover {
        background: none !important;
      }
      .open-in-emby-btn img,
      .open-in-emby-btn svg {
        display: block;
        width: 1.2em;
        height: 1.2em;
        transition: opacity 0.2s;
      }
      .open-in-emby-btn:hover img,
      .open-in-emby-btn:hover svg {
        opacity: 0.7;
      }
    `;
    document.head.appendChild(style);
  }

  function createEmbyButton(type, id) {
    const btn = document.createElement("button");
    btn.className = "open-in-emby-btn";
    btn.appendChild(getIconNode());

    btn.onclick = async () => {
      try {
        const settings = await getPluginSettings();
        if (!settings.embyServer || !settings.embyInternalServer || !settings.embyApiKey) {
          throw new Error("请先配置 Emby 服务器地址、内网地址和 API Key");
        }

        const data = await gql(`mutation RunPluginOperation($plugin_id: ID!, $args: Map) { runPluginOperation(plugin_id: $plugin_id, args: $args) }`, {
          plugin_id: PLUGIN_ID,
          args: {
            embyServer: settings.embyServer,
            embyInternalServer: settings.embyInternalServer,
            embyApiKey: settings.embyApiKey,
            stash_id: id.toString(),
            includeItemTypes: EMBY_TYPE_MAP[type] || 'Movie',
          },
        });

        const result = (typeof data?.runPluginOperation === 'string' ? JSON.parse(data.runPluginOperation) : data?.runPluginOperation) || {};

        if (result?.success && result?.url) {
          window.open(result.url, "_blank", "noopener,noreferrer");
        } else {
          throw new Error(result?.error || "Emby 中未找到匹配");
        }
      } catch (err) {
        alert(`Open in Emby: ${err.message}`);
      }
    };

    return btn;
  }

  function getItemId() {
    const path = window.location.pathname;
    const hash = window.location.hash || "";
    for (const [type, regex] of Object.entries(TYPE_PATTERNS)) {
      let m = path.match(regex) || hash.match(regex);
      if (m) return { type, id: parseInt(m[1], 10) };
    }
    return null;
  }

  function getCardInfo(card) {
    const link = card.querySelector('a[href*="/scenes/"], a[href*="/performers/"], a[href*="/studios/"]');
    if (!link) return null;
    for (const [type, regex] of Object.entries(TYPE_PATTERNS)) {
      const m = link.href.match(regex);
      if (m) return { type, id: parseInt(m[1], 10) };
    }
    return null;
  }

  function addSceneDetailButton() {
    const item = getItemId();
    if (!item || item.type !== 'scene') return;

    const toolbarGroups = Array.from(document.querySelectorAll("span.scene-toolbar-group"));
    const toolbarGroup = toolbarGroups.length > 1 ? toolbarGroups[1] : null;
    if (!toolbarGroup || document.getElementById("open_in_emby__btn")) return;

    const btn = createEmbyButton('scene', item.id);
    btn.id = "open_in_emby__btn";

    const viewCountSpan = toolbarGroup.querySelector('span:has(.view-count-button), span:has(.count-button)');
    if (viewCountSpan && viewCountSpan.parentNode) {
      viewCountSpan.parentNode.insertBefore(btn, viewCountSpan);
    } else {
      toolbarGroup.appendChild(btn);
    }
  }

  function addPerformerStudioButton() {
    const item = getItemId();
    if (!item || (item.type !== 'performer' && item.type !== 'studio')) return;
    if (document.getElementById("open-in-emby-toolbar")) return;

    const qualityGroup = document.querySelector('.quality-group');
    if (!qualityGroup) return;

    const btn = createEmbyButton(item.type, item.id);
    btn.id = "open-in-emby-toolbar";

    const oCounter = qualityGroup.querySelector('.o-counter-button, .count-button');
    if (oCounter && oCounter.parentNode) {
      oCounter.parentNode.insertBefore(btn, oCounter.nextSibling);
    } else {
      qualityGroup.appendChild(btn);
    }
  }

  function addCardButton(card) {
    if (!card || card.querySelector('.open-in-emby-btn')) return;

    const info = getCardInfo(card);
    if (!info) return;

    let refBtn;
    if (info.type === 'scene') {
      refBtn = card.querySelector('.organized button, .organized-btn');
    } else if (info.type === 'performer') {
      refBtn = card.querySelector('.scene-count button');
    } else if (info.type === 'studio') {
      refBtn = card.querySelector('.performer-count button');
    }
    if (!refBtn) return;

    const parent = refBtn.closest('.btn-group, .card-popovers');
    if (parent) {
      const btn = createEmbyButton(info.type, info.id);
      parent.appendChild(btn);
    }
  }

  // ═══════════════════════════════════════════════════════════
  // 模块 2: GraphQL 通信和配置读取
  // ═══════════════════════════════════════════════════════════

  async function gql(query, variables) {
    const res = await fetch(localStorage.getItem("apiEndpoint") || "/graphql", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": localStorage.getItem("apiKey") ? `Bearer ${localStorage.getItem("apiKey")}` : "",
      },
      credentials: "include",
      body: JSON.stringify({ query, variables }),
    });
    const json = await res.json();
    if (json?.errors?.length) throw new Error(json.errors[0].message);
    return json.data;
  }

  async function getPluginSettings() {
    const data = await gql(`query { configuration { plugins } }`);
    const cfg = data?.configuration?.plugins?.[PLUGIN_ID] || {};
    const get = (k) => {
      const v = cfg[k];
      return (v && typeof v === 'object' && 'value' in v) ? v.value : v;
    };
    return {
      embyServer: (get('embyServer') || "").trim().replace(/\/+$/, ""),
      embyInternalServer: (get('embyInternalServer') || "").trim().replace(/\/+$/, ""),
      embyApiKey: (get('embyApiKey') || "").trim(),
    };
  }

  // ═══════════════════════════════════════════════════════════
  // 模块 3: 初始化和监听
  // ═══════════════════════════════════════════════════════════

  function init() {
    initCSS();

    // 首次执行
    addSceneDetailButton();
    addPerformerStudioButton();
    document.querySelectorAll('.scene-card, .performer-card, .studio-card').forEach(addCardButton);

    // 路由监听（页面切换）
    if (window.PluginApi?.Event?.addEventListener) {
      PluginApi.Event.addEventListener("stash:location", () => {
        setTimeout(() => {
          addSceneDetailButton();
          addPerformerStudioButton();
        }, 200);
      });
    }

    // DOM 监听（刷新/动态加载）
    const observer = new MutationObserver(() => {
      addSceneDetailButton();
      addPerformerStudioButton();

      document.querySelectorAll('.scene-card, .performer-card, .studio-card')
        .forEach(card => {
          if (!card.querySelector('.open-in-emby-btn')) {
            addCardButton(card);
          }
        });
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  init();
})();
