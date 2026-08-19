# Airport Occupancy V3.1 — Seasonal EnergyPlus results

Status: `PASS_78_OF_78_DESIGN_SIZING_SENSITIVITY`

All 52 registered EnergyPlus processes completed and all 78/78 winter, summer, and shoulder period identities passed return-code, Severe, Fatal, and output-period gates. The process warning range was 870–871; total recorded wall time was 67.8 minutes. No failed seed was replaced.

The occupancy schedules use `BEM_REFERENCE_NORMALIZED` and preserve public/staff person-hours. However, the applySizingValues completeness gate failed, so these results are design/sizing sensitivity from a partially fixed reference—not a valid fixed installed-HVAC operational comparison.

## SOURCE_STATIC versus dynamic baseline

### Winter

| Metric | Source static | Dynamic P50 | n | Mean difference | Median | Min…Max | P10…P90 | Median % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Facility electricity | 9,831.207 | 9,497.867 | 5 | -333.594 | -333.340 | -335.025…-332.147 | -334.777…-332.509 | -3.39% |
| Fan electricity | 7,571.905 | 7,488.771 | 5 | -83.791 | -83.134 | -85.213…-82.659 | -85.114…-82.788 | -1.10% |
| Pump electricity | 1,595.394 | 1,345.582 | 5 | -249.803 | -249.811 | -250.360…-249.439 | -250.183…-249.459 | -15.66% |
| District cooling boundary | 180.234 | 187.177 | 5 | 6.963 | 6.943 | 6.499…7.519 | 6.589…7.363 | 3.85% |
| District heating boundary | 413,911.344 | 364,098.760 | 5 | -49,806.286 | -49,812.584 | -49,840.371…-49,758.189 | -49,830.727…-49,776.524 | -12.03% |
| Peak HVAC electricity | 381.987 | 379.075 | 5 | -2.890 | -2.911 | -3.204…-2.398 | -3.141…-2.595 | -0.76% |
| Cooling occupied unmet hours | 0.000 | 0.000 | 5 | 0.000 | 0.000 | 0.000…0.000 | 0.000…0.000 | — |
| Heating occupied unmet hours | 0.000 | 0.000 | 5 | 0.050 | 0.000 | 0.000…0.250 | 0.000…0.150 | — |

### Summer

| Metric | Source static | Dynamic P50 | n | Mean difference | Median | Min…Max | P10…P90 | Median % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Facility electricity | 167,547.388 | 166,839.476 | 5 | -719.954 | -707.912 | -758.889…-701.720 | -746.018…-702.848 | -0.42% |
| Fan electricity | 14,233.213 | 13,679.591 | 5 | -564.538 | -553.622 | -600.395…-548.068 | -588.399…-548.920 | -3.89% |
| Pump electricity | 4,743.675 | 4,589.333 | 5 | -155.417 | -154.342 | -158.494…-153.652 | -157.619…-153.907 | -3.25% |
| District cooling boundary | 569,694.445 | 549,733.400 | 5 | -20,019.661 | -19,961.045 | -20,202.859…-19,873.835 | -20,168.445…-19,901.797 | -3.50% |
| District heating boundary | 805.495 | 1,008.178 | 5 | 197.229 | 202.683 | 185.360…206.635 | 185.906…205.879 | 25.16% |
| Peak HVAC electricity | 1,155.819 | 1,130.902 | 5 | -25.024 | -24.917 | -32.688…-17.340 | -30.017…-20.070 | -2.16% |
| Cooling occupied unmet hours | 0.000 | 15.000 | 5 | 15.200 | 15.000 | 14.000…16.750 | 14.300…16.250 | — |
| Heating occupied unmet hours | 0.000 | 0.000 | 5 | 0.000 | 0.000 | 0.000…0.000 | 0.000…0.000 | — |

### Shoulder

