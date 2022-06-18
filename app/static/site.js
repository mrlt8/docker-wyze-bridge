function setCookie(name, value, days) {
    var expires = "";
    if (days) {
        var date = new Date();
        date.setTime(date.getTime() + (days * 24 * 60 * 60 * 1000));
        expires = "; expires=" + date.toUTCString();
    }
    document.cookie = name + "=" + (value || "") + expires + "; path=/";
}

function getCookie(name, def = null) {
    var nameEQ = name + "=";
    var ca = document.cookie.split(';');
    for (var i = 0; i < ca.length; i++) {
        var c = ca[i];
        while (c.charAt(0) == ' ') c = c.substring(1, c.length);
        if (c.indexOf(nameEQ) == 0) return c.substring(nameEQ.length, c.length);
    }
    return def;
}

document.addEventListener('DOMContentLoaded', () => {
    const videos = document.querySelectorAll('video');

    for (var i = 0; i < videos.length; i++) {
        var video = videos[i];
        var videoSrc = video.getAttribute('data-src');
        if (Hls.isSupported()) {
            var config = {
                liveDurationInfinity: true,
            };
            var hls = new Hls(config);
            hls.loadSource(videoSrc);
            hls.attachMedia(video);
        }
        else if (video.canPlayType('application/vnd.apple.mpegurl')) {
            video.src = videoSrc;
        }
    }
});

document.addEventListener('DOMContentLoaded', () => {
    const select = document.querySelector('#select_number_of_columns');
    applyPreferences()

    select.addEventListener('change', (e) => {
        const repeatNumber = select.value;
        setCookie('number_of_columns', repeatNumber)
        applyPreferences()
    })
});

function applyPreferences() {
    const repeatNumber = getCookie('number_of_columns', 2)
    console.debug("applyPreferences number_of_columns", repeatNumber)
    const grid = document.querySelector('.cameras')
    grid.style.setProperty('grid-template-columns', `repeat(${repeatNumber}, 1fr)`);

    const sortOrder = getCookie("camera_order", "");
    console.debug("applyPreferences camera_order", sortOrder)
    const ids = sortOrder.split(",")
    var cameras = [...document.querySelectorAll(".camera")];
    for (var i = 0; i < Math.min(ids.length, cameras.length); i++)
    {
        var a = document.getElementById(ids[i]);
        var b = cameras[i];
        if (a && b) // only swap if they both exist
            swap(a, b)
        cameras = [...document.querySelectorAll(".camera")];
    }
}

/**
 * Swap two Element
 * @param a {Element} the first element
 * @param b {Element} the second element
 */
function swap(a, b) {
    let dummy = document.createElement("span")
    a.before(dummy)
    b.before(a)
    dummy.replaceWith(b)
}

/**
 * Enable dragging/sorting under the given parent.
 * @param parent {Element} parent to sort under
 * @param selector {string} selector string, to select the elements allowed to be sorted/swapped
 * @param onUpdate {Function} fired when an element is updated
 */
function sortable(parent, selector, onUpdate=null) {
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
        e.dataTransfer.dropEffect = 'move';

        const target = e.target.closest(selector)
        if (target && target !== dragEl) {
            console.debug("_onDragOver()", target)
            swap(dragEl, target)
        }
    }

    /**
     * Fired when drag ends (release mouse).
     * Turn off the ghost css.
     * @param e {DragEvent}
     * @private
     */
    function _onDragEnd(e) {
        console.debug("_onDragEnd()", e.target)
        e.preventDefault();
        dragEl.classList.remove('ghost');
        parent.removeEventListener('dragover', _onDragOver, false);
        parent.removeEventListener('dragend', _onDragEnd, false);
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
            return
        }
        dragEl = e.target;
        console.debug("_onDragStart()", e.target)
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('Text', dragEl.textContent);

        parent.addEventListener('dragover', _onDragOver, false);
        parent.addEventListener('dragend', _onDragEnd, false);

        setTimeout(function () {
            dragEl.classList.add('ghost');
        }, 0)
    }

    parent.addEventListener('dragstart', _onDragStart);
}

function refresh_img(imgElement) {
    const url = imgElement.src;
    (u => fetch(u).then(response => imgElement.src = u))(url)
}

function refresh_imgs() {
    console.debug("refresh_imgs " + Date.now());
    var images = document.querySelectorAll('.refresh_img');
    for (var i = 0; i < images.length; i++) {
        var image = images[i];
        refresh_img(image);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const grid = document.querySelector('.cameras');
    const selector = ".camera";
    sortable(grid, selector, function (item) {
        console.log(item);
        const cameras = document.querySelectorAll(selector);
        const ids = [...cameras].map(camera => camera.id).filter(x => x);
        const newOrdering = ids.join(",");
        console.debug("New camera_order", newOrdering)
        setCookie("camera_order", newOrdering)
    });
});

setInterval(refresh_imgs, 30000)  // refresh images every 30 seconds
