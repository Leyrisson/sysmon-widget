#!/usr/bin/env python3
"""SysMon — relatório diário do sistema por e-mail (10h e 18h).

Coleta estado do sistema/hardware, testa a velocidade da internet,
numera erros do journal e tenta resolver automaticamente serviços do
usuário que falharam (reiniciando/resetando), e envia o relatório para o
próprio usuário via SMTP do Gmail.
"""

import json
import os
import re
import smtplib
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from pathlib import Path

HOME = Path.home()
PLUGIN_DIR = HOME / ".config" / "omarchy" / "plugins" / "sysmon"
ENV = Path(os.environ.get(
    "SYSMON_ENV", HOME / ".config" / "omarchy-voice" / "plugins" / "leitormail" / "credenciais.env"))
LOGF = HOME / ".local" / "state" / "sysmon" / "relatorio.log"

sys.path.insert(0, str(PLUGIN_DIR))
from poller import collect  # noqa: E402


def log(msg):
    LOGF.parent.mkdir(parents=True, exist_ok=True)
    with open(LOGF, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()} {msg}\n")


def fmt_bytes(n):
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.1f} {unit}"
        n /= 1024


def fmt_fmt_gb(gb):
    return f"{gb:.0f}G" if gb >= 10 else f"{gb:.1f}G"


def speed_test(down_bytes=30_000_000, up_bytes=12_000_000):
    """Teste de velocidade no endpoint público da Cloudflare."""
    res = {"download_mbps": 0.0, "upload_mbps": 0.0}
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"}
    try:
        req = urllib.request.Request(
            f"https://speed.cloudflare.com/__down?bytes={down_bytes}", headers=headers)
        start = time.time()
        total = 0
        with urllib.request.urlopen(req, timeout=40) as r:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                total += len(chunk)
        dur = time.time() - start
        if dur > 0:
            res["download_mbps"] = round(total * 8 / dur / 1e6, 2)
    except Exception as e:
        log(f"speed download erro: {e}")
    try:
        body = b"\0" * up_bytes
        req = urllib.request.Request(
            "https://speed.cloudflare.com/__up", data=body, method="POST",
            headers={**headers, "Content-Type": "application/octet-stream"})
        start = time.time()
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
        dur = time.time() - start
        if dur > 0:
            res["upload_mbps"] = round(len(body) * 8 / dur / 1e6, 2)
    except Exception as e:
        log(f"speed upload erro: {e}")
    return res


def uptime_str(seconds):
    if not seconds:
        return "—"
    h, rem = divmod(int(seconds), 3600)
    d, h = divmod(h, 24)
    m = rem // 60
    parts = []
    if d:
        parts.append(f"{d}d")
    parts.append(f"{h}h{m}m")
    return " ".join(parts)


def failed_units():
    by_scope = {"user": [], "system": []}
    for scope in by_scope:
        cmd = ["systemctl", "--user"] if scope == "user" else ["systemctl"]
        try:
            out = subprocess.run(
                cmd + ["--failed", "--no-legend", "--no-pager"],
                capture_output=True, text=True, timeout=10).stdout
            for line in out.splitlines():
                parts = line.split()
                if parts:
                    by_scope[scope].append(parts[0])
        except Exception:
            pass
    return by_scope


def try_resolve_failed_user(units):
    """Tenta resolver serviços do usuário que falharam.

    Depois de resetar/reiniciar reapareceram como ativos? Só contamos
    como resolvido o que saiu do estado failed.
    """
    resolved = []
    remaining = []
    for unit in units:
        try:
            subprocess.run(
                ["systemctl", "--user", "reset-failed", unit],
                capture_output=True, text=True, timeout=10)
            subprocess.run(
                ["systemctl", "--user", "try-restart", unit],
                capture_output=True, text=True, timeout=20)
        except Exception:
            pass
    # confirma o que sobrou falho
    try:
        out = subprocess.run(
            ["systemctl", "--user", "--failed", "--no-legend", "--no-pager"],
            capture_output=True, text=True, timeout=10).stdout
        still = {line.split()[0] for line in out.splitlines() if line.split()}
    except Exception:
        still = set(units)
    for unit in units:
        if unit in still:
            remaining.append(unit)
        else:
            resolved.append(unit)
    return resolved, remaining


