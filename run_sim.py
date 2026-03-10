from huggingface_hub import hf_hub_download
import subprocess
import time
import requests

hf_hub_download(
    repo_id="HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive",
    filename="Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf",
    local_dir="models/",)

print("Model downloaded successfully!")

model_path = "models/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf"
proc = subprocess.Popen([
        "llama-server",
        "--model", model_path,
        "--n-gpu-layers", "999",
        "--ctx-size", "32786",
        "--host", "0.0.0.0",
        "--port", "8080",
        "--log-disable",
    ],
    stdout=open("/logs/server.log", "w"),
    stderr=subprocess.STDOUT,
)

print(f"Server PID: {proc.pid}")
for i in range(30):
    time.sleep(2)
    try:
        r = requests.get("http://localhost:8080/health", timeout=3)
        if r.status_code == 200:
            print(f"✓ Server ready after {(i+1)*2}s")
            break
    except requests.ConnectionError:
        pass
else:
    print(" Server did not start in 60s.")

print("server up and runnin, run python/sim.py")