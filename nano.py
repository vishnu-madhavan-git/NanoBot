"""
nano.py — NanoBot (JARVIS mode)
One file. Runs local or cloud. Carries memory via Telegram.

LLM    : Gemini 1.5 Flash → Grok grok-2-1212
Memory : state.json + Telegram SavedMessages (NANO_STATE:)
PC     : subprocess / mss / PowerShell (local only)
Agent  : DuckDuckGo idle study, system health monitor, morning briefing
"""

import asyncio
import io
import json
import os
import random
import re
import subprocess
import threading
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Callable

# ── Config ─────────────────────────────────────────────────────────────────────

def _load_cfg() -> dict:
    cfg = {}
    p = Path(__file__).parent / "secrets.json"
    if p.exists():
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_OWNER_ID",
              "GEMINI_API_KEY", "GROK_API_KEY", "GROK_MODEL"):
        v = os.getenv(k)
        if v:
            cfg[k.lower()] = int(v) if k == "TELEGRAM_OWNER_ID" else v
    return cfg

CFG = _load_cfg()
OWNER_ID: int = int(CFG.get("telegram_owner_id", 0))

# ── Environment ────────────────────────────────────────────────────────────────

IS_LOCAL = Path("C:/Users/VM-openclaw").exists()
IS_CLOUD = bool(os.getenv("PORT") or os.getenv("REPL_ID") or os.getenv("RAILWAY_ENVIRONMENT"))
START_TIME = datetime.utcnow()

# ── Logging ────────────────────────────────────────────────────────────────────

_LOG_FILE = Path(__file__).parent / "nano.log"

def _log(tag: str, msg: str = ""):
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {tag}" + (f" | {msg}" if msg else "")
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
    except Exception:
        pass

# ── State ──────────────────────────────────────────────────────────────────────

_state_lock = threading.Lock()
_STATE: dict = {
    "topics": [
        "AI and LLM developments",
        "Python automation tips",
        "Cybersecurity news",
        "Windows 11 productivity",
        "Telegram bot development",
        "Business automation tools",
        "Rust programming",
    ],
    "knowledge": {},
    "history": [],
    "reminders": [],
    "autostudy": True,
    "sysmon": True,
    "briefing_hour": 9,   # 24h UTC for morning briefing
}

def _gs(key: str, default=None):
    with _state_lock:
        return _STATE.get(key, default)

def _ss(key: str, value):
    with _state_lock:
        _STATE[key] = value

def _state_copy() -> dict:
    with _state_lock:
        return json.loads(json.dumps(_STATE))

# ── LLM: Gemini 1.5 Flash → Grok ───────────────────────────────────────────────

_SYSTEM = (
    "You are Jai, a personal AI assistant — sharp, proactive, and concise like JARVIS. "
    "You help with automation, coding, research, and PC control. "
    "Respond in plain conversational text. No markdown unless asked. "
    "If asked to do something you can't, say so briefly and suggest an alternative."
)

def _load_qwen_token() -> tuple[str, str] | None:
    creds_path = Path.home() / ".qwen" / "oauth_creds.json"
    try:
        if creds_path.exists():
            creds = json.loads(creds_path.read_text(encoding="utf-8"))
            url = f"https://{creds['resource_url']}/v1"
            return creds["access_token"], url
    except Exception:
        pass
    return None

