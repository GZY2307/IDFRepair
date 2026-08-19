# Airport Occupancy V3.1 — Function/Zone effects

Status: `PASS_FUNCTION_AGGREGATION_DESIGN_SIZING_SENSITIVITY`

## Occupancy redistribution

Function totals are aggregated from private Space schedules. Design People is a BEM reference only, not fire-code, operational, or physical terminal capacity.

| Function | Source design People | Source static person-h | Source peak | Dynamic baseline person-h P50 | Dynamic peak P50 | Dynamic peak/design |
|---|---:|---:|---:|---:|---:|---:|
| domestic_waiting | 10,558.163 | 185,295.769 | 9,502.347 | 421,177.372 | 27,544.520 | 260.88% |
| central_hall | 3,190.240 | 55,988.705 | 2,871.216 | 43,414.843 | 2,995.607 | 93.90% |
| baggage_claim | 2,841.071 | 49,860.800 | 2,556.964 | 60,403.260 | 4,616.618 | 162.50% |
| arrival_exit | 2,723.916 | 47,804.732 | 2,451.525 | 3,020.163 | 261.146 | 9.59% |
| departure_entry | 357.021 | 6,265.726 | 321.319 | 22,651.222 | 1,876.743 | 525.67% |
| general_commercial | 2,669.683 | 40,045.242 | 2,669.683 | 4,535.417 | 672.292 | 25.18% |
| restaurant | 1,885.403 | 28,281.042 | 1,885.403 | 1,814.270 | 376.086 | 19.95% |
| restroom | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | — |
| international_arrival | 1,459.357 | 25,611.712 | 1,313.421 | 3,775.204 | 403.356 | 27.64% |
| international_hall | 6,054.851 | 106,262.626 | 5,449.365 | 3,775.204 | 410.222 | 6.78% |

## Largest registered function effect per metric

The selection is made only across the listed public terminal functions and is accompanied by n=5 paired statistics. Energy quantities are summed across member Zones; temperature and RH means are area-weighted; reported peak load is the maximum member-Zone peak, not a sum of noncoincident peaks.

