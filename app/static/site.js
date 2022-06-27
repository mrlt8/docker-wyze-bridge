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

document.addEventListener("DOMContentLoaded", () => {
  const select = document.querySelector("#select_number_of_columns");

  select.addEventListener("change", (e) => {
    const repeatNumber = select.value;
    setCookie("number_of_columns", repeatNumber);
    applyPreferences();
  });
});

document.addEventListener("DOMContentLoaded", () => {
  const select = document.querySelector("#select_refresh_period");

  select.addEventListener("change", (e) => {
    const refresh_period = select.value;
    setCookie("refresh_period", refresh_period);
    applyPreferences();
  });
});

function applyPreferences() {
  const repeatNumber = getCookie("number_of_columns", 2);
  console.debug("applyPreferences number_of_columns", repeatNumber);
  const grid = document.querySelectorAll(".camera");
  for (var i = 0, len = grid.length; i < len; i++) {
    grid[i].classList.forEach((item) => {
      if (item.startsWith("is-")) {
        grid[i].classList.remove(item);
      }
    });
    grid[i].classList.add(`is-${12 / repeatNumber}`);
  }

  const sortOrder = getCookie("camera_order", "");
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
    if (!e.target.matches(selector)) {
      return;
    }
    dragEl = e.target;
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

function refresh_img(imgUrl) {
  console.debug("refresh_img", imgUrl);

  // update img.src
  document.querySelectorAll(`[src="${imgUrl}"]`).forEach(function (e) {
    e.src = imgUrl.replace("img/", "snapshot/");
  });

  // update video.poster
  document.querySelectorAll(`[poster="${imgUrl}"]`).forEach(function (e) {
    e.setAttribute("poster", imgUrl.replace("img/", "snapshot/"));
  });

  // update video js div for poster
  const styleString = `background-image: url("${imgUrl}");`;
  document.querySelectorAll(`[style='${styleString}']`).forEach(function (e) {
    e.style = styleString.replace("img/", "snapshot/");
  });
}

function refresh_imgs() {
  console.debug("refresh_imgs " + Date.now());
  document.querySelectorAll(".refresh_img").forEach(function (image) {
    let url = image.getAttribute("src");
    fetch(url)
      .then((_) => {
        // reduce img flicker by pre-decode, before swapping it
        const tmp = new Image();
        tmp.src = url.replace("img/", "snapshot/");
        return tmp.decode();
      })
      .then(() => refresh_img(url));
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const grid = document.querySelector(".cameras");
  const selector = ".camera";
  sortable(grid, selector, function (item) {
    console.log(item);
    const cameras = document.querySelectorAll(selector);
    const ids = [...cameras].map((camera) => camera.id).filter((x) => x);
    const newOrdering = ids.join(",");
    console.debug("New camera_order", newOrdering);
    setCookie("camera_order", newOrdering);
  });
});

document.addEventListener("DOMContentLoaded", () => {
  let clickHide = document.getElementsByClassName("hide-image");
  function hide_img() {
    let uri = this.getAttribute("uri");
    var card = document
      .getElementById(uri)
      .getElementsByClassName("card-image")[0];
    card.classList.toggle("is-hidden");
  }
  for (var i = 0; i < clickHide.length; i++) {
    clickHide[i].addEventListener("click", hide_img);
  }
});

document.addEventListener("DOMContentLoaded", () => {
  let clickFilter = document.querySelectorAll("#filter > ul > li");
  function hide_cam() {
    document
      .querySelector("#filter > ul > li.is-active")
      .classList.remove("is-active");
    this.classList.add("is-active");
    document.querySelectorAll("div.camera.is-hidden").forEach((div) => {
      div.classList.remove("is-hidden");
    });
    let filter = this.getAttribute("filter");
    if (filter != "all") {
      document
        .querySelectorAll("div.camera:not([" + filter + "='True'])")
        .forEach((cam) => {
          cam.classList.add("is-hidden");
        });
    }
  }
  for (var i = 0; i < clickFilter.length; i++) {
    clickFilter[i].addEventListener("click", hide_cam);
  }
});

document.addEventListener("DOMContentLoaded", () => {
  let checkAPI = document.getElementById("checkUpdate");
  function checkVersion(api) {
    let isNewer = (a, b) => {
      return a.localeCompare(b, undefined, { numeric: true }) === 1;
    };
    let apiVersion = api.tag_name.replace(/[^0-9\.]/g, "");
    let runVersion = checkAPI.getAttribute("version");
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
    console.log(api.tag_name);
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
});

document.addEventListener("DOMContentLoaded", () => {
  function loadPreview(placeholder) {
    let cam_name = placeholder.getAttribute("cam");
    let poster = placeholder.getElementsByClassName("vjs-poster");
    if (cam_name === null) {
      cam_name = placeholder.getAttribute("id").replace("video-", "");
    }
    let cam_img = "snapshot/" + cam_name + ".jpg";
    let snapshot = new Image();
    snapshot.src = cam_img;
    snapshot
      .decode()
      .then(() => {
        placeholder.classList.remove("loading-preview");
        if (poster.length) {
          placeholder.setAttribute("poster", cam_img);
          poster[0].style.backgroundImage = `url("${cam_img}")`;
          placeholder.classList.add("refresh_poster");
        } else {
          placeholder.classList.add("refresh_img");
          placeholder.src = cam_img;
        }
      })
      .catch(() => {
        setTimeout(() => {
          loadPreview(placeholder);
        }, 30000);
      });
  }
  function updateSnapshot(e) {
    console.log("click");
    let button = e.target.closest("button");
    button.disabled = true;
    button.getElementsByClassName("fas")[0].classList.add("fa-pulse");
    button.parentElement.style.display = "block";
    let img = document.querySelector(
      "#" + button.getAttribute("cam") + " div div img.refresh_img"
    );
    let img_src = img.src.replace("img/", "snapshot/");
    fetch(img_src).then((_) => {
      let snapshot = new Image();
      snapshot.src = img_src;
      snapshot.decode().then(() => {
        img.src = snapshot.src;
        button.disabled = false;
        button.getElementsByClassName("fas")[0].classList.remove("fa-pulse");
        button.parentElement.style.display = null;
      });
    });
  }
  [...document.getElementsByClassName("loading-preview")].forEach(
    (placeholder) => loadPreview(placeholder)
  );
  [...document.getElementsByClassName("update-preview")].forEach((up) => {
    up.addEventListener("click", updateSnapshot);
  });
});
