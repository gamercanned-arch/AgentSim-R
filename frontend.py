import asyncio
import json
import os
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
import uvicorn

app = FastAPI()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AgentSim-R | Real-Time Viewer</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #1f2937; }
        ::-webkit-scrollbar-thumb { background: #4b5563; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #6b7280; }
        .log-enter { animation: fadeIn 0.3s ease-out forwards; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
    </style>
</head>
<body class="bg-gray-900 text-gray-100 h-screen flex flex-col font-sans overflow-hidden">
    <header class="bg-gray-800 border-b border-gray-700 p-4 flex items-center justify-between shrink-0">
        <h1 class="text-xl font-bold text-blue-400 tracking-wider">AgentSim-R <span class="text-gray-400 text-sm font-normal ml-2">Live Viewer</span></h1>
        <div class="flex items-center space-x-4">
            <label for="agent-select" class="text-sm text-gray-400">Select Agent:</label>
            <select id="agent-select" class="bg-gray-700 border border-gray-600 text-white text-sm rounded focus:ring-blue-500 focus:border-blue-500 block p-2">
                <option value="">Loading agents...</option>
            </select>
        </div>
    </header>

    <main class="flex-1 flex overflow-hidden">
        <aside class="w-1/3 bg-gray-800 border-r border-gray-700 p-6 overflow-y-auto shrink-0 flex flex-col gap-6">
            <div>
                <h2 class="text-xs uppercase tracking-widest text-gray-500 mb-3">Identity & Status</h2>
                <div class="bg-gray-900 p-4 rounded-lg border border-gray-700">
                    <div class="flex justify-between items-end mb-2">
                        <h3 id="stat-name" class="text-2xl font-bold text-white">-</h3>
                        <span id="stat-activity" class="px-2 py-1 bg-blue-900/50 text-blue-300 text-xs rounded border border-blue-800 uppercase tracking-wide">-</span>
                    </div>
                    <p id="stat-job" class="text-sm text-gray-400 capitalize mb-4">-</p>
                    
                    <div class="grid grid-cols-2 gap-4 text-sm">
                        <div><span class="text-gray-500">Money:</span> <span id="stat-money" class="text-green-400 font-mono">-</span></div>
                        <div><span class="text-gray-500">Wage:</span> <span id="stat-wage" class="text-green-400 font-mono">-</span></div>
                        <div><span class="text-gray-500">Health:</span> <span id="stat-health" class="text-white">-</span></div>
                        <div><span class="text-gray-500">Energy:</span> <span id="stat-energy" class="text-white">-</span></div>
                        <div><span class="text-gray-500">Hunger:</span> <span id="stat-hunger" class="text-white">-</span></div>
                        <div><span class="text-gray-500">Hydration:</span> <span id="stat-hydration" class="text-white">-</span></div>
                        <div><span class="text-gray-500">Stress:</span> <span id="stat-stress" class="text-white">-</span></div>
                        <div><span class="text-gray-500">Happiness:</span> <span id="stat-happiness" class="text-white">-</span></div>
                    </div>
                </div>
            </div>

            <div>
                <h2 class="text-xs uppercase tracking-widest text-gray-500 mb-3">Location & Environment</h2>
                <div class="bg-gray-900 p-4 rounded-lg border border-gray-700 text-sm space-y-3">
                    <div><span class="text-gray-500 block mb-1">Current Location:</span> <span id="stat-loc" class="text-white font-medium">-</span></div>
                    <div><span class="text-gray-500 block mb-1">Coordinates:</span> <span id="stat-coords" class="text-gray-300 font-mono text-xs">-</span></div>
                    <div><span class="text-gray-500 block mb-1">Home:</span> <span id="stat-home" class="text-gray-300">-</span></div>
                </div>
            </div>

            <div class="flex-1">
                <h2 class="text-xs uppercase tracking-widest text-gray-500 mb-3">Inventory</h2>
                <div id="stat-inventory" class="bg-gray-900 p-4 rounded-lg border border-gray-700 text-sm text-gray-300 min-h-[100px]">
                    -
                </div>
            </div>
        </aside>

        <section class="flex-1 flex flex-col bg-gray-900 relative">
            <div id="log-container" class="flex-1 overflow-y-auto p-6 space-y-6 pb-32">
                <div class="text-center text-gray-500 text-sm mt-10" id="waiting-msg">Select an agent to view logs...</div>
            </div>
            <div class="absolute bottom-0 left-0 right-0 h-12 bg-gradient-to-t from-gray-900 to-transparent pointer-events-none"></div>
        </section>
    </main>

    <script>
        const select = document.getElementById('agent-select');
        const logContainer = document.getElementById('log-container');
        const waitingMsg = document.getElementById('waiting-msg');
        let currentEventSource = null;

        fetch('/api/agents').then(res => res.json()).then(data => {
            select.innerHTML = '<option value="">-- Select Agent --</option>';
            data.agents.forEach(agent => {
                const opt = document.createElement('option');
                opt.value = agent;
                opt.textContent = `Agent ${agent}`;
                select.appendChild(opt);
            });
        });

        select.addEventListener('change', (e) => {
            const agentId = e.target.value;
            if (!agentId) return;

            if (currentEventSource) currentEventSource.close();

            logContainer.innerHTML = '';
            waitingMsg.style.display = 'none';

            currentEventSource = new EventSource(`/api/logs/${agentId}`);
            
            currentEventSource.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.error) {
                    logContainer.innerHTML = `<div class="text-red-400 text-center">${data.error}</div>`;
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
            document.getElementById('stat-job').textContent = state.job;
            document.getElementById('stat-money').textContent = `$${state.money.toFixed(2)}`;
            document.getElementById('stat-wage').textContent = `$${state.hourly_wage.toFixed(2)}/h`;
            document.getElementById('stat-health').textContent = `${state.health.toFixed(1)}%`;
            document.getElementById('stat-energy').textContent = `${state.energy.toFixed(1)}%`;
            document.getElementById('stat-hunger').textContent = `${state.hunger.toFixed(1)}%`;
            document.getElementById('stat-hydration').textContent = `${state.hydration.toFixed(1)}%`;
            document.getElementById('stat-stress').textContent = `${state.stress.toFixed(1)}%`;
            document.getElementById('stat-happiness').textContent = `${state.happiness.toFixed(1)}%`;
            
            document.getElementById('stat-loc').textContent = state.location;
            document.getElementById('stat-coords').textContent = `X: ${state.x.toFixed(1)}, Y: ${state.y.toFixed(1)}, Z: ${state.z.toFixed(1)}`;
            document.getElementById('stat-home').textContent = state.home_location || "Homeless";

            const inv = state.inventory.map(i => i.item).join(', ') || "Empty";
            const holding = state.currently_holding ? `<br><span class="text-blue-400">Holding:</span> ${state.currently_holding.item}` : "";
            document.getElementById('stat-inventory').innerHTML = `<span>${inv}</span>${holding}`;
        }

        function appendLog(data) {
            const div = document.createElement('div');
            div.className = "log-enter bg-gray-800 rounded-lg p-5 border border-gray-700 shadow-sm";
            
            const timeStr = data.sim_time ? (data.sim_time / 3600).toFixed(1) + "h" : "Time Unknown";
            let reasoningHTML = "";
            
            if(data.raw_model_reasoning) {
                reasoningHTML = `<div class="text-sm text-gray-400 italic mb-4 border-l-2 border-gray-600 pl-3">"${data.raw_model_reasoning.replace(/\\n/g, '<br>')}"</div>`;
            }

            const outputXML = (data.processed_model_output || data.raw_model_output || "").replace(/</g, "&lt;").replace(/>/g, "&gt;");
            const successColor = data.tool_success ? "text-green-400" : "text-red-400";
            const successBg = data.tool_success ? "bg-green-400/10 border-green-400/20" : "bg-red-400/10 border-red-400/20";

            div.innerHTML = `
                <div class="flex justify-between items-center mb-3">
                    <span class="text-xs font-mono text-gray-500 border border-gray-600 rounded px-2 py-1">Sim Time: ${timeStr}</span>
                    <span class="text-xs text-gray-500">${data.raw_model || "Unknown Model"}</span>
                </div>
                ${reasoningHTML}
                <div class="bg-gray-950 rounded border border-gray-800 p-3 mb-3 font-mono text-xs text-blue-300 overflow-x-auto whitespace-pre-wrap">
                    ${outputXML}
                </div>
                <div class="p-3 rounded border ${successBg}">
                    <span class="text-xs uppercase tracking-wider font-bold ${successColor} block mb-1">Result</span>
                    <span class="text-sm text-gray-200">${data.tool_result}</span>
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
                for line in f:
                    if line.strip(): yield f"data: {line}\n\n"
                
                # Tail new (will safely block here post-mortem without crashing)
                f.seek(0, os.SEEK_END)
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