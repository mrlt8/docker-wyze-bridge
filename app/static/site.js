function setCookie(name, value, days) {
  var expires = "";
  if (days) {
    var date = new Date();
    date.setTime(date.getTime() + days * 24 * 60 * 60 * 1000);
    expires = "; expires=" + date.toUTCString();
  }
  document.cookie = name + "=" + (value || "") + expires + "; path=/";
}

function getCookie(name, def = null) {
  var nameEQ = name + "=";
  var ca = document.cookie.split(";");
  for (var i = 0; i < ca.length; i++) {
    var c = ca[i];
    while (c.charAt(0) == " ") c = c.substring(1, c.length);
    if (c.indexOf(nameEQ) == 0) return c.substring(nameEQ.length, c.length);
  }
  return def;
}

let refresh_interval = null; // refresh images interval
let refresh_period = -1; // refresh images time period in seconds

document.addEventListener("DOMContentLoaded", applyPreferences);

// Event listener for input and validate changes before applyPreferences
document.addEventListener("DOMContentLoaded", () => {
  function changeSetting(select) {
    let changeValue = Number(select.value);
    let cookieId = select.id.replace("select_", "");
    if (changeValue < select.min || changeValue > select.max) {
      select.classList.add("is-danger");
      select.value = getCookie(cookieId, cookieId == "refresh_period" ? 30 : 2);
      setTimeout(() => {
        select.classList.remove("is-danger");
      }, 1000);
      return;
    }
    setCookie(cookieId, changeValue);
    applyPreferences();
    select.classList.add("is-success");
    setTimeout(() => {
      select.classList.remove("is-success");
    }, 1000);
  }
  document
    .querySelectorAll("#select_refresh_period, #select_number_of_columns")
    .forEach((input) => {
      input.addEventListener("change", (e) => changeSetting(e.target));
    });
});

