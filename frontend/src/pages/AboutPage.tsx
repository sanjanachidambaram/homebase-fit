// About: Sanjana's essay, verbatim (her voice, her caps, her typos; please don't "clean it up"), with her own
// "HUGE disclaimer" paragraph styled as the page's disclaimer box. The team photos come first, by design; the
// site-wide footer disclaimer and /legal carry the full medical disclaimer regardless of this page's layout.
// The live data and sources section lives on its own page now: /about/data (AboutDataPage.tsx).
import { useState } from 'react'
import Link from '../components/Link'

const TEAM_PHOTOS = '/content/images/team'
const PHOTO_EXTS = ['jpg', 'png', 'webp']

// Photo files go in content/images/team/ (see its README): <file>.jpg, .png or .webp.
const TEAM: { file: string; caption: string; name: string }[] = [
  { file: 'sanjana', name: 'Sanjana', caption: 'Sanjana — creator' },
  { file: 'summer', name: 'Summer', caption: 'Summer — Personal Trainer & Pilates Instructor' },
  { file: 'fauzia', name: 'Fauzia', caption: 'Fauzia — Physical Therapist' },
  { file: 'sister', name: 'My sister', caption: 'My sister — OB-GYN' },
]

/** Tries name.jpg, .png, .webp; shows a drawn placeholder avatar until one exists (never a broken image). */
function TeamPhoto({ file, name }: { file: string; name: string }) {
  const [attempt, setAttempt] = useState(0)
  if (attempt >= PHOTO_EXTS.length) {
    return (
      <div className="team-avatar team-avatar-empty" role="img" aria-label={`Photo of ${name} coming soon`}>
        <svg viewBox="0 0 64 64" aria-hidden="true">
          <circle cx="32" cy="24" r="12" />
          <path d="M10 58c2-13 11-20 22-20s20 7 22 20z" />
        </svg>
      </div>
    )
  }
  return (
    <img
      className="team-avatar"
      src={`${TEAM_PHOTOS}/${file}.${PHOTO_EXTS[attempt]}`}
      alt={`Photo of ${name}`}
      onError={() => setAttempt((a) => a + 1)}
    />
  )
}

export default function AboutPage() {
  return (
    <article className="about">
      <h2 className="page-title">About Bee Fit</h2>

      <section className="about-section about-team" aria-label="The team">
        <ul className="team-grid">
          {TEAM.map((t) => (
            <li key={t.file} className="team-card">
              <TeamPhoto file={t.file} name={t.name} />
              <strong className="team-name">{t.caption}</strong>
            </li>
          ))}
        </ul>
      </section>


      <div className="about-essay">
        <p>
          Omg!! Guys, I literally vibe coded this entire site for my Yale SOM AI Foundations class. I'm shook to my
          core.
        </p>

        <p>
          So this was our final project for the class, and – also, hi, I'm Sanjana, first-year MBA at Yale SOM (and,
          must add, ardent Buckeye as an Ohio State undergrad) – and I've been thinking about an idea like this for a
          while. Come hear my grievances about working out:
        </p>

        <ul>
          <li>I like working out. I feel good working out.</li>
          <li>
            What I don't like about working out is the MENTAL LOAD. Like. You're telling me I have to not only motivate
            myself to leave my apartment and go to the gym and wear cute workout clothes – and I don't think my workout
            clothes are that cute so sometimes that's a whole battle and also sometimes I don't want to leave the house
            because I literally cannot deal with seeing a single other soul after hours of #networking – but first I
            have to eat a snack and debate how starving I am after and if I have time to cook and then if I can't get
            to the gym in time then I can't cook – and it's just like, okay, on top of all of this, I have to THINK
            ABOUT MY WORKOUT? I can't. Literally cannot.
          </li>
          <li>
            I suppose they all say consistency is key? But you better not expect me to be writing down my workouts. In
            the economy????
          </li>
          <li>
            I need flexibility. I really need to be able to have some at-home workouts and some where I actually go to
            the gym and use machines. I need short times sometimes and longer times others. And I need something to
            hold the mental weight of my working out.
          </li>
          <li>
            Also, at the unripe age of 28, my body hurts. My back hurts and the other day I did my old workout routine
            from like 10 years ago and my back hurt moreeee. I've been in PT, graduated, and yet, it's still hard to
            actually find a workout app that works for your body.
          </li>
          <li>
            I'm also broke now, and these pilates studios will deadass look you in the eye and tell you that their
            classes are $55/session. In this economy????
          </li>
          <li>
            Also, I sort of only want to play sports. Like, actual things that are fun. I joined a soccer league last
            year, and it was so fun (we lost every game), and after every game my entire team was unable to move. So,
            like, to do the fun life things, you have to strength train.
          </li>
          <li>
            And, guys, I begged my women's health friends to all tell me differently but their consensus was
            unequivocal: women, especially women over 30, simply must strength train. I'm sorry. I wish it were
            different, too.
          </li>
          <li>
            Okay, sorry, I had to ask the AI to strip out all of my stream of consciousness and my personality for the
            rest of this app so it's not all this lengthy. Tl;dr: I needed a free workout app that allowed me to meet my
            goals while taking into consideration my injuries, time constraints, home workout materials and – most
            critically – once I set it, would just push me to stick to it.
          </li>
        </ul>

        <p>So here we are! That's my app.</p>

        <p>
          I feel super not qualified to actually give advice on fitness. Thankfully, my best friend/platonic life
          partner (Summer) and her mom (Fauzia) are both in the industry – Summer is a personal trainer and pilates
          instructor, and Fauzia is a physical therapist. My sister (can you guess younger or older??? lol) is a
          literal OB/GYN (talk about one kid with no skills and one kid who's overskilled, right). I've enlisted their
          help to make this app really good, and the functionality features are described below.
        </p>

        {/* Her own disclaimer, in her words, gets the site's disclaimer-box treatment (design.md 7 rule 1). */}
        <section className="class-disclaimer" role="note" aria-label="Disclaimer">
          <p>
            HUGE disclaimer. THIS IS A CLASS PROJECT. Think about your class projects. There are things here that aren't
            fully reviewed and none of this has been verified by a legit, non-vibe-coding programmer. There are flaws,
            it will be buggy, and the health data is IN PROGRESS. If this somehow takes off, then sure, I'll make sure
            we actually work through all health verifications, injury verifications, etc. But guys, it's 40% of my
            class grade at a program that doesn't do grade disclosures. So I'm proud of my work, but to be so real,
            it's not perfect.
          </p>
          <Link to="/legal">Read the full medical disclaimer, privacy and legal page</Link>
        </section>

        <p>
          Okay, that's about it. Email me with whatever if you guys have thoughts or want any changes. If they're easy
          enough, I'll make them. If they're hard, Venmo me. ;)
        </p>
      </div>

      <p className="about-data-link">
        <Link to="/about/data">Curious where our data comes from? See the live numbers and every source we use →</Link>
      </p>

    </article>
  )
}
