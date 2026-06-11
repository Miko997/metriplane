# External Reproduction Note Template

Please complete this after running the MetriPlane v0.1.4 reviewer path.

## Person

- Name:
- Role/title:
- Organization:
- Email or public profile:
- Permission to cite name in immigration/evidence packet: yes/no
- Permission to acknowledge in publication or repository: yes/no

## Environment

- Date:
- Operating system:
- Python version:
- Docker version, if used:
- MetriPlane release or commit:

## Commands run

Linux/macOS:

```bash
git clone https://github.com/Miko997/metriplane.git
cd metriplane
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m metriplane.cli doctor
./tools/mp.sh deterministic-replay
```

Windows Git Bash:

```bash
git clone https://github.com/Miko997/metriplane.git
cd metriplane
python -m venv .venv
source .venv/Scripts/activate
pip install -e .
python -m metriplane.cli doctor
./tools/mp.sh deterministic-replay
```

Use Git Bash or WSL on Windows, not plain Command Prompt, because `tools/mp.sh` is a Bash script.

Optional Docker path:

```bash
./tools/docker_demo_up.sh
curl http://localhost:8000/health
./tools/docker_clean.sh
```

## Observed result

* Did deterministic replay pass?
* Expected camera-free result: doctor 0 failures; replay `pass=true`; `mean_pos_diff_cm=0.0`; `max_pos_diff_cm=0.0`; `event_mismatch_count=0`.
* `No /dev/video* devices found` is acceptable as a warning for camera-free replay.
* Were there installation issues?
* Did health check pass, if Docker was used?
* Notes:

## Relevance statement

In 2-5 sentences, describe whether the artifact appears usable, reproducible, or relevant to robotics, automation, digital twins, physical observability, or research-software evaluation.