function applyPreferences() {
  const repeatNumber = getCookie("number_of_columns", 2);
  console.debug("applyPreferences number_of_columns", repeatNumber);
  const grid = document.querySelectorAll(".camera");
  for (var i = 0, len = grid.length; i < len; i++) {
    grid[i].classList.forEach((item) => {
      if (item.match(/^is\-\d/) || item == "is-one-fifth") {
        grid[i].classList.remove(item);
      }
    });
    grid[i].classList.add(
      `is-${repeatNumber == 5 ? "one-fifth" : 12 / repeatNumber}`
    );
  }
  var sortOrder = getCookie("camera_order", "");
  // clean escaped camera_order from flask args
  if (/["]/.test(sortOrder)) {
    sortOrder = sortOrder.replace(/\\054/g, ",").replace(/["]+/g, '')
    setCookie("camera_order", sortOrder)
  }
  if (sortOrder) {
    console.debug("applyPreferences camera_order", sortOrder);
    const ids = sortOrder.split(",");
    var cameras = [...document.querySelectorAll(".camera")];
    for (var i = 0; i < Math.min(ids.length, cameras.length); i++) {
      var a = document.getElementById(ids[i]);
      var b = cameras[i];
      if (a && b)
        // only swap if they both exist
        swap(a, b);
      cameras = [...document.querySelectorAll(".camera")];
    }
  }

  const new_period = getCookie("refresh_period", 30);
  if (refresh_period != new_period) {
    refresh_period = new_period;
    console.debug("applyPreferences refresh_period", refresh_period);
    clearInterval(refresh_interval);
    if (refresh_period > 0) {
      refresh_interval = setInterval(refresh_imgs, refresh_period * 1000);
    }
  }
}

/**
 * Swap two Element
 * @param a {Element} the first element
 * @param b {Element} the second element
 */
function swap(a, b) {
  let dummy = document.createElement("span");
  a.before(dummy);
  b.before(a);
  dummy.replaceWith(b);
}

/**
 * Enable dragging/sorting under the given parent.
 * @param parent {Element} parent to sort under
 * @param selector {string} selector string, to select the elements allowed to be sorted/swapped
 * @param onUpdate {Function} fired when an element is updated
 */
function sortable(parent, selector, onUpdate = null) {
  /** The element currently being dragged */
  var dragEl;

  /**
   * Fired when dragging over another element.
   * Swap the two elements, based on their parent selector.
   * @param e {DragEvent}
   * @private
   */
  function _onDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";

    const target = e.target.closest(selector);
    if (target && target !== dragEl) {
      console.debug("_onDragOver()", target);
      swap(dragEl, target);
    }
  }

  /**
   * Fired when drag ends (release mouse).
   * Turn off the ghost css.
   * @param e {DragEvent}
   * @private
   */
  function _onDragEnd(e) {
    console.debug("_onDragEnd()", e.target);
    e.preventDefault();
    dragEl.classList.remove("ghost");
    parent.removeEventListener("dragover", _onDragOver, false);
    parent.removeEventListener("dragend", _onDragEnd, false);
    onUpdate(dragEl);
  }

  /**
   * Fired when starting a drag.
   * Only allow dragging of elements that match our selector
   * @param e {DragEvent}
   * @private
   */
  function _onDragStart(e) {
    if (!e.target.matches(".drag_handle")) {
      e.stopPropagation();
      return;
    }
    dragEl = e.target.closest(selector);
    console.debug("_onDragStart()", e.target);
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("Text", dragEl.textContent);

    parent.addEventListener("dragover", _onDragOver, false);
    parent.addEventListener("dragend", _onDragEnd, false);

    setTimeout(function () {
      dragEl.classList.add("ghost");
    }, 0);
  }

  parent.addEventListener("dragstart", _onDragStart);
}

/**
 * Update camera image.
 * Self contained to fetch the new url, pre-decode it, and update the img.src, video.poster and videojs div overlay.
 * @param oldUrl the img url, could either be img/cam-name.jpg or snapshot/cam-name.jpg
 * @returns {Promise<void>}
 */
async function update_img(oldUrl, useImg = false) {
  let [cam, ext] = oldUrl.split("/").pop().split("?")[0].split(".");
  let newUrl = "snapshot/" + cam + "." + ext + "?" + Date.now();
  if (useImg || ext == "svg") {
    newUrl = "img/" + cam + "." + ext;
  }
  console.debug("update_img", oldUrl, newUrl);
  let button = document.querySelector(`.update-preview[data-cam="${cam}"]`);
  if (button) {
    button.disabled = true;
    button.getElementsByClassName("fas")[0].classList.add("fa-spin");
    button.style.display = "inline-block";
  }

  let imgDate = await fetch(newUrl);
  // reduce img flicker by pre-decode, before swapping it
  const tmp = new Image();
  tmp.src = newUrl;
  await tmp.decode();

  // update img.src
  document
    .querySelectorAll(`[src="${oldUrl}"],[src="${newUrl}"]`)
    .forEach(function (e) {
      e.src = newUrl;
    });

  // update video.poster
  document
    .querySelectorAll(`[poster="${oldUrl}"],[poster="${newUrl}"]`)
    .forEach(function (e) {
      e.setAttribute("poster", newUrl);
    });

  // update video js div for poster
  document
    .querySelectorAll(
      `[style='background-image: url("${oldUrl}");'],[style='background-image: url("${newUrl}");']`
    )
    .forEach(function (e) {
      e.style = `background-image: url("${newUrl}");`;
    });
  if (button) {
    button.disabled = false;
    button.getElementsByClassName("fas")[0].classList.remove("fa-spin");
    button.style.display = null;
    if (!imgDate.url.endsWith(".svg")) {
      button.parentElement.querySelector(".age").dataset.age = new Date(imgDate.headers.get("Last-Modified")).getTime();
    }
  }
  return newUrl;
}

function refresh_imgs() {
  console.debug("refresh_imgs " + Date.now());
  document.querySelectorAll(".refresh_img").forEach(async function (image) {
    let url = image.getAttribute("src");
    // Skip if not connected
    await update_img(url, !image.classList.contains("connected"));
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const grid = document.querySelector(".cameras");
  const selector = ".camera";
  sortable(grid, selector, function () {
    const cameras = document.querySelectorAll(selector);
    const ids = [...cameras].map((camera) => camera.id).filter((x) => x);
    const newOrdering = ids.join(",");
    console.debug("New camera_order", newOrdering);
    setCookie("camera_order", newOrdering);
  });
});

document.addEventListener("DOMContentLoaded", () => {
  // Filter cameras
  function filterCams() {
    document
      .querySelector("[data-filter].is-active")
      .classList.remove("is-active");
    this.classList.add("is-active");
    document.querySelectorAll("div.camera.is-hidden").forEach((div) => {
      div.classList.remove("is-hidden");
    });
    let filter = this.dataset.filter;
    if (filter != "all") {
      document
        .querySelectorAll("div.camera:not([data-" + filter + "='True'])")
        .forEach((cam) => {
          cam.classList.add("is-hidden");
        });
    }
  }
  document.querySelectorAll("a[data-filter]").forEach((a) => {
    a.addEventListener("click", filterCams);
  });
  document
    .querySelector(".navbar-brand .navbar-burger")
    .addEventListener("click", function () {
      this.classList.toggle("is-active");
      document.getElementById("refresh-menu").classList.toggle("is-active");
    });

  // Check for version update
  let checkAPI = document.getElementById("checkUpdate");
  function checkVersion(api) {
    let isNewer = (a, b) => {
      return a.localeCompare(b, undefined, { numeric: true }) === 1;
    };
    let apiVersion = api.tag_name.replace(/[^0-9\.]/g, "");
    let runVersion = checkAPI.dataset.version;
    let icon = checkAPI.getElementsByClassName("fa-arrows-rotate")[0];
    let newSpan = document.createElement("span");
    icon.classList.remove("fa-arrows-rotate");
    if (isNewer(apiVersion, runVersion)) {
      newSpan.textContent = "Update available: v" + apiVersion;
      checkAPI.classList.add("has-text-danger");
      icon.classList.add("fa-triangle-exclamation");
    } else {
      newSpan.textContent = "Latest version";
      checkAPI.classList.add("has-text-success");
      icon.classList.add("fa-square-check");
    }
    checkAPI.appendChild(newSpan);
    checkAPI.removeEventListener("click", getGithub);
  }
  function getGithub() {
    fetch(
      "https://api.github.com/repos/mrlt8/docker-wyze-bridge/releases/latest"
    )
      .then((response) => response.json())
      .then((data) => checkVersion(data));
  }
  checkAPI.addEventListener("click", getGithub);

  // Update preview after loading the page
  async function loadPreview(img) {
    let cam = img.getAttribute("data-cam");
    var oldUrl = img.getAttribute("src");
    if (oldUrl == null || !oldUrl.includes(cam)) {
      oldUrl = `snapshot/${cam}.jpg`;
    }
    try {
      let newUrl = await update_img(oldUrl, (getCookie("refresh_period") <= 10 || !img.classList.contains("connected")));
      let newVal = newUrl;
      img.parentElement.querySelectorAll("[src$=loading\\.svg],[style*=loading\\.svg],[poster$=loading\\.svg]")
        .forEach((e) => {
          for (let attr of e.attributes) {
            if (attr.value.includes("loading.svg")) {
              if (attr.name == "style") {
                newVal = `background-image: url(${newUrl});`;
              }
              e.setAttribute(attr.name, newVal);
              continue;
            }
          }
        });
      img.classList.remove("loading-preview");
    } catch {
      setTimeout(() => {
        loadPreview(img);
      }, 30000);
    }
  }
  document.querySelectorAll(".loading-preview").forEach(loadPreview);

  // click to update preview
  document.querySelectorAll(".update-preview[data-cam]").forEach((button) => {
    button.addEventListener("click", async () => {
      let img = document.querySelector(`.refresh_img[data-cam=${button.getAttribute("data-cam")}]`);
      if (img && img.getAttribute("src")) {
        await update_img(img.getAttribute("src"));
      }
    });
  });

  // Restart bridge/rtsp-simple-server.
  document.querySelectorAll("#restart-menu a").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.stopPropagation();
      a.style = "pointer-events: none;";
      a.classList.add("has-text-danger");
      fetch("restart/" + a.dataset.restart)
        .then((resp) => resp.json())
        .then((data) => {
          console.log(data);
        });
      setTimeout(() => {
        a.style = null;
        a.classList.remove("has-text-danger");
      }, 3000);
    });
  });

  // Update status icon based on connection status
  const sse = new EventSource("api/sse_status");
  sse.addEventListener("open", () => {
    document.getElementById("connection-lost").style.display = "none";
    document.querySelectorAll(".cam-overlay button.offline").forEach((btn) => {
      btn.disabled = false;
      btn.classList.remove("offline");
      let icon = btn.getElementsByClassName("fas")[0]
      icon.classList.remove("fa-plug-circle-exclamation");
      icon.classList.add("fa-arrows-rotate");
    })
    applyPreferences();
  });
  sse.addEventListener("error", () => {
    refresh_period = -1;
    clearInterval(refresh_interval);
    document.getElementById("connection-lost").style.display = "block";
    autoplay("stop");
    document.querySelectorAll("img.connected").forEach((i) => { i.classList.remove("connected") })
    document.querySelectorAll(".cam-overlay").forEach((i) => {
      i.getElementsByClassName("fas")[0].classList.remove("fa-spin");
    })
    document.querySelectorAll("[data-enabled=True] .card-header-title .status i").forEach((i) => {
      i.setAttribute("class", "fas fa-circle-exclamation")
    });
    document.querySelectorAll(".cam-overlay button").forEach((btn) => {
      btn.disabled = true;
      btn.parentElement.style.display = null;
      btn.classList.add("offline");
      let icon = btn.getElementsByClassName("fas")[0]
      icon.classList.remove("fa-arrows-rotate", "fa-spin");
      icon.classList.add("fa-plug-circle-exclamation");
    })
  });
  sse.addEventListener("mfa", (e) => {
    const alertDiv = document.getElementById("alert")
    if (e.data == "clear") {
      alertDiv.innerHTML = '<div class="columns is-centered"><div class="column is-half-desktop"><article class="message is-success container is-one-third-desktop"><div class="message-body"><span class="icon"><i class="fas fa-check-circle"></i></span><span>Verification code accepted!</div></article></div></div>'
      setTimeout(function () { location.reload(1); }, 5000);
    } else {
      if (alertDiv.classList.contains("is-hidden")) {
        const mfaType = e.data == "PrimaryPhone" ? "SMS" : "TOTP"
        console.error("MFA Required!!!!!")
        alertDiv.classList.toggle("is-hidden");
        alertDiv.innerHTML = '<div class="columns is-centered"><div class="column is-half-desktop"><article class="message is-dark container is-one-third-desktop"><div class="message-header">Two Factor Authentication Required</div>\
      <div class="message-body"><form id="mfa-form" action="#"><div class="field"><label class="label" for="mfa-code">'+ mfaType + ' code required</label><p class="control has-icons-left"><input id="mfa-code" class="input is-dark is-large is-fullwidth" type="tel" placeholder="e.g. 123456" inputmode="numeric" required pattern="\\d{3}\\s?\\d{3}" maxlength="7" autocomplete="one-time-code"><span class="icon is-left"><i class="fas fa-unlock" aria-hidden="true"></i></span></div><div class="field"><div class="control"><button id="mfa-submit" type="submit" class="button is-dark is-fullwidth">Submit</button></div></p></div></form></div>\
      </article></div></div>'
        const mfaForm = document.getElementById("mfa-form")
        const button = document.getElementById("mfa-submit").classList
        mfaForm.addEventListener('submit', (e) => {
          e.preventDefault();
          button.add("is-loading")
          let mfaCode = document.getElementById("mfa-code").value.replace(/\s/g, '')
          fetch("mfa/" + mfaCode).then(resp => resp.json()).then(data => {
            mfaForm.reset()
            button.remove("is-loading")
          }).catch(console.log("error"))
        })
      }
    }
  })
  sse.addEventListener("message", (e) => {
    Object.entries(JSON.parse(e.data)).forEach(([cam, status]) => {
      const statusIcon = document.querySelector(`#${cam} .status i.fas`);
      const preview = document.querySelector(`#${cam} img.refresh_img,video[data-cam='${cam}']`);
      statusIcon.setAttribute("class", "fas")
      statusIcon.parentElement.title = ""
      if (preview) { preview.classList.remove("connected") }
      if (status == "connected") {
        statusIcon.classList.add("fa-circle-play", "has-text-success");
        statusIcon.parentElement.title = "Click/tap to pause";
        if (preview) { preview.classList.add("connected") }
        autoplay();
        let noPreview = document.querySelector(`#${cam} .no-preview`)
        if (noPreview) {
          let fig = noPreview.parentElement
          let preview = document.createElement("img")
          preview.classList.add("refresh_img", "loading-preview", "connected")
          preview.dataset.cam = cam
          preview.src = "static/loading.svg"
          noPreview.replaceWith(preview)
          loadPreview(fig.querySelector("img"))
        }
      } else if (status == "connecting") {
        statusIcon.classList.add("fa-satellite-dish", "has-text-warning");
        statusIcon.parentElement.title = "Click/tap to pause";
      } else if (status == "standby") {
        statusIcon.classList.add("fa-circle-pause");
        statusIcon.parentElement.title = "Click/tap to play";
      } else if (status == "offline") {
        statusIcon.classList.add("fa-ghost");
        statusIcon.parentElement.title = "Camera offline";
      } else {
        statusIcon.setAttribute("class", "fas fa-circle-exclamation")
        statusIcon.parentElement.title = "Not Connected";
      }
    });
  });

  // Toggle Camera details
  function toggleDetails() {
    const cam = this.getAttribute("data-cam")
    const card = document.getElementById(cam);
    const img = card.getElementsByClassName("card-image")[0]
    const content = card.getElementsByClassName("content")[0]
    this.getElementsByClassName("fas")[0].classList.toggle("fa-flip-horizontal");
    if (content.classList.contains("is-hidden")) {
      const table = content.getElementsByTagName("table")[0]
      fetch(`api/${cam}`).then(resp => resp.json()).then(data => {
        table.innerHTML = ""
        for (const [key, value] of Object.entries(data)) {
          if (key == "camera_info" && value != null) {
            for (const [k, v] of Object.entries(value)) {
              let newRow = table.insertRow();
              let keyCell = newRow.insertCell(0)
              let valCell = newRow.insertCell(1)
              keyCell.innerHTML = k
              valCell.innerHTML = "<code>" + JSON.stringify(v, null, 2) + "</code>"
            }
            continue;
          }
          let newRow = table.insertRow();
          let keyCell = newRow.insertCell(0)
          let valCell = newRow.insertCell(1)
          keyCell.innerHTML = key
          if (typeof value === 'string' && value.startsWith("http")) {
            let link = document.createElement('a');
            link.href = value;
            link.title = value;
            link.innerHTML = value.substring(0, Math.min(50, value.length)) + (value.length >= 50 ? "..." : "");
            valCell.appendChild(link)
          } else {
            valCell.innerHTML = "<code>" + value + "</code>"
          }
        }
      }).catch(console.error);
    }
    img.classList.toggle("is-hidden");
    content.classList.toggle("is-hidden");
  }
  document.querySelectorAll(".toggle-details").forEach((btn) => {
    btn.addEventListener("click", toggleDetails);
  });
  // Play/pause on-demand
  function clickDemand() {
    const icon = this.querySelector("i.fas")
    const uri = this.getAttribute("data-cam");
    if (icon.matches(".fa-circle-play, .fa-satellite-dish")) {
      icon.setAttribute("class", "fas fa-circle-notch fa-spin")
      fetch(`api/${uri}/stop`)
      console.debug("pause " + uri)
    } else if (icon.matches(".fa-circle-pause, .fa-ghost")) {
      icon.setAttribute("class", "fas fa-circle-notch fa-spin")
      fetch(`api/${uri}/start`)
      console.debug("play " + uri)
    }
  }
  document.querySelectorAll(".status.enabled").forEach((span) => {
    span.addEventListener("click", clickDemand);
  });

  // Preview age
  function imgAge() {
    document.querySelectorAll("span.age[data-age]").forEach((span) => {
      timestamp = parseInt(span.dataset.age)
      if (timestamp) {
        var created = new Date(timestamp).getTime(),
          s = Math.floor((new Date() - created) / 1000),
          age = s < 60 ? `${s}s` : s < 3600 ? `+${Math.floor(s / 60)}m` : s < 86400 ? `+${Math.floor(s / 3600)}h` : `+${Math.floor(s / 86400)}d`
        span.textContent = age
      }
    })
    setTimeout(imgAge, 1000);
  }
  if (!getCookie("show_video")) { imgAge() }


  // fullscreen mode
  function toggleFullscreen(fs) {
    if (fs === undefined) {
      fs = getCookie("fullscreen");
    }
    let icon = document.querySelector(".fullscreen .fas");
    icon.classList.remove("fa-maximize", "fa-minimize")
    icon.classList.add(fs ? "fa-minimize" : "fa-maximize")
    document.querySelector(".section").style.padding = fs ? "1.5rem" : "";
    document.querySelectorAll(".fs-display-none").forEach((e) => {
      if (fs) { e.classList.add("fs-mode") } else { e.classList.remove("fs-mode") }
    })
  }
  document.querySelector(".fullscreen button").addEventListener("click", () => {
    let fs = !getCookie("fullscreen", false) ? "1" : "";
    setCookie("fullscreen", fs)
    toggleFullscreen(fs)
  })
  toggleFullscreen()

  // Load WS for WebRTC on demand
  function loadWebRTC(video, force = false) {
    if (!force && (!video.classList.contains("placeholder") || !video.classList.contains("connected"))) { return }
    let videoFormat = getCookie("video");
    video.classList.remove("placeholder");
    video.controls = true;
    fetch(`signaling/${video.dataset.cam}?${videoFormat}`).then((resp) => resp.json()).then((data) => new Receiver(data));
  }
  // Click to load WebRTC

  document.querySelectorAll('[data-enabled=True] video.webrtc.placeholder').forEach((v) => {
    v.parentElement.addEventListener("click", () => loadWebRTC(v, true), { "once": true });
  });
  // Auto-play video
  function autoplay(action) {
    let videos = document.querySelectorAll('video');
    if (action === "stop") {
      videos.forEach(video => {
        if (video.classList.contains("vjs-tech")) { videojs(video).pause() } else {
          video.classList.add("lost");
          // show poster on lost connection
        }
      });
      return;
    }
    let autoPlay = getCookie("autoplay");
    videos.forEach(video => {
      if (video.classList.contains("vjs-tech")) { video = videojs(video); } else {
        video.classList.remove("lost");
      }
      if (autoPlay) {
        if (video.classList.contains("webrtc")) {
          loadWebRTC(video);
        } else {
          video.play();
        }
      }
    });
  }
  // Change default video format for WebUI
  document.querySelectorAll(".preview-toggle [data-action]").forEach((e) => {
    e.addEventListener("click", () => {
      let videoCookie = getCookie("show_video")
      setCookie("show_video", "1");
      switch (e.dataset.action) {
        case "snapshot":
          setCookie("show_video", "");
          break;
        case "autoplay":
          let icon = e.querySelector("i.fas").classList;
          let playCookie = !!getCookie("autoplay");
          setCookie("autoplay", !playCookie);
          if (playCookie) { icon.replace("fa-square-check", "fa-square"); return; }
          icon.replace("fa-square", "fa-square-check")
          if (videoCookie) { autoplay(); return; }
          break;
        case "webrtc":
        case "hls":
        case "kvs":
          setCookie("video", e.dataset.action);
          break;
      }
      window.location = window.location.pathname;
    })
  })
}); 