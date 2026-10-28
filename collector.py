#!/usr/bin/env python3
"""
Live quota & scale usage collector across personal AI accounts:
  1. Claude (Anthropic OAuth /api/oauth/usage + Claude Desktop plan-usage-history.json + .claude transcripts)
  2. ChatGPT / Codex (Codex rollout rate_limits snapshots + state_5.sqlite token scale + /backend-api/wham/usage)
  3. Google Antigravity (Local LanguageServer GetUserStatus model pools & credits + brain transcript scale)

Personal account scope only (snackdriven) - work workspaces/threads excluded.
"""

from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
import urllib.request
from typing import Any

PERSONAL_EMAIL = "snackdriven"
PERSONAL_CLAUDE_ORG = "b7b4f5d6-c5bd-4c41-b8e0-ca56a6f7632c"
PERSONAL_CODEX_ACCOUNT = "2963a808-028c-4c6b-b930-2a2cf7930ab7"
CLAUDE_OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"

WORK_KEYWORDS = (
    "scratch-pad",
    "scratch_pad",
    "nhha",
    "joinchorus",
    "chorusinnovations",
    "ttoad",
    "titan-",
)


def is_work_related(*texts: str | None) -> bool:
    combined = " ".join(t or "" for t in texts).lower()
    return any(k in combined for k in WORK_KEYWORDS)


def clean_title(raw: str | None) -> str:
    if not raw:
        return "Untitled session"
    text = re.sub(r"^#+\s*Files (mentioned|pasted) by the user:.*?\n+", "", raw, flags=re.I | re.S).strip()
    text = re.sub(r"\s+", " ", text)
    return (text[:72] + "...") if len(text) > 75 else (text or "Untitled session")


def iso_to_epoch(iso_str: str | None) -> float | None:
    if not iso_str:
        return None
    try:
        s = iso_str.replace("Z", "+00:00")
        return dt.datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def compute_window_pace(
    used_percent: float | None,
    resets_at_epoch: float | None,
    window_seconds: float,
    now_epoch: float | None = None,
) -> dict[str, Any]:
    """
    Computes how far through the rolling/fixed window we are, linear target %,
    delta (used% - elapsed%), burn rate, and projected exhaustion timestamp.
    """
    now = now_epoch or time.time()
    if used_percent is None or resets_at_epoch is None or window_seconds <= 0:
        return {
            "elapsed_percent": None,
            "pace_delta": None,
            "pace_ratio": None,
            "status": "idle" if (used_percent or 0) == 0 else "unknown",
            "projected_end_pct": None,
            "exhausts_in_seconds": None,
            "remaining_seconds": max(0, int(resets_at_epoch - now)) if resets_at_epoch else None,
        }

    remaining_sec = max(0.0, resets_at_epoch - now)
    elapsed_sec = max(0.0, min(window_seconds, window_seconds - remaining_sec))
    elapsed_pct = (elapsed_sec / window_seconds) * 100.0
    delta = used_percent - elapsed_pct
    pace_ratio = (used_percent / elapsed_pct) if elapsed_pct > 2.0 else None

    if elapsed_sec > 300 and used_percent > 0:
        rate_pct_per_sec = used_percent / elapsed_sec
        projected_end_pct = min(999.0, rate_pct_per_sec * window_seconds)
        remaining_pct = max(0.0, 100.0 - used_percent)
        exhausts_in_sec = (remaining_pct / rate_pct_per_sec) if rate_pct_per_sec > 0 else None
    else:
        projected_end_pct = used_percent
        exhausts_in_sec = None

    if used_percent >= 90:
        status = "critical"
    elif used_percent >= 75 or (delta > 15 and used_percent >= 50):
        status = "hot"
    elif delta > 5:
        status = "warm"
    else:
        status = "on_track"

    return {
        "elapsed_percent": round(elapsed_pct, 1),
        "pace_delta": round(delta, 1),
        "pace_ratio": round(pace_ratio, 2) if pace_ratio is not None else None,
        "status": status,
        "projected_end_pct": round(projected_end_pct, 1) if projected_end_pct is not None else None,
        "exhausts_in_seconds": int(exhausts_in_sec) if exhausts_in_sec is not None else None,
        "remaining_seconds": int(remaining_sec),
    }


