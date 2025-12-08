from __future__ import annotations
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal, QUrl, QThread, pyqtSlot
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PyQt6.QtGui import QPixmap, QImage


class AsyncImageDownloadWorker(QObject):
    """Asynchronous sequential image downloader using QNetworkAccessManager.

    Downloads images one-by-one (keeps ordering) and emits progress, itemReady and finished.
    Supports `cancel()` which aborts the current in-flight request.
    """
    progress = pyqtSignal(int)            # current index
    itemReady = pyqtSignal(str, QPixmap)  # panel_id, pixmap
    itemError = pyqtSignal(str, str)      # url_or_panel_id, error message
    finished = pyqtSignal(str, int, int, bool)  # status, added, errors, cancelled

    def __init__(self, urls: list[str], out_dir: str, existing_count):
        super().__init__()
        import re
        self._urls = urls
        self._out_dir = out_dir
        self._cancel = False
        self._existing_count_cb = existing_count
        self._manager = QNetworkAccessManager(self)
        self._currentReply: QNetworkReply | None = None
        self._index = 0
        self._added = 0
        self._errors = 0
        self._data_uri_re = re.compile(r'^data:image/(png|jpeg|jpg|webp|gif);base64,(.+)$', re.IGNORECASE)

    def start(self):
        self._cancel = False
        self._index = 0
        self._added = 0
        self._errors = 0
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._start_next)

    def cancel(self):
        self._cancel = True
        if self._currentReply is not None:
            try:
                self._currentReply.abort()
            except Exception:
                pass
            try:
                self._currentReply.deleteLater()
            except Exception:
                pass
            self._currentReply = None

    def _start_next(self):
        from PyQt6.QtCore import QTimer, QUrl
        if self._cancel:
            status = "Cancelled"
            self.finished.emit(status, self._added, self._errors, True)
            return
        if self._index >= len(self._urls):
            status = "Completed"
            self.finished.emit(status, self._added, self._errors, False)
            return

        u = self._urls[self._index]
        idx = self._index + 1

        # Data URI case
        m = self._data_uri_re.match(u)
        if m:
            import base64, os
            try:
                ext, b64 = m.group(1), m.group(2)
                raw = base64.b64decode(b64)
                fname = f"data_{self._existing_count_cb()+1}.{ 'jpg' if ext=='jpeg' else ext }"
                path = os.path.join(self._out_dir, fname)
                with open(path, 'wb') as f:
                    f.write(raw)
                pm = QPixmap(path)
                if pm.isNull():
                    self._errors += 1
                    try:
                        self.itemError.emit(u, 'Decoded image is invalid')
                    except Exception:
                        pass
                else:
                    panel_id = f"scrape_{self._existing_count_cb()+1}"
                    self.itemReady.emit(panel_id, pm)
                    self._added += 1
            except Exception:
                self._errors += 1
                try:
                    import traceback
                    traceback.print_exc()
                except Exception:
                    pass
                try:
                    self.itemError.emit(u, 'Data URI decode or save failed')
                except Exception:
                    pass
            self.progress.emit(idx)
            self._index += 1
            QTimer.singleShot(0, self._start_next)
            return

        # Network download
        req = QNetworkRequest(QUrl(u))
        reply = self._manager.get(req)
        self._currentReply = reply
        reply.finished.connect(lambda: self._on_reply_finished(reply))
        reply.errorOccurred.connect(lambda err: self._on_reply_error(reply, err))

    def _on_reply_error(self, reply: QNetworkReply, err):
        from PyQt6.QtCore import QTimer
        # On certain SSL/handshake-related failures Qt's network stack can fail
        # while a Python-based fetch (requests/urllib) would succeed. Try a
        # threaded fallback before declaring the item failed.
        try:
            url = reply.url().toString() if hasattr(reply, 'url') else ''
        except Exception:
            url = ''
        try:
            errstr = reply.errorString() if hasattr(reply, 'errorString') else str(err)
        except Exception:
            errstr = str(err)

        ssl_indicators = ['ssl', 'handshake', 'unsupported function', 'certificate', 'secure']
        if url and any(k in errstr.lower() for k in ssl_indicators):
            # attempt fallback download using Python libraries in a QThread
            try:
                # delete the Qt reply early; we'll continue via fallback
                try:
                    reply.deleteLater()
                except Exception:
                    pass
                self._currentReply = None
                self._start_fallback_download(url)
                return
            except Exception:
                # if fallback setup fails, fall through to emit error below
                pass

        # Non-SSL or fallback not attempted/failed — emit per-item error and continue
        self._errors += 1
        try:
            self.itemError.emit(url or str(self._index), errstr)
        except Exception:
            pass
        idx = self._index + 1
        self.progress.emit(idx)
        try:
            reply.deleteLater()
        except Exception:
            pass
        self._currentReply = None
        self._index += 1
        QTimer.singleShot(0, self._start_next)

    def _start_fallback_download(self, url: str):
        """Start a fallback downloader in a QThread that tries requests then urllib."""
        class _FallbackWorker(QObject):
            ready = pyqtSignal(bytes)
            failed = pyqtSignal(str)
            finished = pyqtSignal()

            def __init__(self, url: str):
                super().__init__()
                self.url = url

            @pyqtSlot()
            def run(self):
                try:
                    try:
                        import requests
                        hdrs = {'User-Agent': 'Mozilla/5.0'}
                        r = requests.get(self.url, headers=hdrs, timeout=16, verify=False)
                        data = r.content
                    except Exception:
                        try:
                            import urllib.request, ssl
                            ctx = ssl.create_default_context()
                            ctx.check_hostname = False
                            ctx.verify_mode = ssl.CERT_NONE
                            with urllib.request.urlopen(self.url, context=ctx, timeout=16) as resp:
                                data = resp.read()
                        except Exception:
                            data = b''
                    if not data:
                        self.failed.emit('Fallback: empty response')
                    else:
                        self.ready.emit(data)
                except Exception as e:
                    try:
                        import traceback
                        traceback.print_exc()
                    except Exception:
                        pass
                    self.failed.emit(str(e))
                finally:
                    self.finished.emit()

        # Create worker/thread
        try:
            worker = _FallbackWorker(url)
            thread = QThread(self)
            worker.moveToThread(thread)
            # When data ready, handle it and continue to next item
            worker.ready.connect(lambda data: self._on_fallback_ready(url, data))
            worker.failed.connect(lambda err: self._on_fallback_failed(url, err))
            worker.finished.connect(thread.quit)
            thread.started.connect(worker.run)
            thread.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            # keep temporary references to avoid GC until finished
            if not hasattr(self, '_fallback_threads'):
                self._fallback_threads = []
            self._fallback_threads.append((thread, worker))
            thread.start()
        except Exception:
            # if fallback couldn't be started, mark as failed immediately
            self._errors += 1
            try:
                self.itemError.emit(url or str(self._index), 'Fallback start failed')
            except Exception:
                pass
            idx = self._index + 1
            self.progress.emit(idx)
            self._index += 1
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, self._start_next)

    def _on_fallback_ready(self, url: str, data: bytes):
        # Write file and emit itemReady if valid image
        try:
            import os
            url_path = url.split('?')[0]
            tail = url_path.split('/')[-1] or f"img_{self._existing_count_cb()+1}.bin"
            if '.' not in tail:
                tail += '.png'
            path = os.path.join(self._out_dir, tail)
            with open(path, 'wb') as f:
                f.write(data)
            pm = QPixmap()
            ok = pm.loadFromData(data)
            if not ok or pm.isNull():
                # try loading from saved file as fallback
                pm = QPixmap(path)
            if pm.isNull():
                self._errors += 1
                try:
                    self.itemError.emit(url, 'Fallback download produced invalid image')
                except Exception:
                    pass
            else:
                panel_id = f"scrape_{self._existing_count_cb()+1}"
                self.itemReady.emit(panel_id, pm)
                self._added += 1
        except Exception:
            self._errors += 1
            try:
                self.itemError.emit(url, 'Fallback save or decode failed')
            except Exception:
                pass
        # finalize this item and move to next
        idx = self._index + 1
        self.progress.emit(idx)
        self._index += 1
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._start_next)

    def _on_fallback_failed(self, url: str, errmsg: str):
        from PyQt6.QtCore import QTimer
        try:
            self._errors += 1
            self.itemError.emit(url, f'Fallback failed: {errmsg}')
        except Exception:
            pass
        idx = self._index + 1
        self.progress.emit(idx)
        self._index += 1
        QTimer.singleShot(0, self._start_next)

    def _on_reply_finished(self, reply: QNetworkReply):
        from PyQt6.QtCore import QTimer
        if reply.error() != QNetworkReply.NetworkError.NoError:
            return self._on_reply_error(reply, reply.error())
        try:
            data = bytes(reply.readAll())
            import os
            url_path = reply.url().path() or ''
            tail = url_path.split('/')[-1].split('?')[0] or f"img_{self._existing_count_cb()+1}.bin"
            if '.' not in tail:
                tail += '.png'
            path = os.path.join(self._out_dir, tail)
            with open(path, 'wb') as f:
                f.write(data)
            pm = QPixmap(path)
            if pm.isNull():
                self._errors += 1
                try:
                    self.itemError.emit(reply.url().toString(), 'Downloaded data is not a valid image')
                except Exception:
                    pass
            else:
                panel_id = f"scrape_{self._existing_count_cb()+1}"
                self.itemReady.emit(panel_id, pm)
                self._added += 1
        except Exception:
            self._errors += 1
            try:
                import traceback
                traceback.print_exc()
            except Exception:
                pass
            try:
                self.itemError.emit(reply.url().toString() if hasattr(reply, 'url') else str(self._index), 'Download or save failed')
            except Exception:
                pass
        idx = self._index + 1
        self.progress.emit(idx)
        try:
            reply.deleteLater()
        except Exception:
            pass
        self._currentReply = None
        self._index += 1
        QTimer.singleShot(0, self._start_next)


