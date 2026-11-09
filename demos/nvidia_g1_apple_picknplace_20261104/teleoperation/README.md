# Unitree G1 apple-to-plate: VR teleoperation and dataset recording

Control the simulated G1's arms and hands from an OpenXR headset in Isaac
Lab-Arena. The robot stands in front of a shelf; pick up the apple and put it on
the plate. Practise the task, record successful demonstrations to HDF5, and
replay your recordings. The separate
[evaluation folder](../evaluation/README.md) is reserved for the Thor workflow.

Everything maintained for this demo lives in this directory. The launchers create
an independent Arena checkout, Docker image, and container. They do not change
an existing `~/IsaacLab-Arena` installation.

## Requirements

See [requirements.txt](requirements.txt) for the host prerequisites, headset,
network, storage, and dependencies supplied by the Docker image. The host
launcher uses Python's standard library, so it needs no additional pip packages.

Install the Ubuntu host command-line tools:

```bash
sudo apt-get update
sudo apt-get install -y git git-lfs python3 x11-xserver-utils
git lfs install
```

Consult
[Isaac Sim requirements](https://docs.isaacsim.omniverse.nvidia.com/latest/installation/requirements.html)
and [NVIDIA Container Toolkit installation](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
for the GPU driver and Docker GPU runtime setup. Application dependencies are
installed inside Docker by `./demo.sh setup`.

## First setup after cloning

From the cloned `humanova` repository:

```bash
cd demos/nvidia_g1_apple_picknplace_20261104/teleoperation
./demo.sh init
```

Edit the generated `.env`:

- Set `HEADSET_SERVER_IP` to the workstation's LAN IPv4 address.
- Keep `PHYSICS_DEVICE=cpu` to match the original session.
- Set `RECORD_DATASET_FILE`, `RECORD_NUM_DEMOS`, and
  `RECORD_NUM_SUCCESS_STEPS` if you want to change the recording defaults.
- Check `DISPLAY` and `XAUTHORITY` against your logged-in desktop session.
  Their defaults inherit your current terminal's settings.
- Optionally move `DEMO_STATE_DIR` to an absolute path on a larger disk.
- If a local Arena clone already exists, optionally set
  `ARENA_CLONE_SOURCE="$HOME/IsaacLab-Arena"`. Only committed Git objects are
  copied from it; its uncommitted changes are left out.

`.env` is ignored by Git, created with user-only permissions, and never
overwritten by `init`. It is a Bash file sourced by the launcher; use normal
shell quoting for paths containing spaces. Each command reloads it.

Review the [Isaac Sim license](https://docs.isaacsim.omniverse.nvidia.com/latest/common/licenses.html).
The default `ACCEPT_EULA=Y` and `PRIVACY_CONSENT=Y` match NVIDIA's Arena
launcher. CloudXR separately prompts for its license on first use.

```bash
./demo.sh setup
```

`setup` clones Arena at the pinned commit, initializes its pinned submodules
over HTTPS, and builds the unmodified upstream Dockerfile. No GitHub SSH key
is needed. Build time and downloads can be substantial. The upstream build
includes Isaac Teleop, `ffmpeg`, and the simulation and teleoperation dependencies.

Run `setup` again to reuse the prepared checkout and matching image. To rebuild
every Docker layer, use `./demo.sh build --no-cache`. Sources with unexpected
edits are rejected instead of reset. Failed submodule downloads can be retried
with the same command. If setup stopped at another point and reports an
incomplete edited checkout, move that checkout aside or use a new state directory.

If an earlier local setup used modified NVIDIA sources, select an unused
runtime directory in `.env`, for example:

```bash
DEMO_STATE_DIR="${DEMO_DIR}/.local/upstream"
DEMO_IMAGE="humanova/g1-apple-vr:arena-8b4a3a47"
```

Keep the previous runtime directory if it contains recordings. Run
`./demo.sh stop` to close the old container, then `./demo.sh setup` to prepare
the clean sources and image.

## Headset networking

Use the workstation's LAN address, not localhost, a Docker bridge address, or
the Thor address. Prefer a wired workstation and a headset on strong Wi-Fi.
Disable wireless client isolation if it prevents the devices communicating.

The tutorial's browser streaming path uses `49100/tcp` (signaling),
`47998/udp` (media), and `48322/tcp` (HTTPS proxy). If UFW is active, allow
these ports from your headset or LAN. For example, replace the subnet below
with your actual LAN:

```bash
sudo ufw allow from 192.168.1.0/24 to any port 49100 proto tcp
sudo ufw allow from 192.168.1.0/24 to any port 47998 proto udp
sudo ufw allow from 192.168.1.0/24 to any port 48322 proto tcp
```

The launcher uses host networking. It does not change firewall rules or
terminate processes occupying these ports.

## Start a VR practice session

In **terminal 1**, from this directory:

```bash
./demo.sh cloudxr
```

This starts the dedicated Arena container and launches CloudXR as the desktop
user. Accept the CloudXR license when prompted. Wait for the runtime and WSS
proxy to report that they are running. Keep this terminal open.

In **terminal 2**, from the same directory:

```bash
./demo.sh teleop
```

This attaches to the same container, checks that CloudXR is alive, loads the
generated CloudXR environment, and launches the apple-to-plate scene. It uses
the explicit Isaac Sim Python interpreter, so interactive Python aliases are
not required. The command refuses to start before CloudXR is ready.

Once Arena opens:

1. Open its **XR** tab and start the XR session. Use the system OpenXR runtime
   if a runtime selector is shown.
2. In the headset browser, open
   [the Isaac Teleop client](https://nvidia.github.io/IsaacCapture/client).
3. Enter the workstation's LAN IP in **Server IP**.
4. Follow the certificate link at `https://<workstation-ip>:48322/`, accept
   the local certificate, and return to the client page.
5. Select **Connect**, put both controllers in their starting poses, then
   press **Play** in the virtual control panel.
6. Move the controllers to position the arms; use the grip/trigger controls
   to manipulate the hands. Pick up the apple and release it over the plate.

`./demo.sh connect` prints the URLs using your local IP setting.

The scene uses NVIDIA's original teleoperation controls. Pause with Stop
before resetting or repositioning the controllers, then press Play to continue.

To display the robot's head-camera view as well, set `ENABLE_CAMERAS=1` in
`.env`, stop the container, and relaunch. This costs additional rendering
work. If XR feels slow, reduce its render resolution in the XR settings.

## Record a dataset

Keep `./demo.sh cloudxr` running in terminal 1. Exit the practice application
in terminal 2, then run:

```bash
./demo.sh record
```

The command follows [NVIDIA's recording workflow](https://docs.nvidia.com/learning/physical-ai/gr00t-e2e-workflow/latest/simulation-workflow/sim-teleop-and-wbc.html#record-with-the-headset-device):
it enables cameras, saves successful episodes, and uses
`--disable_full_sim_buffer_reset`. Defaults are 20 demonstrations and 10
consecutive successful steps before saving. Recording enables cameras even
when practice uses `ENABLE_CAMERAS=0`.

Change the defaults in `.env`:

```bash
RECORD_DATASET_FILE=isaaclab_arena/static_apple_tutorial/arena_g1_static_apple_dataset_recorded.hdf5
RECORD_NUM_DEMOS=20
RECORD_NUM_SUCCESS_STEPS=10
```

Or select a separate session file and count for one run:

```bash
./demo.sh record \
  --dataset-file isaaclab_arena/static_apple_tutorial/session_b.hdf5 \
  --num-demos 20 \
  --num-success-steps 10
```

`--dataset-file` is relative to `DEMO_STATE_DIR/datasets`. The default host
output is:

```text
.local/datasets/isaaclab_arena/static_apple_tutorial/arena_g1_static_apple_dataset_recorded.hdf5
```

Inside Docker, this is under `/datasets/isaaclab_arena/static_apple_tutorial/`.
Recordings stay outside Git in the ignored runtime directory. Existing files
are protected: use a new filename for each session. The recorder creates new
files rather than appending to previous sessions.

In the recording app, start XR, connect the headset again, and press Play.
After placing the apple, let the success sequence finish and watch the saved
demonstration count. The recorder saves automatically and exits after the
requested count. Use Reset for an unsuccessful attempt; pause with Stop when
repositioning the controllers, then press Play to continue. On exit, an
unfinished attempt is not a saved successful demonstration.

For a second view of what the dataset captures, open **Window > Viewport 2**
and select **RobotHeadCam**. Keep grasps and placements visible in this view.
Recording uses the same `PHYSICS_DEVICE` as practice; keep that setting with
the dataset for later replay and training.

## Replay a dataset

After recording finishes, replay the default dataset:

```bash
./demo.sh replay
```

For another session:

```bash
./demo.sh replay --dataset-file isaaclab_arena/static_apple_tutorial/session_b.hdf5
```

Replay uses the current `PHYSICS_DEVICE` and needs no headset or CloudXR
connection. It runs saved actions through the simulation; trajectories may
differ from the original session. Use the original capture quality as well
when judging the demonstrations.

## Stop, restart, and check the setup

Stop XR in the UI, then press Ctrl+C in terminal 2 and terminal 1. Remove the
idle demo container with:

```bash
./demo.sh stop
```

The checkout, caches, and CloudXR license/certificate files are preserved.
Next time, run `cloudxr` and then `teleop` or `record`; setup does not need repeating.
After changing container settings in `.env`, stop before relaunching.

Other commands:

```bash
./demo.sh status       # container state and CloudXR log location
./demo.sh shell        # interactive shell in this demo's container
./demo.sh --help
```

## Files, versions, and local changes

| Location | Contents |
|---|---|
| `config.env` | Shared source, package, base-image, and task settings |
| `requirements.txt` | Host prerequisites and container dependency inventory |
| `.env` | Ignored machine-specific configuration |
| `scripts/` | Host lifecycle and in-container launchers |
| `.local/IsaacLab-Arena/` | Managed source checkout and its submodules |
| `.local/home/.cloudxr/` | Runtime files, license marker, certificates, logs |
| `.local/cache/` | Persistent application cache |
| `.local/datasets/` | Recorded HDF5 sessions, mounted at `/datasets` |
| `.local/source.json` | Source identity used for repeat-setup checks |
| `.local/build.json` | Build timestamp, input versions, and resulting image ID |
| `.local/session.json` | Resolved task and container settings |

These paths follow `DEMO_STATE_DIR` when it is changed. Docker stores its image
layers in its own data directory. The isolated source checkout and dedicated
image/container names avoid using the original installation.

The baseline is Arena commit
`8b4a3a47fc53de23e8205089d71109a2e2348acd`, its recursive submodule revisions,
and Isaac Sim base `6.0.0-dev2` locked to its image digest. Isaac Teleop follows
the upstream Dockerfile's `isaacteleop~=1.1.0` requirement. The downloaded
NVIDIA sources and Dockerfile are used without local modifications. Image
inputs and source integrity are checked before reuse. Apt packages and other
upstream Python dependencies still resolve at build time, so rebuilding later
is not guaranteed to produce an identical image. Preserve `build.json` and the
built image for an exact runtime snapshot.

Arena files retain their Apache-2.0 notices; see the
[upstream license](https://github.com/isaac-sim/IsaacLab-Arena/blob/8b4a3a47fc53de23e8205089d71109a2e2348acd/LICENSE.md).

## Troubleshooting

| Symptom | Action |
|---|---|
| Docker permission denied | Check Docker group/context and log into the desktop again after changing groups. Run as your desktop user. |
| Container cannot see GPU | Check `nvidia-smi` and NVIDIA Container Toolkit configuration, then inspect Docker's error. |
| Window cannot open | Check `DISPLAY`, `XAUTHORITY`, and XWayland. Run from the local desktop. The launcher grants X11 access only to your current local user. |
| CloudXR license exits | Restart `cloudxr` in an interactive terminal and answer its license prompt. |
| CloudXR reports a port in use | Stop the older CloudXR session normally. Inspect `ss -lntup`; do not kill an unidentified process. |
| `teleop` or `record` says CloudXR is not ready | Wait for terminal 1 to print that the runtime and WSS proxy are running, then retry. |
| Recording file already exists | Select a new `--dataset-file` for the next session. |
| Dataset is missing for replay | Check `--dataset-file` relative to `DEMO_STATE_DIR/datasets`. |
| A second session exits with code 75 | This demo already has that CloudXR or teleoperation session running. |
| Headset cannot connect | Recheck LAN IP, local certificate acceptance, firewall, and Wi-Fi client isolation. |
| Controls disappear | Wear the headset before starting XR; move the virtual control panel into view. |
| Robot jumps after reset | Pause with Stop before resetting or moving the controllers back to their initial poses; press Play when ready. |
| Apple falls through on first load | Allow asset loading to finish, then restart once to use the warmed asset/collision cache. |
| Container name belongs to another setup | Choose a unique `DEMO_CONTAINER` in `.env`. |
| Managed source or versions changed | Preserve your work and choose a fresh `DEMO_STATE_DIR`; setup never resets edited sources. |

## References

- [Original NVIDIA simulation setup](https://docs.nvidia.com/learning/physical-ai/gr00t-e2e-workflow/latest/simulation-workflow/sim-setup-isaac-lab-arena.html)
- [NVIDIA VR teleoperation workflow](https://docs.nvidia.com/learning/physical-ai/gr00t-e2e-workflow/latest/simulation-workflow/sim-teleop-and-wbc.html)
- [Isaac Teleop](https://nvidia.github.io/IsaacTeleop/)
- Original local notebook: `/home/vaeinoe/Instructions/gr00t_server_evaluation.ipynb`
  (reference only; not needed after cloning).
