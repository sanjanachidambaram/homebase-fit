# Team photos (About page)

Drop the photos in this folder, named exactly:

| File | Where it shows on the About page ("Meet the Team Behind Bee Fit") |
|---|---|
| `sanjana.jpg` | Sanjana's profile, left of her bio (a landscape headshot is fine; it's cropped to the face) |
| `summer-1.jpg` to `summer-4.jpg` | Summer's profile: the row of four photos above her bio (portrait, 3:4) |

`.png` or `.webp` work too (for example `sanjana.png`). The About page tries `.jpg`, then `.png`, then `.webp`,
and shows a placeholder avatar until a file exists, so a missing photo never shows a broken image.

## Format

- **About 900 to 1000 px wide** (shown up to about 400 px wide, so that stays sharp on high-resolution screens).
  Summer's are portrait (3:4); Sanjana's can be any shape, it's cropped to a 4:5 portrait around the face.
- **Under 300 KB** each. Export as JPG at about 80% quality, or WebP.
- Strip location data (EXIF GPS) before committing; this folder is public on GitHub.
- Only add a photo with that person's permission.

The bios and photo descriptions (alt text) are in `frontend/src/pages/AboutPage.tsx` (`Team`, `SUMMER_PHOTOS`).