| Period | Comparison | Metric | Function | n | Mean | Median | Min…Max | P10…P90 | Median % |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| winter | BASELINE_SPREAD − SOURCE_STATIC | people_sensible_gain_kwh | domestic_waiting | 5 | 36,391.825 kWh | 36,382.734 | 36,332.845…36,439.833 | 36,352.336…36,432.756 | — |
| winter | BASELINE_SPREAD − SOURCE_STATIC | people_latent_gain_kwh | domestic_waiting | 5 | 14,164.876 kWh | 14,158.550 | 14,139.760…14,193.689 | 14,145.474…14,187.548 | — |
| winter | BASELINE_SPREAD − SOURCE_STATIC | people_radiant_gain_kwh | domestic_waiting | 5 | 10,917.548 kWh | 10,914.820 | 10,899.853…10,931.950 | 10,905.701…10,929.827 | — |
| winter | BASELINE_SPREAD − SOURCE_STATIC | sensible_heating_kwh | domestic_waiting | 5 | -25,688.130 kWh | -25,690.683 | -25,802.538…-25,610.031 | -25,762.017…-25,620.484 | -59.46% |
| winter | BASELINE_SPREAD − SOURCE_STATIC | sensible_cooling_kwh | domestic_waiting | 5 | 3,459.249 kWh | 3,446.977 | 3,344.246…3,567.453 | 3,384.923…3,537.123 | — |
| winter | BASELINE_SPREAD − SOURCE_STATIC | maximum_zone_sensible_heating_interval_peak_kw | international_hall | 5 | -8.745 kW | -8.459 | -10.056…-8.307 | -9.472…-8.307 | -2.11% |
| winter | BASELINE_SPREAD − SOURCE_STATIC | maximum_zone_sensible_cooling_interval_peak_kw | domestic_waiting | 5 | 41.209 kW | 41.823 | 39.392…43.497 | 39.433…42.834 | — |
| winter | BASELINE_SPREAD − SOURCE_STATIC | air_temperature_mean_c | restroom | 5 | 0.166 C | 0.167 | 0.164…0.167 | 0.165…0.167 | 0.86% |
| winter | BASELINE_SPREAD − SOURCE_STATIC | relative_humidity_mean_percent | domestic_waiting | 5 | 12.469 % | 12.432 | 12.419…12.552 | 12.420…12.540 | 236.57% |
| winter | BASELINE_SPREAD − SOURCE_STATIC | outdoor_air_mean_m3_s | general_commercial | 5 | -0.000 m3/s | -0.000 | -0.000…0.000 | -0.000…0.000 | -0.00% |
| summer | BASELINE_SPREAD − SOURCE_STATIC | people_sensible_gain_kwh | domestic_waiting | 5 | 10,719.438 kWh | 10,711.296 | 10,698.153…10,746.678 | 10,700.162…10,743.163 | 65.17% |
| summer | BASELINE_SPREAD − SOURCE_STATIC | people_latent_gain_kwh | domestic_waiting | 5 | 9,429.753 kWh | 9,422.477 | 9,416.502…9,463.981 | 9,418.249…9,448.362 | 67.44% |
| summer | BASELINE_SPREAD − SOURCE_STATIC | people_radiant_gain_kwh | domestic_waiting | 5 | 3,215.831 kWh | 3,213.389 | 3,209.446…3,224.003 | 3,210.049…3,222.949 | 65.17% |
| summer | BASELINE_SPREAD − SOURCE_STATIC | sensible_heating_kwh | domestic_waiting | 5 | 0.000 kWh | 0.000 | 0.000…0.000 | 0.000…0.000 | — |
| summer | BASELINE_SPREAD − SOURCE_STATIC | sensible_cooling_kwh | domestic_waiting | 5 | 7,053.037 kWh | 7,052.725 | 7,018.258…7,076.054 | 7,031.139…7,072.707 | 11.50% |
| summer | BASELINE_SPREAD − SOURCE_STATIC | maximum_zone_sensible_heating_interval_peak_kw | domestic_waiting | 5 | 0.000 kW | 0.000 | 0.000…0.000 | 0.000…0.000 | — |
| summer | BASELINE_SPREAD − SOURCE_STATIC | maximum_zone_sensible_cooling_interval_peak_kw | international_hall | 5 | -128.688 kW | -129.798 | -130.686…-124.710 | -130.604…-125.931 | -15.48% |
| summer | BASELINE_SPREAD − SOURCE_STATIC | air_temperature_mean_c | restaurant | 5 | -1.204 C | -1.204 | -1.211…-1.195 | -1.209…-1.198 | -4.85% |
| summer | BASELINE_SPREAD − SOURCE_STATIC | relative_humidity_mean_percent | international_hall | 5 | -2.969 % | -2.962 | -3.006…-2.950 | -2.990…-2.953 | -5.57% |
| summer | BASELINE_SPREAD − SOURCE_STATIC | outdoor_air_mean_m3_s | central_hall | 5 | 3.726 m3/s | 3.724 | 3.708…3.751 | 3.714…3.741 | 10.43% |
| shoulder | BASELINE_SPREAD − SOURCE_STATIC | people_sensible_gain_kwh | domestic_waiting | 5 | 15,152.152 kWh | 15,154.696 | 15,117.352…15,194.013 | 15,119.659…15,185.040 | 104.54% |
| shoulder | BASELINE_SPREAD − SOURCE_STATIC | people_latent_gain_kwh | domestic_waiting | 5 | 13,169.057 kWh | 13,182.671 | 13,106.113…13,227.982 | 13,111.453…13,220.412 | 170.34% |
| shoulder | BASELINE_SPREAD − SOURCE_STATIC | people_radiant_gain_kwh | domestic_waiting | 5 | 4,545.646 kWh | 4,546.409 | 4,535.206…4,558.204 | 4,535.898…4,555.512 | 104.54% |
| shoulder | BASELINE_SPREAD − SOURCE_STATIC | sensible_heating_kwh | central_hall | 5 | 206.978 kWh | 209.639 | 190.739…216.645 | 197.675…213.901 | 131.23% |
| shoulder | BASELINE_SPREAD − SOURCE_STATIC | sensible_cooling_kwh | domestic_waiting | 5 | 6,904.263 kWh | 6,916.810 | 6,798.423…6,973.340 | 6,836.903…6,959.251 | 24.01% |
| shoulder | BASELINE_SPREAD − SOURCE_STATIC | maximum_zone_sensible_heating_interval_peak_kw | international_hall | 5 | 12.871 kW | 13.127 | 11.099…14.558 | 11.532…14.089 | — |
| shoulder | BASELINE_SPREAD − SOURCE_STATIC | maximum_zone_sensible_cooling_interval_peak_kw | international_hall | 5 | -67.549 kW | -67.639 | -69.372…-66.171 | -68.916…-66.235 | -13.82% |
| shoulder | BASELINE_SPREAD − SOURCE_STATIC | air_temperature_mean_c | restaurant | 5 | -1.851 C | -1.852 | -1.853…-1.849 | -1.853…-1.850 | -8.31% |
| shoulder | BASELINE_SPREAD − SOURCE_STATIC | relative_humidity_mean_percent | domestic_waiting | 5 | 3.025 % | 3.058 | 2.936…3.091 | 2.946…3.087 | 8.22% |
| shoulder | BASELINE_SPREAD − SOURCE_STATIC | outdoor_air_mean_m3_s | domestic_waiting | 5 | 7.040 m3/s | 7.101 | 6.701…7.409 | 6.727…7.335 | 5.78% |
| winter | MORNING_BANK − BASELINE_SPREAD | people_sensible_gain_kwh | domestic_waiting | 5 | -5,565.650 kWh | -5,589.536 | -5,683.410…-5,360.683 | -5,657.768…-5,446.536 | -15.36% |
| winter | MORNING_BANK − BASELINE_SPREAD | people_latent_gain_kwh | domestic_waiting | 5 | 5,565.650 kWh | 5,589.536 | 5,360.683…5,683.410 | 5,446.536…5,657.767 | 39.49% |
| winter | MORNING_BANK − BASELINE_SPREAD | people_radiant_gain_kwh | domestic_waiting | 5 | -1,669.695 kWh | -1,676.861 | -1,705.023…-1,608.205 | -1,697.330…-1,633.961 | -15.36% |
| winter | MORNING_BANK − BASELINE_SPREAD | sensible_heating_kwh | domestic_waiting | 5 | 12,395.109 kWh | 12,409.122 | 12,166.605…12,550.874 | 12,248.200…12,521.865 | 70.64% |
| winter | MORNING_BANK − BASELINE_SPREAD | sensible_cooling_kwh | domestic_waiting | 5 | 5,233.006 kWh | 5,192.580 | 5,173.853…5,341.386 | 5,173.867…5,318.160 | 150.14% |
| winter | MORNING_BANK − BASELINE_SPREAD | maximum_zone_sensible_heating_interval_peak_kw | international_hall | 5 | 6.765 kW | 6.732 | 5.665…8.507 | 5.688…7.984 | 1.72% |
| winter | MORNING_BANK − BASELINE_SPREAD | maximum_zone_sensible_cooling_interval_peak_kw | baggage_claim | 5 | 163.217 kW | 161.242 | 159.356…168.799 | 160.092…167.477 | 1,874.77% |
| winter | MORNING_BANK − BASELINE_SPREAD | air_temperature_mean_c | domestic_waiting | 5 | 0.590 C | 0.594 | 0.573…0.598 | 0.579…0.597 | 2.97% |
| winter | MORNING_BANK − BASELINE_SPREAD | relative_humidity_mean_percent | domestic_waiting | 5 | 1.674 % | 1.402 | 1.356…2.187 | 1.363…2.132 | 7.88% |
| winter | MORNING_BANK − BASELINE_SPREAD | outdoor_air_mean_m3_s | domestic_waiting | 5 | 0.305 m3/s | 0.300 | 0.266…0.347 | 0.276…0.338 | 0.42% |
| summer | MORNING_BANK − BASELINE_SPREAD | people_sensible_gain_kwh | domestic_waiting | 5 | -5,186.470 kWh | -5,178.814 | -5,339.484…-5,012.668 | -5,302.754…-5,069.090 | -19.06% |
| summer | MORNING_BANK − BASELINE_SPREAD | people_latent_gain_kwh | domestic_waiting | 5 | 5,186.470 kWh | 5,178.814 | 5,012.668…5,339.484 | 5,069.090…5,302.754 | 22.14% |
| summer | MORNING_BANK − BASELINE_SPREAD | people_radiant_gain_kwh | domestic_waiting | 5 | -1,555.941 kWh | -1,553.644 | -1,601.845…-1,503.800 | -1,590.826…-1,520.727 | -19.06% |
| summer | MORNING_BANK − BASELINE_SPREAD | sensible_heating_kwh | domestic_waiting | 5 | 0.000 kWh | 0.000 | 0.000…0.000 | 0.000…0.000 | — |
| summer | MORNING_BANK − BASELINE_SPREAD | sensible_cooling_kwh | domestic_waiting | 5 | -5,236.733 kWh | -5,258.545 | -5,388.093…-5,094.965 | -5,336.291…-5,130.369 | -7.69% |
| summer | MORNING_BANK − BASELINE_SPREAD | maximum_zone_sensible_heating_interval_peak_kw | domestic_waiting | 5 | 0.000 kW | 0.000 | 0.000…0.000 | 0.000…0.000 | — |
| summer | MORNING_BANK − BASELINE_SPREAD | maximum_zone_sensible_cooling_interval_peak_kw | baggage_claim | 5 | 86.296 kW | 88.250 | 67.298…97.622 | 73.253…97.022 | 25.17% |
| summer | MORNING_BANK − BASELINE_SPREAD | air_temperature_mean_c | domestic_waiting | 5 | 0.189 C | 0.193 | 0.171…0.203 | 0.176…0.199 | 0.78% |
| summer | MORNING_BANK − BASELINE_SPREAD | relative_humidity_mean_percent | departure_entry | 5 | -0.457 % | -0.463 | -0.505…-0.412 | -0.494…-0.418 | -0.85% |
| summer | MORNING_BANK − BASELINE_SPREAD | outdoor_air_mean_m3_s | domestic_waiting | 5 | -2.501 m3/s | -2.508 | -2.539…-2.453 | -2.532…-2.466 | -3.33% |
| shoulder | MORNING_BANK − BASELINE_SPREAD | people_sensible_gain_kwh | domestic_waiting | 5 | -2,641.796 kWh | -2,663.773 | -2,750.018…-2,507.783 | -2,749.887…-2,519.756 | -8.97% |
| shoulder | MORNING_BANK − BASELINE_SPREAD | people_latent_gain_kwh | domestic_waiting | 5 | 2,641.796 kWh | 2,663.773 | 2,507.783…2,750.018 | 2,519.756…2,749.887 | 12.78% |
| shoulder | MORNING_BANK − BASELINE_SPREAD | people_radiant_gain_kwh | domestic_waiting | 5 | -792.539 kWh | -799.132 | -825.005…-752.335 | -824.966…-755.927 | -8.97% |
| shoulder | MORNING_BANK − BASELINE_SPREAD | sensible_heating_kwh | central_hall | 5 | 239.950 kWh | 238.113 | 225.120…261.143 | 228.716…253.190 | 64.44% |
| shoulder | MORNING_BANK − BASELINE_SPREAD | sensible_cooling_kwh | baggage_claim | 5 | -362.474 kWh | -370.598 | -396.168…-325.638 | -390.641…-330.430 | -3.95% |
| shoulder | MORNING_BANK − BASELINE_SPREAD | maximum_zone_sensible_heating_interval_peak_kw | international_hall | 5 | 9.312 kW | 9.309 | 8.180…10.590 | 8.483…10.172 | 72.70% |
| shoulder | MORNING_BANK − BASELINE_SPREAD | maximum_zone_sensible_cooling_interval_peak_kw | baggage_claim | 5 | 150.308 kW | 152.820 | 128.728…165.545 | 137.845…160.497 | 77.88% |
| shoulder | MORNING_BANK − BASELINE_SPREAD | air_temperature_mean_c | domestic_waiting | 5 | -0.645 C | -0.647 | -0.660…-0.621 | -0.659…-0.628 | -2.86% |
| shoulder | MORNING_BANK − BASELINE_SPREAD | relative_humidity_mean_percent | domestic_waiting | 5 | -1.282 % | -1.288 | -1.365…-1.193 | -1.346…-1.214 | -3.21% |
| shoulder | MORNING_BANK − BASELINE_SPREAD | outdoor_air_mean_m3_s | domestic_waiting | 5 | 12.045 m3/s | 12.146 | 11.470…12.546 | 11.560…12.474 | 9.35% |
| winter | MIDDAY_BANK − BASELINE_SPREAD | people_sensible_gain_kwh | domestic_waiting | 5 | -5,607.647 kWh | -5,578.454 | -5,750.562…-5,503.295 | -5,730.223…-5,504.460 | -15.32% |
| winter | MIDDAY_BANK − BASELINE_SPREAD | people_latent_gain_kwh | domestic_waiting | 5 | 5,607.647 kWh | 5,578.454 | 5,503.295…5,750.562 | 5,504.460…5,730.223 | 39.45% |
| winter | MIDDAY_BANK − BASELINE_SPREAD | people_radiant_gain_kwh | domestic_waiting | 5 | -1,682.294 kWh | -1,673.536 | -1,725.169…-1,650.989 | -1,719.067…-1,651.338 | -15.32% |
| winter | MIDDAY_BANK − BASELINE_SPREAD | sensible_heating_kwh | domestic_waiting | 5 | 12,480.692 kWh | 12,426.843 | 12,402.092…12,601.487 | 12,408.272…12,583.091 | 71.27% |
| winter | MIDDAY_BANK − BASELINE_SPREAD | sensible_cooling_kwh | domestic_waiting | 5 | 5,254.819 kWh | 5,226.698 | 5,218.984…5,319.474 | 5,221.593…5,305.057 | 153.28% |
| winter | MIDDAY_BANK − BASELINE_SPREAD | maximum_zone_sensible_heating_interval_peak_kw | baggage_claim | 5 | 5.492 kW | 6.082 | 1.958…9.304 | 2.775…8.029 | 4.24% |
| winter | MIDDAY_BANK − BASELINE_SPREAD | maximum_zone_sensible_cooling_interval_peak_kw | baggage_claim | 5 | 165.471 kW | 164.483 | 161.370…170.511 | 161.373…170.152 | 1,893.37% |
| winter | MIDDAY_BANK − BASELINE_SPREAD | air_temperature_mean_c | domestic_waiting | 5 | 0.594 C | 0.595 | 0.589…0.599 | 0.589…0.598 | 2.97% |
| winter | MIDDAY_BANK − BASELINE_SPREAD | relative_humidity_mean_percent | domestic_waiting | 5 | 1.656 % | 1.621 | 1.444…1.857 | 1.507…1.817 | 9.11% |
| winter | MIDDAY_BANK − BASELINE_SPREAD | outdoor_air_mean_m3_s | domestic_waiting | 5 | 0.310 m3/s | 0.313 | 0.251…0.354 | 0.270…0.345 | 0.44% |
| summer | MIDDAY_BANK − BASELINE_SPREAD | people_sensible_gain_kwh | domestic_waiting | 5 | -7,046.804 kWh | -6,979.847 | -7,321.550…-6,839.419 | -7,269.249…-6,864.614 | -25.69% |
| summer | MIDDAY_BANK − BASELINE_SPREAD | people_latent_gain_kwh | domestic_waiting | 5 | 7,046.804 kWh | 6,979.847 | 6,839.419…7,321.550 | 6,864.614…7,269.249 | 29.84% |
| summer | MIDDAY_BANK − BASELINE_SPREAD | people_radiant_gain_kwh | domestic_waiting | 5 | -2,114.041 kWh | -2,093.954 | -2,196.465…-2,051.826 | -2,180.775…-2,059.384 | -25.69% |
| summer | MIDDAY_BANK − BASELINE_SPREAD | sensible_heating_kwh | domestic_waiting | 5 | 0.000 kWh | 0.000 | 0.000…0.000 | 0.000…0.000 | — |
| summer | MIDDAY_BANK − BASELINE_SPREAD | sensible_cooling_kwh | domestic_waiting | 5 | -7,488.723 kWh | -7,508.123 | -7,625.974…-7,325.738 | -7,611.390…-7,353.149 | -10.98% |
| summer | MIDDAY_BANK − BASELINE_SPREAD | maximum_zone_sensible_heating_interval_peak_kw | domestic_waiting | 5 | 0.000 kW | 0.000 | 0.000…0.000 | 0.000…0.000 | — |
| summer | MIDDAY_BANK − BASELINE_SPREAD | maximum_zone_sensible_cooling_interval_peak_kw | international_hall | 5 | 106.004 kW | 106.578 | 98.730…111.686 | 100.126…111.335 | 15.06% |
| summer | MIDDAY_BANK − BASELINE_SPREAD | air_temperature_mean_c | domestic_waiting | 5 | 0.294 C | 0.293 | 0.281…0.308 | 0.285…0.304 | 1.19% |
| summer | MIDDAY_BANK − BASELINE_SPREAD | relative_humidity_mean_percent | arrival_exit | 5 | 0.652 % | 0.645 | 0.614…0.702 | 0.619…0.690 | 1.25% |
| summer | MIDDAY_BANK − BASELINE_SPREAD | outdoor_air_mean_m3_s | domestic_waiting | 5 | -3.428 m3/s | -3.433 | -3.455…-3.377 | -3.450…-3.398 | -4.55% |
| shoulder | MIDDAY_BANK − BASELINE_SPREAD | people_sensible_gain_kwh | domestic_waiting | 5 | -4,033.818 kWh | -3,943.367 | -4,194.268…-3,906.375 | -4,193.780…-3,916.637 | -13.31% |
| shoulder | MIDDAY_BANK − BASELINE_SPREAD | people_latent_gain_kwh | domestic_waiting | 5 | 4,033.818 kWh | 3,943.367 | 3,906.375…4,194.268 | 3,916.637…4,193.780 | 18.85% |
| shoulder | MIDDAY_BANK − BASELINE_SPREAD | people_radiant_gain_kwh | domestic_waiting | 5 | -1,210.145 kWh | -1,183.010 | -1,258.280…-1,171.912 | -1,258.134…-1,174.991 | -13.31% |
| shoulder | MIDDAY_BANK − BASELINE_SPREAD | sensible_heating_kwh | central_hall | 5 | 221.803 kWh | 219.741 | 208.057…242.749 | 211.141…234.729 | 59.46% |
| shoulder | MIDDAY_BANK − BASELINE_SPREAD | sensible_cooling_kwh | central_hall | 5 | -993.855 kWh | -998.377 | -1,027.667…-959.611 | -1,018.256…-967.560 | -8.11% |
| shoulder | MIDDAY_BANK − BASELINE_SPREAD | maximum_zone_sensible_heating_interval_peak_kw | international_hall | 5 | 9.015 kW | 9.238 | 8.127…9.478 | 8.415…9.440 | 72.20% |
| shoulder | MIDDAY_BANK − BASELINE_SPREAD | maximum_zone_sensible_cooling_interval_peak_kw | baggage_claim | 5 | 206.704 kW | 209.591 | 191.297…212.714 | 197.874…212.501 | 106.90% |
| shoulder | MIDDAY_BANK − BASELINE_SPREAD | air_temperature_mean_c | domestic_waiting | 5 | -0.816 C | -0.817 | -0.832…-0.794 | -0.830…-0.800 | -3.61% |
| shoulder | MIDDAY_BANK − BASELINE_SPREAD | relative_humidity_mean_percent | domestic_waiting | 5 | -1.062 % | -1.052 | -1.193…-0.955 | -1.176…-0.956 | -2.61% |
| shoulder | MIDDAY_BANK − BASELINE_SPREAD | outdoor_air_mean_m3_s | domestic_waiting | 5 | 15.477 m3/s | 15.621 | 14.986…15.822 | 15.081…15.787 | 12.03% |
| winter | EVENING_BANK − BASELINE_SPREAD | people_sensible_gain_kwh | domestic_waiting | 5 | -5,547.139 kWh | -5,549.171 | -5,686.055…-5,384.637 | -5,681.900…-5,406.849 | -15.24% |
| winter | EVENING_BANK − BASELINE_SPREAD | people_latent_gain_kwh | domestic_waiting | 5 | 5,547.139 kWh | 5,549.171 | 5,384.637…5,686.055 | 5,406.849…5,681.900 | 39.25% |
| winter | EVENING_BANK − BASELINE_SPREAD | people_radiant_gain_kwh | domestic_waiting | 5 | -1,664.142 kWh | -1,664.751 | -1,705.817…-1,615.391 | -1,704.570…-1,622.055 | -15.24% |
| winter | EVENING_BANK − BASELINE_SPREAD | sensible_heating_kwh | domestic_waiting | 5 | 12,353.097 kWh | 12,341.373 | 12,202.800…12,574.405 | 12,218.449…12,506.637 | 70.47% |
| winter | EVENING_BANK − BASELINE_SPREAD | sensible_cooling_kwh | domestic_waiting | 5 | 5,228.656 kWh | 5,247.182 | 5,157.063…5,276.365 | 5,175.101…5,270.024 | 152.61% |
| winter | EVENING_BANK − BASELINE_SPREAD | maximum_zone_sensible_heating_interval_peak_kw | international_hall | 5 | 5.879 kW | 5.622 | 5.403…7.121 | 5.456…6.557 | 1.44% |
| winter | EVENING_BANK − BASELINE_SPREAD | maximum_zone_sensible_cooling_interval_peak_kw | baggage_claim | 5 | 166.108 kW | 164.184 | 163.114…170.530 | 163.524…169.747 | 1,902.57% |
| winter | EVENING_BANK − BASELINE_SPREAD | air_temperature_mean_c | domestic_waiting | 5 | 0.590 C | 0.590 | 0.582…0.595 | 0.585…0.594 | 2.95% |
| winter | EVENING_BANK − BASELINE_SPREAD | relative_humidity_mean_percent | domestic_waiting | 5 | 1.835 % | 1.796 | 1.589…2.122 | 1.635…2.060 | 10.16% |
| winter | EVENING_BANK − BASELINE_SPREAD | outdoor_air_mean_m3_s | domestic_waiting | 5 | 0.306 m3/s | 0.292 | 0.253…0.354 | 0.268…0.348 | 0.41% |
| summer | EVENING_BANK − BASELINE_SPREAD | people_sensible_gain_kwh | domestic_waiting | 5 | -6,285.974 kWh | -6,252.592 | -6,571.719…-6,011.028 | -6,545.054…-6,042.408 | -23.01% |
| summer | EVENING_BANK − BASELINE_SPREAD | people_latent_gain_kwh | domestic_waiting | 5 | 6,285.974 kWh | 6,252.592 | 6,011.028…6,571.719 | 6,042.408…6,545.054 | 26.74% |
| summer | EVENING_BANK − BASELINE_SPREAD | people_radiant_gain_kwh | domestic_waiting | 5 | -1,885.792 kWh | -1,875.778 | -1,971.516…-1,803.308 | -1,963.516…-1,812.722 | -23.01% |
| summer | EVENING_BANK − BASELINE_SPREAD | sensible_heating_kwh | domestic_waiting | 5 | 0.000 kWh | 0.000 | 0.000…0.000 | 0.000…0.000 | — |
| summer | EVENING_BANK − BASELINE_SPREAD | sensible_cooling_kwh | domestic_waiting | 5 | -6,579.087 kWh | -6,585.882 | -6,839.166…-6,361.783 | -6,797.906…-6,366.104 | -9.63% |
| summer | EVENING_BANK − BASELINE_SPREAD | maximum_zone_sensible_heating_interval_peak_kw | domestic_waiting | 5 | 0.000 kW | 0.000 | 0.000…0.000 | 0.000…0.000 | — |
| summer | EVENING_BANK − BASELINE_SPREAD | maximum_zone_sensible_cooling_interval_peak_kw | baggage_claim | 5 | 109.069 kW | 115.349 | 92.524…119.610 | 95.336…119.090 | 33.46% |
| summer | EVENING_BANK − BASELINE_SPREAD | air_temperature_mean_c | domestic_waiting | 5 | 0.247 C | 0.246 | 0.230…0.259 | 0.236…0.258 | 1.00% |
| summer | EVENING_BANK − BASELINE_SPREAD | relative_humidity_mean_percent | domestic_waiting | 5 | 0.502 % | 0.503 | 0.387…0.573 | 0.432…0.562 | 0.91% |
| summer | EVENING_BANK − BASELINE_SPREAD | outdoor_air_mean_m3_s | domestic_waiting | 5 | -3.014 m3/s | -3.028 | -3.083…-2.958 | -3.062…-2.963 | -4.02% |
| shoulder | EVENING_BANK − BASELINE_SPREAD | people_sensible_gain_kwh | domestic_waiting | 5 | -3,994.914 kWh | -3,886.413 | -4,209.287…-3,862.689 | -4,179.806…-3,869.852 | -13.12% |
| shoulder | EVENING_BANK − BASELINE_SPREAD | people_latent_gain_kwh | domestic_waiting | 5 | 3,994.914 kWh | 3,886.413 | 3,862.689…4,209.287 | 3,869.852…4,179.806 | 18.62% |
| shoulder | EVENING_BANK − BASELINE_SPREAD | people_radiant_gain_kwh | domestic_waiting | 5 | -1,198.474 kWh | -1,165.924 | -1,262.786…-1,158.807 | -1,253.942…-1,160.956 | -13.12% |
| shoulder | EVENING_BANK − BASELINE_SPREAD | sensible_heating_kwh | domestic_waiting | 5 | 154.344 kWh | 151.137 | 138.916…183.088 | 138.924…173.710 | 75.66% |
| shoulder | EVENING_BANK − BASELINE_SPREAD | sensible_cooling_kwh | central_hall | 5 | -954.399 kWh | -955.734 | -1,017.200…-898.019 | -994.548…-915.000 | -7.78% |
| shoulder | EVENING_BANK − BASELINE_SPREAD | maximum_zone_sensible_heating_interval_peak_kw | international_hall | 5 | 6.482 kW | 6.927 | 5.511…7.174 | 5.595…7.135 | 54.65% |
| shoulder | EVENING_BANK − BASELINE_SPREAD | maximum_zone_sensible_cooling_interval_peak_kw | baggage_claim | 5 | 197.729 kW | 205.686 | 175.318…207.889 | 182.501…207.325 | 104.74% |
| shoulder | EVENING_BANK − BASELINE_SPREAD | air_temperature_mean_c | domestic_waiting | 5 | -0.860 C | -0.861 | -0.888…-0.840 | -0.881…-0.841 | -3.81% |
| shoulder | EVENING_BANK − BASELINE_SPREAD | relative_humidity_mean_percent | domestic_waiting | 5 | -0.654 % | -0.708 | -0.737…-0.543 | -0.734…-0.547 | -1.76% |
| shoulder | EVENING_BANK − BASELINE_SPREAD | outdoor_air_mean_m3_s | domestic_waiting | 5 | 15.406 m3/s | 15.356 | 14.906…15.865 | 15.018…15.805 | 11.83% |
| winter | DOUBLE_BANK − BASELINE_SPREAD | people_sensible_gain_kwh | domestic_waiting | 5 | -1,045.629 kWh | -1,001.766 | -1,127.648…-996.245 | -1,117.763…-997.568 | -2.75% |
| winter | DOUBLE_BANK − BASELINE_SPREAD | people_latent_gain_kwh | domestic_waiting | 5 | 1,045.629 kWh | 1,001.766 | 996.245…1,127.648 | 997.568…1,117.763 | 7.08% |
| winter | DOUBLE_BANK − BASELINE_SPREAD | people_radiant_gain_kwh | domestic_waiting | 5 | -313.689 kWh | -300.530 | -338.294…-298.874 | -335.329…-299.270 | -2.75% |
| winter | DOUBLE_BANK − BASELINE_SPREAD | sensible_heating_kwh | domestic_waiting | 5 | 6,532.613 kWh | 6,595.817 | 6,322.246…6,702.380 | 6,371.732…6,660.092 | 37.49% |
| winter | DOUBLE_BANK − BASELINE_SPREAD | sensible_cooling_kwh | domestic_waiting | 5 | 4,887.550 kWh | 4,853.263 | 4,743.444…5,017.805 | 4,773.853…5,012.192 | 139.00% |
| winter | DOUBLE_BANK − BASELINE_SPREAD | maximum_zone_sensible_heating_interval_peak_kw | baggage_claim | 5 | 5.491 kW | 6.084 | 1.979…9.290 | 2.792…8.010 | 4.24% |
| winter | DOUBLE_BANK − BASELINE_SPREAD | maximum_zone_sensible_cooling_interval_peak_kw | baggage_claim | 5 | 81.666 kW | 85.827 | 65.574…96.844 | 66.384…95.102 | 931.96% |
| winter | DOUBLE_BANK − BASELINE_SPREAD | air_temperature_mean_c | domestic_waiting | 5 | 0.160 C | 0.156 | 0.154…0.173 | 0.154…0.170 | 0.78% |
| winter | DOUBLE_BANK − BASELINE_SPREAD | relative_humidity_mean_percent | baggage_claim | 5 | -0.113 % | -0.150 | -0.224…0.135 | -0.211…0.029 | -1.39% |
| winter | DOUBLE_BANK − BASELINE_SPREAD | outdoor_air_mean_m3_s | general_commercial | 5 | 0.001 m3/s | 0.001 | -0.001…0.002 | -0.001…0.002 | 0.00% |
| summer | DOUBLE_BANK − BASELINE_SPREAD | people_sensible_gain_kwh | domestic_waiting | 5 | -1,300.349 kWh | -1,266.997 | -1,431.778…-1,201.517 | -1,395.505…-1,225.053 | -4.67% |
| summer | DOUBLE_BANK − BASELINE_SPREAD | people_latent_gain_kwh | domestic_waiting | 5 | 1,300.349 kWh | 1,266.997 | 1,201.517…1,431.778 | 1,225.053…1,395.505 | 5.42% |
| summer | DOUBLE_BANK − BASELINE_SPREAD | people_radiant_gain_kwh | domestic_waiting | 5 | -390.105 kWh | -380.099 | -429.533…-360.455 | -418.652…-367.516 | -4.67% |
| summer | DOUBLE_BANK − BASELINE_SPREAD | sensible_heating_kwh | domestic_waiting | 5 | 0.000 kWh | 0.000 | 0.000…0.000 | 0.000…0.000 | — |
| summer | DOUBLE_BANK − BASELINE_SPREAD | sensible_cooling_kwh | domestic_waiting | 5 | -1,176.190 kWh | -1,152.911 | -1,331.890…-1,060.791 | -1,282.268…-1,087.485 | -1.69% |
| summer | DOUBLE_BANK − BASELINE_SPREAD | maximum_zone_sensible_heating_interval_peak_kw | domestic_waiting | 5 | 0.000 kW | 0.000 | 0.000…0.000 | 0.000…0.000 | — |
| summer | DOUBLE_BANK − BASELINE_SPREAD | maximum_zone_sensible_cooling_interval_peak_kw | baggage_claim | 5 | 56.097 kW | 57.567 | 43.273…66.120 | 45.330…65.715 | 16.42% |
| summer | DOUBLE_BANK − BASELINE_SPREAD | air_temperature_mean_c | baggage_claim | 5 | -0.175 C | -0.172 | -0.196…-0.162 | -0.190…-0.163 | -0.69% |
| summer | DOUBLE_BANK − BASELINE_SPREAD | relative_humidity_mean_percent | international_arrival | 5 | 0.197 % | 0.190 | 0.184…0.220 | 0.186…0.212 | 0.37% |
| summer | DOUBLE_BANK − BASELINE_SPREAD | outdoor_air_mean_m3_s | domestic_waiting | 5 | -0.884 m3/s | -0.894 | -0.942…-0.798 | -0.924…-0.835 | -1.19% |
| shoulder | DOUBLE_BANK − BASELINE_SPREAD | people_sensible_gain_kwh | domestic_waiting | 5 | -1,259.116 kWh | -1,238.565 | -1,360.155…-1,182.335 | -1,332.775…-1,198.528 | -4.18% |
| shoulder | DOUBLE_BANK − BASELINE_SPREAD | people_latent_gain_kwh | domestic_waiting | 5 | 1,259.116 kWh | 1,238.565 | 1,182.335…1,360.155 | 1,198.528…1,332.775 | 5.91% |
| shoulder | DOUBLE_BANK − BASELINE_SPREAD | people_radiant_gain_kwh | domestic_waiting | 5 | -377.735 kWh | -371.569 | -408.046…-354.700 | -399.832…-359.559 | -4.18% |
| shoulder | DOUBLE_BANK − BASELINE_SPREAD | sensible_heating_kwh | domestic_waiting | 5 | 184.211 kWh | 180.257 | 167.761…214.203 | 168.333…204.380 | 90.24% |
| shoulder | DOUBLE_BANK − BASELINE_SPREAD | sensible_cooling_kwh | baggage_claim | 5 | -304.874 kWh | -325.193 | -340.613…-254.854 | -338.472…-260.291 | -3.47% |
| shoulder | DOUBLE_BANK − BASELINE_SPREAD | maximum_zone_sensible_heating_interval_peak_kw | international_hall | 5 | 6.954 kW | 6.919 | 5.773…8.210 | 6.142…7.796 | 54.65% |
| shoulder | DOUBLE_BANK − BASELINE_SPREAD | maximum_zone_sensible_cooling_interval_peak_kw | baggage_claim | 5 | 72.726 kW | 72.204 | 66.139…81.794 | 66.987…79.171 | 36.85% |
| shoulder | DOUBLE_BANK − BASELINE_SPREAD | air_temperature_mean_c | domestic_waiting | 5 | -0.286 C | -0.296 | -0.308…-0.246 | -0.306…-0.259 | -1.31% |
| shoulder | DOUBLE_BANK − BASELINE_SPREAD | relative_humidity_mean_percent | domestic_waiting | 5 | -0.558 % | -0.544 | -0.676…-0.474 | -0.644…-0.484 | -1.35% |
| shoulder | DOUBLE_BANK − BASELINE_SPREAD | outdoor_air_mean_m3_s | domestic_waiting | 5 | 9.197 m3/s | 9.404 | 8.320…9.658 | 8.598…9.630 | 7.24% |

People sensible/latent/radiant gains, Zone heating/cooling, air temperature, relative humidity, and outdoor-air flow are all included. The results are controlled and not measured, and the incomplete fixed-sizing gate limits interpretation to design/sizing sensitivity.
