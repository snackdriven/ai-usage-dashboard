#!/usr/bin/env python3
"""
AI Usage & Quota Scale Multi-Page Dashboard Server + CLI + Static Site Exporter
for https://usage.snackdriven.com (and local http://127.0.0.1:8787).

Pages generated & served:
  - /               (Overview across all 3 providers + scale charts)
  - /claude/        (Claude Max 20x deep dive: 5h/7d windows, promo pool, surface split, history)
  - /chatgpt/       (ChatGPT / Codex ProLite deep dive: 7d cap, reset credits, 45-pt rollout curve, top threads)
  - /antigravity/   (Google Antigravity AI Pro deep dive: 5h pools, all 13 model quotas, credits, step scale)
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import socketserver
import sys
from typing import Any

from collector import collect_all

PORT = 8787

PAGES = ("overview", "claude", "chatgpt", "antigravity")

PAGE_META = {
    "overview": {
        "title": "AI Quota & Burn Scale · usage.snackdriven.com",
        "path": "/",
        "heading": "AI Quota & Burn Scale",
        "subtitle": "Live rolling 5h & 7d rate-limit windows, linear pace markers, and 7-day token/step scale across Claude, ChatGPT/Codex, and Antigravity.",
    },
    "claude": {
        "title": "Claude Quota & Scale · usage.snackdriven.com",
        "path": "/claude/",
        "heading": "Claude · Max 20x",
        "subtitle": "5-hour rolling session window, 7-day weekly cap, Fable scoped share, promotional credit bucket, and Claude Code surface split.",
    },
    "chatgpt": {
        "title": "ChatGPT / Codex Quota & Scale · usage.snackdriven.com",
        "path": "/chatgpt/",
        "heading": "ChatGPT / Codex · ProLite",
        "subtitle": "7-day weekly window, banked rate-limit reset credits, rollout burn trajectory, and top token-consuming personal threads.",
    },
    "antigravity": {
        "title": "Google Antigravity Quota & Scale · usage.snackdriven.com",
        "path": "/antigravity/",
        "heading": "Google Antigravity · AI Pro",
        "subtitle": "5-hour Gemini & Claude/GPT-OSS model pools, all 13 model quotas, Prompt/Flow AI credits, and 7-day agent step volume.",
    },
}

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="robots" content="noindex,nofollow" />
  <title>__PAGE_TITLE__</title>
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
  <style>
    body {
      background-color: var(--background, #0b0f17);
      color: var(--foreground, #f1f5f9);
      min-height: 100dvh;
    }
    .hero-title {
      font-size: clamp(1.25rem, 1rem + 1.2vw, 1.75rem);
      line-height: 1.2;
    }
    .surf-card {
      background-color: var(--card, #111827);
      border-color: var(--border, rgba(148, 163, 184, 0.18));
      color: var(--foreground, #f1f5f9);
    }
    .surf-sub {
      background-color: var(--content, rgba(15, 23, 42, 0.55));
      border-color: var(--border, rgba(148, 163, 184, 0.14));
    }
    .txt-muted {
      color: var(--muted-foreground, #94a3b8);
    }
    .pace-tick {
      position: absolute;
      top: -3px;
      bottom: -3px;
      width: 2px;
      background-color: var(--foreground, #ffffff);
      opacity: 0.85;
      z-index: 10;
    }
    .dashboard-section {
      content-visibility: auto;
      contain-intrinsic-size: auto 320px auto 420px;
    }
    @supports not (content-visibility: auto) {
      .dashboard-section {
        contain: layout style paint;
      }
    }
  </style>
</head>
<body class="antialiased p-4 md:p-6">
  <div class="max-w-7xl mx-auto space-y-5">

    <!-- Top Navigation Bar -->
    <nav aria-label="Dashboard pages" class="surf-card border rounded-xl px-4 py-3 flex items-center justify-between gap-3 flex-wrap shadow-sm">
      <div class="flex items-center gap-2 flex-wrap">
        <a href="__ROOT_PREFIX__index.html" class="text-xs font-mono font-bold px-2.5 py-1 rounded-md bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
          &gt; usage.snackdriven.com
        </a>
        <div class="flex items-center gap-1.5 flex-wrap text-xs font-medium">
          <a href="__ROOT_PREFIX__index.html" data-nav="overview" class="nav-pill px-3 py-1.5 rounded-lg border transition">Overview</a>
          <a href="__ROOT_PREFIX__claude/index.html" data-nav="claude" class="nav-pill px-3 py-1.5 rounded-lg border transition flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full bg-orange-400"></span>Claude
          </a>
          <a href="__ROOT_PREFIX__chatgpt/index.html" data-nav="chatgpt" class="nav-pill px-3 py-1.5 rounded-lg border transition flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full bg-emerald-400"></span>ChatGPT / Codex
          </a>
          <a href="__ROOT_PREFIX__antigravity/index.html" data-nav="antigravity" class="nav-pill px-3 py-1.5 rounded-lg border transition flex items-center gap-1.5">
            <span class="w-2 h-2 rounded-full bg-sky-400"></span>Antigravity
          </a>
        </div>
      </div>
      <div class="flex items-center gap-3 text-xs font-mono">
        <a href="https://landing.snackdriven.com/" class="txt-muted hover:text-emerald-400 transition">&larr; All my haunts</a>
        <span class="txt-muted">|</span>
        <a href="https://snackdriven.com/" class="txt-muted hover:text-emerald-400 transition">snackdriven.com</a>
      </div>
    </nav>

    <!-- Page Header -->
    <header class="surf-card border rounded-xl p-4 md:p-5 flex flex-col md:flex-row md:items-center md:justify-between gap-4 shadow-sm">
      <div>
        <div class="flex items-center gap-2.5 flex-wrap">
          <h1 class="hero-title font-bold tracking-tight">__PAGE_HEADING__</h1>
          <span id="account-pill" class="text-xs font-mono px-2.5 py-0.5 rounded-full surf-sub border txt-muted">snackdriven</span>
          <span class="text-xs px-2.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 font-medium">Personal Scope</span>
        </div>
        <p class="txt-muted text-xs mt-1">__PAGE_SUBTITLE__</p>
      </div>
      <div class="flex items-center gap-2.5 flex-wrap">
        <span id="last-updated" class="text-xs txt-muted font-mono"></span>
        <button id="refresh-btn" onclick="refreshLive()" class="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-indigo-500 hover:bg-indigo-400 text-white transition cursor-pointer">
          Refresh Live
        </button>
      </div>
    </header>

    <!-- At-Scale Burn Alert Banner -->
    <div id="alert-banner" class="hidden surf-card border rounded-xl p-4"></div>

    <!-- Main View Container -->
    <main id="page-content" class="space-y-5"></main>

  </div>

  <script>
    let PAGE_KEY = "__PAGE_KEY__";
    const ROOT_PREFIX = "__ROOT_PREFIX__";
    let STATE = __INITIAL_DATA__;

    function syncNavHighlight() {
      document.querySelectorAll(".nav-pill").forEach(el => {
        if (el.getAttribute("data-nav") === PAGE_KEY) {
          el.className = "nav-pill px-3 py-1.5 rounded-lg border border-indigo-400/50 bg-indigo-500/20 text-white font-semibold flex items-center gap-1.5";
        } else {
          el.className = "nav-pill px-3 py-1.5 rounded-lg border border-transparent surf-sub txt-muted hover:text-white flex items-center gap-1.5";
        }
      });
    }
    syncNavHighlight();

    document.querySelectorAll(".nav-pill").forEach(el => {
      el.addEventListener("click", (ev) => {
        const targetPage = el.getAttribute("data-nav");
        const isHostedMultiPage = window.location.hostname.includes("snackdriven.com") || window.location.port === "8787";
        if (!isHostedMultiPage && targetPage) {
          ev.preventDefault();
          PAGE_KEY = targetPage;
          syncNavHighlight();
          renderAll(STATE);
        }
      });
    });

    function fmtNumber(n) {
      if (n === null || n === undefined) return "-";
      if (n >= 1e9) return (n / 1e9).toFixed(2) + "B";
      if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
      if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
      return String(n);
    }

    function fmtDuration(sec) {
      if (sec === null || sec === undefined || sec <= 0) return "now";
      const d = Math.floor(sec / 86400);
      const h = Math.floor((sec % 86400) / 3600);
      const m = Math.floor((sec % 3600) / 60);
      if (d > 0) return `${d}d ${h}h`;
      if (h > 0) return `${h}h ${m}m`;
      return `${m}m`;
    }

    function fmtResetDate(epoch) {
      if (!epoch) return "Idle (starts on next prompt)";
      const dt = new Date(epoch * 1000);
      const now = Date.now() / 1000;
      const diff = Math.max(0, Math.round(epoch - now));
      const dayStr = dt.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
      const timeStr = dt.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
      return `in ${fmtDuration(diff)} (${dayStr} ${timeStr})`;
    }

    function barColorClass(usedPct, paceStatus) {
      if (usedPct >= 90 || paceStatus === "critical") return "bg-rose-500";
      if (usedPct >= 75 || paceStatus === "hot") return "bg-amber-500";
      if (usedPct >= 50 || paceStatus === "warm") return "bg-sky-500";
      return "bg-emerald-500";
    }

    function badgeForPace(win) {
      const p = win.pace || {};
      const used = win.used_percent || 0;
      if (used === 0 && !win.resets_at_epoch) {
        return `<span class="text-xs px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">Idle · 100% Free</span>`;
      }
      if (p.pace_ratio !== null && p.pace_ratio !== undefined) {
        if (p.pace_ratio >= 1.35) {
          const eta = p.exhausts_in_seconds ? ` · hits 100% in ~${fmtDuration(p.exhausts_in_seconds)}` : "";
          return `<span class="text-xs px-2 py-0.5 rounded bg-amber-500/15 text-amber-400 border border-amber-500/30 font-medium">🔥 ${p.pace_ratio.toFixed(1)}x pace (${p.elapsed_percent}% through window)${eta}</span>`;
        }
        if (p.pace_ratio <= 0.85) {
          return `<span class="text-xs px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">🐢 ${p.pace_ratio.toFixed(1)}x pace (${p.elapsed_percent}% elapsed)</span>`;
        }
        return `<span class="text-xs px-2 py-0.5 rounded bg-sky-500/15 text-sky-400 border border-sky-500/30">⚡ ${p.pace_ratio.toFixed(1)}x linear pace (${p.elapsed_percent}% elapsed)</span>`;
      }
      return `<span class="text-xs px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">On Track</span>`;
    }

    function renderWindowGauge(win) {
      const used = win.used_percent || 0;
      const rem = win.remaining_percent ?? Math.max(0, 100 - used);
      const p = win.pace || {};
      const elapsed = p.elapsed_percent;
      const color = barColorClass(used, p.status);
      const tickHtml = (elapsed !== null && elapsed !== undefined && elapsed > 0 && elapsed < 100)
        ? `<div class="pace-tick" style="left: ${Math.min(99, Math.max(1, elapsed))}%;" title="Window time elapsed: ${elapsed}%"></div>`
        : "";

      return `
        <div class="surf-sub border rounded-lg p-3 space-y-2">
          <div class="flex items-center justify-between gap-2">
            <span class="text-xs font-semibold">${win.label}</span>
            <div class="flex items-center gap-1.5 font-mono">
              <span class="text-sm font-bold">${used.toFixed(1)}% used</span>
              <span class="text-xs txt-muted">(${rem.toFixed(1)}% left)</span>
            </div>
          </div>
          <div class="relative w-full h-2.5 rounded-full bg-slate-800/80 overflow-visible">
            <div class="h-2.5 rounded-full ${color} transition-all duration-300" style="width: ${Math.min(100, used)}%"></div>
            ${tickHtml}
          </div>
          <div class="flex items-center justify-between gap-2 flex-wrap pt-0.5">
            ${badgeForPace(win)}
            <span class="text-xs txt-muted font-mono">Resets ${fmtResetDate(win.resets_at_epoch)}</span>
          </div>
        </div>
      `;
    }

    function renderAlertBanner(data) {
      const banner = document.getElementById("alert-banner");
      const claude7d = data.providers.claude?.windows?.seven_day;
      const codex7d = data.providers.chatgpt?.windows?.seven_day;
      const agyGem = data.providers.antigravity?.windows?.gemini_pool;
      const agyClaude = data.providers.antigravity?.windows?.claude_gpt_pool;

      const hotItems = [];
      if (claude7d && claude7d.used_percent >= 70) {
        hotItems.push(`<strong>Claude 7-Day</strong> is at <strong>${claude7d.used_percent}%</strong> (${claude7d.pace?.elapsed_percent}% through week, ${claude7d.pace?.pace_ratio}x burn rate, resets ${fmtResetDate(claude7d.resets_at_epoch)})`);
      }
      if (codex7d && codex7d.used_percent >= 70) {
        const rc = data.providers.chatgpt?.reset_credits_available || 0;
        hotItems.push(`<strong>ChatGPT / Codex 7-Day</strong> is at <strong>${codex7d.used_percent}%</strong> (${codex7d.pace?.elapsed_percent}% through week, ${codex7d.pace?.pace_ratio}x burn rate, resets ${fmtResetDate(codex7d.resets_at_epoch)}, <strong>${rc} reset credits</strong> banked)`);
      }

      if (hotItems.length === 0) {
        banner.classList.add("hidden");
        return;
      }
      banner.classList.remove("hidden");
      banner.className = "surf-card border border-amber-500/40 bg-amber-500/10 rounded-xl p-4 text-xs space-y-1.5";
      banner.innerHTML = `
        <div class="flex items-center justify-between gap-2 flex-wrap">
          <span class="font-semibold text-amber-300 text-sm">⚠️ Weekly Pacing Headroom Check</span>
          <span class="font-mono text-emerald-300">Best immediate capacity: Antigravity Claude/GPT Pool (${agyClaude ? agyClaude.remaining_percent : 100}% free) &amp; Gemini Pool (${agyGem ? agyGem.remaining_percent : 100}% free)</span>
        </div>
        <ul class="list-disc list-inside space-y-1 text-slate-200">
          ${hotItems.map(i => `<li>${i}</li>`).join("")}
        </ul>
      `;
    }

    function buildBurnSvg(data, filterProvider) {
      const cSamples = (data.providers.claude?.history_samples || []).filter(s => s.seven_day_pct !== null && s.seven_day_pct !== undefined);
      const xSamples = (data.providers.chatgpt?.history_samples || []).filter(s => s.seven_day_pct !== null && s.seven_day_pct !== undefined);

      const W = 540, H = 190, PAD_L = 36, PAD_R = 16, PAD_T = 14, PAD_B = 28;
      const plotW = W - PAD_L - PAD_R;
      const plotH = H - PAD_T - PAD_B;

      const now = data.generated_at_epoch || (Date.now() / 1000);
      const minT = now - 7 * 86400;
      const maxT = now;

      function xPos(ts) {
        const clamped = Math.max(minT, Math.min(maxT, ts));
        return PAD_L + ((clamped - minT) / (maxT - minT)) * plotW;
      }
      function yPos(pct) {
        const clamped = Math.max(0, Math.min(100, pct));
        return PAD_T + plotH - (clamped / 100) * plotH;
      }

      function buildPolyline(samples, color) {
        const pts = samples.filter(s => s.ts >= minT).map(s => `${xPos(s.ts).toFixed(1)},${yPos(s.seven_day_pct).toFixed(1)}`);
        if (pts.length === 0) return "";
        const last = samples[samples.length - 1];
        const lx = xPos(last.ts).toFixed(1);
        const ly = yPos(last.seven_day_pct).toFixed(1);
        return `
          <polyline fill="none" stroke="${color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" points="${pts.join(" ")}" />
          <circle cx="${lx}" cy="${ly}" r="4" fill="${color}" />
        `;
      }

      const gridLines = [0, 25, 50, 75, 100].map(pct => {
        const y = yPos(pct).toFixed(1);
        return `
          <line x1="${PAD_L}" y1="${y}" x2="${W - PAD_R}" y2="${y}" stroke="rgba(148,163,184,0.16)" stroke-dasharray="${pct === 75 ? '3,3' : 'none'}" />
          <text x="${PAD_L - 6}" y="${Number(y) + 4}" text-anchor="end" fill="#94a3b8" font-size="12" font-family="monospace">${pct}%</text>
        `;
      }).join("");

      const dayLabels = (data.days_7d || []).map((d, idx, arr) => {
        const frac = idx / Math.max(1, arr.length - 1);
        const x = (PAD_L + frac * plotW).toFixed(1);
        return `<text x="${x}" y="${H - 6}" text-anchor="middle" fill="#94a3b8" font-size="12" font-family="monospace">${d.slice(5)}</text>`;
      }).join("");

      const showClaude = !filterProvider || filterProvider === "claude";
      const showCodex = !filterProvider || filterProvider === "chatgpt";

      return `
        <svg viewBox="0 0 ${W} ${H}" class="w-full h-auto">
          ${gridLines}
          <line x1="${PAD_L}" y1="${yPos(0)}" x2="${W - PAD_R}" y2="${yPos(100)}" stroke="rgba(148,163,184,0.35)" stroke-width="1.5" stroke-dasharray="4,4" />
          ${showClaude ? buildPolyline(cSamples, "#fb923c") : ""}
          ${showCodex ? buildPolyline(xSamples, "#34d399") : ""}
          ${dayLabels}
        </svg>
      `;
    }

    function renderOverviewPage(data) {
      const claude = data.providers.claude;
      const codex = data.providers.chatgpt;
      const agy = data.providers.antigravity;

      const claudeWins = Object.values(claude.windows || {}).map(renderWindowGauge).join("");
      const bonus = claude.bonus_bucket;
      const bonusHtml = bonus ? `
        <div class="surf-sub border rounded-lg p-3 flex items-center justify-between text-xs">
          <div>
            <div class="font-semibold">${bonus.label} <span class="font-mono txt-muted">(${bonus.code_name})</span></div>
            <div class="txt-muted font-mono mt-0.5">Resets ${fmtResetDate(bonus.resets_at_epoch)}</div>
          </div>
          <div class="text-right font-mono">
            <div class="text-sm font-bold text-emerald-400">$${bonus.remaining_dollars.toFixed(2)} left</div>
            <div class="txt-muted">$${bonus.used_dollars.toFixed(2)} / $${bonus.limit_dollars} (${bonus.used_percent}%)</div>
          </div>
        </div>
      ` : "";

      const codexWins = Object.values(codex.windows || {}).map(renderWindowGauge).join("");
      const agyWins = Object.values(agy.windows || {}).map(renderWindowGauge).join("");
      const cred = agy.credits || {};

      const days = data.days_7d || [];
      const codexDaily = codex.scale_7d?.daily_tokens || {};
      const agyDaily = agy.scale_7d?.daily_steps || {};
      const maxTok = Math.max(1, ...days.map(d => codexDaily[d] || 0));
      const maxSteps = Math.max(1, ...days.map(d => agyDaily[d] || 0));

      const dailyBars = days.map(d => {
        const tok = codexDaily[d] || 0;
        const steps = agyDaily[d] || 0;
        return `
          <div class="grid grid-cols-12 items-center gap-2 text-xs font-mono">
            <div class="col-span-2 txt-muted">${d.slice(5)}</div>
            <div class="col-span-6 space-y-1">
              <div class="w-full h-2 rounded bg-slate-800 overflow-hidden"><div class="h-2 bg-emerald-400 rounded" style="width:${Math.round((tok / maxTok) * 100)}%"></div></div>
              <div class="w-full h-2 rounded bg-slate-800 overflow-hidden"><div class="h-2 bg-sky-400 rounded" style="width:${Math.round((steps / maxSteps) * 100)}%"></div></div>
            </div>
            <div class="col-span-4 text-right">
              <span class="text-emerald-400">${fmtNumber(tok)}</span> <span class="txt-muted">·</span> <span class="text-sky-400">${steps} stp</span>
            </div>
          </div>
        `;
      }).join("");

      const threads = codex.scale_7d?.top_threads || [];
      const maxThreadTok = Math.max(1, ...threads.map(t => t.tokens_used || 0));
      const threadsHtml = threads.map(t => `
        <div class="surf-sub border rounded-lg p-2.5 space-y-1.5">
          <div class="flex items-center justify-between gap-2 text-xs">
            <span class="font-medium truncate">${t.title}</span>
            <span class="font-mono font-bold text-emerald-400 shrink-0">${fmtNumber(t.tokens_used)} tok</span>
          </div>
          <div class="w-full h-1.5 rounded bg-slate-800 overflow-hidden">
            <div class="h-1.5 bg-emerald-500/80 rounded" style="width: ${Math.round(((t.tokens_used || 0) / maxThreadTok) * 100)}%"></div>
          </div>
          <div class="flex items-center justify-between text-xs txt-muted font-mono">
            <span>${t.cwd || "workspace"} · ${t.model}</span>
            <span>${new Date(t.updated_at * 1000).toLocaleDateString(undefined, {month:'short', day:'numeric'})}</span>
          </div>
        </div>
      `).join("");

      const agyModels = agy.model_quotas || [];
      const grouped = [
        { name: "Gemini 4 Argon (High / Med / Low)", match: "Gemini 4 Argon" },
        { name: "Gemini 3.8 Flash (High / Med / Low)", match: "Gemini 3.8 Flash" },
        { name: "Claude Opus 5.5 (High / Med / Low)", match: "Claude Opus 5.5" },
        { name: "Claude Sonnet 5.5 (High / Med / Low)", match: "Claude Sonnet 5.5" },
        { name: "GPT-OSS 120B (Medium)", match: "GPT-OSS" },
      ];
      const poolHtml = grouped.map(g => {
        const m = agyModels.find(x => (x.label || "").includes(g.match));
        if (!m) return "";
        return `
          <div class="surf-sub border rounded-lg p-2.5 flex items-center justify-between gap-3 text-xs">
            <div>
              <div class="font-semibold">${g.name}</div>
              <div class="txt-muted font-mono">Resets ${fmtResetDate(m.reset_epoch)}</div>
            </div>
            <div class="text-right font-mono">
              <div class="font-bold ${m.used_percent > 50 ? 'text-amber-400' : 'text-emerald-400'}">${m.remaining_percent.toFixed(1)}% free</div>
              <div class="txt-muted">${m.used_percent.toFixed(1)}% used</div>
            </div>
          </div>
        `;
      }).join("");

      return `
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 dashboard-section">
          <div class="surf-card border rounded-xl p-4 space-y-3 shadow-sm flex flex-col justify-between">
            <div class="space-y-3">
              <div class="flex items-center justify-between">
                <a href="${ROOT_PREFIX}claude/index.html" class="flex items-center gap-2 hover:text-orange-300 transition">
                  <span class="w-2.5 h-2.5 rounded-full bg-orange-400"></span>
                  <h2 class="font-bold text-base">Claude &rarr;</h2>
                </a>
                <span class="text-xs font-mono px-2 py-0.5 rounded surf-sub border">${claude.plan}</span>
              </div>
              ${claudeWins}
              ${bonusHtml}
            </div>
            <div class="pt-2 border-t border-[var(--border)] flex items-center justify-between text-xs txt-muted font-mono">
              <span>7d Split: 100% Claude Code</span>
              <a href="${ROOT_PREFIX}claude/index.html" class="text-orange-400 hover:underline">Open Claude Page &rarr;</a>
            </div>
          </div>

          <div class="surf-card border rounded-xl p-4 space-y-3 shadow-sm flex flex-col justify-between">
            <div class="space-y-3">
              <div class="flex items-center justify-between">
                <a href="${ROOT_PREFIX}chatgpt/index.html" class="flex items-center gap-2 hover:text-emerald-300 transition">
                  <span class="w-2.5 h-2.5 rounded-full bg-emerald-400"></span>
                  <h2 class="font-bold text-base">ChatGPT / Codex &rarr;</h2>
                </a>
                <span class="text-xs font-mono px-2 py-0.5 rounded surf-sub border">${codex.plan}</span>
              </div>
              ${codexWins}
              <div class="grid grid-cols-2 gap-2 text-xs">
                <div class="surf-sub border rounded-lg p-2.5">
                  <div class="txt-muted">Reset Credits Banked</div>
                  <div class="text-base font-bold font-mono text-emerald-400 mt-0.5">${codex.reset_credits_available} available</div>
                </div>
                <div class="surf-sub border rounded-lg p-2.5">
                  <div class="txt-muted">7d Personal Volume</div>
                  <div class="text-base font-bold font-mono mt-0.5">${fmtNumber(codex.scale_7d?.total_tokens || 0)} tok</div>
                </div>
              </div>
            </div>
            <div class="pt-2 border-t border-[var(--border)] flex items-center justify-between text-xs txt-muted font-mono">
              <span>${codex.scale_7d?.threads_active || 0} threads / ${codex.scale_7d?.turns_count || 0} turns</span>
              <a href="${ROOT_PREFIX}chatgpt/index.html" class="text-emerald-400 hover:underline">Open Codex Page &rarr;</a>
            </div>
          </div>

          <div class="surf-card border rounded-xl p-4 space-y-3 shadow-sm flex flex-col justify-between">
            <div class="space-y-3">
              <div class="flex items-center justify-between">
                <a href="${ROOT_PREFIX}antigravity/index.html" class="flex items-center gap-2 hover:text-sky-300 transition">
                  <span class="w-2.5 h-2.5 rounded-full bg-sky-400"></span>
                  <h2 class="font-bold text-base">Google Antigravity &rarr;</h2>
                </a>
                <span class="text-xs font-mono px-2 py-0.5 rounded surf-sub border">${agy.plan}</span>
              </div>
              ${agyWins}
              <div class="grid grid-cols-2 gap-2 text-xs">
                <div class="surf-sub border rounded-lg p-2.5">
                  <div class="txt-muted">AI Credits Available</div>
                  <div class="text-sm font-bold font-mono mt-0.5">${cred.available_prompt_credits ?? 0} prompt · ${cred.available_flow_credits ?? 0} flow</div>
                </div>
                <div class="surf-sub border rounded-lg p-2.5">
                  <div class="txt-muted">7d Agent Scale</div>
                  <div class="text-sm font-bold font-mono mt-0.5">${fmtNumber(agy.scale_7d?.planner_steps || 0)} steps · ${fmtNumber(agy.scale_7d?.tool_calls || 0)} tools</div>
                </div>
              </div>
            </div>
            <div class="pt-2 border-t border-[var(--border)] flex items-center justify-between text-xs txt-muted font-mono">
              <span>7d Convs: ${agy.scale_7d?.conversations_active || 0}</span>
              <a href="${ROOT_PREFIX}antigravity/index.html" class="text-sky-400 hover:underline">Open AGY Page &rarr;</a>
            </div>
          </div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 dashboard-section">
          <div class="surf-card border rounded-xl p-4 md:p-5 shadow-sm flex flex-col justify-between">
            <div>
              <div class="flex items-center justify-between gap-2 mb-1">
                <h2 class="text-base font-semibold">7-Day Weekly Limit Burn Trajectory</h2>
                <span class="text-xs txt-muted font-mono">Claude vs. ChatGPT/Codex</span>
              </div>
              <p class="text-xs txt-muted mb-3">Historical weekly utilization (%) across recent checkpoints. Dashed diagonal shows linear 1.0x weekly pace.</p>
              ${buildBurnSvg(data, null)}
            </div>
            <div class="flex items-center gap-4 flex-wrap text-xs txt-muted mt-3 pt-3 border-t border-[var(--border)]">
              <span class="flex items-center gap-1.5"><span class="w-3 h-1 rounded bg-orange-400 inline-block"></span> Claude 7d (${claude.windows?.seven_day?.used_percent ?? 0}%)</span>
              <span class="flex items-center gap-1.5"><span class="w-3 h-1 rounded bg-emerald-400 inline-block"></span> ChatGPT/Codex 7d (${codex.windows?.seven_day?.used_percent ?? 0}%)</span>
            </div>
          </div>

          <div class="surf-card border rounded-xl p-4 md:p-5 shadow-sm flex flex-col justify-between">
            <div>
              <div class="flex items-center justify-between gap-2 mb-1">
                <h2 class="text-base font-semibold">7-Day Daily Volume at Scale</h2>
                <span class="text-xs txt-muted font-mono">Codex Tokens &amp; Antigravity Agent Steps</span>
              </div>
              <p class="text-xs txt-muted mb-3">Daily personal usage volume over the last 7 calendar days.</p>
              <div class="space-y-2.5">${dailyBars}</div>
            </div>
          </div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 dashboard-section">
          <div class="surf-card border rounded-xl p-4 md:p-5 shadow-sm">
            <h2 class="text-base font-semibold mb-1">Biggest Quota Drivers (Last 7d Personal Threads)</h2>
            <p class="text-xs txt-muted mb-3">Personal Codex/ChatGPT threads ranked by cumulative tokens processed.</p>
            <div class="space-y-2">${threadsHtml}</div>
          </div>
          <div class="surf-card border rounded-xl p-4 md:p-5 shadow-sm">
            <h2 class="text-base font-semibold mb-1">Antigravity Model Pool Breakdown</h2>
            <p class="text-xs txt-muted mb-3">Shared 5-hour pools across Gemini and Claude/GPT-OSS model families.</p>
            <div class="space-y-2">${poolHtml}</div>
          </div>
        </div>
      `;
    }

    function renderClaudePage(data) {
      const claude = data.providers.claude;
      const wins = Object.values(claude.windows || {}).map(renderWindowGauge).join("");
      const bonus = claude.bonus_bucket;
      const samples = (claude.history_samples || []).slice().reverse();
      return `
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 dashboard-section">
          <div class="surf-card border rounded-xl p-5 space-y-3">
            <h2 class="text-base font-semibold">Active Rate-Limit Windows (OAuth Live)</h2>
            ${wins}
            ${bonus ? `
              <div class="surf-sub border rounded-lg p-3.5 space-y-1 text-xs">
                <div class="flex items-center justify-between">
                  <span class="font-semibold">${bonus.label} (${bonus.code_name})</span>
                  <span class="font-mono font-bold text-emerald-400">$${bonus.remaining_dollars.toFixed(2)} remaining</span>
                </div>
                <div class="txt-muted font-mono">Used $${bonus.used_dollars.toFixed(2)} of $${bonus.limit_dollars} (${bonus.used_percent}%) · Resets ${fmtResetDate(bonus.resets_at_epoch)}</div>
              </div>
            ` : ""}
          </div>
          <div class="surf-card border rounded-xl p-5 space-y-3">
            <h2 class="text-base font-semibold">Claude 7-Day Weekly Burn Curve</h2>
            <p class="text-xs txt-muted">Recorded checkpoints from Claude Desktop plan-usage-history.json + live OAuth.</p>
            ${buildBurnSvg(data, "claude")}
            <div class="space-y-1.5 pt-2">
              <div class="text-xs font-semibold">Recent Checkpoints</div>
              ${samples.map(s => `
                <div class="surf-sub border rounded px-3 py-1.5 flex items-center justify-between text-xs font-mono">
                  <span class="txt-muted">${new Date(s.ts * 1000).toLocaleString()}</span>
                  <span>5h: <strong>${s.five_hour_pct}%</strong> · 7d: <strong class="text-orange-400">${s.seven_day_pct}%</strong></span>
                </div>
              `).join("")}
            </div>
          </div>
        </div>
      `;
    }

    function renderChatgptPage(data) {
      const codex = data.providers.chatgpt;
      const wins = Object.values(codex.windows || {}).map(renderWindowGauge).join("");
      const threads = codex.scale_7d?.top_threads || [];
      const maxThreadTok = Math.max(1, ...threads.map(t => t.tokens_used || 0));
      return `
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 dashboard-section">
          <div class="surf-card border rounded-xl p-5 space-y-3">
            <h2 class="text-base font-semibold">Codex / ChatGPT Weekly Limit &amp; Reset Bank</h2>
            ${wins}
            <div class="grid grid-cols-3 gap-2 text-xs">
              <div class="surf-sub border rounded-lg p-3">
                <div class="txt-muted">Reset Credits</div>
                <div class="text-lg font-bold font-mono text-emerald-400 mt-0.5">${codex.reset_credits_available}</div>
              </div>
              <div class="surf-sub border rounded-lg p-3">
                <div class="txt-muted">7d Tokens</div>
                <div class="text-lg font-bold font-mono mt-0.5">${fmtNumber(codex.scale_7d?.total_tokens || 0)}</div>
              </div>
              <div class="surf-sub border rounded-lg p-3">
                <div class="txt-muted">7d Threads / Turns</div>
                <div class="text-lg font-bold font-mono mt-0.5">${codex.scale_7d?.threads_active || 0} / ${codex.scale_7d?.turns_count || 0}</div>
              </div>
            </div>
            <div class="pt-2">
              <h3 class="text-sm font-semibold mb-2">7-Day Burn Curve (Rollout Snapshots)</h3>
              ${buildBurnSvg(data, "chatgpt")}
            </div>
          </div>
          <div class="surf-card border rounded-xl p-5 space-y-3">
            <h2 class="text-base font-semibold">Top Personal Token-Consuming Threads (Last 7d)</h2>
            <p class="text-xs txt-muted">Ranked from ~/.codex/state_5.sqlite (work workspaces excluded).</p>
            <div class="space-y-2">
              ${threads.map(t => `
                <div class="surf-sub border rounded-lg p-3 space-y-1.5">
                  <div class="flex items-center justify-between gap-2 text-xs">
                    <span class="font-medium truncate">${t.title}</span>
                    <span class="font-mono font-bold text-emerald-400 shrink-0">${fmtNumber(t.tokens_used)} tok</span>
                  </div>
                  <div class="w-full h-1.5 rounded bg-slate-800 overflow-hidden">
                    <div class="h-1.5 bg-emerald-500 rounded" style="width: ${Math.round(((t.tokens_used || 0) / maxThreadTok) * 100)}%"></div>
                  </div>
                  <div class="flex items-center justify-between text-xs txt-muted font-mono">
                    <span>${t.cwd || "workspace"} · ${t.model}</span>
                    <span>${new Date(t.updated_at * 1000).toLocaleString()}</span>
                  </div>
                </div>
              `).join("")}
            </div>
          </div>
        </div>
      `;
    }

    function renderAntigravityPage(data) {
      const agy = data.providers.antigravity;
      const wins = Object.values(agy.windows || {}).map(renderWindowGauge).join("");
      const cred = agy.credits || {};
      const models = agy.model_quotas || [];
      return `
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 dashboard-section">
          <div class="surf-card border rounded-xl p-5 space-y-3">
            <h2 class="text-base font-semibold">5-Hour Shared Model Pools &amp; Credits</h2>
            ${wins}
            <div class="grid grid-cols-2 gap-2 text-xs">
              <div class="surf-sub border rounded-lg p-3">
                <div class="txt-muted">Prompt Credits</div>
                <div class="text-base font-bold font-mono text-sky-400 mt-0.5">${cred.available_prompt_credits ?? 0} / ${fmtNumber(cred.monthly_prompt_credits ?? 50000)}</div>
              </div>
              <div class="surf-sub border rounded-lg p-3">
                <div class="txt-muted">Flow Credits</div>
                <div class="text-base font-bold font-mono text-sky-400 mt-0.5">${cred.available_flow_credits ?? 0} / ${fmtNumber(cred.monthly_flow_credits ?? 150000)}</div>
              </div>
              <div class="surf-sub border rounded-lg p-3">
                <div class="txt-muted">7d Active Convs</div>
                <div class="text-base font-bold font-mono mt-0.5">${agy.scale_7d?.conversations_active || 0} (${agy.scale_7d?.user_prompts || 0} prompts)</div>
              </div>
              <div class="surf-sub border rounded-lg p-3">
                <div class="txt-muted">7d Planner Steps / Tools</div>
                <div class="text-base font-bold font-mono mt-0.5">${fmtNumber(agy.scale_7d?.planner_steps || 0)} / ${fmtNumber(agy.scale_7d?.tool_calls || 0)}</div>
              </div>
            </div>
          </div>
          <div class="surf-card border rounded-xl p-5 space-y-2.5">
            <h2 class="text-base font-semibold">All 13 Configured Models (LanguageServer Live)</h2>
            <div class="space-y-1.5">
              ${models.map(m => `
                <div class="surf-sub border rounded-lg px-3 py-2 flex items-center justify-between text-xs font-mono">
                  <span class="font-medium">${m.label}</span>
                  <span><strong class="${m.used_percent > 50 ? 'text-amber-400' : 'text-emerald-400'}">${m.remaining_percent.toFixed(1)}% free</strong> <span class="txt-muted">(${m.used_percent.toFixed(1)}% used · ${fmtResetDate(m.reset_epoch)})</span></span>
                </div>
              `).join("")}
            </div>
          </div>
        </div>
      `;
    }

    function renderAll(data) {
      document.getElementById("account-pill").textContent = data.account || "snackdriven";
      const dtObj = data.generated_at ? new Date(data.generated_at) : new Date();
      document.getElementById("last-updated").textContent = "Updated " + dtObj.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      renderAlertBanner(data);

      const main = document.getElementById("page-content");
      if (PAGE_KEY === "claude") main.innerHTML = renderClaudePage(data);
      else if (PAGE_KEY === "chatgpt") main.innerHTML = renderChatgptPage(data);
      else if (PAGE_KEY === "antigravity") main.innerHTML = renderAntigravityPage(data);
      else main.innerHTML = renderOverviewPage(data);
    }

    async function refreshLive() {
      const btn = document.getElementById("refresh-btn");
      btn.textContent = "Refreshing...";
      btn.disabled = true;
      try {
        const res = await fetch("http://127.0.0.1:8787/api/usage", { cache: "no-store" });
        if (res.ok) {
          STATE = await res.json();
          renderAll(STATE);
        }
      } catch (e) {
        console.warn("Live local server not reachable, showing snapshot", e);
      } finally {
        btn.textContent = "Refresh Live";
        btn.disabled = false;
      }
    }

    renderAll(STATE);
  </script>
</body>
</html>
"""


