# Third-party notices

Vigil
Copyright (c) 2026 Paramjot Singh

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU Affero General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option) any
later version. See [LICENSE](LICENSE) for the full text.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the GNU Affero General Public License for more details.

---

## Why AGPL-3.0

Vigil's detection is built on **Ultralytics YOLO**, which is licensed
**AGPL-3.0**. AGPL-3.0 is a strong copyleft licence: a work that incorporates
it and is distributed to others must itself be offered under AGPL-3.0, with
complete corresponding source available to every recipient. Because Vigil
bundles Ultralytics into its desktop builds and distributes those builds, Vigil
is licensed AGPL-3.0 as well.

This is not a restriction Vigil chose independently — it follows from the
dependency. The alternatives would be to obtain an Ultralytics Enterprise
licence, or to replace the detection backend with a permissively-licensed model.

**What this means in practice.** Anyone who receives a Vigil build is entitled
to the complete source for that build under the same terms. Keeping the source
repository public satisfies this; shipping binaries without published source
would not.

## Bundled components

Versions are those bundled in the desktop builds under `dist/`.

| Component | Version | Licence |
|---|---|---|
| Ultralytics YOLO | 8.4.102 | **AGPL-3.0** |
| PyTorch | 2.13.0 | BSD-3-Clause |
| TorchVision | 0.28.0 | BSD-3-Clause |
| OpenCV (`opencv-python`) | 5.0.0.93 | Apache-2.0 |
| NumPy | 2.5.1 | BSD-3-Clause |
| FastAPI | — | MIT |
| Starlette | — | BSD-3-Clause |
| Uvicorn | — | BSD-3-Clause |
| Pydantic | 2.13.4 | MIT |
| websockets | 16.1.1 | BSD-3-Clause |
| qrcode | 8.2 | BSD |
| pywebpush | — | MPL-2.0 |
| python-multipart | — | Apache-2.0 |

Every licence above other than Ultralytics is permissive and compatible with
AGPL-3.0 distribution. Ultralytics is the binding constraint.

Model weights (`yolov8n.pt` and any fine-tuned derivatives) are covered by the
Ultralytics licence terms, not by Vigil's copyright.

> Verify this table against your own build before relying on it — versions move,
> and a few packages above did not declare a licence in their metadata, so those
> rows come from the projects' own published terms rather than from the bundle.
> This file is a good-faith notice, not legal advice.
