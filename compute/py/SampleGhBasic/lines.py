import compute_rhino3d.Util
import compute_rhino3d.Grasshopper as gh
import rhino3dm
import json
import time
import os
import requests
import base64
import io

# --------------------------------------------------------
# CONFIGURATION
# --------------------------------------------------------

compute_url = os.getenv("RHINO_COMPUTE_URL", "http://localhost:6500/")
import compute_rhino3d.Util

compute_rhino3d.Util.url = compute_url

compute_rhino3d.Util.apiKey = os.getenv("RHINO_COMPUTE_KEY", "")

if not compute_rhino3d.Util.url.endswith("/"):
    compute_rhino3d.Util.url += "/"

print(f"Using Rhino Compute endpoint: {compute_rhino3d.Util.url}")
script_dir = os.path.dirname(os.path.abspath(__file__))
definition_path = os.path.join(script_dir, "twisty.gh")

# --------------------------------------------------------
# WAIT FOR COMPUTE TO BE READY
# --------------------------------------------------------

def wait_for_compute(timeout=30):
    print("Waiting for Rhino Compute to become ready...")
    start = time.time()

    headers = {}
    if compute_rhino3d.Util.apiKey:
        headers["RhinoComputeKey"] = compute_rhino3d.Util.apiKey

    while time.time() - start < timeout:
        try:
            r = requests.get(
                compute_rhino3d.Util.url + "version",
                headers=headers,
                timeout=5
            )

            if r.status_code == 200:
                print("Rhino Compute is ready.")
                print("Server version:", r.text)
                return
            elif r.status_code in (401, 403):
                raise RuntimeError(
                    f"Authentication failed ({r.status_code}) at {compute_rhino3d.Util.url}version. "
                    "Check RhinoComputeKey / token permissions."
                )
            else:
                print("Server responded with status:", r.status_code)
                print("Response:", r.text)

        except RuntimeError:
            raise
        except Exception as e:
            print("Connection failed:", e)

        time.sleep(3)

    raise RuntimeError("Rhino Compute did not become ready in time.")


def evaluate_definition_safe(definition, trees):
    args = {"algo": None, "pointer": None, "values": [tree.data for tree in trees]}

    if definition.startswith("http:") or definition.startswith("https:"):
        args["pointer"] = definition
    else:
        encoded = None
        if os.path.isfile(definition):
            if definition.endswith("gh"):
                with open(definition, "rb") as gh_file:
                    encoded = base64.b64encode(gh_file.read())
            else:
                with io.open(definition, "r", encoding="utf-8-sig") as ghx_file:
                    definition = ghx_file.read()
        if not encoded:
            encoded = base64.b64encode(definition.encode("utf-8"))
        args["algo"] = str(encoded, "utf-8")

    posturl = compute_rhino3d.Util.url + "grasshopper"
    headers = {
        "User-Agent": "rhino-developer-samples/SampleGhBasic",
        "Content-Type": "application/json"
    }

    if compute_rhino3d.Util.authToken:
        headers["Authorization"] = "Bearer " + compute_rhino3d.Util.authToken
    if compute_rhino3d.Util.apiKey:
        headers["RhinoComputeKey"] = compute_rhino3d.Util.apiKey

    response = requests.post(posturl, data=json.dumps(args), headers=headers, timeout=120)

    if response.status_code in (401, 403):
        raise RuntimeError(
            f"Authentication failed ({response.status_code}) at {posturl}. "
            "Your RhinoComputeKey/token is not accepted by this server."
        )
    if response.status_code != 200:
        snippet = response.text[:500].strip()
        raise RuntimeError(
            f"HTTP {response.status_code} from {posturl}. Response: {snippet if snippet else '<empty>'}"
        )

    try:
        return response.json()
    except Exception:
        snippet = response.text[:500].strip()
        raise RuntimeError(
            f"Non-JSON response from {posturl}. Response: {snippet if snippet else '<empty>'}"
        )


wait_for_compute()

# --------------------------------------------------------
# BUILD INPUT
# --------------------------------------------------------

pt1 = rhino3dm.Point3d(0, 0, 0)
circle = rhino3dm.Circle(pt1, 5)
angle = 20

curve = json.dumps(circle.ToNurbsCurve().Encode())

curve_tree = gh.DataTree("curve")
curve_tree.Append([0], [curve])

rotate_tree = gh.DataTree("rotate")
rotate_tree.Append([0], [angle])

trees = [curve_tree, rotate_tree]

# --------------------------------------------------------
# CALL GRASSHOPPER WITH RETRY
# --------------------------------------------------------

output = None
last_error = None

for attempt in range(1, 4):
    try:
        print(f"Calling Grasshopper (attempt {attempt}/3)...")
        output = evaluate_definition_safe(definition_path, trees)
        break
    except Exception as error:
        last_error = error
        if attempt < 3:
            print(f"Request failed: {error}")
            print("Retrying in 3 seconds...")
            time.sleep(3)
        else:
            print("Compute call failed after 3 attempts.")
            raise last_error

print("Grasshopper evaluation successful.")
print(output)

# --------------------------------------------------------
# DECODE RESULTS
# --------------------------------------------------------

if not output or "values" not in output:
    raise RuntimeError("Invalid response from Grasshopper.")

branch = output["values"][0]["InnerTree"]["{0;0}"]

lines = [
    rhino3dm.CommonObject.Decode(json.loads(item["data"]))
    for item in branch
]

filename = "twisty.3dm"
print(f"Writing {len(lines)} lines to {filename}")

model = rhino3dm.File3dm()

for l in lines:
    model.Objects.AddCurve(l)

model.Write(filename)

print("Done.")