| Metric | Source static | Dynamic P50 | n | Mean difference | Median | Min…Max | P10…P90 | Median % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Facility electricity | 111,193.673 | 111,312.915 | 5 | 117.286 | 119.242 | 102.111…132.249 | 105.296…128.450 | 0.11% |
| Fan electricity | 8,716.711 | 8,818.073 | 5 | 99.749 | 101.362 | 85.959…113.924 | 88.595…110.335 | 1.16% |
| Pump electricity | 539.317 | 557.118 | 5 | 17.536 | 17.800 | 16.152…18.324 | 16.702…18.147 | 3.30% |
| District cooling boundary | 59,466.466 | 60,358.929 | 5 | 872.256 | 892.463 | 735.012…999.333 | 772.933…961.462 | 1.50% |
| District heating boundary | 32,044.124 | 36,250.316 | 5 | 4,129.571 | 4,206.192 | 3,864.936…4,301.106 | 3,940.152…4,269.721 | 13.13% |
| Peak HVAC electricity | 461.050 | 484.622 | 5 | 24.353 | 23.571 | 18.898…31.020 | 19.520…29.742 | 5.11% |
| Cooling occupied unmet hours | 0.000 | 3.500 | 5 | 3.850 | 3.500 | 3.000…5.000 | 3.200…4.700 | — |
| Heating occupied unmet hours | 0.000 | 0.000 | 5 | 0.000 | 0.000 | 0.000…0.000 | 0.000…0.000 | — |

## Timing-bank effects versus dynamic spread

### Winter

| Scenario | Metric | n | Mean difference | Median | Min…Max | P10…P90 | Median % |
|---|---|---:|---:|---:|---:|---:|---:|
| MORNING_BANK | Facility electricity | 5 | 118.842 | 115.030 | 112.331…127.871 | 113.041…126.672 | 1.21% |
| MORNING_BANK | Fan electricity | 5 | 55.910 | 53.411 | 47.730…66.019 | 49.254…63.952 | 0.71% |
| MORNING_BANK | Pump electricity | 5 | 62.932 | 62.566 | 61.619…64.601 | 61.712…64.370 | 4.65% |
| MORNING_BANK | District cooling boundary | 5 | 0.760 | 0.775 | 0.665…0.800 | 0.703…0.800 | 0.41% |
| MORNING_BANK | District heating boundary | 5 | 8,028.246 | 8,083.191 | 7,771.356…8,110.752 | 7,889.920…8,109.717 | 2.22% |
| MORNING_BANK | Peak HVAC electricity | 5 | 2.488 | 2.496 | 1.989…2.926 | 2.157…2.803 | 0.66% |
| MORNING_BANK | Cooling occupied unmet hours | 5 | 2.550 | 2.750 | 2.250…2.750 | 2.250…2.750 | — |
| MORNING_BANK | Heating occupied unmet hours | 5 | 0.550 | 0.500 | 0.250…1.000 | 0.350…0.800 | 200.00% |
| MIDDAY_BANK | Facility electricity | 5 | 119.405 | 119.167 | 108.473…129.490 | 110.452…128.284 | 1.25% |
| MIDDAY_BANK | Fan electricity | 5 | 55.325 | 55.446 | 43.930…66.356 | 46.261…64.266 | 0.74% |
| MIDDAY_BANK | Pump electricity | 5 | 64.081 | 63.721 | 63.134…65.343 | 63.346…65.023 | 4.74% |
| MIDDAY_BANK | District cooling boundary | 5 | 0.762 | 0.782 | 0.665…0.800 | 0.708…0.795 | 0.42% |
| MIDDAY_BANK | District heating boundary | 5 | 8,117.449 | 8,125.545 | 7,925.570…8,240.567 | 7,981.483…8,236.424 | 2.23% |
| MIDDAY_BANK | Peak HVAC electricity | 5 | 2.439 | 2.461 | 1.938…2.857 | 2.107…2.745 | 0.65% |
| MIDDAY_BANK | Cooling occupied unmet hours | 5 | 2.500 | 2.500 | 2.000…2.750 | 2.200…2.750 | — |
| MIDDAY_BANK | Heating occupied unmet hours | 5 | 0.300 | 0.250 | 0.000…0.750 | 0.100…0.550 | 100.00% |
| EVENING_BANK | Facility electricity | 5 | 118.096 | 115.236 | 106.231…129.656 | 108.503…128.771 | 1.21% |
| EVENING_BANK | Fan electricity | 5 | 54.909 | 53.047 | 42.970…67.647 | 45.248…65.475 | 0.71% |
| EVENING_BANK | Pump electricity | 5 | 63.186 | 63.247 | 62.010…65.226 | 62.081…64.440 | 4.70% |
| EVENING_BANK | District cooling boundary | 5 | 0.773 | 0.784 | 0.639…0.872 | 0.695…0.840 | 0.42% |
| EVENING_BANK | District heating boundary | 5 | 8,021.491 | 8,052.897 | 7,735.933…8,267.573 | 7,804.144…8,218.381 | 2.21% |
| EVENING_BANK | Peak HVAC electricity | 5 | 2.186 | 2.131 | 1.746…2.670 | 1.833…2.570 | 0.56% |
| EVENING_BANK | Cooling occupied unmet hours | 5 | 2.400 | 2.250 | 1.750…3.000 | 1.950…2.900 | — |
| EVENING_BANK | Heating occupied unmet hours | 5 | 0.150 | 0.000 | 0.000…0.500 | 0.000…0.400 | 0.00% |
| DOUBLE_BANK | Facility electricity | 5 | 33.829 | 33.666 | 32.572…35.475 | 32.942…34.858 | 0.35% |
| DOUBLE_BANK | Fan electricity | 5 | 0.621 | 0.600 | 0.448…0.774 | 0.475…0.772 | 0.01% |
| DOUBLE_BANK | Pump electricity | 5 | 33.207 | 33.149 | 31.803…34.876 | 32.172…34.319 | 2.46% |
| DOUBLE_BANK | District cooling boundary | 5 | 0.177 | 0.196 | 0.097…0.205 | 0.134…0.202 | 0.10% |
| DOUBLE_BANK | District heating boundary | 5 | 1,575.287 | 1,520.032 | 1,508.913…1,701.073 | 1,509.814…1,674.744 | 0.42% |
| DOUBLE_BANK | Peak HVAC electricity | 5 | 2.325 | 2.351 | 1.880…2.643 | 2.030…2.584 | 0.62% |
| DOUBLE_BANK | Cooling occupied unmet hours | 5 | 0.050 | 0.000 | 0.000…0.250 | 0.000…0.150 | — |
| DOUBLE_BANK | Heating occupied unmet hours | 5 | 0.300 | 0.250 | 0.000…0.750 | 0.000…0.650 | 0.00% |