def ask_llm(history: list[dict], prompt: str, system: str | None = None) -> str:
    from openai import OpenAI

    sys_msg = system or _SYSTEM
    msgs = [{"role": "system", "content": sys_msg}]
    msgs += history[-6:]
    msgs.append({"role": "user", "content": prompt})

    # 1. Qwen OAuth (Primary)
    qwen = _load_qwen_token()
    if qwen:
        token, base_url = qwen
        try:
            client = OpenAI(api_key=token, base_url=base_url, timeout=15.0)
            resp = client.chat.completions.create(
                model="qwen3-coder-plus", messages=msgs, max_tokens=600,
            )
            ans = resp.choices[0].message.content.strip()
            _log("LLM:qwen", f"ok {len(ans)}c")
            return ans
        except Exception as e:
            _log("LLM:qwen", f"failed: {e}")

    # 2. Gemini 1.5 Flash
    gemini_key = CFG.get("gemini_api_key", "")
    if gemini_key and not gemini_key.startswith("YOUR_"):
        try:
            client = OpenAI(
                api_key=gemini_key,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                timeout=20.0,
            )
            # Use 'gemini-1.5-flash' (confirmed available via list)
            resp = client.chat.completions.create(
                model="gemini-1.5-flash", messages=msgs, max_tokens=600
            )
            ans = resp.choices[0].message.content.strip()
            _log("LLM:gemini", f"ok {len(ans)}c")
            return ans
        except Exception as e:
            _log("LLM:gemini", f"failed: {e}")

    # 3. Grok (Fallback)
    grok_key = CFG.get("grok_api_key", "")
    if grok_key and not grok_key.startswith("YOUR_"):
        try:
            client = OpenAI(api_key=grok_key, base_url="https://api.x.ai/v1", timeout=20.0)
            resp = client.chat.completions.create(
                model=CFG.get("grok_model", "grok-2-1212"),
                messages=msgs, max_tokens=600,
            )
            ans = resp.choices[0].message.content.strip()
            _log("LLM:grok", f"ok {len(ans)}c")
            return ans
        except Exception as e:
            _log("LLM:grok", f"failed: {e}")

    return "⚠️ I'm here, but my LLM brains are unavailable: Qwen (401), Gemini (Quota/404), Grok (403). Please check your API keys and credits."

# ── Auth guard ─────────────────────────────────────────────────────────────────

def owner_only(fn: Callable) -> Callable:
    @wraps(fn)
    async def _w(update, context, *a, **k):
        uid = getattr(getattr(update, "effective_user", None), "id", None)
        if uid != OWNER_ID:
            _log("AUTH:deny", f"uid={uid}")
            if getattr(update, "effective_message", None):
                await update.effective_message.reply_text("⛔ Not authorised.")
            return
        return await fn(update, context, *a, **k)
    return _w

# ── Shell guard ────────────────────────────────────────────────────────────────

_BLOCKED = {
    "..", "../", "..\\", "%2e%2e",
    "&&", "||", ";", "|", "`", "$(", ">", ">>", "<", "\n", "\r",
    "cmd /c", "powershell -enc", "powershell -command",
    "bash -c", "sh -c", "python -c",
    "curl ", "wget ", "invoke-webrequest", "invoke-expression", "iex ",
    "reg add ", "reg delete ", "del ", "erase ", "rmdir ", "rm -",
    "mkfs", "format ", "shutdown", "reboot", "taskkill /f",
    "bcdedit", "diskpart", "passwd",
}
_INJECT_RE = re.compile(
    r'(^|[\\/])\.\.([\\/]|$)|[;&|`]|(?:\$\()'
    r'|(?:\b(?:cmd|powershell|bash|sh|python)\b.*(?:/c|-c))',
    re.I,
)

def _is_blocked(cmd: str) -> bool:
    s = cmd.strip().lower()
    return any(t in s for t in _BLOCKED) or bool(_INJECT_RE.search(s))

def _cloud_only() -> str:
    return "☁️ PC control unavailable in cloud mode."

# ── PC helpers ─────────────────────────────────────────────────────────────────

def _shell(cmd: str, timeout: int = 12) -> str:
    if not IS_LOCAL:
        return _cloud_only()
    if _is_blocked(cmd):
        return "❌ Blocked by security policy."
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout + r.stderr).strip()
        return out[:3500] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "⏱️ Timed out."
    except Exception as e:
        return f"Error: {e}"

def _screenshot() -> bytes | None:
    if not IS_LOCAL:
        return None
    try:
        import mss, mss.tools
        with mss.mss() as sct:
            img = sct.grab(sct.monitors[0])
            buf = io.BytesIO()
            mss.tools.to_png(img.rgb, img.size, output=buf)
            return buf.getvalue()
    except Exception:
        return None

