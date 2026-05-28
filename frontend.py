import asyncio
import json
import os
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
import uvicorn

app = FastAPI()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en" class="h-full">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AgentSim-R | Cyber-Monitor</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&family=Space+Grotesk:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
        body {
            font-family: 'Space Grotesk', sans-serif;
            background-color: #07090e;
            background-image: 
                radial-gradient(at 0% 0%, rgba(16, 24, 48, 0.5) 0px, transparent 50%),
                radial-gradient(at 100% 0%, rgba(45, 10, 60, 0.3) 0px, transparent 50%),
                radial-gradient(at 50% 100%, rgba(10, 30, 60, 0.4) 0px, transparent 70%);
        }
        .font-mono {
            font-family: 'JetBrains Mono', monospace;
        }
        /* Custom scrollbar */
        ::-webkit-scrollbar { width: 5px; height: 5px; }
        ::-webkit-scrollbar-track { background: rgba(7, 9, 14, 0.6); }
        ::-webkit-scrollbar-thumb { background: rgba(59, 130, 246, 0.3); border-radius: 4px; border: 1px solid rgba(59, 130, 246, 0.1); }
        ::-webkit-scrollbar-thumb:hover { background: rgba(59, 130, 246, 0.6); }
        
        /* Glassmorphism */
        .glass-panel {
            background: rgba(13, 17, 28, 0.7);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.05);
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        }
        
        .glow-blue {
            box-shadow: 0 0 15px rgba(59, 130, 246, 0.2);
            border: 1px solid rgba(59, 130, 246, 0.4);
        }
        
        .glow-purple {
            box-shadow: 0 0 15px rgba(168, 85, 247, 0.2);
            border: 1px solid rgba(168, 85, 247, 0.4);
        }

        .log-enter { 
            animation: slideIn 0.35s cubic-bezier(0.16, 1, 0.3, 1) forwards; 
        }
        @keyframes slideIn { 
            from { opacity: 0; transform: translateY(20px) scale(0.98); } 
            to { opacity: 1; transform: translateY(0) scale(1); } 
        }
    </style>