def refresh_claude_token_if_needed(cred_path: str) -> dict[str, Any]:
    if not os.path.exists(cred_path):
        return {}
    with open(cred_path, "r", encoding="utf-8") as f:
        creds = json.load(f)
    oa = creds.get("claudeAiOauth", {})
    exp_ms = oa.get("expiresAt", 0)
    now_ms = int(time.time() * 1000)
    if exp_ms > now_ms + 300_000 and oa.get("accessToken"):
        return oa

    rt = oa.get("refreshToken")
    if not rt:
        return oa

    payload = json.dumps(
        {
            "grant_type": "refresh_token",
            "refresh_token": rt,
            "client_id": CLAUDE_OAUTH_CLIENT_ID,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://platform.claude.com/v1/oauth/token",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "claude-code/2.0.0"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    oa["accessToken"] = res["access_token"]
    if "refresh_token" in res:
        oa["refreshToken"] = res["refresh_token"]
    if "expires_in" in res:
        oa["expiresAt"] = int((time.time() + res["expires_in"]) * 1000)
    creds["claudeAiOauth"] = oa
    with open(cred_path, "w", encoding="utf-8") as wf:
        json.dump(creds, wf, indent=2)

    wsl_cred = r"\\wsl.localhost\Ubuntu\home\kg\.claude\.credentials.json"
    if os.path.exists(wsl_cred):
        try:
            shutil.copy2(cred_path, wsl_cred)
        except Exception:
            pass
    return oa


def collect_claude() -> dict[str, Any]:
    cred_path = os.path.expanduser(r"~\.claude\.credentials.json")
    result: dict[str, Any] = {
        "provider": "claude",
        "name": "Claude",
        "account": PERSONAL_EMAIL,
        "plan": "Max 20x",
        "status": "ok",
        "error": None,
        "windows": {},
        "bonus_bucket": None,
        "extra_usage": None,
        "surface_breakdown": [],
        "history_samples": [],
        "scale_7d": {
            "local_sessions": 0,
            "local_tokens": 0,
        },
    }
    try:
        oa = refresh_claude_token_if_needed(cred_path)
        tier = oa.get("rateLimitTier") or ""
        if "20x" in tier:
            result["plan"] = "Max 20x"
        elif oa.get("subscriptionType"):
            result["plan"] = str(oa["subscriptionType"]).title()

        tok = oa.get("accessToken")
        if tok:
            req = urllib.request.Request(
                "https://api.anthropic.com/api/oauth/usage",
                headers={
                    "Authorization": f"Bearer {tok}",
                    "anthropic-beta": "oauth-2025-04-20",
                    "User-Agent": "claude-code/2.0.0",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                usage = json.loads(resp.read().decode("utf-8"))

            fh = usage.get("five_hour") or {}
            fh_pct = float(fh.get("utilization") or 0.0)
            fh_reset = iso_to_epoch(fh.get("resets_at"))
            result["windows"]["five_hour"] = {
                "label": "5-Hour Rolling Window",
                "used_percent": round(fh_pct, 1),
                "remaining_percent": round(max(0.0, 100.0 - fh_pct), 1),
                "resets_at": fh.get("resets_at"),
                "resets_at_epoch": fh_reset,
                "window_seconds": 5 * 3600,
                "pace": compute_window_pace(fh_pct, fh_reset, 5 * 3600),
            }

            sd = usage.get("seven_day") or {}
            sd_pct = float(sd.get("utilization") or 0.0)
            sd_reset = iso_to_epoch(sd.get("resets_at"))
            result["windows"]["seven_day"] = {
                "label": "7-Day Weekly Cap (All Models)",
                "used_percent": round(sd_pct, 1),
                "remaining_percent": round(max(0.0, 100.0 - sd_pct), 1),
                "resets_at": sd.get("resets_at"),
                "resets_at_epoch": sd_reset,
                "window_seconds": 7 * 86400,
                "pace": compute_window_pace(sd_pct, sd_reset, 7 * 86400),
            }

            for lim in usage.get("limits") or []:
                if lim.get("kind") == "weekly_scoped":
                    scope_model = (lim.get("scope") or {}).get("model", {}).get("display_name") or "Scoped"
                    sc_pct = float(lim.get("percent") or 0.0)
                    sc_reset = iso_to_epoch(lim.get("resets_at"))
                    result["windows"][f"scoped_{scope_model.lower()}"] = {
                        "label": f"7-Day {scope_model} Share (50% Cap)",
                        "used_percent": round(sc_pct, 1),
                        "remaining_percent": round(max(0.0, 100.0 - sc_pct), 1),
                        "resets_at": lim.get("resets_at"),
                        "resets_at_epoch": sc_reset,
                        "window_seconds": 7 * 86400,
                        "pace": compute_window_pace(sc_pct, sc_reset, 7 * 86400),
                    }

            ig = usage.get("iguana_necktie")
            if isinstance(ig, dict) and ig.get("limit_dollars"):
                ig_pct = float(ig.get("utilization") or 0.0)
                ig_reset = iso_to_epoch(ig.get("resets_at"))
                result["bonus_bucket"] = {
                    "code_name": "iguana_necktie",
                    "label": "Bonus / Promo Credit Pool",
                    "used_percent": round(ig_pct, 1),
                    "limit_dollars": ig.get("limit_dollars"),
                    "used_dollars": round(float(ig.get("used_dollars") or 0.0), 2),
                    "remaining_dollars": round(float(ig.get("remaining_dollars") or 0.0), 2),
                    "resets_at": ig.get("resets_at"),
                    "resets_at_epoch": ig_reset,
                }

            ex = usage.get("extra_usage") or {}
            result["extra_usage"] = {
                "enabled": bool(ex.get("is_enabled")),
                "disabled_reason": ex.get("disabled_reason"),
                "used_credits": ex.get("used_credits") or 0.0,
                "monthly_limit": ex.get("monthly_limit"),
            }

            bd = (usage.get("seven_day_breakdown") or {}).get("rows") or []
            result["surface_breakdown"] = [
                {"name": r.get("display_name"), "key": r.get("key"), "percent": r.get("percent")}
                for r in bd
            ]
    except Exception as e:
        result["status"] = "degraded"
        result["error"] = str(e)

    # Read Claude Desktop plan-usage-history.json (personal org only)
    hist_path = os.path.expanduser(r"~\AppData\Roaming\Claude\plan-usage-history.json")
    if os.path.exists(hist_path):
        try:
            with open(hist_path, "r", encoding="utf-8") as f:
                hd = json.load(f)
            samples = [
                {
                    "ts": int(s["t"] / 1000),
                    "iso": dt.datetime.fromtimestamp(s["t"] / 1000, tz=dt.timezone.utc).isoformat(),
                    "five_hour_pct": s.get("u", {}).get("fh"),
                    "seven_day_pct": s.get("u", {}).get("sd"),
                }
                for s in hd.get("samples", [])
                if s.get("org") == PERSONAL_CLAUDE_ORG
            ]
            if "seven_day" in result["windows"]:
                samples.append(
                    {
                        "ts": int(time.time()),
                        "iso": dt.datetime.now(tz=dt.timezone.utc).isoformat(),
                        "five_hour_pct": result["windows"]["five_hour"]["used_percent"],
                        "seven_day_pct": result["windows"]["seven_day"]["used_percent"],
                    }
                )
            result["history_samples"] = samples
        except Exception:
            pass

    # Scan local .claude/projects JSONL for personal token counts
    proj_dir = os.path.expanduser(r"~\.claude\projects")
    week_ago = time.time() - 7 * 86400
    if os.path.exists(proj_dir):
        local_sessions = 0
        local_tokens = 0
        for r, _, files in os.walk(proj_dir):
            if is_work_related(r):
                continue
            for fn in files:
                if not fn.endswith(".jsonl"):
                    continue
                fp = os.path.join(r, fn)
                try:
                    if os.path.getmtime(fp) < week_ago:
                        continue
                    local_sessions += 1
                    with open(fp, "r", encoding="utf-8", errors="ignore") as jf:
                        for line in jf:
                            if '"usage"' not in line:
                                continue
                            obj = json.loads(line)
                            u = (obj.get("message") or {}).get("usage") or {}
                            local_tokens += (
                                int(u.get("input_tokens") or 0)
                                + int(u.get("cache_creation_input_tokens") or 0)
                                + int(u.get("cache_read_input_tokens") or 0)
                                + int(u.get("output_tokens") or 0)
                            )
                except Exception:
                    pass
        result["scale_7d"] = {
            "local_sessions": local_sessions,
            "local_tokens": local_tokens,
        }

    return result


def collect_codex() -> dict[str, Any]:
    codex_dir = os.path.expanduser(r"~\.codex")
    result: dict[str, Any] = {
        "provider": "chatgpt",
        "name": "ChatGPT / Codex",
        "account": PERSONAL_EMAIL,
        "plan": "ProLite",
        "status": "ok",
        "error": None,
        "windows": {},
        "reset_credits_available": 0,
        "active_model": "gpt-6.1-sol",
        "history_samples": [],
        "scale_7d": {
            "total_tokens": 0,
            "threads_active": 0,
            "turns_count": 0,
            "daily_tokens": {},
            "top_threads": [],
        },
    }

    auth_path = os.path.join(codex_dir, "auth.json")
    if os.path.exists(auth_path):
        try:
            with open(auth_path, "r", encoding="utf-8") as f:
                auth = json.load(f)
            tok = auth.get("tokens", {}).get("access_token")
            acc_id = auth.get("tokens", {}).get("account_id") or PERSONAL_CODEX_ACCOUNT
            if tok and acc_id == PERSONAL_CODEX_ACCOUNT:
                req = urllib.request.Request(
                    "https://chatgpt.com/backend-api/wham/usage",
                    headers={
                        "Authorization": f"Bearer {tok}",
                        "ChatGPT-Account-Id": acc_id,
                        "x-openai-codex-luna-reserve": "1",
                        "User-Agent": "codex_cli_rs/0.1.0",
                    },
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    wham = json.loads(resp.read().decode("utf-8"))
                if wham.get("email"):
                    result["account"] = wham["email"]
                if wham.get("plan_type"):
                    pt = wham["plan_type"]
                    result["plan"] = "ProLite" if pt == "prolite" else str(pt).title()
                rc = wham.get("rate_limit_reset_credits") or {}
                result["reset_credits_available"] = rc.get("available_count") or 0
        except Exception as e:
            result["error"] = f"wham metadata: {e}"

    db_path = os.path.join(codex_dir, "state_5.sqlite")
    now = time.time()
    week_ago = int(now - 7 * 86400)
    latest_rl_ts = ""
    latest_rl: dict[str, Any] | None = None
    rl_timeline: list[dict[str, Any]] = []

    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            rows = conn.execute(
                """
                SELECT id, title, rollout_path, created_at, updated_at, tokens_used, model, cwd, creator_account_id
                FROM threads
                WHERE (creator_account_id = ? OR creator_account_id IS NULL)
                  AND updated_at >= ?
                ORDER BY updated_at DESC
                """,
                (PERSONAL_CODEX_ACCOUNT, week_ago),
            ).fetchall()

            total_tokens = 0
            daily_tokens: dict[str, int] = {}
            all_personal_threads = []
            personal_thread_ids = set()

            for r in rows:
                tid, title, rpath, created_at, updated_at, tokens_used, model, cwd, acc_id = r
                # Always read account-wide rate_limits from rollout files even if a thread was in a work folder,
                # because rate_limits is account-global for personal account
                clean_path = rpath[4:] if (rpath and rpath.startswith("\\\\?\\")) else rpath
                if clean_path and os.path.exists(clean_path):
                    try:
                        with open(clean_path, "r", encoding="utf-8", errors="ignore") as rf:
                            for line in rf:
                                if '"rate_limits"' not in line:
                                    continue
                                obj = json.loads(line)
                                payload = obj.get("payload") or {}
                                rl = payload.get("rate_limits")
                                if not rl:
                                    continue
                                lid = rl.get("limit_id")
                                if lid not in (None, "", "codex"):
                                    continue
                                ts_str = obj.get("timestamp") or ""
                                prim = rl.get("primary") or {}
                                sec = rl.get("secondary") or {}
                                if ts_str and prim.get("used_percent") is not None:
                                    rl_timeline.append(
                                        {
                                            "iso": ts_str,
                                            "used_percent": float(prim["used_percent"]),
                                            "resets_at": prim.get("resets_at"),
                                            "window_minutes": prim.get("window_minutes") or 10080,
                                            "secondary_percent": sec.get("used_percent") if sec else None,
                                        }
                                    )
                                    if ts_str > latest_rl_ts:
                                        latest_rl_ts = ts_str
                                        latest_rl = rl
                    except Exception:
                        pass

                # Filter out work-related threads for personal activity display
                if is_work_related(title, cwd):
                    continue

                personal_thread_ids.add(tid)
                t_used = int(tokens_used or 0)
                total_tokens += t_used
                day_key = dt.datetime.fromtimestamp(updated_at).strftime("%Y-%m-%d")
                daily_tokens[day_key] = daily_tokens.get(day_key, 0) + t_used
                if model:
                    result["active_model"] = model

                clean_cwd = (cwd[4:] if (cwd and cwd.startswith("\\\\?\\")) else (cwd or "")).rstrip("\\/")
                all_personal_threads.append(
                    {
                        "id": tid,
                        "title": clean_title(title),
                        "tokens_used": t_used,
                        "model": model or "gpt-6.1-sol",
                        "updated_at": updated_at,
                        "cwd": os.path.basename(clean_cwd) if clean_cwd else "",
                    }
                )

            all_personal_threads.sort(key=lambda x: x["tokens_used"], reverse=True)
            result["scale_7d"]["total_tokens"] = total_tokens
            result["scale_7d"]["threads_active"] = len(all_personal_threads)
            result["scale_7d"]["daily_tokens"] = daily_tokens
            result["scale_7d"]["top_threads"] = all_personal_threads[:6]
        except Exception as e:
            result["status"] = "degraded"
            result["error"] = str(e)

    th_path = os.path.join(codex_dir, "thread_history_1.sqlite")
    if os.path.exists(th_path):
        try:
            conn_th = sqlite3.connect(f"file:{th_path}?mode=ro", uri=True)
            turns_7d = conn_th.execute(
                "SELECT COUNT(*) FROM thread_turns WHERE started_at >= ?", (week_ago,)
            ).fetchone()[0]
            result["scale_7d"]["turns_count"] = int(turns_7d or 0)
        except Exception:
            pass

    if rl_timeline:
        rl_timeline.sort(key=lambda x: x["iso"])
        deduped = []
        last_pct = None
        last_t = 0.0
        for item in rl_timeline:
            t_ep = iso_to_epoch(item["iso"]) or 0.0
            if item["used_percent"] != last_pct or (t_ep - last_t) > 3600:
                deduped.append(
                    {
                        "ts": int(t_ep),
                        "iso": item["iso"],
                        "seven_day_pct": item["used_percent"],
                        "five_hour_pct": item["secondary_percent"],
                    }
                )
                last_pct = item["used_percent"]
                last_t = t_ep
        result["history_samples"] = deduped[-45:]

    if latest_rl:
        for slot_name in ("primary", "secondary"):
            win = latest_rl.get(slot_name)
            if not isinstance(win, dict) or win.get("used_percent") is None:
                continue
            w_min = int(win.get("window_minutes") or (10080 if slot_name == "primary" else 300))
            used_pct = float(win["used_percent"])
            resets_at_ep = float(win["resets_at"]) if win.get("resets_at") else None
            resets_iso = (
                dt.datetime.fromtimestamp(resets_at_ep, tz=dt.timezone.utc).isoformat()
                if resets_at_ep
                else None
            )
            key = "seven_day" if w_min >= 1440 else "five_hour"
            label = "7-Day Weekly Cap (Codex / ChatGPT)" if key == "seven_day" else "5-Hour Rolling Window"
            result["windows"][key] = {
                "label": label,
                "used_percent": round(used_pct, 1),
                "remaining_percent": round(max(0.0, 100.0 - used_pct), 1),
                "resets_at": resets_iso,
                "resets_at_epoch": resets_at_ep,
                "window_seconds": w_min * 60,
                "as_of": latest_rl_ts,
                "pace": compute_window_pace(used_pct, resets_at_ep, w_min * 60),
            }

    return result


def collect_antigravity() -> dict[str, Any]:
    result: dict[str, Any] = {
        "provider": "antigravity",
        "name": "Google Antigravity",
        "account": PERSONAL_EMAIL,
        "plan": "Google AI Pro",
        "status": "ok",
        "error": None,
        "windows": {},
        "model_quotas": [],
        "credits": {},
        "scale_7d": {
            "conversations_active": 0,
            "user_prompts": 0,
            "planner_steps": 0,
            "tool_calls": 0,
            "daily_steps": {},
        },
    }

    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'language_server.exe' } | Select-Object ProcessId, CommandLine | ConvertTo-Json",
            ],
            text=True,
            timeout=5,
        )
        procs = json.loads(out) if out.strip() else []
        if isinstance(procs, dict):
            procs = [procs]

        for p in procs:
            cmd = p.get("CommandLine") or ""
            m_csrf = re.search(r'--csrf_token[=\s]+([^\s"]+)', cmd)
            if not m_csrf:
                continue
            csrf = m_csrf.group(1)
            pid = p["ProcessId"]
            net = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"Get-NetTCPConnection -OwningProcess {pid} -State Listen | Select-Object -ExpandProperty LocalPort | ConvertTo-Json",
                ],
                text=True,
                timeout=5,
            )
            ports = json.loads(net) if net.strip() else []
            if isinstance(ports, int):
                ports = [ports]

            user_status = None
            for port in ports:
                try:
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/GetUserStatus",
                        data=b'{"metadata":{"ideName":"antigravity","extensionName":"antigravity","locale":"en"}}',
                        headers={
                            "Content-Type": "application/json",
                            "Connect-Protocol-Version": "1",
                            "x-codeium-csrf-token": csrf,
                        },
                    )
                    with urllib.request.urlopen(req, timeout=2) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        user_status = data.get("userStatus")
                        if user_status:
                            break
                except Exception:
                    continue

            if user_status:
                if user_status.get("email"):
                    result["account"] = user_status["email"]
                ps = user_status.get("planStatus") or {}
                pinfo = ps.get("planInfo") or {}
                if pinfo.get("planName"):
                    result["plan"] = f"Google AI {pinfo['planName']}"
                result["credits"] = {
                    "available_prompt_credits": ps.get("availablePromptCredits", 0),
                    "monthly_prompt_credits": pinfo.get("monthlyPromptCredits", 0),
                    "available_flow_credits": ps.get("availableFlowCredits", 0),
                    "monthly_flow_credits": pinfo.get("monthlyFlowCredits", 0),
                }

                cmc = user_status.get("cascadeModelConfigData") or {}
                models = cmc.get("clientModelConfigs") or []
                pools: dict[str, dict[str, Any]] = {}
                for m in models:
                    label = m.get("label") or "Unknown"
                    qi = m.get("quotaInfo") or {}
                    rem_frac = float(qi.get("remainingFraction", 1.0))
                    used_pct = round(max(0.0, (1.0 - rem_frac) * 100.0), 1)
                    rem_pct = round(rem_frac * 100.0, 1)
                    reset_time = qi.get("resetTime")
                    reset_ep = iso_to_epoch(reset_time)

                    result["model_quotas"].append(
                        {
                            "label": label,
                            "used_percent": used_pct,
                            "remaining_percent": rem_pct,
                            "reset_time": reset_time,
                            "reset_epoch": reset_ep,
                        }
                    )

                    pool_key = "gemini_pool" if "Gemini" in label else "claude_gpt_pool"
                    pool_label = (
                        "5-Hour Gemini Pool (Argon / Flash)"
                        if pool_key == "gemini_pool"
                        else "5-Hour Claude & GPT-OSS Pool"
                    )
                    if pool_key not in pools or used_pct > pools[pool_key]["used_percent"]:
                        pools[pool_key] = {
                            "label": pool_label,
                            "used_percent": used_pct,
                            "remaining_percent": rem_pct,
                            "resets_at": reset_time,
                            "resets_at_epoch": reset_ep,
                            "window_seconds": 5 * 3600,
                            "pace": compute_window_pace(used_pct, reset_ep, 5 * 3600),
                            "models": [],
                        }
                    pools[pool_key]["models"].append(label)

                result["windows"] = pools
                break
    except Exception as e:
        result["status"] = "degraded"
        result["error"] = str(e)

    brain_dir = os.path.expanduser(r"~\.gemini\antigravity\brain")
    week_ago = time.time() - 7 * 86400
    if os.path.exists(brain_dir):
        t_files = glob.glob(os.path.join(brain_dir, "*", ".system_generated", "logs", "transcript.jsonl"))
        conv_count = 0
        user_prompts = 0
        planner_steps = 0
        tool_calls = 0
        daily_steps: dict[str, int] = {}

        for tf in t_files:
            try:
                mtime = os.path.getmtime(tf)
                if mtime < week_ago:
                    continue
                with open(tf, "r", encoding="utf-8", errors="ignore") as f:
                    lines = [ln for ln in f if ln.strip()]
                # Skip work conversations if any first user message mentions work keywords
                first_inputs = " ".join(ln[:300] for ln in lines[:5])
                if is_work_related(first_inputs):
                    continue
                conv_count += 1
                for line in lines:
                    obj = json.loads(line)
                    stype = obj.get("type")
                    created = obj.get("created_at") or ""
                    day_k = created[:10] if len(created) >= 10 else dt.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
                    if stype == "USER_INPUT":
                        user_prompts += 1
                    elif stype == "PLANNER_RESPONSE":
                        planner_steps += 1
                        tcs = obj.get("tool_calls") or []
                        tool_calls += len(tcs)
                        daily_steps[day_k] = daily_steps.get(day_k, 0) + 1
            except Exception:
                pass

        result["scale_7d"] = {
            "conversations_active": conv_count,
            "user_prompts": user_prompts,
            "planner_steps": planner_steps,
            "tool_calls": tool_calls,
            "daily_steps": daily_steps,
        }

    return result


def collect_all() -> dict[str, Any]:
    now = dt.datetime.now(tz=dt.timezone.utc).astimezone()
    claude = collect_claude()
    codex = collect_codex()
    agy = collect_antigravity()

    days = []
    for i in range(6, -1, -1):
        d = (now - dt.timedelta(days=i)).strftime("%Y-%m-%d")
        days.append(d)

    return {
        "generated_at": now.isoformat(),
        "generated_at_epoch": int(now.timestamp()),
        "account": PERSONAL_EMAIL,
        "days_7d": days,
        "providers": {
            "claude": claude,
            "chatgpt": codex,
            "antigravity": agy,
        },
    }


if __name__ == "__main__":
    print(json.dumps(collect_all(), indent=2))
