#!/usr/bin/env python3
"""Host-side VR demo lifecycle. Uses only Python's standard library."""

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone


class DemoError(Exception):
    pass


def run(*args, capture=False, check=True, cwd=None):
    result = subprocess.run(
        [str(arg) for arg in args], cwd=cwd, check=False,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None, text=True,
    )
    if check and result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        raise DemoError(f"{args[0]} failed (exit {result.returncode}). {detail}")
    return result


def digest(data):
    return hashlib.sha256(data).hexdigest()


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


class Demo:
    label = "io.humanova.g1-vr"
    workdir = "/workspaces/isaaclab_arena"

    def __init__(self):
        self.root = Path(os.environ["DEMO_DIR"]).resolve()
        self.state = Path(os.environ.get("DEMO_STATE_DIR", str(self.root / ".local"))).expanduser().resolve()
        self.arena = self.state / "IsaacLab-Arena"
        self.image = os.environ.get("DEMO_IMAGE", "humanova/g1-apple-vr:arena-8b4a3a47")
        self.container = os.environ.get("DEMO_CONTAINER", "humanova-g1-apple-vr")
        self.commit = os.environ["ARENA_COMMIT"]
        self.user = run("id", "-un", capture=True).stdout.strip()
        self.group = run("id", "-gn", capture=True).stdout.strip()
        self.container_home = f"/home/{self.user}"

    def require_env(self):
        if not (self.root / ".env").is_file():
            raise DemoError("Create the local environment first: ./demo.sh init")
        if os.getuid() == 0:
            raise DemoError("Run this demo as your desktop user, without sudo.")
        if os.environ.get("PHYSICS_DEVICE") not in ("cpu", "cuda"):
            raise DemoError("PHYSICS_DEVICE in .env must be cpu or cuda.")
        if os.environ.get("ENABLE_CAMERAS") not in ("0", "1"):
            raise DemoError("ENABLE_CAMERAS in .env must be 0 or 1.")

    @contextmanager
    def lifecycle_lock(self):
        self.state.mkdir(parents=True, exist_ok=True)
        with (self.state / "lifecycle.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DemoError("Another setup/container operation is in progress. Wait for it to finish.")
            yield

    def require_commands(self, *commands):
        missing = [command for command in commands if shutil.which(command) is None]
        if missing:
            raise DemoError("Missing host commands: " + ", ".join(missing) + ". See README.md.")

    def require_docker(self):
        self.require_commands("docker")
        result = run("docker", "info", "--format", "{{.ServerVersion}}", capture=True, check=False)
        if result.returncode:
            raise DemoError("Docker is unavailable to this user. Check the daemon, context, and group membership.\n"
                            + result.stderr.strip())

    def init(self):
        path = self.root / ".env"
        if path.exists():
            print("Keeping existing .env.")
            return
        with path.open("x") as destination:
            destination.write((self.root / ".env.example").read_text())
        path.chmod(0o600)
        print("Created .env. Set HEADSET_SERVER_IP to this workstation's LAN IPv4 address.")

    def doctor(self):
        self.require_commands("git", "docker", "nvidia-smi", "xhost")
        if platform.system() != "Linux" or platform.machine() not in ("x86_64", "amd64"):
            raise DemoError("This demo targets a Linux x86_64 workstation.")
        run("git", "lfs", "version")
        self.require_docker()
        run("nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader")
        display = os.environ.get("DISPLAY", "")
        if not display:
            raise DemoError("DISPLAY is empty. Run from your graphical desktop session.")
        run("xhost", capture=True)
        storage = self.state
        while not storage.exists():
            storage = storage.parent
        print(f"Free storage at {storage}: {shutil.disk_usage(storage).free // 2**30} GiB")
        print(f"Display: {display}")
        print(f"Runtime files: {self.state}")
        print("Host checks passed.")

    def recipe(self):
        return {
            "arena_commit": self.commit,
            "isaac_sim_base_image": os.environ["ISAAC_SIM_BASE_IMAGE"],
        }

    def recipe_hash(self):
        return digest(json.dumps(self.recipe(), sort_keys=True).encode())

    def git(self, *args, **kwargs):
        return run("git", "-C", self.arena, *args, **kwargs)

    def verify_source(self):
        marker = self.state / "source.json"
        if not marker.is_file():
            raise DemoError("Source is not prepared. Run ./demo.sh prepare (or ./demo.sh setup).")
        prepared = json.loads(marker.read_text())
        if prepared["recipe"] != self.recipe():
            raise DemoError("Source settings changed. Choose a new DEMO_STATE_DIR and run setup.")
        if self.git("rev-parse", "HEAD", capture=True).stdout.strip() != self.commit:
            raise DemoError("The managed Arena checkout changed revision; refusing to use it.")
        clean = self.git("diff", "--quiet", "HEAD", capture=True, check=False)
        if clean.returncode:
            raise DemoError("The managed Arena checkout must match the unmodified upstream source. "
                            "Preserve your edits and choose a new DEMO_STATE_DIR.")
        untracked = self.git("ls-files", "--others", "--exclude-standard", capture=True).stdout.strip()
        if untracked:
            raise DemoError("Unexpected untracked files in managed Arena checkout:\n" + untracked)
        submodules = self.git("submodule", "status", "--recursive", capture=True).stdout
        if any(line and line[0] != " " for line in submodules.splitlines()):
            raise DemoError("Arena submodules are missing, conflicted, or at different revisions.")
        # submodule status alone does not detect edits within a submodule.
        self.git("submodule", "foreach", "--recursive",
                 'test -z "$(git status --porcelain)"', capture=True)

    def prepare(self):
        self.require_commands("git")
        run("git", "lfs", "version")
        if (self.state / "source.json").exists():
            self.verify_source()
            print("Pinned Arena sources are already prepared.")
            return
        self.state.mkdir(parents=True, exist_ok=True)
        intent = self.state / "preparing.json"
        identity = {"demo": str(self.root), "recipe": self.recipe()}
        if self.arena.exists():
            if not intent.is_file() or json.loads(intent.read_text()) != identity:
                raise DemoError(f"Refusing to modify an unmanaged or incomplete checkout: {self.arena}\n"
                                "Move it aside or choose a new DEMO_STATE_DIR; existing installations are never reset.")
            if self.git("rev-parse", "HEAD", capture=True).stdout.strip() != self.commit:
                raise DemoError("Incomplete setup is at an unexpected revision; preserve it and use a new state directory.")
            # A network failure during submodule download is safe to resume.
            # Exclude submodules here: they can still be missing at this point.
            dirty = self.git("diff", "--ignore-submodules=all", "HEAD", capture=True).stdout
            untracked = self.git("ls-files", "--others", "--exclude-standard", capture=True).stdout
            if dirty or untracked:
                raise DemoError("Incomplete setup has local edits; preserve it and use a new state directory.")
        else:
            write_json(intent, identity)
            source = os.environ.get("ARENA_CLONE_SOURCE") or os.environ["ARENA_GIT_URL"]
            # --no-hardlinks keeps the managed clone independent of a local source.
            run("git", "clone", "--no-hardlinks", "--no-checkout", source, self.arena)
            self.git("checkout", "--detach", self.commit)
        # Public submodules use SSH URLs upstream. Rewrite only for this command,
        # including nested submodules; no SSH keys or global Git changes needed.
        self.git("-c", "url.https://github.com/.insteadOf=git@github.com:",
                 "submodule", "update", "--init", "--recursive")
        write_json(self.state / "source.json", {
            "recipe": self.recipe(),
        })
        self.verify_source()
        print(f"Prepared isolated Arena checkout: {self.arena}")

    def inspect(self, kind, name):
        result = run("docker", kind, "inspect", name, capture=True, check=False)
        return json.loads(result.stdout)[0] if result.returncode == 0 else None

    def build(self, no_cache=False):
        self.verify_source()
        self.require_docker()
        existing = self.inspect("image", self.image)
        labels = (existing or {}).get("Config", {}).get("Labels") or {}
        if existing and labels.get(self.label) != "true":
            raise DemoError(f"Image {self.image} was not built by this demo. Choose a different DEMO_IMAGE.")
        if existing and labels.get(self.label + ".recipe") == self.recipe_hash() and not no_cache:
            print(f"Matching image already built: {self.image}")
            return
        args = ["docker", "build", "--progress=plain",
                "--build-arg", f"BASE_IMAGE={os.environ['ISAAC_SIM_BASE_IMAGE']}",
                "--build-arg", f"WORKDIR={self.workdir}",
                "--build-arg", "INSTALL_GROOT=false",
                "--label", f"{self.label}=true",
                "--label", f"{self.label}.recipe={self.recipe_hash()}",
                "--tag", self.image, "--file", self.arena / "docker/Dockerfile.isaaclab_arena"]
        if no_cache:
            args.append("--no-cache")
        args.append(self.arena)
        run(*args)
        image = self.inspect("image", self.image)
        base = self.inspect("image", os.environ["ISAAC_SIM_BASE_IMAGE"])
        write_json(self.state / "build.json", {
            "built_at": datetime.now(timezone.utc).isoformat(), "recipe": self.recipe(),
            "image": self.image, "image_id": image["Id"],
            "base_image_digests": (base or {}).get("RepoDigests", []),
        })
        print(f"Built {self.image}. Start CloudXR next: ./demo.sh cloudxr")

    def checked_container(self):
        container = self.inspect("container", self.container)
        if container:
            labels = container["Config"].get("Labels") or {}
            if labels.get(self.label + ".owner") != str(self.root):
                raise DemoError(f"Container name {self.container} belongs to another setup. "
                                "Choose a different DEMO_CONTAINER.")
        return container

    def start(self):
        self.verify_source()
        self.require_docker()
        image = self.inspect("image", self.image)
        labels = (image or {}).get("Config", {}).get("Labels") or {}
        if labels.get(self.label + ".recipe") != self.recipe_hash():
            raise DemoError("The matching demo image is missing. Run ./demo.sh build.")
        if os.environ.get("ACCEPT_EULA") != "Y":
            raise DemoError("Isaac Sim requires ACCEPT_EULA=Y in .env. See the terms linked in README.md.")
        self.require_commands("xhost")
        if not os.environ.get("DISPLAY"):
            raise DemoError("DISPLAY is empty. Launch from the workstation desktop.")
        # Authorize the matching desktop UID, rather than all local users.
        run("xhost", f"+si:localuser:{self.user}", capture=True)
        xauthority = Path(os.environ.get("XAUTHORITY") or str(Path.home() / ".Xauthority"))
        settings = {
            "image_id": image["Id"], "state": str(self.state),
            "uid": os.getuid(), "gid": os.getgid(),
            "display": os.environ.get("DISPLAY", ""),
            "xauthority": str(xauthority), "xauthority_exists": xauthority.is_file(),
            "physics_device": os.environ["PHYSICS_DEVICE"],
            "enable_cameras": os.environ["ENABLE_CAMERAS"],
            "accept_eula": os.environ["ACCEPT_EULA"],
            "privacy_consent": os.environ.get("PRIVACY_CONSENT", "N"),
        }
        fingerprint = digest(json.dumps(settings, sort_keys=True).encode())
        container = self.checked_container()
        if container and container["State"]["Running"]:
            if container["Config"]["Labels"].get(self.label + ".settings") != fingerprint:
                raise DemoError("Container settings changed. Run ./demo.sh stop, then launch again.")
        else:
            if container:
                run("docker", "container", "rm", self.container)
            for directory in ("home", "cache", "datasets", "eval"):
                (self.state / directory).mkdir(parents=True, exist_ok=True)
            args = ["docker", "run", "--detach", "--interactive", "--tty",
                    "--name", self.container, "--init", "--network", "host", "--ipc", "host",
                    "--runtime", "nvidia", "--gpus", "all",
                    "--ulimit", "memlock=-1", "--ulimit", "stack=67108864",
                    "--label", f"{self.label}.owner={self.root}",
                    "--label", f"{self.label}.settings={fingerprint}",
                    "--workdir", self.workdir]
            for source, destination, mode in (
                (self.arena, self.workdir, "rw"), (self.root, "/demo", "ro"),
                (self.state / "home", self.container_home, "rw"),
                (self.state / "cache", self.container_home + "/.cache", "rw"),
                (self.state / "datasets", "/datasets", "rw"),
                (self.state / "eval", "/eval", "rw"),
                (Path("/tmp/.X11-unix"), "/tmp/.X11-unix", "rw"),
            ):
                args.extend(["--volume", f"{source}:{destination}:{mode}"])
            if xauthority.is_file():
                args.extend(["--volume", f"{xauthority}:/tmp/demo.Xauthority:ro",
                             "--env", "XAUTHORITY=/tmp/demo.Xauthority"])
            environment = {
                "DISPLAY": settings["display"], "ACCEPT_EULA": settings["accept_eula"],
                "PRIVACY_CONSENT": settings["privacy_consent"],
                "DOCKER_RUN_USER_ID": str(os.getuid()), "DOCKER_RUN_USER_NAME": self.user,
                "DOCKER_RUN_GROUP_ID": str(os.getgid()), "DOCKER_RUN_GROUP_NAME": self.group,
                "ISAACLAB_PATH": self.workdir + "/submodules/IsaacLab",
                "PHYSICS_DEVICE": settings["physics_device"],
                "ENABLE_CAMERAS": settings["enable_cameras"],
            }
            for key, value in environment.items():
                args.extend(["--env", f"{key}={value}"])
            args.extend([self.image, "touch /tmp/humanova-ready && exec sleep infinity"])
            run(*args)
        for _ in range(60):
            ready = run("docker", "exec", self.container, "test", "-f", "/tmp/humanova-ready",
                        capture=True, check=False)
            if ready.returncode == 0:
                write_json(self.state / "session.json", {
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "recipe": self.recipe(), "settings": settings,
                    "task": {key: os.environ[key] for key in
                             ("TASK_NAME", "TASK_OBJECT", "TASK_DESTINATION", "TELEOP_DEVICE")},
                })
                return
            current = self.checked_container()
            if not current or not current["State"]["Running"]:
                break
            time.sleep(0.5)
        run("docker", "logs", "--tail", "60", self.container, check=False)
        raise DemoError("Container initialization failed. Inspect ./demo.sh status and Docker logs.")

    def dataset_path(self, filename):
        relative = Path(filename)
        if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".hdf5":
            raise DemoError("Dataset file must be a relative .hdf5 path within the datasets directory.")
        directory = (self.state / "datasets").resolve()
        host_path = (directory / relative).resolve()
        if not host_path.is_relative_to(directory):
            raise DemoError("Dataset file must stay within the datasets directory.")
        container_path = "/datasets/" + host_path.relative_to(directory).as_posix()
        return host_path, container_path

    def record(self, filename, num_demos, num_success_steps):
        host_path, container_path = self.dataset_path(filename)
        if host_path.exists() or host_path.is_symlink():
            raise DemoError(f"Recording already exists: {host_path}\n"
                            "Choose a new session file with --dataset-file; recordings are never overwritten.")
        print(f"Recording output: {host_path}", flush=True)
        print(f"Target: {num_demos} successful demonstrations; "
              f"{num_success_steps} consecutive success steps. "
              f"Physics: {os.environ['PHYSICS_DEVICE']}. Cameras: enabled.", flush=True)
        self.execute("record", (container_path, str(num_demos), str(num_success_steps)))

    def replay(self, filename):
        host_path, container_path = self.dataset_path(filename)
        if not host_path.is_file():
            raise DemoError(f"Recorded dataset not found: {host_path}")
        print(f"Replaying dataset: {host_path}", flush=True)
        self.execute("replay", (container_path,))

    def execute(self, action, arguments=()):
        with self.lifecycle_lock():
            self.start()
        args = ["docker", "exec", "--interactive"]
        if sys.stdin.isatty() and sys.stdout.isatty():
            args.append("--tty")
        # Use the username so Docker retains the isaac-sim supplementary group
        # assigned by Arena's entrypoint; an explicit UID:GID discards it.
        args.extend(["--user", self.user,
                     "--env", f"HOME={self.container_home}", "--workdir", self.workdir,
                     self.container, "bash", "/demo/scripts/in-container.sh", action, *arguments])
        # Replace this process so Ctrl+C reaches the foreground session.
        os.execvp("docker", args)

    def stop(self):
        self.require_docker()
        container = self.checked_container()
        if not container:
            print("Demo container is already stopped.")
            return
        if container["State"]["Running"]:
            run("docker", "stop", "--time", "15", self.container)
        run("docker", "container", "rm", self.container)
        print("Stopped the demo container. Sources, caches, and CloudXR settings are preserved.")

    def status(self):
        self.require_docker()
        container = self.checked_container()
        print(f"Source: {self.arena}")
        print(f"Image: {self.image}")
        print(f"Container: {self.container} ({container['State']['Status'] if container else 'not created'})")
        print(f"CloudXR logs: {self.state / 'home/.cloudxr/logs'}")

    def connect(self):
        address = os.environ.get("HEADSET_SERVER_IP", "").strip()
        try:
            parsed = ipaddress.IPv4Address(address)
            if parsed.is_loopback or parsed.is_unspecified or parsed.is_multicast:
                raise ValueError()
        except ValueError:
            raise DemoError("Set HEADSET_SERVER_IP in .env to this workstation's LAN IPv4 address.")
        print("Headset client: https://nvidia.github.io/IsaacCapture/client")
        print(f"Server IP: {address}")
        print(f"Accept the local certificate: https://{address}:48322/")
        print("In Arena: XR tab -> Start XR. In the headset client: Connect, then Play.")
        print("CloudXR network ports: 49100/tcp, 47998/udp, 48322/tcp (HTTPS proxy).")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    descriptions = {
        "init": "Create the ignored local .env without overwriting one",
        "doctor": "Optional: inspect host tools, Docker, GPU, display, and free storage",
        "prepare": "Clone pinned, unmodified Arena sources and submodules",
        "setup": "Prepare sources and build the Docker image",
        "build": "Build the pinned base Arena image for VR",
        "start": "Start the demo container without launching VR",
        "cloudxr": "Terminal 1: run CloudXR in the foreground",
        "teleop": "Terminal 2: run VR practice after CloudXR is ready",
        "record": "Terminal 2: save successful VR demonstrations to HDF5",
        "replay": "Replay a recorded HDF5 dataset without a headset",
        "connect": "Show headset connection instructions",
        "shell": "Open a shell in the demo container",
        "status": "Show container state and log locations",
        "stop": "Stop/remove only this demo container; keep runtime files",
    }
    for command, description in descriptions.items():
        child = subcommands.add_parser(command, help=description)
        if command in ("setup", "build"):
            child.add_argument("--no-cache", action="store_true", help="Rebuild all Docker layers")
        if command in ("record", "replay"):
            child.add_argument("--dataset-file", default=os.environ["RECORD_DATASET_FILE"],
                               help="Relative .hdf5 path under DEMO_STATE_DIR/datasets")
        if command == "record":
            child.add_argument("--num-demos", type=positive_int, default=os.environ["RECORD_NUM_DEMOS"],
                               help="Number of successful demonstrations to save (default: %(default)s)")
            child.add_argument("--num-success-steps", type=positive_int,
                               default=os.environ["RECORD_NUM_SUCCESS_STEPS"],
                               help="Consecutive successful steps before saving (default: %(default)s)")
    args = parser.parse_args()
    demo = Demo()
    if args.command != "init":
        demo.require_env()
    if args.command == "setup":
        with demo.lifecycle_lock():
            demo.prepare()
            demo.build(no_cache=args.no_cache)
    elif args.command == "build":
        with demo.lifecycle_lock():
            demo.build(no_cache=args.no_cache)
    elif args.command in ("cloudxr", "teleop", "shell"):
        demo.execute(args.command)
    elif args.command == "record":
        demo.record(args.dataset_file, args.num_demos, args.num_success_steps)
    elif args.command == "replay":
        demo.replay(args.dataset_file)
    elif args.command in ("prepare", "start", "stop"):
        with demo.lifecycle_lock():
            getattr(demo, args.command)()
    else:
        getattr(demo, args.command)()


if __name__ == "__main__":
    try:
        main()
    except (DemoError, OSError, ValueError, KeyError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
