// The card before the quiz: a short audio message from Summer, Bee Fit's personal trainer. Optional: "Continue to quiz"
// works right away, whether or not the audio was played. The audio file is frontend/public/audio/summer-quiz-intro.mp3.
import { useRef, useState } from 'react'
import BeeLogo from './BeeLogo'

export const SUMMER_AUDIO = '/audio/summer-quiz-intro.mp3'

export default function SummerIntro({ onContinue }: { onContinue: () => void }) {
  const audio = useRef<HTMLAudioElement>(null)
  const [playing, setPlaying] = useState(false)
  const [failed, setFailed] = useState(false)

  // The bee is the big play / pause button; the standard controls underneath do the same, plus seeking and volume.
  function toggle() {
    const a = audio.current
    if (!a) return
    if (a.paused) a.play().catch(() => setFailed(true))
    else a.pause()
  }

  return (
    <section className="quiz-step summer-intro" aria-labelledby="summer-intro-title">
      <h3 id="summer-intro-title">Before you take the quiz, a quick word from your personal trainer, Summer...</h3>
      <div className="summer-player">
        <button
          type="button"
          className={playing ? 'summer-bee playing' : 'summer-bee'}
          onClick={toggle}
          aria-label={playing ? "Pause Summer's message" : "Play Summer's message"}
          aria-pressed={playing}
        >
          <BeeLogo size={96} holding="microphone" />
          <span className="summer-bee-badge" aria-hidden="true">
            {playing ? '❚❚' : '▶'}
          </span>
        </button>
        <div className="summer-controls">
          <p className="hint">{playing ? 'Playing… tap the bee to pause.' : 'Tap the bee to play.'}</p>
          <audio
            ref={audio}
            src={SUMMER_AUDIO}
            controls
            preload="metadata"
            onPlay={() => setPlaying(true)}
            onPause={() => setPlaying(false)}
            onEnded={() => setPlaying(false)}
            onError={() => setFailed(true)}
          >
            Your browser can't play this audio.
          </audio>
          {failed && <p className="error">The message couldn't play right now. You can go straight to the quiz.</p>}
        </div>
      </div>
      <div className="button-row">
        <button type="button" className="btn" onClick={onContinue}>
          Continue to quiz
        </button>
      </div>
    </section>
  )
}