</head>
<body class="text-slate-100 h-full flex flex-col overflow-hidden">
    <header class="bg-slate-950/80 backdrop-blur-md border-b border-slate-800/80 px-6 py-4 flex items-center justify-between shrink-0 z-10">
        <div class="flex items-center space-x-3">
            <div class="w-3 h-3 bg-blue-500 rounded-full animate-pulse shadow-[0_0_8px_#3b82f6]"></div>
            <h1 class="text-xl font-bold tracking-tight bg-gradient-to-r from-blue-400 via-indigo-300 to-purple-400 bg-clip-text text-transparent">
                AgentSim-R <span class="text-slate-500 font-mono text-xs ml-2">v2.1_api_monitor</span>
            </h1>
        </div>
        <div class="flex items-center space-x-3">
            <span class="text-xs font-mono text-slate-500">SELECT MODULE:</span>
            <select id="agent-select" class="bg-slate-900/90 border border-slate-700/80 text-slate-200 text-sm font-medium rounded-lg focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 block px-3 py-2 outline-none transition-all">
                <option value="">Loading telemetry...</option>
            </select>
        </div>
    </header>

    <main class="flex-1 flex overflow-hidden">
        <!-- Sidebar -->
        <aside class="w-96 bg-slate-950/40 p-6 overflow-y-auto shrink-0 flex flex-col gap-6 border-r border-slate-900">
            <div>
                <h2 class="text-xs font-mono uppercase tracking-widest text-slate-500 mb-3 flex items-center">
                    <span class="w-1.5 h-1.5 bg-blue-400 rounded-full mr-2"></span>Identity & Status
                </h2>
                <div class="glass-panel p-5 rounded-xl border border-slate-800/80">
                    <div class="flex justify-between items-end mb-3">
                        <h3 id="stat-name" class="text-2xl font-bold tracking-tight text-white">-</h3>
                        <span id="stat-activity" class="px-2.5 py-0.5 bg-blue-950/80 text-blue-400 text-xs font-mono rounded border border-blue-900/50 uppercase tracking-wide">-</span>
                    </div>
                    <p id="stat-job" class="text-xs font-mono text-slate-400 uppercase tracking-wider mb-5">-</p>
                    
                    <div class="grid grid-cols-2 gap-y-4 gap-x-2 text-sm font-mono border-t border-slate-800/60 pt-4">
                        <div><span class="text-slate-500 block text-xs">CASH BALANCE</span> <span id="stat-money" class="text-emerald-400 font-semibold text-base">-</span></div>
                        <div><span class="text-slate-500 block text-xs">HOURLY WAGE</span> <span id="stat-wage" class="text-emerald-400 font-semibold text-base">-</span></div>
                        <div><span class="text-slate-500 block text-xs">VITAL SIGNS</span> <span id="stat-health" class="text-slate-200 font-semibold text-base">-</span></div>
                        <div><span class="text-slate-500 block text-xs">ENERGY SYSTEM</span> <span id="stat-energy" class="text-slate-200 font-semibold text-base">-</span></div>
                        <div><span class="text-slate-500 block text-xs">NUTRITION</span> <span id="stat-hunger" class="text-slate-200 font-semibold text-base">-</span></div>
                        <div><span class="text-slate-500 block text-xs">HYDRATION</span> <span id="stat-hydration" class="text-slate-200 font-semibold text-base">-</span></div>
                        <div><span class="text-slate-500 block text-xs">STRESS LEVEL</span> <span id="stat-stress" class="text-slate-200 font-semibold text-base">-</span></div>
                        <div><span class="text-slate-500 block text-xs">HAPPINESS INDEX</span> <span id="stat-happiness" class="text-slate-200 font-semibold text-base">-</span></div>
                    </div>
                </div>
            </div>

            <div>
                <h2 class="text-xs font-mono uppercase tracking-widest text-slate-500 mb-3 flex items-center">
                    <span class="w-1.5 h-1.5 bg-indigo-400 rounded-full mr-2"></span>Geo Tracking
                </h2>
                <div class="glass-panel p-5 rounded-xl border border-slate-800/80 font-mono text-sm space-y-4">
                    <div>
                        <span class="text-slate-500 block text-xs mb-1">CURRENT AREA</span>
                        <span id="stat-loc" class="text-white font-medium">-</span>
                    </div>
                    <div>
                        <span class="text-slate-500 block text-xs mb-1">COORDINATES (3D)</span>
                        <span id="stat-coords" class="text-indigo-300 text-xs">-</span>
                    </div>
                    <div>
                        <span class="text-slate-500 block text-xs mb-1">REGISTERED DOMICILE</span>
                        <span id="stat-home" class="text-slate-300">-</span>
                    </div>
                </div>
            </div>
            <div>
                <h2 class="text-xs font-mono uppercase tracking-widest text-slate-500 mb-3 flex items-center">
                    <span class="w-1.5 h-1.5 bg-purple-400 rounded-full mr-2"></span>Token Telemetry
                </h2>
                <div class="glass-panel p-5 rounded-xl border border-slate-800/80 font-mono text-sm space-y-3">
                    <div id="token-usages-container" class="space-y-2">
                        <div class="text-slate-500 text-xs">NO USAGE RECORDED</div>
                    </div>
                    <div class="border-t border-slate-800/60 pt-2 flex justify-between text-xs">
                        <span class="text-slate-400">TOTAL COMBINED</span>
                        <span id="stat-total-tokens" class="text-blue-400 font-bold">0</span>
                    </div>
                </div>
            </div>

            <div class="flex-1 flex flex-col min-h-[160px]">
                <h2 class="text-xs font-mono uppercase tracking-widest text-slate-500 mb-3 flex items-center">
                    <span class="w-1.5 h-1.5 bg-purple-400 rounded-full mr-2"></span>Cargo & Inventory
                </h2>
                <div id="stat-inventory" class="glass-panel p-5 rounded-xl border border-slate-800/80 text-sm text-slate-300 flex-1 flex flex-col justify-between font-mono gap-3">
                    -
                </div>
            </div>
        </aside>

        <!-- Monitor Feed -->
        <section class="flex-1 flex flex-col bg-slate-950/20 relative">
            <!-- Subtle Grid Background -->
            <div class="absolute inset-0 bg-[linear-gradient(rgba(18,24,38,0.05)_1px,transparent_1px),linear-gradient(90deg,rgba(18,24,38,0.05)_1px,transparent_1px)] bg-[size:32px_32px] pointer-events-none"></div>
            
            <div id="log-container" class="flex-1 overflow-y-auto p-8 space-y-6 pb-36 relative z-10">
                <div class="flex flex-col items-center justify-center h-full text-slate-500 space-y-3" id="waiting-msg">
                    <div class="w-8 h-8 border-2 border-slate-700 border-t-blue-500 rounded-full animate-spin"></div>
                    <div class="font-mono text-sm">AWAITING CLIENT SELECT TELEMETRY...</div>
                </div>
            </div>
            <!-- Bottom Fade Shadow -->
            <div class="absolute bottom-0 left-0 right-0 h-24 bg-gradient-to-t from-slate-950 to-transparent pointer-events-none z-10"></div>
        </section>
    </main>

    <script>
        const select = document.getElementById('agent-select');
        const logContainer = document.getElementById('log-container');
        const waitingMsg = document.getElementById('waiting-msg');
        let currentEventSource = null;

        fetch('/api/agents').then(res => res.json()).then(data => {
            select.innerHTML = '<option value="">-- TELEMETRY OFFLINE --</option>';
            if(data.agents && data.agents.length > 0) {
                select.innerHTML = '<option value="">-- CONNECT AGENT --</option>';
                data.agents.forEach(agent => {
                    const opt = document.createElement('option');
                    opt.value = agent;
                    opt.textContent = `AGENT #${agent.padStart(2, '0')}`;
                    select.appendChild(opt);
                });
            }
        });

        select.addEventListener('change', (e) => {
            const agentId = e.target.value;
            if (!agentId) return;

            if (currentEventSource) currentEventSource.close();

            logContainer.innerHTML = '';
            waitingMsg.style.display = 'none';

            select.className = "bg-slate-900/90 border border-blue-500/50 text-blue-300 text-sm font-medium rounded-lg focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 block px-3 py-2 outline-none transition-all glow-blue";

            currentEventSource = new EventSource(`/api/logs/${agentId}`);
            
            currentEventSource.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.error) {
                    logContainer.innerHTML = `<div class="text-red-400 text-center font-mono border border-red-900/30 bg-red-950/20 p-4 rounded-lg">${escapeHTML(data.error)}</div>`;
                    return;
                }
                updateStats(data.post_state);
                appendLog(data);
            };
        });

        function updateStats(state) {
            if(!state) return;
            document.getElementById('stat-name').textContent = state.name;
            document.getElementById('stat-activity').textContent = state.current_activity;
            document.getElementById('stat-job').textContent = state.job || "Unemployed";
            document.getElementById('stat-money').textContent = `$${state.money.toFixed(2)}`;
            document.getElementById('stat-wage').textContent = `$${state.hourly_wage.toFixed(2)}/h`;
            document.getElementById('stat-health').textContent = `${state.health.toFixed(1)}%`;
            document.getElementById('stat-energy').textContent = `${state.energy.toFixed(1)}%`;
            document.getElementById('stat-hunger').textContent = `${state.hunger.toFixed(1)}%`;
            document.getElementById('stat-hydration').textContent = `${state.hydration.toFixed(1)}%`;
            document.getElementById('stat-stress').textContent = `${state.stress.toFixed(1)}%`;
            document.getElementById('stat-happiness').textContent = `${state.happiness.toFixed(1)}%`;
            
            document.getElementById('stat-loc').textContent = state.location;
            document.getElementById('stat-coords').textContent = `X: ${state.x.toFixed(1)} | Y: ${state.y.toFixed(1)} | Z: ${state.z.toFixed(1)}`;
            document.getElementById('stat-home').textContent = state.home_location || "Homeless / Co-op";

            const inv = escapeHTML(state.inventory.map(i => i.item).join(', ') || "Empty");
            const holding = state.currently_holding ? `<div class="mt-2 pt-2 border-t border-slate-800/40"><span class="text-blue-400 font-semibold">HOLDING:</span> ${escapeHTML(state.currently_holding.item)}</div>` : "";
            document.getElementById('stat-inventory').innerHTML = `<div class="text-slate-400">${inv}</div>${holding}`;

            // Update token usage registry
            const tokens = state.global_token_usage || {};
            const container = document.getElementById('token-usages-container');
            let total = 0;
            let html = "";
            
            Object.keys(tokens).forEach(model => {
                const prompt = tokens[model].prompt || 0;
                const completion = tokens[model].completion || 0;
                const sum = tokens[model].total || (prompt + completion);
                const safeModel = escapeHTML(model);
                total += sum;
                
                html += `
                    <div class="flex justify-between items-center text-xs">
                        <span class="text-slate-300 truncate max-w-[180px]" title="${safeModel}">${safeModel}</span>
                        <span class="text-slate-400 font-mono">${sum} <span class="text-[9px] text-slate-600">(${prompt}p/${completion}c)</span></span>
                    </div>
                `;
            });
            
            if (html === "") {
                container.innerHTML = `<div class="text-slate-500 text-xs">NO USAGE RECORDED</div>`;
            } else {
                container.innerHTML = html;
            }
            document.getElementById('stat-total-tokens').textContent = total;
        }

        function escapeHTML(value) {
            return (value || "").toString()
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#39;");
        }

        function appendLog(data) {
            const div = document.createElement('div');
            
            const successBorder = data.tool_success ? "border-l-4 border-emerald-500" : "border-l-4 border-rose-500";
            div.className = `log-enter glass-panel rounded-xl p-5 border border-slate-800/60 shadow-lg ${successBorder} relative overflow-hidden`;
            
            // Background glows for cards
            const glowBg = data.tool_success ? "bg-emerald-950/5" : "bg-rose-950/5";
            div.classList.add(glowBg);
            
            const timeStr = data.sim_time ? (data.sim_time / 3600).toFixed(1) + "h" : "Time Unknown";
            let reasoningHTML = "";
            
            if(data.raw_model_reasoning) {
                const safeReasoning = escapeHTML(data.raw_model_reasoning).replace(/\n/g, '<br>');
                reasoningHTML = `
                    <div class="mb-4">
                        <span class="text-[10px] font-mono tracking-wider text-slate-500 block mb-1 uppercase">Cognitive Process</span>
                        <div class="text-sm text-slate-300/80 font-normal italic border-l border-slate-700 pl-3">"${safeReasoning}"</div>
                    </div>
                `;
            }

            const outputXML = escapeHTML(data.processed_model_output || data.raw_model_output || "");
            const escapedToolResult = escapeHTML(data.tool_result || "");
            const successColor = data.tool_success ? "text-emerald-400" : "text-rose-400";
            const successBg = data.tool_success ? "bg-emerald-950/30 border-emerald-900/30" : "bg-rose-950/30 border-rose-900/30";

            div.innerHTML = `
                <div class="flex justify-between items-center mb-4 border-b border-slate-800/60 pb-3 font-mono text-[10px] tracking-wider text-slate-500">
                    <span class="bg-slate-900 border border-slate-800 rounded px-2 py-0.5">METRIC TIME: ${timeStr}</span>
                    <span class="text-slate-400">${escapeHTML(data.raw_model || "Unknown Model")}</span>
                </div>
                ${reasoningHTML}
                <div class="mb-4">
                    <span class="text-[10px] font-mono tracking-wider text-slate-500 block mb-1 uppercase">Structured Tool Command</span>
                    <div class="bg-slate-950 rounded-lg border border-slate-900 p-3.5 font-mono text-xs text-blue-300 overflow-x-auto whitespace-pre-wrap">
                        ${outputXML}
                    </div>
                </div>
                <div class="p-3.5 rounded-lg border ${successBg}">
                    <span class="text-[10px] uppercase tracking-wider font-bold ${successColor} block mb-1 font-mono">Response Feedback</span>
                    <span class="text-sm text-slate-200 font-mono">${escapedToolResult}</span>
                </div>
            `;
            logContainer.appendChild(div);
            logContainer.scrollTop = logContainer.scrollHeight;
        }
    </script>