def render_page_html(data: dict[str, Any], page_key: str = "overview", root_prefix: str = "") -> str:
    meta = PAGE_META.get(page_key, PAGE_META["overview"])
    return (
        HTML_TEMPLATE.replace("__PAGE_KEY__", page_key)
        .replace("__ROOT_PREFIX__", root_prefix)
        .replace("__PAGE_TITLE__", meta["title"])
        .replace("__PAGE_HEADING__", meta["heading"])
        .replace("__PAGE_SUBTITLE__", meta["subtitle"])
        .replace("__INITIAL_DATA__", json.dumps(data))
    )


def export_site(out_dir: str, data: dict[str, Any] | None = None) -> None:
    snap = data or collect_all()
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_page_html(snap, "overview", root_prefix=""))
    for sub in ("claude", "chatgpt", "antigravity"):
        sub_dir = os.path.join(out_dir, sub)
        os.makedirs(sub_dir, exist_ok=True)
        with open(os.path.join(sub_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write(render_page_html(snap, sub, root_prefix="../"))
    with open(os.path.join(out_dir, "CNAME"), "w", encoding="utf-8") as f:
        f.write("usage.snackdriven.com\n")
    with open(os.path.join(out_dir, "usage.json"), "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=2)


def print_cli_summary(data: dict[str, Any]) -> None:
    print(f"=== AI Quota & Scale Summary ({data.get('account')}) @ {data.get('generated_at')} ===")
    for key in ("claude", "chatgpt", "antigravity"):
        p = data["providers"].get(key, {})
        print(f"\n[{p.get('name')} : {p.get('plan')}]")
        for w in (p.get("windows") or {}).values():
            pace = w.get("pace") or {}
            pr = f" | pace={pace['pace_ratio']}x ({pace['elapsed_percent']}% elapsed)" if pace.get("pace_ratio") is not None else ""
            print(f"  - {w['label']}: {w['used_percent']}% used ({w['remaining_percent']}% left){pr}")
        if p.get("bonus_bucket"):
            b = p["bonus_bucket"]
            print(f"  - {b['label']}: ${b['used_dollars']} / ${b['limit_dollars']} used (${b['remaining_dollars']} left)")
        if key == "chatgpt":
            s = p.get("scale_7d") or {}
            print(f"  - Reset Credits Available: {p.get('reset_credits_available', 0)} | 7d Personal Tokens: {s.get('total_tokens', 0):,}")
        if key == "antigravity":
            s = p.get("scale_7d") or {}
            c = p.get("credits") or {}
            print(f"  - Credits: {c.get('available_prompt_credits', 0)} prompt / {c.get('available_flow_credits', 0)} flow | 7d Steps: {s.get('planner_steps', 0):,}")


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path.startswith("/api/usage"):
            data = collect_all()
            body = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        data = collect_all()
        if path.startswith("/claude"):
            html = render_page_html(data, "claude", root_prefix="/").encode("utf-8")
        elif path.startswith("/chatgpt"):
            html = render_page_html(data, "chatgpt", root_prefix="/").encode("utf-8")
        elif path.startswith("/antigravity"):
            html = render_page_html(data, "antigravity", root_prefix="/").encode("utf-8")
        else:
            html = render_page_html(data, "overview", root_prefix="/").encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Personal AI Usage & Quota Dashboard")
    parser.add_argument("--cli", action="store_true", help="Print terminal summary and exit")
    parser.add_argument("--export", metavar="PATH", help="Export standalone HTML dashboard or site directory")
    parser.add_argument("--port", type=int, default=PORT, help="Port to serve live dashboard (default: 8787)")
    args = parser.parse_args()

    if args.cli:
        print_cli_summary(collect_all())
        return

    if args.export:
        target = os.path.abspath(args.export)
        if target.endswith(".html"):
            export_site(os.path.dirname(target))
        else:
            export_site(target)
        print(f"Exported multi-page site to {target}")
        return

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", args.port), DashboardHandler) as httpd:
        print(f"Serving live AI Usage Dashboard at http://127.0.0.1:{args.port}")
        sys.stdout.flush()
        httpd.serve_forever()


if __name__ == "__main__":
    main()
