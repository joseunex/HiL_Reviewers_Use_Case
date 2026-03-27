import socket, subprocess

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

def run(cmd):
    print("\n$ " + " ".join(cmd))
    subprocess.run(cmd, check=True)

def ensure_image_exists(image_ref):
    try:
        subprocess.run(["docker", "image", "inspect", image_ref],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except subprocess.CalledProcessError:
        raise FileNotFoundError(f"Local image not found (build Phase 2 first): {image_ref}")

def image_exists(image_ref):
    try:
        subprocess.run(["docker", "image", "inspect", image_ref],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except subprocess.CalledProcessError:
        return False

print('----------------------------------------------------------------------------------------------------\\n')
print("PHASE 3/3 - Pushing Docker images to registry\\n")
print('----------------------------------------------------------------------------------------------------\\n')
print(f"Registry: {registry}\\n")

# Push fog + api
img = f"{registry}/fog-foga0"
ensure_image_exists(img)
run(["docker", "push", img])

# Push esper
img = f"{registry}/esper-foga0"
ensure_image_exists(img)
run(["docker", "push", img])

# Push actuators and sensors
img = f"{registry}/actuator-acta0"
ensure_image_exists(img)
run(["docker", "push", img])
img = f"{registry}/sensor-sensthread1"
ensure_image_exists(img)
run(["docker", "push", img])

# Push ClosedLoopSensor (reactor batch - thermal model)
cls_image = f"{registry}/closedloopsensor"
if image_exists(cls_image):
    print("\\n--- ClosedLoopSensor image found, pushing... ---")
    run(["docker", "push", cls_image])
else:
    print("\\n--- ClosedLoopSensor image not found, skipping. ---")

print('\\n----------------------------------------------------------------------------------------------------\\n')
print("PHASE 3 done.")
print('----------------------------------------------------------------------------------------------------')
input("Press Enter to continue... ")
