#!/usr/bin/env python3
"""Coleta estado do sistema/hardware e imprime JSON para o widget SysMon."""

import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

HOME = Path.home()
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", HOME / ".local" / "state")) / "sysmon"
STATE_FILE = STATE_DIR / "cpu_prev.json"
NET_FILE = STATE_DIR / "net_prev.json"
SPEED_FILE = STATE_DIR / "speed.json"
SPEED_MAX_AGE = 1800  # refaz o teste de velocidade a cada 30 min


def _first_temp(sensors_json, key):
    data = sensors_json
    for chip in data.values():
        if not isinstance(chip, dict):
            continue
        for label, props in chip.items():
            if key.lower() in label.lower() and isinstance(props, dict):
                val = props.get("temp1_input")
                if val is not None:
                    return val
    return None


def gpu():
    try:
        out = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
        parts = [p.strip() for p in out.stdout.strip().split(",")]
        if len(parts) != 5:
            return None
        name, temp, util, mused, mtotal = parts
        return {
            "name": name,
            "temp": float(temp),
            "util": float(util),
            "mem_used": int(mused),
            "mem_total": int(mtotal),
        }
    except Exception:
        return None


def cpu_temp():
    try:
        out = subprocess.run(["sensors", "-j"], capture_output=True, text=True, timeout=5)
        data = json.loads(out.stdout)
        t = _first_temp(data, "Package id")
        if t is None:
            t = _first_temp(data, "Tctl")
        if t is None:
            t = _first_temp(data, "temp1")
        return t
    except Exception:
        return None


def cpu_pct():
    now_total, now_idle = 0, 0
    try:
        with open("/proc/stat") as f:
            parts = [int(x) for x in f.readline().split()[1:]]
        now_total, now_idle = sum(parts), parts[3] + parts[4]
    except Exception:
        return None
    prev = None
    try:
        prev = json.loads(STATE_FILE.read_text())
    except Exception:
        prev = None
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"total": now_total, "idle": now_idle}))
    if not prev or now_total <= prev["total"]:
        return None
    dt = now_total - prev["total"]
    di = now_idle - prev["idle"]
    return round(100.0 * (dt - di) / dt, 1)


def cpu_load():
    try:
        return round(os.getloadavg()[1], 2)
    except OSError:
        return None


def ram():
    mem = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":", 1)
            mem[k] = int(v.split()[0])
    total = mem["MemTotal"]
    avail = mem["MemAvailable"]
    used = max(0, total - avail)
    return {"total_mb": total // 1024, "used_mb": used // 1024,
            "pct": round(100.0 * used / total, 1)}


def disk(path="/"):
    s = shutil.disk_usage(path)
    return {"total_gb": round(s.total / 2**30, 0), "used_gb": round(s.used / 2**30, 1),
            "pct": round(100.0 * s.used / s.total, 0)}


def uptime():
    try:
        with open("/proc/uptime") as f:
            return round(float(f.read().split()[0]))
    except Exception:
        return None