def _sysinfo_raw() -> dict:
    """Returns dict with cpu%, mem%, disk% (Windows only)."""
    if not IS_LOCAL:
        return {}
    try:
        ps = (
            'powershell -NoProfile -c "'
            '$cpu=[math]::Round((Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average,1);'
            '$os=Get-CimInstance Win32_OperatingSystem;'
            '$mem=[math]::Round(($os.TotalVisibleMemorySize-$os.FreePhysicalMemory)/$os.TotalVisibleMemorySize*100,1);'
            '$disk=Get-PSDrive C|Select-Object Used,Free;'
            '$total=$disk.Used+$disk.Free;'
            '$diskp=[math]::Round($disk.Used/$total*100,1);'
            'Write-Output \"$cpu $mem $diskp\""'
        )
        r = subprocess.run(ps, shell=True, capture_output=True, text=True, timeout=10)
        parts = r.stdout.strip().split()
        if len(parts) == 3:
            return {"cpu": float(parts[0]), "mem": float(parts[1]), "disk": float(parts[2])}
    except Exception:
        pass
    return {}

# ── DuckDuckGo search ──────────────────────────────────────────────────────────

def _search(query: str, n: int = 5) -> list[dict]:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=n))
    except Exception:
        return []

# ── Memory ─────────────────────────────────────────────────────────────────────

_STATE_FILE = Path(__file__).parent / "state.json"
_NANO_TAG = "NANO_STATE:"

def _save_state():
    try:
        data = _state_copy()
        data["history"] = data["history"][-8:]
        kb = data.get("knowledge", {})
        if len(kb) > 40:
            data["knowledge"] = {k: kb[k] for k in sorted(kb.keys())[-30:]}
        _STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        _log("STATE:save_err", str(e))

def _load_state():
    if _STATE_FILE.exists():
        try:
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            with _state_lock:
                _STATE.update(data)
            _log("STATE:loaded", f"kb={len(_STATE.get('knowledge',{}))}")
        except Exception as e:
            _log("STATE:load_err", str(e))
    env_state = os.getenv("NANO_STATE_JSON")
    if env_state:
        try:
            with _state_lock:
                _STATE.update(json.loads(env_state))
            _log("STATE:env_loaded")
        except Exception:
            pass

async def _push_to_telegram(bot):
    if not OWNER_ID:
        return
    _save_state()
    try:
        data = _state_copy()
        data["history"] = data["history"][-4:]
        kb = data.get("knowledge", {})
        data["knowledge"] = {k: kb[k] for k in sorted(kb.keys())[-10:]}
        payload = _NANO_TAG + json.dumps(data, ensure_ascii=False)
        await bot.send_message(
            OWNER_ID,
            f"🧠 *Jai brain synced* — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"`{payload[:300]}...`",
            parse_mode="Markdown",
        )
        _log("STATE:synced", "pushed to Telegram")
    except Exception as e:
        _log("STATE:sync_err", str(e))

# ── Background: Reminders ──────────────────────────────────────────────────────

async def _reminder_loop(bot):
    while True:
        await asyncio.sleep(30)
        now = datetime.utcnow()
        reminders = _gs("reminders", [])
        due = [r for r in reminders if datetime.fromisoformat(r["due"]) <= now]
        if due:
            remaining = [r for r in reminders if r not in due]
            _ss("reminders", remaining)
            _save_state()
            for r in due:
                try:
                    await bot.send_message(OWNER_ID, f"⏰ *Reminder:* {r['msg']}", parse_mode="Markdown")
                except Exception:
                    pass

# ── Background: System monitor ─────────────────────────────────────────────────

_last_alert: dict = {}

