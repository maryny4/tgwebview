//
// TelegramWebviewProxy — injected at document-start via WKUserScript / CoreWebView2 / WebKit2.
// Implements the Telegram Mini App SDK bridge: handles postEvent() calls from the Mini App,
// dispatches receiveEvent() responses, renders the header bar and bottom bar UI,
// and forwards non-local RPC calls to Python via pywebview.api.handle_bridge().
//
(function() {
    // Guard: skip injection in Cloudflare/Turnstile iframes and cross-origin frames
    // to avoid breaking CAPTCHA verification (Turnstile error 600010).
    try {
        var host = window.location.hostname || '';
        if (host.indexOf('cloudflare') !== -1 || host.indexOf('turnstile') !== -1) return;
        if (window !== window.top) {
            try { var _ = window.top.location.href; } catch(e) { return; }
        }
    } catch(e) { return; }

    // Message queue: pywebview.api is not available until 'pywebviewready' fires.
    // Messages sent before that are buffered and flushed once the bridge connects.
    var __tg_queue = [];
    var __tg_ready = false;

    function __tg_send(msg) {
        if (__tg_ready && window.pywebview && window.pywebview.api) {
            window.pywebview.api.handle_bridge(msg);
        } else {
            __tg_queue.push(msg);
        }
    }

    window.addEventListener('pywebviewready', function() {
        __tg_ready = true;
        if (window.pywebview && window.pywebview.api) {
            for (var i = 0; i < __tg_queue.length; i++) {
                window.pywebview.api.handle_bridge(__tg_queue[i]);
            }
        }
        __tg_queue = [];
    });

    // Console forwarding: wrap all console methods to also send output to Python
    // via the __TG_CONSOLE__ bridge message. Only active when --verbose is set,
    // so Mini App console output doesn't leak to terminal by default.
    if (window.__tg_verbose__) {
        ['log', 'warn', 'error', 'debug', 'info'].forEach(function(level) {
            var orig = console[level];
            console[level] = function() {
                orig.apply(console, arguments);
                try {
                    var parts = [];
                    for (var i = 0; i < arguments.length; i++) {
                        var arg = arguments[i];
                        parts.push(typeof arg === 'object' ? JSON.stringify(arg) : String(arg));
                    }
                    __tg_send('__TG_CONSOLE__:' + level + ':' + parts.join(' '));
                } catch(e) {}
            };
        });
    }

    // Safe JSON parser: returns parsed object or empty fallback.
    function __tg_parse(data) {
        if (typeof data === 'object' && data !== null) return data;
        try { return JSON.parse(data); } catch(e) { return null; }
    }

    // Event routing: events listed in __tg_routed_events__ are forwarded to Python.
    // Python handler returns a result via __tg_resolve_event(), or null for default.
    // Uses a queue per event name to support rapid-fire calls (sensors).
    var __tg_routed = {};
    (window.__tg_routed_events__ || []).forEach(function(e) { __tg_routed[e] = true; });
    var __tg_pending = {};

    function __tg_route(event_name, data) {
        if (!__tg_routed[event_name]) return Promise.resolve(null);
        return new Promise(function(resolve) {
            if (!__tg_pending[event_name]) __tg_pending[event_name] = [];
            __tg_pending[event_name].push(resolve);
            __tg_send('__TG_EVENT__:' + event_name + ':' + JSON.stringify(data || {}));
        });
    }

    window.__tg_resolve_event = function(event_name, result) {
        var queue = __tg_pending[event_name];
        if (queue && queue.length > 0) {
            var resolve = queue.shift();
            if (queue.length === 0) delete __tg_pending[event_name];
            resolve(result);
        }
    };

    var __tg_verbose = !!window.__tg_verbose__;
    function __tg_log() {
        if (!__tg_verbose) return;
        var parts = [];
        for (var i = 0; i < arguments.length; i++) {
            var v = arguments[i];
            parts.push(typeof v === 'object' ? JSON.stringify(v) : String(v));
        }
        __tg_send('__TG_CONSOLE__:debug:[Bridge] ' + parts.join(' '));
    }

    // Theme parameters (injected by Python, falls back to light theme)
    var themeParams = window.__tg_theme_params__ || {
        bg_color: '#ffffff',
        text_color: '#000000',
        hint_color: '#999999',
        link_color: '#168acd',
        button_color: '#40a7e3',
        button_text_color: '#ffffff',
        secondary_bg_color: '#f1f1f1',
        header_bg_color: '#ffffff',
        accent_text_color: '#168acd',
        section_bg_color: '#ffffff',
        section_header_text_color: '#168acd',
        subtitle_text_color: '#999999',
        destructive_text_color: '#d14e4e',
        section_separator_color: '#e7e7e7',
        bottom_bar_bg_color: '#ffffff'
    };

    // receiveEvent: deliver events to the Mini App SDK.
    // Tries TelegramGameProxy first (TDesktop-style), then Telegram.WebView (web-style).
    // Data is auto-parsed from JSON string if needed — native clients pass objects.
    function receiveEvent(eventType, eventData) {
        var data = eventData;
        if (typeof data === 'string') {
            try { data = JSON.parse(data); } catch(e) {}
        }
        if (window.TelegramGameProxy && window.TelegramGameProxy.receiveEvent) {
            window.TelegramGameProxy.receiveEvent(eventType, data);
        } else if (window.Telegram && window.Telegram.WebView && window.Telegram.WebView.receiveEvent) {
            window.Telegram.WebView.receiveEvent(eventType, data);
        }
    }
    window.receiveEvent = receiveEvent;

    // Inject CSS for header bar, bottom bar buttons, shine effect and progress spinner.
    // Appended to <html> because <head>/<body> may not exist at document-start.
    (function() {
        var style = document.createElement('style');
        style.textContent = [
            '@keyframes __tg_shine { 0%{left:-100%} 100%{left:100%} }',
            '@keyframes __tg_spin { 0%{transform:rotate(0deg)} 100%{transform:rotate(360deg)} }',
            '.__tg_shine_effect { position:relative; overflow:hidden; }',
            '.__tg_shine_effect::after { content:""; position:absolute; top:0; left:-100%;',
            '  width:100%; height:100%; background:linear-gradient(90deg,transparent,',
            '  rgba(255,255,255,0.3),transparent); animation:__tg_shine 2s infinite; }',
            '.__tg_progress_spinner { display:inline-block; width:16px; height:16px;',
            '  border:2px solid rgba(255,255,255,0.3); border-top-color:#fff;',
            '  border-radius:50%; animation:__tg_spin 0.6s linear infinite;',
            '  vertical-align:middle; margin-right:6px; }',
            '#__tg_bottom_bar__ { position:fixed; bottom:0; left:0; right:0; z-index:99998;',
            '  padding:12px; box-sizing:border-box; display:none;',
            '  border-radius:6px 6px 0 0; }',
            '.__tg_bottom_btn { width:100%; height:40px; border:none; border-radius:6px;',
            '  font-size:14px; font-weight:600; cursor:pointer; display:flex;',
            '  align-items:center; justify-content:center; box-sizing:border-box;',
            '  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;',
            '  transition:opacity 0.15s, background-color 0.15s; outline:none; }',
            '.__tg_bottom_btn:hover { filter:brightness(0.96); }',
            '.__tg_bottom_btn:disabled { opacity:0.6; cursor:default; filter:none; }',
        ].join('\n');
        document.documentElement.appendChild(style);
    })();

    // Bottom bar: fixed container at the bottom of the viewport for main/secondary buttons.
    // Created lazily on first button setup, hidden when no buttons are visible.
    function ensureBottomBar() {
        var bar = document.getElementById('__tg_bottom_bar__');
        if (!bar) {
            bar = document.createElement('div');
            bar.id = '__tg_bottom_bar__';
            bar.style.backgroundColor = themeParams.bottom_bar_bg_color || themeParams.bg_color || '#ffffff';
            document.documentElement.appendChild(bar);
        }
        return bar;
    }

    function getOrCreateButton(id, defaults) {
        var bar = ensureBottomBar();
        var btn = document.getElementById(id);
        if (!btn) {
            btn = document.createElement('button');
            btn.id = id;
            btn.className = '__tg_bottom_btn';
            btn.style.backgroundColor = defaults.bg || '#40a7e3';
            btn.style.color = defaults.text || '#ffffff';
            btn.style.display = 'none';
            bar.appendChild(btn);
        }
        return btn;
    }

    function setButtonProgress(btn, show) {
        var spinner = btn.querySelector('.__tg_progress_spinner');
        if (show && !spinner) {
            spinner = document.createElement('span');
            spinner.className = '__tg_progress_spinner';
            spinner.style.borderColor = 'rgba(255,255,255,0.3)';
            spinner.style.borderTopColor = btn.style.color || '#fff';
            btn.insertBefore(spinner, btn.firstChild);
            btn.__tg_progress = true;
        } else if (!show && spinner) {
            spinner.remove();
            btn.__tg_progress = false;
        }
    }

    // Recalculate button layout: side-by-side (left/right) or stacked (top/bottom),
    // and adjust body padding-bottom so page content doesn't go under the bar.
    function repositionButtons() {
        var bar = document.getElementById('__tg_bottom_bar__');
        if (!bar) return;
        var main = document.getElementById('__tg_main_btn__');
        var sec = document.getElementById('__tg_secondary_btn__');
        var mainVisible = main && main.style.display !== 'none';
        var secVisible = sec && sec.style.display !== 'none';

        if (!mainVisible && !secVisible) {
            bar.style.display = 'none';
            (document.body || document.documentElement).style.paddingBottom = '';
            return;
        }
        bar.style.display = 'block';

        // Reset layout
        bar.style.flexDirection = '';
        bar.style.gap = '';
        if (main) { main.style.width = ''; main.style.order = ''; }
        if (sec) { sec.style.width = ''; sec.style.order = ''; }

        if (mainVisible && secVisible) {
            bar.style.display = 'flex';
            var pos = (sec && sec.__tg_position) || 'left';
            if (pos === 'left' || pos === 'right') {
                // Side by side with 12px gap
                bar.style.flexDirection = 'row';
                bar.style.gap = '12px';
                main.style.width = 'calc(50% - 6px)';
                sec.style.width = 'calc(50% - 6px)';
                if (pos === 'left') {
                    sec.style.order = '1';
                    main.style.order = '2';
                } else {
                    main.style.order = '1';
                    sec.style.order = '2';
                }
                (document.body || document.documentElement).style.paddingBottom = (12 + 40 + 12) + 'px'; // 64px
            } else {
                // Stacked vertically with 8px gap
                bar.style.flexDirection = 'column';
                bar.style.gap = '8px';
                if (pos === 'top') {
                    sec.style.order = '1';
                    main.style.order = '2';
                } else { // bottom
                    main.style.order = '1';
                    sec.style.order = '2';
                }
                (document.body || document.documentElement).style.paddingBottom = (12 + 40 + 8 + 40 + 12) + 'px'; // 112px
            }
        } else {
            // Single button
            (document.body || document.documentElement).style.paddingBottom = (12 + 40 + 12) + 'px'; // 64px
        }
    }

    // Header bar: fixed 42px bar at the top with [close/back] [bot pill] [spacer] [reload] [settings].
    // Window is frameless — this replaces the native title bar on all platforms.
    var __tg_header_height = 42;
    var botInfo = window.__tg_bot_info__ || {name: 'Mini App', id: 0};

    // Per-bot localStorage key prefix for Device Storage (local platform keychain emulation).
    var __tg_deviceStoragePrefix = '__tg_ds_' + botInfo.id + '_';

    // Avatar colors from TDesktop peerColors — indexed by user ID modulo 8.
    var __tg_avatar_colors = ['#e17076','#7bc862','#e5ca77','#65AADD','#a695e7','#ee7aae','#6ec9cb','#faa774'];
    function getAvatarColor(id) {
        return __tg_avatar_colors[Math.abs(id || 0) % __tg_avatar_colors.length];
    }

    function createHeaderIconBtn(svgHtml) {
        var btn = document.createElement('button');
        btn.innerHTML = svgHtml;
        btn.style.cssText = 'width:36px;height:36px;display:flex;align-items:center;' +
            'justify-content:center;background:transparent;border:none;cursor:pointer;' +
            'color:#999999;border-radius:50%;padding:0;flex-shrink:0;' +
            'transition:background-color 0.15s,color 0.15s;';
        btn.__tg_idle_color = '#999999';
        btn.__tg_hover_color = '#8a8a8a';
        btn.onmouseenter = function() {
            btn.style.color = btn.__tg_hover_color;
            btn.style.backgroundColor = 'rgba(128,128,128,0.12)';
        };
        btn.onmouseleave = function() {
            btn.style.color = btn.__tg_idle_color;
            btn.style.backgroundColor = 'transparent';
        };
        return btn;
    }

    // SVG icons for header buttons: close (x), back (←), menu (⋮), reload (↻)
    var __tg_close_svg = '<svg width="14" height="14" viewBox="0 0 14 14" fill="none">' +
        '<path d="M2 2L12 12M12 2L2 12" stroke="currentColor" stroke-width="1.5" ' +
        'stroke-linecap="round"/></svg>';
    var __tg_back_svg = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none">' +
        '<path d="M10 3L5 8L10 13" stroke="currentColor" stroke-width="1.5" ' +
        'stroke-linecap="round" stroke-linejoin="round"/></svg>';
    var __tg_menu_svg = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none">' +
        '<circle cx="8" cy="3.5" r="1.2" fill="currentColor"/>' +
        '<circle cx="8" cy="8" r="1.2" fill="currentColor"/>' +
        '<circle cx="8" cy="12.5" r="1.2" fill="currentColor"/></svg>';
    var __tg_reload_svg = '<svg width="13" height="13" viewBox="3 3 18 18" fill="currentColor">' +
        '<path d="M19.146 4.854l-1.489 1.489A8 8 0 1 0 12 20a8.094 8.094 0 0 0 7.371-4.886' +
        ' 1 1 0 1 0-1.842-.779A6.071 6.071 0 0 1 12 18a6 6 0 1 1 4.243-10.243l-1.39 1.39' +
        'a.5.5 0 0 0 .354.854H19.5A.5.5 0 0 0 20 9.5V5.207a.5.5 0 0 0-.854-.353z"/></svg>';

    // Build header DOM immediately at document-start (before <body> exists).
    // Uses <style> tag for body padding because document.body is null at this point.
    (function buildHeader() {
        var header = document.createElement('div');
        header.id = '__tg_header__';
        var headerBg = themeParams.header_bg_color || themeParams.bg_color || '#ffffff';
        header.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:100000;' +
            'height:' + __tg_header_height + 'px;display:flex;align-items:center;' +
            'background-color:' + headerBg + ';' +
            'box-sizing:border-box;padding:0 3px;' +
            'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;';

        var leftBtn = createHeaderIconBtn(__tg_close_svg);
        leftBtn.id = '__tg_header_left_btn__';
        leftBtn.__tg_is_back = false;
        leftBtn.onclick = function() {
            if (leftBtn.__tg_is_back) {
                if (window.TelegramGameProxy) {
                    TelegramGameProxy.receiveEvent('back_button_pressed');
                }
            } else {
                if (window.pywebview && window.pywebview.api) {
                    window.pywebview.api.handle_bridge('__TG_CLOSE__');
                } else {
                    window.close();
                }
            }
        };
        header.appendChild(leftBtn);

        var pill = document.createElement('div');
        pill.style.cssText = 'display:flex;align-items:center;gap:8px;' +
            'padding:4px 12px 4px 4px;border-radius:18px;' +
            'background:rgba(128,128,128,0.12);margin-left:2px;' +
            'overflow:hidden;max-width:200px;';

        var avatar = document.createElement('div');
        var avatarColor = getAvatarColor(botInfo.id);
        var initial = (botInfo.name || '?').charAt(0).toUpperCase();
        avatar.textContent = initial;
        avatar.style.cssText = 'width:24px;height:24px;border-radius:50%;flex-shrink:0;' +
            'display:flex;align-items:center;justify-content:center;' +
            'font-size:12px;font-weight:600;color:#fff;' +
            'background-color:' + avatarColor + ';';
        pill.appendChild(avatar);

        var nameSpan = document.createElement('span');
        nameSpan.textContent = botInfo.name;
        nameSpan.style.cssText = 'font-size:13px;font-weight:600;' +
            'color:' + (themeParams.text_color || '#000000') + ';' +
            'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;';
        pill.appendChild(nameSpan);
        header.appendChild(pill);

        var spacer = document.createElement('div');
        spacer.style.flex = '1';
        header.appendChild(spacer);

        var reloadBtn = createHeaderIconBtn(__tg_reload_svg);
        reloadBtn.id = '__tg_reload_btn__';
        reloadBtn.onclick = function() {
            // Spin the SVG icon, then reload after a short delay so the animation is visible.
            // transform-origin: center is required for SVG — default is top-left (0,0).
            var svg = reloadBtn.querySelector('svg');
            if (svg) {
                svg.style.transformOrigin = 'center';
                svg.style.animation = '__tg_spin 0.5s linear infinite';
            }
            setTimeout(function() { location.reload(); }, 350);
        };
        header.appendChild(reloadBtn);

        var menuBtn = createHeaderIconBtn(__tg_menu_svg);
        menuBtn.id = '__tg_settings_btn__';
        menuBtn.style.display = 'none';
        menuBtn.onclick = function() {
            if (window.TelegramGameProxy) {
                TelegramGameProxy.receiveEvent('settings_button_pressed');
            }
        };
        header.appendChild(menuBtn);

        document.documentElement.appendChild(header);

        var padStyle = document.createElement('style');
        padStyle.textContent = 'html body { padding-top: ' + __tg_header_height + 'px !important; }';
        document.documentElement.appendChild(padStyle);
    })();

    // Event handlers: each key is a Mini App SDK event name dispatched via
    // TelegramWebviewProxy.postEvent(). Handlers implement the desktop equivalents
    // of native Telegram client behavior, with no-ops for mobile-only features.
    var handlers = {
        // Theme/viewport: return current state to the Mini App on request.
        'web_app_request_theme': function() {
            receiveEvent('theme_changed', JSON.stringify({theme_params: themeParams}));
        },
        'web_app_request_viewport': function() {
            // TDesktop sends raw JS expression — window.innerHeight evaluated at runtime
            receiveEvent('viewport_changed', {
                height: window.innerHeight,
                is_state_stable: true,
                is_expanded: true
            });
        },
        'web_app_request_safe_area': function() {
            receiveEvent('safe_area_changed', {
                top: 0, bottom: 0, left: 0, right: 0
            });
        },
        'web_app_request_content_safe_area': function() {
            receiveEvent('content_safe_area_changed', {
                top: 0, bottom: 0, left: 0, right: 0
            });
        },

        'web_app_request_write_access': function() {
            // Forward to Python → MTProto (bots.canSendMessage / bots.allowSendMessage)
            __tg_send('__TG_WRITE_ACCESS__');
        },
        'web_app_request_phone': function() {
            __tg_route('contact', {}).then(function(r) {
                receiveEvent('phone_requested', JSON.stringify({status: 'sent'}));
            });
        },

        // Window lifecycle: expand is a no-op (already full size), close destroys
        // the window via pywebview API directly (bypasses message queue for reliability).
        'web_app_expand': function() {
            receiveEvent('viewport_changed', {
                height: window.innerHeight,
                is_state_stable: true,
                is_expanded: true
            });
        },
        'web_app_close': function() {
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.handle_bridge('__TG_CLOSE__');
            } else {
                window.close();
            }
        },
        'web_app_ready': function() {
            __tg_log('Mini App signaled ready');
        },

        'web_app_data_send': function(data) {
            __tg_log('data_send:', data);
        },

        // Popup: forwarded to Python for native OS dialog.
        'web_app_open_popup': function(data) {
            var params = __tg_parse(data);
            if (!params || !params.message || !params.buttons || !params.buttons.length) return;
            __tg_send('__TG_POPUP__:' + JSON.stringify(params));
        },

        // Links: forwarded to Python bridge which opens them in the system browser.
        'web_app_open_link': function(data) {
            var params = __tg_parse(data);
            if (!params) return;
            __tg_log('Opening external link:', params.url);
            __tg_send('__TG_OPEN_LINK__:' + params.url);
        },
        'web_app_open_tg_link': function(data) {
            var params = __tg_parse(data);
            if (!params) return;
            var url = 'https://t.me' + params.path_full;
            __tg_log('Opening Telegram link:', url);
            __tg_send('__TG_OPEN_LINK__:' + url);
        },

        // Biometry: UNSUPPORTED on desktop (TDesktop returns available:false).
        // @app.on('biometry') overrides for custom emulation.
        'web_app_biometry_get_info': function() {
            __tg_route('biometry', {action: 'get_info'}).then(function(r) {
                receiveEvent('biometry_info_received', JSON.stringify(
                    (r && r.available !== undefined) ? r : {available: false}
                ));
            });
        },
        'web_app_biometry_request_access': function() {
            __tg_route('biometry', {action: 'request_access'}).then(function(r) {
                receiveEvent('biometry_info_received', JSON.stringify(
                    (r && r.available !== undefined) ? r : {available: false}
                ));
            });
        },
        'web_app_biometry_request_auth': function() {
            __tg_route('biometry', {action: 'request_auth'}).then(function(r) {
                receiveEvent('biometry_auth_requested', JSON.stringify(
                    (r && r.token) ? {status: 'authorized', token: r.token}
                                   : {status: 'failed', error: 'BIOMETRY_UNAVAILABLE'}
                ));
            });
        },
        'web_app_biometry_update_token': function(data) {
            __tg_route('biometry', {action: 'update_token', data: __tg_parse(data)}).then(function(r) {
                receiveEvent('biometry_token_updated', JSON.stringify(
                    r ? {status: 'updated'} : {status: 'failed', error: 'BIOMETRY_UNAVAILABLE'}
                ));
            });
        },
        'web_app_biometry_open_settings': function() {
            __tg_route('biometry', {action: 'open_settings'});
        },

        // Device Storage: backed by localStorage with per-bot prefix (__tg_ds_{botId}_).
        // On real Telegram clients this uses platform keychain — we use localStorage as fallback.
        'web_app_device_storage_save_key': function(data) {
            var params = __tg_parse(data);
            if (!params) return;
            try {
                if (params.value === null || params.value === undefined) {
                    localStorage.removeItem(__tg_deviceStoragePrefix + params.key);
                } else {
                    localStorage.setItem(__tg_deviceStoragePrefix + params.key, params.value);
                }
                __tg_log('Device storage: saved key', params.key);
                receiveEvent('device_storage_key_saved', {req_id: params.req_id});
            } catch(e) {
                __tg_log('Device storage save failed:', e);
                receiveEvent('device_storage_failed', {req_id: params.req_id, error: 'STORAGE_ERROR'});
            }
        },
        'web_app_device_storage_get_key': function(data) {
            var params = __tg_parse(data);
            if (!params) return;
            var val = localStorage.getItem(__tg_deviceStoragePrefix + params.key);
            __tg_log('Device storage: get key', params.key, '=', val !== null ? '(found)' : '(null)');
            receiveEvent('device_storage_key_received', JSON.stringify({req_id: params.req_id, value: val}));
        },
        'web_app_device_storage_clear': function(data) {
            var params = __tg_parse(data);
            if (!params) return;
            var keys = Object.keys(localStorage);
            var count = 0;
            for (var i = 0; i < keys.length; i++) {
                if (keys[i].indexOf(__tg_deviceStoragePrefix) === 0) { localStorage.removeItem(keys[i]); count++; }
            }
            __tg_log('Device storage: cleared', count, 'keys');
            receiveEvent('device_storage_cleared', JSON.stringify({req_id: params.req_id}));
        },

        // Secure Storage: UNSUPPORTED on TDesktop — requires system keychain.
        'web_app_secure_storage_save_key': function(data) {
            var params = __tg_parse(data);
            if (!params) return;
            receiveEvent('secure_storage_failed', JSON.stringify({req_id: params.req_id, error: 'UNSUPPORTED'}));
        },
        'web_app_secure_storage_get_key': function(data) {
            var params = __tg_parse(data);
            if (!params) return;
            receiveEvent('secure_storage_failed', JSON.stringify({req_id: params.req_id, error: 'UNSUPPORTED'}));
        },
        'web_app_secure_storage_restore_key': function(data) {
            var params = __tg_parse(data);
            if (!params) return;
            receiveEvent('secure_storage_failed', JSON.stringify({req_id: params.req_id, error: 'UNSUPPORTED'}));
        },
        'web_app_secure_storage_clear': function(data) {
            var params = __tg_parse(data);
            if (!params) return;
            receiveEvent('secure_storage_failed', JSON.stringify({req_id: params.req_id, error: 'UNSUPPORTED'}));
        },

        'web_app_read_text_from_clipboard': function(data) {
            var params = __tg_parse(data);
            if (!params) return;
            // TDesktop: only allowed if bot is in attach/main menu.
            // Default: deny (omit data field). @app.on('clipboard') overrides.
            __tg_route('clipboard', {req_id: params.req_id}).then(function(r) {
                if (r !== null && r !== undefined) {
                    var text = typeof r === 'string' ? r : r.text || null;
                    receiveEvent('clipboard_text_received', JSON.stringify({req_id: params.req_id, data: text}));
                } else {
                    // No handler = denied — omit data field like TDesktop
                    receiveEvent('clipboard_text_received', JSON.stringify({req_id: params.req_id}));
                }
            });
        },

        // Custom methods: CloudStorage forwarded to Telegram servers via MTProto
        // (bots.invokeWebViewCustomMethod). All other methods forwarded via bridge.
        'web_app_invoke_custom_method': function(data) {
            var request = __tg_parse(data);
            if (!request) return;
            var method = request.method;
            var params = request.params || {};
            if (typeof params === 'string') {
                try { params = JSON.parse(params); } catch(e) { params = {}; }
            }
            var reqId = request.req_id;
            __tg_log('invokeCustomMethod:', method, 'req_id:', reqId, 'params:', JSON.stringify(params));

            // CloudStorage methods → forward to Python → MTProto
            var csMethod = (method === 'saveStorageValue' || method === 'deleteStorageValue' ||
                            method === 'deleteStorageValues' || method === 'getStorageValues' ||
                            method === 'getStorageKeys');
            if (csMethod) {
                __tg_log('CloudStorage via MTProto:', method);
                __tg_send('__TG_CLOUD_STORAGE__:' + JSON.stringify({
                    req_id: reqId, method: method, params: params
                }));
                return;
            }

            // Non-CloudStorage: forward via bridge for Python handler
            if (__tg_routed['invoke']) {
                __tg_log('Custom method routed to Python handler:', method);
            } else {
                __tg_log('Forwarding custom method via bridge:', method);
            }
            __tg_send('__TG_INVOKE__:' + (typeof data === 'string' ? data : JSON.stringify(request)));
        },

        // UI buttons: main/secondary rendered in the bottom bar, back/settings in the header.
        // Back button state is fully SDK-controlled — no auto-navigation detection.
        'web_app_setup_main_button': function(data) {
            var c = __tg_parse(data) || {};
            var btn = getOrCreateButton('__tg_main_btn__', {bg: '#40a7e3', text: '#ffffff'});
            var shouldShow = c.is_visible !== undefined ? c.is_visible : btn.style.display === 'flex';
            if (shouldShow) {
                btn.textContent = c.text || btn.textContent || '';
                if (c.color) btn.style.backgroundColor = c.color;
                if (c.text_color) btn.style.color = c.text_color;
                var isActive = c.is_active !== undefined ? c.is_active : true;
                btn.disabled = !isActive;
                btn.style.display = 'flex';
                if (c.has_shine_effect) {
                    btn.classList.add('__tg_shine_effect');
                } else if (c.has_shine_effect === false) {
                    btn.classList.remove('__tg_shine_effect');
                }
                if (c.is_progress_visible !== undefined) {
                    setButtonProgress(btn, c.is_progress_visible);
                }
                btn.onclick = function() {
                    if (!btn.disabled && window.TelegramGameProxy) {
                        TelegramGameProxy.receiveEvent('main_button_pressed');
                    }
                };
                repositionButtons();
                __tg_log('Main button shown:', c.text);
            } else if (c.is_visible === false) {
                btn.style.display = 'none';
                repositionButtons();
                __tg_log('Main button hidden');
            }
        },
        'web_app_setup_secondary_button': function(data) {
            var c = __tg_parse(data) || {};
            var btn = getOrCreateButton('__tg_secondary_btn__', {bg: '#f0f0f0', text: '#40a7e3'});
            if (c.position) btn.__tg_position = c.position;
            var shouldShow = c.is_visible !== undefined ? c.is_visible : btn.style.display === 'flex';
            if (shouldShow) {
                btn.textContent = c.text || btn.textContent || '';
                if (c.color) btn.style.backgroundColor = c.color;
                if (c.text_color) btn.style.color = c.text_color;
                var isActive = c.is_active !== undefined ? c.is_active : true;
                btn.disabled = !isActive;
                btn.style.display = 'flex';
                if (c.has_shine_effect) {
                    btn.classList.add('__tg_shine_effect');
                } else if (c.has_shine_effect === false) {
                    btn.classList.remove('__tg_shine_effect');
                }
                if (c.is_progress_visible !== undefined) {
                    setButtonProgress(btn, c.is_progress_visible);
                }
                btn.onclick = function() {
                    if (!btn.disabled && window.TelegramGameProxy) {
                        TelegramGameProxy.receiveEvent('secondary_button_pressed');
                    }
                };
                repositionButtons();
                __tg_log('Secondary button shown:', c.text, 'position:', btn.__tg_position || 'left');
            } else if (c.is_visible === false) {
                btn.style.display = 'none';
                repositionButtons();
                __tg_log('Secondary button hidden');
            }
        },
        'web_app_setup_back_button': function(data) {
            var c = __tg_parse(data) || {};
            var leftBtn = document.getElementById('__tg_header_left_btn__');
            if (leftBtn) {
                if (c.is_visible) {
                    leftBtn.innerHTML = __tg_back_svg;
                    leftBtn.__tg_is_back = true;
                } else {
                    leftBtn.innerHTML = __tg_close_svg;
                    leftBtn.__tg_is_back = false;
                }
            }
            __tg_log('Back button', c.is_visible ? 'shown' : 'hidden');
        },
        'web_app_setup_settings_button': function(data) {
            var c = __tg_parse(data) || {};
            window.__tg_settings_visible = !!c.is_visible;
            var btn = document.getElementById('__tg_settings_btn__');
            if (btn) {
                btn.style.display = c.is_visible ? 'flex' : 'none';
            }
            __tg_log('Settings button', c.is_visible ? 'shown' : 'hidden');
        },
        'web_app_setup_closing_behavior': function(data) {
            __tg_log('Closing behavior set:', data || '{}');
        },
        'web_app_setup_swipe_behavior': function(data) {
            __tg_log('Swipe behavior set (no-op on desktop):', data || '{}');
        },
        'web_app_toggle_orientation_lock': function(data) {
            __tg_log('Orientation lock toggled (no-op on desktop):', data || '{}');
        },

        // Header/bottom bar color: color_key references themeParams, color is raw hex.
        // Button icons auto-adjust to light/dark based on header background luminance.
        'web_app_set_header_color': function(data) {
            var c = __tg_parse(data) || {};
            var header = document.getElementById('__tg_header__');
            if (header) {
                var color = c.color || (c.color_key ? themeParams[c.color_key] : null);
                if (color) {
                    header.style.backgroundColor = color;
                    // Relative luminance (BT.709) — determines if icons should be light or dark
                    // Expand shorthand hex (#fff → #ffffff) before parsing
                    if (/^#[0-9a-fA-F]{3}$/.test(color)) {
                        color = '#' + color[1]+color[1] + color[2]+color[2] + color[3]+color[3];
                    }
                    if (/^#[0-9a-fA-F]{6}$/.test(color)) {
                        var red   = parseInt(color.slice(1,3),16)/255;
                        var green = parseInt(color.slice(3,5),16)/255;
                        var blue  = parseInt(color.slice(5,7),16)/255;
                        var luminance = 0.2126*red + 0.7152*green + 0.0722*blue;
                        var btnColor = luminance > 0.5 ? 'rgba(0,0,0,0.55)' : 'rgba(255,255,255,0.55)';
                        var btnHover = luminance > 0.5 ? 'rgba(0,0,0,0.7)' : 'rgba(255,255,255,0.7)';
                        var textColor = luminance > 0.5 ? '#000000' : '#ffffff';
                        var leftBtn = document.getElementById('__tg_header_left_btn__');
                        var menuBtn = document.getElementById('__tg_settings_btn__');
                        var relBtn = document.getElementById('__tg_reload_btn__');
                        [leftBtn, menuBtn, relBtn].forEach(function(el) {
                            if (el) {
                                el.style.color = btnColor;
                                el.__tg_idle_color = btnColor;
                                el.__tg_hover_color = btnHover;
                            }
                        });
                        // Update bot name text color in pill
                        var nameEl = header.querySelector('span');
                        if (nameEl) nameEl.style.color = textColor;
                    }
                }
            }
            __tg_log('Header color set:', c.color || c.color_key);
        },
        'web_app_set_background_color': function(data) {
            __tg_log('Background color set:', data || '{}');
        },
        'web_app_set_bottom_bar_color': function(data) {
            var c = __tg_parse(data) || {};
            var bar = document.getElementById('__tg_bottom_bar__');
            if (bar) {
                var color = c.color || (c.color_key ? themeParams[c.color_key] : null);
                if (color) bar.style.backgroundColor = color;
            }
            __tg_log('Bottom bar color set:', c.color || c.color_key);
        },

        // Haptic feedback (no-op on desktop)
        'web_app_trigger_haptic_feedback': function() {},

        // Invoice: auto-cancelled (no payment UI on desktop).
        'web_app_open_invoice': function(data) {
            var params = __tg_parse(data);
            if (!params) return;
            __tg_log('Invoice opened (auto-cancelled):', params.slug);
            receiveEvent('invoice_closed', JSON.stringify({slug: params.slug, status: 'cancelled'}));
        },

        'web_app_request_fullscreen': function() {
            __tg_route('fullscreen', {action: 'request'}).then(function(r) {
                if (r === true) {
                    receiveEvent('fullscreen_changed', JSON.stringify({is_fullscreen: true}));
                } else {
                    receiveEvent('fullscreen_failed', JSON.stringify({error: 'UNSUPPORTED'}));
                }
            });
        },
        'web_app_exit_fullscreen': function() {
            __tg_route('fullscreen', {action: 'exit'}).then(function() {
                receiveEvent('fullscreen_changed', JSON.stringify({is_fullscreen: false}));
            });
        },

        'web_app_check_home_screen': function() {
            receiveEvent('home_screen_checked', JSON.stringify({status: 'unsupported'}));
        },
        'web_app_add_to_home_screen': function() {
            __tg_log('Add to home screen (unsupported on desktop)');
            receiveEvent('home_screen_failed');
        },

        // Emoji status (unsupported on desktop)
        'web_app_request_emoji_status_access': function() {
            __tg_log('Emoji status access requested (unsupported)');
            receiveEvent('emoji_status_access_requested', {status: 'cancelled'});
        },
        'web_app_set_emoji_status': function() {
            __tg_log('Set emoji status (unsupported on desktop)');
            receiveEvent('emoji_status_failed', {error: 'UNSUPPORTED'});
        },

        // File download
        'web_app_request_file_download': function(data) {
            __tg_log('File download requested (auto-cancelled)');
            receiveEvent('file_download_requested', JSON.stringify({status: 'cancelled'}));
        },

        'web_app_check_location': function() {
            __tg_route('location', {action: 'check'}).then(function(r) {
                if (r && r.available) {
                    receiveEvent('location_checked', {available: true, access_requested: true, access_granted: true});
                } else {
                    receiveEvent('location_checked', {available: false, access_requested: false, access_granted: false});
                }
            });
        },
        'web_app_request_location': function() {
            __tg_route('location', {action: 'request'}).then(function(r) {
                if (r && r.latitude !== undefined) {
                    receiveEvent('location_requested', JSON.stringify({
                        available: true, latitude: r.latitude, longitude: r.longitude,
                        altitude: r.altitude || null, course: r.course || 0,
                        speed: r.speed || 0, horizontal_accuracy: r.horizontal_accuracy || 10
                    }));
                } else {
                    receiveEvent('location_requested', JSON.stringify({available: false}));
                }
            });
        },
        'web_app_open_location_settings': function() {
            __tg_route('location', {action: 'open_settings'});
        },

        // Sharing
        'web_app_share_to_story': function() {
            __tg_log('Share to story (no-op on desktop)');
        },
        'web_app_send_prepared_message': function(data) {
            __tg_log('Send prepared message (unsupported on desktop)');
            receiveEvent('prepared_message_failed', {error: 'UNSUPPORTED'});
        },

        'web_app_open_scan_qr_popup': function(data) {
            __tg_route('qr_scan', __tg_parse(data) || {}).then(function(r) {
                if (r !== null && r !== undefined) {
                    var text = typeof r === 'string' ? r : (r.data || '');
                    receiveEvent('qr_text_received', JSON.stringify({data: text}));
                }
                receiveEvent('scan_qr_popup_closed', JSON.stringify({}));
            });
        },
        'web_app_close_scan_qr_popup': function() {},

        // Inline query
        'web_app_switch_inline_query': function(data) {
            __tg_log('Switch inline query:', data);
        },

        'web_app_start_accelerometer': function(data) {
            __tg_route('accelerometer', {action:'start'}).then(function(r) {
                if (r && typeof r === 'object') {
                    receiveEvent('accelerometer_started', JSON.stringify({}));
                    var interval = (__tg_parse(data) || {}).refresh_rate || 100;
                    window.__tg_accel_timer = setInterval(function() {
                        __tg_route('accelerometer', {action:'data'}).then(function(v) {
                            if (v) receiveEvent('accelerometer_changed', JSON.stringify({x:v.x||0, y:v.y||0, z:v.z||0}));
                        });
                    }, Math.max(interval, 50));
                } else {
                    receiveEvent('accelerometer_failed', JSON.stringify({error: 'UNSUPPORTED'}));
                }
            });
        },
        'web_app_stop_accelerometer': function() {
            if (window.__tg_accel_timer) { clearInterval(window.__tg_accel_timer); window.__tg_accel_timer = null; }
            receiveEvent('accelerometer_stopped', JSON.stringify({}));
        },
        'web_app_start_gyroscope': function(data) {
            __tg_route('gyroscope', {action:'start'}).then(function(r) {
                if (r && typeof r === 'object') {
                    receiveEvent('gyroscope_started', JSON.stringify({}));
                    var interval = (__tg_parse(data) || {}).refresh_rate || 100;
                    window.__tg_gyro_timer = setInterval(function() {
                        __tg_route('gyroscope', {action:'data'}).then(function(v) {
                            if (v) receiveEvent('gyroscope_changed', JSON.stringify({x:v.x||0, y:v.y||0, z:v.z||0}));
                        });
                    }, Math.max(interval, 50));
                } else {
                    receiveEvent('gyroscope_failed', JSON.stringify({error: 'UNSUPPORTED'}));
                }
            });
        },
        'web_app_stop_gyroscope': function() {
            if (window.__tg_gyro_timer) { clearInterval(window.__tg_gyro_timer); window.__tg_gyro_timer = null; }
            receiveEvent('gyroscope_stopped', JSON.stringify({}));
        },
        'web_app_start_device_orientation': function(data) {
            __tg_route('device_orientation', {action:'start'}).then(function(r) {
                if (r && typeof r === 'object') {
                    receiveEvent('device_orientation_started', JSON.stringify({}));
                    var interval = (__tg_parse(data) || {}).refresh_rate || 100;
                    window.__tg_orient_timer = setInterval(function() {
                        __tg_route('device_orientation', {action:'data'}).then(function(v) {
                            if (v) receiveEvent('device_orientation_changed', JSON.stringify({
                                absolute: !!v.absolute, alpha: v.alpha||0, beta: v.beta||0, gamma: v.gamma||0
                            }));
                        });
                    }, Math.max(interval, 50));
                } else {
                    receiveEvent('device_orientation_failed', JSON.stringify({error: 'UNSUPPORTED'}));
                }
            });
        },
        'web_app_stop_device_orientation': function() {
            if (window.__tg_orient_timer) { clearInterval(window.__tg_orient_timer); window.__tg_orient_timer = null; }
            receiveEvent('device_orientation_stopped', JSON.stringify({}));
        },

        // Miscellaneous: no-ops for mobile-only and web-only lifecycle events.
        'web_app_hide_keyboard': function() {
            __tg_log('Hide keyboard (no-op on desktop)');
        },
        'iframe_ready': function(data) {
            __tg_log('iframe_ready (acknowledged)');
        },
        'iframe_will_reload': function() {
            __tg_log('iframe_will_reload (acknowledged)');
        },
    };

    // TelegramWebviewProxy: the global object that the Mini App SDK calls.
    // postEvent() is the single entry point — all SDK calls go through here.
    // Each event is dispatched asynchronously via setTimeout to avoid blocking the SDK.
    window.TelegramWebviewProxy = {
        postEvent: function(eventType, eventData) {
            __tg_log('postEvent:', eventType, eventData || '');
            var handler = handlers[eventType];
            if (handler) {
                setTimeout(function() { handler(eventData); }, 0);
            } else {
                __tg_log('Unhandled event:', eventType);
            }
        }
    };


    // Viewport: fire viewport_changed on window resize.
    // Sends immediate update (is_state_stable: false) + debounced final (is_state_stable: true).
    var __tg_resize_timer = null;
    window.addEventListener('resize', function() {
        if (__tg_resize_timer) clearTimeout(__tg_resize_timer);
        receiveEvent('viewport_changed', {
            height: window.innerHeight,
            is_state_stable: false,
            is_expanded: true
        });
        __tg_resize_timer = setTimeout(function() {
            receiveEvent('viewport_changed', {
                height: window.innerHeight,
                is_state_stable: true,
                is_expanded: true
            });
        }, 150);
    });

    // Window focus/blur → visibility_changed + activated/deactivated
    window.addEventListener('focus', function() {
        receiveEvent('visibility_changed', {is_visible: true});
        receiveEvent('activated');
    });
    window.addEventListener('blur', function() {
        receiveEvent('visibility_changed', {is_visible: false});
        receiveEvent('deactivated');
    });

    // Settings button keyboard shortcut (Cmd+, / Ctrl+,)
    document.addEventListener('keydown', function(e) {
        if ((e.metaKey || e.ctrlKey) && e.key === ',') {
            if (window.__tg_settings_visible && window.TelegramGameProxy) {
                e.preventDefault();
                TelegramGameProxy.receiveEvent('settings_button_pressed');
                __tg_log('Settings button triggered via keyboard shortcut');
            }
        }
    });

    __tg_log('TelegramWebviewProxy injected successfully');
})();