class AsyncImagePreviewer(QObject):
    """Asynchronous image fetcher using QNetworkAccessManager.

    - `fetch(url)` starts a new request, aborting any active request.
    - Emits `ready(QPixmap)` on success, `failed(str)` on error.
    - No extra QThread required — runs on the Qt event loop.
    """
    ready = pyqtSignal(QPixmap)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._manager = QNetworkAccessManager(self)
        self._currentReply: QNetworkReply | None = None
        self._currentUrl: str | None = None
        self._fallbackThread: QThread | None = None
        self._fallbackWorker: QObject | None = None

    def fetch(self, url: str):
        # Abort any in-flight request
        if self._currentReply is not None:
            try:
                self._currentReply.abort()
            except Exception:
                pass
            self._currentReply.deleteLater()
            self._currentReply = None
        self._currentUrl = url
        req = QNetworkRequest(QUrl(url))
        reply = self._manager.get(req)
        self._currentReply = reply

        # Bind handlers
        reply.finished.connect(lambda: self._onFinished(reply))
        reply.errorOccurred.connect(lambda err: self._onError(reply, err))

    def abort(self):
        if self._currentReply is not None:
            try:
                self._currentReply.abort()
            except Exception:
                pass
            self._currentReply.deleteLater()
            self._currentReply = None

    def _onError(self, reply: QNetworkReply, err):
        try:
            errstr = reply.errorString() if hasattr(reply, 'errorString') else str(err)
        except Exception:
            errstr = str(err)
        # If SSL handshake related, attempt a Python-based fallback download in a thread
        url_str = ''
        try:
            url_str = reply.url().toString()
        except Exception:
            url_str = self._currentUrl or ''

        # common indicator text for SSL handshake issues
        ssl_indicators = ['ssl', 'handshake', 'unsupported function', 'certificate', 'secure']
        if any(k in errstr.lower() for k in ssl_indicators) and url_str:
            try:
                # Start fallback downloader in a QThread to avoid blocking UI
                class _FallbackWorker(QObject):
                    finished = pyqtSignal()
                    ready = pyqtSignal(QPixmap)
                    failed = pyqtSignal(str)

                    def __init__(self, url: str):
                        super().__init__()
                        self.url = url

                    @pyqtSlot()
                    def run(self):
                        try:
                            # Prefer requests if available (disable verify to bypass cert issues)
                            try:
                                import requests
                                hdrs = {'User-Agent': 'Mozilla/5.0'}
                                r = requests.get(self.url, headers=hdrs, timeout=12, verify=False)
                                data = r.content
                            except Exception:
                                # Fallback to urllib with unverified SSL context
                                try:
                                    import urllib.request, ssl
                                    ctx = ssl.create_default_context()
                                    ctx.check_hostname = False
                                    ctx.verify_mode = ssl.CERT_NONE
                                    with urllib.request.urlopen(self.url, context=ctx, timeout=12) as resp:
                                        data = resp.read()
                                except Exception as e:
                                    raise
                            pm = QPixmap()
                            ok = pm.loadFromData(data)
                            if not ok or pm.isNull():
                                self.failed.emit('Fallback decode failed')
                            else:
                                self.ready.emit(pm)
                        except Exception as e:
                            self.failed.emit(str(e))
                        finally:
                            self.finished.emit()

                # Clean up any existing fallback
                try:
                    if self._fallbackThread is not None:
                        self._fallbackThread.quit()
                        self._fallbackThread.wait(100)
                except Exception:
                    pass

                worker = _FallbackWorker(url_str)
                thread = QThread(self)
                worker.moveToThread(thread)
                worker.ready.connect(lambda pm: (self.ready.emit(pm)))
                worker.failed.connect(lambda e: self.failed.emit(f"Fallback failed: {e}"))
                worker.finished.connect(thread.quit)
                thread.started.connect(worker.run)
                thread.finished.connect(worker.deleteLater)
                thread.finished.connect(thread.deleteLater)
                self._fallbackThread = thread
                self._fallbackWorker = worker
                thread.start()
                # return early; don't emit original failure yet
                try:
                    reply.deleteLater()
                except Exception:
                    pass
                self._currentReply = None
                return
            except Exception:
                pass

        self.failed.emit(errstr)
        try:
            reply.deleteLater()
        except Exception:
            pass
        if self._currentReply is reply:
            self._currentReply = None
        self.finished.emit()

    def _onFinished(self, reply: QNetworkReply):
        # If the reply reports an error, route to error handler.
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._onError(reply, reply.error())
            return
        try:
            data = bytes(reply.readAll())
            pm = QPixmap()
            ok = pm.loadFromData(data)
            if not ok or pm.isNull():
                self.failed.emit("Invalid image data")
            else:
                self.ready.emit(pm)
        except Exception as e:
            self.failed.emit(f"Decode error: {e}")
        try:
            reply.deleteLater()
        except Exception:
            pass
        if self._currentReply is reply:
            self._currentReply = None
        self.finished.emit()


