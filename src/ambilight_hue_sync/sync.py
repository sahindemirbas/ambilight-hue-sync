"""Runtime: TV reader thread, Hue Entertainment stream, snapshot/restore."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time

import requests
import urllib3

from . import state
from .color import WHITE_XY, frame_targets
from .config import Config
from .protocol import packet
from .smoothing import smooth_step

urllib3.disable_warnings()


def log(*a):
    print(*a, flush=True)


class Sync:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.base = f"https://{cfg.hue_host}/clip/v2/resource"
        self.hue = requests.Session()
        self.hue.verify = False  # bridge uses a self signed certificate
        self.hue.headers["hue-application-key"] = cfg.hue_username
        # One session for the whole lifetime. Opening a new TLS + digest
        # handshake per request makes the TV API fall over (404/403) until
        # the TV is cold booted. Keep-alive avoids that entirely.
        self.tv = requests.Session()
        self.tv.verify = False
        self.tv.auth = requests.auth.HTTPDigestAuth(cfg.tv_username, cfg.tv_password)
        self.tv_url = f"https://{cfg.tv_host}:1926/6/ambilight/processed"
        self.target, self.lock = {}, threading.Lock()
        self.tv_on = threading.Event()
        self.health = state.TvHealth(cfg.interval, cfg.safe_interval)
        self.proc = None
        self.names = [lt.name for lt in cfg.lights]
        self.light_ids = {}
        self._resolve()

    # --- bridge setup ---
    def _get(self, kind):
        return self.hue.get(f"{self.base}/{kind}", timeout=5).json()["data"]

    def _resolve(self):
        cfgs = [c for c in self._get("entertainment_configuration")
                if c["metadata"]["name"] == self.cfg.area]
        if not cfgs:
            sys.exit(f"entertainment area {self.cfg.area!r} not found on the bridge")
        self.cfg_id = cfgs[0]["id"]
        ent = {e["id"]: e["owner"]["rid"] for e in self._get("entertainment")}
        self.devices = {d["id"]: d["metadata"]["name"] for d in self._get("device")}
        self.channels = state.resolve_channels(cfgs[0], ent, self.devices)
        missing = [n for n in self.names if n not in self.channels]
        if missing:
            sys.exit(f"lights not in area {self.cfg.area!r}: {missing}")

    # --- TV reader ---
    def tv_loop(self):
        h = self.health
        while True:
            t0 = time.time()
            try:
                r = self.tv.get(self.tv_url, timeout=2)
                r.raise_for_status()
                d = r.json()
                new = frame_targets(d.get("layer1", d), self.cfg.lights,
                                    self.cfg.top_first, self.cfg.dark)
                with self.lock:
                    self.target.update(new)
                h.ok()
                self.tv_on.set()
            except Exception as e:  # noqa: BLE001, any failure counts
                backoff = h.fail(time.time())
                log("tv error:", type(e).__name__, e)
                if not h.on:
                    self.tv_on.clear()
                time.sleep(backoff)
            iv = h.next_interval(time.time())
            time.sleep(max(0, iv - (time.time() - t0)))

    # --- snapshot / restore ---
    def snapshot(self):
        lights = self._get("light")
        self.light_ids = state.light_ids(lights, self.devices, self.names)
        path = self.cfg.snapshot_path
        if state.keep_existing_snapshot(lights, path.exists()):
            return
        snap = state.build_snapshot(lights, self.devices, self.names)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(snap))
        os.replace(tmp, path)
        log("lights saved:", snap)

    def restore(self):
        try:
            snap = json.loads(self.cfg.snapshot_path.read_text())
        except (OSError, ValueError):
            return
        time.sleep(1.0)  # let the bridge finish leaving streaming mode
        for name, st in snap.items():
            lid = self.light_ids.get(name)
            if not lid:
                continue
            try:
                r = self.hue.put(f"{self.base}/light/{lid}", json=state.restore_body(st), timeout=5)
                log("restored", name, r.status_code)
            except requests.RequestException as e:
                log("restore error", name, e)
            time.sleep(0.15)  # stay under the bridge rate limit
        self.cfg.snapshot_path.unlink(missing_ok=True)

    # --- streaming ---
    def ent_action(self, action):
        r = self.hue.put(f"{self.base}/entertainment_configuration/{self.cfg_id}",
                         json={"action": action}, timeout=5)
        log("entertainment", action, r.status_code, r.text[:150])

    def open_dtls(self):
        # Python has no DTLS in the standard library; openssl s_client does
        # DTLS 1.2 PSK fine and we just write packets to its stdin.
        p = subprocess.Popen(
            ["openssl", "s_client", "-dtls1_2", "-connect", f"{self.cfg.hue_host}:2100",
             "-psk_identity", self.cfg.hue_appid, "-psk", self.cfg.hue_clientkey,
             "-cipher", "PSK-AES128-GCM-SHA256", "-quiet", "-nocommands"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, bufsize=0)
        time.sleep(1.5)  # handshake
        if p.poll() is not None:
            raise RuntimeError("DTLS failed: " + p.stderr.read().decode(errors="replace")[-300:])
        return p

    def stop_stream(self):
        if self.proc:
            self.proc.kill()
            self.proc = None
            self.ent_action("stop")
            self.restore()

    def shutdown(self, *_):
        try:
            self.stop_stream()
        finally:
            os._exit(0)

    def run(self):
        signal.signal(signal.SIGTERM, self.shutdown)
        signal.signal(signal.SIGINT, self.shutdown)
        threading.Thread(target=self.tv_loop, daemon=True).start()
        cur = {n: (*WHITE_XY, 0.0) for n in self.names}
        seq, dt = 0, 1 / self.cfg.fps
        log(f"waiting for TV, area {self.cfg.area!r}, {len(self.names)} lights")
        while True:
            if not self.tv_on.wait(timeout=5):
                self.stop_stream()  # TV went off: lights go back to how they were
                continue
            if self.proc is None or self.proc.poll() is not None:
                try:
                    self.snapshot()
                    self.ent_action("start")
                    self.proc = self.open_dtls()
                    log("stream started")
                except Exception as e:  # noqa: BLE001
                    log("stream error:", e)
                    self.proc = None
                    time.sleep(5)
                    continue
            t0 = time.time()
            with self.lock:
                tg = dict(self.target)
            for n, t in tg.items():
                cur[n] = smooth_step(cur[n], t, dt, self.cfg.smoothing_for(n), self.cfg.dark)
            try:
                self.proc.stdin.write(packet(seq, self.cfg_id, cur, self.channels))
                seq += 1
            except (BrokenPipeError, OSError) as e:
                log("stream dropped:", e)
                self.proc = None
            time.sleep(max(0, dt - (time.time() - t0)))
