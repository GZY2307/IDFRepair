# Terminal Model Inventory

The inputs are two user-authored models from one terminal modelling project; they are not an open dataset. Raw OSM names, paths, geometry, and translated IDF files are intentionally withheld from public distribution.

Every source was opened read-only. SHA-256 was checked before and after translation; generated IDFs remain in an ignored local workspace.

| Alias | Source SHA-256 | Runtime | Spaces | Zones | People | People definitions | Schedules | Air loops | Plant loops | Real zone HVAC | Weather | Translation errors | Source unchanged |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---|
| Terminal Model A | `6463d680b834230e665df8a250c694cae57c3d5cb3c877d1ad22a9c761fcccdb` | OpenStudio 3.6.1 / OSM 3.6.1 | 304 | 305 | 29 | 28 | 44 | 0 | 0 | 0 | assigned | 0 | yes |
| Terminal Model B | `bc1908ab8dd18e137feaf604f120cd90440a04d1b305aeec04f840b2c80849b7` | OpenStudio 3.6.1 / OSM 3.6.1 | 304 | 0 | 29 | 28 | 37 | 0 | 0 | 0 | missing | 0 | yes |

## Interpretation boundary

Object names alone are not used to infer check-in, security, gate, arrivals, baggage, or other terminal functions. Any later spatial groups are neutral controlled groups unless backed by an explicit user-authored mapping. Translation success does not establish HVAC or operational validity.