async def _sysmon_loop(bot):
    await asyncio.sleep(120)
    while True:
        await asyncio.sleep(300)   # check every 5 min
        if not _gs("sysmon", True) or not IS_LOCAL:
            continue
        try:
            info = await asyncio.to_thread(_sysinfo_raw)
            if not info:
                continue
            now = datetime.utcnow()
            alerts = []
            if info.get("cpu", 0) > 90:
                key = "cpu"
                if (now - _last_alert.get(key, datetime.min)).total_seconds() > 1800:
                    alerts.append(f"🔥 CPU at {info['cpu']}%!")
                    _last_alert[key] = now
            if info.get("mem", 0) > 90:
                key = "mem"
                if (now - _last_alert.get(key, datetime.min)).total_seconds() > 1800:
                    alerts.append(f"🧠 RAM at {info['mem']}%!")
                    _last_alert[key] = now
            if info.get("disk", 0) > 95:
                key = "disk"
                if (now - _last_alert.get(key, datetime.min)).total_seconds() > 3600:
                    alerts.append(f"💾 Disk C: at {info['disk']}%!")
                    _last_alert[key] = now
            if alerts:
                await bot.send_message(OWNER_ID, " ".join(alerts))
        except Exception as e:
            _log("SYSMON:err", str(e))

# ── Background: Idle study agent ───────────────────────────────────────────────

_last_activity = {"time": datetime.utcnow()}

async def _idle_loop(bot):
    await asyncio.sleep(90)
    last_collect = datetime.utcnow() - timedelta(hours=1)
    last_briefing_day = None

    while True:
        await asyncio.sleep(60)
        now = datetime.utcnow()

        # Morning briefing
        briefing_hour = _gs("briefing_hour", 9)
        if (now.hour == briefing_hour
                and last_briefing_day != now.date()
                and OWNER_ID):
            last_briefing_day = now.date()
            try:
                digest = _build_digest(hours=24)
                await bot.send_message(
                    OWNER_ID,
                    f"☀️ *Good morning — Jai briefing*\n\n{digest}",
                    parse_mode="Markdown",
                )
            except Exception:
                pass

        # Idle study
        if not _gs("autostudy", True):
            continue
        idle_secs = (now - _last_activity["time"]).total_seconds()
        if idle_secs < 20 * 60:
            continue
        if (now - last_collect).total_seconds() < 55 * 60:
            continue

        try:
            topics = _gs("topics", [])
            if not topics:
                continue
            topic = random.choice(topics)
            results = await asyncio.to_thread(_search, topic, 4)
            if not results:
                continue
            ctx = "\n".join(
                f"- {r.get('title','')}: {r.get('body','')[:150]}" for r in results
            )
            summary = await asyncio.to_thread(
                ask_llm, [],
                f"Summarise in 2-3 bullets about '{topic}':\n{ctx}",
                "You are a research assistant. Give concise factual summaries."
            )
            key = now.isoformat()
            with _state_lock:
                _STATE["knowledge"][key] = {"topic": topic, "summary": summary}
                kb = _STATE["knowledge"]
                if len(kb) > 40:
                    for old in sorted(kb.keys())[:-30]:
                        del kb[old]
            _save_state()
            last_collect = now
            _log("IDLE:study", f"topic={topic}")

            today_count = sum(
                1 for k in _gs("knowledge", {}) if k.startswith(now.strftime("%Y-%m-%d"))
            )
            if today_count % 3 == 0:
                await bot.send_message(
                    OWNER_ID,
                    f"🧠 *Jai learned {today_count} things today.*\n"
                    f"Latest: {topic}\n/digest to read.",
                    parse_mode="Markdown",
                )
        except Exception as e:
            _log("IDLE:err", str(e))

def _build_digest(hours: int = 24) -> str:
    kb = _gs("knowledge", {})
    if not kb:
        return "No knowledge collected yet."
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    recent = {k: v for k, v in kb.items() if datetime.fromisoformat(k) >= cutoff}
    if not recent:
        return f"Nothing collected in last {hours}h."
    lines = [f"📚 {len(recent)} entries (last {hours}h)\n"]
    for ts, e in sorted(recent.items()):
        t = datetime.fromisoformat(ts).strftime("%H:%M")
        lines.append(f"[{t}] *{e['topic']}*\n{e['summary']}\n")
    return "\n".join(lines)[:3800]

