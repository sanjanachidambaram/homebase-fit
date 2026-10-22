# Team photos (About page)

Drop one photo per person in this folder, named exactly:

| File | Caption on the About page |
|---|---|
| `sanjana.jpg` | Sanjana — creator |
| `summer.jpg` | Summer — Personal Trainer & Pilates Instructor |
| `fauzia.jpg` | Fauzia — Physical Therapist |
| `sister.jpg` | My sister — OB-GYN |

`.png` or `.webp` work too (for example `sanjana.png`). The About page tries `.jpg`, then `.png`, then `.webp`,
and shows a placeholder avatar until a file exists, so a missing photo never shows a broken image.

## Format

- **Square**, at least **400 x 400** px (it's shown as a circle about 140 px wide, so 400 px stays sharp on
  high-resolution screens). Center the face; the corners get cropped.
- **Under 300 KB** each. Export as JPG at about 80% quality, or WebP.
- Strip location data (EXIF GPS) before committing; this folder is public on GitHub.
- Only add a photo with that person's permission.

The captions are in `frontend/src/pages/AboutPage.tsx` (`TEAM`).
