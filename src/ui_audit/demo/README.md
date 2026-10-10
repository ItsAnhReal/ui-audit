# Demo app — planted defects

A three-page static site used by the end-to-end tests and by `ui-audit demo`, which serves it and audits it. Every defect is deliberate.

| Route | State | Widths | Defect | Check |
|---|---|---|---|---|
| `/` | default | 800–946 | Four fixed 220px feature columns | `horizontal-overflow` |
| `/` | menu open | 320–767 | Drawer positioned `right: -60px` | `horizontal-overflow` |
| `/` | all | all | Two 18px icon buttons without a label, 4px apart | `small-target` ×2, `unnamed-control` ×2 |
| `/pricing.html` | default | 320–767 | Price in an 80px box with hidden overflow | `clipped-content` ×3 |
| `/pricing.html` | default | 768–1023 | "Contact" slides under "Compare" | `overlapping-controls` ×3 |
| `/dashboard.html` | Reports tab | all | Report text in a 60px box with hidden overflow | `clipped-content` |
| `/dashboard.html` | filters open | 320–~400 | Two fixed 180px inputs | `horizontal-overflow` |

The 800–946 overflow is the point of the demo: the four standard presets (390, 768, 1366, 1920) miss it, the sweep finds it, and refinement pins both edges.
