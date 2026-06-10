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

```bash
git clone https://github.com/Miko997/metriplane.git
cd metriplane
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m metriplane.cli doctor
./tools/mp.sh deterministic-replay
```

Optional Docker path:

```bash
./tools/docker_demo_up.sh
curl http://localhost:8000/health
./tools/docker_clean.sh
```

## Observed result

* Did deterministic replay pass?
* Were there installation issues?
* Did health check pass, if Docker was used?
* Notes:

## Relevance statement

In 2-5 sentences, describe whether the artifact appears usable, reproducible, or relevant to robotics, automation, digital twins, physical observability, or research-software evaluation.
