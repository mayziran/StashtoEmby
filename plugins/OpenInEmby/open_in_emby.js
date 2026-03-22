(() => {
  "use strict";

  const HOST_SPAN_ID = "open_in_emby__host_span";
  const BTN_ID = "open_in_emby__btn";
  const PLUGIN_ID = "open_in_emby";

  const ICON_URL = "https://cdn.jsdelivr.net/gh/lige47/QuanX-icon-rule@main/icon/04ProxySoft/emby.png";

  const FALLBACK_SVG = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" style="width:1em;height:1em;display:block;">
  <circle cx="256" cy="256" r="200" fill="#52B54B"/>
  <text x="256" y="320" font-size="200" text-anchor="middle" fill="white" font-weight="bold">E</text>
</svg>`.trim();

  function log(...args) {
    console.log("[open_in_emby]", ...args);
  }

  function svgFromString(svgStr) {
    const tpl = document.createElement("template");
    tpl.innerHTML = svgStr.trim();
    return tpl.content.firstChild;
  }

  function getSceneId() {
    const path = window.location.pathname;
    let m = path.match(/\/scenes\/(\d+)/);
    if (m) return parseInt(m[1], 10);
    m = (window.location.hash || "").match(/\/scenes\/(\d+)/);
    return m ? parseInt(m[1], 10) : null;
  }

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
    const data = await gql(`
      query Configuration {
        configuration { plugins }
      }
    `);

    const plugins = data?.configuration?.plugins || {};
    const cfg = plugins?.[PLUGIN_ID] || {};

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

  async function matchByStashId(args, stashId) {
    const data = await gql(`
      mutation RunPluginOperation($plugin_id: ID!, $args: Map) {
        runPluginOperation(plugin_id: $plugin_id, args: $args)
      }
    `, {
      plugin_id: PLUGIN_ID,
      args: { ...args, stash_id: stashId.toString() },
    });

    const output = data?.runPluginOperation;
    if (!output) return null;

    const parsed = typeof output === 'string' ? JSON.parse(output) : output;
    const result = parsed.output || parsed;

    if (result.success && result.url) {
      log(`✅ ${result.item?.name || '未知'}`);
      return result.url;
    }
    log(`❌ ${result.error || '未知错误'}`);
    return null;
  }

  function createIconNode() {
    const img = document.createElement("img");
    img.src = ICON_URL;
    img.alt = "Emby";
    img.referrerPolicy = "no-referrer";
    img.style.width = "1em";
    img.style.height = "1em";
    img.style.display = "block";

    img.onerror = () => {
      try {
        img.replaceWith(svgFromString(FALLBACK_SVG));
      } catch (e) {
        log("Icon fallback failed:", e);
      }
    };

    return img;
  }

  function findToolbarGroup() {
    const groups = Array.from(document.querySelectorAll("span.scene-toolbar-group"));
    for (const g of groups) {
      const eye = g.querySelector('div.count-button.increment-only.btn-group svg[data-icon="eye"]');
      if (eye) return g;
    }
    return null;
  }

  // 提取点击事件处理函数，方便复用
  function createButtonOnClickHandler(sceneId, btn) {
    return async (e) => {
      e.preventDefault();
      e.stopPropagation();

      const originalHTML = btn.innerHTML;
      btn.innerHTML = "⏳";
      btn.disabled = true;

      try {
        const settings = await getPluginSettings();

        if (!settings.embyServer) {
          alert("Open in Emby: 请先配置 Emby 服务器地址（跳转用）");
          return;
        }
        if (!settings.embyInternalServer) {
          alert("Open in Emby: 请先配置 Emby 内网地址（API 用）");
          return;
        }
        if (!settings.embyApiKey) {
          alert("Open in Emby: 请先配置 Emby API Key");
          return;
        }

        const url = await matchByStashId(settings, sceneId);

        if (url) {
          window.open(url, "_blank", "noopener,noreferrer");
        } else {
          alert(`Open in Emby:\nEmby 中未找到匹配的视频\n\nStash ID: ${sceneId}`);
        }
      } catch (err) {
        alert(`Open in Emby 错误：${err.message}`);
      } finally {
        btn.innerHTML = originalHTML;
        btn.disabled = false;
      }
    };
  }

  function createButton(sceneId) {
    const toolbarGroup = findToolbarGroup();
    if (!toolbarGroup) return false;

    // 检查是否已存在，存在则只更新 onclick（upsert 模式）
    let host = document.getElementById(HOST_SPAN_ID);
    if (host) {
      const btn = document.getElementById(BTN_ID);
      if (btn) {
        btn.onclick = createButtonOnClickHandler(sceneId, btn);
      }
      return true;
    }

    // 不存在才创建
    host = document.createElement("span");
    host.id = HOST_SPAN_ID;

    const group = document.createElement("div");
    group.setAttribute("role", "group");
    group.className = "btn-group";

    const btn = document.createElement("button");
    btn.id = BTN_ID;
    btn.type = "button";
    btn.className = "minimal btn btn-secondary";
    btn.title = "Open in Emby";
    btn.appendChild(createIconNode());

    group.appendChild(btn);
    host.appendChild(group);

    const refSpan = toolbarGroup.querySelector('div.count-button.increment-only.btn-group svg[data-icon="eye"]')?.closest("span");
    if (refSpan) {
      toolbarGroup.insertBefore(host, refSpan);
    } else {
      toolbarGroup.appendChild(host);
    }

    btn.onclick = createButtonOnClickHandler(sceneId, btn);

    return true;
  }

  function handleLocation() {
    const sceneId = getSceneId();
    if (!sceneId) return;

    // React 需要多次尝试创建按钮
    let tries = 0;
    const maxTries = 40;
    const tick = () => {
      tries += 1;
      const ok = createButton(sceneId);
      if (!ok && tries < maxTries) {
        setTimeout(tick, 100);
      }
    };
    tick();
  }

  // 首次加载
  handleLocation();

  // 监听路由变化
  if (window.PluginApi?.Event?.addEventListener) {
    PluginApi.Event.addEventListener("stash:location", () => {
      setTimeout(handleLocation, 200);
    });
  } else {
    // fallback: 轮询
    setInterval(handleLocation, 1000);
  }
})();