# ── Command handlers ────────────────────────────────────────────────────────────

@owner_only
async def cmd_start(update, _ctx):
    env = "🖥️ Local PC" if IS_LOCAL else "☁️ Cloud"
    await update.message.reply_text(
        f"⚡ *Jai online* — {env}\n\n"
        "Just talk to me naturally.\n\n"
        "🖥️ PC: /ss /run /open /kill /ls /sysinfo\n"
        "🧠 Brain: /digest /topics /sync /autostudy\n"
        "🔍 Search: /search <query>\n"
        "📋 Plan: /plan <goal>\n"
        "⏰ Reminders: /remind <Xm|Xh> <msg>\n"
        "📊 Monitor: /sysmon on|off\n"
        "⚙️ Other: /status /clear /help",
        parse_mode="Markdown",
    )

@owner_only
async def cmd_help(update, _ctx):
    await update.message.reply_text(
        "*Jai — Command Reference*\n\n"
        "💬 *AI*\n"
        "  Just type anything — I'm listening\n"
        "  /clear — reset chat history\n"
        "  /status — system status\n\n"
        "🖥️ *PC Control (local only)*\n"
        "  /ss — screenshot\n"
        "  /run <cmd> — shell command\n"
        "  /open <app|url> — launch\n"
        "  /kill <process.exe> — kill\n"
        "  /ls [path] — list directory\n"
        "  /sysinfo — CPU / RAM / disk\n\n"
        "🔍 *Research*\n"
        "  /search <query> — web search + AI summary\n"
        "  /plan <goal> — break down a goal\n\n"
        "🧠 *Knowledge*\n"
        "  /digest — today's learning\n"
        "  /topics — manage study topics\n"
        "  /autostudy on|off\n"
        "  /sync — save brain\n\n"
        "⏰ *Reminders*\n"
        "  /remind 30m check email\n"
        "  /remind 2h meeting\n\n"
        "📊 *Monitor*\n"
        "  /sysmon on|off — system health alerts",
        parse_mode="Markdown",
    )

@owner_only
async def cmd_status(update, _ctx):
    gemini_ok = bool(CFG.get("gemini_api_key", "").strip("YOUR_"))
    grok_ok = bool(CFG.get("grok_api_key", "").strip("YOUR_"))
    uptime = str(datetime.utcnow() - START_TIME).split(".")[0]
    env = "🖥️ Local" if IS_LOCAL else "☁️ Cloud"
    kb = len(_gs("knowledge", {}))
    reminders = len(_gs("reminders", []))
    sysmon = _gs("sysmon", True)
    study = _gs("autostudy", True)
    lines = [
        f"⚡ *Jai Status* — {env}",
        f"Uptime: {uptime}",
        f"Gemini Flash: {'✅' if gemini_ok else '❌'}",
        f"Grok:         {'✅' if grok_ok else '❌'}",
        f"Knowledge:    {kb} entries",
        f"Topics:       {len(_gs('topics', []))}",
        f"Reminders:    {reminders} pending",
        f"Auto-study:   {'on' if study else 'off'}",
        f"Sysmon:       {'on' if sysmon else 'off'}",
    ]
    if IS_LOCAL:
        info = await asyncio.to_thread(_sysinfo_raw)
        if info:
            lines.append(f"CPU: {info.get('cpu')}%  RAM: {info.get('mem')}%  Disk: {info.get('disk')}%")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

@owner_only
async def cmd_clear(update, _ctx):
    _ss("history", [])
    await update.message.reply_text("🧹 Chat history cleared.")

@owner_only
async def cmd_sync(update, ctx):
    await update.message.reply_text("💾 Syncing…")
    await _push_to_telegram(ctx.bot)
    await update.message.reply_text("✅ Brain synced.")