def build_body(state, speed, failed, resolved, remaining):
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    ram = state["ram"]
    disk = state["disk"]
    gpu = state["gpu"]
    lines = []
    lines.append("RELATÓRIO SYS MONITOR — estado do sistema e hardware")
    lines.append(f"Gerado em: {now} (UTC-3) automático 10h/18h")
    lines.append("")
    lines.append("=== SISTEMA ===")
    lines.append(f"OS: Omarchy | kernel {_kernel()}")
    lines.append(f"Uptime: {uptime_str(state['uptime_s'])} | load (5m): {state['cpu_load']}")
    lines.append(f"CPU: {state['cpu_pct']}% de uso | {state['cpu_temp']}°C")
    lines.append(
        f"RAM: {fmt_fmt_gb(ram['used_mb'] / 1024)} usada de {ram['total_mb'] // 1024}G ({ram['pct']}%)")
    lines.append(
        f"DISCO /: {disk['used_gb']}G usados de {disk['total_gb']}G ({disk['pct']}%)")
    if gpu:
        lines.append(
            f"GPU: {gpu['name']} | {gpu['temp']}°C | {gpu['util']}% uso | "
            f"{gpu['mem_used']}MiB/{gpu['mem_total']}MiB")
    lines.append("")
    lines.append("=== INTERNET (agora) ===")
    lines.append(
        f"Download: {speed['download_mbps']:.2f} Mbps | Upload: {speed['upload_mbps']:.2f} Mbps")
    lines.append("")
    lines.append("=== ERROS ===")
    ativos = state["errors"] or 0
    avisos = state["err_avisos"] or 0
    total = state["err_total"] or 0
    lines.append(f"Erros ativos (distintos): {ativos}")
    lines.append(
        f"(total {total} ocorrências no journal — {avisos} são avisos conhecidos e inocentes: "
        "brilho DDC do monitor HDMI não suportado, TDX, WiFi e keyring no login)")
    if res := resolved:
        lines.append(f"Resolvidos automaticamente: {', '.join(res)}")
    if rem := remaining:
        lines.append(f"Serviços do usuário ainda com falha: {', '.join(rem)}")
    if fos := failed["system"]:
        lines.append(f"Serviços do sistema com falha (requer sudo): {', '.join(fos)}")
    resumo = state.get("err_resumo") or []
    if resumo:
        lines.append("Erros ativos encontrados:")
        lines.extend(f"  - {e}" for e in resumo)
    else:
        lines.append("Nenhum erro ativo encontrado.")
    lines.append("")
    lines.append("--- fim ---")
    return "\n".join(lines)


def _kernel():
    try:
        return subprocess.run(
            ["uname", "-r"], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return "?"


def send_mail(addr, pwd, body, subject):
    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = addr
    msg["To"] = addr
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="PCLEY")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=40) as s:
        s.login(addr, pwd)
        s.sendmail(addr, [addr], msg.as_string())


def load_creds():
    data = {}
    for line in ENV.read_text().splitlines():
        if line and "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    return data


def main():
    state = collect()
    speed = speed_test()
    failed = failed_units()
    resolved, remaining = try_resolve_failed_user(failed["user"])

    body = build_body(state, speed, failed, resolved, remaining)

    subject = f"SysMon {datetime.now().strftime('%d/%m %H:%M')} — "
    problem = bool(remaining) or bool(failed["system"]) or (state["errors"] or 0) > 0
    subject += "atenção a erros" if problem else "sistema ok"
    log(f"enviando relatório ({subject})")
    print(body)
    print("\n### envio ###")
    creds = load_creds()
    if not creds.get("GMAIL_ADDR") or not creds.get("GMAIL_PASS"):
        log("sem credenciais — não enviou")
        return 2
    send_mail(creds["GMAIL_ADDR"], creds["GMAIL_PASS"], body, subject)
    log("e-mail enviado")
    print(f"enviado -> {creds['GMAIL_ADDR']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())