"""Create a Hue Bridge application key and Entertainment client key.

Press the link button on the bridge while this runs. The result is written
to a JSON file with mode 0600; keep it out of version control.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings()


def register(host: str, out: Path, devicetype: str = "ambilight_hue_sync#host",
             timeout: float = 900, poll: float = 2) -> dict:
    deadline = time.time() + timeout
    print(f"Press the link button on the bridge at {host} (waiting {int(timeout)} s)")
    while time.time() < deadline:
        try:
            r = requests.post(f"https://{host}/api", verify=False, timeout=5,
                              json={"devicetype": devicetype, "generateclientkey": True}).json()
            ok = next((x["success"] for x in r if "success" in x), None)
            if ok:
                h = requests.get(f"https://{host}/auth/v1", verify=False, timeout=5,
                                 headers={"hue-application-key": ok["username"]})
                creds = {"username": ok["username"], "clientkey": ok["clientkey"],
                         "appid": h.headers.get("hue-application-id", "")}
                out.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as f:
                    json.dump(creds, f)
                print(f"Saved credentials to {out}")
                return creds
        except requests.RequestException as e:
            print("error:", e)
        time.sleep(poll)
    raise SystemExit("timed out waiting for the link button")