@owner_only
async def cmd_ss(update, _ctx):
    if not IS_LOCAL:
        await update.message.reply_text(_cloud_only())
        return
    await update.message.reply_text("📸 Capturing…")
    data = await asyncio.to_thread(_screenshot)
    if data:
        await update.message.reply_photo(photo=io.BytesIO(data), caption="📸 Screenshot")
    else:
        await update.message.reply_text("❌ Screenshot failed — try /run powershell Get-Process")

@owner_only
async def cmd_run(update, ctx):
    if not ctx.args:
        await update.message.reply_text("Usage: /run <command>")
        return
    cmd = " ".join(ctx.args)
    out = await asyncio.to_thread(_shell, cmd)
    await update.message.reply_text(f"```\n{out}\n```", parse_mode="Markdown")

@owner_only
async def cmd_open(update, ctx):
    if not IS_LOCAL:
        await update.message.reply_text(_cloud_only())
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /open <app or URL>")
        return
    target = " ".join(ctx.args)
    if _is_blocked(target):
        await update.message.reply_text("❌ Blocked.")
        return
    await asyncio.to_thread(_shell, f'start "" "{target}"')
    await update.message.reply_text(f"🚀 Launched: {target}")

@owner_only
async def cmd_kill(update, ctx):
    if not IS_LOCAL:
        await update.message.reply_text(_cloud_only())
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /kill <process.exe>")
        return
    name = ctx.args[0]
    if not re.match(r'^[\w\-\.]+\.(exe|bat|cmd)$', name, re.I):
        await update.message.reply_text("❌ Invalid process name.")
        return
    out = await asyncio.to_thread(_shell, f"taskkill /F /IM {name}")
    await update.message.reply_text(out[:1000])