### Summer

| Scenario | Metric | n | Mean difference | Median | Min…Max | P10…P90 | Median % |
|---|---|---:|---:|---:|---:|---:|---:|
| MORNING_BANK | Facility electricity | 5 | -441.874 | -435.420 | -472.880…-421.697 | -465.126…-423.369 | -0.26% |
| MORNING_BANK | Fan electricity | 5 | -357.957 | -353.280 | -385.132…-337.934 | -378.642…-340.573 | -2.59% |
| MORNING_BANK | Pump electricity | 5 | -83.917 | -83.763 | -87.749…-81.346 | -86.484…-81.664 | -1.83% |
| MORNING_BANK | District cooling boundary | 5 | -907.711 | -788.806 | -1,138.145…-739.844 | -1,119.003…-756.493 | -0.14% |
| MORNING_BANK | District heating boundary | 5 | 64.587 | 56.892 | 51.797…80.086 | 53.260…79.534 | 5.64% |
| MORNING_BANK | Peak HVAC electricity | 5 | 167.417 | 170.824 | 153.224…173.655 | 158.677…173.204 | 15.00% |
| MORNING_BANK | Cooling occupied unmet hours | 5 | -8.300 | -8.000 | -9.750…-6.500 | -9.750…-6.900 | -57.14% |
| MORNING_BANK | Heating occupied unmet hours | 5 | 0.000 | 0.000 | 0.000…0.000 | 0.000…0.000 | — |
| MIDDAY_BANK | Facility electricity | 5 | 141.333 | 141.436 | 115.246…165.522 | 121.203…161.043 | 0.08% |
| MIDDAY_BANK | Fan electricity | 5 | 166.126 | 165.973 | 144.745…187.551 | 149.754…182.569 | 1.21% |
| MIDDAY_BANK | Pump electricity | 5 | -24.793 | -24.537 | -29.500…-20.772 | -28.551…-21.275 | -0.53% |
| MIDDAY_BANK | District cooling boundary | 5 | -787.642 | -742.037 | -1,337.771…-392.400 | -1,111.230…-513.274 | -0.14% |
| MIDDAY_BANK | District heating boundary | 5 | 62.516 | 55.114 | 49.653…78.056 | 50.973…77.555 | 5.47% |
| MIDDAY_BANK | Peak HVAC electricity | 5 | 471.332 | 467.037 | 448.820…500.448 | 453.727…491.976 | 41.30% |
| MIDDAY_BANK | Cooling occupied unmet hours | 5 | -9.050 | -9.000 | -10.750…-7.750 | -10.250…-7.950 | -58.93% |
| MIDDAY_BANK | Heating occupied unmet hours | 5 | 0.000 | 0.000 | 0.000…0.000 | 0.000…0.000 | — |
| EVENING_BANK | Facility electricity | 5 | -283.949 | -283.825 | -318.118…-237.724 | -314.949…-250.588 | -0.17% |
| EVENING_BANK | Fan electricity | 5 | -203.396 | -199.046 | -234.456…-165.196 | -231.133…-175.972 | -1.45% |
| EVENING_BANK | Pump electricity | 5 | -80.553 | -83.663 | -84.779…-72.528 | -84.486…-74.617 | -1.82% |
| EVENING_BANK | District cooling boundary | 5 | -264.338 | -187.909 | -594.371…-99.448 | -469.260…-123.016 | -0.03% |
| EVENING_BANK | District heating boundary | 5 | -13.098 | -19.459 | -24.138…1.787 | -23.296…0.413 | -1.93% |
| EVENING_BANK | Peak HVAC electricity | 5 | 338.304 | 338.885 | 325.206…354.881 | 327.691…349.380 | 30.16% |
| EVENING_BANK | Cooling occupied unmet hours | 5 | -8.650 | -9.250 | -10.750…-5.250 | -10.350…-6.450 | -62.71% |
| EVENING_BANK | Heating occupied unmet hours | 5 | 0.000 | 0.000 | 0.000…0.000 | 0.000…0.000 | — |
| DOUBLE_BANK | Facility electricity | 5 | 185.293 | 191.149 | 152.263…220.841 | 156.975…211.772 | 0.11% |
| DOUBLE_BANK | Fan electricity | 5 | 171.962 | 176.346 | 144.274…205.335 | 146.943…196.365 | 1.29% |
| DOUBLE_BANK | Pump electricity | 5 | 13.330 | 14.802 | 7.989…15.506 | 10.032…15.407 | 0.32% |
| DOUBLE_BANK | District cooling boundary | 5 | 1,644.412 | 1,697.894 | 1,334.788…1,866.283 | 1,432.802…1,817.079 | 0.31% |
| DOUBLE_BANK | District heating boundary | 5 | 30.565 | 26.819 | 20.612…43.788 | 21.387…41.897 | 2.65% |
| DOUBLE_BANK | Peak HVAC electricity | 5 | 157.740 | 152.660 | 149.369…171.575 | 150.533…168.073 | 13.49% |
| DOUBLE_BANK | Cooling occupied unmet hours | 5 | -4.450 | -4.750 | -5.750…-2.000 | -5.650…-2.900 | -32.20% |
| DOUBLE_BANK | Heating occupied unmet hours | 5 | 0.000 | 0.000 | 0.000…0.000 | 0.000…0.000 | — |

