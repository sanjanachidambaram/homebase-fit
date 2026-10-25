# HomeBase Fit: Design Direction

**Status: spec for the real frontend. Not applied yet.** The current test pages still use the
temporary blue-and-white, Times New Roman styling. This file is the standing design direction for
**every** page we build next: quiz, dashboard, programs, basics hub, calendar, progress, faves,
and the exercise detail view. When a page is built, it follows this file; if a page needs
something this file doesn't cover, add it here first.

> This replaces the blue/white/Times New Roman defaults in `AGENTS.md` for the HomeBase Fit
> frontend, because you asked for this direction explicitly. Everything else in `AGENTS.md`
> still applies (notably: pictures are built with HTML/CSS/SVG, never generated raster images).

---

## 1. The feeling

Vibrant, fun, playful, a little "girly", genuinely joyful to use. Opening the app should feel
like a treat, not like opening a spreadsheet or a clinic's intake form.

- Think candy-shop colors, big friendly shapes, things that bounce when you touch them.
- Warm, a little cheeky, encouraging. Never clinical, never preachy.
- Celebrate showing up, not looking a certain way (see "Copy" below).

## 2. Palette

Starting palette from the brief, kept as is. **Use it for fills, shapes, and accents.** The numbers
in the table are real WCAG contrast ratios (computed, not guessed) against the page background,
and they show why text needs separate colors.

| Role | Name | Hex | vs. background | Notes |
|---|---|---|---|---|
| Primary / brand | Hot pink | `#FF4FA3` | 2.9 | Main buttons, active tab, hearts. Text on it: dark ink (4.6) or **large bold** white (3.0) only |
| Highlight | Sunny yellow | `#FFD23F` | 1.4 | Stars, streak badges, confetti, highlights. Always with dark ink text (9.8) |
| Success | Mint / teal | `#06D6A0` | 1.8 | Goal hit, completed workout, checkmarks. Dark ink text on it (7.5) |
| Secondary | Soft lavender | `#B298DC` | 2.4 | Cards, section tints, secondary buttons. Dark ink text on it (5.7) |
| Warm accent | Warm coral | `#FF6B6B` | 2.7 | Warm pops, rest-day cards. Dark ink text on it (5.1) |
| Background | Warm off-white | `#FFF9F5` | n/a | Page background |
| Text | Plum ink (new) | `#3A2147` | 13.5 | All body text and headings. A very dark plum, softer than black |

**Text-safe deep versions** (new). The brand colors are too light to carry small text on the
off-white background, so links, icons, and outlines that must be *readable* use these:

| Use | Hex | vs. background |
|---|---|---|
| Deep pink (links, focus rings, small icons) | `#E0006B` | 4.6 |
| Deep teal (success text) | `#048261` | 4.6 |
| Deep lavender (secondary text/icons) | `#865DC8` | 4.6 |
| Error red (new; coral is too light for error text) | `#B3261E` | 6.3 |

Rules:
1. **Never put white text on yellow, mint, lavender, or coral.** Use plum ink.
2. White text on hot pink only at large bold sizes (24px+, or 19px+ bold). Otherwise plum ink.
3. Color never carries meaning alone: pair it with an icon or words (heart + "Saved", check + "Done").
4. Safety and legal text (disclaimer, red-flag redirects, delete confirmation) uses plum ink on a
   plain or very light background. Pretty, but never faint (see section 7).

Suggested CSS tokens: `--pink`, `--yellow`, `--mint`, `--lavender`, `--coral`, `--bg`, `--ink`,
`--pink-deep`, `--mint-deep`, `--lavender-deep`, `--error`.

## 3. Type

| Use | Font | Notes |
|---|---|---|
| Headings, buttons, big numbers | **Fredoka** (or **Baloo 2**) | Rounded and chunky. Pick one and use it everywhere. Fredoka is the default pick |
| Body, forms, small text | **Nunito** (or **Quicksand**) | Rounded and very readable. Nunito is the default pick; Quicksand is thin at small sizes, so use it only for short labels |

- Body text is at least 16px with a 1.5 line height. Headings are big and bouncy; don't be shy.
- **Self-host the fonts** (the `@fontsource` npm packages) instead of the Google Fonts link. The
  link makes every visitor's browser contact Google, which doesn't fit the privacy promise on the
  Legal page. The look is identical.
- Exercise names, instructions, and anything medical stay in the body font at normal weight:
  readable first, cute second.

## 4. Shape, depth, and spacing

- **Big radii:** cards 24px, buttons and chips fully pill-shaped (999px), inputs 16px.
- **Soft, colored shadows**, never hard grey ones: e.g. `0 8px 24px rgba(255, 79, 163, 0.18)`.
  Hover/press lifts the shadow and moves the element up 2px.
- **Generous space:** 16px minimum padding inside cards, 24px between sections.
- **Tap targets at least 48px** tall. Buttons are fat and friendly. The site is used on phones.
- Mobile first: design the 375px screen first, then widen.
- A little color on every screen: tinted section backgrounds (lavender at 20% opacity, mint at
  15%), pill badges, rounded illustrations. White space stays warm (`--bg`), never stark white.

## 5. Components

- **Primary button:** hot pink fill, plum ink text (or large white), pill shape, soft pink shadow,
  squishes to 0.96 scale when pressed.
