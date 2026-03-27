import os, glob, socket, subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

def local_ip(fallback="127.0.0.1"):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return fallback
    finally:
        s.close()

REGISTRY_PORT = 5000
registry_host = local_ip()
registry = f"{registry_host}:{REGISTRY_PORT}"

def run(cmd, cwd=None):
    print("\n$ " + " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)

def require_file(p):
    if not os.path.isfile(p):
        raise FileNotFoundError(f"Missing file: {p}")

def require_glob(pattern, hint):
    if not glob.glob(pattern):
        raise FileNotFoundError(f"Missing expected artifact ({hint}): {pattern}")

print('----------------------------------------------------------------------------------------------------\\n')
print("PHASE 2/3 - Building Docker images\\n")
print('----------------------------------------------------------------------------------------------------\\n')
print(f"Registry: {registry}\\n")

# Sensors images (Thorntail)
sensor_dir = os.path.join(PATH, 'sensthread1')
require_file(os.path.join(sensor_dir, "Dockerfile"))
require_glob(os.path.join(sensor_dir, "target", "*-thorntail.jar"), "thorntail jar")
sensor_image = f"{registry}/sensor-sensthread1"
run(["docker", "build", "-t", sensor_image, "."], cwd=sensor_dir)

# Actuators images (Thorntail)
act_dir = os.path.join(PATH, 'acta0')
require_file(os.path.join(act_dir, "Dockerfile"))
require_glob(os.path.join(act_dir, "target", "*-thorntail.jar"), "thorntail jar")
act_image = f"{registry}/actuator-acta0"
run(["docker", "build", "-t", act_image, "."], cwd=act_dir)

# Fog images (Thorntail)
fog_dir = os.path.join(PATH, 'foga0')
require_file(os.path.join(fog_dir, "Dockerfile"))
require_glob(os.path.join(fog_dir, "target", "*-thorntail.jar"), "thorntail jar")
fog_image = f"{registry}/fog-foga0"
run(["docker", "build", "-t", fog_image, "."], cwd=fog_dir)

# Esper images (CEP) (assembly fat jar)
esper_dir = os.path.join(PATH, 'EsperComponentfoga0')
require_file(os.path.join(esper_dir, "Dockerfile"))
require_glob(os.path.join(esper_dir, "target", "*-jar-with-dependencies.jar"), "jar-with-dependencies")
esper_image = f"{registry}/esper-foga0"
run(["docker", "build", "-t", esper_image, "."], cwd=esper_dir)

# ClosedLoopSensor image (reactor batch - thermal model)
cls_dir = os.path.join(PATH, 'ClosedLoopSensor')
if os.path.isdir(cls_dir):
    print("\\n--- ClosedLoopSensor detected, building Docker image... ---")
    require_file(os.path.join(cls_dir, "Dockerfile"))
    require_glob(os.path.join(cls_dir, "target", "*-thorntail.jar"), "thorntail jar")
    cls_image = f"{registry}/closedloopsensor"
    run(["docker", "build", "-t", cls_image, "."], cwd=cls_dir)
else:
    print("\\n--- ClosedLoopSensor not found, skipping. ---")

print('\\n----------------------------------------------------------------------------------------------------\\n')
print("PHASE 2 done.")
print('----------------------------------------------------------------------------------------------------')
input("Press Enter to continue... ")
