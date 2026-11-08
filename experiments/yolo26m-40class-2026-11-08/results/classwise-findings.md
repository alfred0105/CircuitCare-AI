# YOLO26m label-level findings

Metrics are from the held-out 5% test sample (116 images). “AP” below is class mAP50–95. Low scores on rare classes are especially uncertain.

Best overall completed condition by test mAP50–95: **Extra: rare-class oversampling (+211 repeats)** (0.253).

## Labels with low AP or missed detections

| Label | P | R | AP50 | AP50–95 | Test images | Test boxes |
|---|---:|---:|---:|---:|---:|---:|
| battery | 0.684 | 0.057 | 0.194 | 0.099 | 17 | 401 |
| transistor | 1.000 | 0.020 | 0.139 | 0.067 | 25 | 98 |
| heatsink | 1.000 | 0.000 | 0.124 | 0.062 | 2 | 2 |
| resistor | 0.763 | 0.051 | 0.109 | 0.044 | 57 | 1362 |
| oscillator | 1.000 | 0.000 | 0.048 | 0.034 | 16 | 50 |
| relay | 0.285 | 0.091 | 0.064 | 0.025 | 4 | 11 |
| inductor | 0.000 | 0.000 | 0.018 | 0.013 | 14 | 46 |
| fuse | 1.000 | 0.000 | 0.022 | 0.010 | 7 | 53 |
| text_noncomponent | 0.000 | 0.000 | 0.025 | 0.007 | 3 | 1376 |
| speaker | 0.000 | 0.000 | 0.008 | 0.006 | 1 | 1 |
| MOV | 1.000 | 0.000 | 0.007 | 0.001 | 2 | 2 |
| jumper | 1.000 | 0.000 | 0.005 | 0.001 | 7 | 219 |
| ferrite_bead | 1.000 | 0.000 | 0.000 | 0.000 | 5 | 31 |
| emi_filter | 1.000 | 0.000 | 0.000 | 0.000 | 2 | 12 |
| solder_pad | 1.000 | 0.000 | 0.000 | 0.000 | 8 | 71 |
| pin | 0.000 | 0.000 | 0.000 | 0.000 | 1 | 1 |
| test_point | 1.000 | 0.000 | 0.000 | 0.000 | 6 | 37 |

## Change from baseline 640

Largest class-level AP changes by condition; negative values identify labels whose AP fell versus baseline.

### 960 baseline

| Largest drops | ΔAP | Base → condition | Support images / boxes |
|---|---:|---:|---:|
| exc_solder | -0.348 | 0.796 → 0.448 | 1 / 1 |
| touchpad | -0.204 | 0.204 → 0.000 | 1 / 4 |
| potentiometer | -0.191 | 0.372 → 0.182 | 29 / 34 |
| LDR | -0.143 | 0.162 → 0.019 | 2 / 2 |
| switch | -0.097 | 0.199 → 0.101 | 27 / 116 |

| Largest gains | ΔAP | Base → condition | Support images / boxes |
|---|---:|---:|---:|
| good | +0.746 | 0.149 → 0.895 | 1 / 1 |
| transformer | +0.096 | 0.267 → 0.364 | 10 / 16 |
| display | +0.043 | 0.050 → 0.093 | 9 / 46 |
| diode | +0.031 | 0.133 → 0.165 | 31 / 100 |
| board_module | +0.005 | 0.231 → 0.236 | 2 / 2 |

### 1280 baseline

| Largest drops | ΔAP | Base → condition | Support images / boxes |
|---|---:|---:|---:|
| no_good | -0.298 | 0.895 → 0.597 | 1 / 1 |
| thermistor | -0.262 | 0.265 → 0.003 | 1 / 1 |
| board_module | -0.231 | 0.231 → 0.000 | 2 / 2 |
| potentiometer | -0.222 | 0.372 → 0.150 | 29 / 34 |
| touchpad | -0.204 | 0.204 → 0.000 | 1 / 4 |

| Largest gains | ΔAP | Base → condition | Support images / boxes |
|---|---:|---:|---:|
| good | +0.647 | 0.149 → 0.796 | 1 / 1 |
| transformer | +0.031 | 0.267 → 0.298 | 10 / 16 |
| fuse | +0.009 | 0.014 → 0.023 | 7 / 53 |
| ferrite_bead | +0.000 | 0.000 → 0.000 | 5 / 31 |
| jumper | +0.000 | 0.000 → 0.000 | 7 / 219 |

### cls_pw=0.5

| Largest drops | ΔAP | Base → condition | Support images / boxes |
|---|---:|---:|---:|
| IC | -0.105 | 0.307 → 0.202 | 56 / 248 |
| potentiometer | -0.059 | 0.372 → 0.314 | 29 / 34 |
| switch | -0.048 | 0.199 → 0.150 | 27 / 116 |
| LED | -0.044 | 0.126 → 0.081 | 37 / 167 |
| connector | -0.036 | 0.101 → 0.065 | 23 / 313 |

| Largest gains | ΔAP | Base → condition | Support images / boxes |
|---|---:|---:|---:|
| thermistor | +0.630 | 0.265 → 0.895 | 1 / 1 |
| LDR | +0.584 | 0.162 → 0.746 | 2 / 2 |
| variable_capacitor | +0.501 | 0.033 → 0.534 | 1 / 2 |
| solder_joint | +0.479 | 0.000 → 0.479 | 1 / 29 |
| poor_solder | +0.423 | 0.000 → 0.423 | 1 / 1 |

### PCB augmentation