@owner_only
async def cmd_ls(update, ctx):
    if not IS_LOCAL:
        await update.message.reply_text(_cloud_only())
        return
    base = Path("C:/Users/VM-openclaw/EliteBook")
    p = base
    if ctx.args:
        candidate = Path(" ".join(ctx.args))
        if not candidate.is_absolute():
            candidate = base / candidate
        if not str(candidate.resolve()).startswith(str(base.resolve())):
            await update.message.reply_text("❌ Access denied outside EliteBook.")
            return
        p = candidate
    try:
        entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        lines = [f"{'📁' if e.is_dir() else '📄'} {e.name}" for e in entries[:50]]
        await update.message.reply_text(f"`{p}`\n" + "\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

@owner_only
async def cmd_sysinfo(update, _ctx):
    if not IS_LOCAL:
        await update.message.reply_text(_cloud_only())
        return
    await update.message.reply_text("📊 Checking…")
    ps = (
        'powershell -NoProfile -c "'
        'Write-Output \"OS: $((Get-CimInstance Win32_OperatingSystem).Caption)\";'
        'Write-Output \"CPU: $((Get-CimInstance Win32_Processor).Name)\";'
        '$cpu=[math]::Round((Get-CimInstance Win32_Processor).LoadPercentage,1);'
        'Write-Output \"CPU Load: $cpu%\";'
        '$os=Get-CimInstance Win32_OperatingSystem;'
        '$mem=[math]::Round(($os.TotalVisibleMemorySize-$os.FreePhysicalMemory)/1MB,1);'
        '$total=[math]::Round($os.TotalVisibleMemorySize/1MB,1);'
        'Write-Output \"RAM: $mem GB / $total GB\";'
        '$disk=Get-PSDrive C|Select-Object Used,Free;'
        '$u=[math]::Round($disk.Used/1GB,1);$f=[math]::Round($disk.Free/1GB,1);'
        'Write-Output \"Disk C: $u GB used, $f GB free\""'
    )
    out = await asyncio.to_thread(_shell, ps, timeout=15)
    await update.message.reply_text(f"```\n{out}\n```", parse_mode="Markdown")

@owner_only
async def cmd_search(update, ctx):
    if not ctx.args:
        await update.message.reply_text("Usage: /search <query>")
        return
    query = " ".join(ctx.args)
    await update.message.reply_text(f"🔍 Searching: {query}…")
    results = await asyncio.to_thread(_search, query, 5)
    if not results:
        await update.message.reply_text("No results found.")
        return
    ctx_text = "\n".join(
        f"- {r.get('title','')}: {r.get('body','')[:200]}" for r in results
    )
    summary = await asyncio.to_thread(
        ask_llm, [],
        f"Summarise these search results for '{query}' in 3-4 concise points:\n{ctx_text}",
        "You are a research assistant. Summarise clearly and concisely."
    )
    sources = "\n".join(f"• {r.get('href','')}" for r in results[:3] if r.get("href"))
    await update.message.reply_text(f"*{query}*\n\n{summary}\n\nSources:\n{sources}", parse_mode="Markdown")

@owner_only
async def cmd_plan(update, ctx):
    if not ctx.args:
        await update.message.reply_text("Usage: /plan <goal or task>")
        return
    goal = " ".join(ctx.args)
    await update.message.reply_text(f"📋 Planning: {goal}…")
    plan = await asyncio.to_thread(
        ask_llm, [],
        f"Break down this goal into clear numbered steps (max 8). Be specific and actionable:\n{goal}",
        "You are a smart AI assistant. Create a practical step-by-step plan. Be specific."
    )
    await update.message.reply_text(f"📋 *Plan: {goal}*\n\n{plan}", parse_mode="Markdown")

@owner_only
async def cmd_remind(update, ctx):
    if len(ctx.args) < 2:
        await update.message.reply_text("Usage: /remind <Xm|Xh|Xd> <message>\nExample: /remind 30m check email")
        return
    time_str = ctx.args[0].lower()
    msg = " ".join(ctx.args[1:])
    m = re.match(r'^(\d+)(m|h|d)$', time_str)
    if not m:
        await update.message.reply_text("Time format: 30m, 2h, 1d")
        return
    n, unit = int(m.group(1)), m.group(2)
    delta = timedelta(minutes=n if unit == "m" else 0,
                      hours=n if unit == "h" else 0,
                      days=n if unit == "d" else 0)
    due = (datetime.utcnow() + delta).isoformat()
    reminders = _gs("reminders", [])
    reminders.append({"due": due, "msg": msg})
    _ss("reminders", reminders)
    _save_state()
    when = (datetime.utcnow() + delta).strftime("%H:%M UTC")
    await update.message.reply_text(f"⏰ Reminder set for {when}: {msg}")

@owner_only
async def cmd_sysmon(update, ctx):
    if ctx.args:
        on = ctx.args[0].lower() in ("on", "1", "true")
        _ss("sysmon", on)
        _save_state()
        await update.message.reply_text(f"System monitor {'enabled ✅' if on else 'disabled ❌'}")
    else:
        on = _gs("sysmon", True)
        await update.message.reply_text(f"System monitor: {'on ✅' if on else 'off ❌'}")

@owner_only
async def cmd_digest(update, ctx):
    hours = 24
    if ctx.args:
        try:
            hours = int(ctx.args[0])
        except ValueError:
            pass
    digest = _build_digest(hours)
    await update.message.reply_text(digest, parse_mode="Markdown")

@owner_only
async def cmd_topics(update, ctx):
    topics = _gs("topics", [])
    if ctx.args:
        action = ctx.args[0].lower()
        if action == "add" and len(ctx.args) > 1:
            t = " ".join(ctx.args[1:])
            if t not in topics:
                topics.append(t)
                _ss("topics", topics)
                _save_state()
            await update.message.reply_text(f"✅ Added: {t}")
            return
        elif action == "remove" and len(ctx.args) > 1:
            t = " ".join(ctx.args[1:])
            _ss("topics", [x for x in topics if x != t])
            _save_state()
            await update.message.reply_text(f"🗑️ Removed: {t}")
            return
    msg = "*Study topics:*\n" + "\n".join(f"• {t}" for t in topics)
    msg += "\n\n/topics add <topic>\n/topics remove <topic>"
    await update.message.reply_text(msg, parse_mode="Markdown")

@owner_only
async def cmd_autostudy(update, ctx):
    if ctx.args:
        on = ctx.args[0].lower() in ("on", "1", "true")
        _ss("autostudy", on)
        _save_state()
        await update.message.reply_text(f"Auto-study {'enabled ✅' if on else 'disabled ❌'}")
    else:
        on = _gs("autostudy", True)
        await update.message.reply_text(f"Auto-study: {'on ✅' if on else 'off ❌'}")

@owner_only
async def handle_message(update, _ctx):
    _last_activity["time"] = datetime.utcnow()
    text = (update.message.text or "").strip()
    if not text:
        return
    history = _gs("history", [])
    reply = await asyncio.to_thread(ask_llm, history, text)
    history = history[-10:]
    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})
    _ss("history", history[-12:])
    _save_state()
    await update.message.reply_text(reply[:4000])

