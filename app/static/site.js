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
    const grid = document.querySelector('.cameras')
    grid.style.setProperty('grid-template-columns', `repeat(${repeatNumber}, 1fr)`);
}

function sortable(section, onUpdate) {
    var dragEl, nextEl, newPos, dragGhost;

    // let oldPos = [...section.children].map(item => {
    //     item.draggable = true
    //     let pos = item.getBoundingClientRect();
    //     return pos;
    // });

    function _onDragOver(e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';

        var target = e.target;
        if (target && target !== dragEl && target.nodeName === 'DIV') {
            if (target.classList.contains('inside')) {
                e.stopPropagation();
            } else {
                var targetPos = target.getBoundingClientRect();
                //checking that mouse is within the bounds of target
                var next = (e.clientY > targetPos.top) && (e.clientY < targetPos.bottom) && (e.clientX > targetPos.left) && (e.clientX < targetPos.right);
                section.insertBefore(dragEl, next && target.nextSibling || target);
            }
        }
    }

    function _onDragEnd(evt) {
        evt.preventDefault();
        newPos = [...section.children].map(child => {
            let pos = child.getBoundingClientRect();
            return pos;
        });
        dragEl.classList.remove('ghost');
        section.removeEventListener('dragover', _onDragOver, false);
        section.removeEventListener('dragend', _onDragEnd, false);

        nextEl !== dragEl.nextSibling ? onUpdate(dragEl) : false;
    }

    function _onDragStart(e) {
        dragEl = e.target;
        nextEl = dragEl.nextSibling;

        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('Text', dragEl.textContent);

        section.addEventListener('dragover', _onDragOver, false);
        section.addEventListener('dragend', _onDragEnd, false);

        setTimeout(function () {
            dragEl.classList.add('ghost');
        }, 0)
    }

    section.addEventListener('dragstart', _onDragStart);
}

function refresh_img(imgElement) {
    const url = imgElement.src;
    (u => fetch(u).then(response => imgElement.src = u))(url)
}

function refresh_imgs() {
    // console.log("refresh_imgs " + Date.now());
    var images = document.querySelectorAll('.refresh_img');
    for (var i = 0; i < images.length; i++) {
        var image = images[i];
        refresh_img(image);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const grid = document.querySelector('.cameras');
    sortable(grid, function (item) {
        /* console.log(item); */
    });
});

setInterval(refresh_imgs, 30000)
