# Vendored browser scripts

Copied into every built project (`assets/vendor/`) so renders never depend on a CDN.

| Package | File | Licence | Source |
|---|---|---|---|
| gsap 3.14.2 | `gsap-3.14.2/gsap.min.js` | GSAP Standard "no charge" licence (https://gsap.com/standard-license) | `npm pack gsap@3.14.2` (integrity checked by npm) |
| @hyperframes/shader-transitions 0.8.172 | `shader-transitions-0.8.172/shader-transitions.global.js` | Apache 2.0 (`LICENSE`) | `npm pack @hyperframes/shader-transitions@0.8.172` |

SHA-256 of each file is in its folder (`tools/doctor.py` verifies it). The shader-transitions
version matches the pinned HyperFrames CLI (0.8.172). To update: `npm pack <pkg>@<ver>` into a
scratch folder, copy the file, record the new SHA-256, bump the folder name in tools/build.py.