def error_summary():
    """Resumo de erros do journal do boot.

    Filtra ruído conhecido/inesperado (ddcutil sem DDC no HDMI, kernel TDX,
    wpa multicast, keyring no login), deduplica mensagens repetidas e devolve
    o número de erros ativos distintos (que importam de verdade).
    """
    ignore = (
        "ddcutil",                 # mon. Samsung não suporta DDC/CI (hardware)
        "virt/tdx",                # máquina sem suporte a TDX (informativo)
        "tdx not supported",
        "multicast rx",            # limite do driver wifi
        "login keyring",           # cosmético, 1x por login
    )
    signatures = {}
    try:
        out = subprocess.run(
            ["journalctl", "-b", "-p", "err", "--no-pager"],
            capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return {"total": 0, "ativos": 0, "avisos": 0, "resumo": []}
    for line in out.splitlines():
        if not line.strip():
            continue
        ident = "kernel"
        m = re.match(r"^[A-Za-z]{3} [0-9]{2} [0-9:]{8} [^ ]+ ([^[]+)", line)
        if m:
            ident = m.group(1).rstrip(" :")
        msg = line.split(": ", 1)[-1].strip() if ": " in line else line.strip()
        if not msg:
            continue
        sig = ident + "|" + " ".join(msg.split()[:7]).lower()
        signatures[sig] = msg
    noise = [sig for sig in signatures
             if any(pat in sig.lower() for pat in ignore)]
    keep = [msg for sig, msg in signatures.items() if sig not in noise]
    return {
        "total": len(signatures),
        "ativos": len(keep),
        "avisos": len(noise),
        "resumo": [m[:170] for m in keep[:8]],
    }


def _default_iface():
    try:
        with open("/proc/net/route") as f:
            for line in f.readlines()[1:]:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "00000000":
                    return parts[0]
    except Exception:
        pass
    return None


def _net_bytes():
    iface = _default_iface()
    rx = tx = 0
    try:
        with open("/proc/net/dev") as f:
            for line in f:
                if ":" not in line:
                    continue
                name, data = line.split(":", 1)
                name = name.strip()
                if iface:
                    if name != iface:
                        continue
                elif name == "lo":
                    continue
                fields = data.split()
                rx += int(fields[0])
                tx += int(fields[8])
    except Exception:
        return None
    return rx, tx


def net_live():
    """Taxa atual (Mbps) desde a última leitura, via contadores do /proc/net/dev."""
    cur = _net_bytes()
    if not cur:
        return {"down": None, "up": None}
    prev = None
    try:
        prev = json.loads(NET_FILE.read_text())
    except Exception:
        prev = None
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    NET_FILE.write_text(json.dumps({"rx": cur[0], "tx": cur[1], "t": now}))
    if not prev or cur[0] < prev.get("rx", 0):
        return {"down": None, "up": None}
    dt = now - prev.get("t", now)
    if dt <= 0:
        return {"down": None, "up": None}
    return {
        "down": round((cur[0] - prev["rx"]) * 8 / dt / 1e6, 2),
        "up": round((cur[1] - prev["tx"]) * 8 / dt / 1e6, 2),
    }


def _speed_run(down_bytes=10_000_000, up_bytes=5_000_000):
    res = {"download_mbps": 0.0, "upload_mbps": 0.0}
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"}
    req = urllib.request.Request(
        f"https://speed.cloudflare.com/__down?bytes={down_bytes}", headers=headers)
    start = time.time()
    total = 0
    with urllib.request.urlopen(req, timeout=30) as r:
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            total += len(chunk)
    dur = time.time() - start
    if dur > 0:
        res["download_mbps"] = round(total * 8 / dur / 1e6, 2)

    body = b"\0" * up_bytes
    req = urllib.request.Request(
        "https://speed.cloudflare.com/__up", data=body, method="POST",
        headers={**headers, "Content-Type": "application/octet-stream"})
    start = time.time()
    with urllib.request.urlopen(req, timeout=45) as r:
        r.read()
    dur = time.time() - start
    if dur > 0:
        res["upload_mbps"] = round(len(body) * 8 / dur / 1e6, 2)
    return res


def speed_cached(max_age=SPEED_MAX_AGE):
    """Teste de velocidade da Cloudflare, guardado em cache (sem repetir a cada poll)."""
    cache = {}
    try:
        cache = json.loads(SPEED_FILE.read_text())
    except Exception:
        cache = {}
    now = time.time()
    if now - cache.get("ts", 0) > max_age:
        try:
            r = _speed_run()
            cache = {"down": r["download_mbps"], "up": r["upload_mbps"], "ts": now}
        except Exception:
            cache = {"down": None, "up": None, "ts": now}  # evita tentar de novo em loop
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        SPEED_FILE.write_text(json.dumps(cache))
    age = int(now - cache["ts"]) if cache.get("ts") else None
    return {"down": cache.get("down"), "up": cache.get("up"), "age_s": age}


def collect():
    errs = error_summary()
    net = net_live()
    spd = speed_cached()
    info = {
        "cpu_temp": cpu_temp(),
        "cpu_pct": cpu_pct(),
        "cpu_load": cpu_load(),
        "ram": ram(),
        "disk": disk("/"),
        "gpu": gpu(),
        "net_down": net["down"],
        "net_up": net["up"],
        "speed_down": spd["down"],
        "speed_up": spd["up"],
        "speed_age_s": spd["age_s"],
        "uptime_s": uptime(),
        "errors": errs["ativos"],
        "err_total": errs["total"],
        "err_avisos": errs["avisos"],
        "err_resumo": errs["resumo"],
        "gen": int(time.time()),
    }
    return info


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=False))