| Largest drops | ΔAP | Base → condition | Support images / boxes |
|---|---:|---:|---:|
| exc_solder | -0.655 | 0.796 → 0.141 | 1 / 1 |
| board_module | -0.231 | 0.231 → 0.000 | 2 / 2 |
| thermistor | -0.216 | 0.265 → 0.050 | 1 / 1 |
| touchpad | -0.204 | 0.204 → 0.000 | 1 / 4 |
| no_good | -0.199 | 0.895 → 0.697 | 1 / 1 |

| Largest gains | ΔAP | Base → condition | Support images / boxes |
|---|---:|---:|---:|
| good | +0.249 | 0.149 → 0.398 | 1 / 1 |
| transformer | +0.058 | 0.267 → 0.325 | 10 / 16 |
| heatsink | +0.022 | 0.000 → 0.022 | 2 / 2 |
| solder_joint | +0.004 | 0.000 → 0.004 | 1 / 29 |
| text_noncomponent | +0.000 | 0.004 → 0.004 | 3 / 1376 |

### Extra: multi-scale ±25%

| Largest drops | ΔAP | Base → condition | Support images / boxes |
|---|---:|---:|---:|
| exc_solder | -0.708 | 0.796 → 0.088 | 1 / 1 |
| touchpad | -0.204 | 0.204 → 0.000 | 1 / 4 |
| potentiometer | -0.136 | 0.372 → 0.236 | 29 / 34 |
| IC | -0.132 | 0.307 → 0.175 | 56 / 248 |
| LDR | -0.131 | 0.162 → 0.031 | 2 / 2 |

| Largest gains | ΔAP | Base → condition | Support images / boxes |
|---|---:|---:|---:|
| no_good | +0.099 | 0.895 → 0.995 | 1 / 1 |
| inductor | +0.007 | 0.033 → 0.040 | 14 / 46 |
| photodiode | +0.001 | 0.000 → 0.001 | 1 / 1 |
| ferrite_bead | +0.000 | 0.000 → 0.000 | 5 / 31 |
| jumper | +0.000 | 0.000 → 0.000 | 7 / 219 |

### Extra: rare-class oversampling (+211 repeats)

| Largest drops | ΔAP | Base → condition | Support images / boxes |
|---|---:|---:|---:|
| oscillator | -0.022 | 0.055 → 0.034 | 16 / 50 |
| inductor | -0.019 | 0.033 → 0.013 | 14 / 46 |
| MOV | -0.015 | 0.017 → 0.001 | 2 / 2 |
| switch | -0.011 | 0.199 → 0.188 | 27 / 116 |
| IC | -0.011 | 0.307 → 0.296 | 56 / 248 |

| Largest gains | ΔAP | Base → condition | Support images / boxes |
|---|---:|---:|---:|
| solder_joint | +0.748 | 0.000 → 0.748 | 1 / 29 |
| LDR | +0.683 | 0.162 → 0.846 | 2 / 2 |
| thermistor | +0.630 | 0.265 → 0.895 | 1 / 1 |
| board_module | +0.565 | 0.231 → 0.796 | 2 / 2 |
| variable_capacitor | +0.514 | 0.033 → 0.547 | 1 / 2 |

### 640 + test-time augmentation

| Largest drops | ΔAP | Base → condition | Support images / boxes |
|---|---:|---:|---:|
| no_good | -0.448 | 0.895 → 0.448 | 1 / 1 |
| exc_solder | -0.100 | 0.796 → 0.697 | 1 / 1 |
| LDR | -0.037 | 0.162 → 0.125 | 2 / 2 |
| good | -0.021 | 0.149 → 0.128 | 1 / 1 |
| switch | -0.013 | 0.199 → 0.186 | 27 / 116 |

| Largest gains | ΔAP | Base → condition | Support images / boxes |
|---|---:|---:|---:|
| thermistor | +0.531 | 0.265 → 0.796 | 1 / 1 |
| board_module | +0.375 | 0.231 → 0.605 | 2 / 2 |
| poor_solder | +0.318 | 0.000 → 0.318 | 1 / 1 |
| touchpad | +0.121 | 0.204 → 0.325 | 1 / 4 |
| variable_capacitor | +0.101 | 0.033 → 0.134 | 1 / 2 |

### 640 + tiled inference

| Largest drops | ΔAP | Base → condition | Support images / boxes |
|---|---:|---:|---:|
| no_good | -0.895 | 0.895 → 0.000 | 1 / 1 |
| exc_solder | -0.796 | 0.796 → 0.000 | 1 / 1 |
| board_module | -0.231 | 0.231 → 0.000 | 2 / 2 |
| good | -0.149 | 0.149 → 0.000 | 1 / 1 |
| LDR | -0.078 | 0.162 → 0.084 | 2 / 2 |

| Largest gains | ΔAP | Base → condition | Support images / boxes |
|---|---:|---:|---:|
| resistor | +0.026 | 0.039 → 0.065 | 57 / 1362 |
| touchpad | +0.014 | 0.204 → 0.218 | 1 / 4 |
| diode | +0.009 | 0.133 → 0.143 | 31 / 100 |
| relay | +0.007 | 0.010 → 0.017 | 4 / 11 |
| transformer | +0.007 | 0.267 → 0.275 | 10 / 16 |

## Test support and interpretation

- `solder_joint` has only one image in this test subset, matching the one test image in the full source; its score cannot support a reliable conclusion.
- Classes with fewer than 10 test images are listed with their support counts; treat their per-class scores as exploratory.
- No predictions for a class appear as zero precision/recall/AP in the metric export; missing class metrics are marked with an em dash.