</body>
</html>
"""

@app.get("/")
async def get_root():
    return HTMLResponse(HTML_TEMPLATE)

@app.get("/api/agents")
async def get_agents():
    if not os.path.exists("logs"): return {"agents": []}
    files = [f for f in os.listdir("logs") if f.startswith("agent_") and f.endswith(".log")]
    agents = [f.replace("agent_", "").replace(".log", "") for f in files]
    return {"agents": sorted(agents, key=lambda x: int(x) if x.isdigit() else x)}

@app.get("/api/logs/{agent_id}")
async def stream_logs(agent_id: str):
    async def event_generator():
        filepath = f"logs/agent_{agent_id}.log"
        if not os.path.exists(filepath):
            yield f"data: {json.dumps({'error': 'No log found'})}\n\n"
            return
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                # Send existing
                while True:
                    line = f.readline()
                    if not line:
                        break
                    if line.strip():
                        yield f"data: {line}\n\n"
                
                # Tail new (will safely block here post-mortem without crashing)
                while True:
                    line = f.readline()
                    if not line:
                        await asyncio.sleep(0.5)
                        continue
                    if line.strip():
                        yield f"data: {line}\n\n"
        except (asyncio.CancelledError, RuntimeError):
            # Cleanly handle client disconnects
            return

    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9261)
