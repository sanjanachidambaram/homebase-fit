# Team photos (About page)

Drop one photo per person in this folder, named exactly:

| File | Who |
|---|---|
| `creator.jpg` | the creator (Yale student) |
| `pt-friend.jpg` | physical therapist (friend) |
| `pt-mom.jpg` | physical therapist (her mom) |
| `obgyn-sister.jpg` | OB-GYN (sister) |

`.png` or `.webp` work too (for example `creator.png`). The About page tries `.jpg`, then `.png`, then `.webp`,
and shows a placeholder avatar until a file exists, so a missing photo never shows a broken image.

## Format

- **Square**, at least **400 x 400** px (it's shown as a circle about 140 px wide, so 400 px stays sharp on
  high-resolution screens). Center the face; the corners get cropped.
- **Under 300 KB** each. Export as JPG at about 80% quality, or WebP.
- Strip location data (EXIF GPS) before committing; this folder is public on GitHub.
- Only add a photo with that person's permission.

Names, roles and bios are placeholders in `frontend/src/pages/AboutPage.tsx` (`TEAM`). The OB-GYN's name
comes from `OBGYN_NAME` in `frontend/src/legal.ts`, the same constant the pregnancy support page uses.
