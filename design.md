# Bee Fit: Design Direction

**Status: applied.** Every page follows this file (tokens in `frontend/src/index.css`, components in
`frontend/src/App.css`). It's the standing design direction for **every** page: quiz, dashboard, programs, basics hub, calendar, progress, faves,
and the exercise detail view. When a page is built, it follows this file; if a page needs
something this file doesn't cover, add it here first.

> This replaces the blue/white/Times New Roman defaults in `AGENTS.md` for the Bee Fit
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

**Rebranded 2026-10-25: Bee Fit, yellow / orange / green** (replacing the hot pink, mint, lavender and coral
palette). **Use these for fills, shapes, and accents.** The numbers are real WCAG contrast ratios, computed, not
guessed; they're why text gets its own colors.

| Role | Name | Hex | Token | Notes |
|---|---|---|---|---|
| Primary / brand | Bee orange | `#FF8C1A` | `--orange` | Main buttons, active tab, hearts. Dark ink text on it (6.2). Never white text |
| Highlight | Honey yellow | `#FFC61A` | `--yellow` | Stars, streaks, the bee's body, shoulders. Dark ink text on it (9.2) |
| Success | Leaf green | `#5CB85C` | `--green` | Done days, goal hit, progress. Dark ink text on it (5.8) |
| Secondary | Soft honey | `#F0C75E` | `--honey` | Borders, outlines, section accents. Dark ink text on it (9.0) |
| Warm accent | Rust orange | `#F2703A` | `--rust` | Warm pops (chest). Dark ink text on it (4.9) |
| Background | Warm cream | `#FFFBEF` | `--bg` | Page background |
| Text | Ink | `#2B2A1E` | `--ink` | All body text and headings (14.0 on the background). A warm near-black |
| Secondary text | Soft ink | `#5B5340` | `--ink-soft` | 7.4 on the background, 6.4 or more on every tint |

Light tints for backgrounds (dark ink text on all of them, 12:1 or more): `--orange-tint #FFE8CC`,
`--yellow-tint #FFF4C2`, `--green-tint #E2F4DC`, `--honey-tint #FFF5DC`, `--rust-tint #FFE5D9`.

**Text-safe deep versions.** The bright colors are too light to carry text on the cream background, so links,
icons and outlines that must be *readable* use these:

| Use | Hex | Token | Contrast |
|---|---|---|---|
| Deep orange (links, focus rings, small icons, large title text) | `#B34A00` | `--orange-deep` | 5.2 on bg; white text on it 5.4 |
| Deep green (success text) | `#276B2B` | `--green-deep` | 6.3 on bg, 5.7 on the green tint |
| Deep honey (secondary text, icons, outlines) | `#7A5700` | `--honey-deep` | 6.4 on bg |
| Error red | `#B3261E` | `--error` | 6.3; white text on it 6.5 |

Rules:
1. **Never put white text on orange, yellow, green, honey, or rust.** Use dark ink. White text goes only on
   `--orange-deep`, `--green-deep` or `--error` (badges like "Today").
2. Bright orange is never a text color, not even for big titles (2.3 on the background): use `--orange-deep`.
3. Color never carries meaning alone: pair it with an icon or words (heart + "Saved", check + "Done").
4. Safety and legal text (disclaimer, red-flag redirects, delete confirmation) uses dark ink on a
   plain or very light background. Pretty, but never faint (see section 7).

**The logo:** a bee lifting a dumbbell over its head, drawn in inline SVG (`frontend/src/components/BeeLogo.tsx`,
and the same drawing as `frontend/public/favicon.svg`), shown in the header next to "Bee Fit 🐝", on the landing
page, and doing a little lift in the loading indicator.

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
- **Soft, colored shadows**, never hard grey ones: e.g. `0 8px 24px rgba(255, 140, 26, 0.18)`.
  Hover/press lifts the shadow and moves the element up 2px.
- **Generous space:** 16px minimum padding inside cards, 24px between sections.
- **Tap targets at least 48px** tall. Buttons are fat and friendly. The site is used on phones.
- Mobile first: design the 375px screen first, then widen.
- A little color on every screen: tinted section backgrounds (the honey, green and
  orange tints), pill badges, rounded illustrations. White space stays warm (`--bg`), never stark white.

## 5. Components

- **Primary button:** bee orange fill, dark ink text, pill shape, soft orange shadow,
  squishes to 0.96 scale when pressed.
- **Secondary button:** white fill, 2px honey-deep outline, dark ink text.
- **Cards** (exercises, programs, articles): white, 24px radius, soft shadow, a colored top accent
  or tinted media area. Each muscle group gets its own color so the library feels like a candy
  rack (legs orange, arms honey, chest rust, shoulders yellow, back green, core
  green-yellow mix, full body gradient). Always keep the muscle group name as text too.
- **Favorite heart:** outlined heart in deep orange; tapping fills it with a bounce plus a small
  burst of 5 to 6 mini hearts that float up and fade (about 600ms). Un-faving is a quieter
  shrink. The heart has a 48px tap area and `aria-pressed`.
- **Tabs / filters:** pill chips. The active one is bee orange; the others are white with an outline.
- **Progress:** thick rounded progress bars and rings with a green fill; streaks as little yellow
  flames or stars.
- **Empty states:** a cheerful inline-SVG illustration and one friendly line plus one button
  ("No faves yet. Tap a heart on any move to save it here!").
- **Modals** (exercise detail): slide up as a bottom sheet on phones, 28px top radius, big orange
  close button.
- **Pictures and decorations:** build them with HTML, CSS, or inline SVG (blobs, sparkles,
  hearts, flames, confetti). Do not generate raster images.

## 6. Motion and moments of delight

Delight is the point, so it's specified, not left to chance.

| Moment | What happens |
|---|---|
| Heart tapped | Bounce + mini-heart burst (above) |
| Workout logged | Checkmark pops in with a spring; the card flashes green |
| Weekly goal hit / program finished | **Confetti** (orange, yellow, green, honey, rust pieces drawn with CSS or SVG) for ~2 seconds, plus a big cheerful message |
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
   anything still marked `placeholder`. It can be styled as a cute honey pill, but it must
   not be hidden or made hard to read.

## 8. Accessibility checklist (every page)

- Text contrast of at least 4.5:1 (large text 3:1), using the pairings in section 2.
- Visible focus ring on everything focusable: 3px deep orange outline with a 2px offset.
- Keyboard works everywhere; modals trap focus, close on Escape, and return focus to the opener.
- Real labels on form fields, `aria-pressed` on toggles, alt text on demo media.
- Reduced motion respected (section 6).
- The always-visible medical disclaimer stays in the footer of every page, full contrast.

## 9. Applying it, page by page (when we build each one)

| Page | Personality |
|---|---|
| Quiz | One question per screen, big tappable answer cards with emoji-style SVG icons, springy progress bar. The consent step is calm and clear (rule 1) |
| Dashboard | A greeting, then exactly two cards (2026-10-25): "Plan for today" (today's day from the calendar) and "Your streak" (current and longest streak, active days, day-streak badges). Code only, no AI |
| Programs | Cards with a colored goal ribbon, weekly strip of rounded day circles |
| Workout Basics hub | Honey-tinted article cards with a friendly icon; review tag visible |
| Exercise library + faves | Candy-colored cards per muscle group, hearts, bottom-sheet detail. Filters read like the quiz (its own question component): what to work on (upper body, lower body, core / mobility) and areas to avoid because of an injury |
| Calendar | Rounded day cells, green check for done days, yellow star for goal days |
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