# ── Flask keep-alive ────────────────────────────────────────────────────────────

def _start_flask():
    try:
        from flask import Flask
        app = Flask(__name__)

        @app.route("/")
        def health():
            return f"Jai alive — {datetime.utcnow().strftime('%H:%M UTC')}", 200

        port = int(os.getenv("PORT", 8080))
        threading.Thread(
            target=lambda: app.run(host="0.0.0.0", port=port, use_reloader=False),
            daemon=True,
        ).start()
        _log("FLASK", f"port {port}")
    except Exception as e:
        _log("FLASK:err", str(e))

# ── Boot ───────────────────────────────────────────────────────────────────────

async def _run(token: str):
    """Explicit async main — avoids post_init hook reliability issues."""
    from telegram.ext import Application, CommandHandler, MessageHandler, filters

    if IS_CLOUD or os.getenv("PORT"):
        _start_flask()

    app = Application.builder().token(token).build()

    for name, fn in [
        ("start", cmd_start), ("help", cmd_help), ("status", cmd_status),
        ("clear", cmd_clear), ("sync", cmd_sync),
        ("ss", cmd_ss), ("run", cmd_run), ("open", cmd_open),
        ("kill", cmd_kill), ("ls", cmd_ls), ("sysinfo", cmd_sysinfo),
        ("search", cmd_search), ("plan", cmd_plan),
        ("remind", cmd_remind), ("sysmon", cmd_sysmon),
        ("digest", cmd_digest), ("topics", cmd_topics), ("autostudy", cmd_autostudy),
    ]:
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    async with app:
        _load_state()
        _log("BOT:init", f"local={IS_LOCAL} cloud={IS_CLOUD}")

        # Background tasks
        asyncio.create_task(_idle_loop(app.bot))
        asyncio.create_task(_reminder_loop(app.bot))
        asyncio.create_task(_sysmon_loop(app.bot))

        # Startup notification to owner
        if OWNER_ID:
            try:
                env = "🖥️ Local" if IS_LOCAL else "☁️ Cloud"
                await app.bot.send_message(
                    OWNER_ID,
                    f"⚡ *Jai is online* — {env}\n"
                    f"Gemini {'✅' if CFG.get('gemini_api_key','').strip('YOUR_') else '❌'}  "
                    f"Grok {'✅' if CFG.get('grok_api_key','').strip('YOUR_') else '❌'}\n"
                    f"Type anything or /help",
                    parse_mode="Markdown",
                )
            except Exception as e:
                _log("NOTIFY:err", str(e))

        await app.updater.start_polling(drop_pending_updates=True)
        _log("BOT:start", "polling active")
        await app.start()
        # Keep running until signal
        await asyncio.Event().wait()

def main():
    token = CFG.get("telegram_bot_token", "")
    if not token:
        raise RuntimeError("telegram_bot_token missing in secrets.json or env")
    try:
        asyncio.run(_run(token))
    except KeyboardInterrupt:
        _log("BOT:stop", "interrupted")

if __name__ == "__main__":
    main()
