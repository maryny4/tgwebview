(function() {
    console.debug('[QR-Cam] starting');
    var overlay = document.createElement('div');
    overlay.id = '__tg_qr_cam__';
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;z-index:999999;background:#000;display:flex;flex-direction:column;';

    var canvas = document.createElement('canvas');
    canvas.style.cssText = 'flex:1;object-fit:contain;background:#111;';

    var video = document.createElement('video');
    video.setAttribute('playsinline',''); video.muted = true;
    video.style.cssText = 'position:absolute;width:1px;height:1px;opacity:0;pointer-events:none;';

    var bar = document.createElement('div');
    bar.style.cssText = 'height:56px;display:flex;align-items:center;justify-content:center;background:#111;flex-shrink:0;';

    var cancelBtn = document.createElement('button');
    cancelBtn.textContent = 'Cancel';
    cancelBtn.style.cssText = 'background:transparent;color:#fff;border:1px solid #555;border-radius:8px;padding:10px 40px;font-size:15px;cursor:pointer;font-family:inherit;';

    var status = document.createElement('div');
    status.style.cssText = 'position:absolute;top:50%;left:0;right:0;text-align:center;color:rgba(255,255,255,0.7);font-size:14px;z-index:2;font-family:inherit;transform:translateY(-50%);';
    status.textContent = 'Starting camera...';

    bar.appendChild(cancelBtn);
    overlay.appendChild(canvas);
    overlay.appendChild(video);
    overlay.appendChild(status);
    overlay.appendChild(bar);
    document.body.appendChild(overlay);

    var stream = null, scanning = true;
    var ctx = canvas.getContext('2d');
    var decoder = null;

    function cleanup() {
        scanning = false;
        if (stream) stream.getTracks().forEach(function(t){t.stop();});
        if (overlay.parentNode) overlay.remove();
    }
    function sendResult(data) {
        cleanup();
        if (window.pywebview && window.pywebview.api)
            window.pywebview.api.handle_bridge('__TG_QR_RESULT__:' + (data || ''));
    }
    function send(data, loc) {
        if (!data) { sendResult(''); return; }
        scanning = false;
        var vw = canvas.width, vh = canvas.height;
        ctx.drawImage(video, 0, 0);
        drawViewfinder(vw, vh);
        if (loc) {
            ctx.strokeStyle = '#4caf50'; ctx.lineWidth = 3;
            ctx.beginPath();
            ctx.moveTo(loc.topLeftCorner.x, loc.topLeftCorner.y);
            ctx.lineTo(loc.topRightCorner.x, loc.topRightCorner.y);
            ctx.lineTo(loc.bottomRightCorner.x, loc.bottomRightCorner.y);
            ctx.lineTo(loc.bottomLeftCorner.x, loc.bottomLeftCorner.y);
            ctx.closePath(); ctx.stroke();
        }
        ctx.fillStyle = '#4caf50';
        ctx.font = 'bold 14px -apple-system, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(data.length > 50 ? data.substring(0,47) + '...' : data, vw/2, vh - 20);
        ctx.textAlign = 'start';
        console.debug('[QR-Cam] found:', data);
        setTimeout(function(){ sendResult(data); }, 600);
    }

    cancelBtn.onclick = function() { send(''); };

    function drawViewfinder(w, h) {
        var side = Math.min(w, h) * 0.6;
        var x1 = (w - side) / 2, y1 = (h - side) / 2;
        var x2 = x1 + side, y2 = y1 + side;
        ctx.fillStyle = 'rgba(0,0,0,0.55)';
        ctx.fillRect(0, 0, w, y1);
        ctx.fillRect(0, y2, w, h - y2);
        ctx.fillRect(0, y1, x1, side);
        ctx.fillRect(x2, y1, w - x2, side);
        ctx.strokeStyle = 'rgba(255,255,255,0.6)';
        ctx.lineWidth = 2;
        ctx.strokeRect(x1, y1, side, side);
        var cl = side / 5;
        ctx.strokeStyle = '#40a7e3'; ctx.lineWidth = 3; ctx.lineCap = 'round';
        ctx.beginPath();
        ctx.moveTo(x1, y1+cl); ctx.lineTo(x1, y1); ctx.lineTo(x1+cl, y1);
        ctx.moveTo(x2-cl, y1); ctx.lineTo(x2, y1); ctx.lineTo(x2, y1+cl);
        ctx.moveTo(x1, y2-cl); ctx.lineTo(x1, y2); ctx.lineTo(x1+cl, y2);
        ctx.moveTo(x2-cl, y2); ctx.lineTo(x2, y2); ctx.lineTo(x2, y2-cl);
        ctx.stroke();
        ctx.fillStyle = 'rgba(255,255,255,0.8)';
        ctx.font = '13px -apple-system, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('Point camera at QR code', w/2, y2 + 28);
        ctx.textAlign = 'start';
    }

    function drawAndScan() {
        if (!scanning) return;
        if (video.readyState < video.HAVE_ENOUGH_DATA) {
            requestAnimationFrame(drawAndScan);
            return;
        }
        var vw = video.videoWidth, vh = video.videoHeight;
        if (canvas.width !== vw) { canvas.width = vw; canvas.height = vh; }
        ctx.drawImage(video, 0, 0);
        drawViewfinder(vw, vh);

        if (decoder === 'barcode') {
            new BarcodeDetector({formats:['qr_code']}).detect(canvas).then(function(r) {
                if (r.length > 0) { send(r[0].rawValue, null); return; }
                if (scanning) requestAnimationFrame(drawAndScan);
            }).catch(function() { if (scanning) requestAnimationFrame(drawAndScan); });
        } else if (typeof jsQR !== 'undefined') {
            var imageData = ctx.getImageData(0, 0, vw, vh);
            var code = jsQR(imageData.data, vw, vh);
            if (code && code.data) { send(code.data, code.location); return; }
            if (scanning) requestAnimationFrame(drawAndScan);
        } else {
            if (scanning) requestAnimationFrame(drawAndScan);
        }
    }

    function startScanning() {
        console.debug('[QR-Cam] video playing, starting scan');
        status.style.display = 'none';
        if (typeof BarcodeDetector !== 'undefined') {
            decoder = 'barcode';
            console.debug('[QR-Cam] using BarcodeDetector');
            drawAndScan();
        } else if (typeof jsQR !== 'undefined') {
            decoder = 'jsqr';
            console.debug('[QR-Cam] using jsQR (cached)');
            drawAndScan();
        } else {
            status.textContent = 'Loading QR decoder...';
            status.style.display = '';
            var s = document.createElement('script');
            s.src = 'https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.min.js';
            s.onload = function() {
                decoder = 'jsqr';
                console.debug('[QR-Cam] jsQR loaded from CDN');
                status.style.display = 'none';
                drawAndScan();
            };
            s.onerror = function() {
                console.error('[QR-Cam] failed to load jsQR');
                status.textContent = 'Failed to load QR decoder';
                setTimeout(function(){ send(''); }, 3000);
            };
            document.head.appendChild(s);
        }
    }

    function attachStream(s) {
        stream = s;
        video.srcObject = s;
        console.debug('[QR-Cam] stream attached, tracks:', s.getTracks().map(function(t){return t.label+' '+t.readyState;}).join(', '));
        video.play().then(function() {
            console.debug('[QR-Cam] video.play() ok, %dx%d', video.videoWidth, video.videoHeight);
            startScanning();
        }).catch(function(e) {
            console.error('[QR-Cam] video.play() failed:', e);
            status.textContent = 'Play failed: ' + e.message;
            setTimeout(function(){ send(''); }, 3000);
        });
    }

    navigator.mediaDevices.getUserMedia({video:true}).then(attachStream).catch(function(e) {
        console.error('[QR-Cam] getUserMedia failed:', e);
        status.textContent = 'Camera: ' + e.message;
        setTimeout(function(){ send(''); }, 3000);
    });

    setTimeout(function(){ if (scanning) send(''); }, 60000);
})();
