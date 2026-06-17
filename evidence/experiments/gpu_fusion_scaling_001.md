# GPU Fusion Scaling Benchmark

- host: Linux-6.17.0-35-generic-x86_64-with-glibc2.39
- python: 3.12.3
- processor: x86_64

## Results (median latency per fuse call)

| backend | n_objects | obs | method | p50_ms | p95_ms | throughput_obs_s | rmse_vs_cpu |
|---|---|---|---|---|---|---|---|
| cpu_numpy | 1 | 2 | avg | 0.006112 | 0.006763 | 320704.7 | - |
| gpu_cupy | 1 | 2 | avg | 0.354205 | 0.464255 | 5445.69 | 0.0 |
| cpu_numpy | 1 | 2 | weighted | 0.006382 | 0.007494 | 300431.12 | - |
| gpu_cupy | 1 | 2 | weighted | 0.35118 | 0.364005 | 5643.69 | 0.0 |
| cpu_numpy | 1 | 4 | avg | 0.007945 | 0.008326 | 500321.04 | - |
| gpu_cupy | 1 | 4 | avg | 0.353634 | 0.370577 | 11275.75 | 0.0 |
| cpu_numpy | 1 | 4 | weighted | 0.008326 | 0.008647 | 477473.21 | - |
| gpu_cupy | 1 | 4 | weighted | 0.348986 | 0.363173 | 11390.24 | 0.0 |
| cpu_numpy | 10 | 2 | avg | 0.025779 | 0.02652 | 772080.54 | - |
| gpu_cupy | 10 | 2 | avg | 0.384393 | 0.597921 | 48064.19 | 0.0 |
| cpu_numpy | 10 | 2 | weighted | 0.027873 | 0.028665 | 710350.88 | - |
| gpu_cupy | 10 | 2 | weighted | 0.376708 | 0.405964 | 52399.2 | 0.0 |
| cpu_numpy | 10 | 4 | avg | 0.044455 | 0.045677 | 895316.6 | - |
| gpu_cupy | 10 | 4 | avg | 0.389493 | 0.402638 | 102138.19 | 0.0 |
| cpu_numpy | 10 | 4 | weighted | 0.047792 | 0.051088 | 830052.9 | - |
| gpu_cupy | 10 | 4 | weighted | 0.399201 | 0.508319 | 96150.04 | 0.0 |
| cpu_numpy | 100 | 2 | avg | 0.228976 | 0.247732 | 868843.57 | - |
| gpu_cupy | 100 | 2 | avg | 0.587992 | 0.653947 | 335429.51 | 0.0 |
| cpu_numpy | 100 | 2 | weighted | 0.239136 | 0.245999 | 833734.34 | - |
| gpu_cupy | 100 | 2 | weighted | 0.607699 | 0.718861 | 321522.04 | 0.0 |
| cpu_numpy | 100 | 4 | avg | 0.401405 | 0.406435 | 994464.15 | - |
| gpu_cupy | 100 | 4 | avg | 0.748327 | 0.779496 | 535168.75 | 0.0 |
| cpu_numpy | 100 | 4 | weighted | 0.407628 | 0.415732 | 982655.4 | - |
| gpu_cupy | 100 | 4 | weighted | 0.735864 | 0.932087 | 531182.35 | 0.0 |
| cpu_numpy | 1000 | 2 | avg | 1.956772 | 2.14459 | 1008333.95 | - |
| gpu_cupy | 1000 | 2 | avg | 2.370872 | 2.413422 | 842491.3 | 0.0 |
| cpu_numpy | 1000 | 2 | weighted | 2.216738 | 2.300878 | 898694.23 | - |
| gpu_cupy | 1000 | 2 | weighted | 2.563459 | 2.625267 | 779464.79 | 0.0 |
| cpu_numpy | 1000 | 4 | avg | 3.710266 | 3.739422 | 1077856.69 | - |
| gpu_cupy | 1000 | 4 | avg | 3.9642 | 4.153522 | 1000769.3 | 0.0 |
| cpu_numpy | 1000 | 4 | weighted | 4.047329 | 4.132752 | 986879.79 | - |
| gpu_cupy | 1000 | 4 | weighted | 4.382258 | 4.442853 | 913513.35 | 0.0 |
| cpu_numpy | 10000 | 2 | avg | 20.616229 | 21.128025 | 970524.65 | - |
| gpu_cupy | 10000 | 2 | avg | 21.159435 | 21.819213 | 941310.45 | 0.0 |
| cpu_numpy | 10000 | 2 | weighted | 22.731152 | 23.506471 | 876064.16 | - |
| gpu_cupy | 10000 | 2 | weighted | 23.182894 | 24.571051 | 856865.38 | 0.0 |
| cpu_numpy | 10000 | 4 | avg | 38.714967 | 39.68677 | 1035673.18 | - |
| gpu_cupy | 10000 | 4 | avg | 39.012053 | 40.118634 | 1020986.82 | 0.0 |
| cpu_numpy | 10000 | 4 | weighted | 42.641475 | 44.9198 | 933426.99 | - |
| gpu_cupy | 10000 | 4 | weighted | 43.151548 | 44.773822 | 927065.21 | 0.0 |
| cpu_numpy | 100000 | 2 | avg | 246.919971 | 251.781484 | 810062.37 | - |
| gpu_cupy | 100000 | 2 | avg | 256.976371 | 284.051479 | 766705.56 | 0.0 |
| cpu_numpy | 100000 | 2 | weighted | 288.947366 | 294.678596 | 692706.01 | - |
| gpu_cupy | 100000 | 2 | weighted | 287.159336 | 293.408304 | 696597.34 | 0.0 |
| cpu_numpy | 100000 | 4 | avg | 446.225495 | 452.928638 | 897651.1 | - |
| gpu_cupy | 100000 | 4 | avg | 448.698261 | 456.380071 | 893205.84 | 0.0 |
| cpu_numpy | 100000 | 4 | weighted | 524.282634 | 529.136071 | 765889.29 | - |
| gpu_cupy | 100000 | 4 | weighted | 523.491245 | 533.406826 | 764818.41 | 0.0 |

## Break-even analysis

GPU (`gpu_cupy`) first matches or beats CPU at n_objects = 100000.

## Limitations

- Synthetic observations; real workloads differ.
- Timing includes host-device transfer for GPU (intentional, honest).
- Single-process, single-stream measurement.
