# Intro video

Drop the intro podcast/Zoom clip in this folder as:

- `intro_podcast.mp4` (preferred), or
- `intro_podcast.mov`

The home page will embed whichever one is here.

## Format for web embedding

- **Container/codec:** MP4 with H.264 video and AAC audio plays in every browser. `.mov` works in Safari but not reliably in Chrome or Firefox, so convert it to MP4 if you can.
- **Resolution:** 720p (1280x720) is plenty for a talking-head clip; 1080p at most.
- **Size:** keep it **under 50 MB**. GitHub rejects any file over 100 MB, and big files load slowly on phones.
- **Length:** a 1 to 3 minute clip is ideal for an intro.
- **Fast start:** export with "optimize for web" / "fast start" so playback begins before the whole file downloads.

To shrink and convert a Zoom recording with ffmpeg:

```bash
ffmpeg -i zoom_recording.mp4 -vf scale=-2:720 -c:v libx264 -crf 28 -preset slow -c:a aac -b:a 128k -movflags +faststart intro_podcast.mp4
```

If the clip can't get under 50 MB, upload it as an unlisted YouTube or Vimeo video and we'll embed that link instead.