class OcrWorker(QObject):
    """Worker that performs OCR on one or more panels in a background QThread.

    Emits:
        - finished(panel_id, blocks): for each panel processed
        - error(panel_id, errmsg): for per-panel errors
        - progress(done, total): after each panel
        - finished(done): when all panels are done
    """
    itemFinished = pyqtSignal(str, list)
    itemError = pyqtSignal(str, str)
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(int)

    def __init__(self, items, lang: str = 'jpn', ocr_engine=None, conf_thresh: int = 0, preprocess: bool = True):
        """
        items: list of (panel_id, crops) or (panel_id, QImage), or a single tuple
        ocr_engine: preloaded OCR engine (optional, for single-panel use)
        """
        super().__init__()
        # Normalize input to always be a list of (panel_id, crops) tuples
        if isinstance(items, tuple) and len(items) == 2:
            self._items = [items]
        elif isinstance(items, list):
            # If it's a list of crops/images, treat as single panel
            if items and not (isinstance(items[0], tuple) and len(items[0]) == 2):
                self._items = [('panel', items)]  # Use a dummy panel_id if not provided
            else:
                self._items = items
        else:
            raise ValueError("OcrWorker items must be a tuple or list")
        self.ocr_engine = ocr_engine
        self.lang = lang
        self.conf_thresh = conf_thresh
        self.preprocess = preprocess
        self._cancel = False

    def cancel(self):
        self._cancel = True

    @pyqtSlot()
    def run(self):
        import traceback
        done = 0
        total = len(self._items)
        # Use provided ocr_engine or create one (for batch)
        ocr = self.ocr_engine
        if ocr is None:
            from MangaWebTranslator.services.ocr.ocr_adapter import create_ocr
            ocr = create_ocr()
        for item in self._items:
            # Defensive unpacking
            if isinstance(item, tuple) and len(item) == 2:
                panel_id, crops = item
            else:
                panel_id, crops = 'panel', item
            if self._cancel:
                break
            try:
                # Accept either a single image or a list of crops
                crop_list = crops if isinstance(crops, list) else [crops]
                print(f"[OCR] OCRing {panel_id} with {len(crop_list)} crops (lang={self.lang} preprocess={self.preprocess} conf={self.conf_thresh})")
                results = []
                for idx, crop in enumerate(crop_list):
                    print(f"[OCR] Crop {idx+1} type: {type(crop).__name__}")
                    if not hasattr(ocr, 'extract_blocks'):
                        print("[OCR] ERROR: Provided ocr_engine does not have extract_blocks method.")
                        results.append([])
                        continue
                    if not (hasattr(crop, 'size') or hasattr(crop, 'width')):
                        print(f"[OCR] WARNING: Crop {idx+1} is not an image. Value: {crop}")
                    try:
                        blocks = ocr.extract_blocks(crop, lang=self.lang, preprocess=self.preprocess, conf_thresh=self.conf_thresh)
                        results.append(blocks)
                    except Exception as e:
                        print(f"[OCR] Error in crop {idx+1}: {e}")
                        try:
                            traceback.print_exc()
                        except Exception:
                            pass
                        results.append([])
                # Flatten results for display logic
                flat_results = [block for blocks in results for block in blocks]
                self.itemFinished.emit(panel_id, flat_results)
            except Exception as e:
                try:
                    traceback.print_exc()
                except Exception:
                    pass
                self.itemError.emit(panel_id, str(e))
            done += 1
            self.progress.emit(done, total)
        self.finished.emit(done)