- **Secondary button:** white fill, 2px lavender-deep outline, plum ink text.
- **Cards** (exercises, programs, articles): white, 24px radius, soft shadow, a colored top accent
  or tinted media area. Each muscle group gets its own color so the library feels like a candy
  rack (for example: legs hot pink, arms lavender, chest coral, shoulders yellow, back mint, core
  pink-lavender mix, full body rainbow gradient). Always keep the muscle group name as text too.
- **Favorite heart:** outlined heart in deep pink; tapping fills it with a bounce plus a small
  burst of 5 to 6 mini hearts that float up and fade (about 600ms). Un-faving is a quieter
  shrink. The heart has a 48px tap area and `aria-pressed`.
- **Tabs / filters:** pill chips. The active one is hot pink; the others are white with an outline.
- **Progress:** thick rounded progress bars and rings with a mint fill; streaks as little yellow
  flames or stars.
- **Empty states:** a cheerful inline-SVG illustration and one friendly line plus one button
  ("No faves yet. Tap a heart on any move to save it here!").
- **Modals** (exercise detail): slide up as a bottom sheet on phones, 28px top radius, big pink
  close button.
- **Pictures and decorations:** build them with HTML, CSS, or inline SVG (blobs, sparkles,
  hearts, flames, confetti). Do not generate raster images.

## 6. Motion and moments of delight

Delight is the point, so it's specified, not left to chance.

| Moment | What happens |
|---|---|
| Heart tapped | Bounce + mini-heart burst (above) |
| Workout logged | Checkmark pops in with a spring; the card flashes mint |
| Weekly goal hit / program finished | **Confetti** (pink, yellow, mint, lavender, coral pieces drawn with CSS or SVG) for ~2 seconds, plus a big cheerful message |
| New streak day | Yellow star bounces next to the count |
| Quiz step complete | Progress bar springs forward |
| Buttons | Squish on press, lift on hover |
| Page change | Content fades and rises 8px (about 200ms) |

**Reduced motion is a requirement.** When `prefers-reduced-motion: reduce` is set, replace
bounces and confetti with a simple instant color change or fade. Nothing essential may depend on
animation, and nothing flashes more than 3 times a second.

## 7. Copy: warm and a little cheeky, with firm limits

Voice: a supportive best friend who's a bit of a hype woman. Short sentences. Contractions.
Light emoji are welcome (1 per message at most).

Examples:
- Empty faves: "No faves yet! Tap a heart on any move you love."
- Workout logged: "Look at you go! That's 3 workouts this week."
- Rest day: "Rest day! Your muscles do their growing while you do absolutely nothing. 💅"
- Long gap since the last workout: "Hey you! Ready when you are. Even 10 minutes counts."

**Where the cheek stops (these rules beat the vibe):**
1. **Medical, safety, and legal text is plain and warm, never jokey.** This covers the disclaimer,
   the consent step, pain and red-flag redirects ("see a professional"), the overtraining
   warning, and "Delete my data". Same typefaces and colors, calm wording, full contrast.
2. **Never shame or push.** No guilt-trips about missed days, and no jokes about food, "burning
   off" a meal, or "earning" treats. Weight-loss goals are supported, not moralized.
3. **Celebrate effort and consistency, not bodies or numbers on a scale.** The motivational stats
   ("you can lift 3 trees!") are about what the user's body can *do*.
4. **Injury-aware cheer:** when someone is rehabbing, "listening to your body is a win" beats
   "push harder". Never tell anyone to push through pain.
5. **Honest about content status.** The "Content pending expert review" tag stays visible on
   anything still marked `placeholder`. It can be styled as a cute lavender pill, but it must
   not be hidden or made hard to read.

## 8. Accessibility checklist (every page)

- Text contrast of at least 4.5:1 (large text 3:1), using the pairings in section 2.
- Visible focus ring on everything focusable: 3px deep pink outline with a 2px offset.
- Keyboard works everywhere; modals trap focus, close on Escape, and return focus to the opener.
- Real labels on form fields, `aria-pressed` on toggles, alt text on demo media.
- Reduced motion respected (section 6).
- The always-visible medical disclaimer stays in the footer of every page, full contrast.

## 9. Applying it, page by page (when we build each one)

| Page | Personality |
|---|---|
| Quiz | One question per screen, big tappable answer cards with emoji-style SVG icons, springy progress bar. The consent step is calm and clear (rule 1) |
| Dashboard | A warm greeting (no name needed; we don't collect one), today's workout as one big pink card, streak star, a fun strength fact |
| Programs | Cards with a colored goal ribbon, weekly strip of rounded day circles |
| Workout Basics hub | Lavender-tinted article cards with a friendly icon; review tag visible |
| Exercise library + faves | Candy-colored cards per muscle group, hearts, bottom-sheet detail |
| Calendar | Rounded day cells, mint check for done days, yellow star for goal days |
| Progress | Rings and thick bars, the "3 full-size trees" style fun stats, confetti on milestones |
| Settings / Legal | Same look, plainest copy (rule 1). The delete button stays clearly labeled in the error red |

## 10. Implementation notes

- One `theme.css` with the tokens above; no hard-coded colors in components.
- Fonts via `@fontsource` (self-hosted).
- Confetti and the heart burst: small CSS keyframe animations on inline SVG or `span`s, no image
  files and no heavy library needed.
- Check every new color pairing against section 2 before using it for text.
- Still to decide later: the illustration style (flat blobs vs. line doodles), and whether the
  muscle-group colors above stay as listed.