### Shoulder

| Scenario | Metric | n | Mean difference | Median | Min…Max | P10…P90 | Median % |
|---|---|---:|---:|---:|---:|---:|---:|
| MORNING_BANK | Facility electricity | 5 | 698.397 | 710.761 | 666.397…717.943 | 672.442…716.915 | 0.64% |
| MORNING_BANK | Fan electricity | 5 | 693.935 | 706.615 | 662.924…713.382 | 668.645…711.840 | 8.01% |
| MORNING_BANK | Pump electricity | 5 | 4.462 | 4.283 | 3.473…5.845 | 3.742…5.332 | 0.77% |
| MORNING_BANK | District cooling boundary | 5 | -913.230 | -943.100 | -1,005.298…-812.444 | -986.488…-826.281 | -1.56% |
| MORNING_BANK | District heating boundary | 5 | 4,399.296 | 4,380.396 | 4,220.766…4,696.999 | 4,237.385…4,592.601 | 12.08% |
| MORNING_BANK | Peak HVAC electricity | 5 | 215.182 | 213.355 | 205.330…230.362 | 208.066…224.094 | 43.40% |
| MORNING_BANK | Cooling occupied unmet hours | 5 | 0.300 | 0.750 | -0.750…1.000 | -0.550…0.900 | 21.43% |
| MORNING_BANK | Heating occupied unmet hours | 5 | 0.000 | 0.000 | 0.000…0.000 | 0.000…0.000 | — |
| MIDDAY_BANK | Facility electricity | 5 | 1,154.387 | 1,159.374 | 1,133.481…1,173.468 | 1,136.052…1,170.363 | 1.04% |
| MIDDAY_BANK | Fan electricity | 5 | 1,089.296 | 1,093.341 | 1,069.174…1,108.016 | 1,071.655…1,105.039 | 12.42% |
| MIDDAY_BANK | Pump electricity | 5 | 65.091 | 65.131 | 64.307…66.032 | 64.397…65.800 | 11.69% |
| MIDDAY_BANK | District cooling boundary | 5 | 5,485.986 | 5,514.157 | 5,371.828…5,581.982 | 5,389.606…5,567.466 | 9.14% |
| MIDDAY_BANK | District heating boundary | 5 | 9,363.278 | 9,269.804 | 9,188.485…9,725.156 | 9,218.522…9,582.841 | 25.66% |
| MIDDAY_BANK | Peak HVAC electricity | 5 | 384.814 | 382.062 | 381.525…395.483 | 381.640…390.565 | 79.07% |
| MIDDAY_BANK | Cooling occupied unmet hours | 5 | 0.850 | 1.000 | -0.500…1.750 | 0.000…1.550 | 28.57% |
| MIDDAY_BANK | Heating occupied unmet hours | 5 | 0.000 | 0.000 | 0.000…0.000 | 0.000…0.000 | — |
| EVENING_BANK | Facility electricity | 5 | 1,035.862 | 1,038.503 | 1,016.003…1,059.573 | 1,017.452…1,053.986 | 0.93% |
| EVENING_BANK | Fan electricity | 5 | 976.518 | 978.940 | 957.613…999.960 | 959.039…993.936 | 11.10% |
| EVENING_BANK | Pump electricity | 5 | 59.344 | 59.564 | 58.389…60.705 | 58.413…60.268 | 10.69% |
| EVENING_BANK | District cooling boundary | 5 | 5,806.728 | 5,854.652 | 5,678.807…5,911.257 | 5,681.727…5,907.881 | 9.70% |
| EVENING_BANK | District heating boundary | 5 | 7,177.209 | 7,133.170 | 6,937.941…7,556.395 | 7,006.280…7,393.736 | 19.69% |
| EVENING_BANK | Peak HVAC electricity | 5 | 269.221 | 270.438 | 258.039…284.511 | 258.375…280.402 | 56.17% |
| EVENING_BANK | Cooling occupied unmet hours | 5 | 0.950 | 1.250 | -0.250…2.000 | 0.050…1.700 | 35.71% |
| EVENING_BANK | Heating occupied unmet hours | 5 | 0.000 | 0.000 | 0.000…0.000 | 0.000…0.000 | — |
| DOUBLE_BANK | Facility electricity | 5 | 378.431 | 390.530 | 338.168…395.374 | 353.444…393.915 | 0.35% |
| DOUBLE_BANK | Fan electricity | 5 | 357.456 | 368.600 | 319.243…373.688 | 333.547…372.511 | 4.19% |
| DOUBLE_BANK | Pump electricity | 5 | 20.975 | 21.355 | 18.925…21.930 | 19.747…21.833 | 3.83% |
| DOUBLE_BANK | District cooling boundary | 5 | 1,689.317 | 1,742.051 | 1,454.566…1,818.873 | 1,545.461…1,791.040 | 2.89% |
| DOUBLE_BANK | District heating boundary | 5 | 3,538.240 | 3,561.243 | 3,341.778…3,815.520 | 3,367.352…3,716.090 | 9.84% |
| DOUBLE_BANK | Peak HVAC electricity | 5 | 80.827 | 82.847 | 56.216…100.347 | 65.975…93.852 | 16.95% |
| DOUBLE_BANK | Cooling occupied unmet hours | 5 | 3.000 | 3.000 | 2.000…3.500 | 2.400…3.500 | 100.00% |
| DOUBLE_BANK | Heating occupied unmet hours | 5 | 0.000 | 0.000 | 0.000…0.000 | 0.000…0.000 | — |

District cooling and district heating are building-side boundary energy, not central-plant production. The five seeds quantify controlled ABM stochastic-realization sensitivity, not measured uncertainty. DCV remained off, and no ABM parameter was changed after viewing energy results.
