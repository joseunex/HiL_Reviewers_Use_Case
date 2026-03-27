import os, shutil, socket, subprocess, sys

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

def run(cmd, cwd=None):
    print("\n$ " + " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)

def require_dir(p):
    if not os.path.isdir(p):
        raise FileNotFoundError(f"Missing directory: {p}")

print('----------------------------------------------------------------------------------------------------\\n')
print("PHASE 1/3 - Compiling and packaging (Maven)\\n")
print('----------------------------------------------------------------------------------------------------\\n')
print(f"Host IP (info): {local_ip()}\\n")

# -----------------------------------------------------------------------------------------------------
# PRE-STEP: Copy CSV files into generated sensors
# -----------------------------------------------------------------------------------------------------

# -----------------------------------------------------------------------------------------------------
# Maven builds
# -----------------------------------------------------------------------------------------------------

# Sensors
module_dir = os.path.join(PATH, 'sensthread1')
require_dir(module_dir)
run(["mvn", "clean", "package", "-DskipTests"], cwd=module_dir)

# Actuators
module_dir = os.path.join(PATH, 'acta0')
require_dir(module_dir)
run(["mvn", "clean", "package", "-DskipTests"], cwd=module_dir)

# Fog/Cloud nodes
module_dir = os.path.join(PATH, 'foga0')
require_dir(module_dir)
run(["mvn", "clean", "package", "-DskipTests"], cwd=module_dir)

# Esper components (CEP) – build fat jar (assembly)
esper_dir = os.path.join(PATH, 'EsperComponentfoga0')
require_dir(esper_dir)
run(["mvn", "clean", "compile", "assembly:single", "-DskipTests"], cwd=esper_dir)

# ClosedLoopSensor (reactor batch - thermal model)
cls_dir = os.path.join(PATH, 'ClosedLoopSensor')
if os.path.isdir(cls_dir):
    print("\\n--- ClosedLoopSensor detected, compiling... ---")
    run(["mvn", "clean", "package", "-DskipTests"], cwd=cls_dir)
else:
    print("\\n--- ClosedLoopSensor not found, skipping. ---")

print('\\n----------------------------------------------------------------------------------------------------\\n')
print("PHASE 1 done.")
print('----------------------------------------------------------------------------------------------------')
input("Press Enter to continue... ")
